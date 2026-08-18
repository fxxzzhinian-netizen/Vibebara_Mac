"""WebSocket 强制鉴权验证（方案 B M2）。

不起真实服务：用假 WebSocket + monkeypatch 路由依赖，直接驱动 WS 端点函数，
断言鉴权分支：
- 项目级 /ws/project/{pid}（强制）：缺 token / 错 token / user_id 不一致 → close 4001；
  非团队成员 → close 4003；合法且为成员 → connect 放行。

注：会话级 /ws/{sid} 编排通道已随 session/adapter 子系统退役，相关用例已移除。

可直接运行：`python -m tests.test_ws_auth`（无需 pytest，亦兼容 pytest）。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import WebSocketDisconnect

from app.websocket import routes as r


class FakeWS:
    """记录 accept/close 调用、收到一条消息后立即断开的假 WebSocket。"""

    def __init__(self):
        self.closed_code = None
        self.closed_reason = None
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def close(self, code=1000, reason=""):
        self.closed_code = code
        self.closed_reason = reason

    async def receive_text(self):
        raise WebSocketDisconnect()

    async def send_json(self, *a, **k):
        return None


class _ProjMgr:
    def __init__(self):
        self.connected = []
        self.disconnected = []
        self._online = {}

    async def connect(self, ws, project_id, user_id):
        self.connected.append((project_id, user_id))

    async def disconnect(self, project_id, user_id, _websocket=None):
        self.disconnected.append((project_id, user_id))

    def get_online_users(self, project_id):
        return []

    async def on_skill_event(self, event):
        return None


class _FakeSync:
    @staticmethod
    def subscribe(*a, **k):
        return None

    @staticmethod
    def unsubscribe(*a, **k):
        return None


def _patch_project(monkey_token_user, team_id, is_member):
    proj = _ProjMgr()

    async def _verify(tok):
        return monkey_token_user

    r.verify_credential = _verify

    async def _get_team(pid):
        return team_id

    async def _is_member(tid, uid):
        return is_member

    r.project_service.get_project_team_id = _get_team
    r.team_service.is_team_member = _is_member
    r.project_ws_manager = proj
    r.SkillSyncService = _FakeSync
    return proj


# ----------------------------- 项目级 WS -----------------------------

def test_project_ws_missing_token_rejected():
    proj = _patch_project(monkey_token_user=None, team_id="t1", is_member=True)
    ws = FakeWS()
    asyncio.run(r.project_websocket_endpoint(ws, "p1", user_id="u1", token=""))
    assert ws.closed_code == 4001
    assert proj.connected == []


def test_project_ws_invalid_token_rejected():
    proj = _patch_project(monkey_token_user=None, team_id="t1", is_member=True)
    ws = FakeWS()
    asyncio.run(r.project_websocket_endpoint(ws, "p1", user_id="u1", token="bad"))
    assert ws.closed_code == 4001
    assert proj.connected == []


def test_project_ws_user_id_mismatch_rejected():
    proj = _patch_project(monkey_token_user="u1", team_id="t1", is_member=True)
    ws = FakeWS()
    # token 解析出 u1，但连接声明 user_id=u2 → 防伪冒拒绝
    asyncio.run(r.project_websocket_endpoint(ws, "p1", user_id="u2", token="ok"))
    assert ws.closed_code == 4001
    assert proj.connected == []


def test_project_ws_non_member_forbidden():
    proj = _patch_project(monkey_token_user="u1", team_id="t1", is_member=False)
    ws = FakeWS()
    asyncio.run(r.project_websocket_endpoint(ws, "p1", user_id="u1", token="ok"))
    assert ws.closed_code == 4003
    assert proj.connected == []


def test_project_ws_valid_member_allowed():
    proj = _patch_project(monkey_token_user="u1", team_id="t1", is_member=True)
    ws = FakeWS()
    asyncio.run(r.project_websocket_endpoint(ws, "p1", user_id="u1", token="ok"))
    assert ws.closed_code is None
    assert proj.connected == [("p1", "u1")]
    assert proj.disconnected == [("p1", "u1")]


def test_project_ws_missing_team_forbidden():
    proj = _patch_project(monkey_token_user="u1", team_id=None, is_member=True)
    ws = FakeWS()
    asyncio.run(r.project_websocket_endpoint(ws, "p-ghost", user_id="u1", token="ok"))
    assert ws.closed_code == 4003
    assert proj.connected == []


def _run_all():
    tests = [
        test_project_ws_missing_token_rejected,
        test_project_ws_invalid_token_rejected,
        test_project_ws_user_id_mismatch_rejected,
        test_project_ws_non_member_forbidden,
        test_project_ws_valid_member_allowed,
        test_project_ws_missing_team_forbidden,
    ]
    for t in tests:
        t()
        print(f"  PASS  {t.__name__}")
    print(f"\nAll {len(tests)} ws-auth tests passed.")


if __name__ == "__main__":
    _run_all()

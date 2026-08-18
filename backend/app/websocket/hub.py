from fastapi import WebSocket
from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)


# ======================================================================
# ProjectConnectionManager — 项目级 WebSocket 通道（Skill 实时同步）
# ======================================================================

class ProjectConnectionManager:
    """
    管理项目级 WebSocket 连接。

    当 SkillSyncService 广播 Skill 变更事件时，
    本 manager 将事件推送给该项目通道的所有在线成员。
    """

    def __init__(self):
        # project_id -> {user_id: WebSocket}
        self._connections: Dict[str, Dict[str, WebSocket]] = {}

    async def connect(
        self, websocket: WebSocket, project_id: str, user_id: str
    ):
        await websocket.accept()
        previous = self._connections.get(project_id, {}).get(user_id)
        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=4001, reason="signed in elsewhere")
            except Exception:
                pass
        self._connections.setdefault(project_id, {})[user_id] = websocket

        await self._broadcast(
            project_id,
            {
                "type": "project.member.joined",
                "user_id": user_id,
                "project_id": project_id,
            },
            exclude_user=user_id,
        )
        logger.info(
            f"[ProjectWS] 用户 {user_id} 加入项目通道 {project_id}"
        )

    async def disconnect(
        self, project_id: str, user_id: str, websocket: WebSocket | None = None
    ):
        conns = self._connections.get(project_id, {})
        if websocket is None or conns.get(user_id) is websocket:
            conns.pop(user_id, None)
        if not conns:
            self._connections.pop(project_id, None)

        await self._broadcast(
            project_id,
            {
                "type": "project.member.left",
                "user_id": user_id,
                "project_id": project_id,
            },
        )
        logger.info(
            f"[ProjectWS] 用户 {user_id} 离开项目通道 {project_id}"
        )

    async def on_skill_event(self, event: Dict[str, Any]) -> None:
        """SkillSyncService 的事件回调入口"""
        project_id = event.get("project_id")
        if not project_id:
            return
        await self._broadcast(project_id, event)

    async def _broadcast(
        self,
        project_id: str,
        message: dict,
        exclude_user: str = None,
    ):
        conns = self._connections.get(project_id, {})
        dead: List[str] = []
        for uid, ws in conns.items():
            if uid == exclude_user:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(uid)
        for uid in dead:
            conns.pop(uid, None)

    def get_online_users(self, project_id: str) -> List[str]:
        return list(self._connections.get(project_id, {}).keys())

    async def close_user(
        self,
        user_id: str,
        code: int = 4001,
        reason: str = "signed in elsewhere",
    ) -> None:
        for project_id, conns in list(self._connections.items()):
            ws = conns.pop(user_id, None)
            if ws is not None:
                try:
                    await ws.close(code=code, reason=reason)
                except Exception:
                    pass
            if not conns:
                self._connections.pop(project_id, None)


# ======================================================================
# TeamConnectionManager — 团队级 WebSocket 通道（结构变更实时同步）
# ======================================================================

class TeamConnectionManager:
    """
    管理团队级 WebSocket 连接。

    当 TeamSyncService 广播团队结构事件（项目增删、团队 Skill 仓库增减、
    成员加入）时，本 manager 将事件推送给该团队通道的所有在线成员，
    使其项目列表 / 团队 Skill 仓库 / 成员列表无需手动刷新即可更新。
    """

    def __init__(self):
        # team_id -> {user_id: WebSocket}
        self._connections: Dict[str, Dict[str, WebSocket]] = {}

    async def connect(self, websocket: WebSocket, team_id: str, user_id: str):
        await websocket.accept()
        previous = self._connections.get(team_id, {}).get(user_id)
        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=4001, reason="signed in elsewhere")
            except Exception:
                pass
        self._connections.setdefault(team_id, {})[user_id] = websocket
        logger.info(f"[TeamWS] 用户 {user_id} 加入团队通道 {team_id}")

    async def disconnect(
        self, team_id: str, user_id: str, websocket: WebSocket | None = None
    ):
        conns = self._connections.get(team_id, {})
        if websocket is None or conns.get(user_id) is websocket:
            conns.pop(user_id, None)
        if not conns:
            self._connections.pop(team_id, None)
        logger.info(f"[TeamWS] 用户 {user_id} 离开团队通道 {team_id}")

    async def on_team_event(self, event: Dict[str, Any]) -> None:
        """TeamSyncService 的事件回调入口"""
        team_id = event.get("team_id")
        if not team_id:
            return
        await self._broadcast(team_id, event)

    async def _broadcast(
        self,
        team_id: str,
        message: dict,
        exclude_user: str = None,
    ):
        conns = self._connections.get(team_id, {})
        dead: List[str] = []
        for uid, ws in conns.items():
            if uid == exclude_user:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(uid)
        for uid in dead:
            conns.pop(uid, None)

    def get_online_users(self, team_id: str) -> List[str]:
        return list(self._connections.get(team_id, {}).keys())

    async def close_user(
        self,
        user_id: str,
        code: int = 4001,
        reason: str = "signed in elsewhere",
    ) -> None:
        for team_id, conns in list(self._connections.items()):
            ws = conns.pop(user_id, None)
            if ws is not None:
                try:
                    await ws.close(code=code, reason=reason)
                except Exception:
                    pass
            if not conns:
                self._connections.pop(team_id, None)


project_ws_manager = ProjectConnectionManager()
team_ws_manager = TeamConnectionManager()


async def close_user_connections(
    user_id: str,
    code: int = 4001,
    reason: str = "signed in elsewhere",
) -> None:
    await project_ws_manager.close_user(user_id, code=code, reason=reason)
    await team_ws_manager.close_user(user_id, code=code, reason=reason)

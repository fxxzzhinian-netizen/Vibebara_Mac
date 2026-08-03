"""
TeamSyncService — 团队级实时同步事件总线

职责：
  团队范围内的「结构性变更」（新建/删除项目、团队 Skill 仓库增减、成员加入）
  通过内存事件总线广播到团队级 WebSocket 通道（/ws/team/{team_id}），
  让在线成员无需手动刷新即可看到项目列表 / 团队 Skill 仓库 / 成员的更新。

与 SkillSyncService 的分工：
  - SkillSyncService：项目内 **某个 Skill 内容** 的版本/动态（/ws/project/{project_id}）。
  - TeamSyncService：团队 **结构** 变更（项目、团队仓库、成员），与具体 Skill 内容无关。

设计沿用 SkillSyncService 的「类级监听器 + 回调」模式：
  WebSocket Hub 在连接建立时把团队通道的 on_team_event 注册进来，
  服务层（project_service / native_skill_store / team_service）在写操作提交后调用
  emit_* 广播事件。本服务不反向 import hub，避免循环依赖。
"""

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional

from app.core.database import async_session_factory
from app.models.user import User

logger = logging.getLogger(__name__)

# 事件回调类型: async def callback(event: dict) -> None
_EventCallback = Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]


class TeamSyncService:
    """单例，管理团队结构变更事件的订阅与分发。"""

    _listeners: Dict[str, List[_EventCallback]] = {}

    # ------------------------------------------------------------------
    # 事件订阅（供 WebSocket Hub 注册回调）
    # ------------------------------------------------------------------

    @classmethod
    def subscribe(cls, team_id: str, callback: _EventCallback) -> None:
        # 幂等：团队通道用的是 team_ws_manager 单例的同一个绑定方法，多个成员连接
        # 同一团队时会重复 subscribe。用 == 去重（绑定方法按 __self__/__func__ 比较
        # 相等），保证每个团队同一时刻只有一个监听器，避免事件被重复广播。
        cbs = cls._listeners.setdefault(team_id, [])
        if callback not in cbs:
            cbs.append(callback)

    @classmethod
    def unsubscribe(cls, team_id: str, callback: _EventCallback) -> None:
        # 用 != 而非 is not：绑定方法每次访问是新对象，identity 比较会漏删导致泄漏。
        cbs = cls._listeners.get(team_id, [])
        cls._listeners[team_id] = [cb for cb in cbs if cb != callback]

    # ------------------------------------------------------------------
    # 对外：各服务在写操作提交后调用的便捷广播方法
    # ------------------------------------------------------------------

    @classmethod
    async def emit_project_created(
        cls, team_id: str, project: Dict[str, Any], user_id: str
    ) -> None:
        await cls._emit(
            team_id,
            "project.created",
            user_id,
            {"project_id": project.get("id"), "project": project},
        )

    @classmethod
    async def emit_project_updated(
        cls, team_id: str, project: Dict[str, Any], user_id: str
    ) -> None:
        await cls._emit(
            team_id,
            "project.updated",
            user_id,
            {"project_id": project.get("id"), "project": project},
        )

    @classmethod
    async def emit_project_deleted(
        cls, team_id: str, project_id: str, user_id: str
    ) -> None:
        await cls._emit(
            team_id, "project.deleted", user_id, {"project_id": project_id}
        )

    @classmethod
    async def emit_team_skill_added(
        cls, team_id: str, skill: Dict[str, Any], user_id: str
    ) -> None:
        await cls._emit(
            team_id,
            "team_skill.added",
            user_id,
            {
                "skill_id": skill.get("id"),
                "skill_display_name": skill.get("display_name") or skill.get("id"),
            },
        )

    @classmethod
    async def emit_member_joined(cls, team_id: str, user_id: str) -> None:
        await cls._emit(team_id, "team.member.joined", user_id, {})

    @classmethod
    async def emit_team_deleted(cls, team_id: str, user_id: str) -> None:
        # 团队被 owner 删除：在线成员据此清空当前团队视图并刷新团队列表。
        await cls._emit(team_id, "team.deleted", user_id, {})

    @classmethod
    def clear_team(cls, team_id: str) -> None:
        # 团队删除后丢弃其监听器，避免内存泄漏（WebSocket 侧重连会被鉴权拒绝）。
        cls._listeners.pop(team_id, None)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @classmethod
    async def _emit(
        cls,
        team_id: str,
        event_type: str,
        user_id: str,
        payload: Dict[str, Any],
    ) -> None:
        if not team_id:
            return
        # 没有任何在线订阅者时，省掉用户名查询与广播开销。
        if not cls._listeners.get(team_id):
            return

        event = {
            "type": event_type,
            "team_id": team_id,
            "user_id": user_id,
            "user_display_name": await cls._get_user_display_name(user_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        await cls._broadcast(team_id, event)
        logger.info(
            "[TeamSync] %s team='%s' by='%s'", event_type, team_id, user_id
        )

    @classmethod
    async def _get_user_display_name(cls, user_id: Optional[str]) -> str:
        if not user_id:
            return ""
        if user_id == "system":
            return "系统自动检测"
        async with async_session_factory() as session:
            user = await session.get(User, user_id)
            if user:
                return user.display_name or user.username
        return user_id

    @classmethod
    async def _broadcast(cls, team_id: str, event: Dict[str, Any]) -> None:
        callbacks = cls._listeners.get(team_id, [])
        dead: List[_EventCallback] = []
        for cb in callbacks:
            try:
                await cb(event)
            except Exception as e:
                logger.warning(f"[TeamSync] 广播回调异常: {e}")
                dead.append(cb)
        for cb in dead:
            cls._listeners[team_id] = [
                c for c in cls._listeners.get(team_id, []) if c is not cb
            ]

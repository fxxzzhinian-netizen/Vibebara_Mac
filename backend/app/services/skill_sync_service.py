"""
SkillSyncService — Skill 实时同步核心

职责：
  1. 当 NativeSkillStore（抽象层）发生 CRUD 操作时，更新 project_skills 的
     version / content_hash，并写入 skill_change_log
  2. 通过内存事件总线将变更通知广播到项目级 WebSocket 通道

所有 Skill 内容的读写仍由 NativeSkillStore 完成，
本服务只处理同步元数据和事件广播。
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.project import ProjectSkill
from app.models.skill_change_log import SkillChangeLog
from app.models.skill_package import PersonalSkill, TeamSkill
from app.models.user import User

logger = logging.getLogger(__name__)

# 事件回调类型: async def callback(event: dict) -> None
_EventCallback = Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]


class SkillSyncService:
    """单例，管理 Skill 变更的版本追踪和事件分发。"""

    _listeners: Dict[str, List[_EventCallback]] = {}

    # ------------------------------------------------------------------
    # 事件订阅（供 WebSocket Hub 注册回调）
    # ------------------------------------------------------------------

    @classmethod
    def subscribe(cls, project_id: str, callback: _EventCallback) -> None:
        cls._listeners.setdefault(project_id, []).append(callback)

    @classmethod
    def unsubscribe(cls, project_id: str, callback: _EventCallback) -> None:
        cbs = cls._listeners.get(project_id, [])
        cls._listeners[project_id] = [cb for cb in cbs if cb is not callback]

    # ------------------------------------------------------------------
    # 核心：Skill 变更通知（由 NativeSkillStore 调用）
    # ------------------------------------------------------------------

    @classmethod
    async def on_skill_changed(
        cls,
        skill_id: str,
        user_id: str,
        action: str,
        diff_summary: str = "",
        change_items: Optional[List[Dict[str, Any]]] = None,
        base_hash: str = "",
        new_hash: str = "",
    ) -> None:
        """
        Skill 抽象层完成写操作后调用此方法。

        1. 查找该 skill 所属的所有 project（通过 project_skills 或 skill_packages.project_id）
        2. 递增 project_skills.version，更新 content_hash
        3. 写入 skill_change_log（含逐项改动 change_items / 摘要 diff_summary）
        4. 广播事件到项目通道（携带 change_items / diff_summary，供前端动态详情展示）
        """
        change_items = change_items or []
        change_items_json = json.dumps(change_items, ensure_ascii=False)
        project_ids = await cls._find_projects_for_skill(skill_id)
        if not project_ids:
            logger.debug(
                f"[SkillSync] skill '{skill_id}' 未关联到任何项目，跳过同步"
            )
            return

        events: List[Dict[str, Any]] = []

        async with async_session_factory() as session:
            result = await session.execute(
                select(ProjectSkill).where(
                    ProjectSkill.skill_id == skill_id,
                )
            )
            project_skills = {
                ps.project_id: ps for ps in result.scalars().all()
            }

            pkg = (
                await session.get(PersonalSkill, skill_id)
                or await session.get(TeamSkill, skill_id)
            )
            latest_hash = cls._compute_hash(pkg.store_path) if pkg and pkg.store_path else ""

            for project_id in project_ids:
                ps = project_skills.get(project_id)
                new_version = 0
                content_hash = latest_hash

                if ps:
                    ps.version += 1
                    ps.last_modified_by = user_id
                    ps.content_hash = latest_hash
                    new_version = ps.version
                    content_hash = ps.content_hash

                    if action == "deleted":
                        await session.delete(ps)

                log = SkillChangeLog(
                    project_id=project_id,
                    skill_id=skill_id,
                    user_id=user_id,
                    action=action,
                    version=new_version,
                    diff_summary=diff_summary,
                    change_items=change_items_json,
                    base_hash=base_hash,
                    new_hash=new_hash or latest_hash,
                )
                session.add(log)
                events.append({
                    "project_id": project_id,
                    "version": new_version,
                    "content_hash": content_hash,
                })

            await session.commit()

        user_display_name = await cls._get_user_display_name(user_id)
        skill_display_name = await cls._get_skill_display_name(skill_id)

        timestamp = datetime.now(timezone.utc).isoformat()
        for event_meta in events:
            event = {
                "type": f"skill.{action}",
                "project_id": event_meta["project_id"],
                "skill_id": skill_id,
                "version": event_meta["version"],
                "content_hash": event_meta["content_hash"],
                "user_id": user_id,
                "user_display_name": user_display_name,
                "skill_display_name": skill_display_name,
                "change_items": change_items,
                "diff_summary": diff_summary,
                "timestamp": timestamp,
            }

            await cls._broadcast(event_meta["project_id"], event)
            logger.info(
                "[SkillSync] %s skill='%s' project='%s' v=%s",
                action,
                skill_id,
                event_meta["project_id"],
                event_meta["version"],
            )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @classmethod
    async def _get_user_display_name(cls, user_id: str) -> str:
        if user_id == "system":
            return "系统自动检测"
        async with async_session_factory() as session:
            user = await session.get(User, user_id)
            if user:
                return user.display_name or user.username
        return user_id

    @classmethod
    async def _get_skill_display_name(cls, skill_id: str) -> str:
        async with async_session_factory() as session:
            pkg = (
                await session.get(PersonalSkill, skill_id)
                or await session.get(TeamSkill, skill_id)
            )
            if pkg:
                return pkg.display_name or pkg.name
        return skill_id

    @classmethod
    async def _find_projects_for_skill(cls, skill_id: str) -> List[str]:
        async with async_session_factory() as session:
            result = await session.execute(
                select(ProjectSkill.project_id).where(
                    ProjectSkill.skill_id == skill_id
                )
            )
            project_ids = list(result.scalars().all())

            # 仅团队 Skill 可能带遗留 project_id；个人 Skill 不参与项目。
            pkg = await session.get(TeamSkill, skill_id)
            if pkg and pkg.project_id:
                project_ids.append(pkg.project_id)

            return list(dict.fromkeys(project_ids))

    @staticmethod
    def _compute_hash(store_path: str) -> str:
        p = Path(store_path)
        if not p.exists():
            return ""

        digest = hashlib.sha256()
        has_files = False
        for file_path in sorted(x for x in p.rglob("*") if x.is_file()):
            rel = file_path.relative_to(p).as_posix()
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(file_path.read_bytes())
            digest.update(b"\0")
            has_files = True

        return digest.hexdigest() if has_files else ""

    @classmethod
    async def _broadcast(cls, project_id: str, event: Dict[str, Any]) -> None:
        callbacks = cls._listeners.get(project_id, [])
        dead: List[_EventCallback] = []
        for cb in callbacks:
            try:
                await cb(event)
            except Exception as e:
                logger.warning(f"[SkillSync] 广播回调异常: {e}")
                dead.append(cb)
        for cb in dead:
            cls._listeners[project_id] = [
                c for c in cls._listeners.get(project_id, []) if c is not cb
            ]

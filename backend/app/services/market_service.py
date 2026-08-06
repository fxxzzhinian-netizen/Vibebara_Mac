"""SKILL 市场服务 — 发布快照 / 审核 / 获取 / 介绍页。

发布即把源 Skill（个人或团队）当时内容逐对象复制到 `skills/market/{id}/`，并在
`market_listings` 表记录元数据快照 + 溯源 + 「介绍页」信息（取自 Skill 自身 config.intro，
在编辑页填写，可由 AI 辅助生成），**不与源同步**。审核通过后全体可见，用户「获取」时再把
市场快照复制一份到自己的个人仓库。

复用 NativeSkillStore 的对象存储助手（前缀解析 / 读写 config / copy_prefix）。
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_factory
from app.models.market_listing import MarketListing
from app.models.market_listing_version import MarketListingVersion
from app.models.skill_package import PersonalSkill, TeamSkill
from app.models.user import User
from app.services import auth_service, team_service
from app.services.native_skill_store import NativeSkillStore

logger = logging.getLogger(__name__)

MARKET_ROOT = "skills/market"
MARKET_VERSIONS_ROOT = "skills/market_versions"


def _market_prefix(market_id: str) -> str:
    return f"{MARKET_ROOT}/{market_id}"


def _market_version_prefix(listing_id: str, version_id: str) -> str:
    return f"{MARKET_VERSIONS_ROOT}/{listing_id}/{version_id}"


def _version_row_to_dict(row: MarketListingVersion) -> Dict[str, Any]:
    return {
        "id": row.id,
        "listing_id": row.listing_id,
        "seq": row.seq,
        "display_name": row.display_name,
        "description": row.description,
        "short_description": row.short_description,
        "version": row.version,
        "tags": list(row.tags or []),
        "content_hash": row.content_hash,
        "intro_title": row.intro_title or "",
        "intro_author": row.intro_author or "",
        "intro_category": row.intro_category or "",
        "intro_md": row.intro_md or "",
        "status": row.status,
        "published_by": row.published_by,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _row_to_dict(row: MarketListing, publisher_name: str = "") -> Dict[str, Any]:
    return {
        "id": row.id,
        "display_name": row.display_name,
        "description": row.description,
        "short_description": row.short_description,
        "version": row.version,
        "tags": list(row.tags or []),
        "content_hash": row.content_hash,
        "intro_title": row.intro_title or "",
        "intro_author": row.intro_author or "",
        "intro_category": row.intro_category or "",
        "intro_md": row.intro_md or "",
        "source_scope": row.source_scope,
        "source_skill_id": row.source_skill_id,
        "source_team_id": row.source_team_id,
        "publisher_id": row.publisher_id,
        "publisher_name": publisher_name,
        "status": row.status,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "review_note": row.review_note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _publisher_names(rows: List[MarketListing]) -> Dict[str, str]:
    ids = {r.publisher_id for r in rows if r.publisher_id}
    if not ids:
        return {}
    async with async_session_factory() as session:
        users = (
            await session.execute(select(User).where(User.id.in_(ids)))
        ).scalars().all()
    return {u.id: (u.display_name or u.username) for u in users}


async def _unique_personal_name(base: str, user_id: str) -> str:
    """为当前用户生成未占用的自然名；不同用户可使用相同名称。"""
    base = NativeSkillStore._strip_team_suffix(base) or base
    async with async_session_factory() as session:
        names = set(
            (
                await session.execute(
                    select(PersonalSkill.name).where(
                        PersonalSkill.owner_id == user_id,
                    )
                )
            ).scalars().all()
        )
    if base not in names:
        return base
    i = 2
    while f"{base}-{i}" in names:
        i += 1
    return f"{base}-{i}"


async def _resolve_source_skill(
    skill_id: str, user_id: str
) -> Tuple[Any, str, str, Optional[str], User]:
    """解析源 Skill 行 + 作用域 + 对象存储前缀，并校验当前用户发布权限。

    返回 (row, scope, prefix, source_team_id, user)。无权限抛 PermissionError，
    找不到抛 FileNotFoundError。
    """
    prefix, scope = await NativeSkillStore._resolve_prefix(skill_id)
    if prefix is None:
        raise FileNotFoundError(f"Skill '{skill_id}' not found")

    async with async_session_factory() as session:
        if scope == "team":
            row = await session.get(TeamSkill, skill_id)
        else:
            row = await session.get(PersonalSkill, skill_id)
        user = await session.get(User, user_id)

    if row is None or user is None:
        raise FileNotFoundError(f"Skill '{skill_id}' not found")

    source_team_id: Optional[str] = None
    if scope == "team":
        source_team_id = row.team_id
        if not await team_service.is_team_member(source_team_id, user_id):
            raise PermissionError("无权发布该团队 Skill（非团队成员）")
    else:
        if row.owner_id != user_id:
            raise PermissionError("无权发布他人的个人 Skill")

    return row, scope, prefix, source_team_id, user


# =========================================================================
# 发布
# =========================================================================


async def publish(skill_id: str, user_id: str) -> Dict[str, Any]:
    """把个人 / 团队 Skill 发布为市场快照。种子用户免审核（直接 approved）。

    同一个 skill（按 `source_skill_id` + `publisher_id` 唯一）在市场只对应一个条目：
      · 首次发布 → 新建市场条目；
      · 再次发布 → 用新内容**覆盖**当前快照，被覆盖的上一版归档为「前一代版本」记录在该
        条目下（`market_listing_versions`），`market_id` 保持稳定。非种子用户覆盖已通过
        条目时条目转回 `pending` 需重新审核。

    「介绍页」信息取自 Skill 自身 config 的 `intro`（在编辑页填写，可 AI 辅助），
    随快照 copy 一并带入市场条目。返回结果附带 `replaced` 标记本次是否为覆盖更新。
    """
    row, scope, prefix, source_team_id, user = await _resolve_source_skill(
        skill_id, user_id
    )

    store = NativeSkillStore._store()
    publisher_name = user.display_name or user.username

    # 「介绍页」取自源 Skill config 的 intro（best-effort 读取，失败则视为空）
    try:
        src_config = NativeSkillStore._read_store_config(prefix)
        intro = src_config.get("intro") or {}
    except Exception:
        intro = {}
    intro_title = (intro.get("title") or "").strip() or (row.display_name or row.name)
    intro_author = (intro.get("author") or "").strip() or publisher_name
    intro_category = (intro.get("category") or "").strip()
    intro_md = (intro.get("md") or "").strip()

    seed = auth_service.is_seed_user(user)
    now = datetime.now(timezone.utc)

    # 查现有条目（同源同发布者）。存量可能有多条重复，取最近一条作为覆盖目标。
    async with async_session_factory() as session:
        existing = (
            await session.execute(
                select(MarketListing)
                .where(
                    MarketListing.source_skill_id == skill_id,
                    MarketListing.publisher_id == user_id,
                )
                .order_by(MarketListing.created_at.desc())
            )
        ).scalars().first()

        if existing is None:
            # —— 首次发布：新建市场条目 ——
            market_id = str(uuid.uuid4())
            market_prefix = _market_prefix(market_id)
            store.copy_prefix(prefix, market_prefix)
            ms = MarketListing(
                id=market_id,
                store_path=market_prefix,
                display_name=row.display_name or row.name,
                description=row.description or "",
                short_description=row.short_description or "",
                version=row.version or "1.0.0",
                tags=list(row.tags or []),
                content_hash=store.compute_prefix_hash(market_prefix),
                intro_title=intro_title,
                intro_author=intro_author,
                intro_category=intro_category,
                intro_md=intro_md,
                source_scope=scope,
                source_skill_id=skill_id,
                source_team_id=source_team_id,
                publisher_id=user_id,
                status="approved" if seed else "pending",
                reviewed_by=user_id if seed else None,
                reviewed_at=now if seed else None,
            )
            session.add(ms)
            await session.commit()
            await session.refresh(ms)
            result = _row_to_dict(ms, publisher_name)
            result["replaced"] = False
            return result

        # —— 再次发布：归档上一版 + 覆盖当前快照 ——
        listing = existing
        old_prefix = listing.store_path or _market_prefix(listing.id)

        # 1) 归档上一版内容为「前一代版本」。
        version_id = str(uuid.uuid4())
        version_prefix = _market_version_prefix(listing.id, version_id)
        try:
            store.copy_prefix(old_prefix, version_prefix)
            archived_hash = store.compute_prefix_hash(version_prefix)
        except Exception:
            logger.exception(
                f"[market/publish] 归档上一版失败 listing={listing.id}"
            )
            version_prefix = ""
            archived_hash = listing.content_hash or ""
        next_seq = int(
            await session.scalar(
                select(func.max(MarketListingVersion.seq)).where(
                    MarketListingVersion.listing_id == listing.id
                )
            )
            or 0
        ) + 1
        session.add(
            MarketListingVersion(
                id=version_id,
                listing_id=listing.id,
                seq=next_seq,
                store_path=version_prefix,
                display_name=listing.display_name or "",
                description=listing.description or "",
                short_description=listing.short_description or "",
                version=listing.version or "1.0.0",
                tags=list(listing.tags or []),
                content_hash=archived_hash,
                intro_title=listing.intro_title or "",
                intro_author=listing.intro_author or "",
                intro_category=listing.intro_category or "",
                intro_md=listing.intro_md or "",
                status=listing.status or "approved",
                published_by=listing.publisher_id,
                published_at=listing.created_at,
            )
        )

        # 2) 用新内容覆盖当前快照。
        if old_prefix:
            store.delete_prefix(old_prefix)
        market_prefix = _market_prefix(listing.id)
        store.copy_prefix(prefix, market_prefix)

        # 3) 更新条目元数据 + 审核态。
        listing.store_path = market_prefix
        listing.display_name = row.display_name or row.name
        listing.description = row.description or ""
        listing.short_description = row.short_description or ""
        listing.version = row.version or "1.0.0"
        listing.tags = list(row.tags or [])
        listing.content_hash = store.compute_prefix_hash(market_prefix)
        listing.intro_title = intro_title
        listing.intro_author = intro_author
        listing.intro_category = intro_category
        listing.intro_md = intro_md
        listing.source_scope = scope
        listing.source_team_id = source_team_id
        listing.status = "approved" if seed else "pending"
        listing.reviewed_by = user_id if seed else None
        listing.reviewed_at = now if seed else None
        listing.review_note = None

        await session.commit()
        await session.refresh(listing)
        result = _row_to_dict(listing, publisher_name)
        result["replaced"] = True
        return result


# =========================================================================
# 列表
# =========================================================================


async def list_market() -> List[Dict[str, Any]]:
    """市场页：审核通过（approved）的快照，全体可见。"""
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(MarketListing)
                .where(MarketListing.status == "approved")
                .order_by(MarketListing.updated_at.desc())
            )
        ).scalars().all()
    names = await _publisher_names(rows)
    return [_row_to_dict(r, names.get(r.publisher_id, "")) for r in rows]


async def list_mine(user_id: str) -> List[Dict[str, Any]]:
    """我的发布：当前用户全部发布（含 pending / rejected）。"""
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(MarketListing)
                .where(MarketListing.publisher_id == user_id)
                .order_by(MarketListing.created_at.desc())
            )
        ).scalars().all()
    names = await _publisher_names(rows)
    return [_row_to_dict(r, names.get(r.publisher_id, "")) for r in rows]


async def list_pending() -> List[Dict[str, Any]]:
    """审核队列：待审核（pending）快照，按提交时间升序（先到先审）。"""
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(MarketListing)
                .where(MarketListing.status == "pending")
                .order_by(MarketListing.created_at.asc())
            )
        ).scalars().all()
    names = await _publisher_names(rows)
    return [_row_to_dict(r, names.get(r.publisher_id, "")) for r in rows]


# =========================================================================
# 详情（只读「SKILL 介绍」页）
# =========================================================================


async def get_detail(market_id: str) -> Dict[str, Any]:
    """读取市场条目完整详情：介绍字段 + 快照 config / 正文 / 资源 + 行元数据。"""
    async with async_session_factory() as session:
        ms = await session.get(MarketListing, market_id)
    if ms is None:
        raise FileNotFoundError("市场 Skill 不存在")

    prefix = ms.store_path or _market_prefix(market_id)
    try:
        config = NativeSkillStore._read_store_config(prefix)
    except Exception:
        config = {}
    try:
        vibeh_content = NativeSkillStore._read_store_vibeh(prefix) or ""
    except Exception:
        vibeh_content = ""
    try:
        resources = NativeSkillStore._scan_store_resources(prefix)
        if any(resources.values()):
            config["resources"] = resources
    except Exception:
        pass

    names = await _publisher_names([ms])
    item = _row_to_dict(ms, names.get(ms.publisher_id, ""))
    return {
        "id": ms.id,
        "config": config,
        "vibeh_content": vibeh_content,
        "store_path": prefix,
        "listing": item,
    }


async def read_resource_file(market_id: str, rel_path: str) -> Dict[str, Any]:
    """读取市场快照中的单个资源文件内容（文本 utf8 / 二进制 base64）。"""
    import base64

    async with async_session_factory() as session:
        ms = await session.get(MarketListing, market_id)
    if ms is None:
        raise FileNotFoundError("市场 Skill 不存在")

    prefix = ms.store_path or _market_prefix(market_id)
    safe = NativeSkillStore._safe_resource_rel(rel_path)
    data = NativeSkillStore._store().get_bytes(prefix + "/" + safe)
    if data is None:
        raise FileNotFoundError(f"资源文件不存在: {safe}")

    try:
        text = data.decode("utf-8")
        return {
            "path": safe,
            "encoding": "utf8",
            "content": text,
            "size": len(data),
            "is_binary": False,
        }
    except UnicodeDecodeError:
        return {
            "path": safe,
            "encoding": "base64",
            "content": base64.b64encode(data).decode("ascii"),
            "size": len(data),
            "is_binary": True,
        }


# =========================================================================
# 历史版本（前一代版本：列表 / 详情 / 资源文件）
# =========================================================================


async def list_versions(market_id: str) -> List[Dict[str, Any]]:
    """列出某市场条目的全部「前一代版本」（按 seq 倒序）。"""
    async with async_session_factory() as session:
        ms = await session.get(MarketListing, market_id)
        if ms is None:
            raise FileNotFoundError("市场 Skill 不存在")
        rows = (
            await session.execute(
                select(MarketListingVersion)
                .where(MarketListingVersion.listing_id == market_id)
                .order_by(MarketListingVersion.seq.desc())
            )
        ).scalars().all()
    return [_version_row_to_dict(r) for r in rows]


async def get_version_detail(market_id: str, version_id: str) -> Dict[str, Any]:
    """读取某前一代版本的完整详情：归档快照 config / 正文 / 资源 + 版本元数据。

    合并父条目的发布者 / 来源信息，便于前端复用市场详情页渲染。
    """
    async with async_session_factory() as session:
        ver = await session.get(MarketListingVersion, version_id)
        if ver is None or ver.listing_id != market_id:
            raise FileNotFoundError("历史版本不存在")
        ms = await session.get(MarketListing, market_id)

    prefix = ver.store_path or _market_version_prefix(market_id, version_id)
    try:
        config = NativeSkillStore._read_store_config(prefix)
    except Exception:
        config = {}
    try:
        vibeh_content = NativeSkillStore._read_store_vibeh(prefix) or ""
    except Exception:
        vibeh_content = ""
    try:
        resources = NativeSkillStore._scan_store_resources(prefix)
        if any(resources.values()):
            config["resources"] = resources
    except Exception:
        pass

    names = await _publisher_names([ms]) if ms is not None else {}
    publisher_name = names.get(ms.publisher_id, "") if ms is not None else ""

    # 版本快照元数据 + 父条目溯源信息 → 拼成 listing 风格对象供前端复用渲染。
    item = _version_row_to_dict(ver)
    item.update(
        {
            "source_scope": ms.source_scope if ms is not None else "personal",
            "source_skill_id": ms.source_skill_id if ms is not None else "",
            "source_team_id": ms.source_team_id if ms is not None else None,
            "publisher_id": ms.publisher_id if ms is not None else "",
            "publisher_name": publisher_name,
            "reviewed_by": None,
            "reviewed_at": None,
            "review_note": None,
            "updated_at": item.get("created_at"),
        }
    )
    return {
        "id": ver.id,
        "config": config,
        "vibeh_content": vibeh_content,
        "store_path": prefix,
        "listing": item,
    }


async def read_version_resource_file(
    market_id: str, version_id: str, rel_path: str
) -> Dict[str, Any]:
    """读取某前一代版本归档快照中的单个资源文件内容。"""
    import base64

    async with async_session_factory() as session:
        ver = await session.get(MarketListingVersion, version_id)
    if ver is None or ver.listing_id != market_id:
        raise FileNotFoundError("历史版本不存在")

    prefix = ver.store_path or _market_version_prefix(market_id, version_id)
    safe = NativeSkillStore._safe_resource_rel(rel_path)
    data = NativeSkillStore._store().get_bytes(prefix + "/" + safe)
    if data is None:
        raise FileNotFoundError(f"资源文件不存在: {safe}")

    try:
        text = data.decode("utf-8")
        return {
            "path": safe,
            "encoding": "utf8",
            "content": text,
            "size": len(data),
            "is_binary": False,
        }
    except UnicodeDecodeError:
        return {
            "path": safe,
            "encoding": "base64",
            "content": base64.b64encode(data).decode("ascii"),
            "size": len(data),
            "is_binary": True,
        }


# =========================================================================
# 审核
# =========================================================================


async def review(
    market_id: str, reviewer_id: str, approve: bool, note: str = ""
) -> Dict[str, Any]:
    async with async_session_factory() as session:
        ms = await session.get(MarketListing, market_id)
        if ms is None:
            raise FileNotFoundError("市场 Skill 不存在")
        ms.status = "approved" if approve else "rejected"
        ms.reviewed_by = reviewer_id
        ms.reviewed_at = datetime.now(timezone.utc)
        ms.review_note = note or None
        await session.commit()
        await session.refresh(ms)
        return _row_to_dict(ms)


# =========================================================================
# 获取（复制快照到个人仓库）
# =========================================================================


async def acquire(market_id: str, user_id: str) -> Dict[str, Any]:
    async with async_session_factory() as session:
        ms = await session.get(MarketListing, market_id)
    if ms is None:
        raise FileNotFoundError("市场 Skill 不存在")
    if ms.status != "approved":
        raise PermissionError("该 Skill 未通过审核，暂不可获取")

    store = NativeSkillStore._store()
    source_config = NativeSkillStore._read_store_config(ms.store_path)
    base = str(source_config.get("name") or "market-skill")
    # 唯一约束是并发下的最终裁决；若两次获取同时选中同一自然名，
    # 失败者清理自己的 UUID 前缀后重新选名。
    for attempt in range(3):
        new_name = await _unique_personal_name(base, user_id)
        new_id = str(uuid.uuid4())
        new_prefix = NativeSkillStore._personal_prefix(user_id, new_id)
        store.copy_prefix(ms.store_path, new_prefix)

        config = NativeSkillStore._read_store_config(new_prefix)
        display = (
            ms.display_name
            or config.get("ui", {}).get("display_name")
            or config.get("display_name")
            or new_name
        )
        config["name"] = new_name
        config.setdefault("ui", {})["display_name"] = display
        config["scope"] = "personal"
        config.pop("team_id", None)
        config["source_skill_id"] = ms.id  # 溯源到市场条目（软引用，不同步）
        NativeSkillStore._write_store_config(new_prefix, config)

        try:
            row = await NativeSkillStore._upsert_db(
                new_id,
                config,
                new_prefix,
                owner_id=user_id,
                name=new_name,
            )
            return NativeSkillStore._row_to_dict(row)
        except IntegrityError as e:
            store.delete_prefix(new_prefix)
            if attempt == 2:
                raise ValueError(
                    "并发获取导致个人 Skill 名称持续冲突，请重试"
                ) from e

    raise RuntimeError("市场 Skill 获取失败")


# =========================================================================
# 编辑介绍页
# =========================================================================


async def update_intro(
    market_id: str,
    user_id: str,
    *,
    intro_title: str,
    intro_author: str,
    intro_category: str,
    intro_md: str,
) -> Dict[str, Any]:
    """修改市场条目的「介绍页」信息（审核员或发布者本人可改）。

    仅更新介绍字段，不触碰快照内容 / 审核态 / 溯源。
    """
    async with async_session_factory() as session:
        ms = await session.get(MarketListing, market_id)
        if ms is None:
            raise FileNotFoundError("市场 Skill 不存在")
        user = await session.get(User, user_id)
        if ms.publisher_id != user_id and not auth_service.is_reviewer(user):
            raise PermissionError("无权修改该市场条目的介绍")
        ms.intro_title = (intro_title or "").strip()
        ms.intro_author = (intro_author or "").strip()
        ms.intro_category = (intro_category or "").strip()
        ms.intro_md = (intro_md or "").strip()
        await session.commit()
        await session.refresh(ms)
    names = await _publisher_names([ms])
    return _row_to_dict(ms, names.get(ms.publisher_id, ""))


# =========================================================================
# 删除 / 撤回
# =========================================================================


async def remove(market_id: str, user_id: str) -> Dict[str, Any]:
    """发布者本人或审核员（种子 / 平台管理员）可删除市场条目。

    一并清理该条目的全部「前一代版本」记录与归档快照前缀。
    """
    store = NativeSkillStore._store()
    async with async_session_factory() as session:
        ms = await session.get(MarketListing, market_id)
        if ms is None:
            raise FileNotFoundError("市场 Skill 不存在")
        user = await session.get(User, user_id)
        if ms.publisher_id != user_id and not auth_service.is_reviewer(user):
            raise PermissionError("无权删除该市场条目")
        if ms.store_path:
            store.delete_prefix(ms.store_path)
        # 清理历史版本行（归档前缀统一在 skills/market_versions/{listing_id} 下整体删除）。
        await session.execute(
            sa_delete(MarketListingVersion).where(
                MarketListingVersion.listing_id == market_id
            )
        )
        await session.delete(ms)
        await session.commit()
    try:
        store.delete_prefix(f"{MARKET_VERSIONS_ROOT}/{market_id}")
    except Exception:
        logger.warning(f"[market/remove] 清理归档前缀失败: {market_id}")
    return {"success": True}

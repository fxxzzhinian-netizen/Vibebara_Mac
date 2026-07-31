"""
NativeSkillStore — 平台原生 Skill 的 CRUD + 文件系统 + MySQL 索引

存储格式遵循 docs/design/skill-forge.md 设计文档：
    skill.config.yaml   — 统一配置（design-doc 格式，嵌套 ui/policy/metadata）
    SKILL.md            — 技能正文（纯 Markdown）
    scripts/
    references/
    assets/
"""

import hashlib
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from sqlalchemy import delete, select, update

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.project import UserSkillDeployment
from app.models.skill_package import PersonalSkill, TeamSkill
from app.models.team import TeamMember
from app.models.user import User
from app.services.skill_forge_service import call_bridge
from app.services.skill_sync_service import SkillSyncService
from app.services.team_sync_service import TeamSyncService

logger = logging.getLogger(__name__)

CURSOR_SKILLS_DIR = Path.home() / ".cursor" / "skills"
CODEX_SKILLS_DIR = Path(
    os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
) / "skills"
# Windsurf 全局 skill 目录在 ~/.codeium/windsurf/skills（不是 ~/.windsurf）。
WINDSURF_SKILLS_DIR = Path.home() / ".codeium" / "windsurf" / "skills"
# Claude Code 全局 skill 目录在 ~/.claude/skills。
CLAUDE_SKILLS_DIR = Path.home() / ".claude" / "skills"
# Kiro 全局 skill 目录在 ~/.kiro/skills。
KIRO_SKILLS_DIR = Path.home() / ".kiro" / "skills"


def trae_skills_dir() -> Path:
    """Trae 全局 skill 目录自动探测（docs/design/skill-forge.md §8.5）。

    Trae 国际版（trae.ai）用 ~/.trae，国内版（trae.cn）用 ~/.trae-cn，两版项目
    目录都是 .trae/skills/。择优规则：优先已存在的 ~/.trae，否则 ~/.trae-cn，
    都不存在回退 ~/.trae。与 skill-forge resolveTraeSkillsDir / local-agent
    traeSkillsDir 口径一致。
    """
    home = Path.home()
    intl = home / ".trae"
    cn = home / ".trae-cn"
    if intl.exists():
        return intl / "skills"
    if cn.exists():
        return cn / "skills"
    return intl / "skills"


def qoder_skills_dir() -> Path:
    """Qoder 全局 skill 目录（docs/design/skill-forge.md §9.5）。

    Qoder 全局目录统一为 ~/.qoder/skills，**无国内/国际分叉，无须探测**
    （与 Trae 不同）。项目级目录为 .qoder/skills/，同名时项目级优先于全局。
    与 skill-forge resolveQoderSkillsDir / local-agent qoderSkillsDir 口径一致。
    """
    return Path.home() / ".qoder" / "skills"


def workbuddy_skills_dir() -> Path:
    """WorkBuddy（腾讯 CodeBuddy 生态）全局 skill 目录（docs/design/skill-forge.md §9.6）。

    WorkBuddy 全局目录统一为 ~/.workbuddy/skills，**无国内/国际分叉，无须探测**
    （与 Qoder 同）。项目级目录为 .workbuddy/skills/，同名时项目级优先于全局。
    与 skill-forge resolveWorkbuddySkillsDir / local-agent workbuddySkillsDir 口径一致。
    """
    return Path.home() / ".workbuddy" / "skills"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_tags(value: Any) -> List[str]:
    """把任意来源的 tags 归一为「字符串列表」。

    tags 存在 JSON 列，写入时直接取自 skill frontmatter（_upsert_db），用户导入的
    原生 skill 若把 tags 写成单个字符串（``tags: alpha``）、逗号串（``tags: a,b``）、
    数字或字典等非「字符串列表」形态，旧实现会原样落库；读取时响应模型
    NativeSkillItem.tags 是严格的 List[str]，于是**整条 list 序列化 500**，表现为
    “个人/团队 Skill 仓库始终加载失败”。这里在读写两端都做容错归一，既修复存量坏
    数据、也避免再产生坏数据。
    """
    if value is None:
        return []
    if isinstance(value, str):
        # 逗号/换行分隔的字符串拆成多个标签；单个标签即单元素列表。
        parts = [p.strip() for p in value.replace("\n", ",").split(",")]
        return [p for p in parts if p]
    if isinstance(value, (list, tuple, set)):
        out: List[str] = []
        for item in value:
            if item is None:
                continue
            out.append(item if isinstance(item, str) else str(item))
        return out
    # 数字/布尔/字典等其它标量：转成单个字符串标签，避免丢失但保证可序列化。
    return [str(value)]


def _normalize_version(value: Any) -> str:
    """把 version 归一为字符串。

    version 取自 frontmatter（metadata.version），YAML 会把 ``version: 1.0`` 解析为
    数字；旧实现直接赋给行对象，create/import 响应在 refresh 前读到的是内存中的数字，
    NativeSkillItem.version 为严格 str → 序列化 500。统一转字符串。
    """
    if value is None or value == "":
        return "1.0.0"
    return value if isinstance(value, str) else str(value)


def _read_yaml(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


def _write_yaml(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def _parse_skill_md(path: Path) -> tuple:
    """解析 SKILL.md 为 (frontmatter_dict, body_str)"""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm = yaml.safe_load(parts[1]) or {}
            body = parts[2].lstrip("\n")
            return fm, body
    return {}, text


def _scan_resources(skill_dir: Path) -> Dict[str, List[Dict[str, str]]]:
    """扫描 skill 目录下的 scripts/references/assets，返回资源声明列表。"""
    result: Dict[str, List[Dict[str, str]]] = {
        "scripts": [],
        "references": [],
        "assets": [],
    }
    for category in ("scripts", "references", "assets"):
        sub = skill_dir / category
        if not sub.is_dir():
            continue
        for f in sorted(sub.rglob("*")):
            if f.is_file():
                rel = f.relative_to(skill_dir).as_posix()
                result[category].append({"path": rel, "description": ""})
    return result


def _compute_dir_hash(root: Path) -> str:
    # R2 收敛（M0 §7.2）：排序键统一为「相对 root 的 POSIX 路径字符串的
    # UTF-8 字节序」，大小写敏感、不做 normcase、分隔符恒为 '/'。
    # 必须与 project_service._compute_content_hash 位级一致，并与 M0 契约
    # §7.3 的 TS 伪代码对齐（本地代理需位级复刻）。
    if not root.exists():
        return ""
    digest = hashlib.sha256()
    has_files = False
    files = sorted(
        (p for p in root.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(root).as_posix().encode("utf-8"),
    )
    for file_path in files:
        rel = file_path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
        has_files = True
    return digest.hexdigest() if has_files else ""


def _detect_origin(src: Path, frontmatter: Dict[str, Any]) -> str:
    """根据路径与 frontmatter 特征判断 skill 来源平台。

    路径为强信号；frontmatter 为细分信号。注意 Cursor 与 Claude 都可能含
    `disable-model-invocation`，故优先用 Claude 专有运行时字段区分，避免误判。
    详见 docs/design/skill-forge.md §八。
    """
    src_str = str(src).replace("\\", "/").lower()

    # 路径主信号（最可靠）
    if "/.codeium/windsurf/skills/" in src_str or "/.windsurf/skills/" in src_str:
        return "windsurf"
    if "/.claude/skills/" in src_str:
        return "claude"
    # Kiro 无独占 frontmatter 字段（license/compatibility/metadata 与 Claude/Codex
    # 共享），仅靠 .kiro/skills/ 路径主信号识别。
    if "/.kiro/skills/" in src_str:
        return "kiro"
    # Trae 仅 name+description、无独占 frontmatter 辅信号（与 Windsurf 同），
    # 仅靠 .trae/skills/ 路径主信号识别。
    if "/.trae/skills/" in src_str:
        return "trae"
    # Qoder 仅 name+description、无独占 frontmatter 辅信号（与 Windsurf/Trae 同），
    # 仅靠 .qoder/skills/ 路径主信号识别（全局/项目统一，无国内/国际分叉）。
    if "/.qoder/skills/" in src_str:
        return "qoder"
    # WorkBuddy（腾讯 CodeBuddy 生态）.workbuddy/skills/ 路径主信号识别
    # （全局/项目统一，无国内/国际分叉）；市场安装态边文件 _skillhub_meta.json 为辅信号。
    if "/.workbuddy/skills/" in src_str:
        return "workbuddy"
    if (src / "_skillhub_meta.json").exists():
        return "workbuddy"
    if (src / "agents" / "openai.yaml").exists():
        return "codex"

    # frontmatter 细分信号：Claude 专有运行时字段
    claude_fields = (
        "allowed-tools",
        "disallowed-tools",
        "user-invocable",
        "argument-hint",
        "model",
        "effort",
        "context",
        "agent",
        "hooks",
        "when_to_use",
    )
    if any(frontmatter.get(f) is not None for f in claude_fields):
        return "claude"
    if frontmatter.get("metadata", {}).get("surfaces"):
        return "cursor"
    if frontmatter.get("disable-model-invocation") is not None:
        return "cursor"
    return "unknown"


def _merge_block(target: Dict[str, Any], updates: Dict[str, Any]) -> None:
    """块内浅合并：值为 None 表示删除该键（前端清空字段时发 null），其余覆盖/新增。

    背景：前端每次保存上送整份 config；某字段被清空时前端发 `null`（而非 undefined，
    否则 JSON 序列化会丢键、后端无从得知要删）。这里据此把对应键从存储 config 里删掉，
    避免 skill.config.yaml 残留旧值或 `null` 噪声。空字符串/空数组等仍按正常值写入。
    """
    for k, v in updates.items():
        if v is None:
            target.pop(k, None)
        else:
            target[k] = v


def _config_to_ts_format(config: Dict[str, Any], vibeh_content: str = "") -> Dict[str, Any]:
    """
    将 design-doc 格式的 skill.config.yaml 转换为 TS bridge 期望的格式。

    Design-doc 格式（嵌套）→ TS 格式（扁平 camelCase）
    """
    ui = config.get("ui", {})
    policy = config.get("policy", {})
    metadata = config.get("metadata", {})
    resources = config.get("resources", {})
    deps = config.get("dependencies", {})

    auto_invoke = policy.get("auto_invoke", True)

    def _extract_paths(items: list) -> List[str]:
        result = []
        for item in (items or []):
            if isinstance(item, dict):
                result.append(item.get("path", ""))
            elif isinstance(item, str):
                result.append(item)
        return [p for p in result if p]

    ts_config: Dict[str, Any] = {
        "name": config.get("name", ""),
        "description": config.get("description", ""),
        "version": metadata.get("version", config.get("version", "1.0.0")),
        "instructions": vibeh_content or config.get("instructions", ""),
        "triggers": {
            "disableModelInvocation": not auto_invoke,
            "allowImplicitInvocation": auto_invoke,
        },
        "ui": {
            k: v
            for k, v in {
                "brandColor": ui.get("brand_color"),
                "iconSmall": ui.get("icon_small"),
                "iconLarge": ui.get("icon_large"),
                "defaultPrompt": ui.get("default_prompt"),
            }.items()
            if v
        },
        "dependencies": {
            "tools": deps.get("tools", []),
        },
        "resources": {
            "scripts": _extract_paths(resources.get("scripts", [])),
            "references": _extract_paths(resources.get("references", [])),
            "assets": _extract_paths(resources.get("assets", [])),
        },
    }

    if ui.get("display_name"):
        ts_config["displayName"] = ui["display_name"]
    if ui.get("short_description"):
        ts_config["shortDescription"] = ui["short_description"]

    # Claude Code 专有运行时字段（design-doc snake_case → unified.ts camelCase）。
    # 仅在构建 Claude 目标时被消费；其余平台适配器整体丢弃。
    claude = config.get("claude", {}) or {}
    claude_ts = {
        k: v
        for k, v in {
            "allowedTools": claude.get("allowed_tools"),
            "disallowedTools": claude.get("disallowed_tools"),
            "userInvocable": claude.get("user_invocable"),
            "argumentHint": claude.get("argument_hint"),
            "whenToUse": claude.get("when_to_use"),
            "model": claude.get("model"),
            "effort": claude.get("effort"),
            "context": claude.get("context"),
            "agent": claude.get("agent"),
            "hooks": claude.get("hooks"),
        }.items()
        if v not in (None, "")
    }
    if claude_ts:
        ts_config["claude"] = claude_ts

    # Agent Skills 标准元数据（license/compatibility/author/version/surfaces）。
    # 各平台适配器按支持情况选择性输出（详见 docs/design/skill-forge.md §2.4 矩阵）。
    meta_ts = {
        k: v
        for k, v in {
            "license": metadata.get("license"),
            "compatibility": metadata.get("compatibility"),
            "author": metadata.get("author"),
            "version": metadata.get("version"),
            "surfaces": metadata.get("surfaces"),
        }.items()
        if v not in (None, "")
    }
    if meta_ts:
        ts_config["metadata"] = meta_ts

    return ts_config


class NativeSkillStore:
    _store_dir: str = ""

    # ------------------------------------------------------------------
    # 对象存储路由辅助：个人/团队两张物理表 + 对象键前缀按仓库分层
    #   personal: skills/personal/{id}/   (id=自然名)
    #   team:     skills/team/{id}/        (id={自然名}-team-{team_id[:8]})
    # 个人 id 与团队 id 天然不冲突，故 get/解析可「先个人再团队」。
    # store_path（DB 列）= 对象键前缀（如 skills/personal/foo）。
    # ------------------------------------------------------------------

    @classmethod
    def _store(cls):
        from app.services.object_store import get_object_store
        return get_object_store()

    @staticmethod
    def _personal_prefix(skill_id: str) -> str:
        return f"skills/personal/{skill_id}"

    @staticmethod
    def _team_prefix(skill_id: str) -> str:
        return f"skills/team/{skill_id}"

    @classmethod
    def _resolve_prefix(cls, skill_id: str) -> tuple:
        """返回 (prefix, scope)；都不存在返回 (None, None)。"""
        store = cls._store()
        p = cls._personal_prefix(skill_id)
        if store.exists(p + "/skill.config.yaml"):
            return p, "personal"
        t = cls._team_prefix(skill_id)
        if store.exists(t + "/skill.config.yaml"):
            return t, "team"
        return None, None

    @classmethod
    def _prefix_for(cls, skill_id: str, scope: str) -> str:
        return cls._team_prefix(skill_id) if scope == "team" else cls._personal_prefix(skill_id)

    # ---- 对象存储读写（config / SKILL.md / 资源 / hash）----

    @classmethod
    def _read_store_config(cls, prefix: str) -> Dict[str, Any]:
        text = cls._store().get_text(prefix + "/skill.config.yaml")
        return (yaml.safe_load(text) or {}) if text is not None else {}

    @classmethod
    def _write_store_config(cls, prefix: str, config: Dict[str, Any]) -> None:
        cls._store().put_text(
            prefix + "/skill.config.yaml",
            yaml.dump(config, allow_unicode=True, sort_keys=False, default_flow_style=False),
        )

    @classmethod
    def _read_store_vibeh(cls, prefix: str) -> str:
        return cls._store().get_text(prefix + "/SKILL.md") or ""

    @classmethod
    def _write_store_vibeh(cls, prefix: str, body: str) -> None:
        cls._store().put_text(prefix + "/SKILL.md", body)

    @classmethod
    def _scan_store_resources(cls, prefix: str) -> Dict[str, List[Dict[str, str]]]:
        """扫描对象前缀下 scripts/references/assets，返回资源声明（路径相对前缀）。"""
        result: Dict[str, List[Dict[str, str]]] = {
            "scripts": [], "references": [], "assets": [],
        }
        base = prefix.rstrip("/") + "/"
        for key in cls._store().list(base):
            rel = key[len(base):]
            if "/" not in rel:
                continue
            cat = rel.split("/", 1)[0]
            if cat in result:
                result[cat].append({"path": rel, "description": ""})
        for cat in result:
            result[cat].sort(key=lambda d: d["path"])
        return result

    @classmethod
    def _store_exists(cls, prefix: str) -> bool:
        return cls._store().exists(prefix + "/skill.config.yaml")

    @staticmethod
    def _strip_team_suffix(skill_id: str) -> str:
        """从团队代理 id `{base}-team-{8hex}` 还原自然名（不匹配则原样返回）。"""
        return re.sub(r"-team-[0-9a-z]{1,12}$", "", skill_id) or skill_id

    @staticmethod
    async def _get_row(session, skill_id: str):
        """先查个人表再查团队表，返回 (row, scope) 或 (None, None)。"""
        row = await session.get(PersonalSkill, skill_id)
        if row is not None:
            return row, "personal"
        row = await session.get(TeamSkill, skill_id)
        if row is not None:
            return row, "team"
        return None, None

    @staticmethod
    async def _row_accessible(session, row, user_id: Optional[str]) -> bool:
        """统一仓库访问判断；user_id=None 仅保留给受信任的内部任务。"""
        if row is None:
            return user_id is None
        if user_id is None:
            return True
        if isinstance(row, PersonalSkill):
            return bool(row.owner_id) and row.owner_id == user_id
        if isinstance(row, TeamSkill):
            member_id = await session.scalar(
                select(TeamMember.id).where(
                    TeamMember.team_id == row.team_id,
                    TeamMember.user_id == user_id,
                )
            )
            return member_id is not None
        return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    async def init(cls, store_dir: str = "") -> None:
        cls._store_dir = store_dir
        # 触发对象存储初始化（local 文件系统 / COS）。
        store = cls._store()
        if settings.SKILL_STORE_SYNC_ON_START:
            await cls._sync_from_filesystem()
        try:
            migrated = await cls.migrate_orphan_owners()
            if migrated:
                logger.info(
                    f"[NativeSkillStore] 已将 {migrated} 个无主个人 Skill 归属给首个用户"
                )
        except Exception as e:
            logger.warning(f"[NativeSkillStore] 个人 Skill 归属迁移失败: {e}")
        logger.info(
            f"[NativeSkillStore] 初始化完成, backend={settings.STORAGE_BACKEND}"
        )

    @classmethod
    async def _sync_from_filesystem(cls) -> None:
        """按对象存储前缀 skills/personal/、skills/team/ 列举 skill，同步到对应表；
        并删除「DB 有但对象存储无」的记录（按表分别裁剪）。

        skill 数量大时可经 SKILL_STORE_SYNC_ON_START=false 关闭（信任 DB 索引）。
        """
        store = cls._store()
        found_personal: List[str] = []
        found_team: List[str] = []

        async def _scan(repo_root: str, scope: str) -> None:
            try:
                ids = store.list_dirs(repo_root)
            except Exception as e:
                logger.warning(f"[NativeSkillStore] 列举 {repo_root} 失败: {e}")
                return
            for skill_id in ids:
                prefix = f"{repo_root}/{skill_id}"
                if not store.exists(prefix + "/skill.config.yaml"):
                    continue
                try:
                    config = cls._read_store_config(prefix)
                    if "resources" not in config:
                        resources = cls._scan_store_resources(prefix)
                        if any(resources.values()):
                            config["resources"] = resources
                            cls._write_store_config(prefix, config)
                    if scope == "team":
                        found_team.append(skill_id)
                        await cls._upsert_db(
                            skill_id, config, prefix, scope="team",
                            team_id=config.get("team_id"),
                            source_skill_id=config.get("source_skill_id"),
                            name=config.get("name") or cls._strip_team_suffix(skill_id),
                        )
                    else:
                        found_personal.append(skill_id)
                        await cls._upsert_db(skill_id, config, prefix, scope="personal")
                except Exception as e:
                    logger.warning(f"[NativeSkillStore] 跳过 {scope}/{skill_id}: {e}")

        await _scan("skills/personal", "personal")
        await _scan("skills/team", "team")

        # 按表分别删除 DB 中已不存在于对象存储的记录
        async with async_session_factory() as session:
            if found_personal:
                await session.execute(
                    delete(PersonalSkill).where(PersonalSkill.id.notin_(found_personal))
                )
            else:
                await session.execute(delete(PersonalSkill))
            if found_team:
                await session.execute(
                    delete(TeamSkill).where(TeamSkill.id.notin_(found_team))
                )
            else:
                await session.execute(delete(TeamSkill))
            await session.commit()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    @classmethod
    async def _upsert_db(
        cls,
        skill_id: str,
        config: Dict[str, Any],
        store_path: str,
        *,
        scope: str = "personal",
        owner_id: Optional[str] = None,
        team_id: Optional[str] = None,
        source_skill_id: Optional[str] = None,
        name: Optional[str] = None,
    ):
        ui = config.get("ui", {})
        metadata = config.get("metadata", {})
        import_meta = config.get("_import_meta", {})
        meta_legacy = config.get("meta", {})

        async with async_session_factory() as session:
            if scope == "team":
                row = await session.get(TeamSkill, skill_id)
                if row is None:
                    row = TeamSkill(
                        id=skill_id,
                        name=name or config.get("name") or cls._strip_team_suffix(skill_id),
                        team_id=team_id or "",
                        store_path=store_path,
                        created_at=datetime.now(timezone.utc),
                    )
                    session.add(row)
                if name:
                    row.name = name
                if team_id:
                    row.team_id = team_id
                if source_skill_id is not None:
                    row.source_skill_id = source_skill_id
            else:
                row = await session.get(PersonalSkill, skill_id)
                if row is None:
                    row = PersonalSkill(
                        id=skill_id,
                        store_path=store_path,
                        created_at=datetime.now(timezone.utc),
                    )
                    session.add(row)
                if owner_id and not row.owner_id:
                    row.owner_id = owner_id

            row.display_name = (
                ui.get("display_name")
                or config.get("displayName", "")
            )
            row.description = config.get("description", "")
            row.short_description = (
                ui.get("short_description")
                or config.get("shortDescription", "")
            )
            row.version = _normalize_version(
                metadata.get("version")
                or config.get("version", "1.0.0")
            )
            row.tags = _normalize_tags(
                metadata.get("tags")
                or meta_legacy.get("tags", [])
            )
            row.imported_from = (
                import_meta.get("source")
                or meta_legacy.get("importedFrom")
            )
            row.store_path = store_path
            row.content_hash = cls._store().compute_prefix_hash(store_path)
            row.updated_at = datetime.now(timezone.utc)

            # 平台部署状态（deployed_cursor/codex）：
            #   - local 形态（后端=用户机器）：沿用现状，探测后端机器 home 的
            #     ~/.cursor|.codex/skills/{id}/SKILL.md（语义有效，不改 local 行为）。
            #   - cloud 形态（薄代理）：后端磁盘与用户机器无关，探测无意义；本机是否
            #     已装 cursor/codex 改由**本地代理 scan 的 installedAt** 按用户实时回答，
            #     前端用其展示（详见 M4-收尾与联调记录）。此处**不据后端盘设置**，
            #     保留字段兼容（新行默认 False，存量值不被后端盘探测覆盖）。
            if settings.DEPLOYMENT_MODE != "cloud":
                row.deployed_cursor = (
                    CURSOR_SKILLS_DIR / skill_id / "SKILL.md"
                ).exists()
                row.deployed_codex = (
                    CODEX_SKILLS_DIR / skill_id / "SKILL.md"
                ).exists()
                row.deployed_windsurf = (
                    WINDSURF_SKILLS_DIR / skill_id / "SKILL.md"
                ).exists()
                row.deployed_claude = (
                    CLAUDE_SKILLS_DIR / skill_id / "SKILL.md"
                ).exists()
                row.deployed_kiro = (
                    KIRO_SKILLS_DIR / skill_id / "SKILL.md"
                ).exists()
                row.deployed_trae = (
                    trae_skills_dir() / skill_id / "SKILL.md"
                ).exists()
                row.deployed_qoder = (
                    qoder_skills_dir() / skill_id / "SKILL.md"
                ).exists()
                row.deployed_workbuddy = (
                    workbuddy_skills_dir() / skill_id / "SKILL.md"
                ).exists()
            else:
                if row.deployed_cursor is None:
                    row.deployed_cursor = False
                if row.deployed_codex is None:
                    row.deployed_codex = False
                if row.deployed_windsurf is None:
                    row.deployed_windsurf = False
                if row.deployed_claude is None:
                    row.deployed_claude = False
                if row.deployed_kiro is None:
                    row.deployed_kiro = False
                if row.deployed_trae is None:
                    row.deployed_trae = False
                if row.deployed_qoder is None:
                    row.deployed_qoder = False
                if row.deployed_workbuddy is None:
                    row.deployed_workbuddy = False

            await session.commit()
            await session.refresh(row)
            return row

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @classmethod
    async def list_all(
        cls,
        scope: Optional[str] = None,
        owner_id: Optional[str] = None,
        team_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        async with async_session_factory() as session:
            if scope == "team":
                if not team_ids:
                    return []
                stmt = (
                    select(TeamSkill)
                    .where(TeamSkill.team_id.in_(team_ids))
                    .order_by(TeamSkill.updated_at.desc())
                )
                rows = (await session.execute(stmt)).scalars().all()
                return [cls._row_to_dict(r) for r in rows]

            # 默认/personal：个人表按 owner 过滤
            if not owner_id:
                return []
            stmt = (
                select(PersonalSkill)
                .where(PersonalSkill.owner_id == owner_id)
                .order_by(PersonalSkill.updated_at.desc())
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [cls._row_to_dict(r) for r in rows]

    @classmethod
    async def get_by_id(
        cls, skill_id: str, user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        async with async_session_factory() as session:
            row, _ = await cls._get_row(session, skill_id)
            if not await cls._row_accessible(session, row, user_id):
                return None

        prefix, scope = cls._resolve_prefix(skill_id)
        if prefix is None:
            return None
        config = cls._read_store_config(prefix)

        resources = cls._scan_store_resources(prefix)
        if any(resources.values()):
            if config.get("resources") != resources:
                config["resources"] = resources
                cls._write_store_config(prefix, config)

        vibeh_content = cls._read_store_vibeh(prefix)

        return {
            "id": skill_id,
            "config": config,
            "vibeh_content": vibeh_content,
            "store_path": prefix,
            "db": cls._row_to_dict(row) if row else None,
        }

    # ------------------------------------------------------------------
    # 单个资源文件读写（scripts/references/assets/**）—— 供网页文件树编辑器使用。
    # 直接对对象存储（COS / 本地）按 {prefix}/{rel} 读写单个文件字节。
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_resource_rel(rel_path: str) -> str:
        """校验并规整资源相对路径：必须落在 scripts/references/assets 下且无逃逸。"""
        p = (rel_path or "").replace("\\", "/").strip("/")
        if not p:
            raise ValueError("空路径")
        parts = p.split("/")
        if any(seg in ("", ".", "..") for seg in parts):
            raise ValueError("非法路径")
        if parts[0] not in ("scripts", "references", "assets"):
            raise ValueError("仅允许 scripts/references/assets 下的文件")
        if len(parts) < 2:
            raise ValueError("路径必须指向具体文件")
        return p

    @classmethod
    async def read_resource_file(
        cls, skill_id: str, rel_path: str, user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """读取单个资源文件内容。文本返回 utf8，无法解码则返回 base64（标记为二进制）。"""
        import base64

        async with async_session_factory() as session:
            row, _ = await cls._get_row(session, skill_id)
            if not await cls._row_accessible(session, row, user_id):
                raise PermissionError("Skill 不存在或无权访问")

        prefix, _scope = cls._resolve_prefix(skill_id)
        if prefix is None:
            raise FileNotFoundError(f"Skill '{skill_id}' not found")

        safe = cls._safe_resource_rel(rel_path)
        data = cls._store().get_bytes(prefix + "/" + safe)
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

    @classmethod
    async def write_resource_file(
        cls, skill_id: str, rel_path: str, content: str,
        encoding: str = "utf8", user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """写入单个资源文件内容，并刷新资源清单与内容哈希。"""
        import base64

        async with async_session_factory() as session:
            row, row_scope = await cls._get_row(session, skill_id)
            if row_scope == "team" and (not user_id or user_id == "system"):
                raise PermissionError("团队 Skill 编辑需要登录用户身份")
            if not await cls._row_accessible(session, row, user_id):
                raise PermissionError("Skill 不存在或无权修改")

        prefix, scope = cls._resolve_prefix(skill_id)
        if prefix is None:
            raise FileNotFoundError(f"Skill '{skill_id}' not found")

        safe = cls._safe_resource_rel(rel_path)
        key = prefix + "/" + safe
        if not cls._store().exists(key):
            raise FileNotFoundError(f"资源文件不存在: {safe}")

        if encoding == "base64":
            data = base64.b64decode(content or "")
        else:
            data = (content or "").encode("utf-8")
        cls._store().put_bytes(key, data)

        # 刷新资源清单（路径可能未变，但保持与对象存储一致）与内容哈希。
        config = cls._read_store_config(prefix)
        resources = cls._scan_store_resources(prefix)
        if config.get("resources") != resources:
            config["resources"] = resources
            cls._write_store_config(prefix, config)
        row = await cls._upsert_db(skill_id, config, prefix, scope=scope)

        editor_id = user_id or "system"
        try:
            await SkillSyncService.on_skill_changed(
                skill_id=skill_id,
                user_id=editor_id,
                action="updated",
                diff_summary=f"编辑资源文件 {safe}",
            )
        except Exception as e:  # 同步通知失败不阻断保存
            logger.warning(f"[write_resource_file] 同步通知失败 skill='{skill_id}': {e}")

        if is_team:
            try:
                from app.services.project_service import mark_skill_deployments_outdated

                await mark_skill_deployments_outdated(skill_id, editor_id)
            except Exception as e:
                logger.warning(
                    f"[write_resource_file] 标记部署过期失败 skill='{skill_id}': {e}"
                )

        return {"path": safe, "content_hash": row.content_hash or ""}

    @classmethod
    async def _apply_auto_tags(
        cls, config: Dict[str, Any], body: str, *, force: bool = False
    ) -> None:
        """创建/导入时由 LLM 从固定词表分类标签，写入 config["metadata"]["tags"]。

        仅在 tags 为空（或 force）时生成；best-effort：LLM 未配置/失败一律静默跳过，
        绝不阻断创建或导入流程。
        """
        metadata = config.setdefault("metadata", {})
        if metadata.get("tags") and not force:
            return
        try:
            from app.services.llm_service import classify_skill_tags

            tags = await classify_skill_tags(
                config.get("name", ""),
                config.get("description", ""),
                body or "",
            )
            if tags:
                metadata["tags"] = tags
        except Exception as e:  # 分类失败不阻断主流程
            logger.warning(f"[auto-tags] 标签分类失败 name='{config.get('name')}': {e}")

    @classmethod
    async def create(
        cls, config: Dict[str, Any], vibeh_content: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        skill_id: str = config["name"]
        prefix = cls._personal_prefix(skill_id)

        if cls._store_exists(prefix):
            raise ValueError(f"Skill '{skill_id}' already exists")

        now = _now_iso()

        body = vibeh_content or config.pop("instructions", "") or ""

        config.setdefault("metadata", {})
        if "version" not in config.get("metadata", {}):
            config["metadata"]["version"] = config.pop("version", "1.0.0")
        config["metadata"].setdefault("author", "")
        config["metadata"].setdefault("tags", [])

        config.setdefault("_import_meta", {
            "source": "manual",
            "source_path": prefix,
            "imported_at": now,
            "incomplete_fields": [],
        })

        if not body:
            body = f"# {skill_id}\n\n在此编写 Skill 指令。\n"

        # LLM 自动分类标签（best-effort；tags 为空时才生成，失败不阻断创建）。
        await cls._apply_auto_tags(config, body)

        # 对象存储无空目录概念，scripts/references/assets 待有文件时自然出现。
        cls._write_store_config(prefix, config)

        cls._write_store_vibeh(prefix, body)

        row = await cls._upsert_db(skill_id, config, prefix, owner_id=owner_id)

        await SkillSyncService.on_skill_changed(
            skill_id=skill_id,
            user_id=config.get("_sync_user_id", "system"),
            action="created",
        )

        return cls._row_to_dict(row)

    @classmethod
    async def update(
        cls, skill_id: str, partial: Dict[str, Any],
        vibeh_content: Optional[str] = None,
        user_id: Optional[str] = None,
        create_version: bool = False,
        version_label: str = "",
    ) -> Dict[str, Any]:
        prefix, scope = cls._resolve_prefix(skill_id)
        if prefix is None:
            raise FileNotFoundError(f"Skill '{skill_id}' not found")

        is_team = scope == "team"
        existing_dict: Optional[Dict[str, Any]] = None
        base_hash = ""
        async with async_session_factory() as session:
            row, _ = await cls._get_row(session, skill_id)
            if row:
                existing_dict = cls._row_to_dict(row)
                base_hash = row.content_hash or ""
            if is_team:
                # 团队（平台）仓库改为团队成员人人可直接编辑；成员身份在 API 层鉴权。
                # 此处仅作防御：团队 Skill 编辑必须携带明确的登录用户身份。
                if not user_id or user_id == "system":
                    raise PermissionError("团队 Skill 编辑需要登录用户身份")
            if (
                isinstance(row, PersonalSkill) and user_id
                and row.owner_id and row.owner_id != user_id
            ):
                raise PermissionError("无权修改他人的个人 Skill")

        # 编辑前的原始内容快照（用于"是否有编辑/编辑了什么"的判定）
        config_old = cls._read_store_config(prefix)
        old_vibeh = cls._read_store_vibeh(prefix)

        # 在独立副本上应用本次编辑，便于与原始内容对比
        config = cls._read_store_config(prefix)

        if "instructions" in partial:
            partial.pop("instructions")

        for key, val in partial.items():
            if key in ("ui", "policy", "metadata", "dependencies", "resources", "_import_meta", "meta"):
                config.setdefault(key, {})
                if isinstance(val, dict):
                    _merge_block(config[key], val)
                else:
                    config[key] = val
            elif isinstance(val, dict):
                # 任意嵌套块（如 claude）：首次出现时 config 里还没有该键，
                # 用空字典起步再 _merge_block，确保 null 删除标记也被正确处理（不落 null 噪声）。
                if not isinstance(config.get(key), dict):
                    config[key] = {}
                _merge_block(config[key], val)
            else:
                config[key] = val

        new_vibeh = vibeh_content if vibeh_content is not None else old_vibeh

        # 团队 Skill：保存时判断是否真的有编辑，并算出"编辑了什么"用于"项目动态"。
        change_items: List[Dict[str, Any]] = []
        diff_summary = ""
        if is_team:
            if not cls._abstract_content_changed(
                config_old, config, old_vibeh, new_vibeh
            ):
                # 没有任何实质改动：不写盘、不推进版本、不记动态、不打扰其他成员。
                return {
                    "skill": existing_dict,
                    "no_change": True,
                    "diff_summary": "无改动",
                    "change_items": [],
                }

            from app.services.skill_diff_service import (
                diff_abstract_packages,
                summarize_changes,
            )

            # 网页编辑器仅改 config + SKILL 正文，不改动资源文件本身，
            # 故资源哈希两侧一致（传空字典即可），改动点聚焦字段与正文。
            base_pkg = {"config": config_old, "vibeh_body": old_vibeh, "resources": {}}
            cur_pkg = {"config": config, "vibeh_body": new_vibeh, "resources": {}}
            change_items = diff_abstract_packages(base_pkg, cur_pkg)
            diff_summary = summarize_changes(change_items)
            if diff_summary == "无改动":
                # 改动落在未列入展示白名单的字段（如资源清单），仍记一条概要动态。
                diff_summary = "更新了 Skill 内容"

        cls._write_store_config(prefix, config)

        if vibeh_content is not None:
            cls._write_store_vibeh(prefix, vibeh_content)

        row = await cls._upsert_db(skill_id, config, prefix, scope=scope)
        new_hash = row.content_hash or ""

        editor_id = user_id or partial.get("_sync_user_id", "system")
        await SkillSyncService.on_skill_changed(
            skill_id=skill_id,
            user_id=editor_id,
            action="updated",
            diff_summary=diff_summary,
            change_items=change_items,
            base_hash=base_hash,
            new_hash=new_hash,
        )

        # 团队仓库被网页编辑器直接修改保存后：把该 Skill 的所有部署实例标记为
        # 可更新/冲突，使各成员可一键拉取团队最新内容（复用既有推送链路语义）。
        if is_team:
            from app.services.project_service import mark_skill_deployments_outdated

            await mark_skill_deployments_outdated(skill_id, editor_id)

        version = None
        if create_version:
            try:
                from app.services.skill_version_service import SkillVersionService

                version = await SkillVersionService.create_version(
                    skill_id,
                    created_by=editor_id,
                    source="web_edit",
                    label=version_label or "",
                    change_summary=diff_summary,
                    change_items=change_items,
                )
            except Exception as e:
                logger.warning(f"[update] 创建版本快照失败 skill='{skill_id}': {e}")

        return {
            "skill": cls._row_to_dict(row),
            "no_change": False,
            "diff_summary": diff_summary,
            "change_items": change_items,
            "version": version,
        }

    @staticmethod
    def _abstract_content_changed(
        old_cfg: Dict[str, Any],
        new_cfg: Dict[str, Any],
        old_body: str,
        new_body: str,
    ) -> bool:
        """判断一次编辑是否产生了实质内容改动（忽略仅时间戳类的易变元数据）。

        正文按与 diff 引擎一致的规则规整后再比，避免「仅尾部空白/空行/换行符」
        被误判为改动。"""
        from app.services.skill_diff_service import _normalize_body_lines

        if _normalize_body_lines(old_body or "") != _normalize_body_lines(new_body or ""):
            return True
        volatile = {"_import_meta", "meta"}
        a = {k: v for k, v in (old_cfg or {}).items() if k not in volatile}
        b = {k: v for k, v in (new_cfg or {}).items() if k not in volatile}
        return a != b

    @classmethod
    async def delete(cls, skill_id: str, user_id: str = "system") -> bool:
        async with async_session_factory() as session:
            row, scope = await cls._get_row(session, skill_id)
            # 团队 Skill 的成员归属校验在 API 层完成（与 update 一致）；服务层仅校验个人归属。
            if (
                isinstance(row, PersonalSkill) and user_id and user_id != "system"
                and row.owner_id and row.owner_id != user_id
            ):
                raise PermissionError("无权删除他人的个人 Skill")

        await SkillSyncService.on_skill_changed(
            skill_id=skill_id,
            user_id=user_id,
            action="deleted",
        )

        prefix, _ = cls._resolve_prefix(skill_id)
        if prefix:
            cls._store().delete_prefix(prefix)

        async with async_session_factory() as session:
            # 团队 Skill 的成员部署记录需显式清理，不依赖 DB 外键级联，保证跨引擎一致；
            # project_skills 关联已由 on_skill_changed(action="deleted") 一并清理。
            await session.execute(
                delete(UserSkillDeployment).where(
                    UserSkillDeployment.team_skill_id == skill_id
                )
            )
            await session.execute(
                delete(PersonalSkill).where(PersonalSkill.id == skill_id)
            )
            await session.execute(
                delete(TeamSkill).where(TeamSkill.id == skill_id)
            )
            await session.commit()

        # 清理该 Skill 的版本记录与磁盘资源快照（best-effort，不阻断删除）。
        try:
            from app.services.skill_version_service import SkillVersionService

            await SkillVersionService.cleanup_skill(skill_id)
        except Exception as e:
            logger.warning(f"[delete] 清理版本记录失败 skill='{skill_id}': {e}")

        return True

    # ------------------------------------------------------------------
    # Import from external terminal skill
    # ------------------------------------------------------------------

    @classmethod
    async def import_from_external(
        cls,
        source_path: str,
        origin: Optional[str] = None,
        allow_team_update: bool = False,
        target_skill_id: Optional[str] = None,
        owner_id: Optional[str] = None,
        source_url: Optional[str] = None,
        team_id: Optional[str] = None,
        team_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        从外部 Cursor/Codex skill 目录导入为平台原生 skill。

        导入时不补齐缺失字段，仅标记 _import_meta.incomplete_fields。
        补齐在部署时由 LLM 完成，需用户手动确认。

        source_url 非空时（从远程链接导入）记入 _import_meta.source_url 供溯源。
        """
        src = Path(source_path)
        skill_md = src / "SKILL.md"
        if not skill_md.exists():
            raise FileNotFoundError(f"No SKILL.md found at {source_path}")

        frontmatter, body = _parse_skill_md(skill_md)

        detected_origin = origin or _detect_origin(src, frontmatter)

        config: Dict[str, Any] = {
            "name": frontmatter.get("name", src.name),
            "description": frontmatter.get("description", ""),
        }

        if frontmatter.get("disable-model-invocation") is True:
            config["policy"] = {"auto_invoke": False}

        if frontmatter.get("metadata", {}).get("surfaces"):
            config.setdefault("metadata", {})["surfaces"] = frontmatter["metadata"]["surfaces"]

        # Claude Code 专有运行时 frontmatter → claude 块（反向导入 round-trip）。
        # 按字段存在性捕获，不依赖 origin 判定，保证最大保真。
        _fm_to_claude = {
            "allowed-tools": "allowed_tools",
            "disallowed-tools": "disallowed_tools",
            "user-invocable": "user_invocable",
            "argument-hint": "argument_hint",
            "when_to_use": "when_to_use",
            "model": "model",
            "effort": "effort",
            "context": "context",
            "agent": "agent",
            "hooks": "hooks",
        }
        claude_block: Dict[str, Any] = {}
        for fm_key, cfg_key in _fm_to_claude.items():
            if frontmatter.get(fm_key) is not None:
                claude_block[cfg_key] = frontmatter[fm_key]
        if claude_block:
            config["claude"] = claude_block

        # Claude 标准元数据 frontmatter → metadata 块
        if frontmatter.get("license"):
            config.setdefault("metadata", {})["license"] = frontmatter["license"]
        if frontmatter.get("compatibility"):
            config.setdefault("metadata", {})["compatibility"] = frontmatter["compatibility"]
        fm_meta = frontmatter.get("metadata", {})
        if isinstance(fm_meta, dict):
            if fm_meta.get("author"):
                config.setdefault("metadata", {})["author"] = fm_meta["author"]
            if fm_meta.get("version"):
                config.setdefault("metadata", {})["version"] = fm_meta["version"]

        openai_yaml_path = src / "agents" / "openai.yaml"
        if openai_yaml_path.exists():
            oa = _read_yaml(openai_yaml_path)
            interface = oa.get("interface", {})
            ui: Dict[str, Any] = {}
            if interface.get("display_name"):
                ui["display_name"] = interface["display_name"]
            if interface.get("short_description"):
                ui["short_description"] = interface["short_description"]
            if interface.get("brand_color"):
                ui["brand_color"] = interface["brand_color"]
            if interface.get("icon_small"):
                ui["icon_small"] = interface["icon_small"]
            if interface.get("icon_large"):
                ui["icon_large"] = interface["icon_large"]
            if interface.get("default_prompt"):
                ui["default_prompt"] = interface["default_prompt"]
            if ui:
                config["ui"] = ui

            policy = oa.get("policy", {})
            if "allow_implicit_invocation" in policy:
                config.setdefault("policy", {})["auto_invoke"] = policy["allow_implicit_invocation"]

            deps_tools = oa.get("dependencies", {}).get("tools")
            if deps_tools:
                config.setdefault("dependencies", {})["tools"] = deps_tools

        # 推送/提升回写团队仓库时，技能 id（= target_skill_id）必须保持稳定
        # （它是 DB 主键、store 目录名与 deployment.team_skill_id 的引用）。
        # 但本地若把 name 改成与 id 不同的值，视为「重命名」意图，落到友好显示名
        # (ui.display_name) 上，使平台卡片标题与本地保持一致。
        if target_skill_id:
            local_name = config.get("name")
            if (
                local_name
                and local_name != target_skill_id
                and not config.get("ui", {}).get("display_name")
            ):
                config.setdefault("ui", {})["display_name"] = local_name

        from app.services.llm_service import detect_incomplete_fields
        incomplete = detect_incomplete_fields(config, source=detected_origin)

        config["_import_meta"] = {
            "source": detected_origin,
            "source_path": str(src),
            "imported_at": _now_iso(),
            "incomplete_fields": incomplete,
        }
        if source_url:
            config["_import_meta"]["source_url"] = source_url

        config.setdefault("meta", {})
        config["meta"]["importedFrom"] = detected_origin
        config["meta"]["createdAt"] = _now_iso()
        config["meta"]["updatedAt"] = _now_iso()

        # LLM 自动分类标签（best-effort；导入源未带 metadata.tags 时才生成，失败不阻断导入）。
        # 该处收口覆盖 import / import-content / import-url / import_external_to_team 全部导入路径。
        await cls._apply_auto_tags(config, body)

        # 拆表路由：allow_team_update ⟹ 写团队表（target_skill_id 即团队代理 id）；
        # 否则写个人表。团队在独立表，个人导入永远不会与团队同名冲突。
        scope = "team" if allow_team_update else "personal"

        if scope == "team":
            if not target_skill_id:
                raise ValueError("团队写回必须提供 target_skill_id")
            skill_id = target_skill_id
            config["name"] = target_skill_id
            prefix = cls._team_prefix(skill_id)
        else:
            skill_id = config["name"]
            # 个人导入仅与「他人已占用的同名个人 Skill」冲突 → 分配新 id 作独立快照。
            async with async_session_factory() as session:
                existing = await session.get(PersonalSkill, skill_id)
                if (
                    existing and existing.owner_id and owner_id
                    and existing.owner_id != owner_id
                ):
                    base = skill_id
                    candidate = base
                    n = 1
                    while (
                        await session.get(PersonalSkill, candidate) is not None
                        or cls._store_exists(cls._personal_prefix(candidate))
                    ):
                        n += 1
                        candidate = f"{base}-{n}"
                    if not config.get("ui", {}).get("display_name"):
                        config.setdefault("ui", {})["display_name"] = base
                    config["name"] = candidate
                    skill_id = candidate
            prefix = cls._personal_prefix(skill_id)

        # 覆盖语义：先清空目标前缀，再写入。
        cls._store().delete_prefix(prefix)
        cls._write_store_config(prefix, config)
        cls._write_store_vibeh(prefix, body)

        # 从本地临时源把资源文件逐个上传到对象存储（源为瞬时处理目录）。
        for sub in ("scripts", "references", "assets"):
            src_sub = src / sub
            if src_sub.is_dir():
                for f in sorted(src_sub.rglob("*")):
                    if f.is_file():
                        rel = f.relative_to(src).as_posix()
                        cls._store().put_bytes(prefix + "/" + rel, f.read_bytes())

        resources = cls._scan_store_resources(prefix)
        if any(resources.values()):
            config["resources"] = resources
            cls._write_store_config(prefix, config)

        license_src = src / "LICENSE.txt"
        if not license_src.exists():
            license_src = src / "LICENSE"
        if license_src.exists():
            cls._store().put_bytes(prefix + "/LICENSE", license_src.read_bytes())

        if scope == "team":
            row = await cls._upsert_db(
                skill_id, config, prefix, scope="team",
                team_id=team_id, name=team_name,
            )
        else:
            row = await cls._upsert_db(
                skill_id, config, prefix, scope="personal", owner_id=owner_id
            )
        return cls._row_to_dict(row)

    # ------------------------------------------------------------------
    # 方案 B · M4：按 contents 导入（薄代理，云端不读后端用户磁盘）
    # ------------------------------------------------------------------

    @classmethod
    async def import_from_content(
        cls,
        files: List[Dict[str, Any]],
        origin: Optional[str] = None,
        owner_id: Optional[str] = None,
        scope: str = "personal",
        team_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """按上传的 files[] 导入：写临时目录后复用既有外部导入解析逻辑。

        前端经本地代理 read-folder 读取本地 skill 文件夹并上传 files[]（M0 §3.5）。
        云端在临时目录重建后：scope=personal → import_from_external（个人，归属
        owner_id）；scope=team → import_external_to_team（团队，需 team_id）。
        """
        # 延迟导入避免与 content_transfer 形成模块级循环依赖
        from app.services.content_transfer import write_files

        if not files:
            raise ValueError("未提供任何文件内容")

        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "skill"
            write_files(src, files)
            if not (src / "SKILL.md").exists():
                raise FileNotFoundError("上传内容缺少 SKILL.md")

            if scope == "team":
                if not team_id:
                    raise ValueError("scope=team 时必须提供 team_id")
                return await cls.import_external_to_team(
                    str(src), team_id, owner_id or "", origin=origin
                )
            return await cls.import_from_external(
                str(src), origin, owner_id=owner_id
            )

    # ------------------------------------------------------------------
    # Copy personal skill into team repository
    # ------------------------------------------------------------------

    @classmethod
    async def copy_to_team(
        cls, skill_id: str, team_id: str, user_id: str
    ) -> Dict[str, Any]:
        """将个人 skill 复制一份到团队仓库（scope=team），个人仓库保留原件。

        新记录使用独立 id（带团队后缀），并通过 source_skill_id 溯源到原个人 skill。
        """
        src_prefix = cls._personal_prefix(skill_id)
        if not cls._store_exists(src_prefix):
            raise FileNotFoundError(f"Skill '{skill_id}' not found")

        async with async_session_factory() as session:
            src = await session.get(PersonalSkill, skill_id)
        if src is None:
            raise PermissionError("只能将个人 Skill 放入团队仓库")
        if src.owner_id and src.owner_id != user_id:
            raise PermissionError("无权操作他人的个人 Skill")

        new_id = f"{skill_id}-team-{team_id[:8]}"
        new_prefix = cls._team_prefix(new_id)
        if cls._store_exists(new_prefix):
            raise ValueError("该 Skill 已放入该团队仓库")

        # 对象存储服务端逐对象复制 personal/{id} → team/{new_id}
        cls._store().copy_prefix(src_prefix, new_prefix)

        config = cls._read_store_config(new_prefix)
        orig_display = (
            config.get("ui", {}).get("display_name")
            or config.get("display_name")
            or src.display_name
            or skill_id
        )
        config["name"] = new_id
        config.setdefault("ui", {})["display_name"] = orig_display
        config["scope"] = "team"
        config["team_id"] = team_id
        config["source_skill_id"] = skill_id
        cls._write_store_config(new_prefix, config)

        await cls._upsert_db(
            new_id, config, new_prefix, scope="team",
            team_id=team_id, source_skill_id=skill_id, name=skill_id,
        )

        async with async_session_factory() as session:
            row = await session.get(TeamSkill, new_id)
            await session.refresh(row)
            result = cls._row_to_dict(row)

        # 团队级实时同步：通知在线成员刷新团队 Skill 仓库
        await TeamSyncService.emit_team_skill_added(team_id, result, user_id)
        return result

    # ------------------------------------------------------------------
    # Import a local folder directly into team repository
    # ------------------------------------------------------------------

    @classmethod
    async def import_external_to_team(
        cls,
        source_path: str,
        team_id: str,
        user_id: str,
        origin: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """从本地文件夹直接导入为团队（平台）仓库 Skill（scope=team）。

        不在个人仓库留存副本：使用带团队后缀的稳定 id，复用通用外部导入逻辑落盘，
        随后把配置与 DB 记录标记为团队 scope。原始 SKILL.md 名作为友好显示名。
        """
        src = Path(source_path)
        skill_md = src / "SKILL.md"
        if not skill_md.exists():
            raise FileNotFoundError(f"所选文件夹缺少 SKILL.md：{source_path}")

        frontmatter, _ = _parse_skill_md(skill_md)
        base_name = frontmatter.get("name") or src.name
        new_id = f"{base_name}-team-{team_id[:8]}"

        new_prefix = cls._team_prefix(new_id)
        if cls._store_exists(new_prefix):
            raise ValueError("该 Skill 已存在于团队仓库（同名）")

        # 复用通用外部导入逻辑：落到团队专属 id（写团队表）；原名作为 name/显示名。
        await cls.import_from_external(
            source_path,
            origin,
            allow_team_update=True,
            target_skill_id=new_id,
            owner_id=None,
            source_url=source_url,
            team_id=team_id,
            team_name=base_name,
        )

        # 团队元数据落入 config，供 _sync_from_filesystem 重建时识别。
        config = cls._read_store_config(new_prefix)
        config["scope"] = "team"
        config["team_id"] = team_id
        cls._write_store_config(new_prefix, config)

        async with async_session_factory() as session:
            row = await session.get(TeamSkill, new_id)
            if row is None:
                raise FileNotFoundError("导入失败：未生成 Skill 记录")
            await session.refresh(row)
            result = cls._row_to_dict(row)

        # 团队级实时同步：通知在线成员刷新团队 Skill 仓库
        await TeamSyncService.emit_team_skill_added(team_id, result, user_id)
        return result

    # ------------------------------------------------------------------
    # LLM 补齐缺失字段
    # ------------------------------------------------------------------

    @classmethod
    async def complete_fields(
        cls, skill_id: str
    ) -> Dict[str, Any]:
        """
        调用 LLM 为 skill 的缺失字段生成建议值。
        返回 { incomplete_fields, suggestions }，不自动写入——需用户确认。
        """
        prefix, _ = cls._resolve_prefix(skill_id)
        if prefix is None:
            raise FileNotFoundError(f"Skill '{skill_id}' not found")

        config = cls._read_store_config(prefix)

        from app.services.llm_service import detect_incomplete_fields, complete_skill_fields

        incomplete = detect_incomplete_fields(config)
        if not incomplete:
            return {"incomplete_fields": [], "suggestions": {}}

        body_preview = cls._read_store_vibeh(prefix)[:500]

        suggestions = await complete_skill_fields(config, body_preview, incomplete)

        return {
            "incomplete_fields": incomplete,
            "suggestions": suggestions,
        }

    @classmethod
    async def regenerate_tags(
        cls, skill_id: str, *, force: bool = False
    ) -> List[str]:
        """为已存在的 skill 重新（或首次）生成标签并落库。

        force=False（默认）仅在 tags 为空时生成，便于存量回填；force=True 强制重生成。
        返回最终标签列表。供回填脚本与手动重生成端点复用。
        """
        prefix, scope = cls._resolve_prefix(skill_id)
        if prefix is None:
            raise FileNotFoundError(f"Skill '{skill_id}' not found")

        config = cls._read_store_config(prefix)
        body = cls._read_store_vibeh(prefix)

        await cls._apply_auto_tags(config, body, force=force)

        cls._write_store_config(prefix, config)
        row = await cls._upsert_db(skill_id, config, prefix, scope=scope)
        return _normalize_tags(row.tags)

    # ------------------------------------------------------------------
    # Build & Deploy
    # ------------------------------------------------------------------

    @classmethod
    async def _get_ts_yaml(cls, skill_id: str) -> str:
        """读取 config + SKILL.md，转换为 TS bridge 期望的 YAML 格式"""
        prefix, _ = cls._resolve_prefix(skill_id)
        if prefix is None:
            raise FileNotFoundError(f"Skill '{skill_id}' not found")

        config = cls._read_store_config(prefix)
        vibeh_content = cls._read_store_vibeh(prefix)

        ts_config = _config_to_ts_format(config, vibeh_content)
        return yaml.dump(ts_config, allow_unicode=True, sort_keys=False)

    @classmethod
    async def build(
        cls, skill_id: str, target: str
    ) -> Dict[str, Any]:
        """构建 native skill 到目标平台（不部署）"""
        yaml_content = await cls._get_ts_yaml(skill_id)
        result = await call_bridge("build", {"yaml": yaml_content, "target": target})
        if not result.get("success"):
            raise RuntimeError(result.get("error", "build failed"))
        return result

    @classmethod
    async def deploy(
        cls, skill_id: str, target: str,
        dest_path: Optional[str] = None,
        notify: bool = True,
        allow_team: bool = False,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        构建并部署 native skill。

        dest_path 为空时部署到平台目录（~/.cursor/skills 或 ~/.codex/skills）,
        非空时部署到用户指定的项目目录。
        """
        prefix, scope = cls._resolve_prefix(skill_id)
        if prefix is None:
            raise FileNotFoundError(f"Skill '{skill_id}' not found")

        async with async_session_factory() as session:
            row, _ = await cls._get_row(session, skill_id)
            if scope == "team" and not allow_team:
                raise PermissionError(
                    "Team repository skills must be deployed from a project"
                )
            if (
                isinstance(row, PersonalSkill) and user_id
                and row.owner_id and row.owner_id != user_id
            ):
                raise PermissionError("无权部署他人的个人 Skill")

        yaml_content = await cls._get_ts_yaml(skill_id)

        result = await call_bridge("build", {"yaml": yaml_content, "target": target})
        if not result.get("success"):
            raise RuntimeError(result.get("error", "build failed"))

        build_outputs = result.get("data", [])
        deployed = []

        for output in build_outputs:
            contents: Dict[str, str] = output.get("contents", {})
            if not contents:
                continue

            out_target = output.get("target", target)

            if dest_path:
                project_root = Path(dest_path)
                if out_target == "cursor":
                    dest_root = project_root / ".cursor" / "skills"
                elif out_target == "windsurf":
                    dest_root = project_root / ".windsurf" / "skills"
                elif out_target == "claude":
                    dest_root = project_root / ".claude" / "skills"
                elif out_target == "kiro":
                    dest_root = project_root / ".kiro" / "skills"
                elif out_target == "trae":
                    dest_root = project_root / ".trae" / "skills"
                elif out_target == "qoder":
                    dest_root = project_root / ".qoder" / "skills"
                elif out_target == "workbuddy":
                    dest_root = project_root / ".workbuddy" / "skills"
                else:
                    dest_root = project_root / ".codex" / "skills"
            elif out_target == "cursor":
                dest_root = CURSOR_SKILLS_DIR
            elif out_target == "windsurf":
                dest_root = WINDSURF_SKILLS_DIR
            elif out_target == "claude":
                dest_root = CLAUDE_SKILLS_DIR
            elif out_target == "kiro":
                dest_root = KIRO_SKILLS_DIR
            elif out_target == "trae":
                dest_root = trae_skills_dir()
            elif out_target == "qoder":
                dest_root = qoder_skills_dir()
            elif out_target == "workbuddy":
                dest_root = workbuddy_skills_dir()
            else:
                dest_root = CODEX_SKILLS_DIR

            dest_dir = dest_root / skill_id
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            dest_dir.mkdir(parents=True, exist_ok=True)

            for rel_path, content in contents.items():
                file_path = dest_dir / rel_path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content, encoding="utf-8")

            # 从对象存储把资源文件物化到目标目录（仅 scripts/references/assets）。
            store = cls._store()
            base = prefix.rstrip("/") + "/"
            for key in store.list(base):
                rel = key[len(base):]
                top = rel.split("/", 1)[0] if "/" in rel else ""
                if top in ("scripts", "references", "assets"):
                    data = store.get_bytes(key)
                    if data is None:
                        continue
                    out = dest_dir / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(data)

            deploy_label = "project" if dest_path else out_target
            deployed.append({"target": deploy_label, "path": str(dest_dir)})

        # 更新 DB 部署状态
        config = cls._read_store_config(prefix)
        await cls._upsert_db(skill_id, config, prefix, scope=scope)

        if notify:
            await SkillSyncService.on_skill_changed(
                skill_id=skill_id,
                user_id="system",
                action="deployed",
                diff_summary=f"deployed to {', '.join(d['target'] for d in deployed)}",
            )

        return {"success": True, "deployed": deployed}

    @classmethod
    async def preview(
        cls, skill_id: str, target: str = "all"
    ) -> Dict[str, Any]:
        yaml_content = await cls._get_ts_yaml(skill_id)
        result = await call_bridge("preview", {"yaml": yaml_content, "target": target})
        if not result.get("success"):
            raise RuntimeError(result.get("error", "preview failed"))
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _row_to_dict(cls, row) -> Dict[str, Any]:
        is_team = isinstance(row, TeamSkill)
        return {
            "id": row.id,
            "name": row.name if is_team else row.id,
            "display_name": row.display_name,
            "description": row.description,
            "short_description": row.short_description,
            "version": _normalize_version(row.version),
            "tags": _normalize_tags(row.tags),
            "imported_from": row.imported_from,
            "store_path": row.store_path,
            "scope": "team" if is_team else "personal",
            "team_id": row.team_id if is_team else None,
            "owner_id": None if is_team else row.owner_id,
            "source_skill_id": row.source_skill_id if is_team else None,
            "content_hash": row.content_hash,
            "deployed_cursor": row.deployed_cursor,
            "deployed_codex": row.deployed_codex,
            "deployed_windsurf": row.deployed_windsurf,
            "deployed_claude": row.deployed_claude,
            "deployed_kiro": row.deployed_kiro,
            "deployed_trae": row.deployed_trae,
            "deployed_qoder": row.deployed_qoder,
            "deployed_workbuddy": row.deployed_workbuddy,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    @classmethod
    async def migrate_orphan_owners(cls) -> int:
        """将无主的个人 Skill 归属给系统首个用户（按 created_at 最早）。"""
        async with async_session_factory() as session:
            first_user_id = (
                await session.execute(
                    select(User.id).order_by(User.created_at).limit(1)
                )
            ).scalar_one_or_none()
            if not first_user_id:
                return 0
            result = await session.execute(
                update(PersonalSkill)
                .where(PersonalSkill.owner_id.is_(None))
                .values(owner_id=first_user_id)
            )
            await session.commit()
            return int(result.rowcount or 0)

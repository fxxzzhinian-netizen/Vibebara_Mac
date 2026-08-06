from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class _SkillColumnsMixin:
    """个人 / 团队 Skill 共用列（数据层拆表后两表复用）。

    拆表说明（docs/design/ide-import.md 后续设计）：原单表 `skill_packages` 用 `scope`
    字段区分个人/团队，现拆为 `personal_skills` 与 `team_skills` 两张物理表实现数据层隔离。
    scope 由「所在表」隐含，不再有 scope 列。
    """

    display_name: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    short_description: Mapped[str] = mapped_column(String(256), default="")
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    imported_from: Mapped[str | None] = mapped_column(String(16), nullable=True)
    store_path: Mapped[str] = mapped_column(String(512), default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    deployed_cursor: Mapped[bool] = mapped_column(Boolean, default=False)
    deployed_codex: Mapped[bool] = mapped_column(Boolean, default=False)
    deployed_windsurf: Mapped[bool] = mapped_column(Boolean, default=False)
    deployed_claude: Mapped[bool] = mapped_column(Boolean, default=False)
    deployed_kiro: Mapped[bool] = mapped_column(Boolean, default=False)
    deployed_trae: Mapped[bool] = mapped_column(Boolean, default=False)
    deployed_qoder: Mapped[bool] = mapped_column(Boolean, default=False)
    deployed_workbuddy: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PersonalSkill(_SkillColumnsMixin, Base):
    """个人 Skill 仓库（scope=personal）。

    `id` 为内部 UUID；`name` 为用户可见自然名，并在 owner 维度唯一。
    对象存储落 `skills/personal/{owner_id}/{id}/`。
    """

    __tablename__ = "personal_skills"
    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_personal_skill_owner_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )


class TeamSkill(_SkillColumnsMixin, Base):
    """团队 Skill 仓库（scope=team）。

    PK `id` 为单列代理键 `{自然名}-team-{team_id[:8]}`（每个 (team, 自然名) 唯一），
    `name` 为自然名（可与个人仓库同名）。磁盘落 `{SKILL_STORE_DIR}/team/{id}/`。
    `project_skills.skill_id` 与 `user_skill_deployments.team_skill_id` 外键均指向本表 id。
    """

    __tablename__ = "team_skills"
    __table_args__ = (
        UniqueConstraint("team_id", "name", name="uq_team_skill_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    team_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("teams.id"), index=True
    )
    # 软引用 personal_skills.id（从个人复制到团队时的溯源），不建 DB 外键。
    source_skill_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 遗留字段：早期把项目 id 挂在 Skill 行上，现以 project_skills 关联为准。
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=True
    )

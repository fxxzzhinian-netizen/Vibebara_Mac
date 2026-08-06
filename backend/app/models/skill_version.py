import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SkillVersion(Base):
    """团队 Skill 的「版本快照」。

    与 `skill_change_log`（每次推送都自动记一条审计流）不同：版本是**用户显式选择**
    "更新版本号"时才落的一条**完整内容快照**，可在 Skill 详情页查看与回滚。

    - `seq`：该 Skill 维度单调递增的内部排序键。
    - `version_number`：用户可见的 x.y 版本号（v1.1/v1.2…）。
    - `config_json` / `vibeh_content`：当次完整内容快照，用于查看历史版本与回滚还原。
    - `source`：`push`（部署实例推送）/ `web_edit`（团队仓库网页编辑器保存）/ `restore`（回滚）。
    """

    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint(
            "skill_id",
            "version_number",
            name="uq_skill_versions_skill_version_number",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    skill_id: Mapped[str] = mapped_column(String(64), index=True)
    team_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    version_number: Mapped[str] = mapped_column(String(32), default="1.1")
    label: Mapped[str] = mapped_column(String(128), default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    vibeh_content: Mapped[str] = mapped_column(Text, default="")
    # 资源文件清单 {相对路径: sha256}（脚本/引用/资源）。实际文件字节快照落在磁盘
    # {data_dir}/skill_versions/{skill_id}/{version_id}/ 下，回滚时据此还原。
    resources_json: Mapped[str] = mapped_column(Text, default="{}")
    change_summary: Mapped[str] = mapped_column(Text, default="")
    change_items: Mapped[str] = mapped_column(Text, default="[]")
    source: Mapped[str] = mapped_column(String(32), default="push")
    created_by: Mapped[str] = mapped_column(String(36), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

import ssl
from typing import Any, Dict

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


def _build_connect_args() -> Dict[str, Any]:
    """构造 aiomysql 连接参数；仅在配置 TLS 时注入 ssl context（供托管 MySQL）。"""
    connect_args: Dict[str, Any] = {}
    if settings.DB_SSL_ENABLED or settings.DB_SSL_CA:
        ctx = ssl.create_default_context(
            cafile=settings.DB_SSL_CA or None
        )
        if not settings.DB_SSL_VERIFY:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ctx
    return connect_args


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.db_echo,
    pool_pre_ping=settings.DB_POOL_PRE_PING,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    connect_args=_build_connect_args(),
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """开发兜底：自动建表 + 增量补列。

    受 settings.DB_AUTO_CREATE 控制（默认 True，保持现有首次启动自动可用）。
    云端用 Alembic 管理 schema 时，可设 DB_AUTO_CREATE=false 并改用
    `alembic upgrade head`。
    """
    if not settings.DB_AUTO_CREATE:
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _migrate_add_columns()


async def _migrate_add_columns() -> None:
    """为已有表补充新增列（幂等，列已存在则跳过）"""
    # 注：个人/团队 Skill 已从单表 skill_packages 拆为 personal_skills / team_skills
    # 两张物理表，新表由 create_all 直接建出完整列，无需在此增量补列。
    migrations = [
        ("teams", "auto_skill_hot_update", "TINYINT(1) NOT NULL DEFAULT 0"),
        # WorkBuddy 部署态列：存量 personal_skills / team_skills 表升级补列
        # （新表由 create_all 直接含完整 deployed_* 列）。
        ("personal_skills", "deployed_workbuddy", "TINYINT(1) NOT NULL DEFAULT 0"),
        ("team_skills", "deployed_workbuddy", "TINYINT(1) NOT NULL DEFAULT 0"),
        ("skill_change_log", "team_id", "VARCHAR(36) NULL"),
        ("skill_change_log", "deployment_id", "VARCHAR(36) NULL"),
        ("skill_change_log", "source", "VARCHAR(32) NOT NULL DEFAULT 'team_repo'"),
        ("skill_change_log", "base_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("skill_change_log", "new_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("skill_change_log", "change_items", "TEXT NULL"),
        ("user_skill_deployments", "abstract_snapshot", "LONGTEXT NULL"),
        ("user_skill_deployments", "local_dirty", "TINYINT(1) NOT NULL DEFAULT 0"),
        # 团队 Skill 版本记录：资源清单列（存量表升级补列；新表由 create_all 直接含）。
        ("skill_versions", "resources_json", "TEXT NULL"),
        # 注册邀请码：记录用户注册时消费的码（invite_codes 新表由 create_all 直接建）。
        ("users", "invite_code_used", "VARCHAR(16) NULL"),
        # 首次登录引导：完成标记 + 场景偏好 + 最常用工具（存量表升级补列）。
        ("users", "onboarded", "TINYINT(1) NOT NULL DEFAULT 0"),
        ("users", "dev_mode", "VARCHAR(16) NULL"),
        ("users", "favorite_tool", "VARCHAR(32) NULL"),
        # 平台管理员标记：可审核 SKILL 市场发布（种子用户除外，按用户名判定）。
        ("users", "is_platform_admin", "TINYINT(1) NOT NULL DEFAULT 0"),
        # 个人资料：均允许为空，display_name/email/avatar_url 为 users 表既有列。
        ("users", "phone", "VARCHAR(32) NULL"),
        ("users", "gender", "VARCHAR(16) NULL"),
        ("users", "birthday", "DATE NULL"),
        ("users", "locale", "VARCHAR(16) NULL"),
        ("users", "location", "VARCHAR(256) NULL"),
    ]
    async with engine.begin() as conn:
        for table, column, col_def in migrations:
            check_sql = (
                f"SELECT COUNT(*) FROM information_schema.COLUMNS "
                f"WHERE TABLE_SCHEMA = DATABASE() "
                f"AND TABLE_NAME = '{table}' "
                f"AND COLUMN_NAME = '{column}'"
            )
            from sqlalchemy import text
            result = await conn.execute(text(check_sql))
            exists = result.scalar()
            if not exists:
                alter_sql = f"ALTER TABLE `{table}` ADD COLUMN `{column}` {col_def}"
                await conn.execute(text(alter_sql))
                print(f"  [迁移] 已添加列: {table}.{column}")

        from sqlalchemy import text
        try:
            await conn.execute(text(
                "ALTER TABLE `skill_change_log` MODIFY COLUMN `action` VARCHAR(32) NOT NULL"
            ))
        except Exception:
            pass


async def close_db() -> None:
    await engine.dispose()

import os
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings

# backend 根目录（config.py 位于 backend/app/core/config.py → parents[2] = backend）
_BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    APP_NAME: str = "Vibebara"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    # 运行模式开关（方案 B M1）：
    #   "local" = 浏览器+后端+用户文件同机的现状形态（默认，保持兼容）
    #   "cloud" = 云端中央后端，不依赖本地用户文件、不轮询本地部署目录
    DEPLOYMENT_MODE: Literal["local", "cloud"] = "local"

    # 监听地址/端口（云端通常由反向代理/HTTPS 终止，这里仅代码层可配置）
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # ------------------------------------------------------------------
    # 数据库
    # ------------------------------------------------------------------
    DATABASE_URL: str = "mysql+aiomysql://root:@localhost:3306/cowork?charset=utf8mb4"

    # 连接池（供托管 MySQL 调优；默认值与既有 database.py 行为一致）
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_PRE_PING: bool = False
    # SQL echo：None → 跟随 DEBUG（保持现状）；显式 True/False 可覆盖
    DB_ECHO: Optional[bool] = None
    # 启动时自动建表（init_db 的 create_all + 增量列迁移）。
    # 开发/本地默认开启作为兜底；云端用 Alembic 管理时可设为 false。
    DB_AUTO_CREATE: bool = True

    # 托管 MySQL TLS（默认关闭，不影响本地明文连接）
    DB_SSL_ENABLED: bool = False
    DB_SSL_CA: str = ""          # CA 证书路径（设置后自动启用 TLS）
    DB_SSL_VERIFY: bool = True   # 是否校验服务端证书/主机名

    # ------------------------------------------------------------------
    # CORS / 来源
    # ------------------------------------------------------------------
    ALLOWED_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]
    # 桌面端来源（Electron）匹配：file:// 的 Origin 多为 "null"，app://、自定义 scheme
    # 需用正则匹配。默认空字符串=不启用（不影响本地开发）。
    # 示例：^(app|vibebara|file)://.*$
    ALLOW_ORIGIN_REGEX: str = ""

    # ------------------------------------------------------------------
    # 安全 / 鉴权（方案 B M2）
    # ------------------------------------------------------------------
    # 独立的 token 签名密钥（历史遗留：Token 根治后已不参与校验，统一凭据为
    # auth_tokens 表的不可猜随机串 + sha256 落库）。保留字段仅为兼容既有环境注入，
    # 当前无实际作用，可后续清理。
    JWT_SECRET: str = ""

    # 登录态（session）凭据有效期（秒），默认 7 天。长期凭据（PAT）默认无过期。
    SESSION_TOKEN_TTL_SECONDS: int = 7 * 24 * 3600

    # ------------------------------------------------------------------
    # 滑块人机验证（登录/注册）
    # ------------------------------------------------------------------
    # True = 登录/注册必须携带滑块验证 token（默认）；本地开发/脚本调试可设 false。
    # 挑战与 token 为进程内存态，依赖单进程部署（同 WS hub 约束）。
    CAPTCHA_REQUIRED: bool = True

    # ------------------------------------------------------------------
    # 注册邀请码（测试版收口注册入口）
    # ------------------------------------------------------------------
    # True = 注册必须提供有效邀请码（种子用户不受影响）；本地开发可设 false 放开。
    INVITE_CODE_REQUIRED: bool = True
    # 邀请码管理端点（签发/列表/禁用）的管理员用户名白名单。
    # 默认无人具备用户名白名单权限；生产按需经 JSON 环境变量显式注入。
    ADMIN_USERNAMES: List[str] = []

    # SKILL 市场审核员用户名白名单；生产按需显式配置。
    MARKET_SEED_REVIEWERS: List[str] = []

    # ------------------------------------------------------------------
    # 预设种子用户（启动时幂等创建 DAIL/DAIL2）
    # ------------------------------------------------------------------
    # True = 仅本地开发时创建文档化预设账号；cloud 模式禁止启用。
    SEED_USERS_ENABLED: bool = False

    # ------------------------------------------------------------------
    # 数据目录 / Skill 存储（去 user-home 语义耦合）
    # ------------------------------------------------------------------
    # 显式数据根目录。空 → 取环境变量 COWORK_DATA_DIR；再空 → backend/data。
    # 不再隐含 Path.home()，Windows/Linux 通用。
    COWORK_DATA_DIR: str = ""
    SKILL_SCAN_DIR: str = ""
    # 平台原生 skill 集中存储目录。空 → {data_dir}/skills。仅 STORAGE_BACKEND=local 使用。
    SKILL_STORE_DIR: str = ""

    # ------------------------------------------------------------------
    # 对象存储（Skill 持久化后端）
    # ------------------------------------------------------------------
    # "local" = 本地文件系统（开发默认，键映射到 COWORK_DATA_DIR 下）；
    # "cos"   = 腾讯云 COS 对象存储（生产，需配 COS_* 凭证）。
    STORAGE_BACKEND: Literal["local", "cos"] = "local"
    COS_BUCKET: str = ""          # 形如 vibebara-1327732770（含 AppId）
    COS_REGION: str = ""          # 形如 ap-chengdu
    COS_SECRET_ID: str = ""       # 经环境变量注入，勿入库/前端/git
    COS_SECRET_KEY: str = ""
    COS_PREFIX: str = ""          # 桶内统一前缀（多环境共享一桶时区分），默认空
    # 启动时按 COS 前缀列举重建 DB 索引（_sync_from_filesystem）。skill 多时可关，信任 DB。
    SKILL_STORE_SYNC_ON_START: bool = True

    # ------------------------------------------------------------------
    # 大模型接口（统一经 Provider 抽象层，见 app/services/llm/）
    # ------------------------------------------------------------------
    # 厂商：bailian（阿里云百炼 / DashScope 兼容模式，默认）| openai-compatible（其它 OpenAI 兼容网关）
    LLM_PROVIDER: str = "bailian"
    # 接入点（不含 /v1，由抽象层自动补全）。留空 → 取所选厂商预设：
    #   bailian → https://dashscope.aliyuncs.com/compatible-mode
    LLM_BASE_URL: str = ""
    LLM_API_KEY: str = ""
    # 模型名。留空 → 取所选厂商预设（bailian → qwen-plus）
    LLM_MODEL: str = ""

    class Config:
        env_file = ".env"

    @model_validator(mode="after")
    def _resolve_paths(self) -> "Settings":
        """解析数据目录与 Skill 存储目录，移除对 user home 的依赖。"""
        if not self.COWORK_DATA_DIR:
            self.COWORK_DATA_DIR = str(_BACKEND_DIR / "data")
        if not self.SKILL_STORE_DIR:
            self.SKILL_STORE_DIR = str(Path(self.COWORK_DATA_DIR) / "skills")
        return self

    @property
    def db_echo(self) -> bool:
        """SQL echo 最终值：DB_ECHO 显式设置则用之；否则本地跟随 DEBUG，
        cloud 模式默认关闭（避免生产日志泄露语句/性能噪声）。需要时经 DB_ECHO 覆盖。"""
        if self.DB_ECHO is not None:
            return self.DB_ECHO
        return self.DEBUG and self.DEPLOYMENT_MODE != "cloud"


settings = Settings()

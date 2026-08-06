from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Dict, List, Optional


# =========================================================================
# 目录浏览
# =========================================================================

class BrowseRequest(BaseModel):
    path: str = ""


class DirEntry(BaseModel):
    name: str
    abs_path: str
    is_drive: bool = False


class BrowseResponse(BaseModel):
    success: bool
    current: str = ""
    parent: Optional[str] = None
    dirs: List[DirEntry] = []
    error: Optional[str] = None


# =========================================================================
# 外部 Skill 扫描 + 迁移（Dashboard 用）
# =========================================================================

class InstalledAtStatus(BaseModel):
    cursor: bool = False
    codex: bool = False
    windsurf: bool = False
    claude: bool = False
    kiro: bool = False
    trae: bool = False
    qoder: bool = False
    workbuddy: bool = False


class UnifiedSkillPackage(BaseModel):
    id: str
    origin: str
    origin_confidence: str
    origin_signals: List[str] = []
    source_path: str
    name: str = ""
    display_name: str = ""
    description: str = ""
    short_description: str = ""
    has_scripts: bool = False
    has_references: bool = False
    has_assets: bool = False
    installed_at: InstalledAtStatus = InstalledAtStatus()


class ScanStatusResponse(BaseModel):
    status: str
    packages: List[UnifiedSkillPackage] = []
    scan_dir: str = ""
    last_scan: Optional[str] = None
    error: Optional[str] = None


class RescanRequest(BaseModel):
    scan_dir: Optional[str] = None


class MigrateRequest(BaseModel):
    source_path: str
    target_platform: str


class MigrateResponse(BaseModel):
    success: bool
    id: str = ""
    origin: str = ""
    adapted: bool = False
    target_platform: str = ""
    dest_path: str = ""
    error: Optional[str] = None


# =========================================================================
# Native Skill Store（平台原生 CRUD）
# =========================================================================

class NativeSkillItem(BaseModel):
    id: str
    # 自然名用于展示和本机部署；id 为个人 UUID 或团队代理键。
    name: str = ""
    display_name: str = ""
    description: str = ""
    short_description: str = ""
    version: str = "1.0.0"
    tags: List[str] = []
    imported_from: Optional[str] = None
    store_path: str = ""
    scope: str = "personal"
    team_id: Optional[str] = None
    owner_id: Optional[str] = None
    source_skill_id: Optional[str] = None
    content_hash: str = ""
    deployed_cursor: bool = False
    deployed_codex: bool = False
    deployed_windsurf: bool = False
    deployed_claude: bool = False
    deployed_kiro: bool = False
    deployed_trae: bool = False
    deployed_qoder: bool = False
    deployed_workbuddy: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class NativeSkillListResponse(BaseModel):
    success: bool
    skills: List[NativeSkillItem] = []
    error: Optional[str] = None


class NativeSkillDetailResponse(BaseModel):
    success: bool
    id: str = ""
    config: Dict[str, Any] = {}
    vibeh_content: str = ""
    store_path: str = ""
    db: Optional[NativeSkillItem] = None
    error: Optional[str] = None


class NativeSkillCreateRequest(BaseModel):
    config: Dict[str, Any]
    vibeh_content: Optional[str] = None


class NativeSkillUpdateRequest(BaseModel):
    partial: Dict[str, Any]
    vibeh_content: Optional[str] = None
    # 团队仓库网页编辑器保存时：用户勾选"更新版本号"则建一条版本快照。
    create_version: bool = False
    version_number: str = ""
    version_label: str = ""


class NativeSkillImportRequest(BaseModel):
    source_path: str
    origin: Optional[str] = None


class ImportContentFile(BaseModel):
    """import-content 上传的单个文件载荷（M0 §4.5 / 契约 FilePayload）。"""

    path: str
    encoding: str = "utf8"  # "utf8" | "base64"
    content: str = ""


class ImportContentRequest(BaseModel):
    """方案 B · M4：按 contents 导入（契约 ImportContentRequest）。

    POST /skill-forge/store/import-content —— 前端经本地代理 read-folder 读取本地
    skill 文件夹后上传 files[]，云端写临时目录后复用既有 import_from_external 解析。
    """

    model_config = ConfigDict(populate_by_name=True)

    files: List[ImportContentFile] = []
    origin: Optional[str] = None
    scope: Optional[str] = "personal"  # "personal" | "team"
    team_id: Optional[str] = Field(default=None, alias="teamId")


class ImportUrlScanRequest(BaseModel):
    """从远程链接（GitHub 等仓库或归档 URL）解析可导入的 Skill 列表。"""

    url: str


class ImportUrlScanResponse(BaseModel):
    success: bool
    token: str = ""
    packages: List[UnifiedSkillPackage] = []
    source_url: str = ""
    error: Optional[str] = None


class ImportUrlRequest(BaseModel):
    """把链接解析结果中勾选的 Skill 导入到个人 / 团队仓库（全局可复用）。

    token 为 scan 返回的缓存句柄；source_paths 为勾选的「仓库内相对路径」。
    scope=team 时需提供 team_id。
    """

    model_config = ConfigDict(populate_by_name=True)

    token: str
    source_paths: List[str] = []
    scope: str = "personal"  # "personal" | "team"
    team_id: Optional[str] = Field(default=None, alias="teamId")
    source_url: Optional[str] = Field(default=None, alias="sourceUrl")


class ImportUrlResultItem(BaseModel):
    source_path: str = ""
    success: bool = False
    skill: Optional[NativeSkillItem] = None
    error: Optional[str] = None


class ImportUrlResponse(BaseModel):
    success: bool
    imported: int = 0
    skills: List[NativeSkillItem] = []
    results: List[ImportUrlResultItem] = []
    error: Optional[str] = None


class NativeSkillBuildRequest(BaseModel):
    target: str = "all"


class NativeSkillDeployRequest(BaseModel):
    target: str
    dest_path: Optional[str] = None


class NativeSkillMutationResponse(BaseModel):
    success: bool
    skill: Optional[NativeSkillItem] = None
    error: Optional[str] = None
    no_change: bool = False
    diff_summary: str = ""
    change_items: List[Dict[str, Any]] = []
    # 本次保存若创建了版本快照，回传该版本（含 seq），供前端提示"已创建版本 vN"。
    version: Optional[Dict[str, Any]] = None


# =========================================================================
# Skill 版本记录（团队仓库版本快照）
# =========================================================================

class SkillVersionItem(BaseModel):
    id: str
    skill_id: str
    team_id: Optional[str] = None
    seq: int
    version_number: str
    label: str = ""
    content_hash: str = ""
    change_summary: str = ""
    change_items: List[Dict[str, Any]] = []
    resource_count: int = 0
    source: str = ""
    created_by: str = ""
    created_by_name: str = ""
    created_at: Optional[str] = None


class SkillVersionDetail(SkillVersionItem):
    config: Dict[str, Any] = {}
    vibeh_content: str = ""
    resources: List[str] = []


class SkillVersionListResponse(BaseModel):
    success: bool
    versions: List[SkillVersionItem] = []
    error: Optional[str] = None


class TeamSkillHistoryItem(SkillVersionItem):
    """团队级聚合的提交记录：在版本快照基础上补 Skill 名，便于跨 Skill 展示。"""

    skill_name: str = ""


class TeamSkillHistoryResponse(BaseModel):
    success: bool
    items: List[TeamSkillHistoryItem] = []
    error: Optional[str] = None


class SkillVersionDetailResponse(BaseModel):
    success: bool
    version: Optional[SkillVersionDetail] = None
    error: Optional[str] = None


class RestoreVersionResponse(BaseModel):
    success: bool
    version: Optional[SkillVersionItem] = None
    diff_summary: str = ""
    error: Optional[str] = None


class NativeSkillDeployResponse(BaseModel):
    success: bool
    deployed: List[Dict[str, str]] = []
    error: Optional[str] = None


class NativeSkillPreviewResponse(BaseModel):
    success: bool
    data: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None

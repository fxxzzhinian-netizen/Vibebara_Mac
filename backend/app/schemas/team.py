from pydantic import BaseModel
from typing import List, Optional


class TeamCreateRequest(BaseModel):
    name: str
    description: str = ""


class TeamUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class TeamSettingsUpdateRequest(BaseModel):
    auto_skill_hot_update: Optional[bool] = None


class TeamMemberInfo(BaseModel):
    user_id: str
    username: str
    display_name: str
    avatar_url: Optional[str] = None
    role: str
    joined_at: Optional[str] = None


class TeamInfo(BaseModel):
    id: str
    name: str
    description: str
    owner_id: str
    invite_code: str
    max_members: int
    member_count: int = 0
    auto_skill_hot_update: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TeamResponse(BaseModel):
    success: bool
    team: Optional[TeamInfo] = None
    error: Optional[str] = None


class TeamListResponse(BaseModel):
    success: bool
    teams: List[TeamInfo] = []
    error: Optional[str] = None


class TeamMemberListResponse(BaseModel):
    success: bool
    members: List[TeamMemberInfo] = []
    error: Optional[str] = None


class InviteCodeResponse(BaseModel):
    success: bool
    invite_code: str = ""
    error: Optional[str] = None


class JoinTeamRequest(BaseModel):
    invite_code: str


class UpdateMemberRoleRequest(BaseModel):
    role: str

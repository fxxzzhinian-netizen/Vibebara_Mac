export interface UserInfo {
  id: string;
  username: string;
  display_name: string;
  email: string | null;
}

export interface UserResponse {
  success: boolean;
  user?: UserInfo;
  credential?: { kind: string; device_id: string | null };
  error?: string;
}

export interface UserSkillDeploymentInfo {
  id: string;
  user_id: string;
  device_id?: string | null;
  project_id: string;
  team_skill_id: string;
  skill_name: string;
  tool_type: string;
  deploy_path: string;
  install_path: string;
  repo_version: number;
  repo_hash: string;
  installed_hash: string;
  status: string;
  tracking_enabled: boolean;
  local_dirty: boolean;
  last_seen_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface DeploymentListResponse {
  success: boolean;
  deployments: UserSkillDeploymentInfo[];
  error?: string;
}

export interface MutationResponse {
  success: boolean;
  error?: string;
}

export interface CloudResourceItem {
  path: string;
  transfer: "inline" | "url";
  encoding?: "utf8" | "base64";
  content?: string;
  url?: string;
  sha256?: string;
  size?: number;
}

export interface BuildArtifactResponse {
  success: boolean;
  skill_id: string;
  tool: string;
  contents: Record<string, string>;
  resources: CloudResourceItem[];
  repo_hash: string;
  repo_version: number;
  abstract_snapshot: Record<string, unknown>;
  error?: string;
}

export interface ChangeItem {
  field?: string;
  path?: string;
  action?: string;
  before?: unknown;
  after?: unknown;
}

export interface PushDeploymentResponse {
  success: boolean;
  conflict?: boolean;
  no_change?: boolean;
  status?: string;
  change_items: ChangeItem[];
  diff_summary: string;
  deployment?: UserSkillDeploymentInfo;
  error?: string;
}

export interface PullUpdateResponse {
  success: boolean;
  conflict?: boolean;
  deployment?: UserSkillDeploymentInfo;
  error?: string;
}

export interface MergeResourceOp {
  path: string;
  action: "use_mine" | "use_theirs" | "write_text" | "delete";
  encoding?: string;
  content?: string;
}

export interface MergedContent {
  body: string;
  config: Record<string, unknown>;
  resource_ops: MergeResourceOp[];
}

export interface MergeManualConflict {
  path: string;
  reason: string;
}

export interface MergePreviewResponse {
  success: boolean;
  error?: string;
  merged?: MergedContent;
  preview_change_items: ChangeItem[];
  manual_conflicts: MergeManualConflict[];
  notes: string[];
  merge_available: boolean;
  theirs_hash: string;
}

export interface MergeApplyResponse {
  success: boolean;
  conflict?: boolean;
  error?: string;
  artifact?: BuildArtifactResponse;
}

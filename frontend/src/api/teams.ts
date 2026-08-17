import apiClient from './client'
import { DEV_SKIP_AUTH } from '@/runtime/devAuth'
import {
  devMockTeamList,
  devMockTeam,
  devMockUpdateTeam,
  devMockMembers,
} from '@/runtime/devMock'

export interface TeamInfo {
  id: string
  name: string
  description: string
  owner_id: string
  invite_code: string
  max_members: number
  member_count: number
  auto_skill_hot_update: boolean
  created_at: string | null
  updated_at: string | null
}

export interface TeamMemberInfo {
  user_id: string
  username: string
  display_name: string
  avatar_url: string | null
  role: string
  joined_at: string | null
}

export interface TeamResponse {
  success: boolean
  team?: TeamInfo
  error?: string
}

export interface TeamListResponse {
  success: boolean
  teams: TeamInfo[]
  error?: string
}

export interface MemberListResponse {
  success: boolean
  members: TeamMemberInfo[]
  error?: string
}

export interface TeamSkillHistoryItem {
  id: string
  skill_id: string
  skill_name: string
  team_id: string | null
  seq: number
  version_number: string
  label: string
  change_summary: string
  resource_count: number
  source: string
  created_by: string
  created_by_name: string
  created_at: string | null
}

export interface TeamSkillHistoryResponse {
  success: boolean
  items: TeamSkillHistoryItem[]
  error?: string
}

export async function createTeam(
  name: string,
  description: string = '',
): Promise<TeamResponse> {
  const { data } = await apiClient.post<TeamResponse>('/teams', {
    name,
    description,
  })
  return data
}

export async function listTeams(): Promise<TeamListResponse> {
  // 开发者模式（跳过登录）下后端会因假 token 返回 401，这里回放假数据预览样式。
  if (DEV_SKIP_AUTH) return devMockTeamList()
  const { data } = await apiClient.get<TeamListResponse>('/teams')
  return data
}

export async function getTeam(teamId: string): Promise<TeamResponse> {
  if (DEV_SKIP_AUTH) return devMockTeam(teamId)
  const { data } = await apiClient.get<TeamResponse>(`/teams/${teamId}`)
  return data
}

export async function updateTeam(
  teamId: string,
  name?: string,
  description?: string,
): Promise<TeamResponse> {
  if (DEV_SKIP_AUTH) return devMockUpdateTeam(teamId, name ?? null, description ?? null)
  const { data } = await apiClient.put<TeamResponse>(`/teams/${teamId}`, {
    name: name ?? null,
    description: description ?? null,
  })
  return data
}

export async function updateTeamSettings(
  teamId: string,
  autoSkillHotUpdate: boolean,
): Promise<TeamResponse> {
  const { data } = await apiClient.patch<TeamResponse>(`/teams/${teamId}/settings`, {
    auto_skill_hot_update: autoSkillHotUpdate,
  })
  return data
}

export async function deleteTeam(
  teamId: string,
): Promise<{ success: boolean }> {
  const { data } = await apiClient.delete<{ success: boolean }>(
    `/teams/${teamId}`,
  )
  return data
}

export async function joinTeam(
  inviteCode: string,
): Promise<TeamResponse> {
  const { data } = await apiClient.post<TeamResponse>('/teams/join', {
    invite_code: inviteCode,
  })
  return data
}

export async function listMembers(
  teamId: string,
): Promise<MemberListResponse> {
  if (DEV_SKIP_AUTH) return devMockMembers(teamId)
  const { data } = await apiClient.get<MemberListResponse>(
    `/teams/${teamId}/members`,
  )
  return data
}

export async function updateMemberRole(
  teamId: string,
  userId: string,
  role: string,
): Promise<{ success: boolean }> {
  const { data } = await apiClient.put(`/teams/${teamId}/members/${userId}`, {
    role,
  })
  return data as { success: boolean }
}

export async function listTeamSkillHistory(
  teamId: string,
  opts: { skillId?: string; limit?: number; offset?: number } = {},
): Promise<TeamSkillHistoryResponse> {
  // 开发者模式（跳过登录）下后端会因假 token 返回 401，这里回放空列表避免报错。
  if (DEV_SKIP_AUTH) return { success: true, items: [] }
  const { data } = await apiClient.get<TeamSkillHistoryResponse>(
    `/teams/${teamId}/skill-history`,
    {
      params: {
        skill_id: opts.skillId || undefined,
        limit: opts.limit ?? 50,
        offset: opts.offset ?? 0,
      },
    },
  )
  return data
}

# Skill 协作与同步 — 实现纪要

> 状态：**已实现**（本文汇总自 4 篇迭代计划，原始决策记录见 [`archive/`](archive/)）
> 一句话：个人 / 团队 Skill 仓库隔离 → 放入团队仓库 → 加入项目 Skill 列表 → 用户本地部署 → 本地改动探测 → 手动推送（抽象层改动点）→ 通知其他成员 → 拉取更新，构成一条完整的团队协作链路。

本文是当前系统行为的**单一事实来源**。四篇过程文档已归档，仅作决策溯源；如与本文冲突，以本文与代码为准。

---

## 1. 资产模型（四层）

| 层级 | 定义 | 数据条件 | 是否同步源 |
|------|------|----------|------------|
| 个人 Skill 仓库 | 当前登录用户私有的 Skill 草稿区 | `personal_skills.owner_id=当前用户` | 否，仅个人可复用素材 |
| 团队 Skill 仓库 | 团队共享的 Skill 基线 | `scope='team' AND team_id ∈ 用户所属团队` | 是，团队分发与推送/拉取的事实源 |
| 项目 Skill 列表 | 项目声明可用哪些团队 Skill，不含本地路径/工具 | `project_skills(project_id, skill_id)` | 否 |
| 用户部署实例 | 某用户把项目 Skill 部署到本机后的真实运行副本 | `user_skill_deployments`（per-user） | 是，监听其变化并经推送回写团队仓库 |

核心原则：**个人仓库 per-user 互不可见；团队仓库 per-team 成员可见；列表分开、入口分开、归属字段分开。**

---

## 2. 用户隔离边界

| 资产 / 行为 | 归属 | 说明 |
|-------------|------|------|
| 个人 Skill（`scope=personal`） | per-user | 按 `owner_id` 隔离，他人不可见、不可改 |
| 本地部署目录 `install_path` | per-user | 各成员路径/工具不同，互不可见 |
| 跟踪与改动探测 `local_dirty` | per-user | 各自部署实例独立 |
| 部署快照基线 `abstract_snapshot` | per-user | 只用于计算本人的增量改动点 |
| 推送 / 拉取权限 | per-user | 只能操作自己的部署实例 |
| 团队仓库 Skill（`scope=team`） | team 共享 | 推送/拉取的唯一事实源 |
| 项目 Skill 列表 / 项目动态 | project 共享 | 团队成员可见的版本与审计流 |
| "需要我行动"提示（推送/拉取） | per-user | 由本人 `deployment.status` 驱动 |

`/skill-forge/store/*` 全部接口已加认证（`Depends(get_current_user_id)`）：个人 Skill 按 `owner_id` 过滤鉴权，团队 Skill 按团队成员鉴权。

---

## 3. 数据模型（关键字段）

**`skill_packages`**（个人 + 团队仓库共用一张表，靠 `scope` 区分）
- `scope`：`personal` / `team`
- `owner_id`：个人仓库归属用户（必填）
- `id` / `name`：个人 Skill 的内部 UUID / 自然名；`(owner_id, name)` 用户内唯一
- `team_id`：团队仓库归属团队
- `source_skill_id`：溯源（个人→团队复制时指向原个人 Skill）
- `version` / `content_hash`：仓库版本与抽象包内容 hash
- `store_path`：对象存储前缀；个人 Skill 使用 `skills/personal/{owner_id}/{id}`，团队 Skill 使用 `skills/team/{id}`

**`user_skill_deployments`**（部署实例，per-user）
- `user_id` / `project_id` / `team_skill_id` / `skill_name`
- `tool_type`（cursor/codex）、`deploy_path`、`install_path`
- `repo_version` / `repo_hash`：部署时团队仓库版本与 hash（冲突判断基线）
- `installed_hash`：当前本地实例 hash
- `abstract_snapshot`：上次推送时的抽象包快照（增量 diff 基线）
- `local_dirty`：本地是否有未推送改动
- `status`：`synced` / `changed` / `conflict` / `missing` / `untracked` / `outdated`
- `tracking_enabled` / `last_seen_at`

**`skill_change_log`**（项目/团队动态，审计流）
- `team_id` / `project_id` / `deployment_id` / `user_id` / `skill_id`
- `source`：`team_repo` / `user_deployment`
- `action`：`pushed` / `pulled` / `conflict` / `missing` / `created` …
- `base_hash` / `new_hash`
- `change_items`：结构化改动点列表（JSON）
- `diff_summary`：中文一句话摘要

---

## 4. 核心流程

```
个人 Skill 仓库 (SkillForge)
  └─[放入团队仓库 / 复制]→ 团队 Skill 仓库 (Teams)
        └─[加入项目]→ 项目 Skill 列表 (ProjectSkills)
              └─[用户部署]→ 本地部署实例（写入 .cursor/skills 或 .codex/skills）
                    ├─ 本地改动 → 只读探测 local_dirty → 卡片"有改动待推送"
                    ├─[推送]→ 解析→diff→写回团队仓库(version+1)→记动态→标记他人 outdated→WS 通知
                    └─[拉取更新]→ 团队仓库最新构建写回本人本地目录
```

### 4.1 个人 → 团队（复制 + 溯源）
- 入口：个人 Skill 仓库（`SkillForge.vue`）每个 Skill 的「放入团队」按钮 → 选目标团队。
- 后端：`NativeSkillStore.copy_to_team(skill_id, team_id, user_id)`
  - 校验源为本人个人 Skill；以个人 Skill 的自然名生成团队代理键并复制到团队对象前缀，避免把个人 UUID 暴露为安装目录名。
  - 新副本 `scope=team` + `team_id` + `source_skill_id=原个人 id`；`owner_id=None`（团队共享）。
  - 保留原 `display_name` 作为友好名；个人仓库**保留原件**。
- 接口：`POST /api/v1/teams/{team_id}/skills/from-personal/{skill_id}`（团队成员校验）。
- 两边独立演进，不保留版本关联（仅 `source_skill_id` 可追溯）。

> 注：早期 `add_skill_to_project()` 把个人 Skill **原地转** `scope=team` 的旧逻辑仍保留（精简版），但"放入团队仓库"走上面独立的复制入口，是当前推荐路径。

### 4.2 加入项目
- 团队仓库 Skill → 加入某项目 Skill 列表（`project_skills`），仅声明"项目可用"，**不部署、不监听**。

### 4.3 用户部署
- 项目 Skill 卡片「部署」→ 选工具（Cursor/Codex）+ 本机路径 + 是否覆盖。
- 构建目标平台产物写入 `{deploy_path}/.{tool}/skills/{skill_name}/`，幂等维护项目 `.gitignore`，创建部署实例并启用跟踪。

### 4.4 本地改动探测（只读）
- `GET /api/v1/skill-deployments/{id}/local-status`：实时比对 `install_path` hash 与 `installed_hash`，返回是否有未推送改动，**不写库、不进动态**。
- 前端进入项目页 + 每 8 秒轮询刷新，驱动「有改动待推送」徽标与按钮显隐。

### 4.5 手动推送（即同步到平台）
- `POST /api/v1/skill-deployments/{id}/push`：解析本地 → 与本人上次快照 diff → 生成 `change_items` →
  **直接写回团队仓库 Skill（version+1、content_hash 更新）** → 写 `action=pushed` 动态 →
  同 Skill 其他成员实例标记 `outdated`（若其本地也有改动则 `conflict`）→ WS 广播 `skill.pushed`。
- 冲突拦截：`deployment.repo_hash != team.content_hash`（团队仓库已被他人更新）→ 提示"先拉取最新再推送"。
- 本地改动**不再自动同步**（已移除/降级旧的自动轮询 promote）。

### 4.6 拉取更新
- `POST /api/v1/skill-deployments/{id}/pull-update`：用团队仓库当前内容构建并写回本人 `install_path`，状态回到 `synced`。
- 若本人本地有未推送改动 → 默认拦截，需 `overwrite=true`（覆盖本地）确认。

---

## 5. 抽象层改动点（Diff）

改动点基于**平台抽象包**（`skill.config.yaml` + `SKILL.md`）维度，而非 Cursor/Codex 原生文件维度：

- `parse_native_skill(path)`：把原生 Skill 目录解析为内存抽象包（不写盘、不碰 DB）。
- `diff_abstract_packages(base, current)` 产出 `change_items`：
  - `field`：标量/嵌套字段（如 `description`、`policy.auto_invoke`），含 `old`/`new` 与中文 `label`。
  - `body`：`SKILL.md` 正文 `+N / -M` 行。
  - `resource`：`scripts/` `references/` `assets/` 文件 `added`/`removed`/`modified`。
- 项目动态条目可展开显示明细，主行展示「{用户} 推送了 {skill}」+ 摘要。

---

## 6. 冲突策略

| 场景 | 判断 | 处理 |
|------|------|------|
| 推送时团队仓库已被他人推送 | `repo_hash != team.content_hash` | 拦截推送，提示先拉取再推送 |
| 拉取时本人本地有未推送改动 | `local_dirty=true` | 默认拦截，需 `overwrite` 覆盖 / 查看差异 |
| 既 outdated 又本地有改动 | 两者叠加 | 标记 `conflict`，由用户选择覆盖 / 放弃 / **AI 合并** |

团队 `auto_skill_hot_update`（默认关闭）：开启且无冲突时，推送后自动提升为团队仓库新版本。

**AI 辅助合并（已实现）**：冲突时除「覆盖 / 放弃」外，新增「AI 合并」——对 base / mine / theirs 三方做 AI 合并（SKILL.md 正文 + 配置字段 + 文本资源），先预览可编辑、再一键提交写回团队仓库并覆盖本地。完整设计见 [ai-assisted-merge.md](ai-assisted-merge.md)。

---

## 7. 关键 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/skill-forge/store/list?scope=personal\|team` | 个人/团队仓库列表（按 owner/team 过滤） |
| POST | `/api/v1/teams/{team_id}/skills/from-personal/{skill_id}` | 个人 Skill 复制进团队仓库 |
| POST | `/api/v1/projects/{project_id}/skills/{skill_id}` | 团队 Skill 加入项目列表 |
| GET | `/api/v1/projects/{project_id}/skills` | 项目可用 Skill + 当前用户部署状态 |
| POST | `/api/v1/projects/{project_id}/skills/{skill_id}/deploy` | 部署到本机并创建部署实例 |
| GET | `/api/v1/skill-deployments/{id}/local-status` | 只读探测本地改动 |
| POST | `/api/v1/skill-deployments/{id}/push` | 推送即同步到团队仓库 |
| POST | `/api/v1/skill-deployments/{id}/pull-update` | 拉取团队最新到本地 |
| GET | `/api/v1/projects/{id}/sync/changes` | 项目动态（含 `change_items`） |

---

## 8. 前端入口与组件

| 页面/组件 | 角色 |
|-----------|------|
| `Dashboard.vue` | 首页导航（已移除"协作会话""适配器管理"，保留"个人 Skill 仓库""团队协作"） |
| `SkillForge.vue` | **个人 Skill 仓库**：仅拉 `scope=personal`，可编辑/部署/「放入团队」 |
| `Teams.vue` | 团队协作：团队列表 + 项目列表 + **团队 Skill 仓库**区块 + 成员；顶栏有返回主页按钮 |
| `ProjectSkills.vue` | 项目 Skill 列表 + 部署/推送/拉取/动态；按钮按状态显隐（见下） |
| `SkillDetail.vue` | 任意 Skill 的**只读**详情页（`/skills/:id`） |

**按钮显隐规则（`ProjectSkills.vue`）**
- 「部署」：仅未部署（`!skill.deployment`）时显示；部署过即隐藏。
- 「推送」：仅在跟踪中且本地检测到改动（`tracking_enabled && hasLocalChanges`）时显示。
- 「更新本地」：仅 `status ∈ {outdated, conflict}` 时显示。

---

## 9. 已落地的关键决策

1. **个人→团队 = 复制 + 溯源**，个人仓库保留原件（独立"放入团队"入口，非改造 add_skill_to_project）。
2. **推送 = 直接同步到平台**（写回团队仓库 + 推进版本），冲突时拦截要求先拉取。
3. 部署实例变更**不自动同步**，必须手动推送；平台只做只读 dirty 探测。
4. 改动点以**抽象层**维度表达并结构化展示。
5. 个人仓库按 `owner_id` 隔离；`/skill-forge/store/*` 全加认证。
6. 存量无主 `personal` Skill 启动迁移归属系统首个用户（`migrate_orphan_owners`）。
7. 团队仓库 Skill 在编辑器内只读，只能经部署实例推送/提升产生新版本。
8. 停止跟踪默认不删除本地文件，仅断开平台跟踪关系。

---

## 10. 暂未做 / 后续增强

- ~~自动三方合并（Markdown / 资源目录）~~ → 已实现「AI 辅助合并」，见 [ai-assisted-merge.md](ai-assisted-merge.md)（资源仍为二方合并、无 diff3 确定性兜底，列入该文档后续增强）。
- 细粒度行级合并 UI（当前 AI 合并提供整稿预览可编辑 + 覆盖/放弃兜底，尚无逐 hunk 取舍 UI）。
- 多机器路径同步、跨团队共享同一团队 Skill 实例。
- 独立通知/未读计数中心（当前复用 status + change_log + WS）。
- 个人副本与团队副本的版本联动（当前仅 `source_skill_id` 溯源）。
- 物理目录级 personal/team 隔离（当前共用 `SKILL_STORE_DIR`）。

---

## 11. 决策溯源（已归档原始计划）

| 归档文档 | 贡献的内容 |
|----------|------------|
| [`../archive/team-project-skill-sync-plan.md`](../archive/team-project-skill-sync-plan.md) | 四层资产模型、数据模型、部署/监听/冲突的总体设计 |
| [`../archive/skill-push-and-abstract-diff-plan.md`](../archive/skill-push-and-abstract-diff-plan.md) | 手动推送 + 抽象层改动点 diff |
| [`../archive/skill-push-user-isolation-plan.md`](../archive/skill-push-user-isolation-plan.md) | 推送即同步、outdated、拉取更新、用户隔离边界 |
| [`../archive/personal-vs-team-skill-repo-plan.md`](../archive/personal-vs-team-skill-repo-plan.md) | 个人/团队仓库隔离、owner_id、编辑器并入团队协作 |

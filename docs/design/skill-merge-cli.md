# 无头 CLI（Skill 合并 / 推送 / 拉取）— 设计与实施方案

> 状态：**M0–M8 已实现，M9 真实协作端到端待完成（2026-07-31）**。
> 一句话：把当前只能在桌面客户端「手动点击」触发的 Skill 合并 / 推送 / 拉取，下沉为一个工具无关的命令行工具 `vibebara`，使任何能跑 shell 的 Coding Agent（Cursor/Codex/Claude/…）、CI 脚本或人都能用同一条命令完成「冲突合并并写回团队仓库」。
>
> **最近复审（2026-07，基于最新代码）**：①「Gap A 无头鉴权」已由 **Token 根治**（统一 `auth_tokens` 表 + `vhk_` PAT，见 §6/§10）解决，CLI 鉴权侧后端零改动；②云端 merge/push/pull 编排端点**均已在 `backend/app/api/projects.py` 落地**；③local-agent 已切 `local-core`，`local-core`/`cli` 经 `file:` 共享（不建 workspace）；④分发主路已调整为 Windows 桌面安装包内置 Node SEA `vibebara.exe` 并注册用户 PATH，npm tarball 保留为开发/CI 能力但本期不发布。

本文是「无头 CLI」子系统的单一事实来源（评审稿）。合并算法本身见 [ai-assisted-merge.md](ai-assisted-merge.md)，协作链路见 [skill-collaboration-sync.md](skill-collaboration-sync.md)；本文只覆盖「在 GUI 之外驱动同一套链路」的部分。MCP 方案为后续增强，本文不展开（见 §14）。

---

## 0. 执行总览（2026-07-16）

本文同时作为 CLI 落地的执行计划。实施按 §11 的里程碑推进，当前基线如下：

| 阶段 | 状态 | 交付物 / 验收 |
|------|------|---------------|
| P0 设计与风险收口 | ✅ 已完成 | Token 根治、响应 snake_case、merge 本地只读一次、同机锁定、包结构与 npm 分发方案均已敲定 |
| M-pre PAT 引导 | 🟡 代码完成，待桌面实机 | 已实现「为 CLI 授权」→ preload/IPC → 原子写 `~/.vibebara/config.json`；web 回退一次性复制；desktop build、vue-tsc、桌面/移动视口 UI 已验证 |
| M0–M1 脚手架/本地内核 | ✅ 已完成 | 已建 `local-core` / `cli` 包；抽取 hash/读写/安全/平台逻辑；core 3 tests passed |
| M2 local-agent 切源 | ✅ 已完成 | local-agent 已经 `file:` 依赖/re-export `local-core`，47 tests passed；Windows unpackaged build 成功并确认 core `package.json + dist/index.js` 在资源目录 |
| M3 后端寻址 | ✅ 已完成 | `GET /skill-deployments/mine` + `list_user_deployments` + 用户归属查询/路由鉴权测试 |
| M4 CLI 基础设施 | ✅ 已完成 | config / REST client / DTO / 输出与退出码已落地；CLI build + 6 tests passed |
| M5 CLI 基础命令 | 🟡 代码完成，待云端联调 | login / whoami / logout / status、仓库寻址、同机校验已实现；待 P3 的真实 IP/账号联调 |
| M6–M7 协作命令 | 🟡 代码完成，待云端端到端 | merge preview/apply 单次读盘、乐观锁、push/pull 与退出码均已实现；mock 云端编排测试通过 |
| M8 桌面 CLI 分发 | ✅ 已完成 | Node SEA `vibebara.exe`、desktop extraResources、NSIS 用户 PATH、升级/卸载清理与授权提示均已落地；npm tarball 仅保留为开发/CI 能力 |
| M9 端到端验收 | ⏳ 待 P3 | 真实 IP/账号下的 merge/push/pull 与跨工具冒烟 |

**关键路径**：`M0 → M1 → M2 → M4 → M5 → M6/M7 → M8 → M9`；`M-pre` 可与 `M0–M4` 并行但必须在 M5 联调前完成，M3 可与 M0–M2 并行。

**开工门槛**：
1. 代码侧 P1 已审查通过；目标数据库只需确认 `auth_tokens` 表存在（`DB_AUTO_CREATE=True` 会启动自动创建，关闭时需 `alembic upgrade head`）。
2. P3 的可达后端 IP 与测试账号暂不阻塞编码，仅在 M5/M9 联调时需要。
3. 正式 HTTPS 域名不阻塞开发；公网 GA 前必须补齐。

**阶段完成规则**：每个里程碑必须同时满足代码、测试、文档三项完成；禁止仅以“代码写完”标记完成。详细任务与验收见 §11–§12。

---

## 1. 背景与目标

现状（见 [ai-assisted-merge.md](ai-assisted-merge.md) §4）：一次 AI 合并不是单个后端动作，而是一条 **前端编排的多步链路**（`frontend/src/api/orchestration.ts` 的 `mergePreviewOrchestrated` / `mergeCommitOrchestrated`）：

```
本地代理 read-folder（读 install） → 云端 merge-preview（算）
  → 云端 merge-apply（写回团队 Store） → 本地代理 write-skill（覆盖落盘） → 云端 commit-merge（登记）
```

真正绑定在 GUI 上的只有两块：**①编排逻辑**（锁在前端 Vue 上下文）、**②本地磁盘读写**（锁在桌面拉起的本地代理里）。最重的合并计算（三方合并 + LLM + 团队仓库写回 + 乐观锁）已经是一套 **不读客户端本地盘** 的纯 REST 接口（`merge-preview` / `merge-apply` / `commit-merge`，入参均为 `{currentHash, files}` 内容上传）。

**目标**：

- 提供 `vibebara` CLI，在桌面客户端之外完成 merge / push / pull。
- 工具无关：不为每个 Coding 工具单独适配；一份二进制 + 一份 `SKILL.md` 指令即可被任意 Agent 调用（详见 §14 的 CLI vs MCP 取舍结论）。
- 不破坏现有 GUI 链路：CLI 与前端编排走 **同一套云端 REST** 与 **同一套本地盘语义**，hash 口径位级一致。
- 无头友好：长期 API Key 鉴权、`--json` 结构化输出、明确退出码、`--yes` 跳过交互。

**非目标（本期不做）**：

- MCP server（后续增强，§14）。
- 部署（deploy）/ 导入（import）/ 扫描（scan）等命令（可后续用同一内核扩展，本期聚焦 merge/push/pull）。
- **跨机操作**：CLI **锁定「部署所在机」**（同机）。换机 / 全新 CI runner / 异地 clone 上，CLI **不做路径重定位**，而是**同机校验失败即友好拒绝并提示先在本机部署**（检测与文案见 §9.2）。即"CI 友好"收窄为"在已部署过的 checkout 上跑 CI"。远程 / 多机路径同步仍非目标。
- 行级逐 hunk 取舍 UI（CLI 提供整稿预览 + 覆盖/放弃兜底，与 GUI 对齐）。

---

## 2. 范围（命令面）

| 命令 | 期次 | 作用 |
|------|------|------|
| `vibebara login` / `logout` / `whoami` | MVP | 用 API Key 建立 / 清除 / 查看本机凭据 |
| `vibebara status` | MVP | 列出当前用户的部署实例及其状态（dirty/outdated/conflict） |
| `vibebara merge` | **MVP 核心** | 对冲突部署做三方合并：预览 → （确认）→ 写回团队仓库 + 覆盖本地 |
| `vibebara push` | MVP | 推送本地改动到团队仓库（含冲突拦截） |
| `vibebara pull` | MVP | 拉取团队最新覆盖本地 |
| `vibebara deploy` / `import` / `scan` | 后续 | 用同一内核扩展，本期不做 |

---

## 3. 总体架构

```mermaid
flowchart TD
    subgraph shells["调用方（工具无关）"]
      A["Coding Agent (shell)"]
      H["人 / CI"]
    end
    A --> CLI
    H --> CLI
    subgraph cli["vibebara CLI（新增）"]
      CLI["命令解析 (Commander)"]
      ORCH["orchestrate/*：merge/push/pull 编排<br/>(移植自 orchestration.ts)"]
      CLOUD["cloud/*：REST 客户端 (API Key)"]
      CLI --> ORCH --> CLOUD
      ORCH --> LC
    end
    LC["local-core（新增共享包）<br/>computeDirHash / walk / readFolder / writeSkill / gitignore"]
    CLOUD -->|HTTP(S) + Bearer(API Key)| BE["云端 FastAPI<br/>merge-preview/apply/commit-merge（已存在）"]
    LC -->|直接 fs 读写| DISK["用户本地 .{tool}/skills/{id}"]
    LA["local-agent（现有）"] -.复用同一包.-> LC
```

设计要点：

1. **云端零改动复用**：`merge-preview` / `merge-apply` / `commit-merge` / `build-artifact` / `push` / `commit-pull` 已经是「上传内容 + hash 令牌」的无头接口，CLI 直接调，**不重写任何合并算法**。
2. **本地盘走共享包，不依赖桌面 / 本地代理**：把本地代理里的纯文件逻辑抽成 `local-core`，CLI 直接 `import` 后用 `fs` 读写本机盘——CLI 自身就是本地进程，无需经 `127.0.0.1` 本地代理，也就不需要发现「桌面随机生成的配对令牌+端口」。
3. **hash 单一事实来源**：`computeDirHash` 是 dirty 检测与乐观锁的命门，必须与云端、与本地代理位级一致。通过「`local-core` 同一份实现被 local-agent 与 CLI 共用」从根上杜绝口径漂移（见 `local-agent/src/hash.ts` 的冻结算法说明）。
4. **编排移植而非搬运 GUI**：CLI 内置一份 `orchestrate`，等价于 `orchestration.ts` 的 merge/push/pull 段，但用普通 REST 客户端（携 API Key），不依赖 axios 拦截器 / `window.__VIBEBARA_RUNTIME__`。

---

## 4. 复用 / 抽取 / 新增 清单

| 模块 | 现状 | 本方案处置 |
|------|------|-----------|
| 三方合并、配置裁决、资源处置 | `backend/app/services/skill_merge_service.py` | **零改动复用**（经 REST） |
| merge/push/pull 云端端点 | `backend/app/api/projects.py`（已存在） | **零改动复用** |
| 目录 hash / 文件遍历 | `local-agent/src/hash.ts`、`walk.ts` | **抽取**到 `local-core`，两端共用 |
| 读文件夹 / 写 skill / gitignore / 安全校验 / 平台目录 | `local-agent/src/handlers/readFolder.ts`、`handlers/writeSkill.ts`、`gitignore.ts`、`security.ts`、`platform.ts`、`fileio.ts` | **抽取核心纯函数**到 `local-core`，CLI 直接调；local-agent 改为薄 HTTP 包装复用同包 |
| 编排（merge/push/pull 串联） | `frontend/src/api/orchestration.ts` | **移植**为 `cli/src/orchestrate/*`（去 axios/window 依赖） |
| 云端 DTO | `frontend/src/api/projects.ts`、`orchestration.ts` | **移植**为 `cli/src/cloud/types.ts` |
| 统一凭据鉴权（`vhs_`/`vhk_`） | **已根治**：`get_current_user_id` 走 `verify_credential`，PAT 由 `auth_tokens` 表承载 | **零改动复用**（CLI 直接带 `vhk_` PAT；见 §6） |
| 部署寻址（跨项目） | 仅能逐项目 `GET /projects/{id}/skills`，**无 `mine` 列表** | **后端新增** `GET /skill-deployments/mine`（§10，唯一待补后端项） |

> 风险控制（§15-Q1 已定：**本期一步到位切源**，同源杜绝口径漂移）：M1 抽 `local-core`、M2 让 local-agent 切源删重复实现，以 §12 的三方 hash 对拍兜底。后备（若需缩爆炸半径）：M1 先只让 CLI 用、local-agent 切源延到 M2 末。

---

## 5. 包结构与目录

新增一个与 `local-agent/` 平级的 CLI 包，以及一个共享包：

```
local-core/                      # 新增：纯文件/哈希逻辑（无 HTTP、无 CLI）
├── src/
│   ├── hash.ts                  # 从 local-agent 迁入：computeDirHash / hashPath
│   ├── walk.ts                  # 从 local-agent 迁入：walkFiles
│   ├── fileio.ts                # readFilePayload / writeContent
│   ├── security.ts              # safeJoinUnder / isInside / realResolve
│   ├── gitignore.ts             # ensureGitignore
│   ├── platform.ts              # platformSkillsDir
│   ├── readFolder.ts            # 纯函数版（输入 path → {root,dirHash,files}）
│   └── writeSkill.ts            # 纯函数版（输入 {deployPath,tool,skillId,contents,resources} → {installPath,installedHash,written}）
├── package.json
└── tsconfig.json

cli/                             # 新增：vibebara CLI
├── src/
│   ├── index.ts                 # bin 入口（Commander）
│   ├── config.ts                # 读凭据/cloud base（~/.vibebara/config.json + env）
│   ├── output.ts                # 人读输出 + --json
│   ├── cloud/
│   │   ├── client.ts            # REST 客户端（Bearer = API Key）
│   │   └── types.ts             # 云端 DTO（移植自 frontend）
│   ├── orchestrate/
│   │   ├── merge.ts             # mergePreview / mergeCommit（移植 orchestration.ts）
│   │   ├── push.ts
│   │   └── pull.ts
│   ├── resolve.ts               # 解析 deployment（cwd / --skill / --deployment）+ 同机校验（§9.2）
│   └── commands/
│       ├── login.ts  whoami.ts  logout.ts
│       ├── status.ts
│       ├── merge.ts  push.ts  pull.ts
├── test/                        # vitest（合同测试 + 端到端 mock）
├── package.json                 # bin: { "vibebara": "dist/index.js" }
└── tsconfig.json
```

技术栈：Node>=20 + TypeScript + Vitest；`cli` 使用 ESM + Commander.js + 内置 `fetch`（避免新增 axios），`local-core` 输出 CommonJS，以便现有 CommonJS `local-agent` 零模块制式迁移直接复用（ESM CLI 可正常消费 CommonJS 导出）。

---

## 6. 鉴权方案（统一凭据 / PAT）—— 已随「Token 根治」落地

> 更新：原计划「给 `get_current_user_id` 加一条 `vhk_` 分支查 `api_key_hash`」已被**更彻底的根治**取代。本节据最新代码（`backend/app/services/auth_service.py`、`backend/app/api/auth.py`）改写——**CLI 鉴权侧后端零改动**。

- **统一有状态凭据表 `auth_tokens`**：登录态（`vhs_`，带 `expires_at`）与长期无头凭据 PAT（`vhk_`，默认无过期）**同表、同一条校验路径** `auth_service.verify_credential`（`sha256(raw)` 命中 `token_hash` → `revoked_at` 为空且未过期 → 返回 `user_id`）。退化的 `users.api_key_hash` 单列已**废弃并 drop**。前缀 `vhs_`/`vhk_` 仅作日志辨识，**校验不分流前缀**。
- **CLI 用的就是 PAT**：`POST /api/v1/auth/api-key`（`Depends(get_current_user_id)`，**需已登录会话**）签发 `vhk_...`（内部 `create_pat`，**重生成 = 轮换旧 PAT**），响应字段 `api_key`（snake）。
- **首个 PAT 引导 —— ✅ 已定（2026-06-29）：C+「桌面一键为 CLI 授权」**。后端 `POST /auth/api-key` 已就绪，但**前端/桌面原无「生成 PAT」入口**（账户/设置页无相关视图）。落定方案：
  - **桌面（主路 C+，零复制）**：设置区加按钮「**为 CLI 授权**」→ 复用渲染层**已登录会话**调 `POST /auth/api-key` 铸 `vhk_` → 经 preload/IPC 交主进程**写入 `~/.vibebara/config.json`**（含 `apiKey` + `cloudApiBase`，`0600`）。用户一次点击、**零手动复制**，CLI 即用。
  - **纯 web / CI 回退（C 基础）**：无桌面主进程可写盘时，同一按钮**一次性回显 `vhk_`** → 人工 `vibebara login --api-key <key>` 或塞 `VIBEBARA_API_KEY`。
  - 两路都只调 `POST /auth/api-key`、在**已认证会话**内铸 PAT，**零新增暴破面**；与未来 §15-Q3「命名/列出/吊销」同源演进。
- **为何不开「无滑块 CLI 登录」**：`CAPTCHA_REQUIRED` 默认 `True`（`app/core/config.py:72`、`.env.example`）且后端**无任何登录限流/锁定**（grep `rate limit`/`slowapi`/`lockout`/`attempt` 全空）——**验证码是密码登录唯一的暴破屏障**。单开同账密、无滑块的 `/cli-login` 等于绕开该屏障，除非同时补限流否则是安全回退。**故弃用**（A 方案）。
- **传输**：CLI 统一 `Authorization: Bearer <vhk_...>`。
- **whoami**：`GET /api/v1/auth/me`（带 Bearer 即可）回显 username 等。
- **不过期、可吊销**：PAT 默认无 `expires_at`，适配长跑 / CI；吊销 = `revoked_at` 置位。本期靠「重生成 = 轮换」做事实吊销；「列出 / 命名 / 单独吊销」端点见 §15-Q3（表已支持多条/命名/吊销，仅缺端点）。
- **破坏性提示**：Token 根治的迁移 `20260624_..._add_auth_tokens` 会 **drop `users.api_key_hash`** 并使现有登录态立即失效（需重登）；这是后端一次性事项，与 CLI 项目解耦。

---

## 7. 配置与凭据存储

优先级：**命令行参数 > 环境变量 > 配置文件 > 默认**。

| 项 | 配置文件键 | 环境变量 | 默认 |
|----|-----------|----------|------|
| 云端 API Base | `cloudApiBase` | `VIBEBARA_CLOUD_API_BASE` | **无烤死默认**（登录时 `--cloud` 指定，存入配置文件）。详见 §15-Q5 |
| API Key | `apiKey` | `VIBEBARA_API_KEY` | 无（未登录） |

- 配置文件：`~/.vibebara/config.json`（Windows：`%USERPROFILE%\.vibebara\config.json`）。
- 写入时权限收紧（POSIX `0600`；Windows 靠用户目录 ACL）。API Key 为敏感凭据，`whoami` 只回显前 8 位掩码。
- **写入来源**：①CLI 自身 `vibebara login`；②**桌面「为 CLI 授权」（C+，§6/§P2）直接写本文件**（`apiKey` + `cloudApiBase`），与 CLI 读取同一路径同一格式。
- CI 场景推荐 **只用环境变量**（`VIBEBARA_API_KEY` / `VIBEBARA_CLOUD_API_BASE`），不落盘。
- **Base URL 现状（§15-Q5）**：暂无正式域名，仅 IP。本期**不烤死生产默认**，由 `vibebara login --cloud http://<ip>:<port>/api/v1` 写入配置；待正式域名（HTTPS）就位再补烤默认并切 HTTPS。⚠️ IP + HTTP 下 Bearer/API Key **明文过线**，仅限可信内网；公网 GA 前必须切 HTTPS 域名。

---

## 8. 命令详述

通用全局参数：`--json`（结构化输出到 stdout）、`--yes`（跳过确认）、`--cwd <path>`（覆盖工作目录）、`--verbose`。

### 8.1 `vibebara login` / `whoami` / `logout`
```
vibebara login --api-key vhk_xxxx --cloud http://<ip>:<port>/api/v1   # 写入 ~/.vibebara/config.json（无烤死默认，§15-Q5）
vibebara whoami                              # 调 GET /auth/me，回显 username + key 掩码
vibebara logout                              # 删除本机凭据
```

### 8.2 `vibebara status`
列出当前用户全部部署实例（调 `GET /skill-deployments/mine`，§10），对每个用 `local-core.computeDirHash(install_path)` 实算本地 hash 与基线比对，给出统一状态。
```
vibebara status [--project <id>] [--json]
```
`--json` 形如：
```json
{ "deployments": [
  { "id": "dep_1", "skill": "babysit", "tool": "cursor", "project": "proj_1",
    "install_path": "/repo/.cursor/skills/babysit",
    "status": "conflict", "local_dirty": true, "outdated": true } ] }
```

### 8.3 `vibebara merge`（核心）
对一个处于 `conflict` 的部署做 AI 三方合并。

```
vibebara merge [target] [flags]

target            可选；省略时按 §9 解析（cwd 命中 / 唯一冲突）
--deployment <id> 指定部署实例 id
--skill <name>    按 skill 名定位（配合 cwd / --project）
--project <id>    限定项目
--preview         只预览不提交（等价 dry-run；打印合并稿与冲突清单后退出）
--yes             跳过「确认提交」交互（无 manual_conflicts 时才允许直接提交）
--force-manual    存在 manual_conflicts 时仍按合并稿提交（默认拒绝，退出码 4）
--json            结构化输出
```

行为：
1. `read-folder`（本地 `local-core`）+ `computeDirHash` → 调 `POST /skill-deployments/{id}/merge-preview`。
2. 打印 / 输出 `merged`（body/config/resource_ops 摘要）、`preview_change_items`、`manual_conflicts`、`merge_available`、`theirs_hash`。
3. `--preview` → 到此结束（退出码：有 manual_conflicts → 4，否则 0）。
4. 否则确认（`--yes` 跳过）→ 调 `merge-apply`（带 `expectedTheirsHash` 乐观锁）→ `local-core.writeSkill`（overwrite 覆盖落盘）→ `commit-merge` 登记。
5. 乐观锁失败（团队又被推送）→ 退出码 3，提示 `vibebara merge` 重跑。

> 本期 CLI 不做行级编辑；如需人工修改合并稿，用 `--preview` 看清后在本地改文件，再走 `vibebara push`（或重跑 merge）。后续可加 `--edit` 拉起 `$EDITOR` 编辑 `merged`（§15-Q4）。

### 8.4 `vibebara push` / `vibebara pull`
```
vibebara push [target] [--create-version] [--version-label <s>] [--json]
vibebara pull [target] [--overwrite] [--json]
```
push：本地有改动 → `read-folder` 上传 `POST /skill-deployments/{id}/push`；命中冲突拦截（`repo_hash != team.content_hash`）→ 退出码 3，提示「先 pull 或 merge」。
pull：`build-artifact` 取团队最新 → `writeSkill` 覆盖 → `commit-pull`；本地有未推送改动且未 `--overwrite` → 退出码 3。

### 8.5 退出码（全命令统一）
| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 1 | 一般错误 |
| 2 | 用法错误（参数缺失/非法） |
| 3 | 冲突，需用户处置（乐观锁失败 / push 被拦截 / pull 需 overwrite） |
| 4 | 合并存在 `manual_conflicts`（未 `--force-manual`，未完成提交） |
| 5 | 鉴权失败（缺 / 失效 API Key） |
| 6 | 本地盘错误（目录缺失 / 无权限 / 写盘失败） |

---

## 9. 部署寻址 + 同机锁定（无 GUI 时如何定位 deployment）

合并 / 推送 / 拉取端点按 `deployment_id` 寻址。CLI 分两步：**①解析 deployment ②同机校验**。

### 9.1 解析 deployment
1. `--deployment <id>` → 直接用。
2. `--skill <name>`（+ 可选 `--project`）→ 在 `GET /skill-deployments/mine` 结果里匹配。
3. 都没给 → 取 cwd：按**仓库根探测规则**从 cwd 逐级向上、**最近命中者胜**（优先级 `{dir}/.{tool}/skills/{skillId}` > `{dir}/.{tool}` > `{dir}/.git`）定出**本地仓库根**，再在 `mine` 里取 `deploy_path` == 该根（或 `install_path` 落在该根下）的部署；
   - 命中唯一 → 用之；
   - 命中多个 → 列出让用户加 `--skill` 消歧（退出码 2）；
   - 对 `merge`：若该根下唯一处于 `conflict` 的部署，直接选它。

> monorepo / 多 `.git`：取**最内层（最近祖先）**命中；要换根用 `--cwd` 覆盖。约定：在 skill 所在的包目录里跑 CLI。

### 9.2 同机锁定（lock-down，本期方案）
> 背景见 §16 R-B：部署行存的是**部署当时那台机的绝对路径**且「每机一行」。本期 CLI **不做跨机重定位**，改为**锁定同机 + 跨机友好拒绝**（「多机路径同步」本就是 §1 非目标）。

解析到 deployment 后、落盘 / 读盘前做**同机校验**（零后端改动）：
1. 云端记录的 `install_path` 在本机**存在且是目录**；
2. **且**该目录下**确为该 skill**（`SKILL.md` 在 / 目录名 == `skillId`）。

- **通过** → 视为同机，**直接信任** stored `deploy_path`/`install_path`（与 GUI 今天经本地代理的语义一致），照常 read-folder / writeSkill / commit，**不做任何路径推导或回写**。
- **不通过** → 判为跨机 / 仓库搬走 / 未在本机部署 → **拒绝并友好提示**，退出码 6：
  > 该部署登记在 `<install_path>`，本机不存在该路径（或非该 Skill）。请在本机用桌面客户端重新部署，或回原机器操作；CLI 暂不支持跨机。

由此跨机子问题 **RB-2（按 skill 重定位）/ RB-3（跨机 base 取舍）/ RB-4（回写路径）本期均不发生**（编号见 §16 R-B，独立于 §15 的 Q1–Q6）：同机 = 单行、路径有效、base（该行 `abstract_snapshot`）精确无歧义；`mine` 返回的绝对路径仅用于**解析匹配 + 同机校验**。

> 窄风险：两台机**同一绝对路径**各放不同仓库时，9.2-1 会误判「同机」；9.2-2 的 skill 存在性校验把这类误判降到最低。要彻底根治需给 deployment 加 `machine_id`（本期不做）。

---

## 10. 后端改造清单（最小集）

> 鉴权侧已由「Token 根治」完成（见 §6）；**本期 CLI 仅需后端补 1 项**（部署寻址）。

1. **统一凭据消费 —— 已完成 ✓**
   - `backend/app/api/auth.py::get_current_user_id` 已统一走 `await auth_service.verify_credential`，`vhs_` 会话与 `vhk_` PAT 同一路径；`POST /auth/api-key` 经 `create_pat` 签发 PAT；迁移 `20260624_..._add_auth_tokens` 建 `auth_tokens` 并 drop `users.api_key_hash`。
   - **CLI 无需再改后端鉴权**（原计划的 `verify_api_key` 分支 + `api_key_hash` 比对已作废）。
2. **部署列表（自己的，跨项目）—— 待补 ⏳（唯一后端待办）**
   - 新增 `GET /api/v1/skill-deployments/mine`（`Depends(get_current_user_id)`）→ `project_service` 增 `list_user_deployments(user_id)`，按 `UserSkillDeployment.user_id` 查，返回 `UserSkillDeploymentInfo[]`（复用既有 schema，含 `deploy_path`/`install_path`/`installed_hash`/`repo_hash`/`tool_type` 等寻址所需字段）。
   - 现状仅 `GET /projects/{id}/skills` 逐项目返回，CLI 无从跨项目枚举自己的部署（确认无任何 `mine`/全量部署端点）。

> 数据库：Token 根治已新增迁移 `auth_tokens` 并 drop `users.api_key_hash`；`mine` 列表为纯查询，**无新增迁移**。

---

## 11. 实施步骤（评审通过后按序执行）

> **前置条件（开工前需到位）**：
> - **P1 目标后端版本（代码已审查在位 ✓，2026-06-29）**：「Token 根治」与「R-A 响应 snake 化」均已确认落地——`get_current_user_id`→`verify_credential`（`auth.py:51`）、`AuthToken` 模型 + `create_pat` + 迁移 `add_auth_tokens`（含 drop `users.api_key_hash`）、`BuildArtifactResponse` 全 snake 且 `projects.py`/`skill_store.py` 已去 `response_model_by_alias`，无 `verify_token` 残留。**仅余部署态确认**：目标实例的 `auth_tokens` 表已建。注意**双轨建表**——`DB_AUTO_CREATE=True`（默认）时 `init_db` 的 `create_all` 启动即自动建出 `auth_tokens`（`api_key_hash` 死列不 drop 但无害，代码零引用），此时 `alembic upgrade` 非必需；仅当生产设 `DB_AUTO_CREATE=false` 时才**必须** `alembic upgrade head`，否则登录/PAT 校验因缺表 500。速检：目标库 `SHOW TABLES LIKE 'auth_tokens'`，或登录后 `POST /auth/api-key` 能否返回 `vhk_`。
> - **P2 首个 PAT 引导入口 —— ✅ 已定：C+ 桌面一键授权（详见 §6）**：桌面设置按钮「为 CLI 授权」→ `POST /auth/api-key` 铸 `vhk_` → 主进程写 `~/.vibebara/config.json`（`apiKey`+`cloudApiBase`，`0600`）；纯 web/CI 回退为同按钮一次性回显 + 人工 `login --api-key`。见里程碑 **M-pre**。**硬前置**：不挡 M0–M2 编码，挡 M5 登录联调与实际可用。
> - **P3 可达后端地址 + 测试账号**：M5+ 调试与 M9 端到端需一个可达 `IP:port` 与能登录的账号（Q5 现状为 IP+HTTP）。
> - **不构成前置**：正式 HTTPS 域名（Q5，仅挡 GA）、npm scope 归属（桌面内置分发不依赖 npm 发布）。

- **M-pre｜PAT 引导（C+，前置 P2）—— 🟡 代码完成，待桌面实机**：①`frontend` 用户菜单已加「为 CLI 授权」，调 `POST /auth/api-key`；②`desktop` 已加 preload/contextBridge/IPC + 主进程原子写 `{apiKey, cloudApiBase}` 到 `~/.vibebara/config.json`（`0600`）；③web/自动写盘失败会一次性回显 `vhk_`。`desktop build`、`vue-tsc` 与浏览器桌面/移动视口通过；待 Electron 实机点击验证。
- **M0｜脚手架 —— ✅ 已完成**：已建 `local-core/`（CommonJS，兼容现有 local-agent）与 `cli/`（ESM npm 入口 + CommonJS SEA bundle）包；CLI 构建基线 Node>=22.12（对齐 commander 15），`cli` bin=`vibebara`；两端均以 `"@vibebara/local-core": "file:../local-core"` 复用，不建 workspace。
- **M1｜local-core 抽取 —— ✅ 已完成**：已迁入 `hash/walk/fileio/security/gitignore/platform`，落地 `readFolder()` / `writeSkill()`；独立 Python 参考 hash / 固定 cloud hex 对拍与读写/逃逸测试共 3 项通过。
- **M2｜local-agent 切源 —— ✅ 已完成**：对应模块已从 `local-core` re-export / 调用，既有 local-agent 47 tests passed；`electron-builder.yml` 已把 core `package.json + dist` 打进 local-agent 依赖目录。`electron-builder --win --dir` 成功，并已核验 `release/win-unpacked/resources/local-agent/node_modules/@vibebara/local-core/{package.json,dist/index.js}` 存在。
- **M3｜后端寻址 —— ✅ 已完成**：已实现 `GET /skill-deployments/mine` + `project_service.list_user_deployments`，固定最近更新排序；数据库查询 user_id 过滤测试 + 路由鉴权测试通过。
- **M4｜CLI 基础设施 —— ✅ 已完成**：已实现 config（同 C+ 格式）、Bearer REST client、snake_case DTO、JSON/人读输出、退出码体系；CLI build + 6 tests passed。
- **M5｜命令：login/whoami/logout/status —— 🟡 代码完成，待云端联调**：已实现 PAT 登录校验/存储、身份查询、登出、跨项目 status、本地 hash 实算与状态判定；已实现 §9.1 仓库/部署解析 + §9.2 同机校验（退码 6）。待 P3 的真实后端 IP/测试账号做联调。
- **M6｜命令：merge（核心）—— 🟡 代码完成，待云端端到端**：已移植 preview→apply→writeSkill→commit-merge，preview/apply 复用同一份 mine files；已实现 `--preview/--yes/--force-manual`、人工冲突退码 4、theirs 乐观锁冲突退码 3。mock 测试验证 preview 后本地文件变化不会污染 apply 上传树。
- **M7｜命令：push/pull —— 🟡 代码完成，待云端端到端**：push 已实现本地无改动短路、全量文件上传、版本快照参数与冲突退码；pull 已实现本地 dirty 拦截、build-artifact→writeSkill→commit-pull。mock 云端 + 真实临时目录测试通过。
- **M8｜分发与文档 —— ✅ 已完成（Windows 桌面主路）**：CLI 通过 esbuild 聚合依赖后注入 Node 22 SEA，生成无需用户机 Node.js 的 `vibebara.exe`；桌面构建脚本将其作为第五件套构建，electron-builder 打入 `resources/cli`，NSIS 幂等注册用户 PATH、升级保留、真实卸载清理。npm tarball 的 bundled local-core 闭环继续保留，但 `private: true` 不在本期发布。
- **M9｜端到端验收**：见 §12。

每个里程碑结束需：本里程碑单测绿 + 不破坏既有 `local-agent` / `backend` 测试。

---

## 12. 测试计划

- **口径对拍（M1，最关键）**：对同一组目录样本，`local-core.computeDirHash` === `local-agent` 旧实现 === 云端 `_compute_content_hash`（取若干 fixture 固定期望值）。
- **后端鉴权**：`vhk_` PAT 命中 / 失配 / 过期 / 吊销 / 空已由 Token 根治测试覆盖（`backend/tests/test_auth_tokens.py`），CLI 项目不重复；本期只新增 `mine` 列表归属隔离测试（只含本人部署）。
- **CLI 单测（mock 云端）**：merge 三态——干净合并直提、有 `manual_conflicts` 退 4、乐观锁失败退 3；push 拦截退 3；pull 需 overwrite 退 3；未登录退 5；目录缺失退 6。
- **端到端（联调后端 + 真实临时目录）**：构造「A 改本地 + B 已推送」的冲突部署，`vibebara merge --yes` 后：团队仓库 `version+1`、本地被覆盖为合并稿、`status` 回 `synced`，且与 GUI 走同链路结果一致。
- **跨工具冒烟**：在 Cursor / Codex / Claude 各让 Agent 通过 shell 跑 `vibebara merge --json` 验证可调用、输出可解析。

---

## 13. 安全与边界

- **写盘授权来源**：GUI 形态下 `write-skill` 的可写根绑定「用户在桌面确认选定的 deployPath」（见 `local-agent/src/handlers/writeSkill.ts`）。无头无此交互，CLI 的等价授权 = **解析到的 deployment 的 `deploy_path`/`install_path`**（来自云端、归属本人校验）+ `cwd` 约束；仍保留 `safeJoinUnder` / realpath / `..` 逃逸防护。CLI 不接受任意 `--path` 凭空写盘。
- **API Key**：等价长期身份；`0600` 落盘、`whoami` 掩码、CI 走 env 不落盘；覆盖即吊销。
- **LLM 降级**：`merge_available=false`（未配 `LLM_API_KEY` 或失败）时，CLI 必须显式透出（人读高亮 + JSON 字段），避免 Agent 误判「干净合并」；此时建议人工核对或走覆盖/放弃。
- **乐观锁**：`merge-apply` 的 `expectedTheirsHash` 失配 → 不写、退 3；CLI 不自动无限重试（避免与第三方推送活锁），由调用方决定重跑。
- **二进制资源双改**：进入 `manual_conflicts`，默认退 4（除非 `--force-manual`），与 GUI「需手动处理」一致。

---

## 14. 与 MCP 的关系（为什么先 CLI）

- MCP server 是「写一次、所有支持 MCP 的工具共用」，但每个终端要付「配置格式不同（Cursor JSON / Codex TOML / Claude…）+ 传输支持差异 + 覆盖面不全」的接入税；本项目目标 8 个工具（`cursor/codex/windsurf/claude/kiro/trae/qoder/workbuddy`）中仅子集原生支持 MCP。
- CLI 工具无关：一份产物 + 一份 `SKILL.md` 指令，凡能跑 shell 的 Agent / 人 / CI 皆可用，覆盖面最广，且贴合现有「skill 分发到多工具」的定位。
- 二者共用 **同一内核**（`local-core` + `orchestrate`）。MCP 作为后续增强，只是把内核再包一层 stdio 协议外壳 + 各工具配置片段，**不重写业务**。

---

## 15. 待决策 / 开放问题（评审时确认）

- **Q1 local-agent 是否本期就切 `local-core`？** —— ✅ **已定（2026-06-29）：本期切（同源）**。M1 抽 `local-core`、M2 让 local-agent 切源删重复实现，并用 **fixture 对拍测试**（`local-core` == 旧 local-agent 产出 == 云端 `_compute_content_hash`）摁住 hash 漂移（§12 头号验收）。后备：若要缩半径，M1 先只让 CLI 用、local-agent 切源延到 M2 末。
- **Q2 CLI 包归属与共享机制** —— ✅ **已定（2026-06-29；2026-07-16 补充分发闭环）**。`cli` 与 `local-core` **各自独立成包**（`local-core`=纯文件/哈希引擎，被 local-agent 与 cli 共用；`cli`=命令行 App，依赖 local-core + 打云端），CLI **不并入** frontend/backend/desktop/skill-forge。仓库内共用机制 = **`file:` 依赖、不建 workspace 根**：各包保留独立 `node_modules`，`cli`/`local-agent` 经 `"@vibebara/local-core": "file:../local-core"` 引用。理由：`desktop/electron-builder.yml` 的 `extraResources` 逐个拷贝 `../local-agent/node_modules/<dep>`，**workspaces 的依赖 hoist 会令这些路径失效、打断桌面打包**；`file:` 保留"每包各自 node_modules"模型。**npm 分发闭环**：外部用户不存在 `../local-core`，故 `@vibebara/cli` 通过 `bundleDependencies` 将 local-core 内嵌在 tarball，不要求单独发布 local-core。scope `@vibebara/cli`、bin 名 `vibebara`。
- **Q3 PAT 管理面** —— 🔸 **后续（不阻塞本期）**。当前「重生成 = 轮换」对 CLI 够用；是否补「列出 / 命名 / 单独吊销 PAT」端点 + 设置页 UI（`auth_tokens` 表已支持多条 / 命名 / 吊销，**仅缺端点**）留作增强。
- **Q4 合并稿人工编辑** —— 🔸 **后续（不阻塞本期）**。本期用 `--preview` + 本地改文件 + `push`；`--edit` 拉起 `$EDITOR` 直接改 `merged` 留作增强。
- **Q5 生产云端 Base URL 默认值** —— ✅ **已定（2026-06-29，方向）**。背景：CLI 是首个「无承载来源」的客户端——web 前端用同源相对 `/api/v1`（随 origin 解析）、桌面由外壳注入 `cloudApiBase`，CLI **既无 serving origin 也无注入壳**，必须显式取值。**现状：暂无正式域名，仅 IP**。决策：本期**不烤死生产默认**，由 `vibebara login --cloud http://<ip>:<port>/api/v1`（或 `VIBEBARA_CLOUD_API_BASE` / `--cloud-api-base`）写入 `~/.vibebara/config.json`；CLI 编码不被阻塞，仅"开箱即连生产"延后。**待正式域名（HTTPS）就位后**：把默认值烤进二进制并默认走 HTTPS。⚠️ **安全注记**：IP + HTTP 下 Bearer / API Key **明文过线**，仅限可信内网；公网 GA 前**必须**切 HTTPS 域名。CLI 本期不需 `cloudWsBase`（merge/push/pull/status 全 REST）。
- **Q6 分发方式** —— ✅ **已调整（2026-07-31）：Windows 桌面安装包内置 Node SEA 为主路**。安装包携带独立 `vibebara.exe`，注册当前用户 PATH，用户无需 Node/npm；安装或升级后新开终端即可调用。npm tarball、标准 bin/shebang 与 bundled local-core 保留用于仓库开发和 CI，但包继续 `private`，本期不做 registry 发布。发布机构建基线 Node>=22.12，正式包由 electron-builder 对桌面程序、安装器与内置 CLI 统一签名。

---

## 16. 最新代码复审：风险点（CLI 实施前必读）

> 2026-06 基于最新代码逐文件复审。R1（鉴权）/R5（mine 寻址）已并入 §6/§10；以下为**新增/仍待正视**的工程风险，按严重度排序。
>
> **本轮处置（2026-06-24）**：R-A（响应统一 snake）/ R-C / R-D **已改代码**（后端 + 前端，`vue-tsc` 通过、相关 route 测试通过）；R-E / R-F **保留**（本期不改代码）。
>
> **R-B 决策（2026-06-29）**：采「**同机锁定 + 跨机友好拒绝**」（见 §9.2 与下方 R-B 决策块）——不做跨机重定位，跨机子问题 RB-1–RB-4 收敛，**零后端改动**（仍只需 `mine`）；代价是全新 CI runner / 跨机需先 deploy（本期非目标）。

### R-A（高）DTO 大小写**混用** —— ✅ 已统一为 snake_case（方向①）
**审查结论**：前端**无**全局 camel↔snake 转换层（`frontend/src/api/client.ts` 拦截器仅做 Bearer 注入、防缓存、错误日志），各 `api/*.ts` interface **逐字段硬编码**后端真实口径——故后端口径一改，前端必须同链改。原混用面：仅 `build-artifact`、`merge-apply.artifact` 响应为 camelCase（`response_model_by_alias=True` + `serialization_alias`），其余响应全 snake_case。

**已改（响应全量 snake_case）**：
- **后端**：`BuildArtifactResponse` 去除 4 个 `serialization_alias`（`skillId`/`repoHash`/`repoVersion`/`abstractSnapshot` → `skill_id`/`repo_hash`/`repo_version`/`abstract_snapshot`）；4 条路由去除 `response_model_by_alias=True`（`projects.py` 的 project / deployment build-artifact + merge-apply，`skill_store.py` 的 store build-artifact）。`merge-apply.artifact` 内嵌 `BuildArtifactResponse` 随之转 snake。`schemas/project.py` 顶部约定注释更新为「响应全量 snake」。
- **前端**：`orchestration.ts` 的 `BuildArtifactResponse` interface 及全部 `artifact.*` 读取点（deploy / global-deploy / pull / mergeCommit / import 共 14 处）camel→snake。`vue-tsc` 通过。
- **测试**：`test_m4_orchestration.py` 两处 HTTP 响应断言改 snake（其余用例读 service 层 snake dict、不受影响）；build-artifact route 测试通过。

**口径现状（统一后）**：
- **响应**：全链 snake_case（CLI / 前端单一读取规则）。
- **请求**：仍 `populate_by_name=True` + camelCase alias（前端继续发 camel，**CLI 可直接发 snake**——两者皆受）；`merged.resource_ops` 本就 snake。即「请求收 camel/snake 皆可、响应恒 snake」。

**安全网（CLI）**：`cli/src/cloud/types.ts` 移植自前端 interface（现已全 snake）+ 逐端点合同测试；**勿**做全局 camel↔snake 转换。

> 备注：`backend/app/api/devices.py` 的 `response_model_by_alias=True` 属设备模块、与协作链路无关，本次未动。

### R-B（高）跨机 / CI **绝对路径失配** —— ✅ 已决策：同机锁定 + 跨机友好拒绝
**审查结论（换机使用现状）**：系统**不做任何路径重定位**，部署记录持久化的是**部署当时那台机的绝对路径**：
- `register_deployment`（`project_service.py`）以 `deploy_path_norm = str(Path(deploy_path))` + `install_path`（前端实算上报）**原样落库**；UPSERT 主键含 `deploy_path` ⇒ **同一 (user, project, skill, tool) 在不同路径生成不同部署行**。即「多机协作」现状 = **每台机各自重新部署**、各得一行 deployment（按 `deploy_path` 区分），**没有跨机共享的单一部署**。
- 基线 hash（`installed_hash` / `_compute_content_hash`）按**相对 POSIX 路径 + 字节内容**计算，**与机器/绝对路径无关 ⇒ 可跨机**；团队产物 `build_deployment_artifact` 从 Store 构建，**也与本地路径无关**。
- 但所有**摸本地盘**的动作都按绝对路径走：
  - `status` / `local-status` / `promote` / `resume`：读 `install_path` → 换机不存在 → `_compute_content_hash` 返回 `""` → 状态 `missing`（`resume` 直接回「本地部署目录缺失，请重新部署」）。
  - `pull`：产物来自 Store（OK），但 `writeSkill` 落 `deploy_path`（A 机路径）→ 目标不存在 → `WRITE_ROOT_FORBIDDEN`。
  - `push` / `merge`：读 `install_path`（A 机）→ `missing` → 阻断。
- **结论**：在另一台机 / CI runner / 另一处 clone 上，**直接信云端绝对路径的链路全部失败**（与「无头 / CI」初衷冲突）；唯一可跨机的是「内容 hash + 团队产物」。

**决策（本期：同机锁定 + 跨机友好拒绝；详见 §9.2）**：**不做**跨机路径重定位（「多机路径同步」本就是 §1 非目标）。CLI 解析到 deployment 后、落盘前做**同机校验**——云端 `install_path` 在本机**存在且确为该 skill**（`SKILL.md` 在 / 目录名 == `skillId`）：
- **通过** → 直接信任 stored 路径（同 GUI 语义），照常 read / write / commit，不做路径推导或回写。
- **不通过** → 退出码 6 + 友好文案「请在本机重新部署或回原机操作，CLI 暂不支持跨机」。

**RB-1–RB-4 收敛结论**（此处 RB-编号专指 R-B 的跨机子问题，**与 §15 的 Q1–Q6 无关**）：
- **RB-1（仓库根探测）**：采「从 cwd 逐级向上、最近命中者胜，优先级 `.{tool}/skills/{skillId}` > `.{tool}` > `.git`」，本期**仅作 cwd→部署的解析辅助**（§9.1-3）。
- **RB-2 / RB-3 / RB-4 本期不发生**：同机 = 单行、路径有效、base（该行 `abstract_snapshot`）精确无歧义；无需按 skill 重定位、无 base 歧义、无需回写路径。
- **零后端改动**（仍只需 §10 的 `mine`）。**代价**：全新 CI runner / 跨机需先 deploy（本期非目标）。**窄风险**（两机同绝对路径不同仓库）由 9.2-2 的 skill 存在性校验兜底；彻底根治需 `machine_id`（本期不做）。

### R-C（中）`orchestration.ts` 顶部「尚未实现」注释**已过时** —— ✅ 已清理
原顶部注释及文件内 7 处 `TODO(cloud): …（M1）` 行均称端点「当前后端尚未实现」；复审确认这些端点（build-artifact / register-deployment / commit-pull / push / import-content / merge-preview / merge-apply / commit-merge）**均已在 `backend/app/api/projects.py` 落地**。

- **已改**：`frontend/src/api/orchestration.ts` 顶部注释改为「M1 已落地」；章节头与 7 处 `TODO(cloud)` 行改为「云端协作端点（已实现）」，保留各自行为描述。纯注释改动、零运行时影响（`vue-tsc` 通过）。

### R-D（中）merge 两步各读一次本地 —— ✅ 已改为只读一次（乐观锁仍只锁 theirs）
**已改**：`mergePreviewOrchestrated` 把 preview 阶段 `read-folder` 的 mine 文件树**回填**到响应 `mineFiles`；经 `projectSyncStore`（按 `deploymentId` 缓存）透传给 `mergeCommitOrchestrated`，apply **复用**该树而**不再二次 `read-folder`**（绕过 preview 直接 commit 时回退再读一次作兜底）。效果：preview→apply **只读一次本地**，且「合并稿所基于的 mine」与 apply 落库的 mine **位级一致**。改动文件：`orchestration.ts` / `projects.ts` / `projectSyncStore.ts`（`vue-tsc` 通过）。

- **仍存（设计取舍）**：`merge-apply` 乐观锁 `expectedTheirsHash` **只锁团队侧**（theirs）；preview→commit 之间团队侧被他人再推 → 失配 → 退码 3，提示重跑。mine 侧因「只读一次」已无 preview/apply 不一致问题。
- **CLI 落地**：单进程内连续 preview→apply，沿用同一份 files；要改本地请走 `--preview` 看清后改文件再 `push`。

### R-E（低）`transfer="url"` 资源未实现 —— 保留（本期不改代码）
`writeSkill.ts` 对 `transfer==="url"` 抛 `BAD_REQUEST`（M3 仅 inline）；当前 build-artifact 只下发 inline 资源。`local-core.writeSkill` 同样仅支持 inline；若团队仓库出现 url 资源（大文件预留），CLI 与 GUI 一样失败——**文档化为已知边界**，留待「url 下载（带 Bearer）」统一补。**本期保留，不改代码。**

### R-F（低）local-core 迁移面可**收窄**（merge/push/pull 全是 project scope）—— 保留（本期不改代码）
merge/push/pull 三链落盘均 `scope:'project'`（传 `deployment.deploy_path`），**不触发 `platformSkillsDir`**。MVP 的 `local-core` 必需件 = `hash` / `walk` / `fileio` / `security` / `gitignore` / `readFolder` / `writeSkill(project 分支)`；`platform.ts`（8 工具目录 + trae 国内/国际探测）仅 deploy / platform-scope 才需，可**延后到 deploy 命令期**迁移，缩小 M1 爆炸半径。但 `computeDirHash` 三方（后端 `_compute_content_hash` / `_compute_dir_hash`、local-agent、CLI）**位级对拍**仍是 M1 头号验收项。**本期保留，不改代码。**

---

## 附：关键复用点速查

| 能力 | 位置 |
|------|------|
| 三方合并算法 | `backend/app/services/skill_merge_service.py::merge_three_way` |
| 合并/推送/拉取端点 | `backend/app/api/projects.py`（`merge-preview`/`merge-apply`/`commit-merge`/`push`/`build-artifact`/`commit-pull`） |
| 现有 GUI 编排（移植蓝本） | `frontend/src/api/orchestration.ts` |
| 目录 hash 冻结算法 | `local-agent/src/hash.ts::computeDirHash` |
| 写盘语义（路径推导/覆盖/gitignore/逃逸） | `local-agent/src/handlers/writeSkill.ts` |
| 读文件夹语义 | `local-agent/src/handlers/readFolder.ts` |
| PAT 签发（`vhk_`，轮换） | `backend/app/services/auth_service.py::create_pat` / `generate_api_key` |
| 统一凭据校验（已根治） | `backend/app/services/auth_service.py::verify_credential` ← `backend/app/api/auth.py::get_current_user_id` |
| 编排端点（已全部落地） | `backend/app/api/projects.py`（build-artifact / register-deployment / push / commit-pull / merge-preview / merge-apply / commit-merge） |

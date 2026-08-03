# Vibebara — 文档索引

> Vibebara 是一个 AI 协作中台，以 `skill-forge` 为统一 Skill 工具链，让使用不同 Vibe Coding 工具（Cursor、Codex 等）的团队成员共享、部署、同步 Skill。

## 目录结构

```
docs/
├── architecture.md              整体架构（现行）
├── gitlab-cicd.md               GitLab CI/CD 与后端生产部署运维
│
├── design/                      现行功能与子系统设计（How it works now）
│   ├── skill-forge.md               抽象 Skill 包格式 & 多平台构建规则、反向导入
│   ├── skill-collaboration-sync.md  ★ Skill 协作与同步的当前实现（单一事实来源）
│   ├── ai-assisted-merge.md         冲突时的 AI 三方合并（预览可编辑 + 一键提交）
│   ├── skill-merge-cli.md           无头 CLI 的架构、执行进度与验收计划
│   ├── ide-import.md                从 IDE 工具导入 Skill 到个人仓库
│   ├── personal-team-skill-split.md 个人 / 团队 Skill 拆表（数据层隔离）
│   └── cos-storage.md               后端 Skill 存储迁移到腾讯云 COS（对象存储）
│
├── research/                    调研（Why & What，参考）
│   ├── ai-coding-skills.md          8 大平台 Skill/指令体系全景调研
│   └── codex-vs-claude.md           Codex CLI vs Claude Code 深度对比
│
└── archive/                     历史 / 已归档（仅作决策溯源，不再维护）
    ├── desktop-migration/           方案 B 桌面客户端迁移（M0–M5 全程记录，已完成）
    └── *-plan.md                    早期过程计划（功能均已落地，被 design/ 收编）
```

## 文档清单

### 现行（与代码一致，优先参考）

| 文档 | 类别 | 摘要 |
|------|------|------|
| [architecture.md](architecture.md) | 架构 | 桌面壳 + 本地代理 + 云端后端三层架构；Vue 3 前端 + FastAPI + skill-forge + WebSocket |
| [gitlab-cicd.md](gitlab-cicd.md) | 运维 | GitLab Runner、生产变量、后端发布、备份、健康检查与回滚 |
| [design/skill-forge.md](design/skill-forge.md) | 设计 | 抽象 Skill 包（`skill.config.yaml` + `SKILL.md`）、多平台构建规则、反向导入 |
| [design/skill-collaboration-sync.md](design/skill-collaboration-sync.md) | 实现纪要 | 个人/团队仓库隔离、放入团队、部署、手动推送（抽象层 diff）、拉取更新的完整链路（**单一事实来源**） |
| [design/ai-assisted-merge.md](design/ai-assisted-merge.md) | 设计 | 推送冲突时对 base/mine/theirs 做 AI 三方合并（正文 + 配置 + 文本资源），预览可编辑后一键提交 |
| [design/skill-merge-cli.md](design/skill-merge-cli.md) | 设计与执行计划 | `vibebara` CLI 的鉴权、本地共享内核、merge/push/pull 编排、分发与验收进度 |
| [design/ide-import.md](design/ide-import.md) | 设计 | 从已安装 IDE（Cursor/Codex 等）的全局目录反向导入 Skill 到个人仓库 |
| [design/personal-team-skill-split.md](design/personal-team-skill-split.md) | 设计 | 个人 / 团队 Skill 数据层拆表隔离（`owner_id` / `scope`） |
| [design/cos-storage.md](design/cos-storage.md) | 设计 | Skill 持久化由本地磁盘卷迁移到腾讯云 COS；hash 口径与本地代理位级一致 |

### 调研（参考）

| 文档 | 摘要 |
|------|------|
| [research/ai-coding-skills.md](research/ai-coding-skills.md) | Cursor、Codex、Claude Code、Copilot、Windsurf、Cline、Aider、Continue.dev 的 Skill/指令系统对比 |
| [research/codex-vs-claude.md](research/codex-vs-claude.md) | OpenAI Codex CLI 与 Anthropic Claude Code 指令系统、Agent Skills 开放标准的深度分析 |

### 历史 / 已归档

详见 [archive/README.md](archive/README.md)。其中：

- `archive/desktop-migration/` — 方案 B「本机单体 → 桌面客户端」迁移的全过程记录（技术路径总览 + M0–M5 里程碑实施记录 + 上线 Checklist + 本地代理 API 契约）。迁移**已完成**，相关产物即当前的 `desktop/` + `local-agent/` + cloud 后端。
- `archive/*-plan.md` — Skill 协作/同步各特性的早期设计计划，功能**均已落地**，内容已被 `design/skill-collaboration-sync.md` 汇总收编。

> 归档文档仅保留作决策溯源，不再单独维护；如与 `design/` 下的现行文档或代码冲突，**以后者为准**。

## 阅读顺序

1. **了解背景** → `research/ai-coding-skills.md`、`research/codex-vs-claude.md`（各平台 Skill 体系）
2. **理解设计** → `design/skill-forge.md`（抽象包与多平台构建）
3. **把握全局** → `architecture.md`（三层架构与 Skill Forge 的位置）
4. **掌握当前实现** → `design/skill-collaboration-sync.md`（协作与同步链路、数据模型、API、前端入口）
5. **追溯决策**（可选）→ `archive/`（迁移全程与各特性当初的方案取舍）

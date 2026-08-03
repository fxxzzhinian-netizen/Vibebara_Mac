# Vibebara — AI 协作中台

Vibebara 是一个面向 Vibe Coding 工具（Cursor / Codex 等）的 **Skill 协作平台**：在平台抽象层统一管理 Skill，支持团队 / 项目维度的 Skill 关联、本地部署、改动推送与拉取更新，并通过 WebSocket 实时同步「项目动态」。

## 产品形态

| 形态 | 状态 | 说明 |
| --- | --- | --- |
| **桌面客户端（Electron）** | 主线 | 三层架构：桌面壳 + 本地代理 + 云端后端。后续发版、测试均以此为准 |
| Web 前端（浏览器） | 仅初期验证 | 早期原型验证用，不再作为发布形态。代码保留供参考 |

## 技术栈

| 层 | 技术 |
| --- | --- |
| 云端后端 | Python 3.10+ · FastAPI · Uvicorn · SQLAlchemy(async) · MySQL(aiomysql) · WebSocket |
| 桌面壳 | Electron · TypeScript（主进程 + preload） |
| 本地代理 | Node.js 20+ · TypeScript（纯 TS 薄代理，文件落盘/扫描/hash/监控） |
| 协作 CLI | TypeScript · Commander · Node 22 SEA（桌面安装包内置，用户机无需 Node.js） |
| 渲染层 | Vue 3 · Vite · Pinia · Vue Router · Axios（桌面壳加载 `frontend/dist` 产物） |
| Skill 构建 | Node 端 skill-forge bridge（`backend/skill-forge`） |
| 部署 | Docker · Docker Compose（云端后端 + MySQL） |

## 目录结构

```
Vibebara/
├── backend/              # FastAPI 云端后端（app/ 主代码，skill-forge/ Skill 构建桥，Dockerfile）
├── desktop/              # Electron 桌面壳（主进程 + 预加载 + 打包配置）
├── cli/                  # vibebara 无头协作 CLI（merge/push/pull/status）
├── local-core/           # CLI 与 local-agent 共用的文件/hash/安全内核
├── local-agent/          # 本地代理（纯 TS 薄代理，负责文件落盘/扫描/hash/监控）
├── frontend/             # Vue 3 + Vite 渲染层（桌面壳复用其 dist/ 产物）
├── docs/                 # 设计与方案文档
├── docker-compose.yml    # 云端部署编排（后端 + MySQL）
├── build-desktop.ps1     # Windows 桌面客户端一键构建/运行/打包脚本
├── start.ps1             # Windows 一键启动脚本（浏览器形态，仅初期验证用）
├── start.sh              # Linux / macOS 一键启动脚本（浏览器形态，仅初期验证用）
└── README.md
```

## 架构概览

```
开发者本机                                    云服务器
┌─────────────────────────────┐          ┌───────────────────────┐
│  Electron 桌面壳 (desktop/)  │          │  Docker               │
│  ├─ 渲染层 (frontend/dist)   │  HTTP/WS │  ├─ backend (cloud)   │
│  ├─ 本地代理 (local-agent/)  │ ───────► │  │  └─ skill-forge    │
│  └─ CLI (vibebara.exe)       │          │  └─ MySQL 8.0         │
└─────────────────────────────┘          └───────────────────────┘
```

- **桌面壳**：窗口管理、拉起本地代理、注入运行时配置、安全存储 token。
- **本地代理**：仅监听 `127.0.0.1`，承接文件落盘/目录浏览/扫描/hash/监控。
- **云端后端**：以 `DEPLOYMENT_MODE=cloud` 运行，提供数据/协作/广播能力。

---

## 常用命令速查

日常更新两步走：先在**服务器**拉取最新代码并重建，再在**本机**启动桌面壳连云端。

### 1. 服务器：拉取构建（Linux，bash）

```bash
cd vibebara                              # 进入仓库目录
git pull && docker compose up -d --build

# 验证
docker compose ps                       # backend、mysql 均为 running/healthy
docker compose logs --tail=30 backend   # 查看启动日志
curl http://localhost:8000/health       # {"status":"healthy",...}
```

> 个人/团队 Skill 拆表（破坏性 schema 变更，丢弃旧数据）部署一次性命令：
> `git pull && docker compose down -v && docker compose up -d --build`（`down -v` 会清空全部数据卷并重建空库，种子用户 DAIL/DAIL2 自动重建）。详见 `docs/design/personal-team-skill-split.md`。

> 若构建走了缓存导致依赖没更新：`docker compose build --no-cache backend && docker compose up -d`。

### 2. 本机：启动桌面壳（PowerShell，连云端后端）

```powershell
$env:VIBEBARA_CLOUD_API_BASE = "http://43.136.128.162:8000/api/v1"
$env:VIBEBARA_CLOUD_WS_BASE  = "ws://43.136.128.162:8000"
.\build-desktop.ps1 -Quick -NoBe
```

> - `-NoBe`：不在本机起后端，直连云端。
> - 首次或代码刚更新用上面这条（重建前端 + 桌面壳 + 本地代理三件套）；代码没改想秒开加 `-Quick`：`.\build-desktop.ps1 -Quick -NoBe`。
> - 当前测试服务器尚未部署 TLS，暂时使用 HTTP/WS；登录凭据会以明文链路传输，不应扩大到正式外部发布。

---

## 云端后端部署（Docker）

后端以 Docker 容器部署到云服务器（含 MySQL），桌面壳从本机直连。

### 前置要求

- 一台 Linux 云服务器（Ubuntu 推荐），有公网 IP
- Docker 20+ 及 Docker Compose 插件
- 当前测试环境安全组放行 `8000/tcp`

> 国内云服务器安装 Docker 建议使用阿里云/腾讯云镜像源，详见下方「国内环境注意事项」。

### 部署步骤

```bash
# 1. 拉取代码
git clone http://162.14.122.9/dailtech/vibebara/cowork-deploy.git vibebara
cd vibebara

# 2. 配置环境变量（.env 与 docker-compose.yml 同目录，不进 git）
echo "JWT_SECRET=$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')" >> .env
printf 'DB_USER=cowork\nDB_PASSWORD=你的数据库密码\nMYSQL_ROOT_PASSWORD=你的Root密码\n' >> .env
# Skill 持久化改用腾讯云 COS 对象存储（不再用本地磁盘卷）。COS_BUCKET/COS_REGION 已在
# docker-compose 设默认值，仅需补密钥；详见 docs/design/cos-storage.md。
printf 'STORAGE_BACKEND=cos\nCOS_SECRET_ID=你的SecretId\nCOS_SECRET_KEY=你的SecretKey\n' >> .env
printf 'ALLOWED_ORIGINS=["null","https://你的Web域名"]\nADMIN_USERNAMES=["你的管理员用户名"]\n' >> .env

# 3. 构建并启动
docker compose up -d --build

# 4. 验证
docker compose ps                        # backend、mysql 均为 running/healthy
docker compose logs --tail=30 backend    # 期望：MySQL 表就绪 / 跳过预设用户
curl http://localhost:8000/health        # {"status":"healthy",...}
```

### 创建首个账号

cloud 模式不会创建任何预设弱口令账号。先在服务器签发一次性邀请码：

```bash
docker compose exec backend python scripts/generate_invites.py -n 1
```

再从客户端使用该邀请码注册；管理员用户名须与 `.env` 的 `ADMIN_USERNAMES` 一致。

### 前端开发者模式（跳过登录直调 UI）

只想调样式 / 改前端时，不必每次都登录 + 过滑块验证。开启后会注入一个「假登录态」直接进入主界面。

**开启步骤：**

```bash
# 在 frontend/ 下创建 .env.local（已被 .gitignore 忽略，不会提交）
echo "VITE_DEV_SKIP_AUTH=true" > frontend/.env.local

# 重启开发服务器（env 变更需重启才生效）
cd frontend && npm run dev
```

打开 `http://localhost:5173/` 即直达主页，无需登录。关闭时把值改为 `false` 或删除 `frontend/.env.local`，再重启即可。

**说明与边界：**

- **仅本地 dev 生效**：开关同时要求 `import.meta.env.DEV`（即 `vite dev`），`vite build` 产物里恒为关闭，不会泄漏到线上。
- **只绕过前端鉴权**：后端接口仍会因 token 非法返回 `401`（控制台可见报错），页面以「空数据」渲染。**纯 UI/样式调试足够**；需要真实数据时请关闭本开关、正常登录（或配合后端 `CAPTCHA_REQUIRED=false` 免滑块登录）。
- 实现位置：`frontend/src/runtime/devAuth.ts`（开关 + 假 token/假用户），在 `tokenStorage.getToken()`、`authStore`（`init`/`fetchMe`）三处接入。

### 邀请码（测试版注册收口）

测试版注册需填写后台签发的邀请码（格式 `VH-XXXX-XXXX`，大小写不敏感、连字符可省略）。种子账号不受影响。

**服务器上签发 / 管理（推荐）：**

```bash
# 签发 10 个一次性邀请码
docker compose exec backend python scripts/generate_invites.py -n 10

# 签发 1 个可用 20 次、30 天后过期的码（适合发到一个测试群）
docker compose exec backend python scripts/generate_invites.py --max-uses 20 --expires-days 30 --note "首批内测群"

# 查看全部邀请码及使用状况 / 吊销某个码
docker compose exec backend python scripts/generate_invites.py --list
docker compose exec backend python scripts/generate_invites.py --disable VH-8K2M-9DQ4
```

**管理 API（管理员账号登录后调用，默认白名单 `DAIL`）：**

- `POST /api/v1/invites/generate` — 批量签发（`count` / `max_uses` / `expires_in_days` / `note`）
- `GET /api/v1/invites` — 列出全部码及使用状况
- `POST /api/v1/invites/{code}/disable` — 吊销

**相关配置（环境变量 / `.env`）：**

- `INVITE_CODE_REQUIRED`（默认 `true`）— 设为 `false` 可放开注册（本地开发用）
- `ADMIN_USERNAMES`（默认 `["DAIL"]`）— 邀请码管理端点的管理员用户名白名单
- `CAPTCHA_REQUIRED`（默认 `true`）— 登录/注册需通过滑块拼图人机验证；本地开发/脚本调试可设 `false`。挑战与 token 为进程内存态，依赖后端单进程部署（同 WS 约束）

### 日常运维

```bash
# 更新代码后重新部署
git pull && docker compose up -d --build

# 重启 / 停止 / 日志
docker compose restart backend
docker compose down                # 停止（数据卷保留）
docker compose logs -f backend

# 备份数据库
docker compose exec mysql sh -c 'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" cowork' > backup_$(date +%F).sql
```

> 数据持久化在 Docker 卷（`mysql-data`、`skill-store`），`docker compose down` 不会丢数据；只有 `down -v` 才删卷。

### 国内环境注意事项

Dockerfile 已将所有源切换为国内镜像（腾讯云 apt + npmmirror Node/npm + 清华 pip），适配国内云服务器网络。非腾讯云环境构建时，可覆盖 apt 镜像：

```bash
docker compose build --build-arg APT_MIRROR=mirrors.aliyun.com backend
```

留空则恢复官方源：`--build-arg APT_MIRROR=`。

建议同时配置 Docker Hub 拉取加速（`/etc/docker/daemon.json`）：

```json
{ "registry-mirrors": ["https://mirror.ccs.tencentyun.com"] }
```

---

## 桌面客户端开发与联调

桌面壳是 Vibebara 的**唯一发布形态**，架构为「桌面壳 + 本地代理 + 云端后端」三层。

| 层 | 目录 | 说明 |
| --- | --- | --- |
| 桌面壳 | `desktop/` | Electron 主进程，窗口管理、拉起本地代理、注入运行时配置、安全存储 token |
| 本地代理 | `local-agent/` | 纯 TS 薄代理，仅监听 `127.0.0.1`，文件落盘/目录浏览/扫描/hash/监控 |
| 云端后端 | `backend/` | FastAPI，以 `DEPLOYMENT_MODE=cloud` 运行（服务器 Docker 部署） |

### 环境要求（开发者本机）

- **Node.js** 20+（含 npm）
- **Python** 3.10+（仅本地起后端调试时需要；连云端后端则不需要）

### 一键启动（连云端后端联调）

云端后端已在服务器部署后，开发者本机只需指定服务器地址：

```powershell
$env:VIBEBARA_CLOUD_API_BASE = "http://43.136.128.162:8000/api/v1"
$env:VIBEBARA_CLOUD_WS_BASE  = "ws://43.136.128.162:8000"
.\build-desktop.ps1 -NoBe     # 不启动本地后端，直连云端
```

> 首次运行不要加 `-Quick`（需构建三件套）。后续代码没改时可用 `.\build-desktop.ps1 -Quick -NoBe` 秒开。

### 一键启动（本地全栈，含后端）

本机同时跑后端（需 Python + MySQL）：

```powershell
.\build-desktop.ps1            # 零参数：构建三件套 → 拉起 cloud 后端 → 启动桌面壳
```

> 需确保 MySQL 可连接且 `cowork` 库已创建（`CREATE DATABASE cowork CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`）。

### 其他启动方式

```powershell
.\build-desktop.ps1 -Quick       # 跳过构建，直接启动（代码没改时用，秒开）
.\build-desktop.ps1 -NoBe        # 不启动后端（后端已在别处运行）
.\build-desktop.ps1 -Dev         # 开发模式：前端走 Vite dev server，支持热更新
.\build-desktop.ps1 -BuildOnly   # 仅构建，不启动任何服务
```

### 单独构建前端

桌面壳生产模式加载 `frontend/dist` 产物。**只改了前端代码**时，可只重建前端，再用 `-Quick` 秒开：

```powershell
cd frontend
npm install        # 仅首次或依赖变更时需要
npm run build      # 执行 vue-tsc 类型检查 + vite 打包，输出到 frontend/dist
cd ..
.\build-desktop.ps1 -Quick -NoBe   # dist 已最新，秒开即可看到改动
```

> `-Quick` 会跳过已有产物的构建。改了前端却仍用 `-Quick` 启动，会看到旧界面——此时先 `npm run build` 重建 dist，或去掉 `-Quick`（让 `build-desktop.ps1` 重建 local-core、CLI、本地代理、前端与桌面壳五件套）。

### 打包为 Windows 安装包

```powershell
.\build-desktop.ps1 -UnsignedDist # 构建未签名 NSIS 安装包，供本地/内部测试
.\build-desktop.ps1 -Dist         # 构建正式签名 NSIS 安装包
.\build-desktop.ps1 -Pack         # 构建解压即用目录（不生成安装包）
```

每次构建都会同时输出独立 CLI 到 `desktop/release/vibebara.exe`，方便本地终端验证；
`-Dist` 完成后该文件会由安装包内已签名版本覆盖，可随正式产物分发。

> `-Dist` 是正式发布路径，会强制要求 `WIN_CSC_LINK` / `WIN_CSC_KEY_PASSWORD`
>（或对应 `CSC_*`）代码签名凭据及 HTTPS `VIBEBARA_UPDATE_URL`；缺任一项即拒绝产出安装包。
> `-UnsignedDist` 会生成带完整安装/卸载流程的未签名内测安装包；`-Pack` 仅生成本地试运行目录。
>
> NSIS 安装包内置无需 Node.js 的 `vibebara.exe`，并把其目录加入当前用户 PATH。
> 安装或覆盖升级后需要**重新打开终端**，再运行 `vibebara --version` 验证。

### CLI 授权与使用

1. 安装并登录 Vibebara Desktop。
2. 在用户菜单点击「为 CLI 授权」，桌面端会写入 `%USERPROFILE%\.vibebara\config.json`。
3. 新开 PowerShell，运行 `vibebara whoami`；随后可使用 `status`、`merge`、`push`、`pull`。

源码开发态不会修改系统 PATH；需要从源码调用时，在 `local-core` 与 `cli` 依次构建后，
可运行 `node cli/dist/index.js --help`，或在 `cli` 目录执行 `npm link`。

### 云端地址覆盖

桌面壳默认连接本机 cloud demo。切换到真实云端时：

- **环境变量**（联调优先级最高）：

```powershell
$env:VIBEBARA_CLOUD_API_BASE = "http://43.136.128.162:8000/api/v1"
$env:VIBEBARA_CLOUD_WS_BASE  = "ws://43.136.128.162:8000"
$env:VIBEBARA_UPDATE_URL     = "https://你的更新域名/desktop/"
```

- **配置文件**：`%APPDATA%/@vibebara/desktop/vibebara-desktop.config.json`

```json
{
  "cloudApiBase": "http://43.136.128.162:8000/api/v1",
  "cloudWsBase": "ws://43.136.128.162:8000",
  "updateUrl": "https://你的更新域名/desktop/"
}
```

安装包当前内置上述 HTTP/WS 测试地址，也可通过环境变量或配置文件覆盖。
正式构建会生成更新元数据，把 `desktop/release/` 中安装包、blockmap 和 `latest.yml`
同步到 `VIBEBARA_UPDATE_URL` 对应的静态存储即可启用自动更新。

---

## 核心功能流程

1. **关联 Skill**：在团队 / 项目下从平台仓库关联 Skill。
2. **部署到本地**：把 Skill 部署到本机项目目录（`.cursor/skills` 或 `.codex/skills`），平台开始跟踪该实例。
3. **推送（Push）**：本地改动后点「推送」，改动写回团队仓库并以抽象层改动点记录到「项目动态」，其他成员实例被标记为「可更新」。
4. **更新本地（Pull）**：其他成员一键把团队最新内容拉取覆盖到本地部署目录。
5. **实时同步**：项目动态通过 WebSocket 实时刷新，并带轮询兜底，断线自动重连。

---

## Web 前端（仅初期验证，不再作为发布形态）

`frontend/` 中的 Vue 3 + Vite 前端是早期原型验证用的浏览器形态。代码保留供参考和渲染层复用（桌面壳加载 `frontend/dist` 产物），但**不作为独立发布形态**。

如需临时使用浏览器访问（调试/演示），可用一键启动脚本：

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File .\start.ps1

# Linux / macOS
chmod +x start.sh && ./start.sh
```

> 需本机同时运行后端。前端通过 Vite 代理转发 `/api`、`/ws` 到 `127.0.0.1:8000`。

---

## 常见问题

- **后端启动报数据库连接错误**：确认 MySQL 已启动、`cowork` 库已创建，并核对 `.env` 的 `DATABASE_URL`。Docker 部署时检查 `docker compose ps` 确认 mysql 为 healthy。
- **Docker 构建报 `cryptography` 缺失**：`requirements.txt` 已包含 `cryptography>=42.0.0`（MySQL 8.0 `caching_sha2_password` 认证必需）。若旧缓存导致未生效，用 `docker compose build --no-cache backend` 重建。
- **Docker 构建慢 / 拉镜像超时**：国内云服务器需配置镜像加速（见「国内环境注意事项」）。
- **Skill 部署 / 构建失败，提示未找到 node**：skill-forge bridge 依赖 Node.js；确认 `node` 在 PATH 中。Docker 镜像已内置 Node 20。
- **项目动态不实时**：确认后端已运行、页面顶部显示「实时同步中」；前端已内置 WebSocket 自动重连与轮询兜底。WS 为进程内内存态，后端**必须单进程**（`--workers 1`）。
- **桌面壳启动白屏 / 接口 401**：确认 cloud 模式后端已启动，且 `ALLOWED_ORIGINS` 显式包含 `"null"`（Electron `file://` Origin）及实际 Web 域名；不要使用 `ALLOW_ORIGIN_REGEX=.*`。
- **桌面壳提示本地代理不可用**：确认 `local-agent/dist/index.js` 已构建（`build-desktop.ps1` 会自动构建）。主进程会自动拉起代理进程；崩溃后自动重启并漂移端口。
- **授权后终端仍提示找不到 `vibebara`**：授权只写入凭据；安装包会注册 CLI PATH，但已打开的终端不会自动刷新。关闭并重新打开终端后运行 `Get-Command vibebara`。源码开发态请先按上文构建并执行 `npm link`。

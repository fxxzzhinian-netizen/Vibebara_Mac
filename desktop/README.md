# Vibebara 桌面壳（Electron / 方案 B M5-a）

桌面客户端外壳：主进程拉起并守护本地代理 `local-agent`、生成并注入配对令牌、注入
`window.__VIBEBARA_RUNTIME__` 运行时配置、用 `safeStorage` 安全存储登录 token、在本机
重做一键启动 launcher。渲染层复用 `../frontend/dist` 构建产物。

> 设计与决策见 `docs/archive/desktop-migration/M5-实施计划.md`、落地与验证见
> `docs/archive/desktop-migration/M5-a-桌面壳骨架实施记录.md`。

## 目录结构

```
desktop/
├── package.json            # Electron 工程 + dev/build/start/smoke 脚本
├── tsconfig.json           # TS → dist-electron（CommonJS）
├── electron-builder.yml    # Windows NSIS 打包（内置 local-agent/frontend/CLI）
├── build/
│   └── installer.nsh       # 安装/升级/卸载时维护用户级 CLI PATH
├── scripts/
│   ├── smoke-agent.cjs      # 无 GUI 验证本地代理拉起/令牌/重启/清理
│   ├── publish-update-cos.ps1 # 按安全顺序上传签名安装包和更新元数据
│   └── update-cli-path.ps1  # 幂等添加/删除 resources/cli PATH
└── src/
    ├── shared/types.ts      # 主进程↔预加载 共享类型 + IPC 通道常量
    ├── main/
    │   ├── index.ts          # 主进程入口：启动顺序编排、窗口、退出清理
    │   ├── localAgentManager.ts  # 子进程管理（端口/令牌/健康/重启/清理，仅 Node 内置）
    │   ├── portFinder.ts     # 探测空闲端口
    │   ├── pairing.ts        # 生成高熵配对令牌（与 security.py 兼容）
    │   ├── runtimeConfig.ts  # 组装 window.__VIBEBARA_RUNTIME__ 负载
    │   ├── userConfig.ts     # 云端地址：内置默认 + 配置文件/env 覆盖
    │   ├── tokenStore.ts     # safeStorage 加密持久化登录 token
    │   ├── deviceId.ts       # device_id 预留（本机持久临时 uuid 占位）
    │   ├── launcher.ts       # cursor/codex-cli/codex-app 启动（重做 launcher.py）
    │   └── ipc.ts            # 注册 IPC 处理器
    └── preload/index.ts      # contextBridge 注入 __VIBEBARA_RUNTIME__ / __VIBEBARA_DESKTOP__
```

## 前置

- Node ≥ 22.12（桌面发布机需要生成 Node SEA CLI；安装后的用户机不需要 Node）。
- 先构建共享内核、CLI 与本地代理：`../local-core` → `../cli` → `../local-agent`。
- 前端产物（prod 加载）：`cd ../frontend && npm install && npm run build`（生成 `frontend/dist`）。

## 开发 / 运行

```powershell
cd desktop
npm install
npm run build      # 编译 TS → dist-electron
npm start          # 启动桌面壳（默认加载 ../frontend/dist/index.html）
# 或指向 Vite dev server（前端 npm run dev 后）：
#   $env:VIBEBARA_DEV_SERVER_URL = "http://localhost:5173"; npm start
```

`npm run dev` = 编译 + 启动。

## 验证（无 GUI）

```powershell
npm run build
npm run smoke:agent   # 验证本地代理拉起/配对令牌/崩溃重启/退出清理
```

## 云端地址覆盖

默认指向本机 cloud demo（`http://127.0.0.1:8000/api/v1`、`ws://127.0.0.1:8000`）。覆盖方式：

- 配置文件：`<userData>/vibebara-desktop.config.json`（`cloudApiBase` / `cloudWsBase` / `writableRoots`）。
- 环境变量（联调优先）：`VIBEBARA_CLOUD_API_BASE` / `VIBEBARA_CLOUD_WS_BASE` / `VIBEBARA_WRITABLE_ROOTS`（`;` 分隔）。

`<userData>` 在 Windows 为 `%APPDATA%/@vibebara/desktop`（以 Electron app name 为准）。

## 打包与内置 CLI

根目录 `build-desktop.ps1 -Pack/-UnsignedDist/-Dist` 会按顺序构建
`local-core → CLI SEA → local-agent → frontend → desktop`。安装包将
`cli/release/vibebara.exe` 放到 `resources/cli`，NSIS 为当前用户注册 PATH；
升级保持该 PATH，真实卸载时删除。Windows 只会向新启动的终端传播 PATH，
因此安装或升级后需重新打开终端。

`-UnsignedDist` 默认使用基础配置生成未签名 NSIS 内测安装包；加上 `-Publish` 后改用
`electron-builder.unsigned-release.yml` 生成自动更新元数据并发布。`-Dist` 使用
`electron-builder.release.yml`，要求代码签名证书和 HTTPS 更新源。CLI 授权配置
`%USERPROFILE%\.vibebara\config.json` 属于用户数据，卸载时保留。

## 自动更新与 COS 源站发布

带更新元数据的安装包使用 `electron-updater`：启动 8 秒后后台检查并自动下载；下载完成后在应用内提示
“立即重启安装 / 稍后”。选择稍后不会打断当前工作，正常退出应用时也会自动安装已下载版本。
开发态和未配置 `publish` 的安装包不会形成可用的在线更新链路。未签名自动更新属于过渡方案：
Windows 无法验证发布者，首次安装和后续升级都可能触发 SmartScreen；取得证书后应切回 `-Dist`。

目前直接使用腾讯云 COS 源站 HTTPS 地址，不依赖 CDN。建议为桌面更新创建独立桶；至少应确保
`desktop/windows/` 下的安装包、blockmap 和 `latest.yml` 可匿名读取，不要修改 Skill 私有对象
的权限。发布机需安装 `coscli` 并设置：

```powershell
$env:COS_BUCKET = "vibebara-exe-1327732770"
$env:COS_REGION = "ap-chengdu"
$env:COS_SECRET_ID = "发布专用SecretId"
$env:COS_SECRET_KEY = "发布专用SecretKey"
$env:VIBEBARA_COS_UPDATE_PREFIX = "desktop/windows"
$env:VIBEBARA_UPDATE_URL = "https://vibebara-exe-1327732770.cos.ap-chengdu.myqcloud.com/desktop/windows/"

# 过渡期：构建并发布未签名自动更新
.\build-desktop.ps1 -UnsignedDist -Publish

# 取得证书后：改用签名发布
# $env:WIN_CSC_LINK = "C:\secure\vibebara-signing.pfx"
# $env:WIN_CSC_KEY_PASSWORD = "证书密码"
# .\build-desktop.ps1 -Dist -Publish
```

凭据只从发布机环境变量读取，不写入仓库。脚本会校验安装包签名状态；未签名发布必须由
`-UnsignedDist -Publish` 显式开启。随后先上传带版本号的
`VBB-Setup-*.exe` 和 `.blockmap`，最后上传 `latest.yml`，随后用 HTTPS HEAD 请求确认三个对象
均可匿名读取。只验证发布文件而不上传时可运行：

```powershell
.\desktop\scripts\publish-update-cos.ps1 -AllowUnsigned -DryRun
```

后续接入 CDN 时，只需将 `VIBEBARA_UPDATE_URL` 改为对应 CDN HTTPS 目录后重新发布新版本，
客户端更新逻辑无需调整。已安装的旧版本仍会继续访问其安装包内记录的原 COS 地址。

# Vibebara Desktop - 一键构建 / 启动 / 打包（Windows PowerShell）
#
# 默认行为（无参数）：构建三件套 → 拉起 cloud 模式后端 → 启动桌面壳。
# 即：双击或执行本脚本就能跑起完整桌面客户端。
#
# 用法：
#   .\build-desktop.ps1              # 构建 + 后端 + 桌面壳（默认，最常用）
#   .\build-desktop.ps1 -Quick       # 跳过构建，直接启动后端 + 桌面壳（已构建过时用）
#   .\build-desktop.ps1 -BuildOnly   # 仅构建，不启动
#   .\build-desktop.ps1 -NoBe        # 构建 + 桌面壳，不启动后端（后端已在跑）
#   .\build-desktop.ps1 -Dev         # 开发模式：后端 + 前端 dev server + 桌面壳(热更新)
#   .\build-desktop.ps1 -Pack        # 构建 + electron-builder 解包目录
#   .\build-desktop.ps1 -Dist        # 构建 + electron-builder NSIS 安装包
#
# 提示：若 PowerShell 执行策略受限，请用：
#   powershell -ExecutionPolicy Bypass -File .\build-desktop.ps1
#
[CmdletBinding()]
param(
    [switch]$Quick,         # 跳过构建，直接启动（已构建过时用）
    [switch]$BuildOnly,     # 仅构建，不启动任何服务
    [switch]$NoBe,          # 不启动后端（后端已在另一个窗口跑着）
    [switch]$Dev,           # 开发模式：前端走 Vite dev server 热更新
    [switch]$Pack,          # electron-builder --win --dir
    [switch]$Dist,          # electron-builder --win (NSIS 安装包)
    [switch]$ForceInstall   # 强制重新 npm install / pip install
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ROOT = $PSScriptRoot
$backendDir   = Join-Path $ROOT "backend"
$frontendDir  = Join-Path $ROOT "frontend"
$localCoreDir = Join-Path $ROOT "local-core"
$agentDir     = Join-Path $ROOT "local-agent"
$desktopDir   = Join-Path $ROOT "desktop"
$venvPython   = Join-Path $backendDir ".venv\Scripts\python.exe"

# 当前线上尚未部署 TLS，-NoBe 暂时回退到现有 HTTP/WS 公网地址。
$DEFAULT_CLOUD_API_BASE = "http://43.136.128.162:8000/api/v1"
$DEFAULT_CLOUD_WS_BASE  = "ws://43.136.128.162:8000"

# ── 工具函数 ────────────────────────────────────────────────

function Write-Section($text) {
    Write-Host ""
    Write-Host "========================================================" -ForegroundColor Cyan
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host "========================================================" -ForegroundColor Cyan
}

function Invoke-In($dir, [scriptblock]$action, $label) {
    Push-Location $dir
    try {
        & $action
        if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "$label 失败 (exit $LASTEXITCODE)" }
    } finally { Pop-Location }
}

function Build-Node($dir, $name) {
    Write-Host "  [$name] " -NoNewline -ForegroundColor White
    $needInstall = $ForceInstall -or (-not (Test-Path (Join-Path $dir "node_modules")))
    if ($needInstall) {
        Write-Host "install → " -NoNewline -ForegroundColor Yellow
        Invoke-In $dir { npm install --loglevel=error } "$name npm install"
    }
    Write-Host "build → " -NoNewline -ForegroundColor Yellow
    Invoke-In $dir { npm run build } "$name build"
    Write-Host "OK" -ForegroundColor Green
}

function Set-DesktopBuildVersion {
    # 打包前在终端「手动输入」本次打包的版本号，写入 desktop/package.json。
    # 版本号有两个作用：
    #   1) 决定安装包文件名 Vibebara Setup <version>.exe（不同版本不会互相覆盖、易区分）；
    #   2) 决定升级识别：appId 不变 → GUID 不变，只要新版本号比已装的高，安装时会
    #      自动卸掉旧版并装到同一目录，用户无需先手动卸载（详见 electron-builder.yml）。
    # 必须显式按 UTF-8 读写：PS 5.1 的 Get-Content -Raw 会把无 BOM 的 UTF-8 当 GBK 解码，
    # 导致 description 里的中文变乱码、写回后掺入非法控制字符，npm 解析 package.json 直接报错。
    $pkgPath = Join-Path $desktopDir "package.json"
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $content = [System.IO.File]::ReadAllText($pkgPath, $utf8)

    $cur = if ($content -match '"version"\s*:\s*"([^"]*)"') { $Matches[1] } else { "0.0.0" }
    # 默认建议：把当前版本的「修订号」+1（合法时），直接回车即可采用。
    $suggest = $cur
    if ($cur -match '^(\d+)\.(\d+)\.(\d+)$') {
        $suggest = "{0}.{1}.{2}" -f $Matches[1], $Matches[2], ([int]$Matches[3] + 1)
    }

    $ver = $null
    while (-not $ver) {
        $verInput = Read-Host "  请输入本次打包版本号 (当前 $cur，直接回车用 $suggest)"
        if ([string]::IsNullOrWhiteSpace($verInput)) { $verInput = $suggest }
        $verInput = $verInput.Trim()
        if ($verInput -match '^(\d+)\.(\d+)\.(\d+)$' -and
            [int]$Matches[1] -le 65535 -and [int]$Matches[2] -le 65535 -and [int]$Matches[3] -le 65535) {
            $ver = $verInput
        }
        else {
            Write-Host "  [无效] 需为 主.次.修订 三段数字，每段 0-65535（如 1.2.3）。请重输。" -ForegroundColor Yellow
        }
    }

    $content = [regex]::Replace($content, '("version"\s*:\s*")[^"]*(")', "`${1}$ver`${2}")
    [System.IO.File]::WriteAllText($pkgPath, $content, $utf8)
    Write-Host "  [打包] 版本号 → $ver  (desktop/package.json，安装包名将含此版本)" -ForegroundColor Cyan
    return $ver
}

function Ensure-Backend-Venv {
    if (-not (Test-Path $venvPython)) {
        Write-Host "  [后端] 创建虚拟环境 + 安装依赖..." -ForegroundColor Yellow
        $py = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "python3" }
        & $py -m venv (Join-Path $backendDir ".venv")
        & $venvPython -m pip install -r (Join-Path $backendDir "requirements.txt") -q 2>$null
        Write-Host "  [后端] OK" -ForegroundColor Green
    }
}

function Start-Backend {
    Ensure-Backend-Venv
    $script = Join-Path $env:TEMP "vibebara-desktop-backend.ps1"
    @"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
`$Host.UI.RawUI.WindowTitle = 'Vibebara Backend (cloud :8000)'
Set-Location '$backendDir'
`$env:DEPLOYMENT_MODE = 'cloud'
`$env:ALLOW_ORIGIN_REGEX = '^null$'
`$env:SEED_USERS_ENABLED = 'false'
`$env:INVITE_CODE_REQUIRED = 'false'
`$env:ADMIN_USERNAMES = '[]'
`$env:MARKET_SEED_REVIEWERS = '[]'
Write-Host 'Vibebara Backend (cloud) -> http://127.0.0.1:8000' -ForegroundColor Green
& '$venvPython' -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Write-Host 'Backend stopped. Press any key...' -ForegroundColor Yellow
`$null = `$Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
"@ | Out-File -FilePath $script -Encoding UTF8
    Start-Process powershell -ArgumentList "-NoExit", "-File", $script
    Write-Host "  [后端] 已在新窗口启动 (cloud, :8000)" -ForegroundColor Green
    Start-Sleep -Seconds 2
}

function Start-Frontend-Dev {
    $script = Join-Path $env:TEMP "vibebara-desktop-frontend-dev.ps1"
    @"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
`$Host.UI.RawUI.WindowTitle = 'Vibebara Frontend (Vite :5173)'
Set-Location '$frontendDir'
Write-Host 'Vibebara Frontend Dev -> http://localhost:5173' -ForegroundColor Green
npm run dev
"@ | Out-File -FilePath $script -Encoding UTF8
    Start-Process powershell -ArgumentList "-NoExit", "-File", $script
    Write-Host "  [前端] Vite dev server 已在新窗口启动 (:5173)" -ForegroundColor Green
    Start-Sleep -Seconds 3
}

function Start-Desktop([switch]$devMode) {
    if ($devMode) {
        $env:VIBEBARA_DEV_SERVER_URL = "http://localhost:5173"
        Write-Host "  [桌面壳] 开发模式 → 加载 Vite dev server (热更新)" -ForegroundColor Magenta
    }
    Invoke-In $desktopDir { npm start } "electron start"
    if ($devMode) { Remove-Item Env:\VIBEBARA_DEV_SERVER_URL -ErrorAction SilentlyContinue }
}

# ── 环境检查 ────────────────────────────────────────────────

Write-Section "Vibebara 桌面客户端"
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "  [ERROR] 未找到 Node.js，请安装 Node 20+" -ForegroundColor Red; exit 1
}
Write-Host "  Node $(node --version) · npm $(npm --version)" -ForegroundColor DarkGray

# ── 构建 ────────────────────────────────────────────────────

$skipBuild = $Quick
if (-not $skipBuild) {
    Write-Section "构建桌面端四件套"
    # local-agent 通过 file:../local-core 复用共享文件/hash 内核；必须先产出
    # local-core/dist，干净机器上 local-agent 的 npm install/tsc 才能解析类型与运行时入口。
    Build-Node $localCoreDir "local-core"
    Build-Node $agentDir   "local-agent"
    if (-not $Dev) {
        Build-Node $frontendDir "frontend"
    } else {
        Write-Host "  [frontend] 开发模式，跳过 build（走 Vite dev server）" -ForegroundColor DarkGray
    }
    Build-Node $desktopDir "desktop"
}
else {
    # Quick 模式：检查产物是否存在
    $missing = @()
    if (-not (Test-Path (Join-Path $localCoreDir "dist\index.js")))      { $missing += "local-core/dist" }
    if (-not (Test-Path (Join-Path $agentDir "dist\index.js")))          { $missing += "local-agent/dist" }
    if (-not $Dev -and -not (Test-Path (Join-Path $frontendDir "dist\index.html"))) { $missing += "frontend/dist" }
    if (-not (Test-Path (Join-Path $desktopDir "dist-electron\main\index.js")))     { $missing += "desktop/dist-electron" }
    if ($missing.Count -gt 0) {
        Write-Host "  [WARN] -Quick 但以下产物缺失，将自动构建: $($missing -join ', ')" -ForegroundColor Yellow
        if ($missing -contains "local-core/dist")     { Build-Node $localCoreDir "local-core" }
        if ($missing -contains "local-agent/dist")    { Build-Node $agentDir   "local-agent" }
        if ($missing -contains "frontend/dist")       { Build-Node $frontendDir "frontend" }
        if ($missing -contains "desktop/dist-electron"){ Build-Node $desktopDir "desktop" }
    }
    else {
        Write-Host "  [Quick] 产物已存在，跳过构建" -ForegroundColor DarkGray
    }
}

# ── 打包 ────────────────────────────────────────────────────

# electron-builder 工具链（nsis 等）默认从 GitHub 拉，国内常被墙/VPN fake-ip 拦截。
# 未显式设置时默认走 npmmirror 镜像；需走官方源时先 $env:ELECTRON_BUILDER_BINARIES_MIRROR=""。
if (($Dist -or $Pack) -and (-not (Test-Path Env:\ELECTRON_BUILDER_BINARIES_MIRROR))) {
    $env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"
    Write-Host "  [打包] 工具链镜像 → npmmirror（可设 ELECTRON_BUILDER_BINARIES_MIRROR 覆盖）" -ForegroundColor DarkGray
}

if ($Dist) {
    Write-Section "打包 NSIS 安装包"
    Set-DesktopBuildVersion | Out-Null
    Write-Host "  首次会下载 electron + nsis 工具链，请耐心等待" -ForegroundColor Gray
    Invoke-In $desktopDir { npm run dist:win } "electron-builder dist"
    Write-Host "  [OK] 输出: $(Join-Path $desktopDir 'release')" -ForegroundColor Green
    Write-Host ""; exit 0
}
if ($Pack) {
    Write-Section "打包解压即用目录"
    Set-DesktopBuildVersion | Out-Null
    Write-Host "  首次会下载 electron 工具链，请耐心等待" -ForegroundColor Gray
    Invoke-In $desktopDir { npm run pack:win } "electron-builder pack"
    Write-Host "  [OK] 输出: $(Join-Path $desktopDir 'release')" -ForegroundColor Green
    Write-Host ""; exit 0
}

# ── 仅构建 ──────────────────────────────────────────────────

if ($BuildOnly) {
    Write-Section "构建完成"
    Write-Host "  local-core/dist, local-agent/dist, frontend/dist, desktop/dist-electron" -ForegroundColor Green
    Write-Host ""; exit 0
}

# ── 启动 ────────────────────────────────────────────────────

Write-Section "启动服务"

if (-not $NoBe) {
    Start-Backend
}
else {
    # -NoBe：不在本机起后端，未显式配置时连接当前测试服务器。
    if (-not $env:VIBEBARA_CLOUD_API_BASE) { $env:VIBEBARA_CLOUD_API_BASE = $DEFAULT_CLOUD_API_BASE }
    if (-not $env:VIBEBARA_CLOUD_WS_BASE)  { $env:VIBEBARA_CLOUD_WS_BASE = $DEFAULT_CLOUD_WS_BASE }
    Write-Host "  [后端] -NoBe: 不起本地后端，直连云端" -ForegroundColor Yellow
    if ($env:VIBEBARA_CLOUD_API_BASE.StartsWith("http://")) {
        Write-Host "  [安全警告] 当前云端使用明文 HTTP/WS，请勿用于正式外部发布" -ForegroundColor Yellow
    }
    Write-Host "  [云端] API → $($env:VIBEBARA_CLOUD_API_BASE)" -ForegroundColor Cyan
    Write-Host "  [云端] WS  → $($env:VIBEBARA_CLOUD_WS_BASE)"  -ForegroundColor Cyan
}

if ($Dev) {
    Start-Frontend-Dev
    Start-Desktop -devMode
}
else {
    Start-Desktop
}

Write-Host ""

# Vibebara Desktop - build, launch, and package (Windows PowerShell 5.1+)
#
# Default: build all components, start the cloud-mode backend, then launch desktop.
#
# Usage:
#   .\build-desktop.ps1              # Build and launch backend + desktop
#   .\build-desktop.ps1 -Quick       # Skip existing builds and launch
#   .\build-desktop.ps1 -BuildOnly   # Build only
#   .\build-desktop.ps1 -NoBe        # Build and launch desktop without backend
#   .\build-desktop.ps1 -Dev         # Backend + Vite dev server + desktop
#   .\build-desktop.ps1 -Pack        # Build electron-builder unpacked directory
#   .\build-desktop.ps1 -UnsignedDist # Build unsigned NSIS installer for testing
#   .\build-desktop.ps1 -Dist        # Build signed release NSIS installer
#
# If script execution is restricted:
#   powershell -ExecutionPolicy Bypass -File .\build-desktop.ps1
#
[CmdletBinding()]
param(
    [switch]$Quick,         # Skip builds when artifacts already exist
    [switch]$BuildOnly,     # Build without starting services
    [switch]$NoBe,          # Do not start the backend
    [switch]$Dev,           # Use the Vite dev server
    [switch]$Pack,          # electron-builder --win --dir
    [switch]$UnsignedDist,  # Unsigned NSIS installer for internal testing
    [switch]$Dist,          # Signed release NSIS installer
    [switch]$ForceInstall   # Force npm/pip dependency installation
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$packageModeCount = 0
foreach ($enabled in @($Pack, $UnsignedDist, $Dist)) {
    if ($enabled) { $packageModeCount++ }
}
if ($packageModeCount -gt 1) {
    throw "Choose only one packaging mode: -Pack, -UnsignedDist, or -Dist."
}

$ROOT = $PSScriptRoot
$backendDir   = Join-Path $ROOT "backend"
$frontendDir  = Join-Path $ROOT "frontend"
$localCoreDir = Join-Path $ROOT "local-core"
$cliDir       = Join-Path $ROOT "cli"
$agentDir     = Join-Path $ROOT "local-agent"
$desktopDir   = Join-Path $ROOT "desktop"
$venvPython   = Join-Path $backendDir ".venv\Scripts\python.exe"

# The current test endpoint has not migrated to TLS yet.
$DEFAULT_CLOUD_API_BASE = "http://162.14.106.190:8000/api/v1"
$DEFAULT_CLOUD_WS_BASE  = "ws://162.14.106.190:8000"

# Helpers

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
        if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "$label failed (exit $LASTEXITCODE)" }
    } finally { Pop-Location }
}

function Build-Node($dir, $name) {
    Write-Host "  [$name] " -NoNewline -ForegroundColor White
    $needInstall = $ForceInstall -or (-not (Test-Path (Join-Path $dir "node_modules")))
    if ($needInstall) {
        Write-Host "install -> " -NoNewline -ForegroundColor Yellow
        Invoke-In $dir { npm install --loglevel=error } "$name npm install"
    }
    Write-Host "build -> " -NoNewline -ForegroundColor Yellow
    Invoke-In $dir { npm run build } "$name build"
    Write-Host "OK" -ForegroundColor Green
}

function Publish-CliArtifact([string]$source = (Join-Path $cliDir "release\vibebara.exe")) {
    if (-not (Test-Path $source)) {
        throw "CLI release artifact not found: $source"
    }
    $releaseDir = Join-Path $desktopDir "release"
    $target = Join-Path $releaseDir "vibebara.exe"
    New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
    Copy-Item -Force $source $target
    Write-Host "  [cli-output] $target" -ForegroundColor DarkGray
}

function Build-Cli {
    Build-Node $cliDir "cli"
    Write-Host "  [cli-sea] " -NoNewline -ForegroundColor White
    Write-Host "bundle + SEA -> " -NoNewline -ForegroundColor Yellow
    Invoke-In $cliDir { npm run sea:win } "cli SEA build"
    Write-Host "OK" -ForegroundColor Green
    Publish-CliArtifact
}

function Set-DesktopBuildVersion {
    # Prompt for the package version before packaging. The version controls both
    # the installer filename and electron-builder upgrade detection.
    # Read and write JSON explicitly as UTF-8 because Windows PowerShell 5.1
    # treats UTF-8 without a BOM as the system code page.
    $pkgPath = Join-Path $desktopDir "package.json"
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $content = [System.IO.File]::ReadAllText($pkgPath, $utf8)

    $cur = if ($content -match '"version"\s*:\s*"([^"]*)"') { $Matches[1] } else { "0.0.0" }
    # Suggest incrementing the patch version.
    $suggest = $cur
    if ($cur -match '^(\d+)\.(\d+)\.(\d+)$') {
        $suggest = "{0}.{1}.{2}" -f $Matches[1], $Matches[2], ([int]$Matches[3] + 1)
    }

    $ver = $null
    while (-not $ver) {
        $verInput = Read-Host "  Package version (current $cur, Enter for $suggest)"
        if ([string]::IsNullOrWhiteSpace($verInput)) { $verInput = $suggest }
        $verInput = $verInput.Trim()
        if ($verInput -match '^(\d+)\.(\d+)\.(\d+)$' -and
            [int]$Matches[1] -le 65535 -and [int]$Matches[2] -le 65535 -and [int]$Matches[3] -le 65535) {
            $ver = $verInput
        }
        else {
            Write-Host "  [invalid] Use major.minor.patch with values from 0 to 65535 (for example 1.2.3)." -ForegroundColor Yellow
        }
    }

    $content = [regex]::Replace($content, '("version"\s*:\s*")[^"]*(")', "`${1}$ver`${2}")
    [System.IO.File]::WriteAllText($pkgPath, $content, $utf8)

    $lockPath = Join-Path $desktopDir "package-lock.json"
    if (Test-Path $lockPath) {
        $lockContent = [System.IO.File]::ReadAllText($lockPath, $utf8)
        $versionPattern = New-Object regex('(?m)^(\s*"version"\s*:\s*")[^"]*(")')
        $lockContent = $versionPattern.Replace($lockContent, "`${1}$ver`${2}", 2)
        [System.IO.File]::WriteAllText($lockPath, $lockContent, $utf8)
    }

    Write-Host "  [package] version -> $ver (desktop package and lock files)" -ForegroundColor Cyan
    return $ver
}

function Ensure-Backend-Venv {
    if (-not (Test-Path $venvPython)) {
        Write-Host "  [backend] Creating virtual environment and installing dependencies..." -ForegroundColor Yellow
        $py = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "python3" }
        & $py -m venv (Join-Path $backendDir ".venv")
        & $venvPython -m pip install -r (Join-Path $backendDir "requirements.txt") -q 2>$null
        Write-Host "  [backend] OK" -ForegroundColor Green
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
    Write-Host "  [backend] Started in a new window (cloud, :8000)" -ForegroundColor Green
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
    Write-Host "  [frontend] Vite dev server started in a new window (:5173)" -ForegroundColor Green
    Start-Sleep -Seconds 3
}

function Start-Desktop([switch]$devMode) {
    if ($devMode) {
        $env:VIBEBARA_DEV_SERVER_URL = "http://localhost:5173"
        Write-Host "  [desktop] Dev mode -> loading Vite dev server" -ForegroundColor Magenta
    }
    Invoke-In $desktopDir { npm start } "electron start"
    if ($devMode) { Remove-Item Env:\VIBEBARA_DEV_SERVER_URL -ErrorAction SilentlyContinue }
}

# Environment checks

Write-Section "Vibebara Desktop"
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "  [ERROR] Node.js not found. Install Node 22.12 or newer." -ForegroundColor Red; exit 1
}
$nodeVersionText = (node --version).TrimStart("v")
if ([version]$nodeVersionText -lt [version]"22.12.0") {
    Write-Host "  [ERROR] CLI build requires Node 22.12+. Current: $nodeVersionText" -ForegroundColor Red; exit 1
}
Write-Host "  Node v$nodeVersionText | npm $(npm --version)" -ForegroundColor DarkGray

# Build

$skipBuild = $Quick
if (-not $skipBuild) {
    Write-Section "Build desktop components"
    # local-agent and CLI share local-core through file:../local-core, so build
    # local-core first to expose its type declarations and runtime entry.
    Build-Node $localCoreDir "local-core"
    Build-Cli
    Build-Node $agentDir   "local-agent"
    if (-not $Dev) {
        Build-Node $frontendDir "frontend"
    } else {
        Write-Host "  [frontend] Dev mode: skipping build and using Vite" -ForegroundColor DarkGray
    }
    Build-Node $desktopDir "desktop"
}
else {
    # Quick mode still builds missing artifacts.
    $missing = @()
    if (-not (Test-Path (Join-Path $localCoreDir "dist\index.js")))      { $missing += "local-core/dist" }
    if (-not (Test-Path (Join-Path $cliDir "release\vibebara.exe")))     { $missing += "cli/release/vibebara.exe" }
    if (-not (Test-Path (Join-Path $agentDir "dist\index.js")))          { $missing += "local-agent/dist" }
    if (-not $Dev -and -not (Test-Path (Join-Path $frontendDir "dist\index.html"))) { $missing += "frontend/dist" }
    if (-not (Test-Path (Join-Path $desktopDir "dist-electron\main\index.js")))     { $missing += "desktop/dist-electron" }
    if ($missing.Count -gt 0) {
        Write-Host "  [WARN] -Quick found missing artifacts; building: $($missing -join ', ')" -ForegroundColor Yellow
        if ($missing -contains "local-core/dist")     { Build-Node $localCoreDir "local-core" }
        if ($missing -contains "cli/release/vibebara.exe") { Build-Cli }
        if ($missing -contains "local-agent/dist")    { Build-Node $agentDir   "local-agent" }
        if ($missing -contains "frontend/dist")       { Build-Node $frontendDir "frontend" }
        if ($missing -contains "desktop/dist-electron"){ Build-Node $desktopDir "desktop" }
    }
    else {
        Write-Host "  [Quick] All artifacts exist; skipping build" -ForegroundColor DarkGray
    }
}

# Package

# Use the npmmirror electron-builder binary mirror unless explicitly overridden.
if (($Dist -or $UnsignedDist -or $Pack) -and (-not (Test-Path Env:\ELECTRON_BUILDER_BINARIES_MIRROR))) {
    $env:ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"
    Write-Host "  [package] electron-builder mirror -> npmmirror" -ForegroundColor DarkGray
}

if ($Dist) {
    Write-Section "Package signed release NSIS installer"
    Invoke-In $desktopDir { npm run release:check } "release environment check"
    Set-DesktopBuildVersion | Out-Null
    Write-Host "  Electron and NSIS binaries may be downloaded on the first run" -ForegroundColor Gray
    Invoke-In $desktopDir { npm run dist:win } "electron-builder dist"
    Invoke-In $desktopDir { npm run smoke:cli -- --require-signature } "desktop CLI signed smoke"
    Publish-CliArtifact (Join-Path $desktopDir "release\win-unpacked\resources\cli\vibebara.exe")
    Write-Host "  [OK] Output: $(Join-Path $desktopDir 'release')" -ForegroundColor Green
    Write-Host ""; exit 0
}
if ($UnsignedDist) {
    Write-Section "Package unsigned NSIS installer for internal testing"
    Set-DesktopBuildVersion | Out-Null
    Write-Host "  Electron and NSIS binaries may be downloaded on the first run" -ForegroundColor Gray
    $previousAutoDiscovery = $env:CSC_IDENTITY_AUTO_DISCOVERY
    try {
        $env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
        Invoke-In $desktopDir { npm run dist:win:unsigned } "electron-builder unsigned dist"
    }
    finally {
        if ($null -eq $previousAutoDiscovery) {
            Remove-Item Env:\CSC_IDENTITY_AUTO_DISCOVERY -ErrorAction SilentlyContinue
        }
        else {
            $env:CSC_IDENTITY_AUTO_DISCOVERY = $previousAutoDiscovery
        }
    }
    Invoke-In $desktopDir { npm run smoke:cli } "desktop CLI smoke"
    Publish-CliArtifact (Join-Path $desktopDir "release\win-unpacked\resources\cli\vibebara.exe")
    Write-Host "  [OK] Unsigned output: $(Join-Path $desktopDir 'release')" -ForegroundColor Green
    Write-Host ""; exit 0
}
if ($Pack) {
    Write-Section "Package unpacked directory"
    Set-DesktopBuildVersion | Out-Null
    Write-Host "  Electron binaries may be downloaded on the first run" -ForegroundColor Gray
    Invoke-In $desktopDir { npm run pack:win } "electron-builder pack"
    Invoke-In $desktopDir { npm run smoke:cli } "desktop CLI smoke"
    Publish-CliArtifact (Join-Path $desktopDir "release\win-unpacked\resources\cli\vibebara.exe")
    Write-Host "  [OK] Output: $(Join-Path $desktopDir 'release')" -ForegroundColor Green
    Write-Host ""; exit 0
}

# Build only

if ($BuildOnly) {
    Write-Section "Build complete"
    Write-Host "  local-core/dist, cli/release/vibebara.exe, local-agent/dist, frontend/dist, desktop/dist-electron" -ForegroundColor Green
    Write-Host ""; exit 0
}

# Launch

Write-Section "Start services"

if (-not $NoBe) {
    Start-Backend
}
else {
    # Without a local backend, use the current remote test server by default.
    if (-not $env:VIBEBARA_CLOUD_API_BASE) { $env:VIBEBARA_CLOUD_API_BASE = $DEFAULT_CLOUD_API_BASE }
    if (-not $env:VIBEBARA_CLOUD_WS_BASE)  { $env:VIBEBARA_CLOUD_WS_BASE = $DEFAULT_CLOUD_WS_BASE }
    Write-Host "  [backend] -NoBe: using the remote endpoint" -ForegroundColor Yellow
    if ($env:VIBEBARA_CLOUD_API_BASE.StartsWith("http://")) {
        Write-Host "  [security] Remote endpoint uses plaintext HTTP/WS; do not use for production" -ForegroundColor Yellow
    }
    Write-Host "  [cloud] API -> $($env:VIBEBARA_CLOUD_API_BASE)" -ForegroundColor Cyan
    Write-Host "  [cloud] WS  -> $($env:VIBEBARA_CLOUD_WS_BASE)"  -ForegroundColor Cyan
}

if ($Dev) {
    Start-Frontend-Dev
    Start-Desktop -devMode
}
else {
    Start-Desktop
}

Write-Host ""

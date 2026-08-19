# Publish a GitHub-built macOS arm64 update artifact from a domestic Windows machine.
# Versioned artifacts are uploaded first; latest-mac.yml is uploaded last.
[CmdletBinding()]
param(
    [string]$ReleaseDir = (Get-Location).Path,
    [string]$Bucket = $env:COS_BUCKET,
    [string]$Region = $env:COS_REGION,
    [string]$Prefix = $(if ($env:VIBEBARA_COS_UPDATE_PREFIX) { $env:VIBEBARA_COS_UPDATE_PREFIX } else { "desktop/macos" }),
    [string]$UpdateUrl = $env:VIBEBARA_UPDATE_URL,
    [string]$CosCli = "coscli",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol =
    [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$script:CosConfigPath = $null

function Require-Value([string]$Value, [string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "Missing required environment variable or parameter: $Name"
    }
}

function ConvertTo-YamlString([string]$Value) {
    return '"' + $Value.Replace('\', '\\').Replace('"', '\"') + '"'
}

function New-TemporaryCosConfig {
    $configPath = Join-Path ([System.IO.Path]::GetTempPath()) "vibebara-mac-cos-$([guid]::NewGuid().ToString('N')).yaml"
    $sessionToken = if ($env:COS_SESSION_TOKEN) { $env:COS_SESSION_TOKEN } else { "" }
    $yaml = @"
cos:
  base:
    secretid: $(ConvertTo-YamlString $env:COS_SECRET_ID)
    secretkey: $(ConvertTo-YamlString $env:COS_SECRET_KEY)
    sessiontoken: $(ConvertTo-YamlString $sessionToken)
    protocol: https
    disableencryption: "true"
  buckets:
    - name: $(ConvertTo-YamlString $Bucket)
      alias: vibebara-mac-update
      region: $(ConvertTo-YamlString $Region)
      endpoint: $(ConvertTo-YamlString "cos.$Region.myqcloud.com")
      ofs: false
"@
    [System.IO.File]::WriteAllText(
        $configPath,
        $yaml,
        (New-Object System.Text.UTF8Encoding($false))
    )
    return $configPath
}

function Get-FileSha512Base64([string]$Path) {
    $stream = [System.IO.File]::OpenRead($Path)
    $sha = [System.Security.Cryptography.SHA512]::Create()
    try {
        return [Convert]::ToBase64String($sha.ComputeHash($stream))
    }
    finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

function Invoke-CosUpload([string]$Source, [string]$ObjectKey) {
    $name = Split-Path $Source -Leaf
    $destination = "cos://$Bucket/$ObjectKey"
    $sizeMb = [math]::Round((Get-Item -LiteralPath $Source).Length / 1MB, 2)
    Write-Host "  [upload] $name ($sizeMb MB) -> $destination" -ForegroundColor Cyan
    if ($DryRun) { return }

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    & $CosCli cp $Source $destination `
        --acl public-read `
        --log-path (Join-Path $ReleaseDir "coscli.log") `
        -c $script:CosConfigPath
    $exitCode = $LASTEXITCODE
    $stopwatch.Stop()
    if ($exitCode -ne 0) {
        throw "COS upload failed for $name after $([math]::Round($stopwatch.Elapsed.TotalSeconds))s (exit $exitCode)"
    }
    Write-Host "  [upload] completed $name in $([math]::Round($stopwatch.Elapsed.TotalSeconds))s" -ForegroundColor Green
}

function Test-PublicObject([string]$BaseUrl, [string]$FileName) {
    $encodedName = [uri]::EscapeDataString($FileName).Replace("%2F", "/")
    $url = "$($BaseUrl.TrimEnd('/'))/$encodedName"
    try {
        $response = Invoke-WebRequest -Uri $url -Method Head -UseBasicParsing -TimeoutSec 30
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 400) {
            throw "HTTP $($response.StatusCode)"
        }
        Write-Host "  [public] $url" -ForegroundColor Green
    }
    catch {
        throw "Uploaded object is not anonymously readable: $url ($($_.Exception.Message))"
    }
}

function Test-RemoteLatest([string]$BaseUrl, [string]$LocalPath) {
    $url = "$($BaseUrl.TrimEnd('/'))/latest-mac.yml"
    $tempPath = Join-Path ([System.IO.Path]::GetTempPath()) "vibebara-latest-mac-$([guid]::NewGuid().ToString('N')).yml"
    try {
        Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 30 -OutFile $tempPath
        $localHash = (Get-FileHash -LiteralPath $LocalPath -Algorithm SHA256).Hash
        $remoteHash = (Get-FileHash -LiteralPath $tempPath -Algorithm SHA256).Hash
        if ($localHash -ne $remoteHash) {
            throw "remote latest-mac.yml content differs from the local release metadata"
        }
        Write-Host "  [metadata] remote latest-mac.yml matches local SHA-256" -ForegroundColor Green
    }
    finally {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
}

$ReleaseDir = [System.IO.Path]::GetFullPath($ReleaseDir)
if (-not (Test-Path -LiteralPath $ReleaseDir -PathType Container)) {
    throw "Release directory not found: $ReleaseDir"
}

$latestPath = Join-Path $ReleaseDir "latest-mac.yml"
if (-not (Test-Path -LiteralPath $latestPath -PathType Leaf)) {
    throw "Missing electron-updater metadata: $latestPath"
}

$latestText = [System.IO.File]::ReadAllText($latestPath)
$pathMatch = [regex]::Match($latestText, '(?m)^path:\s*(.+?)\s*$')
if (-not $pathMatch.Success) {
    throw "latest-mac.yml does not contain a top-level update path"
}
$zipName = $pathMatch.Groups[1].Value.Trim().Trim('"').Trim("'")
$zipMatch = [regex]::Match($zipName, '^VBB-mac-(\d+\.\d+\.\d+)-arm64\.zip$')
if (-not $zipMatch.Success) {
    throw "Unexpected arm64 update path in latest-mac.yml: $zipName"
}

$version = $zipMatch.Groups[1].Value
$dmgName = "VBB-mac-$version-arm64.dmg"
$zipPath = Join-Path $ReleaseDir $zipName
$dmgPath = Join-Path $ReleaseDir $dmgName
$zipBlockmapPath = "$zipPath.blockmap"
$dmgBlockmapPath = "$dmgPath.blockmap"
$versionedArtifacts = @(
    $dmgPath,
    $zipPath,
    $dmgBlockmapPath,
    $zipBlockmapPath
)
foreach ($required in $versionedArtifacts) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Missing release artifact: $required"
    }
}

$shaMatch = [regex]::Match($latestText, '(?m)^sha512:\s*(\S+)\s*$')
if (-not $shaMatch.Success) {
    throw "latest-mac.yml does not contain the expected ZIP sha512"
}
$actualSha512 = Get-FileSha512Base64 $zipPath
$expectedSha512 = $shaMatch.Groups[1].Value.Trim()
if ($actualSha512 -cne $expectedSha512) {
    throw "ZIP SHA-512 does not match latest-mac.yml"
}
Write-Host "  [metadata] ZIP SHA-512 matches latest-mac.yml" -ForegroundColor Green

Require-Value $Bucket "COS_BUCKET"
Require-Value $Region "COS_REGION"
$Prefix = $Prefix.Trim().Trim("/")
if (-not $Prefix) {
    throw "VIBEBARA_COS_UPDATE_PREFIX cannot be empty"
}
Require-Value $UpdateUrl "VIBEBARA_UPDATE_URL"
try {
    $parsedUpdateUrl = [uri]$UpdateUrl
    if ($parsedUpdateUrl.Scheme -ne "https") { throw "HTTPS required" }
}
catch {
    throw "VIBEBARA_UPDATE_URL must be a valid HTTPS URL"
}

if (-not $DryRun) {
    Require-Value $env:COS_SECRET_ID "COS_SECRET_ID"
    Require-Value $env:COS_SECRET_KEY "COS_SECRET_KEY"
    if (-not (Get-Command $CosCli -ErrorAction SilentlyContinue)) {
        throw "COSCLI was not found: $CosCli"
    }
}

if ($DryRun) {
    Write-Host "  [dry-run] macOS artifact validation completed; no files were uploaded." -ForegroundColor Yellow
    exit 0
}

$script:CosConfigPath = New-TemporaryCosConfig
try {
    $objectBase = "$Prefix/"
    foreach ($artifact in $versionedArtifacts) {
        $name = Split-Path $artifact -Leaf
        Invoke-CosUpload $artifact "$objectBase$name"
    }
    # Switch the updater pointer only after every versioned artifact succeeds.
    Invoke-CosUpload $latestPath "$($objectBase)latest-mac.yml"
}
finally {
    if ($script:CosConfigPath) {
        Remove-Item -LiteralPath $script:CosConfigPath -Force -ErrorAction SilentlyContinue
        $script:CosConfigPath = $null
    }
}

foreach ($artifact in $versionedArtifacts) {
    Test-PublicObject $UpdateUrl (Split-Path $artifact -Leaf)
}
Test-PublicObject $UpdateUrl "latest-mac.yml"
Test-RemoteLatest $UpdateUrl $latestPath
Write-Host "  [OK] macOS arm64 update published to COS from Windows." -ForegroundColor Green

# Upload an electron-builder release to a public-readable Tencent COS prefix.
# Versioned artifacts are uploaded first; latest.yml is uploaded last as the publish pointer.
[CmdletBinding()]
param(
    [string]$ReleaseDir = (Join-Path $PSScriptRoot "..\release"),
    [string]$Bucket = $env:COS_BUCKET,
    [string]$Region = $env:COS_REGION,
    [string]$Prefix = $(if ($env:VIBEBARA_COS_UPDATE_PREFIX) { $env:VIBEBARA_COS_UPDATE_PREFIX } else { "desktop/windows" }),
    [switch]$AllowUnsigned,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Net.ServicePointManager]::SecurityProtocol =
    [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$script:CosConfigPath = $null

function Require-Value([string]$Value, [string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "Missing required environment variable: $Name"
    }
}

function Invoke-CosUpload([string]$Source, [string]$ObjectKey) {
    $destination = "cos://$Bucket/$ObjectKey"
    Write-Host "  [upload] $(Split-Path $Source -Leaf) -> $destination" -ForegroundColor Cyan
    if ($DryRun) { return }

    & coscli cp $Source $destination `
        --acl public-read `
        --disable-log=true `
        -c $script:CosConfigPath
    if ($LASTEXITCODE -ne 0) {
        throw "COS upload failed for $(Split-Path $Source -Leaf) (exit $LASTEXITCODE)"
    }
}

function ConvertTo-YamlString([string]$Value) {
    return '"' + $Value.Replace('\', '\\').Replace('"', '\"') + '"'
}

function New-TemporaryCosConfig {
    $configPath = Join-Path ([System.IO.Path]::GetTempPath()) "vibebara-cos-$([guid]::NewGuid().ToString('N')).yaml"
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
      alias: vibebara-update
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
    $url = "$($BaseUrl.TrimEnd('/'))/latest.yml"
    $tempPath = Join-Path ([System.IO.Path]::GetTempPath()) "vibebara-latest-$([guid]::NewGuid().ToString('N')).yml"
    try {
        Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 30 -OutFile $tempPath
        $localHash = (Get-FileHash -LiteralPath $LocalPath -Algorithm SHA256).Hash
        $remoteHash = (Get-FileHash -LiteralPath $tempPath -Algorithm SHA256).Hash
        if ($localHash -ne $remoteHash) {
            throw "remote latest.yml content differs from the local release metadata"
        }
        Write-Host "  [metadata] remote latest.yml matches local SHA-256" -ForegroundColor Green
    }
    finally {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
}

$ReleaseDir = [System.IO.Path]::GetFullPath($ReleaseDir)
if (-not (Test-Path -LiteralPath $ReleaseDir -PathType Container)) {
    throw "Release directory not found: $ReleaseDir"
}

$latestPath = Join-Path $ReleaseDir "latest.yml"
if (-not (Test-Path -LiteralPath $latestPath -PathType Leaf)) {
    throw "Missing electron-updater metadata: $latestPath"
}

$latestText = [System.IO.File]::ReadAllText($latestPath)
$pathMatch = [regex]::Match($latestText, '(?m)^path:\s*(.+?)\s*$')
if (-not $pathMatch.Success) {
    throw "latest.yml does not contain a top-level installer path"
}
$installerName = $pathMatch.Groups[1].Value.Trim().Trim('"').Trim("'")
if ($installerName -notmatch '^VBB-Setup-\d+\.\d+\.\d+\.exe$') {
    throw "Unexpected installer path in latest.yml: $installerName"
}

$installerPath = Join-Path $ReleaseDir $installerName
$blockmapPath = "$installerPath.blockmap"
foreach ($required in @($installerPath, $blockmapPath)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Missing release artifact: $required"
    }
}

$shaMatch = [regex]::Match($latestText, '(?m)^sha512:\s*(\S+)\s*$')
$sizeMatch = [regex]::Match($latestText, '(?m)^\s+size:\s*(\d+)\s*$')
if (-not $shaMatch.Success -or -not $sizeMatch.Success) {
    throw "latest.yml does not contain the expected installer sha512 and size"
}
$actualSha512 = Get-FileSha512Base64 $installerPath
$expectedSha512 = $shaMatch.Groups[1].Value.Trim()
if ($actualSha512 -cne $expectedSha512) {
    throw "Installer SHA-512 does not match latest.yml"
}
$actualSize = (Get-Item -LiteralPath $installerPath).Length
$expectedSize = [int64]$sizeMatch.Groups[1].Value
if ($actualSize -ne $expectedSize) {
    throw "Installer size does not match latest.yml (expected $expectedSize, actual $actualSize)"
}
Write-Host "  [metadata] installer sha512 and size match latest.yml" -ForegroundColor Green

$signature = Get-AuthenticodeSignature -FilePath $installerPath
if ($signature.Status -eq [System.Management.Automation.SignatureStatus]::Valid) {
    Write-Host "  [signature] $installerName -> Valid" -ForegroundColor Green
}
elseif (
    $AllowUnsigned -and
    $signature.Status -eq [System.Management.Automation.SignatureStatus]::NotSigned
) {
    Write-Host "  [signature] WARNING: publishing unsigned installer" -ForegroundColor Yellow
}
else {
    throw "Installer signature is not valid: $($signature.Status) $($signature.StatusMessage)"
}

Require-Value $Bucket "COS_BUCKET"
Require-Value $Region "COS_REGION"
$Prefix = $Prefix.Trim().Trim("/")
if (-not $Prefix) {
    throw "VIBEBARA_COS_UPDATE_PREFIX cannot be empty"
}

$updateUrl = $env:VIBEBARA_UPDATE_URL
Require-Value $updateUrl "VIBEBARA_UPDATE_URL"
try {
    $parsedUpdateUrl = [uri]$updateUrl
    if ($parsedUpdateUrl.Scheme -ne "https") { throw "HTTPS required" }
}
catch {
    throw "VIBEBARA_UPDATE_URL must be a valid HTTPS URL"
}

if (-not $DryRun) {
    Require-Value $env:COS_SECRET_ID "COS_SECRET_ID"
    Require-Value $env:COS_SECRET_KEY "COS_SECRET_KEY"
    if (-not (Get-Command coscli -ErrorAction SilentlyContinue)) {
        throw "coscli was not found in PATH. Install Tencent COSCLI on the release machine."
    }
}

if ($DryRun) {
    Write-Host "  [dry-run] Validation completed; no files were uploaded." -ForegroundColor Yellow
    exit 0
}

$script:CosConfigPath = New-TemporaryCosConfig
try {
    $objectBase = "$Prefix/"
    Invoke-CosUpload $installerPath "$objectBase$installerName"
    Invoke-CosUpload $blockmapPath "$objectBase$(Split-Path $blockmapPath -Leaf)"
    # Publish latest.yml last so clients never observe metadata for incomplete artifacts.
    Invoke-CosUpload $latestPath "$($objectBase)latest.yml"
}
finally {
    if ($script:CosConfigPath) {
        Remove-Item -LiteralPath $script:CosConfigPath -Force -ErrorAction SilentlyContinue
        $script:CosConfigPath = $null
    }
}

Test-PublicObject $updateUrl $installerName
Test-PublicObject $updateUrl "$(Split-Path $blockmapPath -Leaf)"
Test-PublicObject $updateUrl "latest.yml"
Test-RemoteLatest $updateUrl $latestPath
Write-Host "  [OK] Desktop update published to COS origin." -ForegroundColor Green

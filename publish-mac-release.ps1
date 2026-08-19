# Extract the newest GitHub macOS Artifact from mac_release/ and publish it to COS.
[CmdletBinding()]
param(
    [string]$ArtifactDir,
    [string]$ArtifactPath,
    [string]$Bucket = $env:COS_BUCKET,
    [string]$Region = $env:COS_REGION,
    [string]$Prefix = "desktop/macos",
    [string]$UpdateUrl = $env:VIBEBARA_MAC_UPDATE_URL,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Require-Value([string]$Value, [string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "Missing required environment variable or parameter: $Name"
    }
}

if ([string]::IsNullOrWhiteSpace($ArtifactDir)) {
    $ArtifactDir = Join-Path $PSScriptRoot "mac_release"
}
$ArtifactDir = [System.IO.Path]::GetFullPath($ArtifactDir)
if (-not (Test-Path -LiteralPath $ArtifactDir -PathType Container)) {
    throw "Artifact directory not found: $ArtifactDir"
}

if ([string]::IsNullOrWhiteSpace($ArtifactPath)) {
    $candidate = Get-ChildItem -LiteralPath $ArtifactDir -File |
        Where-Object { $_.Name -match '^VBB-mac-\d+\.\d+\.\d+-arm64\.zip$' } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $candidate) {
        throw "No completed VBB-mac-<version>-arm64.zip Artifact found in $ArtifactDir"
    }
    $ArtifactPath = $candidate.FullName
}
else {
    $ArtifactPath = [System.IO.Path]::GetFullPath($ArtifactPath)
}

if (-not (Test-Path -LiteralPath $ArtifactPath -PathType Leaf)) {
    throw "Artifact archive not found: $ArtifactPath"
}

$artifactName = Split-Path $ArtifactPath -Leaf
$nameMatch = [regex]::Match($artifactName, '^VBB-mac-(\d+\.\d+\.\d+)-arm64\.zip$')
if (-not $nameMatch.Success) {
    throw "Unexpected Artifact filename: $artifactName"
}
$version = $nameMatch.Groups[1].Value
$baseName = "VBB-mac-$version-arm64"
$requiredNames = @(
    "$baseName.dmg",
    "$baseName.zip",
    "$baseName.dmg.blockmap",
    "$baseName.zip.blockmap",
    "latest-mac.yml"
)

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($ArtifactPath)
try {
    $entryNames = @($archive.Entries | ForEach-Object { Split-Path $_.FullName -Leaf })
    foreach ($required in $requiredNames) {
        if ($entryNames -notcontains $required) {
            throw "Artifact archive is incomplete; missing $required"
        }
    }
}
finally {
    $archive.Dispose()
}

Require-Value $Bucket "COS_BUCKET"
Require-Value $Region "COS_REGION"
Require-Value $env:COS_SECRET_ID "COS_SECRET_ID"
Require-Value $env:COS_SECRET_KEY "COS_SECRET_KEY"

$extractDir = Join-Path $ArtifactDir $baseName
Write-Host "[artifact] $ArtifactPath" -ForegroundColor Cyan
Write-Host "[extract]  $extractDir" -ForegroundColor Cyan
Expand-Archive -LiteralPath $ArtifactPath -DestinationPath $extractDir -Force

$publisher = Join-Path $PSScriptRoot "desktop\scripts\publish-mac-update-cos.ps1"
if (-not (Test-Path -LiteralPath $publisher -PathType Leaf)) {
    throw "macOS COS publisher not found: $publisher"
}

$publishArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $publisher,
    "-ReleaseDir", $extractDir,
    "-Bucket", $Bucket,
    "-Region", $Region,
    "-Prefix", $Prefix
)
if (-not [string]::IsNullOrWhiteSpace($UpdateUrl)) {
    $publishArgs += @("-UpdateUrl", $UpdateUrl)
}
if ($DryRun) {
    $publishArgs += "-DryRun"
}

& powershell @publishArgs
if ($LASTEXITCODE -ne 0) {
    throw "macOS COS publisher failed with exit code $LASTEXITCODE"
}

if ($DryRun) {
    Write-Host "[OK] Artifact $artifactName passed local validation." -ForegroundColor Green
}
else {
    $effectiveUpdateUrl = if ($UpdateUrl) {
        $UpdateUrl.TrimEnd("/")
    }
    else {
        "https://$Bucket.cos.$Region.myqcloud.com/$($Prefix.Trim('/'))"
    }
    Write-Host "[OK] macOS $version published." -ForegroundColor Green
    Write-Host "     DMG: $effectiveUpdateUrl/$baseName.dmg"
    Write-Host "     Feed: $effectiveUpdateUrl/latest-mac.yml"
}

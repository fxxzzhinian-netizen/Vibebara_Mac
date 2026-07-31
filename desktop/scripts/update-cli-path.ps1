[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Add", "Remove")]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [string]$TargetPath,

    [ValidateSet("User", "Process")]
    [string]$Scope = "User"
)

$ErrorActionPreference = "Stop"

function Normalize-PathEntry([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
    return $Value.Trim().Trim('"').TrimEnd("\")
}

$target = Normalize-PathEntry $TargetPath
if (-not $target) {
    throw "CLI PATH 目标不能为空"
}

$current = [Environment]::GetEnvironmentVariable("Path", $Scope)
$entries = @(
    ($current -split ";") |
        ForEach-Object { Normalize-PathEntry $_ } |
        Where-Object { $_ }
)
$withoutTarget = @(
    $entries | Where-Object {
        -not [string]::Equals($_, $target, [StringComparison]::OrdinalIgnoreCase)
    }
)

if ($Action -eq "Add") {
    $next = @($withoutTarget + $target) -join ";"
}
else {
    $next = $withoutTarget -join ";"
}

if ($next -ne $current) {
    [Environment]::SetEnvironmentVariable("Path", $next, $Scope)
}

if ($Scope -eq "User" -and -not ("Vibebara.NativeMethods" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
namespace Vibebara {
    public static class NativeMethods {
        [DllImport("user32.dll", CharSet = CharSet.Auto, SetLastError = true)]
        public static extern IntPtr SendMessageTimeout(
            IntPtr hWnd, uint msg, UIntPtr wParam, string lParam,
            uint flags, uint timeout, out UIntPtr result);
    }
}
"@
}

if ($Scope -eq "User") {
    $broadcast = [IntPtr]0xffff
    $wmSettingChange = 0x001a
    $result = [UIntPtr]::Zero
    [void][Vibebara.NativeMethods]::SendMessageTimeout(
        $broadcast,
        $wmSettingChange,
        [UIntPtr]::Zero,
        "Environment",
        0x0002,
        5000,
        [ref]$result
    )
}

Write-Output "CLI PATH $Action complete ($Scope): $target"

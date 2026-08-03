$ErrorActionPreference = "Stop"
$helper = Join-Path $PSScriptRoot "update-cli-path.ps1"
$target = "C:\Vibebara Test\resources\cli"
$original = $env:Path

try {
    $env:Path = "C:\Windows\System32;C:\Tools"
    & $helper -Action Add -TargetPath $target -Scope Process | Out-Null
    & $helper -Action Add -TargetPath "$target\" -Scope Process | Out-Null

    $matches = @(
        ($env:Path -split ";") |
            Where-Object {
                [string]::Equals(
                    $_.TrimEnd("\"),
                    $target,
                    [StringComparison]::OrdinalIgnoreCase
                )
            }
    )
    if ($matches.Count -ne 1) {
        throw "CLI PATH add 不是幂等操作: $env:Path"
    }

    & $helper -Action Remove -TargetPath $target -Scope Process | Out-Null
    if (($env:Path -split ";") -contains $target) {
        throw "CLI PATH remove 未删除目标项: $env:Path"
    }
    if ($env:Path -ne "C:\Windows\System32;C:\Tools") {
        throw "CLI PATH remove 破坏了其他 PATH 项: $env:Path"
    }

    Write-Output "[desktop-cli] PATH add/remove idempotency verified"
}
finally {
    $env:Path = $original
}

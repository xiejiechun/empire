param([switch]$Recover)
$ErrorActionPreference = 'Stop'
# Direct builds use the same full gate and ownership; no unchecked packaging entry point.
& (Join-Path $PSScriptRoot 'verify-release.ps1') -Recover:$Recover

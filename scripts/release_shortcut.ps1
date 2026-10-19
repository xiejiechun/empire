param(
    [Parameter(Mandatory=$true)][string]$Candidate,
    [Parameter(Mandatory=$true)][string]$Existing,
    [Parameter(Mandatory=$true)][string]$Target,
    [Parameter(Mandatory=$true)][string]$WorkingDirectory
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
if (Test-Path -LiteralPath $Candidate) { throw 'Shortcut candidate already exists.' }
$shell = New-Object -ComObject WScript.Shell
if (Test-Path -LiteralPath $Existing) {
    $old = $shell.CreateShortcut($Existing)
    if ($old.TargetPath -eq $Target -and $old.WorkingDirectory -eq $WorkingDirectory) {
        exit 0
    }
}
$shortcut = $shell.CreateShortcut($Candidate)
$shortcut.TargetPath = $Target
$shortcut.WorkingDirectory = $WorkingDirectory
$shortcut.IconLocation = "$Target,0"
$shortcut.Description = 'Empire desktop'
$shortcut.Save()

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$executable = Join-Path $projectRoot 'dist\Empire\Empire.exe'
$shortcutPath = Join-Path $projectRoot 'Empire.lnk'
$manifestDirectory = Join-Path $projectRoot 'build\generated'
$manifestPath = Join-Path $manifestDirectory 'build_manifest.json'
$dependencyReport = Join-Path $projectRoot 'build\dependency-report.json'
$requiredPyInstaller = '6.22.3'

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Create .venv and install the project dependencies first. See README.md.'
}
if (Get-Process Empire -ErrorAction SilentlyContinue) {
    throw 'Close Empire before rebuilding.'
}

$buildLock = [IO.File]::Open(
    (Join-Path $projectRoot '.build.lock'),
    [IO.FileMode]::OpenOrCreate,
    [IO.FileAccess]::ReadWrite,
    [IO.FileShare]::None
)
$previousPath = $env:PATH
try {
    $pythonVersion = (& $python -c 'import platform; print(platform.python_version())').Trim()
    if ($LASTEXITCODE -ne 0 -or -not $pythonVersion.StartsWith('3.12.')) {
        throw "Release build requires Python 3.12.x; found $pythonVersion."
    }
    $actualPyInstaller = (& $python -c 'import PyInstaller; print(PyInstaller.__version__)' 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or $actualPyInstaller -ne $requiredPyInstaller) {
        throw "Release build requires PyInstaller $requiredPyInstaller; found $actualPyInstaller. Install requirements.lock."
    }
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Installed dependencies are inconsistent.' }

    $commit = (& git -C $projectRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') {
        throw 'A Git commit is required to identify the build.'
    }
    $dirty = [bool]((& git -C $projectRoot status --porcelain).Count)
    $requirementsHash = (Get-FileHash -LiteralPath (Join-Path $projectRoot 'requirements.lock') -Algorithm SHA256).Hash.ToLowerInvariant()
    if (-not (Test-Path -LiteralPath $dependencyReport)) {
        throw 'Dependency report is missing. Run verify-release.ps1 before packaging.'
    }
    $dependencyData = Get-Content -LiteralPath $dependencyReport -Raw | ConvertFrom-Json
    if ($dependencyData.requirements_sha256 -ne $requirementsHash) {
        throw 'Dependency report does not match requirements.lock. Run verify-release.ps1 again.'
    }
    $dependencyReportHash = (Get-FileHash -LiteralPath $dependencyReport -Algorithm SHA256).Hash.ToLowerInvariant()
    $version = (& $python -c 'from empire import __version__; print(__version__)').Trim()
    New-Item -ItemType Directory -Path $manifestDirectory -Force | Out-Null
    $manifest = [ordered]@{
        version = $version
        commit = $commit
        dirty = $dirty
        requirements_sha256 = $requirementsHash
        dependency_count = [int]$dependencyData.component_count
        dependency_report_sha256 = $dependencyReportHash
        built_at_utc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
        python = $pythonVersion
        pyinstaller = $actualPyInstaller
    } | ConvertTo-Json
    [IO.File]::WriteAllText($manifestPath, $manifest, [Text.UTF8Encoding]::new($false))

    # Keep unrelated DLLs elsewhere on PATH out of the Qt application bundle.
    $basePython = (& $python -c 'import sys; print(sys.base_prefix)').Trim()
    $env:PATH = (Join-Path $projectRoot '.venv\Scripts') + ';' + $basePython + ';' +
        $env:SystemRoot + '\System32;' + $env:SystemRoot + ';' +
        $env:SystemRoot + '\System32\Wbem'
    & $python -m PyInstaller --noconfirm --clean `
        --distpath (Join-Path $projectRoot 'dist') `
        --workpath (Join-Path $projectRoot 'build') `
        (Join-Path $projectRoot 'Empire.spec')
    if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $executable
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.IconLocation = "$executable,0"
    $shortcut.Description = '打开 Empire 投资研究桌面'
    $shortcut.Save()
} finally {
    $env:PATH = $previousPath
    $buildLock.Dispose()
}

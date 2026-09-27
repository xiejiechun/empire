$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$executable = Join-Path $projectRoot 'dist\Empire\Empire.exe'
$smokeImage = Join-Path $projectRoot 'build\release-smoke.png'
$capacityReport = Join-Path $projectRoot 'build\capacity-report.json'
$dependencyReport = Join-Path $projectRoot 'build\dependency-report.json'

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Create .venv and install requirements.lock before release verification.'
}
if (Get-Process Empire -ErrorAction SilentlyContinue) {
    throw 'Close Empire normally before running the release gate.'
}

$previousIntegration = $env:EMPIRE_INTEGRATION
$previousScale = $env:QT_SCALE_FACTOR
$previousPlatform = $env:QT_QPA_PLATFORM
$previousLocalAppData = $env:LOCALAPPDATA
try {
    & $python (Join-Path $projectRoot 'scripts\verify_release_environment.py')
    if ($LASTEXITCODE -ne 0) { throw 'Release environment verification failed.' }
    & $python (Join-Path $projectRoot 'scripts\audit_dependencies.py') --output $dependencyReport
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $dependencyReport)) {
        throw 'Dependency inventory failed.'
    }
    & $python (Join-Path $projectRoot 'scripts\verify_documentation.py')
    if ($LASTEXITCODE -ne 0) { throw 'Documentation contract verification failed.' }
    & $python -m ruff check src tests scripts
    if ($LASTEXITCODE -ne 0) { throw 'Ruff failed.' }
    & $python -m mypy
    if ($LASTEXITCODE -ne 0) { throw 'Mypy failed.' }
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
    & git -C $projectRoot -c core.whitespace=cr-at-eol diff --check
    if ($LASTEXITCODE -ne 0) { throw 'Git whitespace check failed.' }
    $env:EMPIRE_INTEGRATION = '1'
    & $python -m pytest -q --tb=short -rs
    if ($LASTEXITCODE -ne 0) { throw 'Test suite failed.' }
    & $python (Join-Path $projectRoot 'scripts\measure_capacity.py') --quick --output $capacityReport
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $capacityReport)) {
        throw 'Isolated capacity baseline failed.'
    }
    foreach ($scale in @('1', '1.25', '1.5', '2')) {
        $env:QT_SCALE_FACTOR = $scale
        & $python (Join-Path $projectRoot 'scripts\verify_foundation_ui.py')
        if ($LASTEXITCODE -ne 0) { throw "UI layout verification failed at scale $scale." }
    }
    & (Join-Path $projectRoot 'build.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Package build failed.' }
    $packageDirectory = Join-Path $projectRoot 'dist\Empire'
    $portableEvidence = [ordered]@{
        chinese_space_path = $false
        packaged_smoke = $false
        first_run_prepared_config = $false
        config_recheck = $false
    }
    $portableRoot = Join-Path $projectRoot ("build\portable-smoke-" + [Guid]::NewGuid().ToString('N'))
    $portableDirectory = Join-Path $portableRoot '中文 空格\Empire'
    $buildRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'build'))
    $portableFull = [IO.Path]::GetFullPath($portableRoot)
    if (-not $portableFull.StartsWith($buildRoot + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Portable smoke directory escaped the build directory.'
    }
    New-Item -ItemType Directory -Path (Split-Path $portableDirectory) -Force | Out-Null
    Move-Item -LiteralPath $packageDirectory -Destination $portableDirectory
    try {
        $portableExecutable = Join-Path $portableDirectory 'Empire.exe'
        $env:QT_QPA_PLATFORM = 'offscreen'
        $smoke = Start-Process -FilePath $portableExecutable `
            -ArgumentList @('package-smoke', '--screenshot', $smokeImage) `
            -WorkingDirectory $portableDirectory -WindowStyle Hidden -Wait -PassThru
        if ($smoke.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $smokeImage)) {
            throw "Relocated packaged smoke failed with exit code $($smoke.ExitCode)."
        }
        $portableEvidence.chinese_space_path = $true
        $portableEvidence.packaged_smoke = $true
        $env:LOCALAPPDATA = Join-Path $portableRoot '用户 数据'
        $firstRun = Start-Process -FilePath $portableExecutable -ArgumentList @('check-config') `
            -WorkingDirectory $portableDirectory -WindowStyle Hidden -Wait -PassThru
        $preparedConfig = Join-Path $env:LOCALAPPDATA 'Empire\config.toml'
        if ($firstRun.ExitCode -ne 1 -or -not (Test-Path -LiteralPath $preparedConfig)) {
            throw 'Packaged first-run configuration guidance did not prepare the user config.'
        }
        $portableEvidence.first_run_prepared_config = $true
        $configCheck = Start-Process -FilePath $portableExecutable -ArgumentList @('check-config') `
            -WorkingDirectory $portableDirectory -WindowStyle Hidden -Wait -PassThru
        if ($configCheck.ExitCode -ne 0) { throw 'Packaged user configuration validation failed.' }
        $portableEvidence.config_recheck = $true
    } finally {
        $env:LOCALAPPDATA = $previousLocalAppData
        if (Test-Path -LiteralPath $portableDirectory) {
            Move-Item -LiteralPath $portableDirectory -Destination $packageDirectory
        }
        if (Test-Path -LiteralPath $portableRoot) {
            Remove-Item -LiteralPath $portableRoot -Recurse -Force
        }
    }
    $manifest = Get-Content -LiteralPath (Join-Path $projectRoot 'build\generated\build_manifest.json') -Raw | ConvertFrom-Json
    $capacity = Get-Content -LiteralPath $capacityReport -Raw | ConvertFrom-Json
    $dependencies = Get-Content -LiteralPath $dependencyReport -Raw | ConvertFrom-Json
    if (-not $capacity.passed) { throw 'Capacity report does not pass its acceptance checks.' }
    $report = [ordered]@{
        verified_at_utc = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
        manifest = $manifest
        executable_sha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
        smoke_image = $smokeImage
        capacity_report = $capacityReport
        capacity = $capacity
        dependency_report = $dependencyReport
        dependencies = $dependencies
        portable_distribution = $portableEvidence
    }
    $report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $projectRoot 'build\release-report.json') -Encoding utf8
    Write-Host 'PASS release gate: dependencies, tests, capacity, DPI, portable config, build, smoke.'
} finally {
    $env:EMPIRE_INTEGRATION = $previousIntegration
    $env:QT_SCALE_FACTOR = $previousScale
    $env:QT_QPA_PLATFORM = $previousPlatform
    $env:LOCALAPPDATA = $previousLocalAppData
}

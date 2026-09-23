$ErrorActionPreference = 'Stop'
$serviceName = 'MySQL_Empire'
$root = 'E:\mysql\empire'
$data = Join-Path $root 'data'
$logs = Join-Path $root 'logs'
$result = 'D:\project\empire\artifacts\mysql-low-write-maintenance.json'
$removed = @()
try {
    $service = Get-CimInstance Win32_Service -Filter "Name='MySQL_Empire'"
    if ($service.PathName -notlike '*E:\mysql\empire\server\bin\mysqld.exe*') {
        throw 'Unexpected MySQL service path'
    }
    & 'E:\mysql\empire\server\bin\mysqld.exe' '--defaults-file=E:\mysql\empire\my.ini' '--validate-config'
    if ($LASTEXITCODE -ne 0) { throw 'MySQL configuration validation failed' }
    Stop-Service -Name $serviceName
    (Get-Service $serviceName).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(60))
    # Resolve each exact, non-recursive target while the service is stopped.
    # Redo, undo, .ibd and replication metadata are never included.
    $targets = @(Get-ChildItem -LiteralPath $data -File | Where-Object {
        $_.Name -match '^binlog\.(\d{6}|index)$' -or
        $_.Name -in @('xiejiechun.log', 'xiejiechun-slow.log')
    })
    $targets += @(Get-ChildItem -LiteralPath $logs -File | Where-Object { $_.Extension -in @('.err','.log') })
    foreach ($target in $targets) {
        $resolved = (Resolve-Path -LiteralPath $target.FullName).Path
        if ([IO.Path]::GetDirectoryName($resolved) -notin @($data, $logs)) { throw 'Target outside MySQL log directories' }
        $removed += @{ path = $resolved; bytes = $target.Length }
        Remove-Item -LiteralPath $resolved
    }
    Start-Service -Name $serviceName
    (Get-Service $serviceName).WaitForStatus('Running', [TimeSpan]::FromSeconds(60))
    @{ status = 'complete'; removed = $removed; service = $serviceName } |
        ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $result -Encoding UTF8
} catch {
    # Preserve availability if a maintenance step failed after the normal stop.
    if ((Get-Service $serviceName).Status -eq 'Stopped') { Start-Service -Name $serviceName -ErrorAction SilentlyContinue }
    @{ status = 'failed'; error = $_.Exception.Message; removed = $removed } |
        ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $result -Encoding UTF8
    exit 1
}

# Estado del escaneo local: tareas rapida y lenta, ultimas lineas de log y estado
# de cada fuente de datos segun el ultimo docs/data.json (una fuente con 0
# mercados o de la que no se lee nada es senal de que algo va mal).

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$any = $false

foreach ($entry in @(@("SurebetsLocalScan", "rapido: APIs directas + cache, cada 5 min", "local_scan.log"),
                     @("SurebetsSlowScan", "lento: comparadores -> cache, cada 30 min", "local_slow_scan.log"))) {
    $name, $desc, $log = $entry
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "[$name] no existe (ver scripts\install_scan_tasks.ps1)"
        continue
    }
    $any = $true
    $info = Get-ScheduledTaskInfo -TaskName $name
    $estado = if ($task.State -eq "Disabled") { "APAGADO" } else { "ENCENDIDO" }
    Write-Host "[$name] $estado ($desc)"
    Write-Host "    Ultima ejecucion: $($info.LastRunTime)  (resultado: $($info.LastTaskResult))"
    Write-Host "    Proximo disparo:  $($info.NextRunTime)"
    $logFile = Join-Path $ProjectRoot "logs\$log"
    if (Test-Path $logFile) {
        Write-Host "    Ultimas lineas de $log :"
        Get-Content -Path $logFile -Tail 4 | ForEach-Object { Write-Host "      $_" }
    }
}
if (-not $any) { exit 1 }

$dataFile = Join-Path $ProjectRoot "docs\data.json"
if (Test-Path $dataFile) {
    $data = Get-Content $dataFile -Raw -Encoding utf8 | ConvertFrom-Json
    $age = [int]((Get-Date).ToUniversalTime() - ([datetime]$data.generated_at).ToUniversalTime()).TotalMinutes
    Write-Host ""
    Write-Host "Ultimo docs/data.json: hace $age min (modo: $($data.settings.mode))"
    if ($data.settings.sources) {
        foreach ($src in $data.settings.sources.PSObject.Properties) {
            $v = $src.Value
            $extra = ""
            if ($v.cache) { $extra = "  [cache: $($v.cache.leagues) competiciones, lectura mas antigua $($v.cache.oldest_minutes) min]" }
            $flag = if ((-not $v.ok) -or ($v.markets -eq 0)) { "  <-- SIN DATOS" } else { "" }
            Write-Host ("  {0,-12} {1,6} mercados, {2,4} partidos{3}{4}" -f $src.Name, $v.markets, $v.events, $extra, $flag)
        }
    }
}

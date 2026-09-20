# Estado del escaneo local: encendido/apagado, ultima ejecucion y proximo disparo.

$TaskName = "SurebetsLocalScan"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "No existe la tarea '$TaskName' en el Programador de tareas."
    exit 1
}

$info = Get-ScheduledTaskInfo -TaskName $TaskName
$estado = if ($task.State -eq "Disabled") { "APAGADO" } else { "ENCENDIDO" }

Write-Host "Escaneo local: $estado"
Write-Host "Ultima ejecucion:  $($info.LastRunTime)  (resultado: $($info.LastTaskResult))"
Write-Host "Proximo disparo:   $($info.NextRunTime)"

$logFile = Join-Path (Split-Path -Parent $PSScriptRoot) "logs\local_scan.log"
if (Test-Path $logFile) {
    Write-Host "`nUltimas lineas de log:"
    Get-Content -Path $logFile -Tail 8
}

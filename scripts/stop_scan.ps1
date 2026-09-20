# Apaga el escaneo local: deshabilita la tarea programada "SurebetsLocalScan"
# (se ejecuta cada 5 min via el Programador de tareas de Windows, ver
# scripts/local_scan.ps1) y, si hay un ciclo en marcha ahora mismo, lo corta.

$TaskName = "SurebetsLocalScan"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "No existe la tarea '$TaskName' en el Programador de tareas."
    exit 1
}

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Disable-ScheduledTask -TaskName $TaskName | Out-Null

Write-Host "Escaneo local detenido (tarea '$TaskName' deshabilitada)."
Write-Host "Para reanudarlo: scripts\start_scan.ps1"

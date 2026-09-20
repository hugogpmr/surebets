# Enciende el escaneo local: habilita la tarea programada "SurebetsLocalScan"
# (ver scripts/local_scan.ps1) y dispara un ciclo ya mismo en vez de esperar a
# los 5 min del siguiente disparo automatico.

$TaskName = "SurebetsLocalScan"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "No existe la tarea '$TaskName' en el Programador de tareas."
    exit 1
}

Enable-ScheduledTask -TaskName $TaskName | Out-Null
Start-ScheduledTask -TaskName $TaskName

$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host "Escaneo local activado (tarea '$TaskName' habilitada, ciclo disparado ahora)."
Write-Host "Proximo disparo automatico: $($info.NextRunTime)"

# Enciende el escaneo local: habilita las dos tareas programadas y dispara un
# ciclo de cada una ya mismo en vez de esperar al siguiente disparo automatico.
#   - SurebetsLocalScan: ciclo RAPIDO (APIs directas + cache de comparadores), cada 5 min
#   - SurebetsSlowScan:  ciclo LENTO (lee los comparadores y llena la cache), cada 30 min
# La tarea lenta se crea con scripts\install_scan_tasks.ps1 (una sola vez).

$Fast = "SurebetsLocalScan"
$Slow = "SurebetsSlowScan"

$fastTask = Get-ScheduledTask -TaskName $Fast -ErrorAction SilentlyContinue
if (-not $fastTask) {
    Write-Host "No existe la tarea '$Fast' en el Programador de tareas."
    exit 1
}
if (-not (Get-ScheduledTask -TaskName $Slow -ErrorAction SilentlyContinue)) {
    Write-Host "Falta la tarea del ciclo lento: ejecutando scripts\install_scan_tasks.ps1"
    & (Join-Path $PSScriptRoot "install_scan_tasks.ps1")
}

# El lento primero: llena la cache que va a leer el rapido.
Enable-ScheduledTask -TaskName $Slow | Out-Null
Start-ScheduledTask -TaskName $Slow
Enable-ScheduledTask -TaskName $Fast | Out-Null
Start-ScheduledTask -TaskName $Fast

Write-Host "Escaneo local activado:"
foreach ($name in @($Fast, $Slow)) {
    $info = Get-ScheduledTaskInfo -TaskName $name
    Write-Host ("  {0,-18} proximo disparo automatico: {1}" -f $name, $info.NextRunTime)
}

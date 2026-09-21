# Apaga el escaneo local: deshabilita las dos tareas programadas (rapida
# "SurebetsLocalScan" y lenta "SurebetsSlowScan", ver scripts/local_scan.ps1 y
# scripts/local_slow_scan.ps1) y corta cualquier ciclo en marcha ahora mismo,
# incluidos el proceso de Python y los navegadores que haya lanzado.

$Names = @("SurebetsLocalScan", "SurebetsSlowScan")
$found = $false

foreach ($name in $Names) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        $found = $true
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        Disable-ScheduledTask -TaskName $name | Out-Null
        Write-Host "Tarea '$name' deshabilitada."
    }
}
if (-not $found) {
    Write-Host "No existe ninguna tarea de escaneo en el Programador de tareas."
    exit 1
}

# Stop-ScheduledTask no siempre mata a los hijos: se cierra el arbol de cada
# scan_once_action.py (y con el, sus Chromium de Playwright).
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*scan_once_action.py*" }
foreach ($p in $procs) {
    taskkill /PID $p.ProcessId /T /F | Out-Null
    Write-Host "Proceso de escaneo $($p.ProcessId) terminado."
}

Write-Host "Escaneo local detenido. Para reanudarlo: scripts\start_scan.ps1"

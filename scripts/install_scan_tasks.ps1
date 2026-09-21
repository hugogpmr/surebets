# Registra (o actualiza) la tarea programada del ciclo LENTO "SurebetsSlowScan"
# (scripts/local_slow_scan.ps1, cada 30 min, sin solaparse consigo misma) copiando
# el usuario y los ajustes de la tarea del ciclo rapido "SurebetsLocalScan".
# La deja DESHABILITADA: se enciende con scripts\start_scan.ps1.

$FastName = "SurebetsLocalScan"
$SlowName = "SurebetsSlowScan"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

$fast = Get-ScheduledTask -TaskName $FastName -ErrorAction SilentlyContinue
if (-not $fast) {
    Write-Host "No existe la tarea '$FastName': crea primero la del ciclo rapido (ver deploy/README_DEPLOY.md, opcion C)."
    exit 1
}

$script = Join-Path $ProjectRoot "scripts\local_slow_scan.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)

# Mismos ajustes que la tarea rapida (bateria, despertar el equipo...) pero sin
# solaparse consigo misma y con un limite de 3 h por ciclo.
$settings = $fast.Settings
$settings.MultipleInstances = "IgnoreNew"
$settings.ExecutionTimeLimit = "PT3H"

Register-ScheduledTask -TaskName $SlowName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $fast.Principal -Force | Out-Null
Disable-ScheduledTask -TaskName $SlowName | Out-Null

Write-Host "Tarea '$SlowName' registrada (cada 30 min) y DESHABILITADA."
Write-Host "Para encender todo el escaneo: scripts\start_scan.ps1"

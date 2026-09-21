# Ciclo LENTO del escaneo local: lee los comparadores (CuotasAhora, BetExplorer)
# por rotacion de competiciones durante un presupuesto de tiempo
# (SLOW_BUDGET_MINUTES, 20 por defecto) y actualiza la cache en cache/ (ver
# engine/cache.py). No calcula surebets, no avisa por Telegram y no toca git ni
# la base de datos: de eso se encarga el ciclo rapido (scripts/local_scan.ps1),
# que lee la cache cada pocos minutos.
#
# Pensado para el Programador de tareas de Windows (tarea "SurebetsSlowScan",
# cada 30 min, sin solaparse consigo misma; ver scripts/install_scan_tasks.ps1).

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "local_slow_scan.log"

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $LogFile -Value $line -Encoding utf8
}

Write-Log "Iniciando ciclo lento (comparadores)"

# Mismo motivo que en local_scan.ps1: navegadores de Playwright dentro del .venv
# y no en el cache global, invisible para procesos lanzados por el Programador.
$env:PLAYWRIGHT_BROWSERS_PATH = "0"
$env:PYTHONPATH = $ProjectRoot
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$scanScript = Join-Path $ProjectRoot "scripts\scan_once_action.py"

# Redireccion real de stdout/stderr a ficheros temporales (Start-Process): con
# "&" PowerShell envuelve cada linea de stderr como NativeCommandError.
$stdout = [System.IO.Path]::GetTempFileName()
$stderr = [System.IO.Path]::GetTempFileName()
try {
    $proc = Start-Process -FilePath $python -ArgumentList "`"$scanScript`" --mode slow" -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    Get-Content -Path $stdout, $stderr -ErrorAction SilentlyContinue | Add-Content -Path $LogFile -Encoding utf8
    $exitCode = $proc.ExitCode
} finally {
    Remove-Item -Path $stdout, $stderr -ErrorAction SilentlyContinue
}

if ($exitCode -ne 0) {
    Write-Log "El ciclo lento fallo con codigo $exitCode"
    exit $exitCode
}
Write-Log "Ciclo lento completado"

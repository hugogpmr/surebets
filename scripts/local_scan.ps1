# Ciclo de escaneo local: sustituye al scraping en GitHub Actions (bloqueado por
# IP de datacenter para Betfair/CuotasAhora - ver checklist.md seccion 7).
# Pensado para el Programador de tareas de Windows (ver deploy/README_DEPLOY.md,
# "Opcion C: scraper local"), no para ejecucion manual interactiva.

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "local_scan.log"

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $LogFile -Value $line -Encoding utf8
}

function Invoke-Logged {
    # Ejecuta un proceso con redireccion real de stdout/stderr a ficheros temp
    # (via Start-Process), en vez de "&"/"*>>" de PowerShell, que envuelve cada
    # linea de stderr de un proceso nativo como NativeCommandError - con
    # $ErrorActionPreference = "Stop" eso aborta el script entero a la primera
    # linea de log de Python o de aviso de git, aunque el proceso acabe bien.
    param(
        [Parameter(Mandatory)] [string]$FilePath,
        [Parameter(Mandatory)] [string]$ArgumentString
    )
    $stdout = [System.IO.Path]::GetTempFileName()
    $stderr = [System.IO.Path]::GetTempFileName()
    try {
        $proc = Start-Process -FilePath $FilePath -ArgumentList $ArgumentString -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        Get-Content -Path $stdout, $stderr -ErrorAction SilentlyContinue | Add-Content -Path $LogFile -Encoding utf8
        return $proc.ExitCode
    } finally {
        Remove-Item -Path $stdout, $stderr -ErrorAction SilentlyContinue
    }
}

function Send-TelegramAlert {
    param([string]$Text)
    $envFile = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path $envFile)) { return }
    $envVars = @{}
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            $envVars[$Matches[1]] = $Matches[2].Trim('"').Trim("'")
        }
    }
    $token = $envVars["TELEGRAM_BOT_TOKEN"]
    $chatId = $envVars["TELEGRAM_CHAT_ID"]
    if (-not $token -or -not $chatId) { return }
    try {
        Invoke-RestMethod -Method Post -Uri "https://api.telegram.org/bot$token/sendMessage" `
            -Body @{ chat_id = $chatId; text = $Text } | Out-Null
    } catch {
        Write-Log "No se pudo enviar aviso de fallo a Telegram: $_"
    }
}

Write-Log "Iniciando ciclo de escaneo local"

# PLAYWRIGHT_BROWSERS_PATH=0 fuerza a instalar/buscar los navegadores dentro
# del propio .venv (site-packages/playwright/driver/package/.local-browsers)
# en vez de en el cache global %LOCALAPPDATA%\ms-playwright: bajo el
# Programador de tareas de Windows ese cache global resultaba invisible para
# el proceso lanzado por la tarea (Test-Path devolvia False para un exe que
# desde una sesion interactiva normal si existia) - causa exacta no
# diagnosticada (aislamiento de sesion/perfil del Programador de tareas), pero
# usar una ruta dentro del propio proyecto evita el problema por completo.
$env:PLAYWRIGHT_BROWSERS_PATH = "0"
$env:PYTHONPATH = $ProjectRoot
# Sobreescribe el DB_PATH del .env local (pensado para "py main.py" en pruebas
# manuales, que usa surebets.db suelto en la raiz) por el mismo data/surebets.db
# que ya usa scan_once_action.py en GitHub Actions: si no, este script escribe
# en una base de datos distinta a la que lee el panel web y a la que esta en
# git, dejando docs/data.json fuera de sincronia con el historial real.
$env:DB_PATH = Join-Path $ProjectRoot "data\surebets.db"
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$scanScript = Join-Path $ProjectRoot "scripts\scan_once_action.py"

# Modo rapido: solo las APIs directas (~1-2 min) + los comparadores desde la cache
# que mantiene el ciclo lento (scripts/local_slow_scan.ps1). Ver engine/cache.py.
$scanExitCode = Invoke-Logged -FilePath $python -ArgumentString "`"$scanScript`" --mode fast"

if ($scanExitCode -ne 0) {
    Write-Log "El escaneo fallo con codigo $scanExitCode"
    Send-TelegramAlert "Fallo el escaneo local de surebets (codigo $scanExitCode). Ver $LogFile"
    exit $scanExitCode
}

Invoke-Logged -FilePath "git" -ArgumentString "add data/ docs/data.json" | Out-Null
git diff --cached --quiet
$hasChanges = ($LASTEXITCODE -ne 0)

if (-not $hasChanges) {
    Write-Log "Sin cambios que commitear"
    Write-Log "Ciclo completado"
    exit 0
}

# Commitear ANTES de intentar sincronizar: si se hiciera "git pull" con
# docs/data.json ya modificado en el working tree pero sin commitear, git
# rechaza el merge entero ("local changes would be overwritten") en cuanto el
# origen tenga cualquier cambio, aunque sea en el mismo fichero regenerado.
# Con el cambio ya commiteado, un "git pull" de por medio se resuelve como un
# merge de verdad (ver .gitattributes: estos ficheros usan merge=ours, valido
# porque ambos lados son igual de "ultima foto valida" sin relacion de
# precedencia entre si).
Invoke-Logged -FilePath "git" -ArgumentString 'commit -m "chore: actualizar estado del escaneo (local)"' | Out-Null

$pushExitCode = Invoke-Logged -FilePath "git" -ArgumentString "push"
if ($pushExitCode -ne 0) {
    Write-Log "git push rechazado, intentando 'git pull' para sincronizar con el remoto"
    $pullExitCode = Invoke-Logged -FilePath "git" -ArgumentString "pull --no-edit"
    if ($pullExitCode -ne 0) {
        Write-Log "git pull fallo (codigo $pullExitCode) - conflicto real, no se pushea este ciclo"
        Send-TelegramAlert "El escaneo local funciono pero el commit no se pudo sincronizar con GitHub (conflicto real). Revisa $LogFile y resuelve manualmente."
        exit 1
    }
    $pushExitCode = Invoke-Logged -FilePath "git" -ArgumentString "push"
    if ($pushExitCode -ne 0) {
        Write-Log "git push sigue fallando tras el pull (codigo $pushExitCode)"
        Send-TelegramAlert "El escaneo local funciono pero 'git push' sigue fallando tras sincronizar. Revisa $LogFile y resuelve manualmente."
        exit 1
    }
}

Write-Log "Cambios commiteados y pusheados"

Write-Log "Ciclo completado"

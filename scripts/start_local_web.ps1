# Sirve la carpeta docs/ (el mismo panel que GitHub Pages) en un servidor HTTP
# local y abre el navegador. No se puede abrir docs/index.html directamente
# como file:// porque el fetch() de data.json falla por CORS en ese esquema.
#
# El escaneo local (tarea programada "SurebetsLocalScan", ver start_scan.ps1)
# es quien regenera docs/data.json cada ~5 min; este script solo sirve esa
# carpeta tal cual - app.js ya hace polling de data.json cada 60s por su
# cuenta, así que basta con dejar esta ventana abierta y refrescar el navegador
# si hace falta. Ctrl+C aquí para parar el servidor.

param(
    [int]$Port = 8000
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DocsDir = Join-Path $ProjectRoot "docs"
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "No se encuentra $python - revisa que el entorno virtual este creado (.venv)."
    exit 1
}

$Url = "http://localhost:$Port/"

Write-Host "Sirviendo $DocsDir en $Url (Ctrl+C para parar)"
Start-Process $Url

Set-Location $DocsDir
& $python (Join-Path $ProjectRoot "scripts\local_http_server.py") $Port

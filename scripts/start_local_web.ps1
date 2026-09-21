# Sirve la carpeta docs/ (el mismo panel que GitHub Pages) en un servidor HTTP
# local y abre el navegador. No se puede abrir docs/index.html directamente
# como file:// porque el fetch() de data.json falla por CORS en ese esquema.
#
# El escaneo local (tarea programada "SurebetsLocalScan", ver start_scan.ps1)
# es quien regenera docs/data.json cada ~5 min; este script solo sirve esa
# carpeta tal cual - app.js ya hace polling de data.json cada 60s por su
# cuenta, así que basta con dejar esta ventana abierta y refrescar el navegador
# si hace falta. Ctrl+C aquí para parar el servidor.

# Con -Lan el panel tambien se puede abrir desde el movil (misma WiFi, o desde
# cualquier sitio si tienes Tailscale). Sin -Lan solo escucha en este PC.
param(
    [int]$Port = 8000,
    [switch]$Lan
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DocsDir = Join-Path $ProjectRoot "docs"
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "No se encuentra $python - revisa que el entorno virtual este creado (.venv)."
    exit 1
}

$Url = "http://localhost:$Port/"
$BindHost = "127.0.0.1"

if ($Lan) {
    $BindHost = "0.0.0.0"
    # IPs de red local de casa (192.168.x / 172.16-31.x); se ignoran el VPN y las 169.254 (sin red).
    $ips = Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -match '^(192\.168\.|172\.(1[6-9]|2\d|3[01])\.)' } |
        Select-Object -ExpandProperty IPAddress
    # Tailscale reparte IPs 100.64.0.0/10.
    $ts = Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -match '^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.' } |
        Select-Object -ExpandProperty IPAddress
    Write-Host "Desde el movil abre:"
    foreach ($ip in $ips) { Write-Host "  http://${ip}:$Port/   (misma WiFi)" }
    foreach ($ip in $ts)  { Write-Host "  http://${ip}:$Port/   (Tailscale, desde cualquier sitio)" }
    if (-not (Get-NetFirewallRule -DisplayName "Surebets panel" -ErrorAction SilentlyContinue)) {
        Write-Host "AVISO: falta la regla de firewall. Ejecuta UNA vez, en PowerShell como administrador:"
        Write-Host "  New-NetFirewallRule -DisplayName 'Surebets panel' -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Private"
    }
}

Write-Host "Sirviendo $DocsDir en $Url (Ctrl+C para parar)"
Start-Process $Url

Set-Location $DocsDir
& $python (Join-Path $ProjectRoot "scripts\local_http_server.py") $Port $BindHost

# Vigil — one-command demo start (Windows PowerShell).
#   powershell -ExecutionPolicy Bypass -File run_demo.ps1            # start (seeds DB on first run)
#   powershell -ExecutionPolicy Bypass -File run_demo.ps1 -Reset     # wipe + reseed, then start
#   powershell -ExecutionPolicy Bypass -File run_demo.ps1 -Mock      # force mock payments (offline)
param([switch]$Reset, [switch]$Mock, [switch]$SkipBuild, [int]$Port = 8000)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$py = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
  Write-Host "Creating Python venv..." -ForegroundColor Cyan
  python -m venv (Join-Path $backend ".venv")
  & $py -m pip install -q -r (Join-Path $backend "requirements.txt")
}
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
  Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
  Push-Location $frontend; npm install --no-audit --no-fund; Pop-Location
}
if (-not $SkipBuild) {
  Write-Host "Building frontend..." -ForegroundColor Cyan
  Push-Location $frontend; npm run build --silent; if ($LASTEXITCODE -ne 0) { Pop-Location; throw "frontend build failed" }; Pop-Location
}
if ($Reset) {
  Write-Host "Resetting demo database..." -ForegroundColor Cyan
  Push-Location $backend; & $py -c "from vigil import db; from vigil.sim import seed; db.connect(); print(seed.seed())"; Pop-Location
}
if ($Mock) { $env:VIGIL_PAYMENT_PROVIDER = "mock" }
$env:VIGIL_PORT = "$Port"
$env:PYTHONIOENCODING = "utf-8"
Push-Location $backend
try { & $py -m vigil.app } finally { Pop-Location }

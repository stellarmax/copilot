# Start the public (Cloudflare Tunnel) deployment on this computer.
# Usage (from the project root):   powershell -ExecutionPolicy Bypass -File scripts\start-production.ps1
# Reads Cloudflare Access settings from deploy.env, builds the web app, then serves everything on
# http://127.0.0.1:8000 for cloudflared to forward. Stop with Ctrl+C.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path "deploy.env")) {
    Write-Host "deploy.env not found. Copy deploy.env.example to deploy.env and fill in your Cloudflare Access values." -ForegroundColor Red
    exit 1
}
foreach ($line in Get-Content "deploy.env") {
    if ($line -match '^\s*([A-Z_]+)\s*=\s*(.+?)\s*$') { Set-Item -Path "Env:$($Matches[1])" -Value $Matches[2] }
}

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Creating the Python virtual environment..."
    python -m venv .venv
    & $python -m pip install --upgrade pip
}
& $python -m pip install -q -r backend\requirements.txt

Push-Location frontend
if (-not (Test-Path "node_modules")) { npm.cmd ci }
npm.cmd run build
Pop-Location

Write-Host "Serving on http://127.0.0.1:8000 (reachable publicly only through Cloudflare Tunnel + Access)." -ForegroundColor Green
& $python -m uvicorn backend.serve:app --host 127.0.0.1 --port 8000

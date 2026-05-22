Set-Location $PSScriptRoot
$env:OPEN_BROWSER = "1"
$env:APP_URL = "http://127.0.0.1:8000"

if (-not (Test-Path ".venv")) {
  python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1
pip install -q -r requirements.txt

Write-Host ""
Write-Host "  Quiniela Predictor" -ForegroundColor Green
Write-Host "  http://127.0.0.1:8000" -ForegroundColor Cyan
Write-Host "  El navegador se abrira solo. Ctrl+C para detener." -ForegroundColor DarkGray
Write-Host ""

python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

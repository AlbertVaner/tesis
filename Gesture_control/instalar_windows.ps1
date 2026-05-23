$ErrorActionPreference = 'Stop'
if (-not (Test-Path -Path .venv)) {
    py -3.11 -m venv .venv
}
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
Write-Host "`nEntorno instalado correctamente." -ForegroundColor Green
Write-Host "Para ejecutar el proyecto:`n" -ForegroundColor Cyan
Write-Host "    .\.venv\Scripts\Activate.ps1"
Write-Host "    python test_camera.py"
Write-Host "    python main.py"
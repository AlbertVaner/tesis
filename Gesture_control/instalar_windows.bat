@echo off
setlocal enabledelayedexpansion
if not exist .venv (
    py -3.11 -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
echo.
echo Entorno instalado correctamente.
echo Para ejecutar el proyecto:
echo    .venv\Scripts\activate.bat
echo    python test_camera.py
echo    python main.py
echo.
endlocal

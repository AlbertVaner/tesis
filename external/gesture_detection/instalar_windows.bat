@echo off
setlocal enabledelayedexpansion
pushd "%~dp0\..\.."
if not exist .venv (
    py -3.11 -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip setuptools wheel
pip install -r .\external\gesture_detection\requirements.txt
echo.
echo Entorno instalado correctamente.
echo Para ejecutar el proyecto:
echo    .venv\Scripts\activate.bat
echo    python .\external\gesture_detection\main_hands.py
echo.
popd
endlocal

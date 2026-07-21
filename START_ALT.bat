@echo off
REM ====================================================================
REM  START_ALT.bat — starter ALLE prosjekt-tjenester fra D:\nav med
REM  prosjektets EGEN Python (.pyruntime). Dobbeltklikk for aa starte alt.
REM  ("alt" = alle tjenestene). Ingenting kjorer fra C.
REM ====================================================================
cd /d "%~dp0"

REM Alt skal ligge/kjore fra D:\nav (ogsaa hvis du dobbeltklikker).
set "PY=%CD%\.pyruntime\python.exe"
set "EASYOCR_MODULE_PATH=%CD%\.EasyOCR"
set "HF_HOME=%CD%\.cache\huggingface"
set "PIP_CACHE_DIR=%CD%\.cache\pip"
set "PREFECT_HOME=%CD%\.prefect"

if not exist "%PY%" (
    echo [FEIL] Fant ikke prosjekt-Python: %PY%
    echo        Kjor migreringen paa nytt eller sjekk .pyruntime.
    pause
    exit /b 1
)

echo Starter NAV dokument-API paa :8600 ...
start "NAV dokument-API :8600" /d "%CD%" cmd /k "%PY%" skript\dokument_api.py

echo Starter Prefect-UI paa :4200 ...
start "Prefect :4200" /d "%CD%" cmd /k .venv-prefect\Scripts\prefect.exe server start --host 127.0.0.1 --port 4200

echo.
echo   ================================================================
echo     Alt startet (hver tjeneste i eget vindu):
echo       API:     http://127.0.0.1:8600/hjelp
echo       Prefect: http://127.0.0.1:4200
echo     Lukk vinduet eller Ctrl+C for aa stoppe en tjeneste.
echo   ================================================================
echo.
echo   Ekstern tilgang (tunnel)? Kjor START_SERVER.bat i tillegg,
echo   eller start cloudflared.exe manuelt. Auto-start ved oppstart?
echo   Bruk Windows-tjenesten (skript\tjeneste\installer_tjeneste.ps1).
echo.
timeout /t 8 >nul

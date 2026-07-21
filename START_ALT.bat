@echo off
REM ====================================================================
REM  START_ALT.bat - starter ALLE prosjekt-tjenester fra nav-mappa med
REM  prosjektets EGEN Python (.pyruntime). Dobbeltklikk for aa starte alt.
REM  Fungerer uansett hvor nav-mappa ligger (portabel). Ingenting fra C.
REM ====================================================================
cd /d "%~dp0"

REM Alt skal ligge/kjore fra nav-mappa (ogsaa hvis du dobbeltklikker).
set "PY=%CD%\.pyruntime\python.exe"
set "EASYOCR_MODULE_PATH=%CD%\.EasyOCR"
set "HF_HOME=%CD%\.cache\huggingface"
set "PIP_CACHE_DIR=%CD%\.cache\pip"
set "PREFECT_HOME=%CD%\.prefect"
REM Kun nav-lokale pakker: ignorer %APPDATA%\Python (user-site) -> ingen C-binding.
set "PYTHONNOUSERSITE=1"
REM UTF-8-trygg utskrift (norske tegn i pipe/redirect).
set "PYTHONUTF8=1"

if not exist "%PY%" (
    echo [FEIL] Fant ikke prosjekt-Python: %PY%
    echo        Sjekk at .pyruntime ligger i nav-mappa.
    pause
    exit /b 1
)

REM --- KRITISK tjeneste: dokument-API (starter alltid) -----------------
echo Starter NAV dokument-API paa :8600 ...
start "NAV dokument-API :8600" /d "%CD%" cmd /k "%PY%" skript\dokument_api.py

REM --- Prefect (valgfri): venv baker inn en ABSOLUTT sti. Hvis nav ble
REM     kopiert til en ANNEN sti enn sist, er venv-en broten -> bygg paa
REM     nytt fra prosjekt-tolken (.pyruntime er selv full-portabel). --------
set "PREFEKT_OK=0"
if exist ".venv-prefect\Scripts\prefect.exe" (
    .venv-prefect\Scripts\python.exe -c "import prefect" 1>nul 2>nul && set "PREFEKT_OK=1"
)
if "%PREFEKT_OK%"=="0" (
    echo [Prefect] venv mangler eller peker paa feil sti - bygger paa nytt ...
    "%PY%" -m venv --clear .venv-prefect
    .venv-prefect\Scripts\python.exe -m pip install --disable-pip-version-check -q prefect
    if exist ".venv-prefect\Scripts\prefect.exe" (
        .venv-prefect\Scripts\python.exe -c "import prefect" 1>nul 2>nul && set "PREFEKT_OK=1"
    )
)
if "%PREFEKT_OK%"=="1" (
    echo Starter Prefect-UI paa :4200 ...
    start "Prefect :4200" /d "%CD%" cmd /k .venv-prefect\Scripts\prefect.exe server start --host 127.0.0.1 --port 4200
) else (
    echo [Prefect] HOPPET OVER - kunne ikke bygge venv ^(trenger internett for
    echo           'pip install prefect'^). API-en kjorer uansett. Bygg manuelt:
    echo             "%PY%" -m venv --clear .venv-prefect
    echo             .venv-prefect\Scripts\python.exe -m pip install prefect
)

echo.
echo   ================================================================
echo     Startet ^(hver tjeneste i eget vindu^):
echo       API:     http://127.0.0.1:8600/hjelp
if "%PREFEKT_OK%"=="1" echo       Prefect: http://127.0.0.1:4200
echo     Lukk vinduet eller Ctrl+C for aa stoppe en tjeneste.
echo   ================================================================
echo.
echo   Ekstern tilgang ^(tunnel^)? Kjor START_SERVER.bat i tillegg,
echo   eller start cloudflared.exe manuelt. Auto-start ved oppstart?
echo   Bruk Windows-tjenesten ^(skript\tjeneste\installer_tjeneste.ps1^).
echo.
timeout /t 8 >nul

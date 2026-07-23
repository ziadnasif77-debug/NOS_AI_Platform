@echo off
REM ====================================================================
REM  Starter KUN Prefect-UI paa :4200 (overvaaking av treningsflyten).
REM  Selvhelbreder venv hvis nav ble flyttet til en annen sti.
REM ====================================================================
title Prefect :4200
cd /d "%~dp0.."

set "PY=%CD%\.pyruntime\python.exe"
set "PREFECT_HOME=%CD%\.prefect"
REM Prefect 3.7 IGNORERER PREFECT_HOME for disse tre (defaulter til C:\Users\...)
REM -> pin dem eksplisitt til nav, ellers provde serveren aa skrive til C.
set "PREFECT_LOCAL_STORAGE_PATH=%CD%\.prefect\storage"
set "PREFECT_MEMO_STORE_PATH=%CD%\.prefect\memo_store.toml"
set "PREFECT_LOGGING_SETTINGS_PATH=%CD%\.prefect\logging.yml"
set "PIP_CACHE_DIR=%CD%\.cache\pip"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"

REM Prefect-venv baker inn en absolutt sti. Ble nav flyttet -> bygg paa nytt.
set "PREFEKT_OK=0"
if exist ".venv-prefect\Scripts\prefect.exe" (
    .venv-prefect\Scripts\python.exe -c "import prefect" 1>nul 2>nul && set "PREFEKT_OK=1"
)
if "%PREFEKT_OK%"=="0" (
    echo [Prefect] venv mangler/peker feil - bygger paa nytt fra .pyruntime ...
    "%PY%" -m venv --clear .venv-prefect
    .venv-prefect\Scripts\python.exe -m pip install --disable-pip-version-check -q prefect
)
if not exist ".venv-prefect\Scripts\prefect.exe" (
    echo [FEIL] Klarte ikke aa bygge Prefect-venv ^(trenger internett for
    echo        'pip install prefect'^). API-en kjorer uansett uten Prefect.
    if not defined NAV_SKJULT pause
    exit /b 1
)

echo Starter Prefect-UI paa http://127.0.0.1:4200 ...
.venv-prefect\Scripts\prefect.exe server start --host 127.0.0.1 --port 4200

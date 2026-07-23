@echo off
REM ====================================================================
REM  Starter KUN Label Studio paa :8080 (menneskelig korrektur/annotering).
REM  Data lagres i nav\data\label-studio (folger en mappe-kopi).
REM  Valgfri tjeneste ? dokument-API-et virker uten den.
REM ====================================================================
title Label Studio :8080
cd /d "%~dp0.."

set "PY=%CD%\.pyruntime\python.exe"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
set "LABEL_STUDIO_BASE_DATA_DIR=%CD%\data\label-studio"
set "LABEL_STUDIO_PORT=8080"
REM Vis dokumentbildene som auto-gjennomgangen legger i data\gjennomgang
REM (URL-ene /data/local-files/?d=bilder/... peker relativt til roten under).
set "LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true"
set "LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT=%CD%\data\gjennomgang"
if exist "%~dp0lokal_env.bat" call "%~dp0lokal_env.bat"

if not exist "%PY%" (
    echo [FEIL] Fant ikke prosjekt-Python: %PY%
    if not defined NAV_SKJULT pause
    exit /b 1
)
if not exist "data\label-studio" mkdir "data\label-studio"

echo Starter Label Studio paa http://127.0.0.1:8080 ...
echo   (data-katalog: %LABEL_STUDIO_BASE_DATA_DIR%)
"%PY%" skript\kjor_label_studio.py

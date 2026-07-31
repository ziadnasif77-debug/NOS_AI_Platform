@echo off
REM ====================================================================
REM  Nullstiller passordet til en Label Studio-bruker.
REM  Du skriver det nye passordet selv, skjult - det vises aldri og
REM  lagres ingen steder. Ma kjores i et VANLIG vindu (ikke skjult),
REM  siden den spor deg om passordet.
REM ====================================================================
title Nullstill Label Studio-passord
cd /d "%~dp0.."

set "PY=%CD%\.pyruntime\python.exe"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
REM Samme datakatalog som start_label_studio.bat. Uten denne gaar
REM kommandoen mot en HELT ANNEN base i brukerprofilen paa C:.
set "LABEL_STUDIO_BASE_DATA_DIR=%CD%\data\label-studio"

if not exist "%PY%" (
    echo [FEIL] Fant ikke prosjekt-Python: %PY%
    pause
    exit /b 1
)

"%PY%" skript\nullstill_ls_passord.py %*
echo.
echo Ferdig. Logg inn paa http://127.0.0.1:8080 med det nye passordet.
pause

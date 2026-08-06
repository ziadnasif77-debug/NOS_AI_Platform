@echo off
REM ====================================================================
REM  Starter vakthunden, som starter og OVERVAAKER dokument-APIet.
REM  Doer serveren, startes den paa nytt - og EXITKODEN skrives til
REM  data\loggerakthund.log. Uten den ga to doegn med krasj null
REM  informasjon aa feilsoke paa.
REM ====================================================================
cd /d "%~dp0.."

set "PY=%CD%\.pyruntime\python.exe"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
if "%BOREALIS_KONTEKST%"=="" set "BOREALIS_KONTEKST=4096"
if exist "%~dp0lokal_env.bat" call "%~dp0lokal_env.bat"

if not exist "%PY%" (
    echo [FEIL] Fant ikke prosjekt-Python: %PY%
    if not defined NAV_SKJULT pause
    exit /b 1
)

echo Vakthunden holder APIet oppe. Logg: data\loggerakthund.log
"%PY%" skriptakthund.py

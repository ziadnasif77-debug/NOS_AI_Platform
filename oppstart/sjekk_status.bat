@echo off
REM ====================================================================
REM  Viser status for alle NAV-tjenester (nyttig naar de kjorer skjult).
REM ====================================================================
title NAV status
cd /d "%~dp0.."

echo Sjekker tjenester ...
echo.
powershell -NoProfile -Command "function T($u){try{(Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 3).StatusCode}catch{'NEDE'}}; 'API          :8600   ' + (T 'http://127.0.0.1:8600/hjelp'); 'Prefect      :4200   ' + (T 'http://127.0.0.1:4200/api/health'); 'Label Studio :8080   ' + (T 'http://127.0.0.1:8080/')"
echo.
echo   (200 = kjorer.  NEDE = ikke startet / krasjet - se loggene:)
echo   data\logger\oppstart_api.log  oppstart_prefect.log  oppstart_label_studio.log
echo.
pause

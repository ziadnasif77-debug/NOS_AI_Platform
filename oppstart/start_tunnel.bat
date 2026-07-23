@echo off
REM ====================================================================
REM  Starter cloudflared-tunnelen -> offentlig lenke til API-et (:8600).
REM  Start API-et FORST (start_api.bat eller start_alt.bat).
REM ====================================================================
title cloudflared tunnel
cd /d "%~dp0.."

if not exist "%~dp0..\cloudflared.exe" (
    echo [FEIL] Fant ikke cloudflared.exe i nav-mappa.
    if not defined NAV_SKJULT pause
    exit /b 1
)

echo   MERK: API-et er AAPENT uten X-API-Key med mindre du har satt
echo   API_NOKKEL som maskin-miljovariabel ^(setx /M API_NOKKEL ...^).
echo.
echo Starter tunnel mot http://localhost:8600 ...
echo Den offentlige lenken ^(https://....trycloudflare.com^) vises under:
echo.
REM Full sti (ikke bare navnet): i skjult modus nekter cmd aa soke i
REM gjeldende mappe ("is not recognized"-feilen).
"%~dp0..\cloudflared.exe" tunnel --url http://localhost:8600
if not defined NAV_SKJULT pause

@echo off
REM ====================================================================
REM  Starter ALT: dokument-API (:8600) + Prefect (:4200) + Label Studio
REM  (:8080), hver i sitt eget vindu. Gjenbruker de enkelte starterne.
REM  (Tunnel startes separat med start_tunnel.bat.)
REM ====================================================================
cd /d "%~dp0.."

echo ================================================================
echo   NAV - starter ALLE tjenester (hver i eget vindu)
echo ================================================================
echo.

start "NAV dokument-API :8600" cmd /k "%~dp0start_api.bat"
start "Prefect :4200"          cmd /k "%~dp0start_prefect.bat"
start "Label Studio :8080"     cmd /k "%~dp0start_label_studio.bat"

echo   Startet:
echo     API:          http://127.0.0.1:8600/hjelp   (+ /dokumentasjon)
echo     Prefect:      http://127.0.0.1:4200
echo     Label Studio: http://127.0.0.1:8080
echo.
echo   Ekstern tilgang? Kjor start_tunnel.bat i tillegg.
echo   Stoppe alt?      Kjor stopp_alt.bat.
echo.
timeout /t 8 >nul

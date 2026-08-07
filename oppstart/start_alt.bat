@echo off
REM ====================================================================
REM  Starter ALT i BAKGRUNNEN (skjulte vinduer): dokument-API (:8600) +
REM  Prefect (:4200) + Label Studio (:8080). Ingen vinduer aa lukke ved
REM  et uhell. Utskrift logges til data\logger\oppstart_*.log.
REM    Status:  sjekk_status.bat      Stopp:  stopp_alt.bat
REM  (Vil du SE en tjeneste live: dobbeltklikk dens start_*.bat alene.)
REM ====================================================================
cd /d "%~dp0.."
if not exist "data\logger" mkdir "data\logger"

REM Forteller de enkelte starterne at de kjorer skjult (ingen pause).
set "NAV_SKJULT=1"
REM Lokale hemmeligheter (arves av tjenestene som startes under).
if exist "%~dp0lokal_env.bat" call "%~dp0lokal_env.bat"

echo ================================================================
echo   NAV - starter ALLE tjenester SKJULT i bakgrunnen ...
echo ================================================================

REM Vakthunden, ikke API-et direkte: den starter serveren, helsesjekker
REM /hjelp og skriver EXITKODEN naar den doer. Ingen oppstartsvei skal
REM lenger la serveren kjoere uovervaaket - to doegn med krasj ga null
REM informasjon nettopp fordi ingen fanget avslutningen.
wscript //nologo "%~dp0_skjult.vbs" "%~dp0start_api_med_vakthund.bat" "%CD%\data\logger\oppstart_api.log"
wscript //nologo "%~dp0_skjult.vbs" "%~dp0start_prefect.bat"      "%CD%\data\logger\oppstart_prefect.log"
wscript //nologo "%~dp0_skjult.vbs" "%~dp0start_label_studio.bat" "%CD%\data\logger\oppstart_label_studio.log"

echo.
echo   Startet (skjult - ingen vinduer):
echo     API:          http://127.0.0.1:8600/hjelp   (+ /dokumentasjon)
echo     Prefect:      http://127.0.0.1:4200
echo     Label Studio: http://127.0.0.1:8080
echo.
echo   Sjekk status:   oppstart\sjekk_status.bat
echo   Stopp alt:      oppstart\stopp_alt.bat
echo   Logger:         data\logger\oppstart_*.log
echo.
echo   (API-et trenger ~30-60 sek paa aa laste Borealis.)
timeout /t 10 >nul

@echo off
setlocal
REM ====================================================================
REM  NAV Dokument-API - tjeneste-wrapper
REM  Kjores av Windows Task Scheduler (se installer_tjeneste.ps1).
REM  Scheduler starter denne ved oppstart og paa nytt hvis den krasjer.
REM  Konfigurasjon settes som MASKIN-miljovariabler (setx /M ...),
REM  slik at SYSTEM-kontoen ser dem. Se LES_MEG.md.
REM ====================================================================

REM Gaa til prosjektroten (to nivaaer opp fra denne .bat-fila).
cd /d "%~dp0..\.."

REM Sorg for at loggmappa finnes.
if not exist "data\logger" mkdir "data\logger"

REM Krev at Python finnes paa PATH.
where python >nul 2>&1
if errorlevel 1 (
    >>"data\logger\dokument_api.feil.log" echo [%date% %time%] [FEIL] Python ikke funnet paa PATH. Tjenesten kan ikke starte.
    exit /b 1
)

REM Standardport hvis ikke satt i maskinmiljoet.
if "%DOKUMENT_API_PORT%"=="" set DOKUMENT_API_PORT=8600

>>"data\logger\dokument_api.ut.log" echo [%date% %time%] Starter dokument_api paa port %DOKUMENT_API_PORT% ...

REM Kjor serveren i forgrunn. Naar prosessen avslutter, tar Scheduler over:
REM  - krasj (kode <> 0)  -> Scheduler restarter (RestartCount/RestartInterval)
REM  - manuell stopp (/end) -> Scheduler restarter IKKE
python -u "skript\dokument_api.py" 1>>"data\logger\dokument_api.ut.log" 2>>"data\logger\dokument_api.feil.log"
set KODE=%errorlevel%

>>"data\logger\dokument_api.feil.log" echo [%date% %time%] dokument_api avsluttet med kode %KODE%.
exit /b %KODE%

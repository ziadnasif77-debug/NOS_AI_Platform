@echo off
setlocal
REM ====================================================================
REM  NAV - ukentlig treningsjobb (kjores av Task Scheduler).
REM  GPU-en (8 GB) har ikke plass til bade serveren OG trening samtidig,
REM  sa vi:
REM    1) stopper serveren  -> frigjor GPU
REM    2) kjorer treningslopet (eksporter -> finjuster, sporet i MLflow)
REM    3) starter serveren igjen -> omstarten laster den nytrente modellen
REM  Steg 1 og 3 er best-effort: kjorer ikke serveren som tjeneste, gjor
REM  de ingenting (og du bor stoppe en manuelt startet server selv forst).
REM ====================================================================
cd /d "%~dp0..\.."
if not exist "data\logger" mkdir "data\logger"

where python >nul 2>&1
if errorlevel 1 (
    >>"data\logger\trening.feil.log" echo [%date% %time%] [FEIL] Python ikke funnet paa PATH.
    exit /b 1
)

REM 1) Frigjor GPU: stopp serveren hvis den kjorer som tjeneste.
schtasks /end /tn "NAV-Dokument-API" >nul 2>&1

REM 2) Kjor treningslopet.
>>"data\logger\trening.ut.log" echo [%date% %time%] Starter treningslop ...
python -u "skript\kjor_treningslop.py" 1>>"data\logger\trening.ut.log" 2>>"data\logger\trening.feil.log"
set KODE=%errorlevel%
>>"data\logger\trening.ut.log" echo [%date% %time%] Treningslop avsluttet med kode %KODE%.

REM 3) Start serveren igjen (laster den nytrente modellen).
schtasks /run /tn "NAV-Dokument-API" >nul 2>&1

exit /b %KODE%

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

REM ALT skal ligge i nav-mappa (ikke C): pek EasyOCR/HF/cache hit, saa selv
REM SYSTEM-kontoen (som ikke arver bruker-setx) bruker nav. Python-pakkene
REM finnes nav-lokalt via .pyruntime\Lib\site-packages\nav_pakker.pth.
set "EASYOCR_MODULE_PATH=%CD%\.EasyOCR"
set "HF_HOME=%CD%\.cache\huggingface"
set "PIP_CACHE_DIR=%CD%\.cache\pip"
set "PREFECT_HOME=%CD%\.prefect"
REM Kun nav-lokale pakker: ignorer %APPDATA%\Python -> ingen C-binding. UTF-8-trygg.
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
REM Lokale hemmeligheter (Label Studio-token -> auto-gjennomgang PAA).
if exist "%CD%\oppstart\lokal_env.bat" call "%CD%\oppstart\lokal_env.bat"

REM Prosjektets egen Python i nav (.pyruntime), ikke system-Python paa C.
set "PY=%CD%\.pyruntime\python.exe"

REM Sorg for at loggmappa finnes.
if not exist "data\logger" mkdir "data\logger"

REM Krev at prosjekt-Python finnes.
if not exist "%PY%" (
    >>"data\logger\dokument_api.feil.log" echo [%date% %time%] [FEIL] Fant ikke %PY%. Tjenesten kan ikke starte.
    exit /b 1
)

REM Standardport hvis ikke satt i maskinmiljoet.
if "%DOKUMENT_API_PORT%"=="" set DOKUMENT_API_PORT=8600

>>"data\logger\dokument_api.ut.log" echo [%date% %time%] Starter dokument_api paa port %DOKUMENT_API_PORT% ...

REM Kjor VAKTHUNDEN, ikke serveren direkte (R142).
REM
REM Denne .bat-en startet tidligere dokument_api.py rett. Da hoppet hele
REM oppstartsveien over vakthunden - og den finnes nettopp fordi to dogn
REM med krasj ga NULL informasjon (R122): den skriver EXITKODEN, som pa
REM Windows sier om det var et nativt krasj (0xC0000005) eller om noen
REM drepte prosessen (0xFFFFFFFF).
REM
REM Viktigere: Scheduler restarter bare en prosess som HAR AVSLUTTET. En
REM HENGT server lever videre, og da gjor Scheduler ingenting. Vakthunden
REM helsesjekker /hjelp og restarter ogsa nar prosessen henger (R123) -
REM "en hengt prosess er like ubrukelig som en dod".
REM
REM Starter panelet ogsa en vakthund, tar den forste lasen (R141) og den
REM andre avslutter pent. De to veiene kolliderer altsa ikke.
REM
REM Nar vakthunden selv avslutter, tar Scheduler over:
REM  - krasj (kode <> 0)  -> Scheduler restarter (RestartCount/RestartInterval)
REM  - manuell stopp (/end) -> Scheduler restarter IKKE
REM --vent: holder oppgaven i live om panelet tilfeldigvis rakk aa starte
REM sin vakthund forst, og tar over nar den forsvinner. Uten den ville
REM oppgaven avsluttet med 0, Scheduler regnet den som ferdig, og
REM serveren statt uten tilsyn til neste omstart.
"%PY%" -u "skript\vakthund.py" --vent 1>>"data\logger\dokument_api.ut.log" 2>>"data\logger\dokument_api.feil.log"
set KODE=%errorlevel%

>>"data\logger\dokument_api.feil.log" echo [%date% %time%] dokument_api avsluttet med kode %KODE%.
exit /b %KODE%

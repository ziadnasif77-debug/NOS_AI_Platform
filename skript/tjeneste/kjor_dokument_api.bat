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

REM ALT skal ligge paa D:\nav (ikke C): pek EasyOCR/HF/cache hit, saa selv
REM SYSTEM-kontoen (som ikke arver bruker-setx) bruker D. Python-pakkene
REM finnes uansett via junction paa standard user-site-stien.
set "EASYOCR_MODULE_PATH=%CD%\.EasyOCR"
set "HF_HOME=%CD%\.cache\huggingface"
set "PIP_CACHE_DIR=%CD%\.cache\pip"
set "PREFECT_HOME=%CD%\.prefect"

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

REM Kjor serveren i forgrunn. Naar prosessen avslutter, tar Scheduler over:
REM  - krasj (kode <> 0)  -> Scheduler restarter (RestartCount/RestartInterval)
REM  - manuell stopp (/end) -> Scheduler restarter IKKE
"%PY%" -u "skript\dokument_api.py" 1>>"data\logger\dokument_api.ut.log" 2>>"data\logger\dokument_api.feil.log"
set KODE=%errorlevel%

>>"data\logger\dokument_api.feil.log" echo [%date% %time%] dokument_api avsluttet med kode %KODE%.
exit /b %KODE%

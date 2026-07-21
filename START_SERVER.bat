@echo off
chcp 65001 >nul
title NAV dokument-API + tunnel
cd /d "%~dp0"

REM Prosjektets EGEN Python i nav (.pyruntime) — ingen system-Python noodvendig.
set "PY=%CD%\.pyruntime\python.exe"
set "EASYOCR_MODULE_PATH=%CD%\.EasyOCR"
set "HF_HOME=%CD%\.cache\huggingface"
set "PIP_CACHE_DIR=%CD%\.cache\pip"
set "PREFECT_HOME=%CD%\.prefect"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
if "%BOREALIS_KONTEKST%"=="" set "BOREALIS_KONTEKST=4096"

echo ============================================================
echo   NAV DOKUMENT-API - STARTER ALT
echo ============================================================
echo.

REM --- 1) Sjekk at prosjekt-Python finnes ---
if not exist "%PY%" (
    echo [FEIL] Fant ikke prosjekt-Python: %PY%
    echo        Sjekk at .pyruntime ligger i nav-mappa (kopier HELE mappa).
    echo.
    pause
    exit /b 1
)

REM --- 2) Stopp eventuell gammel server pa port 8600 ---
echo [1/4] Stopper eventuell gammel server pa port 8600 ...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8600 " ^| findstr LISTENING') do (
    taskkill /F /PID %%p >nul 2>&1
)

REM --- 3) Start API-serveren i eget vindu ---
echo [2/4] Starter dokument-API (eget vindu) ...
start "NAV dokument-API" cmd /k "%PY%" "%~dp0skript\dokument_api.py"

REM --- 4) Vent til serveren svarer / Borealis er klar ---
echo [3/4] Venter pa at Borealis lastes (kan ta 1-2 min forste gang) ...
set /a forsok=0
:vent
timeout /t 3 /nobreak >nul
set /a forsok+=1
for /f %%s in ('"%PY%" "%~dp0skript\_vent_klar.py" 2^>nul') do set status=%%s
if "%status%"=="klar" goto klar
if %forsok% GEQ 60 (
    echo [ADVARSEL] Borealis ble ikke klar innen 3 min - starter tunnelen likevel.
    echo            /analyser virker allerede; /spor blir klar nar modellen er lastet.
    goto tunnel
)
goto vent

:klar
echo        Borealis er klar.

REM --- 5) Start cloudflare-tunnelen ---
:tunnel
echo [4/4] Starter cloudflare-tunnel (offentlig lenke) ...
echo.
echo ============================================================
echo   ALT KJORER. Se tunnel-vinduet for den offentlige lenken
echo   (raden "https://....trycloudflare.com").
echo   Lokalt:  http://localhost:8600/dokumentasjon
echo.
echo   MERK: API-et er AAPENT uten X-API-Key med mindre du setter
echo   API_NOKKEL som maskin-miljovariabel FOR start (setx /M API_NOKKEL ...).
echo   LUKK DETTE og de andre vinduene for a stoppe alt.
echo ============================================================
echo.
"%~dp0cloudflared.exe" tunnel --url http://localhost:8600
pause

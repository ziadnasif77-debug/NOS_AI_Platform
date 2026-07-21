@echo off
REM ====================================================================
REM  Starter KUN dokument-API-et paa :8600 (OCR + Borealis).
REM  Bruker prosjektets egen .pyruntime. Kjor fra nav\oppstart\.
REM ====================================================================
title NAV dokument-API :8600
cd /d "%~dp0.."

set "PY=%CD%\.pyruntime\python.exe"
set "EASYOCR_MODULE_PATH=%CD%\.EasyOCR"
set "HF_HOME=%CD%\.cache\huggingface"
set "PIP_CACHE_DIR=%CD%\.cache\pip"
set "PREFECT_HOME=%CD%\.prefect"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"
if "%BOREALIS_KONTEKST%"=="" set "BOREALIS_KONTEKST=4096"

if not exist "%PY%" (
    echo [FEIL] Fant ikke prosjekt-Python: %PY%
    echo        Kopierte du HELE nav-mappa ^(inkl. .pyruntime^)?
    pause
    exit /b 1
)

echo Starter dokument-API paa http://127.0.0.1:8600/hjelp ...
"%PY%" skript\dokument_api.py

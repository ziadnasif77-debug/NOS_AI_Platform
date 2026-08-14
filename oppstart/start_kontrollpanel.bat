@echo off
REM ====================================================================
REM  Aapner kontrollpanel-GUI-et (api_klient_gui.py): start/stopp av alle
REM  tjenester + live GPU/CPU/RAM-grafer + dokumentklienten. Faner:
REM  Kontrollpanel, Flytskjema, Innsyn, Trening, MODELLER (bytt
REM  spraakmodell med port og angreknapp), Dokument, Operasjoner,
REM  Spoer, Storjobb, Serverinfo. Bruker pythonw (ingen konsollvindu).
REM ====================================================================
cd /d "%~dp0.."

set "PYW=%CD%\.pyruntime\pythonw.exe"
if not exist "%PYW%" set "PYW=%CD%\.pyruntime\python.exe"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"

if not exist "%PYW%" (
    echo [FEIL] Fant ikke prosjekt-Python i .pyruntime.
    pause
    exit /b 1
)

start "" "%PYW%" skript\api_klient_gui.py

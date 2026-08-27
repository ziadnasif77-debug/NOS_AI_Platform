@echo off
REM Lasttest (§21/§26) — Locust ligger i last\pakker, ikke i
REM produksjonsruntimen: 17 pakker med kompilerte utvidelser hoerer
REM ikke hjemme i en mappe som skal kopieres til en hvilken som helst
REM server (§1).
REM
REM   kjor_last.bat            100 brukere, 3 minutter
REM   kjor_last.bat 20 60s     20 brukere, 1 minutt
setlocal
cd /d "%~dp0.."
set BRUKERE=%1
if "%BRUKERE%"=="" set BRUKERE=100
set TID=%2
if "%TID%"=="" set TID=3m
REM Kun nav-lokale pakker: ignorer %APPDATA%\Python -> ingen C-binding.
set "PYTHONNOUSERSITE=1"
set PYTHONPATH=%CD%\last\pakker
.pyruntime\python.exe -m locust -f last\locustfile.py --headless ^
  --users %BRUKERE% --spawn-rate 10 --run-time %TID% ^
  --host http://127.0.0.1:8600 --only-summary
endlocal

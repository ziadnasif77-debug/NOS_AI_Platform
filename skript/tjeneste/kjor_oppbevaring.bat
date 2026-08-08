@echo off
REM ====================================================================
REM  Handhever oppbevaringsfristen paa data/gjennomgang (R173).
REM
REM  Rydderutinen fantes, men INGEN kjorte den: installer_trening.ps1
REM  registrerte bare treningsjobben, og kjor_trening.bat kaller ikke
REM  ryddingen. En oppbevaringspolicy ingen utforer er ikke en policy —
REM  og README presenterte den som en GDPR-egenskap ved systemet.
REM
REM  KJORER MED --slett. Torrkjoring som planlagt jobb ville vaert det
REM  verste av alt: en logg full av «ville slettet ...» som ser ut som
REM  arbeid, mens filene blir liggende.
REM
REM  Rekkefolgen er viktig: eksporten MAA ha kopiert bildene inn i
REM  data/finjustering/bilder (R170) for koen tommes. Den gjor det siden
REM  R170, men gamle rader kan fortsatt peke inn i koen — kjor derfor
REM  eksporten minst en gang for denne jobben settes opp.
REM ====================================================================
cd /d "%~dp0..\.."

if exist "oppstart\lokal_env.bat" call "oppstart\lokal_env.bat"

set "PY=.pyruntime\python.exe"
if not exist "%PY%" set "PY=python"

if not exist "data\logger" mkdir "data\logger"

echo [%DATE% %TIME%] starter oppbevaringsrydding >> "data\logger\oppbevaring.ut.log"

"%PY%" skript\rydd_gjennomgang.py --slett >> "data\logger\oppbevaring.ut.log" 2>> "data\logger\oppbevaring.feil.log"
set KODE=%ERRORLEVEL%

echo [%DATE% %TIME%] ferdig, exitkode %KODE% >> "data\logger\oppbevaring.ut.log"
exit /b %KODE%

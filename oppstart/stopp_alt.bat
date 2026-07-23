@echo off
REM ====================================================================
REM  Stopper alle NAV-tjenester: porter 8600 (API), 4200 (Prefect),
REM  8080 (Label Studio) + cloudflared-tunnelen. Virker baade for
REM  skjulte (start_alt.bat) og synlige (enkelt-start) tjenester.
REM ====================================================================
echo Stopper NAV-tjenester (8600 / 4200 / 8080 + cloudflared) ...

for %%P in (8600 4200 8080) do (
    for /f "tokens=5" %%q in ('netstat -ano ^| findstr ":%%P " ^| findstr LISTENING') do (
        taskkill /F /T /PID %%q >nul 2>&1
    )
)
taskkill /F /IM cloudflared.exe >nul 2>&1

REM Lukk evt. synlige cmd-vinduer som staar igjen (startet med cmd /k).
taskkill /F /IM cmd.exe /FI "WINDOWTITLE eq NAV dokument-API*" >nul 2>&1
taskkill /F /IM cmd.exe /FI "WINDOWTITLE eq Prefect*"          >nul 2>&1
taskkill /F /IM cmd.exe /FI "WINDOWTITLE eq Label Studio*"     >nul 2>&1

echo Ferdig - alle tjenester stoppet.
timeout /t 3 >nul

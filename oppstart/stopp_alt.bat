@echo off
REM ====================================================================
REM  Stopper alle NAV-tjenester: porter 8600 (API), 4200 (Prefect),
REM  8080 (Label Studio) + cloudflared-tunnelen. Virker baade for
REM  skjulte (start_alt.bat) og synlige (enkelt-start) tjenester.
REM ====================================================================
echo Stopper NAV-tjenester (8600 / 4200 / 8080 + cloudflared) ...

REM VAKTHUNDEN FOERST. Den holder ingen port og har ingen vindustittel,
REM saa verken port-loekka under eller tittelfiltrene nederst traff den.
REM Foelgen var at "Stopp alt" meldte ferdig, og vakthunden startet
REM API-et igjen ~20 sekunder senere - som ser ut som at serveren
REM "starter av seg selv".
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name LIKE '%%python%%'\" | Where-Object { $_.CommandLine -like '*vakthund.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

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

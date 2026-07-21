@echo off
REM ====================================================================
REM  Stopper alle NAV-tjenester: porter 8600 (API), 4200 (Prefect),
REM  8080 (Label Studio) + cloudflared-tunnelen.
REM ====================================================================
echo Stopper NAV-tjenester (8600 / 4200 / 8080 + cloudflared) ...

for %%P in (8600 4200 8080) do (
    for /f "tokens=5" %%q in ('netstat -ano ^| findstr ":%%P " ^| findstr LISTENING') do (
        taskkill /F /PID %%q >nul 2>&1
    )
)
taskkill /F /IM cloudflared.exe >nul 2>&1

echo Ferdig - alle tjenester stoppet.
timeout /t 3 >nul

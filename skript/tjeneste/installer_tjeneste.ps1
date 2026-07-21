#Requires -RunAsAdministrator
<#
    Registrerer NAV Dokument-API som en planlagt oppgave i Windows:
      - starter automatisk ved maskinoppstart (eller ved paalogging med -VedInnlogging)
      - restarter automatisk hvis serveren krasjer (opptil 999 ganger, 1 min mellom)
      - kjorer uten at noen maa vaere paalogget (SYSTEM), ELLER i din egen
        brukersesjon med -VedInnlogging (tryggest for GPU hvis SYSTEM ikke
        naar skjermkortet)

    Kjor fra en PowerShell startet som administrator:
        powershell -ExecutionPolicy Bypass -File installer_tjeneste.ps1
        powershell -ExecutionPolicy Bypass -File installer_tjeneste.ps1 -VedInnlogging
#>
param([switch]$VedInnlogging)

$ErrorActionPreference = "Stop"

$navn    = "NAV-Dokument-API"
$rot     = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$wrapper = Join-Path $PSScriptRoot "kjor_dokument_api.bat"

if (-not (Test-Path $wrapper)) {
    throw "Fant ikke wrapper-skriptet: $wrapper"
}

$handling = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument ('/c "{0}"' -f $wrapper) -WorkingDirectory $rot

$innst = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

if ($VedInnlogging) {
    $bruker   = "$env:USERDOMAIN\$env:USERNAME"
    $utloser  = New-ScheduledTaskTrigger -AtLogOn -User $bruker
    $prinsipp = New-ScheduledTaskPrincipal -UserId $bruker -LogonType Interactive -RunLevel Highest
    $modus    = "ved paalogging av $bruker (egen sesjon - tryggest for GPU)"
} else {
    $utloser  = New-ScheduledTaskTrigger -AtStartup
    $prinsipp = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $modus    = "ved maskinoppstart som SYSTEM (ingen paalogging noedvendig)"
}

Register-ScheduledTask -TaskName $navn -Action $handling -Trigger $utloser `
    -Principal $prinsipp -Settings $innst -Force | Out-Null

Write-Host ""
Write-Host "  Registrert: $navn"
Write-Host "  Modus:      $modus"
Write-Host ""
Write-Host "  Start naa:  schtasks /run   /tn `"$navn`""
Write-Host "  Stopp:      schtasks /end   /tn `"$navn`""
Write-Host "  Status:     schtasks /query /tn `"$navn`" /v /fo LIST"
Write-Host "  Avinstall:  powershell -ExecutionPolicy Bypass -File avinstaller_tjeneste.ps1"
Write-Host "  Logg:       $rot\data\logger\dokument_api.ut.log (+ .feil.log)"
Write-Host ""
Write-Host "  Serveren svarer paa http://127.0.0.1:8600/hjelp naar den er klar."
Write-Host ""

#Requires -RunAsAdministrator
<#
    Planlegger treningsløkken til å kjøre AUTOMATISK ukentlig (standard:
    søndag kl. 03:00). Jobben stopper serveren under trening (frigjør
    GPU) og starter den igjen etterpå — se kjor_trening.bat.

    Kjør fra en PowerShell startet som administrator:
        powershell -ExecutionPolicy Bypass -File installer_trening.ps1
        powershell -ExecutionPolicy Bypass -File installer_trening.ps1 -Dag Saturday -Klokke 02:00

    MERK GPU: jobben kjører som SYSTEM. Ser ikke SYSTEM skjermkortet på
    ditt oppsett (samme symptom som for serveren), vil treningen feile —
    kjør da `make trening` manuelt i din egen sesjon i stedet.
#>
param(
    [ValidateSet("Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday")]
    [string]$Dag = "Sunday",
    [string]$Klokke = "03:00"
)

$ErrorActionPreference = "Stop"

$navn    = "NAV-Trening-ukentlig"
$rot     = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$wrapper = Join-Path $PSScriptRoot "kjor_trening.bat"

if (-not (Test-Path $wrapper)) {
    throw "Fant ikke wrapper-skriptet: $wrapper"
}

$naar = [datetime]("2000-01-01 " + $Klokke)   # kun klokkeslettet brukes

$handling = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument ('/c "{0}"' -f $wrapper) -WorkingDirectory $rot
$utloser  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Dag -At $naar
$prinsipp = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$innst    = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6)

Register-ScheduledTask -TaskName $navn -Action $handling -Trigger $utloser `
    -Principal $prinsipp -Settings $innst -Force | Out-Null

Write-Host ""
Write-Host "  Planlagt: $navn - hver $Dag kl. $Klokke"
Write-Host ""
Write-Host "  Test nå:  schtasks /run   /tn `"$navn`""
Write-Host "  Status:   schtasks /query /tn `"$navn`" /v /fo LIST"
Write-Host "  Fjern:    powershell -ExecutionPolicy Bypass -File avinstaller_tjeneste.ps1"
Write-Host "  Logg:     $rot\data\logger\trening.ut.log (+ .feil.log)"
Write-Host "  Sporing:  mlflow ui --backend-store-uri $rot\data\mlflow"
Write-Host ""

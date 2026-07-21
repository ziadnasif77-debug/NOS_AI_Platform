#Requires -RunAsAdministrator
# Fjerner de planlagte oppgavene (server + ukentlig trening). Kjor som
# administrator:
#     powershell -ExecutionPolicy Bypass -File avinstaller_tjeneste.ps1
$ErrorActionPreference = "SilentlyContinue"

foreach ($navn in @("NAV-Dokument-API", "NAV-Trening-ukentlig")) {
    schtasks /end /tn $navn > $null 2>&1
    Unregister-ScheduledTask -TaskName $navn -Confirm:$false
    Write-Host "Fjernet oppgaven: $navn"
}
Write-Host "(Loggene i data\logger beholdes.)"

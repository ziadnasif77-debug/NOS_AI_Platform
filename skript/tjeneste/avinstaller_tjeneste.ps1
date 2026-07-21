#Requires -RunAsAdministrator
# Fjerner den planlagte oppgaven NAV-Dokument-API. Kjor som administrator:
#     powershell -ExecutionPolicy Bypass -File avinstaller_tjeneste.ps1
$ErrorActionPreference = "SilentlyContinue"

$navn = "NAV-Dokument-API"

# Stopp den hvis den kjorer, og avregistrer.
schtasks /end /tn $navn > $null 2>&1
Unregister-ScheduledTask -TaskName $navn -Confirm:$false

Write-Host "Fjernet oppgaven: $navn (loggene i data\logger beholdes)."

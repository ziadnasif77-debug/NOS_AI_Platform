# ══════════════════════════════════════════════════════════════════
# Simulerer UiPath-robotens flyt mot NAV Archive-API-et:
#   last opp → poll → hent felter
# Kjør denne FØR du bygger UiPath-workflowen — er den grønn,
# vil samme kontrakt fungere i UiPath.
#
# Bruk:  .\uipath\test_robotflyt.ps1 -FilSti .\test.pdf
# ══════════════════════════════════════════════════════════════════
param(
    [Parameter(Mandatory = $true)][string]$FilSti,
    [string]$ApiUrl = "http://localhost:8000",
    [string]$ApiNokkel = $env:API_NOKKEL,
    [int]$TidsavbruddSekunder = 300
)

$ErrorActionPreference = "Stop"
$hoder = @{ "X-API-Key" = $ApiNokkel }

Write-Host "1) Laster opp $FilSti ..."
$svar = Invoke-RestMethod -Uri "$ApiUrl/last-opp/" -Method Post -Headers $hoder `
    -Form @{ fil = Get-Item $FilSti }
$jobbId = $svar.job_id
Write-Host "   job_id: $jobbId (state: $($svar.state))"

Write-Host "2) Poller /jobb/$jobbId ..."
$frist = (Get-Date).AddSeconds($TidsavbruddSekunder)
do {
    Start-Sleep -Seconds 2
    $status = Invoke-RestMethod -Uri "$ApiUrl/jobb/$jobbId" -Headers $hoder
    Write-Host "   state: $($status.state)"
    if ((Get-Date) -gt $frist) { throw "Tidsavbrudd — siste tilstand: $($status.state)" }
} while ($status.state -ne "DONE" -and $status.state -ne "FAILED")

if ($status.state -eq "FAILED") { throw "Behandling feilet — sjekk $ApiUrl/audit/$jobbId" }

Write-Host "3) Henter felter ..."
$felter = Invoke-RestMethod -Uri "$ApiUrl/resultat/$jobbId/felter" -Headers $hoder
$felter | ConvertTo-Json -Depth 5

Write-Host ""
Write-Host "Beslutning: $($felter.beslutning)"
Write-Host "Navn:       $($felter.felter.navn)"
Write-Host "Ytelse:     $($felter.felter.ytelse)"
Write-Host "ROBOTFLYT OK — samme kontrakt fungerer i UiPath."

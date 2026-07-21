# Skalering til virksomhetsvolum — beslutningsgrunnlag

> **STATUS: FORSLAG / BESLUTNINGSGRUNNLAG — IKKE VEDTATT.**
> Volumet (titusener dokumenter/dag) er **IKKE bekreftet**. Hele
> skaleringssporet er betinget av det: bekreftes det ikke, er dagens
> monolitt riktig arkitektur. Det gjenbrukte distribuerte systemet
> (slettet i `7b2c2cd`) er **referanse/prior art**, ikke ny baseline,
> før volumet er bekreftet.

Dette er forarbeidet til en eventuell arkitekturendring, produsert etter
en engineering-brief om å skalere NAV Dokument-API. Ingen kode er endret.

## Dokumenter

| Fil | Innhold |
|-----|---------|
| [ADR-001-gjenbruk-vs-nybygg.md](ADR-001-gjenbruk-vs-nybygg.md) | Hvilke slettede komponenter gjenbrukes vs. bygges på nytt |
| [ADR-002-ko-abstraksjon.md](ADR-002-ko-abstraksjon.md) | Køabstraksjon som dekker både container-prod og luftgap |
| [revisjon-gjenbrukskode.md](revisjon-gjenbrukskode.md) | Fil-nivå revisjon av gjenbrukskandidatene (før restaurering) |
| [audit-skjema.md](audit-skjema.md) | Audit-record-skjema (§7.4): versjonssporing, immutabilitet, oppbevaring |

## Fase 0 — antakelser (åpne forretningsbeslutninger uthevet)

| Antakelse | Verdi | Status | Låser |
|-----------|-------|--------|-------|
| **Dagsvolum (titusener/dag)** | antatt | 🔴 **UBEKREFTET — TOPP** | Om §3 (skalering) er berettiget i det hele tatt |
| Topp-samtidighet (ikke snitt) | — | 🔴 mangler | GPU-pool-dimensjonering (byrde er bursty) |
| Responstid SLA/SLO per vei | — | 🔴 mangler | Ytelsesbudsjett, kapasitetskjede |
| Maks kø-ventetid ved topp | — | 🔴 mangler | Backpressure- og autoskalerings-terskler |
| Oppetid SLA/SLO | — | 🔴 mangler | N+1-dimensjonering, DR |
| RTO/RPO | — | 🔴 mangler | Katastrofegjenoppretting, backup |
| Oppbevaring (Label Studio + audit) + immutabilitet | — | 🔴 mangler (§6.4) | Audit-skjema, oppbevaringsjobb |
| Lastprofil | bursty | 🟢 svart | Backpressure-design |
| Container/luftgap | blandet | 🟢 svart | Køabstraksjon (ADR-002) |
| Autentiseringsgrense | bak intern gateway | 🟢 svart | Sikkerhet krymper til identitets-videreføring |

**Kjernen er volumet.** Til det er bekreftet, er dette en designstudie,
ikke et byggeprosjekt.

## Avklarte valg (§6)

- **§6.1 Container/luftgap:** blandet — containerisert nettverks-prod
  *og* en separat luftgap-installasjon fra én konfig-styrt kodebase.
- **§6.3 Autentisering:** bak en intern gateway som håndterer authn/z.
  In-app-sikkerhet krymper til å videreføre gateway-identitet inn i
  audit-loggen + rate-limiting som dybdeforsvar.
- **Lastprofil:** bursty/uforutsigbar → durabel kø med backpressure.

## Fortsatt åpent (blokkerer designdokumentet, ikke gjenbruk-beslutningen)

1. **Volumbekreftelse** (linchpin — se over).
2. Fase 0-tall (SLA/SLO, topp-samtidighet, RTO/RPO).
3. §6.4 oppbevaringsvinduer + om audit trenger immutabilitet.

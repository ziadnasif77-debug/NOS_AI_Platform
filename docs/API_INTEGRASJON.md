# API-integrasjon (RPA og eksterne systemer)

API-et er verktøy-nøytralt: alt et eksternt system trenger, er HTTP og
JSON. Ingen SDK, ingen klientbibliotek, ingen verktøyspesifikk kode.

**Selvdokumenterende:** Swagger-UI på `http://<vert>:8000/docs` og
maskinlesbar spesifikasjon på `/openapi.json` — begge åpne uten nøkkel
(de eksponerer kun skjemaet, aldri data). RPA-verktøy som UiPath
(«New Service» → lim inn OpenAPI-URL) og Power Automate importerer
spesifikasjonen direkte og genererer aktiviteter selv.

## Integrasjonsmønsteret (asynkront)

Behandlingen tar sekunder til minutter — klienten skal aldri blokkere:

```
1) POST /last-opp/                 → 202 { dokument_id, job_ids, antall_sider }
2) GET  /dokument/{id}/status      → poll hvert par sekunder til DONE/FAILED
3) GET  /dokument/{id}/felter      → strukturerte felter for hele dokumentet
```

Alle kall autentiseres med `X-API-Key`-header (eller Bearer-token i
OIDC-modus — se README «Sikkerhet og GDPR»).

## Eksempel med curl (fungerer identisk fra ethvert verktøy)

```bash
# 1) Last opp
curl -X POST http://localhost:8000/last-opp/ \
     -H "X-API-Key: $NOKKEL" -F "fil=@soknad.pdf"
# → {"dokument_id": "3e60…", "antall_sider": 10, "state": "QUEUED", …}

# 2) Poll status
curl -H "X-API-Key: $NOKKEL" http://localhost:8000/dokument/3e60…/status
# → {"state": "IN_PROGRESS", "ferdige_sider": 7, "antall_sider": 10, …}

# 3) Hent felter når state == DONE
curl -H "X-API-Key: $NOKKEL" http://localhost:8000/dokument/3e60…/felter
# → {"beslutning": "APPROVED", "felter": {"navn": …, "ytelse": …}, "per_side": […]}
```

## Kontraktsgarantier klienten kan stole på

| Garanti | Betydning for klienten |
|---------|------------------------|
| Idempotent opplasting | Samme fil på nytt (innen 5 min) gir samme `dokument_id` — retry er alltid trygt |
| `409` fra `/felter` før ferdig | Skill «ikke ferdig ennå» fra feil uten å tolke kropper |
| `422` ved ugyldig id, `400` ved korrupt PDF | Valideringsfeil er aldri `500` |
| Aggregert beslutning | `REJECTED > REVIEW > APPROVED` — sjekk `gjennomgang.kreves` før data sendes videre til fagsystem |
| Statuskoder propageres | Feil nedstrøms kommer som riktige HTTP-koder, ikke `200` med feilkropp |

## Robusthetsråd (verktøy-uavhengige)

- Pakk hele flyten i klientens retry-mekanisme — idempotensen gjør
  gjentak trygge
- Sett et totaltidsavbrudd på pollingen (f.eks. 300 s) og behandl
  brudd som feil
- `FAILED` betyr at minst én side feilet permanent — detaljer per side
  ligger i `/dokument/{id}/status`, hendelsesforløp i `/audit/{job_id}`
- Ved flytting til server: bare bytt basis-URL — kontrakten er identisk

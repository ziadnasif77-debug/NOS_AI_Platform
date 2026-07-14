# UiPath-integrasjon

UiPath gjør kun orkestrering (lett arbeid); all AI-prosessering skjer
i NAV Archive-systemet. Roboten snakker med API-et over HTTP med det
asynkrone mønsteret «last opp → poll → hent» — roboten fryser aldri
mens GPU-en jobber.

```
[UiPath-robot]                      [NAV Archive API :8000]
      │  POST /last-opp/  (PDF) ──────────►  202 + job_id
      │                                        │ Redis-kø → workers
      │  GET /jobb/{id}   (hvert 2. s) ─────►  state: QUEUED/…/DONE
      │  GET /resultat/{id}/felter ─────────►  flat JSON med feltene
      ▼
 skriver inn i ERP / fagsystem / nettleser
```

## Kontrakten roboten bruker

| Steg | Kall | Svar |
|------|------|------|
| 1 | `POST /last-opp/` (multipart, felt `fil`, header `X-API-Key`) | `202` + `{job_id, state}` — `200` med `idempotent: true` hvis samme fil nylig er lastet opp |
| 2 | `GET /jobb/{job_id}` | `{state}` — poll til `DONE` eller `FAILED` |
| 3 | `GET /resultat/{job_id}/felter` | Flat forretnings-JSON (under) — `409` hvis ikke ferdig |

Svar fra `/resultat/{job_id}/felter` (stabil kontrakt for RPA):

```json
{
  "job_id": "…", "state": "DONE", "ferdig": true,
  "filnavn": "soknad.pdf",
  "beslutning": "APPROVED",
  "felter": {
    "navn": "Ola Nordmann", "fodselsnummer": "…", "dato": "2020-01-01",
    "adresse": null, "ytelse": "dagpenger", "fylke": "Oslo",
    "dokumenttype": "vedtak", "utfall": "innvilget", "oppsummering": "…"
  },
  "konfidens": { "ocr": 0.97, "nlp": 0.95 },
  "gjennomgang": { "kreves": false, "label_studio_prosjekt": null }
}
```

Merk: fødselsnummer serveres kun via dette autentiserte endepunktet —
det lagres aldri i søkeindeksen (Milvus).

## Oppsett i UiPath Studio (5 minutter)

1. Nytt prosjekt (Windows) → åpne `Main.xaml`
2. Dra inn én **Invoke Code**-aktivitet (Language: **VBNet**)
3. Lim inn innholdet i [`uipath/LesDokument.vb`](../uipath/LesDokument.vb)
4. Opprett argumentene i aktiviteten (navn/retning/type står øverst i fila):
   `FilSti`, `ApiUrl`, `ApiNokkel`, `TidsavbruddSekunder` (inn) og
   `JobbId`, `Beslutning`, `ResultatJson` (ut)
5. Etterpå: **Deserialize JSON** på `ResultatJson` →
   `resultat("felter")("navn").ToString()` osv. rett inn i målsystemet

Alternativ uten kode: tre **HTTP Request**-aktiviteter
(UiPath.WebAPI.Activities) med samme tre kall og en While-løkke med
Delay 2 s rundt kall 2 — kontrakten er identisk.

## Verifiser kontrakten FØR du åpner Studio

```powershell
$env:API_NOKKEL = "din-nokkel"
.\uipath\test_robotflyt.ps1 -FilSti .\test.pdf
```

Skriptet kjører nøyaktig samme tre kall som roboten. Grønt skript =
UiPath-workflowen vil fungere.

## Robusthet i roboten

- **Retry**: pakk Invoke Code i en Retry Scope (3 forsøk) — opplasting
  er idempotent (samme fil i samme 5-min-vindu gir samme `job_id`),
  så re-kjøring er trygt
- **Tidsavbrudd**: `TidsavbruddSekunder` styrer maks ventetid; ved
  brudd kastes exception med siste tilstand
- **REVIEW/REJECTED**: sjekk `gjennomgang.kreves` — da skal saken til
  menneskelig behandling i Label Studio, ikke inn i ERP
- **Feilsøking**: `GET /audit/{job_id}` gir hele hendelsesforløpet
- **Flytting til server**: bytt kun `ApiUrl` — resten er uendret
- **OIDC i stedet for API-nøkkel**: sett `AUTH_MODUS=oidc` på API-et og
  la roboten sende `Authorization: Bearer <token>` (se README «Sikkerhet»)

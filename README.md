# NAV Archive Intelligence System — V2.1

Et produksjonsklart AI-pipeline for automatisk digitalisering, analyse og søk i historiske NAV-dokumenter (30–60 millioner sider). V2.1 introduserer **Postgres som eneste kilde til sannhet**, asynkrone worker-prosesser, idempotent opplasting og full audit-logg — i henhold til NAV-krav for offentlig forvaltning.

---

## Innholdsfortegnelse

- [Oversikt](#oversikt)
- [V2.1-arkitektur](#v21-arkitektur)
- [Tilstandsmaskin](#tilstandsmaskin)
- [Workers](#workers)
- [Database-skjema](#database-skjema)
- [AI-modeller](#ai-modeller)
- [Forutsetninger](#forutsetninger)
- [Installasjon](#installasjon)
- [Konfigurasjon](#konfigurasjon)
- [Oppstart](#oppstart)
- [API-dokumentasjon](#api-dokumentasjon)
- [Make-kommandoer](#make-kommandoer)
- [Sikkerhetskopi og gjenoppretting](#sikkerhetskopi-og-gjenoppretting)
- [Oppbevaringsbegrensning (6 måneder)](#oppbevaringsbegrensning-6-måneder)
- [Testing](#testing)
- [SLA-mål](#sla-mål)
- [Sikkerhet og GDPR](#sikkerhet-og-gdpr)

---

## Oversikt

| Lag | Funksjon | Teknologi |
|-----|----------|-----------|
| **Preprocessing** | Bildekvalitet + dokumentklassifisering | OpenCV, Laplacian |
| **OCR** | PDF → strukturert tekst + layout | TrOCR, PaddleOCR 3.0, Marker |
| **NLP** | Feltuttrekking + validering + utfall | LayoutLMv3, Borealis-4B, NB-BERT |
| **Routing** | APPROVED / REVIEW / REJECTED | Ren logikk |
| **Søk** | Hybrid semantisk + nøkkelordssøk | Milvus, BM25, RRF |

Dokumenter som ikke møter kvalitetskravene sendes automatisk til **Label Studio** (korrekt prosjekt per årsak). Korreksjoner brukes til kontinuerlig finjustering.

---

## V2.1-arkitektur

```
  POST /last-opp/
       │
       ▼
  ┌─────────────────────────────────────────────────────┐
  │  API (port 8000)                                     │
  │  • idempotens-sjekk (sha256 + 5-min-bøtte)          │
  │  • Postgres: UPLOADED → QUEUED                       │
  │  • Redis: rpush queue:preprocess                     │
  └────────────────────┬────────────────────────────────┘
                       │ Redis blpop
       ┌───────────────▼──────────────────┐
       │  PreprocessingWorker             │
       │  QUEUED → PREPROCESSING          │
       │  Bildekvalitet (Laplacian)       │
       │  Dokumenttype (Otsu)             │
       └───────────────┬──────────────────┘
                       │ queue:ocr
       ┌───────────────▼──────────────────┐
       │  OCRWorker                       │
       │  PREPROCESSING → OCR_PROCESSING  │
       │  Handskrift → TrOCR              │
       │  Tabell     → Marker             │
       │  Blandet    → PaddleOCR+Marker   │
       │  Trykt      → PaddleOCR 3.0      │
       └───────────────┬──────────────────┘
                       │ queue:nlp
       ┌───────────────▼──────────────────┐
       │  NLPWorker                       │
       │  OCR_PROCESSING → NLP_PROCESSING │
       │  layout → LayoutLMv3             │
       │  lang   → Borealis               │
       │  annet  → NB-BERT                │
       │  + intern validering (mod11 fnr) │
       └───────────────┬──────────────────┘
                       │ queue:validation
       ┌───────────────▼──────────────────┐
       │  RoutingWorker                   │
       │  VALIDATION → ROUTING → DONE     │
       │  APPROVED → Milvus-kø            │
       │  REVIEW   → Label Studio         │
       └──────────────────────────────────┘
               ▲
               │  hvert 5. minutt
       ┌───────┴──────────────────────────┐
       │  ReconciliationWorker            │
       │  • stuck jobs (lås utløpt)       │
       │  • ghost states (ikke i Redis)   │
       │  • tapte jobber (UPLOADED > 5m)  │
       └──────────────────────────────────┘

  Postgres = eneste kilde til sannhet
  Redis    = transport (rebuildes fra Postgres ved restart)
```

---

## Tilstandsmaskin

```
UPLOADED → QUEUED → PREPROCESSING → OCR_PROCESSING → NLP_PROCESSING → ROUTING → DONE
                                                                            ↓
                                                                         FAILED (terminal)
```

> **Merk:** `VALIDATION`-tilstanden eksisterer i Postgres-skjemaet, men NLPWorker utfører validering inline og hopper direkte til `ROUTING`. Overgangen `NLP_PROCESSING → ROUTING` er eksplisitt tillatt i `LOVLIGE_OVERGANGER`.

| Overgang | Utløser |
|----------|---------|
| `UPLOADED → QUEUED` | API (commit før redis rpush) |
| `QUEUED → PREPROCESSING` | PreprocessingWorker blpop |
| `PREPROCESSING → OCR_PROCESSING` | OCRWorker blpop |
| `OCR_PROCESSING → NLP_PROCESSING` | NLPWorker blpop |
| `NLP_PROCESSING → ROUTING` | NLPWorker ferdig (validering inline) |
| `ROUTING → DONE` | RoutingWorker ferdig |
| `* → FAILED` | 3 retries → DLQ |
| `FAILED → <før-tilstand>` | `make dlq-gjenoppta MONSTER="..."` — gjenopptak etter fikset infrastrukturfeil (merkes i audit/DLQ så historiske feilrater kan skille bugg fra ekte feil) |

Alle andre overganger kaster `UgyldigTilstandsovergang`.

---

## Flersidige dokumenter

En opplastet PDF splittes i **én jobb per side** (`dokument_id` grupperer,
`side_nummer` identifiserer). Hver side får full livssyklus, eget
audit-spor og uavhengig feilhåndtering — én uleselig side stopper ikke
resten av dokumentet.

- Lag 0 rendrer riktig side til PNG via PyMuPDF (cv2 kan ikke lese PDF)
  og skriver en enkeltside-PDF for Marker
- Søkeindeksen lagrer `(dokument_id, side_nummer)` — treff peker på riktig side
- Aggregerte endepunkter: `GET /dokument/{id}/status` (DONE når alle
  sider er ferdige) og `GET /dokument/{id}/felter` (felter samlet på
  tvers av sidene; strengeste beslutning vinner: REJECTED > REVIEW > APPROVED)

---

## Workers

### BaseWorker (`tjenester/workers/base_worker.py`)
Abstrakt basisklasse alle workers arver:
- **Optimistisk låsing:** `locked_by` + `lock_expiry` (60 sek) — hindrer to workers fra å behandle samme jobb
- **Retry med backoff:** 1s → 3s → 10s, maks 3 forsøk
- **DLQ:** Etter maks retries → `dead_letter_queue`-tabell + `dlq:<stage>`-kø
- **Audit-logg:** Hvert tilstandsskift, låsing og DLQ-hendelse skrives til `audit_log`

### PreprocessingWorker
- Beregner bildekvalitet (Laplacian-varians / 1000, capped 1.0)
- Klassifiserer dokumenttype (Otsu-terskel)
- Sender til Label Studio prosjekt 1 hvis kvalitet < terskel

### OCRWorker
- GPU-samtidighet styres av worker-replicas + K8s GPU-limits (in-process-semafor fjernet — no-op i enkelt-trådet worker)
- Ruter til riktig modell basert på dokumenttype
- Sender til Label Studio prosjekt 2 ved lav konfidens

### NLPWorker (inkluderer validering)
- Ruter NLP-modell: tekst > 200 tegn → Borealis (åpen LLM-uttrekking, alle felter dokumentet inneholder); ellers LayoutLMv3 (ved layout) eller NB-BERT
- **Anti-hallusinasjon** (`utvid_entiteter`): modellverdier for sjekksumfelter (fnr, konto) må bestå mod11; ytelse/fylke må finnes i kanoniske lister (fylke også i teksten); kontornavn må starte med NAV
- **Model serving-modus**: settes `LLM_URL` kalles Borealis over OpenAI-protokollen (vLLM/TGI/Triton) i stedet for lokal lasting — workeren blir lett og horisontalt skalerbar
- **Deterministisk uttrekkslag** (`delt/tekstuttrekk.py`) oppå modellene — mønstre og mod11-sjekksummer, mer presist enn NER for strukturerte felter:

  | Felt | Metode |
  |------|--------|
  | fodselsnummer | 11 sifre + dobbel mod11-sjekksum |
  | kontonummer | 11 sifre (ev. dddd.dd.ddddd) + konto-mod11 |
  | dato | numeriske formater + norske månedsnavn → dd.mm.yyyy |
  | telefon | 8 sifre, +47-prefiks, hopper over haler av fnr/konto |
  | epost, postnummer/poststed, belop (kr/NOK), saksnummer, kontornavn (NAV-kontor) | mønstre |
  | ytelse, fylke | nøkkelord mot kanoniske lister i `delt/konstanter.py` — erstatter den gamle «enhver ORG = ytelse»-gjetningen |
- Intern validering (ingen HTTP): Mod11 fødselsnummer, dato 1900–innværende år (dynamisk), obligatoriske felt, norske fylker
- Kryssvalidering (kun hvis `CONFIG["lag"]["lag5_kryssvalidering"] = true`)
- Sender til Label Studio prosjekt 4 ved valideringsfeil

### RoutingWorker
- Ren logikk, ingen modeller
- Prioritet: OCR-konfidens → NLP-konfidens → validering → anomali → APPROVED
- APPROVED: HTTP POST til `sok:8003/indekser` (3 forsøk med backoff 2s/4s)
- REVIEW/REJECTED: sendes til Label Studio med korrekt prosjekt-ID

### ReconciliationWorker (hvert 5. minutt)
- **Stuck jobs:** lås utløpt → frigi lås + re-kø
- **Ghost states:** aktiv i Postgres, ikke i Redis, > 10 min siden sist oppdatert → re-kø
- **Tapte jobber:** UPLOADED > 5 min uten å bli QUEUED → sett QUEUED + kø

---

## inference_meta — Sporbarhet per forespørsel

Alle `/analyser`-svar fra `lag3_nlp`-tjenesten inkluderer en `inference_meta`-blokk som dokumenterer nøyaktig hvilken modell som ble brukt og hvorfor:

```json
{
  "inference_meta": {
    "confidence_source": "heuristic_fixed_rule_v1",
    "fallback_chain": [
      {"model": "layoutlmv3", "status": "skipped", "reason": "warmup_pending"},
      {"model": "ner",        "status": "used",    "reason": "primary_success"}
    ]
  }
}
```

| `status` | Betydning |
|----------|-----------|
| `used` | Modellen ble brukt |
| `skipped` | Modellen ble ikke forsøkt |
| `failed` | Modellen feilet — fallback ble aktivert |

| `reason` | Utløser |
|----------|---------|
| `primary_success` | Brukt uten feil |
| `no_image` | Mangler bildesti |
| `warmup_pending` | Modell lastes fortsatt i bakgrunn |
| `backoff` | Maks lastforsøk nådd, venter på ny sjanse (10 min) |
| `runtime_error` | Unntak under inferens |

`lag3_nlp`-tjenesten bruker **lazy singleton-initialisering**: modeller lastes ved første forespørsel via en bakgrunnstråd ved oppstart (`lifespan`-hook). Dette eliminerer GPU-minneallokering ved container-oppstart uten trafikk.

---

## Legacy-lag (null trafikk)

Følgende HTTP-tjenester kjører men mottar **ingen trafikk** fra V2.1-pipelinen:

| Tjeneste | Port | Status |
|----------|------|--------|
| `lag0_kvalitet` | 8010 | Aktiv, ikke i bruk |
| `lag1_klassifisering` | 8011 | Aktiv, ikke i bruk |
| `lag2_ocr` | 8012 | Aktiv, ikke i bruk |
| `lag3_nlp` | 8013 | Aktiv — GPU lazy-loaded |
| `lag4_validering` | 8014 | Aktiv, ikke i bruk |
| `lag5_kryssvalidering` | 8015 | Aktiv, ikke i bruk |
| `ruter` | 8016 | Aktiv, ikke i bruk |

All reell behandling skjer i `tjenester/workers/` via Redis-køer.

---

## Database-skjema

### `jobs`
```sql
job_id          UUID PRIMARY KEY DEFAULT gen_random_uuid()
idempotency_key TEXT UNIQUE NOT NULL   -- sha256(innhold + tidsbøtte)
state           job_state NOT NULL DEFAULT 'UPLOADED'
current_stage   TEXT
file_name       TEXT NOT NULL
file_path       TEXT NOT NULL
priority        INT DEFAULT 1
attempt_count   INT DEFAULT 0
max_retries     INT DEFAULT 3
last_error      TEXT
locked_by       TEXT                   -- worker_id eller NULL
lock_expiry     TIMESTAMP              -- utløpstidspunkt for lås
created_at      TIMESTAMP DEFAULT NOW()
updated_at      TIMESTAMP DEFAULT NOW()
completed_at    TIMESTAMP
```

### `results`
```sql
job_id              UUID PRIMARY KEY REFERENCES jobs(job_id)
preprocess_result   JSONB
ocr_result          JSONB
nlp_result          JSONB
validation_result   JSONB
routing_decision    TEXT CHECK (IN ('APPROVED','REVIEW','REJECTED'))
label_studio_project INT
```

### `audit_log` (slettes aldri — NAV-krav)
```sql
id          BIGSERIAL PRIMARY KEY
job_id      UUID
event_type  TEXT NOT NULL   -- STATE_ENDRING, RETRY, DLQ, OPPRETTET, ...
from_state  TEXT
to_state    TEXT
worker_id   TEXT
details     JSONB
created_at  TIMESTAMP DEFAULT NOW()
```

### `dead_letter_queue`
```sql
id               BIGSERIAL PRIMARY KEY
job_id           UUID
stage            TEXT
error_type       TEXT
error_message    TEXT
payload_snapshot JSONB
retry_count      INT
resolved_at      TIMESTAMP   -- NULL = ikke løst
resolved_by      TEXT
created_at       TIMESTAMP DEFAULT NOW()
```

---

## AI-modeller

Alle modeller kjører **100 % offline** etter første nedlasting (~17 GB totalt).

| Nøkkel | Modell | Bruk |
|--------|--------|------|
| `norhand` | `Sprakbanken/TrOCR-norhand-v3` | Håndskrift-OCR |
| `nb_bert` | `NbAiLab/nb-bert-base` | Dokumentklassifisering |
| `nb_bert_ner` | `NbAiLab/nb-bert-base-ner` | Entitetsgjenkjenning (fallback) |
| `layoutlmv3` | `microsoft/layoutlmv3-base` | Feltuttrekking (tekst + layout) |
| `borealis` | `NbAiLab/borealis-4b-instruct-preview` | Norsk LLM — analyse |
| `qwen3` | `Qwen/Qwen3-Embedding-0.6B` | 1024-dim vektorembedding |

**Modellruting NLP (aldri alle tre samtidig):**
- `len(tekst) > 200` → Borealis (åpen LLM-feltuttrekking — finner alle felter dokumentet inneholder, ikke bare en fast liste; 4-bit NF4-kvantisert for 8 GB GPU)
- TRYKT/TABELL + tokens+bokser (når Borealis mangler) → LayoutLMv3
- ellers → NB-BERT

### Model serving (valgfritt)

Borealis kan serveres som egen tjeneste med **vLLM** (OpenAI-kompatibel
API) i stedet for å lastes i NLP-workeren:

```bash
docker compose --profile llm up -d llm   # start vLLM-serveren
# sett i .env:  LLM_URL=http://llm:8000/v1
docker compose up -d nlp_worker          # workeren blir HTTP-klient
```

Gevinster: én modell-lasting (worker-restart tar sekunder, ikke
minutter), continuous batching, og NLP-workerne kan skaleres
horisontalt uten å eie GPU-en. Protokollen er standard OpenAI —
bytt til TGI/Triton uten kodeendring. I K8s: [k8s/16-llm.yaml](k8s/16-llm.yaml).
Faller LLM-tjenesten bort ruter workeren automatisk til NB-BERT
(fallback-kjeden er uendret).

---

## Forutsetninger

- **Docker** ≥ 24 og **Docker Compose** ≥ 2.20
- **NVIDIA GPU** med ≥ 12 GB VRAM (anbefalt for Borealis-4B)
- **NVIDIA Container Toolkit** installert
- Python 3.11+ (kun for skript utenfor Docker)
- ≥ 30 GB ledig diskplass (modeller + data + Postgres)

---

## Installasjon

### 1. Klon repositoriet
```bash
git clone https://github.com/ziadnasif77-debug/nav.git
cd nav
```

### 2. Kjør ett-kommando lokalt oppsett
```bash
make oppsett
```
Gjør automatisk: oppretter `.env` (fra `.env.example`, med `API_NOKKEL`
satt), oppretter alle datamapper, og sjekker om GPU-en din faktisk er
synlig for Docker (NVIDIA-driver + NVIDIA Container Toolkit) — dette
kan kun sjekkes på din egen maskin, ikke i et sky-/CI-miljø.

### 3. Last ned AI-modeller
```bash
make last-ned-modeller   # ~17 GB, én gang — trygt å avbryte og gjenoppta
```
Bruker `snapshot_download` som gjenopptar delvis nedlastede filer automatisk
ved ny kjøring — ingen behov for å slette og starte på nytt ved avbrudd.

### 4. Initialiser databasen
```bash
make start       # starter postgres
make init-db     # oppretter alle tabeller og enum-typer
```

---

## Konfigurasjon

Alle innstillinger i `config/config.yaml` og `.env`.

| Parameter | Standard | Beskrivelse |
|-----------|----------|-------------|
| `terskler.bildekvalitet` | `0.60` | Laplacian-score under dette → Label Studio |
| `terskler.ocr_konfidens` | `85` | Prosent — under dette → Label Studio |
| `terskler.nlp_konfidens` | `80` | Prosent — under dette → Label Studio |
| `gpu.maks_ocr_jobber` | `2` | Maks samtidige GPU-OCR-jobber |
| `reconciliation.intervall_sekunder` | `300` | Reconciliation-frekvens |
| `reconciliation.lock_timeout_sekunder` | `60` | Låsevarighet for workers |
| `lag.lag5_kryssvalidering` | `false` | Aktiver FNR/dato-kryssvalidering |

---

## Oppstart

```bash
# Start alle tjenester (inkl. V2.1 workers og Postgres)
make start

# Første kjøring: initialiser database
make init-db

# Rebuild Redis fra Postgres (etter Redis-restart)
make rebuild-redis

# Sjekk at alt er oppe
make helse

# Se logger
make logger
```

### Kubernetes: hybrid-arkitektur (anbefalt)

Produksjon kjører Redis + permanente workers (varme modeller, lav
latens); Kubeflow brukes kun til trening og modell-livssyklus.
Se [docs/HYBRID_ARKITEKTUR.md](docs/HYBRID_ARKITEKTUR.md) for
diagram, kapasitetsestimat (30–60 mill. sider/år), modelloppdatering
uten nedetid og KEDA-autoskalering på kølengde.

Dokumentflyten kan alternativt kjøre som Kubeflow Pipelines
(`KJOREMODUS=kubeflow`) — én pipeline-run per dokument med synlige
steg i KFP-UI-et, nyttig for feilsøking:

```bash
make kfp-installer        # Kubeflow Pipelines standalone
make k8s-bygg             # bygg alle images lokalt
make k8s-start            # deploy tjenestene (k8s/)
make k8s-init-db          # opprett databaseskjema
make k8s-kopier-modeller  # kopier modeller inn i PVC
```

Se [docs/KUBEFLOW.md](docs/KUBEFLOW.md) for full guide og kjente
begrensninger (retry, ghost-gjenoppretting, oppstartstid per steg).

---

## API-dokumentasjon

### Last opp et dokument
```bash
curl -X POST http://localhost:8000/last-opp/ \
  -H "X-API-Key: din-nokkel" \
  -F "fil=@dokument.pdf"
```
**Svar (202 Accepted):**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "filnavn": "dokument.pdf",
  "state": "QUEUED",
  "idempotent": false,
  "sjekk_status": "/jobb/550e8400-e29b-41d4-a716-446655440000"
}
```
Sender du samme fil innen 5 minutter får du `"idempotent": true` og samme `job_id` tilbake.

### Sjekk status
```bash
curl http://localhost:8000/jobb/{job_id}
```
Returnerer `job_id`, `state`, `filnavn`, `opprettet`, `oppdatert`.

### Hent resultat
```bash
curl http://localhost:8000/resultat/{job_id}
```
Returnerer alle worker-resultater fra `results`-tabellen.

### Hent dokumenttekst i original sideorden
```bash
curl "http://localhost:8000/dokument/{id}/tekst"                      # hele dokumentet
curl "http://localhost:8000/dokument/{id}/tekst?fra_side=0&til_side=49"  # sideintervall (1000+ sider)
curl "http://localhost:8000/dokument/{id}/tekst?tillat_delvis=true"   # ferdige sider mens resten pågår
```
Sider prosesseres parallelt og blir ferdige i vilkårlig rekkefølge —
her gjenopprettes ALLTID original rekkefølge (`ORDER BY side_nummer`):
`sider[]` sortert med tekst + OCR-konfidens per side, og `samlet_tekst`
med sidemarkører (`--- Side N av M ---`). Standard: 409 til alle sider
i intervallet er DONE; `tillat_delvis=true` gir de ferdige sidene
eksplisitt (`ferdig: false` + `manglende_sider`). Verifisert live med
10-siders PDF: alle sider på original posisjon.

> ⚠️ **Visnings-/revisjonsendepunkt** — rå OCR-tekst uten validering.
> Forretningsuttrekk skal bruke `/dokument/{id}/felter` (deterministisk
> validert: mod11, kanoniske lister, anti-hallusinasjon) eller
> `/dokument/{id}/sporsmal` (forankret svar). Å parse rå tekst selv
> omgår alle disse lagene.

### Hent audit-logg
```bash
curl http://localhost:8000/audit/{job_id}
```
Returnerer komplett historikk for jobben (alle tilstandsskifter, retries, DLQ-hendelser).

### Fritekst-spørsmål mot et dokument (LLM)
```bash
curl -X POST http://localhost:8000/dokument/{dokument_id}/sporsmal \
  -H "X-API-Key: ..." -H "Content-Type: application/json" \
  -d '{"sporsmal": "Hva er referansekoden på side 4?"}'
```
**Svar:** `{"svar": "SIDEKODE-0004", "funnet": true, "side": 4, "sitat": "...", "kilde": "borealis-http"}`

Krever model serving (`LLM_URL`). Stilles ETTER prosessering — ubegrenset
antall spørsmål per dokument uten ny OCR. Sidene gjennomgås i original
rekkefølge, bit for bit innenfor modellkonteksten. Svaret er forankret:
sidetall + ordrett sitat, og `funnet: false` i stedet for gjetning når
svaret ikke står i teksten. Svar lagres aldri (ingen ny GDPR-flate).
Dokumenttekst behandles som data — instruksjoner i dokumentet ignoreres.

**Virksomhetsregler** ([config/sporsmal_regler.md](config/sporsmal_regler.md)):
manuelt redigerbar regelfil som leses PÅ NYTT ved hvert spørsmål —
endringer gjelder umiddelbart uten omstart (filen er volummontert).
Reglene injiseres som strenge instrukser i hvert LLM-kall og svaret
rapporterer `regler_aktive`. Se aktive regler: `GET /sporsmal/regler`.
Best for strenghets- og utvalgsregler («usikker → funnet=false»,
«laveste sidetall ved flere kandidater»); omskrivningsregler følges
upålitelig — ordrett uthenting vinner med vilje (anti-hallusinasjon).

### Søk i arkivet
```bash
curl -X POST http://localhost:8000/sok \
  -H "X-API-Key: din-nokkel" \
  -H "Content-Type: application/json" \
  -d '{"sporsmal": "dagpenger 1985", "antall": 10}'
```

### API-integrasjon (RPA og eksterne systemer)

API-et er selvdokumenterende og verktøy-nøytralt: Swagger-UI på
`/docs`, maskinlesbar OpenAPI-spesifikasjon på `/openapi.json` (åpne
uten nøkkel — kun skjema, aldri data). Verktøy som UiPath og Power
Automate importerer spesifikasjonen direkte.

Asynkront mønster for alle klienter:

```
POST /last-opp/                → 202 + dokument_id (én jobb per side)
GET  /dokument/{id}/status     → poll til DONE/FAILED
GET  /dokument/{id}/felter     → aggregerte forretningsfelter
```

Full guide med kontraktsgarantier: [docs/API_INTEGRASJON.md](docs/API_INTEGRASJON.md).

---

## Make-kommandoer

```bash
# ─── Førstegangsoppsett ──────────────────────────────────────────────
make oppsett                 # .env + datamapper + GPU-sjekk (kjøres på din maskin)

# ─── Infrastruktur ───────────────────────────────────────────────────
make start                   # Start alle Docker-tjenester
make stopp                   # Stop alle tjenester
make restart                 # Restart alle tjenester
make logger                  # Vis logger i sanntid
make helse                   # Sjekk alle tjenester

# ─── V2.1 ────────────────────────────────────────────────────────────
make init-db                 # Opprett Postgres-tabeller og enum-typer
make rebuild-redis           # Rebuild Redis-køer fra Postgres
make start-workers           # Start alle worker-containere
make start-reconciliation    # Start ReconciliationWorker

# ─── Sikkerhetskopi ──────────────────────────────────────────────────
make sikkerhetskopi          # Ta en verifisert pg_dump nå
make sikkerhetskopi-status   # Siste kjøring (fil, størrelse, verifisert)
make sikkerhetskopi-verifiser FIL=...   # Kontroller sha256 + lesbarhet
make gjenopprett FIL=... [DB=navn]      # Gjenopprett (DB= for øvelse)

# ─── Tester ──────────────────────────────────────────────────────────
make test                    # Kjør alle tester (290: 248 enhet + 42 integrasjon)
make test-state-machine      # Test tilstandsmaskin
make test-idempotency        # Test idempotens-logikk

# ─── Modeller og trening ─────────────────────────────────────────────
make last-ned-modeller       # Last ned AI-modeller (~17 GB)
make finjuster               # Finjuster TrOCR + NB-BERT + LayoutLMv3
make lag-datasett            # Generer Label Studio-oppgaver
make konverter-annotasjoner  # Konverter annotasjoner → treningsformat
make send-til-trening        # Eksporter + finjuster i én kommando

# ─── Drift ───────────────────────────────────────────────────────────
make sok SPORSMAL="..."      # Søk fra terminalen
make last-opp FIL="..."      # Last opp PDF
make label-studio            # Åpne Label Studio (http://localhost:8080)
```

---

## Sikkerhetskopi og gjenoppretting

Postgres er eneste kilde til sannhet — strategien følger av det:
**daglig verifisert `pg_dump`** (dumpen får ikke endelig navn før
`pg_restore --list` har lest den) med **GFS-retention 7/4/6**, sha256
ved siden av hver dump, inkrementell kopi av originaldokumenter og
hendelseslogging i `audit_log`. Redis og Milvus sikkerhetskopieres
bevisst *ikke* (transport / avledet — gjenoppbygges fra Postgres).

```bash
make sikkerhetskopi          # verifisert kopi nå
make gjenopprett FIL=... DB=nav_archive_restore_test   # øvelse
make gjenopprett FIL=...     # katastrofe (husk: make rebuild-redis!)
```

Lokalt kjører en backup-daemon hver 24. time; i K8s en CronJob kl. 02:00
([k8s/15-sikkerhetskopi.yaml](k8s/15-sikkerhetskopi.yaml)). RPO 24 t
(konfigurerbart), RTO minutter. Full strategi, katastrofeprosedyre og
begrunnelser: **[docs/SIKKERHETSKOPI.md](docs/SIKKERHETSKOPI.md)**.

---

## Oppbevaringsbegrensning (6 måneder)

NAV tillater ikke dokumentlagring over 6 måneder. En daglig
oppbevaringsjobb sletter **alt dokumentinnhold** eldre enn
`OPPBEVARING_MAKS_DAGER` (standard 150): originalfiler, `results`-rader
(OCR-tekst + entiteter), DLQ-snapshots, søkeindeksen (Milvus) og
backup-speilet. `jobs`-raden anonymiseres men beholdes som statistikk;
`audit_log` beholdes for alltid (inneholder aldri dokumentinnhold).
Hver sletting bevises med `SLETTET_OPPBEVARING` i audit-loggen.

Budsjettet inkluderer sikkerhetskopiene:
`150 dager + eldste backup-kopi (~28) ≤ 180`.

```bash
make oppbevaring-torrkjoring   # revisjon: hva ville blitt slettet?
make oppbevaring               # slett nå
```

Full analyse av hvor persondata lever og etterlevelsesbevis:
**[docs/OPPBEVARING.md](docs/OPPBEVARING.md)**.

---

## Testing

### Enhetstester (290 totalt: 248 enhet + 42 integrasjon)

```bash
python -m pytest tester/ -v
```

| Testfil | Beskrivelse |
|---------|-------------|
| `test_config.py` | Config-struktur, porter, terskler |
| `test_state_machine.py` | Gyldige/ugyldige tilstandsoverganger |
| `test_idempotency.py` | SHA256-nøkkel, tidsbøtter, hex-format |
| `test_dlq.py` | Retry-backoff (1s/3s/10s), DLQ etter 3 forsøk |
| `test_routing_decisions.py` | Alle beslutningskombinasjoner |
| `test_validation.py` | Mod11 FNR, dato 1900–2024 |
| `test_reconciliation.py` | Stuck/ghost/tapte jobber |
| `test_contracts.py` | Worker output-nøkler og verdiområder |
| `test_lag0.py` | Bildekvalitet (Laplacian), FNR-format |
| `test_lag4.py` | FNR mod11, datovalidering |
| `test_ruter.py` | Rutinglogikk fra gamle lag |
| `test_sec_rel_obs.py` | API-auth, FNR-fjerning, commit-før-push, audit-synlighet |
| `test_hardening.py` | Env-overrides, DB-feilhåndtering, config-opprydding |
| `test_kubeflow_modus.py` | kfp_steg, KJOREMODUS-gating, K8s-manifester |
| `test_observabilitet_auth.py` | Prometheus-metrikker, OIDC (ekte JWT-validering) |
| `test_audit_fikser.py` | Regresjon for audit-funn: lås/retry, rebuild-kontrakt, RRF-dokumenter, OIDC-roller |
| `test_tekstuttrekk.py` | Deterministisk uttrekkslag: mod11-sjekksummer, mønstre for 8 felter, sammenslåing med modell-entiteter, anti-hallusinasjon |
| `test_sikkerhetskopi.py` | GFS-retention, dump-filnavn, sha256 |
| `test_oppbevaring.py` | 6-månedersregelen: frist, stisamling, fil_id-validering, tørrkjøring, backup-speilrydding |
| `test_llm_klient.py` | Åpen LLM-uttrekking: JSON-parsing, nøkkelnormalisering, utflating, feltordning |

### Integrasjonstester (ekte Postgres + Redis, ingen mocks)

Krever kjørende Postgres og Redis:

```bash
POSTGRES_URL=postgresql://nav:nav@localhost:5432/nav_archive \
REDIS_URL=redis://localhost:6379/0 \
INTEGRASJONSTEST=1 python -m pytest tester/test_integrasjon_lokal.py -v
```

**Verifiserte scenarioer** (`test_integrasjon_lokal.py`, 41 tester) — utdrag:

| # | Scenario | Verifisert |
|---|----------|------------|
| 1 | `/helse` åpen uten API-nøkkel | ✅ |
| 2 | Alle andre endepunkter krever gyldig `X-API-Key` (401 ellers) | ✅ |
| 3 | Ikke-PDF avvises med 400 | ✅ |
| 4 | Opplasting: 202, `QUEUED` i Postgres, audit (`OPPRETTET` + `STATE_ENDRING`), nøyaktig én Redis-melding, fil lagret | ✅ |
| 5 | Idempotens: samme fil → samme `job_id`, ingen duplikat i kø | ✅ |
| 6 | 404 for ukjent jobb/resultat | ✅ |
| 7 | **Redis nede ved opplasting** (REL-1): 500 til klient, jobb trygt `QUEUED`, ghost-detektor re-køer automatisk | ✅ |
| 8 | Ulovlig tilstandsovergang avvises (`DONE → PREPROCESSING`) | ✅ |
| 9 | Optimistisk lås hindrer dobbel behandling | ✅ |
| 10 | PreprocessingWorker ende-til-ende: tilstand, resultat, neste kø, lås frigitt | ✅ |
| 11 | OCRWorker fallback uten modeller: konfidens 0.0, flagges for gjennomgang, fortsetter | ✅ |
| 12 | Routing `APPROVED` (alle terskler OK) | ✅ |
| 13 | Routing `REVIEW` ved lav OCR-konfidens (med Label Studio-prosjekt) | ✅ |
| 14 | Routing `REVIEW` ved anomali | ✅ |
| 15 | Feil → retry med økt teller, jobb ikke `FAILED` | ✅ |
| 16 | Uttømte retries → DLQ-rad, `FAILED`, audit `DLQ`, Redis-DLQ | ✅ |
| 17 | Reconciliation: stuck jobb (utløpt lås) re-køes, lås frigis | ✅ |
| 18 | Reconciliation: ghost (i Postgres, ikke i Redis) re-køes med audit | ✅ |
| 19 | Reconciliation: tapt jobb (`UPLOADED` > 5 min) blir `QUEUED` | ✅ |
| 20 | kfp_steg (kubeflow-modus): preprocess uten kø-push | ✅ |
| 21 | kfp_steg: routing leser forrige resultat fra `results`-tabellen | ✅ |
| 22 | kfp_steg: re-kjøring av fullført steg er ufarlig (ingen `FAILED`) | ✅ |
| 23 | kfp_steg: feil → DLQ + `FAILED` + exception til KFP | ✅ |
| 24 | kfp_steg: manglende forrige resultat gir tydelig feil | ✅ |
| 25 | `rebuild_redis`: køer gjenoppbygges fra Postgres | ✅ |

### Live ende-til-ende-verifikasjon

Hele kjeden er kjørt live (ekte uvicorn-API + ekte workers som
prosesser mot ekte Postgres/Redis): HTTP-opplasting → 401 uten nøkkel →
202 med nøkkel → `QUEUED → PREPROCESSING → OCR_PROCESSING →
NLP_PROCESSING → ROUTING → DONE` med `routing_decision=APPROVED` og
komplett audit-spor. NLP-steget ble simulert med injisert resultat
(se begrensninger under).

### Hva som IKKE dekkes uten modeller/infrastruktur

| Område | Hvorfor | Hvordan teste |
|--------|---------|---------------|
| OCR-/NLP-modellinferens (TrOCR, LayoutLMv3, NB-BERT) | Krever `make last-ned-modeller` (~GB) og helst GPU | Last ned modeller, kjør workers og last opp ekte skannede PDF-er |
| NLPWorker-oppstart | Nekter bevisst å starte uten minst én modell | Samme som over |
| Milvus-søk (`/sok`) | Krever kjørende Milvus + embeddings-modell | `make start` og `make sok SPORSMAL="..."` |
| Kubeflow-runtime | Krever K8s-cluster med KFP installert | Følg [docs/KUBEFLOW.md](docs/KUBEFLOW.md) |

---

## SLA-mål

| Steg | Mål | Hardgrense |
|------|-----|-----------|
| API (upload) | < 200 ms | 500 ms |
| Preprocessing | < 300 ms | 1 000 ms |
| OCR | 1–5 sek | 30 sek |
| NLP | < 1 500 ms | 5 000 ms |
| Validering | < 50 ms | 200 ms |
| Routing | < 20 ms | 100 ms |

---

## Sikkerhet og GDPR

- **Offline:** Alle AI-modeller kjører lokalt — ingen data forlater serveren
- **Autentisering (to moduser via `AUTH_MODUS`):**
  - `api_nokkel` (standard): `X-API-Key` på alle endepunkter unntatt `/helse` og `/metrics` — sammenlignet i konstant tid (`hmac.compare_digest`, mot timing-angrep)
  - `oidc`: Bearer-token (JWT) validert mot institusjonens identitetsleverandør. Valgfri autorisasjon: `OIDC_PAAKREVD_ROLLE` krever rollen i tokenets `roles`-claim (Azure AD, Maskinporten, Keycloak, …). Sett `OIDC_JWKS_URL`, `OIDC_ISSUER` og `OIDC_AUDIENCE`. Signatur, utløp, issuer og audience verifiseres per forespørsel; JWKS-nøkler caches.
- **CORS:** `CORS_ORIGINS` (kommaseparert) begrenser tillatte opphav i produksjon
- **Audit-logg:** Slettes aldri (NAV-krav) — komplett sporbarhet for alle tilstandsskifter
- **Sikkerhetskopi:** Daglig verifisert `pg_dump` med GFS-retention (7/4/6) + inkrementell kopi av originaldokumenter; backup-hendelser logges i audit_log. Full strategi og gjenopprettingsprosedyre: [docs/SIKKERHETSKOPI.md](docs/SIKKERHETSKOPI.md)
- **Idempotens:** Duplikate opplastinger gir ingen duplikate jobber
- **GDPR:** Fødselsnummer, navn og adresse behandles kun internt — validering via Mod11 uten ekstern oppkobling. Fødselsnummer lagres ikke i søkeindeksen (Milvus).
- **Oppbevaringsbegrensning:** Alt dokumentinnhold slettes automatisk etter maks 150 dager (budsjett 180 inkl. backup) — se [docs/OPPBEVARING.md](docs/OPPBEVARING.md)

---

## Overvåking (Prometheus + Grafana)

Alle tjenester eksponerer Prometheus-metrikker:

| Kilde | Endepunkt | Metrikker |
|-------|-----------|-----------|
| API | `:8000/metrics` (åpent for scraping) | `nav_api_forespoersler_total{metode,rute,status}`, `nav_api_latens_sekunder{rute}` |
| Workers | `:9101/metrics` (via `METRIKK_PORT`) | `nav_jobber_behandlet_total{worker,utfall}` (`ok`/`retry`/`dlq`/`hoppet_over`), `nav_jobb_varighet_sekunder{worker}` |

```bash
make overvaaking     # Prometheus (localhost:9090) + Grafana (localhost:3000)
```

Scrape-konfig ligger i `overvaaking/prometheus.yml`; Grafana får
Prometheus som datakilde automatisk. I Kubernetes er API-podden
annotert med `prometheus.io/scrape` for automatisk oppdaging.
Metrikkene degraderer pent: mangler `prometheus-client` kjører
tjenestene videre uten metrikker (`delt/metrikker.py`).

Nyttige spørringer:

```promql
rate(nav_jobber_behandlet_total{utfall="dlq"}[5m])        # feilrate til DLQ
histogram_quantile(0.95, nav_jobb_varighet_sekunder_bucket)  # p95 per steg
rate(nav_api_forespoersler_total{status="401"}[5m])       # avviste forespørsler
```

---

## Mappestruktur

```
nav/
├── docker-compose.yml
├── Makefile
├── config/
│   └── config.yaml                         # Sentralkonfig
├── delt/
│   ├── konstanter.py                        # V2.1: STATE_OVERGANGER, LOVLIGE_OVERGANGER, REDIS_KOOER, NORSKE_FYLKER/YTELSER
│   ├── skjemaer.py                          # Pydantic-modeller
│   ├── tekstuttrekk.py                      # Deterministisk feltuttrekk: mod11, mønstre, utvid_entiteter()
│   ├── metrikker.py                         # Prometheus-metrikker (graceful no-op uten prometheus_client)
│   ├── autentisering.py                     # AUTH_MODUS=api_nokkel|oidc
│   └── verktøy.py
├── tjenester/
│   ├── workers/
│   │   ├── base_worker.py                   # Abstrakt basisklasse (lås, retry, DLQ, audit)
│   │   ├── lag0_preprocessing/lag0.py       # PreprocessingWorker
│   │   ├── lag1_ocr/lag1.py                 # OCRWorker
│   │   ├── lag2_nlp/lag2.py                 # NLPWorker (inkl. validering)
│   │   ├── lag3_routing/lag3.py             # RoutingWorker
│   │   └── reconciliation/
│   │       └── reconciliation_worker.py     # ReconciliationWorker
│   ├── api/
│   │   ├── hoved.py
│   │   └── ruter/
│   │       └── last_opp.py                  # V2.1: idempotens, /jobb, /resultat, /audit
│   ├── backup/                              # Backup-daemon (pg_dump + retention)
│   ├── oppbevaring/                         # 6-månedersregelen (sletting av innhold)
│   ├── sok/
│   └── (legacy: ocr, nlp, lag0–lag5, ruter)
├── k8s/                                     # Kubernetes-manifester (01–16)
│   ├── 14-autoskalering.yaml                # KEDA på Redis-kølengde
│   ├── 15-sikkerhetskopi.yaml               # Backup-CronJob 02:00
│   └── 16-llm.yaml                          # Model serving (vLLM)
├── overvaaking/                             # Prometheus + Grafana + Promtail
├── skript/
│   ├── init_db.py                           # V2.1: opprett 4 Postgres-tabeller
│   ├── rebuild_redis.py                     # V2.1: rebuild Redis fra Postgres
│   ├── sikkerhetskopi.py                    # Verifisert pg_dump + GFS-retention + gjenoppretting
│   ├── last_ned_modeller.py
│   └── finjuster.py
├── tester/
│   ├── test_state_machine.py
│   ├── test_idempotency.py
│   ├── test_dlq.py
│   ├── test_reconciliation.py
│   ├── test_routing_decisions.py
│   ├── test_validation.py
│   ├── test_contracts.py
│   └── (test_config, test_lag0, test_lag4, test_ruter)
└── docs/
    ├── SIKKERHETSKOPI.md                    # Backup-strategi, RPO/RTO, gjenopprettingsprosedyre
    ├── API_INTEGRASJON.md                   # Verktøy-nøytral RPA/integrasjonsguide
    ├── HYBRID_ARKITEKTUR.md                 # Redis-produksjon + Kubeflow-trening
    ├── KUBEFLOW.md                          # Kubeflow-modus: oppsett og begrensninger
    ├── kodeanalyse.md                       # Historisk kodeaudit (funn siden fikset — se README/commits)
    ├── refaktorering_analyse.md             # Historisk funksjonskartlegging (legacy-tjenester)
    └── v2_1_analyse.md                      # Historisk V2.1-migreringsnotat
```

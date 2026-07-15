# Kodeanalyse — NAV Archive Intelligence System
Generert av: Claude Code
Dato: 2026-06-24
Basert på: fullstendig scan av faktisk kildekode — ingen antagelser

> **Historisk øyeblikksbilde — IKKE dagens tilstand.** Alle kritiske
> bugs (B1-B4), funksjonsfeil (F1-F5) og arkitekturelle gap (A1-A6)
> listet under er fikset i senere commits (self-transition, kolonne-
> mismatch, validation→routing-gapet, LayoutLMv3/NB-BERT-uttrekk
> erstattet av `delt/tekstuttrekk.py`, `import psycopg2.extras`, DLQ
> for routing, m.fl.). Se README.md for gjeldende arkitektur og
> `docs/refaktorering_analyse.md`/`v2_1_analyse.md` for tilsvarende
> historiske notater. Dokumentet beholdes som revisjonsspor, ikke som
> driftsdokumentasjon.

---

## DEL 1 — Systemoversikt

**Hva systemet gjør:**
NAV Archive Intelligence System tar imot historiske PDF-dokumenter (NAV-skjemaer, vedtak, søknader), kjører OCR for tekstekstraksjon, bruker NLP for å identifisere feltene navn/fødselsnummer/dato/ytelse/adresse, validerer ekstraherte data, og sender godkjente dokumenter til Milvus for hybrid semantisk søk.

**Dokumenttyper håndtert:**
- `handskrift` — håndskrevne dokumenter (TrOCR)
- `trykt` — maskinskrevne dokumenter (PaddleOCR)
- `tabell` — tabellformat (Marker OCR)
- `blandet` — kombinert (PaddleOCR + Marker)

**Tilstandsmaskin (Postgres er kilde til sannhet):**
```
UPLOADED → QUEUED → PREPROCESSING → OCR_PROCESSING →
NLP_PROCESSING → VALIDATION → ROUTING → DONE
                                              ↘ FAILED (fra alle unntatt DONE)
```
Definert i `delt/konstanter.py`: `STATE_OVERGANGER` og `LOVLIGE_OVERGANGER`.

**Infrastruktur:**
- Redis 7 — transportlag for jobkøer (ikke persistent kilde til sannhet)
- PostgreSQL 16 — state machine, resultater, audit-logg, dead letter queue
- Milvus v2.4.5 — HNSW COSINE-indeks, hybrid BM25+vektor-søk (RRF k=60)
- Label Studio — manuell gjennomgang og annotering
- Qwen3-Embedding-0.6B (1024-dim) — embedding for søk

**AI-modeller (alle offline — ingen ekstern inferens):**
| Modell | Kilde | Bruk |
|--------|-------|------|
| TrOCR-NorHand v3 | Sprakbanken | OCR for håndskrift |
| PaddleOCR | pip | OCR for trykt tekst |
| Marker OCR | pip | OCR for tabeller/PDF |
| NB-BERT-base | NbAiLab | Dokumentklassifisering (zero-shot) |
| NB-BERT-base-NER | NbAiLab | NER-entitetsekstraksjon |
| LayoutLMv3-base | Microsoft | NER med layout-info (tokens+bokser) |
| Borealis-4B | NbAiLab | Generativ NLP-analyse |
| Qwen3-Embedding-0.6B | Qwen | Embedding for Milvus |

---

## DEL 2 — Faktisk arkitektur

To parallelle arkitekturer eksisterer i kodebasen og kjøres **samtidig** i standard `docker-compose up`:

### Arkitektur A — Legacy HTTP-tjenester (aktiv uten profil)
Seks FastAPI-mikroservices som kommuniserer via HTTP:
```
lag0 (port 8010) — bildekvalitet + forbehandling (cv2 Laplacian + CLAHE)
lag1 (port 8011) — dokumentklassifisering (Canny + Hough-linjer)
lag2 (port 8012) — OCR (HTRflow/Marker/PaddleOCR)
lag3 (port 8013) — NLP (LayoutLMv3 + NB-BERT + Borealis, lastet ved oppstart)
lag4 (port 8014) — validering (FNR mod-11, datoformat)
lag5 (port 8015) — kryssvalidering (stub — alltid godkjent)
ruter (port 8016) — ruter-logikk basert på lag0-lag4-svar
```
Disse tjenestene eksponerer HTTP-endepunkter og bruker Redis kun for jobsporing via `r.setex("jobb:{id}", ...)`.

### Arkitektur B — V2.1 Worker-tjenester (aktiv uten profil)
Fem langlevende prosesser som konsumerer Redis-køer og skriver til Postgres:
```
preprocessing_worker — lag0_preprocessing/lag0.py (PreprocessingWorker)
ocr_worker           — lag1_ocr/lag1.py (OCRWorker)
nlp_worker           — lag2_nlp/lag2.py (NLPWorker)
routing_worker       — lag3_routing/lag3.py (RoutingWorker)
reconciliation_worker — reconciliation/reconciliation_worker.py
```
Alle arver `BaseWorker` (bortsett fra `ReconciliationWorker`) og bruker BLPOP mot Redis med Postgres som tilstandskilde.

### Legacy-only tjenester (kun i `[legacy]`-profil — IKKE aktiv som standard)
```
ocr  (port 8001) — watchdog-basert OCR-koordinator (tjenester/ocr/hoved.py)
nlp  (port 8002) — NLP med ThreadPoolExecutor (tjenester/nlp/hoved.py)
```

### Ingen handoff-mekanisme
Arkitektur A og B behandler **separate** jobber via separate kodestier. API-en i `hoved.py` bruker begge sti — POST /last-opp/ skriver til Postgres (B-sti), men `/helse` sjekker `http://ocr:8001` og `http://nlp:8002` som kun finnes i legacy-profil.

---

## DEL 3 — Workers

### BaseWorker (`tjenester/workers/base_worker.py`)
Abstrakt ABC. Kjernemekanismer:

| Mekanisme | Implementasjon |
|-----------|----------------|
| Kø-lesing | `redis.blpop(queue_name, timeout=5)` — blokkerende, 5s timeout |
| Optimistisk låsing | `UPDATE jobs SET locked_by=%s WHERE locked_by IS NULL OR lock_expiry < NOW()` |
| Låse-TTL | 60s (fra `reconciliation.lock_timeout_sekunder`) |
| Retry backoff | [1s, 3s, 10s] — maks 3 forsøk (fra `redis.max_retries`) |
| Tilstandsovergang | `SELECT FOR UPDATE` → sjekk mot `LOVLIGE_OVERGANGER` → `UPDATE state` |
| Resultatlaging | `INSERT INTO results (job_id, {kolonne}) ON CONFLICT DO UPDATE` |
| Neste kø | `rpush(neste_ko, {**job, "forrige_resultat": resultat})` |
| DLQ | `INSERT INTO dead_letter_queue` + `rpush(dlq_name, ...)` + state=FAILED |
| Audit-logg | `INSERT INTO audit_log` — aldri slettet |

**`_lagre_resultat` kolonne-mapping:**
```
running_state          → results-kolonne
PREPROCESSING          → preprocess_result
OCR_PROCESSING         → ocr_result
NLP_PROCESSING         → nlp_result
VALIDATION             → validation_result
(ROUTING → ingen lagring via BaseWorker — RoutingWorker gjør det manuelt)
```

### PreprocessingWorker (`lag0_preprocessing/lag0.py`)
- Queue: `queue:preprocess`, DLQ: `dlq:preprocess`
- `running_state="PREPROCESSING"`, `done_state="OCR_PROCESSING"`
- Bildekvalitet: Laplacian variance / 1000 (capped 1.0)
- Dokumentklassifisering: Otsu-terskel → hvit-andel > 0.90 = trykt, > 0.70 = blandet, ellers = håndskrift
- **Mangler TABELL-klassifisering** (Hough-linjedeteksjon fra legacy lag1 er ikke portert hit)

### OCRWorker (`lag1_ocr/lag1.py`)
- Queue: `queue:ocr`, DLQ: `dlq:ocr`
- `running_state="OCR_PROCESSING"`, `done_state="NLP_PROCESSING"`
- GPU-semafor med `threading.Semaphore(maks_ocr_jobber)` (default 2)
- Modell-routing: HANDSKRIFT→TrOCR, TABELL→Marker, BLANDET→PaddleOCR+Marker, ellers→PaddleOCR
- **Hardkodede konfidenser:** TrOCR returnerer alltid 0.88, Marker alltid 0.90 — ikke basert på faktisk modellutgang

### NLPWorker (`lag2_nlp/lag2.py`)
- Queue: `queue:nlp`, DLQ: `dlq:nlp`
- `running_state="NLP_PROCESSING"`, `done_state="VALIDATION"`
- Gjør NLP + validering + anomali-deteksjon + valgfri kryssvalidering **inline**
- Modell-routing: TRYKT/TABELL med layout-tokens → LayoutLMv3; len(tekst)>500 → Borealis; ellers → NB-BERT
- **Kritisk stub:** `_parse_entities_from_tokens` returnerer `{"navn": tokens[0] if tokens else None}` — FNR, dato, ytelse, adresse ekstraheres aldri via LayoutLMv3-sti
- Validering: FNR mod-11, datoformat (%d.%m.%Y / %Y-%m-%d / %d/%m/%Y), kjente norske fylker, obligatoriske felt per dokumentklasse
- Anomali-score: `min(antall_feil * 0.25, 1.0)` — terskel 0.75

### RoutingWorker (`lag3_routing/lag3.py`)
- Queue: `queue:routing`, DLQ: **`dlq:validation`** (ingen `dlq:routing` finnes)
- `running_state="ROUTING"`, `done_state="DONE"`
- Bestemmer APPROVED/REVIEW/REJECTED basert på terskler og valideringsstatus
- **Bug:** leser `job.get("ocr_konfidens", 1.0)` — dette feltet finnes aldri i payload-kjeden; faktisk OCR-konfidens ligger i `job["forrige_resultat"]["confidence"]`
- APPROVED → sender til `queue:sok_indeksering` (Milvus-indeksering)
- REVIEW/REJECTED → sender til Label Studio

### ReconciliationWorker (`reconciliation/reconciliation_worker.py`)
- Kjører hvert 300s i en `while True`-løkke med `time.sleep`
- **Arver IKKE BaseWorker** — frittstående klasse
- Tre reparasjonstyper:
  1. **Stuck:** `locked_by IS NOT NULL AND lock_expiry < NOW()` → frigir lås + re-køer
  2. **Ghost:** `state NOT IN (DONE,FAILED,UPLOADED) AND locked_by IS NULL AND oppdatert < grense` → re-køer
  3. **Tapte:** `state = 'UPLOADED' AND opprettet < 5min siden` → setter QUEUED + re-køer

---

## DEL 4 — API Layer

### Endepunkter registrert i `tjenester/api/hoved.py`

**Inkluderte rutere (registrert FØR inline-endepunkter):**
```
sok_ruter         → sok.py      (POST /sok, GET /statistikk via SOK_URL)
last_opp_ruter    → last_opp.py (POST /last-opp/, GET /jobb/{id}, GET /resultat/{id}, GET /audit/{id})
gjennomgang_ruter → gjennomgang.py
```

**Inline endepunkter (registrert ETTER include_router):**
```
GET /helse        — sjekker http://ocr:8001, http://nlp:8002, http://sok:8003, label-studio
GET /statistikk   — proxy til SOK_URL/statistikk
GET /jobb/{jobb_id} — leser fra Redis (DUPLIKAT — se under)
GET /dokument/{fil_id} — søker via SOK_URL
```

**Autentisering (X-API-Key middleware):**
- Åpne stier: `/helse`, `/statistikk`
- Åpne prefikser: `/jobb/`, `/resultat/`, `/audit/`
- Alt annet krever `X-API-Key` header som matcher `API_NOKKEL` env-variabel
- Hvis `API_NOKKEL` er tom string, er autentisering deaktivert

### `last_opp.py` — V2.1 opplastingshåndtering
- `POST /last-opp/` — idempotens-nøkkel: `sha256(innhold + str(int(time.time() / 300)).encode())` — 5-minutters tids-bøtter
- Returnerer HTTP 202 med job_id
- `GET /jobb/{job_id}` — leser fra Postgres
- `GET /resultat/{job_id}` — leser fra Postgres results-tabell
- `GET /audit/{job_id}` — leser fra Postgres audit_log

**Duplikat GET /jobb/{id}:**
- `last_opp.py` linje 142 registreres VIA `include_router` (linje 50 i hoved.py) **FØR** inline-ruten
- `hoved.py` linje 85 registreres ETTER — FastAPI matcher første treff
- Postgres-varianten fra `last_opp.py` vinner, men feiler p.g.a. kolonnemismatch (se DEL 5)
- Legacy Redis-varianten i `hoved.py` er effektivt død kode

---

## DEL 5 — Datamodell

### Postgres-skjema (faktisk definert i `skript/init_db.py`)

**`jobs`-tabell:**
```sql
job_id          UUID PRIMARY KEY
idempotency_key TEXT UNIQUE NOT NULL
state           job_state ENUM
current_stage   TEXT
file_path       TEXT NOT NULL
file_name       TEXT NOT NULL
priority        INT DEFAULT 1
attempt_count   INT DEFAULT 0
max_retries     INT DEFAULT 3
last_error      TEXT
locked_by       TEXT
lock_expiry     TIMESTAMP
created_at      TIMESTAMP DEFAULT NOW()
updated_at      TIMESTAMP DEFAULT NOW()
completed_at    TIMESTAMP
```

**`results`-tabell:**
```sql
job_id              UUID PRIMARY KEY REFERENCES jobs(job_id)
preprocess_result   JSONB
ocr_result          JSONB
nlp_result          JSONB
validation_result   JSONB
routing_decision    TEXT CHECK (IN 'APPROVED','REVIEW','REJECTED')
label_studio_project INT
created_at          TIMESTAMP DEFAULT NOW()
updated_at          TIMESTAMP DEFAULT NOW()
```

**`audit_log`-tabell (slettes aldri):**
```sql
id          BIGSERIAL PRIMARY KEY
job_id      UUID REFERENCES jobs(job_id)
event_type  TEXT NOT NULL
from_state  TEXT
to_state    TEXT
worker_id   TEXT
details     JSONB
created_at  TIMESTAMP DEFAULT NOW()
```

**`dead_letter_queue`-tabell:**
```sql
id               BIGSERIAL PRIMARY KEY
job_id           UUID REFERENCES jobs(job_id)
stage            TEXT NOT NULL
error_type       TEXT NOT NULL
error_message    TEXT
payload_snapshot JSONB
retry_count      INT
created_at       TIMESTAMP DEFAULT NOW()
resolved_at      TIMESTAMP
resolved_by      TEXT
```

### Kolonnenavn-mismatch (kritisk)

Skjemaet definerer `file_path`, `file_name`, `created_at`, `updated_at`. Koden bruker et annet sett:

| Fil | Brukt kolonnenavn | Faktisk kolonnenavn |
|-----|-------------------|---------------------|
| `last_opp.py` linje 89 | `filnavn`, `fil_sti` | `file_name`, `file_path` |
| `last_opp.py` linje 110 | `oppdatert` | `updated_at` |
| `last_opp.py` linje 147 | `filnavn`, `opprettet`, `oppdatert` | `file_name`, `created_at`, `updated_at` |
| `base_worker.py` linje 144 | `oppdatert` | `updated_at` |
| `base_worker.py` linje 242 | `oppdatert` | `updated_at` |
| `reconciliation_worker.py` linje 67 | `payload` | finnes ikke |
| `reconciliation_worker.py` linje 94-98 | `oppdatert` | `updated_at` |
| `reconciliation_worker.py` linje 125-128 | `payload`, `opprettet` | finnes ikke, `created_at` |
| `reconciliation_worker.py` linje 139 | `oppdatert` | `updated_at` |

Konsekvens: **alle databaseoperasjoner som ikke er rene INSERT/SELECT på jobs.job_id/state vil feile med `psycopg2.errors.UndefinedColumn` ved runtime.**

### `delt/skjemaer.py` — Pydantic-modeller
```python
UttrukketData:  fil_id, fodselsnummer, navn, dato, adresse, signatur, ytelse,
                kontornavn, fylke, dokumenttype, utfall, oppsummering
SokResultat:    fil_id, filnavn, side_nummer, utdrag, konfidens, metadata: UttrukketData
DokumentInntak: fil_id, filnavn, fil_sti, mottatt_tidspunkt, antall_sider
```
`UttrukketData` har `signatur` (fra LayoutLMv3) og `adresse`. Disse brukes av søketjenesten men ekstraheres ikke pålitelig i workers (se NLP-stub i DEL 3).

---

## DEL 6 — Feilhåndtering

### BaseWorker-feilhåndtering
```
Forsøk 0 (feil) → vent 1s  → re-kø med retry_count=1
Forsøk 1 (feil) → vent 3s  → re-kø med retry_count=2
Forsøk 2 (feil) → vent 10s → re-kø med retry_count=3
Forsøk 3 (feil) → DLQ + state=FAILED
```
Backoff-tabell: `BACKOFF = [1, 3, 10]` i `base_worker.py`.

### Feilhåndteringshuller

**1. Dobbel tilkobling ved feil (base_worker.py linje 101):**
```python
self._haandter_feil(job, exc, psycopg2.connect(self._pg_url))
```
Åpner ny tilkobling mens `pg.rollback()` kalles på den originale. Siden state allerede ble committet til `running_state` (linje 80-81), forblir jobben i `running_state` med lås på. Kun ReconciliationWorker kan reparere dette etter lås-timeout (60s).

**2. `_oppdater_state_direkte` er ikke transaksjonssikker:**
`base_worker.py` linje 238-245: åpner separat tilkobling for å sette state=FAILED. Ingen `SELECT FOR UPDATE` — kan overrive ReconciliationWorkers reparering.

**3. Ingen DLQ for routing:**
`RoutingWorker` bruker `dlq_name=cfg["dlq"]["validation"]` (`dlq:validation`). Det finnes ingen `dlq:routing` i `config.yaml`. Routing-feil lander i valideringskøens DLQ uten merking.

**4. ReconciliationWorker-import mangler `psycopg2.extras`:**
`reconciliation_worker.py` importerer `import psycopg2` men bruker `psycopg2.extras.RealDictCursor` (linje 63, 88) og `psycopg2.extras.Json` (linje 196) uten eksplisitt `import psycopg2.extras`. I Python er ikke `psycopg2.extras` garantert tilgjengelig via `import psycopg2` alene. Dette vil gi `AttributeError` ved første kjøring.

### Label Studio-integrasjon
`BaseWorker.send_til_label_studio` gjør HTTP POST mot `{ls_url}/api/projects/{project_id}/import`.
- Token fra `LABEL_STUDIO_TOKEN` env-variabel
- Feil svelges stille (`logger.warning`) — ingen retry
- Kalles fra lag0 (bildekvalitet), lag1 (OCR-konfidens), lag2 (NLP-validering), lag3 (routing)

---

## DEL 7 — Redis og køsystem

### Køstruktur

| Kønavn | Produsent | Konsument |
|--------|-----------|-----------|
| `queue:preprocess` | `last_opp.py` + ReconciliationWorker | PreprocessingWorker |
| `queue:ocr` | PreprocessingWorker + ReconciliationWorker | OCRWorker |
| `queue:nlp` | OCRWorker + ReconciliationWorker | NLPWorker |
| `queue:validation` | NLPWorker + ReconciliationWorker | **INGEN WORKER** |
| `queue:routing` | **INGEN PRODUSENT** | RoutingWorker |
| `queue:sok_indeksering` | RoutingWorker (ved APPROVED) | **Søketjenesten via HTTP** |

| DLQ-navn | Skriver | Leser |
|----------|---------|-------|
| `dlq:preprocess` | PreprocessingWorker | Manuell/ukjent |
| `dlq:ocr` | OCRWorker | Manuell/ukjent |
| `dlq:nlp` | NLPWorker | Manuell/ukjent |
| `dlq:validation` | RoutingWorker | Manuell/ukjent |

**Kritisk gap:** `queue:validation` og `queue:routing` er effektivt koblet fra — ingen job kan nå ROUTING → DONE via normal flyt.

### Redis-persistens
- `rebuild_redis.py` leser alle ikke-terminale jobber fra Postgres og re-køer dem
- Redis-data er ikke persistent (ingen AOF/RDB i `docker-compose.yml`)
- Etter Redis-restart vil alle jobber i transit forsvinne til ReconciliationWorker reparerer dem

### BLPOP-timeout
Alle workers bruker `blpop(queue_name, timeout=5)`. `None` returneres ved timeout → `continue` i løkken. CPU-forbruk er lavt mellom jobber.

### Payload-kjede gjennom pipeline
Hvert steg legger til `forrige_resultat` i jobbens payload:
```json
{
  "job_id": "uuid",
  "fil_sti": "/data/inntak/uuid.pdf",
  "forrige_resultat": { ...forrige workers returverdi... },
  "retry_count": 0
}
```
OCRWorker leser `job.get("forrige_resultat", {}).get("preprocessed_path", job.get("fil_sti", ""))` — korrekt.
RoutingWorker leser `job.get("ocr_konfidens", 1.0)` — **feil**: OCR-konfidens er i `job["forrige_resultat"]["confidence"]`.

---

## DEL 8 — Gaps vs V2.2.2-design

### Kritiske bugs som hindrer systemet fra å kjøre

| # | Bug | Sted | Konsekvens |
|---|-----|------|------------|
| B1 | Self-transition i tilstandsmaskin | `base_worker.py` linje 80 | OCRWorker, NLPWorker, RoutingWorker kaster `UgyldigTilstandsovergang` fordi `running_state == current_state` i Postgres. Kun PreprocessingWorker fungerer. |
| B2 | Pipeline-gap: validation→routing | `lag2_nlp/lag2.py` (done_state) | Ingen worker leser `queue:validation`; RoutingWorker leser aldri fra `queue:routing`. Alle jobber stopper etter NLP. |
| B3 | Kolonnemismatch: `oppdatert`/`filnavn`/`payload` | `last_opp.py`, `base_worker.py`, `reconciliation_worker.py` | SQL-feil `UndefinedColumn` ved POST /last-opp/, state-oppdatering og reconciliation. |
| B4 | Manglende `import psycopg2.extras` | `reconciliation_worker.py` | `AttributeError` ved første reconciliation-kjøring. |

### Funksjonsfeil

| # | Problem | Sted | Konsekvens |
|---|---------|------|------------|
| F1 | OCR-konfidens alltid 1.0 i routing | `lag3_routing/lag3.py` linje 39 | OCR-terskelen i routing utløses aldri. |
| F2 | LayoutLMv3-sti ekstraherer bare navn | `lag2_nlp/lag2.py` linje 168-169 | FNR, dato, ytelse, adresse mangler alltid når LayoutLMv3 brukes. |
| F3 | Duplikat `GET /jobb/{id}` | `hoved.py` linje 85 + `last_opp.py` linje 142 | Postgres-varianten vinner men feiler (B3). Legacy Redis-varianten er effektivt utilgjengelig. |
| F4 | Lag5 er alltid stub | `lag5_kryssvalidering/lag5.py` | `anomali_score` er alltid 0.0; Milvus-oppkobling prøves men anomali-logikk mangler. |
| F5 | TrOCR/Marker hardkodet konfidens | `lag1_ocr/lag1.py` linje 118, 129 | OCR-konfidens reflekterer ikke faktisk modellnøyaktighet. |

### Arkitekturelle gaps

| # | Gap | Sted | Konsekvens |
|---|-----|------|------------|
| A1 | To uavhengige arkitekturer uten handoff | `docker-compose.yml` | Legacy lag0-lag5 og V2.1-workers kjører parallelt; API peker på begge uten koordinering. |
| A2 | `/helse` sjekker legacy-tjenester | `hoved.py` linje 62-73 | `ocr` og `nlp` under `/helse` viser alltid "ikke tilgjengelig" i standard profil. |
| A3 | Ingen ValidationWorker | `docker-compose.yml` | `queue:validation` produseres men konsumeres aldri. |
| A4 | `sok_indeksering`-køen leses av HTTP | `tjenester/sok/hoved.py` | Søketjenesten mottar data via HTTP POST `/indekser`, ikke fra Redis-kø. Redis-kø skrives men leser ukjent. |
| A5 | Manglende TABELL-klassifisering i V2.1 | `lag0_preprocessing/lag0.py` | Hough-linjedeteksjon fra legacy lag1 er ikke portert — TABELL-type aldri detektert av PreprocessingWorker. |
| A6 | Ingen `dlq:routing` | `config.yaml` | RoutingWorker bruker `dlq:validation` som sin DLQ. |

### Hva som faktisk fungerer
- `skript/last_ned_modeller.py` — laster ned alle 7 modeller fra HuggingFace via `snapshot_download`
- `skript/finjuster.py` — finjustering av TrOCR, NB-BERT og LayoutLMv3 fra Label Studio-eksporter
- `skript/rebuild_redis.py` — rebuilder Redis fra Postgres korrekt
- `tjenester/sok/hoved.py` — Milvus-integrasjon med hybrid BM25+vektor-søk (uavhengig av pipeline)
- `tjenester/lag3_nlp/lag3.py` (legacy) — fullstendig NLP-pipeline inkl. LayoutLMv3 + Borealis + NB-BERT med paralell ThreadPoolExecutor
- `tjenester/lag4_validering/lag4.py` (legacy) — korrekt FNR mod-11 + datovalidering
- `tjenester/ruter/ruter.py` (legacy) — korrekt routing-logikk basert på lag0-lag4

---

## DEL 9 — Faktisk arkitekturdiagram (tekstbasert)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          KLIENT                                              │
└────────────────────────────┬───────────────────────────────────────────────┘
                             │ HTTP
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  API (port 8000)  tjenester/api/hoved.py                                    │
│  Middleware: X-API-Key                                                       │
│  POST /last-opp/ ──────────────────────────────────────────┐                │
│  GET  /jobb/{id}  (Postgres via last_opp.py [vinner])      │                │
│  GET  /jobb/{id}  (Redis, legacy [taper — død kode])       │                │
│  GET  /sok        → proxy til sok (port 8003)              │                │
│  GET  /helse      → sjekker ocr:8001✗ nlp:8002✗ sok:8003   │                │
└────────────────────────────────────────────────────────────┼────────────────┘
                                                             │ INSERT jobs
                                                             ▼
┌──────────────────────────────────────┐  ┌─────────────────────────────────┐
│  POSTGRES (nav_archive)              │  │  REDIS                          │
│  ┌─────────┐ ┌────────┐             │  │  queue:preprocess ←─────────────┤
│  │  jobs   │ │results │             │  │  queue:ocr        ←─────────────┤
│  └─────────┘ └────────┘             │  │  queue:nlp        ←─────────────┤
│  ┌───────────────┐ ┌──────────────┐ │  │  queue:validation ←──── NLPWorker│
│  │  audit_log    │ │dead_letter_q │ │  │                   (INGEN LESER)  │
│  └───────────────┘ └──────────────┘ │  │  queue:routing    (INGEN SKRIVER)│
└──────────────────────────────────────┘  │                   ←─── RoutingW. │
                                          │  dlq:preprocess/ocr/nlp/validation│
                                          └─────────────────────────────────┘

V2.1 WORKERS (alle avhenger av postgres + redis)
┌─────────────────────┐     ┌─────────────────────┐
│ PreprocessingWorker │────▶│    OCRWorker        │
│ (FUNGERER DELVIS*) │     │ (KRASJER B1)         │
└─────────────────────┘     └─────────────────────┘
         *B3 stopper INSERT                │
                             ┌─────────────────────┐
                             │    NLPWorker        │
                             │ (KRASJER B1)         │
                             └─────────────────────┘
                                          │
                             ┌─────────────────────┐
                             │   RoutingWorker     │
                             │ (ALDRI NÅS — B2)    │
                             └─────────────────────┘
                             ┌─────────────────────┐
                             │ReconciliationWorker  │
                             │ (KRASJER B3+B4)      │
                             └─────────────────────┘

LEGACY ARKITEKTUR (lag0-lag5 HTTP, kjøres parallelt)
lag0:8010 ──▶ lag1:8011 ──▶ lag2:8012 ──▶ lag3:8013 ──▶ lag4:8014 ──▶ lag5:8015
                                                                              │
                                                                    ruter:8016 (HTTP)
                                                                              │
                                                              ┌───────────────┴──────┐
                                                              │   Søketjeneste       │
                                                              │   (port 8003)        │
                                                              │   Milvus + Qwen3     │
                                                              └──────────────────────┘
```

---

## DEL 10 — Kritiske risikoer (rangert)

| Rang | Risiko | Alvorlighet | Fil(er) |
|------|--------|-------------|---------|
| 1 | **Self-transition-bug**: alle V2.1-workers unntatt Preprocessing krasjer med `UgyldigTilstandsovergang` | KRITISK — pipeline ikke-funksjonell | `base_worker.py:80`, `delt/konstanter.py` |
| 2 | **Kolonnemismatch**: `oppdatert`/`filnavn`/`fil_sti`/`payload` finnes ikke i `init_db.py`-skjema | KRITISK — alle SQL-skriv feiler | `last_opp.py:89,110,147`, `base_worker.py:144,242`, `reconciliation_worker.py:67,94,125,139` |
| 3 | **Pipeline-gap validation→routing**: ingen worker leser `queue:validation`, ingen skriver til `queue:routing` | KRITISK — ingen jobb når DONE | `lag2_nlp/lag2.py:done_state`, `docker-compose.yml` |
| 4 | **Manglende `import psycopg2.extras`** i ReconciliationWorker | HØY — reconciliation krasjer ved oppstart | `reconciliation_worker.py:1-12` |
| 5 | **OCR-konfidens aldri lest i routing** — alltid 1.0 | HØY — OCR-terskel utløses aldri | `lag3_routing/lag3.py:39` |
| 6 | **LayoutLMv3-stub** — `_parse_entities_from_tokens` returnerer bare navn | HØY — NLP-uttrekk nesten tomt via layout-sti | `lag2_nlp/lag2.py:168-169` |
| 7 | **Duplikat `GET /jobb/{id}`** — Postgres-varianten vinner men feiler (rang 2) | MEDIUM — jobbstatus utilgjengelig | `hoved.py:85`, `last_opp.py:142` |
| 8 | **To parallelle arkitekturer uten koordinering** — legacy og V2.1 behandler separate jobber | MEDIUM — uforutsigbar oppførsel | `docker-compose.yml` |
| 9 | **Redis ikke persistent** — ingen AOF/RDB | MEDIUM — jobber i transit mistes ved Redis-restart | `docker-compose.yml:377-381` |
| 10 | **Lag5 alltid stub** — anomali-deteksjon er no-op | LAV — sikkerhetsnet mangler | `lag5_kryssvalidering/lag5.py:34-36` |

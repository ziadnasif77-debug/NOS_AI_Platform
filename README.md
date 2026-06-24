# NAV Archive Intelligence System

Et komplett AI-pipeline for automatisk digitalisering, analyse og søk i historiske NAV-dokumenter (30–60 millioner sider). Systemet kombinerer OCR, NLP og semantisk søk i en selvforbedrede arkitektur med menneskelig kvalitetssikring.

---

## Innholdsfortegnelse

- [Oversikt](#oversikt)
- [Arkitektur](#arkitektur)
- [Tjenester](#tjenester)
- [AI-modeller](#ai-modeller)
- [Forutsetninger](#forutsetninger)
- [Installasjon](#installasjon)
- [Konfigurasjon](#konfigurasjon)
- [Oppstart](#oppstart)
- [API-dokumentasjon](#api-dokumentasjon)
- [Make-kommandoer](#make-kommandoer)
- [Jobbkø og statusstyring](#jobbkø-og-statusstyring)
- [Label Studio — kvalitetssikring](#label-studio--kvalitetssikring)
- [Finjusteringspipeline](#finjusteringspipeline)
- [Dataflyt](#dataflyt)
- [Mappestruktur](#mappestruktur)
- [Utvikling](#utvikling)

---

## Oversikt

NAV Archive Intelligence System behandler historiske papirdokumenter fra NAV gjennom tre lag:

| Lag | Funksjon | Teknologi |
|-----|----------|-----------|
| **OCR** | PDF → strukturert tekst + layout | TrOCR, PaddleOCR, Marker |
| **NLP** | Feltuttrekking + klassifisering + oppsummering | LayoutLMv3, NB-BERT, Borealis-4B |
| **Søk** | Hybridssøk over hele arkivet | Milvus, BM25, RRF |

Dokumenter som OCR-tjenesten er usikker på (konfidens < 85 %) sendes automatisk til **Label Studio** for menneskelig gjennomgang. Korreksjoner brukes til å finjustere modellene, slik at systemet kontinuerlig forbedrer seg.

---

## Arkitektur

```
                      ┌─────────────────────────────────────────┐
                      │           INNTAK (PDF-filer)             │
                      └────────────────┬────────────────────────┘
                                       │ Watchdog
                      ┌────────────────▼────────────────────────┐
                      │             OCR-TJENESTE (8001)          │
                      │  ┌──────────────────────────────────┐   │
                      │  │ 1. PDF → PNG (PyMuPDF)            │   │
                      │  │ 2. Forbehandling (OpenCV)         │   │
                      │  │ 3. Klassifisering                 │   │
                      │  │    handskrift → TrOCR-NorHand     │   │
                      │  │    trykt      → PaddleOCR 3.0     │   │
                      │  │    tabell     → Marker OCR        │   │
                      │  └──────────────┬───────────────────┘   │
                      └─────────────────┼───────────────────────┘
                             konfidens  │
                    ┌──────────────────►│◄──────────────────┐
                    │  < 85 %           │          >= 85 %   │
                    ▼                   │                    ▼
        ┌──────────────────┐            │     ┌─────────────────────────────┐
        │  LABEL STUDIO     │            │     │      NLP-TJENESTE (8002)    │
        │  (8080)           │            │     │  ┌───────────────────────┐  │
        │  Menneskelig      │            │     │  │ LayoutLMv3            │  │
        │  korreksjon +     │            │     │  │ (feltuttrekking)      │  │
        │  LayoutLMv3-      │            │     │  │ + NB-BERT (klasse)    │  │
        │  annotering       │            │     │  │ + Borealis-4B (summ.) │  │
        └────────┬──────────┘            │     └───────────┬───────────────┘  │
                 │ make send-til-trening  │                 │                    │
                 ▼                        │                 ▼                    │
        ┌──────────────────┐             │     ┌─────────────────────────────┐ │
        │  FINJUSTERING     │             │     │      SØK-TJENESTE (8003)    │ │
        │  TrOCR / NB-BERT  │             │     │  Milvus + BM25 + RRF        │ │
        │  / LayoutLMv3     │             │     │  Qwen3-Embedding-0.6B       │ │
        └──────────────────┘             │     └─────────────────────────────┘ │
                                          │                                       │
                      ┌───────────────────▼───────────────────────────────────┐  │
                      │                API-TJENESTE (8000)                    │  │
                      │  POST /last-opp  GET /sok  GET /jobb/{id}             │  │
                      └───────────────────────────────────────────────────────┘  │
```

Et fullstendig flytdiagram finnes i [`docs/flytdiagram.svg`](docs/flytdiagram.svg).

---

## Tjenester

### `ocr` — OCR-tjeneste (port 8001)
Overvåker `data/inntak/` med Watchdog. Konverterer PDF til PNG, forbehandler bildet (deskew, CLAHE, binarisering), klassifiserer dokumenttypen og kjører riktig OCR-motor.

- **Semaphore:** Maks `MAKS_OCR_JOBBER` (standard: 2) samtidige jobber — hindrer GPU OOM
- **Jobbsporing:** Leser `.jobb.json`-sidecar og oppdaterer status i Redis

### `nlp` — NLP-tjeneste (port 8002)
Mottar OCR-output og kjører klassifisering og feltuttrekking **parallelt** med `ThreadPoolExecutor`:
- **NB-BERT** (zero-shot): dokumenttype, ytelse, utfall
- **LayoutLMv3**: navn, fødselsnummer, dato, adresse, signatur — bruker tekst + layout
- **Borealis-4B**: norsk oppsummering + fylkeutrekking (regex over 24 norske fylker)

Faller tilbake til NB-BERT-NER hvis LayoutLMv3 ikke er finjustert ennå.

### `sok` — Søketjeneste (port 8003)
Hybrid semantisk + nøkkelordssøk:
- **Milvus** (HNSW, COSINE): vektorsøk med Qwen3-Embedding-0.6B (1024 dim)
- **BM25Okapi**: tradisjonelt nøkkelordssøk
- **RRF** (k=60): Reciprocal Rank Fusion kombinerer de to

BM25-indeksen gjenoppbygges automatisk fra Milvus ved oppstart (synkronisering etter restart).

### `api` — Ekstern API (port 8000)
FastAPI med X-API-Key autentisering. Videresender til interne tjenester.

| Endepunkt | Metode | Beskrivelse |
|-----------|--------|-------------|
| `/last-opp/` | POST | Last opp PDF. Returnerer `jobb_id` umiddelbart |
| `/jobb/{jobb_id}` | GET | Sjekk behandlingsstatus (åpen, ingen nøkkel) |
| `/sok` | POST | Hybrid semantisk + nøkkelordssøk |
| `/dokument/{fil_id}` | GET | Hent ett dokument |
| `/gjennomgang/ko` | GET | Antall dokumenter til gjennomgang i Label Studio |
| `/gjennomgang/korriger/{fil_id}` | POST | Send korreksjon til Label Studio |
| `/helse` | GET | Helsesjekk alle tjenester |
| `/statistikk` | GET | Antall dokumenter i arkivet |

### `label-studio` — Kvalitetssikring (port 8080)
Selvhostet Label Studio for OCR-korreksjon og LayoutLMv3-annotering. Bilder deles via felles volum (`GJENNOMGANG_STI`) slik at Label Studio kan vise dem.

### `pipeline_dashboard` — Overvåkingsdashboard (port 5000)
Flask + Server-Sent Events (SSE) for live visning av pipeline-status. Trådsikker buffer med `threading.Lock`.

### `milvus`, `etcd`, `minio` — Vektorinfrastruktur
Milvus v2.4.5 med etcd (konfiglagrings) og MinIO (objektlagring).

### `redis` — Jobbkø og statusstyring
Redis 7 for asynkron jobbsporing. 24 timers TTL per jobb.

---

## AI-modeller

Alle modeller lastes ned én gang og lagres lokalt. Systemet kjører **100 % offline** etter første nedlasting (~17 GB totalt).

| Nøkkel | Modell-ID | Størrelse | Bruk |
|--------|-----------|-----------|------|
| `norhand` | `Sprakbanken/TrOCR-norhand-v3` | ~1,2 GB | Historisk håndskrift-OCR |
| `nb-bert` | `NbAiLab/nb-bert-base` | ~440 MB | Dokumentklassifisering (zero-shot) |
| `nb-bert-ner` | `NbAiLab/nb-bert-base-ner` | ~440 MB | Navngitt entitetsgjenkjenning (fallback) |
| `borealis` | `NbAiLab/borealis-4b-instruct-preview` | ~8 GB | Norsk LLM — oppsummering + analyse |
| `qwen3-embed` | `Qwen/Qwen3-Embedding-0.6B` | ~1,2 GB | Tekstembedding for vektorsøk |
| `layoutlmv3` | `microsoft/layoutlmv3-base` | ~500 MB | Feltuttrekking (tekst + layout) |

**Merk:** LayoutLMv3 må finjusteres på NAV-data før det gir nyttige resultater. Se [Finjusteringspipeline](#finjusteringspipeline).

---

## Forutsetninger

- **Docker** ≥ 24 og **Docker Compose** ≥ 2.20
- **NVIDIA GPU** med ≥ 12 GB VRAM (anbefalt for Borealis-4B)
- **NVIDIA Container Toolkit** installert
- Python 3.11+ (kun for skript utenfor Docker)
- ≥ 30 GB ledig diskplass (modeller + data)

### GPU-verifisering
```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

---

## Installasjon

### 1. Klon repositoriet
```bash
git clone https://github.com/ziadnasif77-debug/nav.git
cd nav
```

### 2. Opprett `.env`-fil
```bash
cp .env.example .env
# Rediger .env og sett minst:
#   API_NOKKEL=<sterk-tilfeldig-streng>
#   LABEL_STUDIO_API_KEY=<din-label-studio-nokkel>
#   GPU_ENHET=cuda:0
```

### 3. Last ned alle AI-modeller
```bash
pip install huggingface_hub marker-pdf
make last-ned-modeller
```
Dette laster ned ~17 GB og tar 20–60 minutter avhengig av internettforbindelsen. Trenger bare gjøres én gang.

### 4. Opprett datamapper
```bash
mkdir -p data/{inntak,behandlet,gjennomgang,finjustering,logger}
```

---

## Konfigurasjon

Alle innstillinger settes i `.env`. Se `.env.example` for fullstendig oversikt.

| Variabel | Standard | Beskrivelse |
|----------|----------|-------------|
| `DATA_STI` | `./data` | Rotmappe for alle data |
| `MODELLER_STI` | `./modeller` | Lokal modellmappe |
| `INNTAK_STI` | `./data/inntak` | PDF-filer som skal behandles |
| `BEHANDLET_STI` | `./data/behandlet` | OCR-output |
| `GJENNOMGANG_STI` | `./data/gjennomgang` | Delt volum med Label Studio |
| `FINJUSTERING_STI` | `./data/finjustering` | Treningsdata |
| `KONFIDENS_TERSKEL` | `85` | Prosent — under dette → Label Studio |
| `GPU_ENHET` | `cuda:0` | GPU-enhet |
| `API_NOKKEL` | *(tom)* | X-API-Key for eksternt API. Tom = ingen autentisering |
| `REDIS_URL` | `redis://redis:6379/0` | Redis-adresse |
| `MAKS_OCR_JOBBER` | `2` | Maks samtidige OCR-jobber |
| `LABEL_STUDIO_API_KEY` | — | API-nøkkel fra Label Studio UI |
| `LABEL_STUDIO_OCR_PROSJEKT_ID` | `1` | Prosjekt-ID i Label Studio |

---

## Oppstart

```bash
# Start alle tjenester
make start

# Sjekk at alt er oppe
make helse

# Se logger i sanntid
make logger

# Stop
make stopp
```

Første oppstart tar lenger tid fordi Docker-bildene bygges og modellene lastes inn i GPU-minnet.

### Verifiser at API fungerer
```bash
# Uten autentisering (hvis API_NOKKEL er tom)
curl http://localhost:8000/helse

# Med autentisering
curl -H "X-API-Key: din-nokkel" http://localhost:8000/helse
```

---

## API-dokumentasjon

### Last opp et dokument
```bash
curl -X POST http://localhost:8000/last-opp/ \
  -H "X-API-Key: din-nokkel" \
  -F "fil=@/sti/til/dokument.pdf"
```
**Svar:**
```json
{
  "jobb_id": "f8e194242467",
  "filnavn": "dokument.pdf",
  "status": "i_ko",
  "sjekk_status": "/jobb/f8e194242467"
}
```

### Sjekk behandlingsstatus
```bash
curl http://localhost:8000/jobb/f8e194242467
```
**Mulige statuser:**
| Status | Beskrivelse |
|--------|-------------|
| `i_ko` | Fil mottatt, venter på OCR |
| `ocr_pagar` | OCR pågår |
| `nlp_pagar` | NLP-analyse pågår |
| `gjennomgang` | Lav konfidens → sendt til Label Studio |
| `fullfort` | Indeksert i søkemotoren |
| `feil` | Feil under behandling (se `feil`-feltet) |

### Søk i arkivet
```bash
# Enkel tekst-søk
curl -X POST http://localhost:8000/sok \
  -H "X-API-Key: din-nokkel" \
  -H "Content-Type: application/json" \
  -d '{"sporsmal": "dagpenger søknad 1985", "antall": 10}'

# Med filtre
curl -X POST http://localhost:8000/sok \
  -H "X-API-Key: din-nokkel" \
  -H "Content-Type: application/json" \
  -d '{
    "sporsmal": "uføretrygd",
    "filtre": {
      "ytelse": "uforetrygd",
      "fylke": "Rogaland"
    },
    "antall": 5
  }'
```

### Bruk via Makefile
```bash
# Søk direkte fra terminalen
make sok SPORSMAL="Ola Nordmann 1234567890"

# Last opp en fil
make last-opp FIL="skjema.pdf"
```

---

## Make-kommandoer

```bash
make start                  # Start alle Docker-tjenester
make stopp                  # Stop alle tjenester
make restart                # Restart alle tjenester
make logger                 # Vis logger i sanntid
make helse                  # Sjekk alle tjenester

make last-ned-modeller      # Last ned AI-modeller fra HuggingFace (~17 GB)
make finjuster              # Finjuster TrOCR + NB-BERT + LayoutLMv3

make label-studio           # Åpne Label Studio i nettleseren
make eksporter-korreksjoner # Eksporter korreksjoner fra Label Studio til JSON
make send-til-trening       # Eksporter + finjuster automatisk

make lag-datasett           # Generer Label Studio-oppgaver for LayoutLMv3-annotering
make konverter-annotasjoner # Konverter Label Studio-eksport til LayoutLMv3-treningsformat

make sok SPORSMAL="..."     # Søk direkte fra terminalen
make last-opp FIL="..."     # Last opp én PDF-fil
```

---

## Jobbkø og statusstyring

Systemet bruker **Redis** for asynkron jobbsporing med 24 timers TTL.

### Slik fungerer det

1. `POST /last-opp/` lagrer PDF-filen i `data/inntak/` og returnerer **umiddelbart** med `jobb_id`
2. En `.jobb.json`-sidecarfil skrives ved siden av PDF-en med jobbens ID
3. **Watchdog** i OCR-tjenesten plukker opp filen og leser sidecar-en
4. OCR-tjenesten oppdaterer statusen i Redis for hvert steg
5. Klienten poller `GET /jobb/{jobb_id}` for å følge med

### Backpressure
`MAKS_OCR_JOBBER` (standard: 2) begrenser antall samtidige OCR-jobber via en `threading.Semaphore`. Filer som ankommer mens grensen er nådd, venter i Watchdog-køen. Dette hindrer GPU-minnefeil (OOM) ved masseopplasting.

---

## Label Studio — kvalitetssikring

### Oppsett
1. Start systemet: `make start`
2. Åpne Label Studio: `make label-studio` (http://localhost:8080)
3. Opprett API-nøkkel i Label Studio → Settings → Account → Access Token
4. Sett `LABEL_STUDIO_API_KEY` i `.env`
5. Opprett to prosjekter:
   - **OCR-korreksjon** (prosjekt ID 1): for lav-konfidens dokumenter
   - **LayoutLMv3-annotering** (prosjekt ID 2): for navngitt entitetsmerking

### Workflow for OCR-korreksjon
Dokumenter med OCR-konfidens under 85 % sendes automatisk til Label Studio. Bilder kopieres til `data/gjennomgang/bilder/` som Label Studio serverer via `/data/local-files/?d=bilder/`.

### Workflow for LayoutLMv3-trening
```bash
# Steg 1: Generer Label Studio-oppgaver fra PDF-filer
make lag-datasett
# → Kjører PaddleOCR og lager oppgaver med tokens + bounding boxes

# Steg 2: Annotter i Label Studio
# (merk NAVN, FODSELSNUMMER, DATO, ADRESSE, SIGNATUR manuelt)

# Steg 3: Eksporter og konverter
make konverter-annotasjoner
# → Konverterer til LayoutLMv3-treningsformat

# Steg 4: Tren modellen
make finjuster
```

---

## Finjusteringspipeline

Systemet støtter finjustering av tre modeller:

### TrOCR-NorHand
Forbedrer håndskrift-OCR basert på menneskelige korreksjoner fra Label Studio.
- Treningsdata: `data/finjustering/trocr_*.json`
- Format: `{"fil_sti": "...", "tekst": "korrekt tekst"}`
- Metode: Seq2SeqTrainer, 3 epoker, lr=5e-5

### NB-BERT
Forbedrer dokumentklassifisering.
- Treningsdata: `data/finjustering/nb_bert_*.json`
- Format: `{"tekst": "...", "etikett": "soknad|vedtak|korrespondanse"}`
- Metode: Trainer, 3 epoker, lr=2e-5

### LayoutLMv3
Forbedrer feltuttrekking med 6 etiketter:

| Etikett | ID | Beskrivelse |
|---------|-----|-------------|
| `NAVN` | 0 | Fullt navn |
| `FODSELSNUMMER` | 1 | 11-sifret personnummer |
| `DATO` | 2 | Dato |
| `ADRESSE` | 3 | Postadresse |
| `SIGNATUR` | 4 | Signatur |
| `O` | 5 | Ingen etikett |

- Treningsdata: `data/finjustering/layoutlmv3_*.json`
- Metode: Trainer, 5 epoker, lr=5e-5
- `ignore_mismatched_sizes=True` lar base-modellen få ny klassifiseringshode

**Alle finjusteringer tar automatisk backup** med tidsstempel (`modeller/norhand-backup-YYYYMMDD_HHMMSS/`) før modellen overskrives.

### Automatisk eksport og trening
```bash
make send-til-trening
# Tilsvarer: eksporter_fra_label_studio.py && finjuster.py
# Etter fullføring: OCR-tjenesten laster inn nye modeller uten omstart
```

---

## Dataflyt

```
PDF
 │
 ├─ pdf_til_bilde()         PyMuPDF: første side → PNG (2x zoom)
 ├─ forbehandle_bilde()     OpenCV: deskew + CLAHE + Otsu-binarisering
 ├─ klassifiser_side()      OpenCV: HANDSKRIFT / TRYKT / TABELL / BLANDET
 │
 ├─ [HANDSKRIFT] kjor_htrflow()     HTRflow + TrOCR-NorHand → tekst
 ├─ [TRYKT]      kjor_paddleocr()   PaddleOCR 3.0 → tekst + tokens + bokser
 └─ [TABELL]     kjor_marker()      Marker OCR → tekst + markdown
      │
      ├─ konfidens >= 85%
      │    └─ NLP: LayoutLMv3 + NB-BERT (parallell) + Borealis-4B
      │         └─ Søk: Qwen3-embedding → Milvus + BM25 → indeksert
      │
      └─ konfidens < 85%
           └─ Label Studio: menneskelig korreksjon
                └─ make send-til-trening → finjustering → reload
```

---

## Mappestruktur

```
nav/
├── docker-compose.yml          # Alle 9 tjenester + infrastruktur
├── Makefile                    # Alle driftskommandoer
├── .env.example                # Konfigurasjonsmalen
├── .gitignore
│
├── delt/                       # Delt kode mellom alle tjenester
│   ├── skjemaer.py             # Pydantic-modeller (DokumentInntak, UttrukketData, ...)
│   ├── konstanter.py           # Dokumenttyper, statuser
│   └── verktøy.py              # Logging, JSON-verktøy, UUID-ID-generator
│
├── tjenester/
│   ├── ocr/
│   │   ├── hoved.py            # Watchdog + OCR-routing + jobbsporing
│   │   ├── klassifiserer.py    # OpenCV-dokumentklassifisering
│   │   ├── pipeline.yaml       # HTRflow-konfigurasjon
│   │   ├── helsesjekk.py       # Docker healthcheck
│   │   └── krav.txt            # Python-avhengigheter
│   ├── nlp/
│   │   ├── hoved.py            # LayoutLMv3 + NB-BERT + Borealis (parallell)
│   │   ├── helsesjekk.py
│   │   └── krav.txt
│   ├── sok/
│   │   ├── hoved.py            # Milvus + BM25 + RRF + BM25-gjenoppbygging
│   │   ├── helsesjekk.py
│   │   └── krav.txt
│   └── api/
│       ├── hoved.py            # API-nøkkel-middleware + /jobb/<id>
│       ├── ruter/
│       │   ├── last_opp.py     # Asynkron opplasting med jobb_id
│       │   ├── sok.py          # Søke-endepunkter
│       │   └── gjennomgang.py  # Label Studio-integrasjon
│       └── krav.txt
│
├── skript/
│   ├── last_ned_modeller.py    # Engangs-nedlasting fra HuggingFace
│   ├── finjuster.py            # TrOCR + NB-BERT + LayoutLMv3 trening
│   ├── eksporter_fra_label_studio.py   # Eksporter korreksjoner → treningsdata
│   ├── send_til_label_studio.py        # Send lav-konfidens dok. til Label Studio
│   ├── lag_layoutlmv3_datasett.py      # PDF → Label Studio-oppgaver (PaddleOCR)
│   ├── konverter_til_layoutlmv3.py     # Label Studio-eksport → treningsformat
│   └── sjekk_helse.py          # Helse-sjekk for alle tjenester
│
├── pipeline_dashboard/
│   ├── app.py                  # Flask + SSE (trådsikker)
│   ├── pipeline.py             # Pipeline-faser og helsesjekker
│   └── maler/indeks.html       # Dashboard-UI
│
├── docs/
│   └── flytdiagram.svg         # Komplett arkitekturdiagram
│
└── data/                       # Opprettet ved installasjon
    ├── inntak/                 # Drop PDF-filer her (eller via API)
    ├── behandlet/              # OCR-output (raw/ + renset/)
    ├── gjennomgang/            # Delt med Label Studio (bilder + annoteringer)
    ├── finjustering/           # Treningsdata og eksporterte annoteringer
    └── logger/                 # Tjenestologger
```

---

## Utvikling

### Kjør én tjeneste lokalt (uten Docker)
```bash
# Eksempel: API-tjenesten
pip install -r tjenester/api/krav.txt
cd tjenester/api
API_NOKKEL="" SOK_URL=http://localhost:8003 uvicorn hoved:app --reload --port 8000
```

### Syntaks-sjekk alle filer
```bash
python3 -m py_compile delt/*.py tjenester/**/*.py skript/*.py
```

### Lokal søk uten Docker
```bash
make sok SPORSMAL="dagpenger 1985"
# Tilsvarer:
curl -X POST http://localhost:8000/sok \
  -H "Content-Type: application/json" \
  -d '{"sporsmal": "dagpenger 1985"}'
```

### Manuell batch-import av mange PDF-filer
Kopier PDF-filene direkte til `data/inntak/`. Watchdog plukker dem opp automatisk og respekterer semaphore-grensen.

```bash
cp /sti/til/mange_filer/*.pdf data/inntak/
# Maks 2 behandles parallelt, resten venter
```

---

## Sikkerhet

- **Autentisering:** X-API-Key header for alle endepunkter unntatt `/helse`, `/statistikk` og `/jobb/<id>`
- **Offline:** Alle AI-modeller kjører lokalt — ingen data sendes til eksterne tjenester
- **GDPR:** Sensitiv persondata (fødselsnummer, navn, adresse) forlater aldri serveren
- **API-nøkkel:** Sett `API_NOKKEL` til en sterk tilfeldig streng i produksjon (`openssl rand -hex 32`)

---

## Kjente begrensninger

| Begrensning | Forklaring |
|-------------|------------|
| LayoutLMv3 utrenet | Krever annoterte NAV-dokumenter via Label Studio før feltuttrekking fungerer optimalt |
| Kun første PDF-side | Watchdog behandler bare side 1. Flersidig støtte er ikke implementert |
| Enkeltfiloppladning | `POST /last-opp/` tar én fil om gangen |
| Ingen OAuth2/JWT | API bruker enkel statisk nøkkel — tilstrekkelig for intern bruk |

---

## Lisens

Dette prosjektet er utviklet for internt bruk med historiske NAV-dokumenter.

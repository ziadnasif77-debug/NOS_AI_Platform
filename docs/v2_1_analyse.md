# NAV Archive Intelligence System — V2.1 Analyse

> **Historisk migreringsnotat** fra overgangen til V2.1-arkitekturen
> (Postgres som kilde til sannhet, BaseWorker, DLQ, reconciliation).
> Alle punkter under «V2.1 Endringer» er fullført og er nå beskrevet
> som gjeldende arkitektur i README.md. Siden er skrevet er systemet
> også utvidet med flersidige PDF-er, deterministisk feltuttrekk,
> hybrid Kubeflow-arkitektur, observability og OIDC — se README.md for
> nåværende stand.

## Kartlegging av eksisterende kode

### `config/`
- `config.yaml` — sentralkonfig med lag, porter, stier, modeller, terskler, gpu, redis, label_studio
- `config_loader.py` — laster YAML og eksponerer `CONFIG`

### `delt/`
- `konstanter.py` — statuser, dokumenttyper, terskler, mappenavn
- `skjemaer.py` — Pydantic-modeller for API
- `verktøy.py` — logging-oppsett

### `tjenester/api/`
- `hoved.py` — FastAPI-app, middleware for API-nøkkel, inkluderer rutere
- `ruter/last_opp.py` — POST /last-opp, sender til OCR via HTTP
- `ruter/gjennomgang.py` — gjennomgang-endepunkter
- `ruter/sok.py` — søkeendepunkter

### `tjenester/workers/` (V2-arkitektur)
- `lag0_preprocessing/lag0.py` — preprocessing worker (eksisterer)
- `lag1_ocr/lag1.py` — OCR worker (eksisterer)

### `tjenester/lag*_*/` (gamle HTTP-baserte tjenester)
- lag0 — bildekvalitet
- lag1 — klassifisering
- lag2 — OCR (PaddleOCR/HTRflow/Marker)
- lag3 — NLP (LayoutLMv3/NB-BERT/Borealis)
- lag4 — validering (fnr, dato, fylke)
- lag5 — kryssvalidering (Milvus)
- ruter/ — ruter-tjeneste

### `legacy/`
- `ocr/` — gammel OCR-tjeneste (profiles: [legacy])
- `nlp/` — gammel NLP-tjeneste (profiles: [legacy])

### `skript/`
- `init_db.py` — DB-initialisering (eksisterer, skal oppdateres)
- `rebuild_redis.py` — Redis rebuild (skal opprettes)
- Diverse hjelpeskript

### `docker-compose.yml`
- Definerer lag0-lag5, ruter, api, redis, milvus, etcd, minio, label-studio
- Legacy: ocr, nlp (profiles: [legacy])

## V2.1 Endringer

1. **Postgres state machine** — 9 tilstander, lovlige overganger
2. **BaseWorker** — grunnklasse med locking, retry, DLQ, audit log
3. **Workers**: preprocessing, OCR, NLP, routing, reconciliation
4. **Idempotency** i API via SHA256-hash
5. **Audit log** — alle overganger logges til Postgres
6. **DLQ** — Dead Letter Queue etter maks retries
7. **Reconciliation** — periodisk reparasjon av stuck/ghost jobs

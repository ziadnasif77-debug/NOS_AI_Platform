# ADR-001 — Gjenbruk vs. nybygg av det slettede distribuerte systemet

- **Status:** Forslag (betinget av at volumet bekreftes — se
  [README](README.md)).
- **Dato:** 2026-07-21
- **Kontekst:** «recover-and-adapt» er ledende, ikke låst. Blandede
  profiler (container + luftgap), gateway eier auth, bursty last. Det
  distribuerte systemet ble slettet i `7b2c2cd` fordi volumet var lavt;
  briefen reverserer den premissen *hvis* volumet stemmer.

## Beslutning (foreslått)

Gjenbruk **rørleggerarbeidet** (kø/worker/tilstandsmaskin/DLQ/audit-skjema
+ testene). Hent **OCR, konfidens og rutebeslutning fra dagens monolitt**,
ikke fra de slettede lagene. Forkast det som er koblet til søk (fjernet
funksjon) og Kubeflow.

| Komponent | Verdikt | Begrunnelse |
|-----------|---------|-------------|
| `workers/base_worker.py` | **Gjenbruk & tilpass** | Ekte idempotens/lås/retry/DLQ/audit. Tilpass: `/app`-hardkoding, køabstraksjon, DB-pool, dual-write-gap |
| `workers/reconciliation_worker.py` | **Gjenbruk & tilpass** | Durabilitets-ryggraden; viktigere under bursty last |
| `skript/init_db.py` (skjema) | **Gjenbruk & utvid** | Solid; mangler versjons-kolonner, audit-immutabilitet, oppbevaring |
| `delt/konstanter.py` (tilstandsmaskin) | **Gjenbruk** | Ren lineær SM + FAILED + self-transitions |
| `lag3` beslutningslogikk | **Tilpass** | Behold terskelstruktur; **fjern Milvus**; **avklar REJECTED** |
| `lag0_preprocessing` | Gjenbruk **Fase 2** | Forhåndsskissert deskew/denoise, ikke Fase 1 |
| `ruter/ruter.py` | **Forkast** | Konkurrerende ruter, søk-koblet, fail-open |
| `lag1_ocr.py` | **IKKE gjenbruk** | Fabrikkert konfidens + Paddle/Marker; dagens OCR er bedre |
| `kfp_steg` / Kubeflow | **Forkast** | Erstattet av `kjor_treningslop` + MLflow + kvalitetsport |
| `sok/` | **Forkast** | Funksjonen er fjernet |
| Testsuite (dlq/idempotens/state/reconciliation/routing/contracts) | **Gjenbruk som akseptansenett** | Porten for tilpasningen — ikke stol på gjenbrukskode før disse er grønne på den tilpassede versjonen |

## Alternativer vurdert

- **Nybygg fra bunn:** forkastet — re-utleder mønstre som allerede er
  testet her (idempotens, DLQ, reconciliation).
- **Gjenbruk alt uendret:** forkastet — drar med søk, Paddle/Marker,
  fabrikkert konfidens og en konkurrerende fail-open-ruter.

## Konsekvenser

- Kø/worker/audit-kjernen gjenbrukes (uker spart).
- OCR/konfidens/beslutning kommer fra dagens system, som allerede har
  løst F3-1 (ekte regionvekt-konfidens) — se
  [revisjon-gjenbrukskode.md](revisjon-gjenbrukskode.md).
- Den gjenbrukte testsuiten er sikkerhetsnettet; kode regnes ikke som
  restaurert før dens tester passerer på den tilpassede versjonen.
- REJECTED må avgjøres som *policy* (implementer en ekte auto-avvis, eller
  fjern det døde utfallet for ærlighet).

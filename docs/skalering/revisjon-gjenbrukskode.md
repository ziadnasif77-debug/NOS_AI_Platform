# Fil-nivå revisjon av gjenbrukskoden (før restaurering)

> Kildene er lest fra `7b2c2cd^` (commit før slettingen). Ingenting er
> restaurert. Dette er porten for om — og hvordan — hver fil gjenbrukes.
> Se [ADR-001](ADR-001-gjenbruk-vs-nybygg.md) for verdiktene.

## `workers/base_worker.py` (458 linjer) — høy kvalitet

- ✅ Idempotens, eierskaps-sjekket optimistisk lås, retry/backoff, DLQ
  (Postgres + Redis), audit, graceful shutdown, gift-jobb-vern via DB
  `attempt_count` (ikke bare payload).
- ⚠️ `sys.path.insert(0, "/app")` (L23) — Linux/container-sti, brekker
  native Windows/luftgap.
- ⚠️ Tilkobling-per-jobb, flere tilkoblinger per jobb (L89–134) — ingen
  pool → tilkoblings-utsulting ved skala. **Må ha connection-pool.**
- ⚠️ **Dual-write-gap** (L104–108): jobb settes DONE og *deretter*
  Redis-push til neste kø — ikke atomisk. Krasj imellom = DONE men aldri
  videresendt. Reconciliation demper; `PostgresKo` (ADR-002) fjerner det.
- **Verdikt: Gjenbruk & tilpass.**

## Skjema (`skript/init_db.py`) — solid, allerede herdet

- ✅ `idempotency_key UNIQUE`, DLQ med `resolved_at/by`, reconciliation-
  indekser, unik indeks mot duplikate sider. Fix-ID-er (F1-5/F2-6/F2-9)
  vitner om en tidligere revisjonsrunde.
- 🔴 **Ingen versjons-kolonner** — §3.3 krever modell-/regel-/terskel-/
  LLM-versjon per record for reproduserbarhet. Må utvides.
- 🔴 `audit_log` er **muterbar, ingen immutabilitetsgaranti** (§6.4).
- 🔴 Ingen oppbevarings-affordans.
- **Verdikt: Gjenbruk & utvid** (utgangspunkt for audit-skjemaet).

## `lag3_routing/lag3.py` (189) — REJECTED-bekymringen bekreftet

- 🔴 `_bestem_beslutning` (L81–105) returnerer **kun APPROVED / REVIEW —
  REJECTED emitteres aldri**, selv om docstring (L3), skjema-CHECK og
  handleren (L64) alle later som tre-veis. Reelt to-veis.
- 🔴 **Milvus/søk-kobling** (L63, L145–184) må fjernes (funksjon borte).
- ⚠️ Leser numerisk `ocr_confidence` som (for håndskrift) er fabrikkert
  oppstrøms — se under.
- **Verdikt: Tilpass** — fjern søk, avklar REJECTED som policy;
  terskelstrukturen er gjenbrukbar.

## `lag1_ocr.py` (173) — fabrikkert-konfidens-stedet (F3-1)

- 🔴 TrOCR returnerer hardkodet **`0.88`** (L147), Marker **`0.90`**
  (L158); kun PaddleOCR er ekte (L129).
- 🟢 *Dempet for auto-godkjenning*: `konfidens_er_ekte`-porten (L76–77)
  tvinger fabrikkert-konfidens-veier til menneskelig gjennomgang — ingen
  slik dok auto-godkjennes (bevisst, dokumentert).
- 🔴 **Men den falske `0.88` lagres og auditeres som ekte** (L93) og mater
  lag3s beslutning — en usann audit-record i et statlig system.
- 🔴 Motorene er Paddle/Marker/TrOCR — erstattet. Dagens `region_ocr`
  beregner ekte lengdevektet konfidens fra regionscorer og ruter
  håndskrift til gjennomgang, så F3-1-feilmodusen er allerede håndtert.
- **Verdikt: IKKE gjenbruk.** Pakk dagens OCR inn i worker-mønsteret i
  stedet. *Verifiser norhands regionscore-kilde ved innpakking* så ingen
  placeholder sniker seg inn igjen.

## `ruter/ruter.py` (64) — forkast

- 🔴 Konkurrerende *andre* ruter (annet vokabular `sok`/`label_studio`),
  søk-koblet.
- 🔴 **Fail-open**: manglende oppstrøms-data defaulter til `1.0`
  konfidens → «godkjent» (L35, L40). Farlig default for PII.
- **Verdikt: Forkast**; rut inne i worker-pipelinen.

## `delt/konstanter.py` (80) — tilstandsmaskin, ren

- ✅ Lineær SM + FAILED fra hvert steg + self-transitions + NLP→ROUTING-
  hopp; terminaltilstander DONE/FAILED.
- Merk: **ingen REJECTED livssyklus-tilstand** — konsistent med lag3.
- **Verdikt: Gjenbruk** (tilstandsmaskin + kønavn).

## Bunnlinje

Mekanikken (worker, kø, tilstandsmaskin, DLQ, audit-skjema, tester) er
sterk og verdt å gjenbruke. Beslutnings-/OCR-/ruter-laget er der råten
sitter (konfidens lagret-som-ekte, dødt REJECTED, konkurrerende
fail-open-ruter, søk-kobling) — og det meste er allerede løst bedre i
dagens monolitt. **Gjenbruk rørleggerarbeidet; hent OCR/konfidens/
beslutning fra dagens system; avgjør REJECTED som policy.**

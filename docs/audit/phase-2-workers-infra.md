# Fase 2 — Workers, Redis og Postgres

**Metode:** full kodegjennomgang (delegert dyplesing) + live-verifikasjon av
de sentrale påstandene mot kjørende system. Klassifisering per funn.

---

## Live-verifiserte påstander

| Påstand | Test | Resultat |
|---|---|---|
| Postgres-tilkoblinger «lekker ubegrenset» | `pg_stat_activity` med idle workers | **Delvis avkreftet:** 1 aktiv tilkobling av 100 maks. Python-GC lukker connection når variabelen går ut av scope. Ingen ubegrenset lekkasje — men ingen pooling (F2-1 nedjustert) |
| Redis «Timeout reading from socket»-spam | `grep` i live-logg siste 3 min | **Avkreftet som nåværende problem:** 0 forekomster. `socket_timeout` er ikke satt (default None), BLPOP timeout=5 er trygt. Var historisk (Redis kortvarig utilgjengelig ved tidligere restart) |
| Ingen SIGTERM/graceful shutdown | `docker stop --timeout 10` på routing_worker | **Bekreftet:** stoppet umiddelbart, ingen 10s drain. In-flight jobb ville dødd midt i `process()` |

---

## Funn

### F2-1 · Høy · Ingen connection pooling — tilkobling per jobb
**Fil:** `base_worker.py:76,88,304,362`, `reconciliation_worker.py:60,429`.
**Klassifisering:** utledet fra kode; **lekkasje-påstand avkreftet ved kjøring**
(GC lukker, idle=1 tilkobling), men skaleringsbekymringen står.
**Bevis:** `_behandle()` åpner ≥2 nye `psycopg2.connect()` per jobb, ingen pool.
**Konsekvens ved 60M dok:** ved N samtidige workers × 2 tilkoblinger + burst
kan `max_connections=100` nås; hver `connect()` har oppkoblings-latens (TCP +
auth) som dominerer korte jobber.
**Fiks:** `psycopg2.pool.ThreadedConnectionPool` per worker, eller pgbouncer
foran Postgres. Gjenbruk én tilkobling per jobb i stedet for to.

### F2-2 · Høy · Ingen graceful shutdown (SIGTERM) — bekreftet live
**Fil:** `base_worker.py:58-71`, `reconciliation_worker.py:49-56` (`while True`,
ingen `import signal`).
**Klassifisering:** bekreftet ved kjøring.
**Konsekvens:** hver `docker stop`/K8s-rullering under last dreper en jobb
midt i prosessering. Meldingen er allerede BLPOP-et ut av Redis, `state=
running_state`+lås committet → jobben henger til `lock_expiry` (60s) og
reconciliation `reparer_stuck_jobs` re-køer. Ikke tap, men 60s–10min
forsinkelse per deploy × mange samtidige jobber.
**Fiks:**
```python
import signal
def __init__(...): self._stopp = False; signal.signal(signal.SIGTERM, self._be_om_stopp)
def _be_om_stopp(self, *_): self._stopp = True
def run(self):
    while not self._stopp:
        raw = self._redis.blpop(self.queue_name, timeout=5)
        ...   # fullfør in-flight jobb før retur
```

### F2-3 · Høy · Dobbeltbehandling mulig når `process()` > lock_timeout (60s)
**Fil:** `reconciliation_worker.py` (`reparer_stuck_jobs`) + `base_worker.py:127-139`.
**Klassifisering:** utledet fra kode (race — ikke live-reprodusert).
**Bevis:** låsen (60s) fornyes ikke under lang inferens. Marker/TrOCR på store
dokumenter kan overstige 60s (OCR hard-limit i config er 30s, men ikke
håndhevet). Da re-køer reconciliation, worker B claimer (`lock_expiry<NOW()`),
og begge kjører samme stage. Milvus-indeksering og Label Studio er ikke
idempotente → doble sideeffekter.
**Fiks:** lås-heartbeat (forny `lock_expiry` periodisk under `process`), ELLER
`lock_timeout` > verste `hard_limit`, ELLER reconciliation-grace > ett
prosesseringsintervall.

### F2-4 · Høy · `_frigi_las` mangler eierskapssjekk
**Fil:** `base_worker.py:141-146`.
**Klassifisering:** utledet fra kode.
**Bevis:** `UPDATE jobs SET locked_by=NULL WHERE job_id=%s` — ingen `AND
locked_by=self.worker_id`. I racet i F2-3 nullstiller sen worker A den ferske
låsen til worker B.
**Fiks:** `... WHERE job_id=%s AND locked_by=%s` med `self.worker_id`.

### F2-5 · Middels · `_legg_i_neste_ko` ikke dedup-beskyttet
**Fil:** `base_worker.py:205-216`. Ren `rpush`. Under F2-3-racet pushes samme
jobb to ganger; nedstrøms fanges av tilstandsmaskinen (ulovlig overgang) men
etter bortkastet arbeid. **Fiks:** betinget push via `RETURNING` på
state-oppdateringen (kun push hvis denne transaksjonen satte done_state).
**Klassifisering:** utledet fra kode.

### F2-6 · Middels · Manglende indekser for reconciliation-spørringer
**Fil:** `skript/init_db.py` vs. `reconciliation_worker.py`.
**Klassifisering:** utledet fra kode.
**Bevis:** `ettersend_label_studio` filtrerer på `audit_log.event_type` og
`results.routing_decision` — ingen av dem indeksert. Ved 60M audit-rader =
full table scan hvert 5. minutt.
**Fiks:**
```sql
CREATE INDEX ON audit_log (event_type, id);
CREATE INDEX ON results (routing_decision) WHERE routing_decision IN ('REVIEW','REJECTED');
CREATE INDEX ON jobs (state, updated_at);
```

### F2-7 · Middels · Ikke exactly-once per stage under lang prosessering
Konsekvens av F2-3. Milvus/Label Studio-sideeffekter kan dobbeltfyres.
Se F2-3-fiks. **Klassifisering:** utledet fra kode.

### F2-8 · Lav · DLQ-vei etterlater `locked_by` satt på FAILED-rad
**Fil:** `base_worker.py:273-301`. Ufarlig (FAILED ekskluderes av
reconciliation) men gir misvisende låsedata i overvåkning. **Fiks:** inkluder
`locked_by=NULL` i DLQ-grenens state-oppdatering.

### F2-9 · Lav · Redundant indeks + manglende UNIQUE(dokument_id, side_nummer)
**Fil:** `init_db.py:84` (`idx_jobs_idempotency` duplikat av UNIQUE-constraint)
og manglende `UNIQUE(dokument_id, side_nummer)` (se også F1-5). **Klassifisering:**
utledet fra kode.

---

## Bekreftelse av kjente punkter

- **Punkt (4) — «best-effort» Label Studio:** bekreftet i fase 3-arbeid tidligere
  i økten (routing_decision lagres FØR LS-kall; kvalitetsporten kan ikke
  omgås). Audit-kvittering + reconciliation-ettersending lagt til og bevist live.
- **Punkt (8) — historiske DLQ-ofre:** løst og bevist live — 10 jobber
  gjenopptatt via `dlq_gjenoppta.py`, 10/10 DONE, merket
  `ls-avhengighet-bugg-2026` i audit.

## Gjort bra (verifisert)

- Commit-før-rpush overalt (bevist i ekte hendelse denne økten)
- Optimistisk lås korrekt for normal dobbeltlevering (integrasjonstest #9)
- Varig `attempt_count` i DB hindrer evig re-kø-løkke for giftige jobber
- DATA_INKONSISTENS-vakt i både reconciliation og rebuild_redis
- Ghost-detektor setter `updated_at=NOW()` for å unngå dobbeltmatch
- Alle fire kritiske indekser brukeren spurte om FINNES (state, dokument_id,
  audit.job_id, dlq.job_id)

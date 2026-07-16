# Fase 1 — Arkitektur, pipeline og state machine

**Metode:** kodegjennomgang mot faktisk kjørende system (hele stacken oppe
under revisjonen) + kjøring av testsuiten + live knekk-forsøk mot API-et.
Klassifisering per funn: `bekreftet ved kjøring` / `utledet fra kode` /
`policy-beslutning`.

---

## 1. Samsvar arkitektur ↔ README

| Påstand i README | Faktisk | Vurdering |
|---|---|---|
| Postgres eneste kilde til sannhet; Redis transport | Bekreftet: `rebuild_redis.py` gjenoppbygger køene fra `jobs`-tabellen; ghost-detektor re-køer | ✅ bekreftet ved kjøring (live i denne økten: feilet `rpush` etter commit → automatisk gjenoppretting) |
| Én jobb per side, uavhengig livssyklus | Bekreftet: `last_opp.py:154-186` (én transaksjon, én rad per side) | ✅ bekreftet ved kjøring (10-siders + 1000-siders dokument) |
| Tilstandsflyt UPLOADED→…→DONE, NLP hopper over VALIDATION | `delt/konstanter.py:40-63` matcher README-tabellen eksakt, inkl. `("NLP_PROCESSING","ROUTING")` | ✅ bekreftet ved kjøring |
| Modellruting NLP | README oppdatert i takt med koden (Borealis primær, LLM_URL-modus) | ✅ |

Avvik funnet: ingen strukturelle. Tilleggskomponenter (model serving,
backup, oppbevaring) er dokumentert i README.

## 2. Knekk-forsøk på state machine

| Angrep | Resultat | Klassifisering |
|---|---|---|
| Ulovlig overgang (`DONE→PREPROCESSING`) | Avvist med `UgyldigTilstandsovergang` — `test_state_machine.py` 5/5 grønne (kjørt i denne revisjonen) + integrasjonstest #8 | bekreftet ved kjøring |
| To workers på samme jobb | Optimistisk lås `locked_by`+`lock_expiry` (`base_worker.py`); integrasjonstest #9 | bekreftet ved kjøring (testsuite) |
| Krasj mellom Postgres-commit og Redis-push | Ghost-detektor re-køer. **Reelt observert i denne økten:** `dlq_gjenoppta` fra vert krasjet på rpush etter commit — jobben ble automatisk plukket opp og fullført | bekreftet ved kjøring (ekte hendelse) |
| Kjent punkt (6): én FAILED side blokkerer `/tekst` for alltid | **Var reelt — nå fikset og bevist:** dokument med 1000 FAILED sider gir HTTP 200, `ferdig=true`, `komplett=false`, `feilede_sider` eksplisitt (`last_opp.py`, terminaltilstands-logikk) | bekreftet ved kjøring |
| Duplikat side_nummer ved samtidige opplastinger | Hele sideinnsettingen er ÉN transaksjon + `idempotency_key` UNIQUE per `(fil, side)`; taperen får rollback + idempotent svar (`last_opp.py:219-228`) | utledet fra kode (unit-/integrasjonstestet for énsides-tilfellet) |

## 3. Funn

### F1-1 · Middels · State machine håndheves kun i applikasjonslaget
**Fil:** `tjenester/workers/base_worker.py` (overgangsvalidering), ingen DB-motpart.
**Bevis:** i denne økten ble `FAILED→QUEUED` (dlq-gjenopptak) og `QUEUED→FAILED`
(nøytralisering av SLA-test) utført med direkte SQL — databasen aksepterer alt.
**Klassifisering:** bekreftet ved kjøring (selv demonstrert).
**Konsekvens:** feilskrevne admin-skript/manuell SQL kan sette ulovlige
tilstander uten spor i valideringslaget (audit fanger det bare hvis skriptet
selv auditerer).
**Fiks:** PostgreSQL-trigger som validerer `(OLD.state, NEW.state)` mot en
overgangstabell, med en eksplisitt `admin_bypass`-kolonne/rolle for
gjenopptaksskript:
```sql
CREATE FUNCTION valider_overgang() RETURNS trigger AS $$
BEGIN
  IF (OLD.state, NEW.state) NOT IN (SELECT fra, til FROM lovlige_overganger)
     AND current_setting('nav.admin_bypass', true) IS DISTINCT FROM 'on'
  THEN RAISE EXCEPTION 'Ulovlig overgang % -> %', OLD.state, NEW.state;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
```

### F1-2 · Lav · To sannhetskilder for kønavn — den ene er død og feil
**Fil:** `delt/konstanter.py:25-38` (`REDIS_KOOER`, `DLQ_KOOER`) vs
`config/config.yaml:43-54`.
**Bevis:** grep viser at ingen konsument importerer konstantene — alle leser
CONFIG. `DLQ_KOOER` mangler til og med `routing`-nøkkelen (config har den).
**Klassifisering:** utledet fra kode (grep-verifisert).
**Fiks:** slett kø-konstantene fra `konstanter.py`, eller la config-loaderen
importere dem derfra så det finnes én kilde.

### F1-3 · Høy (for produksjon) · SPOF-kartlegging
**Klassifisering:** utledet fra kode/manifester.
| Komponent | Status | Konsekvens ved bortfall |
|---|---|---|
| Postgres | 1 instans, ingen replika (`docker-compose.yml`, `k8s/03-postgres.yaml` replicas=1) | Total stopp. Backup gir RPO 24 t, men ingen failover |
| Redis | 1 instans; ingen AOF/persistens konfigurert | Akseptert by design: køene gjenoppbygges fra Postgres (`rebuild_redis.py`) — bekreftet ved kjøring |
| vLLM/GPU | 1 instans, 1 GPU | NLP faller tilbake til NB-BERT (svakere uttrekk) — degradert, ikke død; bekreftet fallback-kjede |
| sok/Milvus | 1 instans | Indeksering får retry+audit (`INDEKSERING_FEILET`), søk nede | 
**Fiks (prod):** Postgres HA (Patroni/managed), `replicas>1` for sok/API i
`k8s/13-workers.yaml`/`10-api.yaml`, PodDisruptionBudgets.

### F1-4 · Lav · Død tilstand og kø: VALIDATION
**Fil:** `delt/konstanter.py:45-46`, `config/config.yaml:47,53`.
VALIDATION-tilstand + `queue:validation`/`dlq:validation` er definert men
aldri i bruk (NLP validerer inline — dokumentert i README). Ryddekandidat;
`rebuild_redis.py:30` ruter den forsvarlig til nlp-køen om den skulle oppstå.
**Klassifisering:** utledet fra kode.

### F1-5 · Middels · Ingen deklarativ garanti mot duplikat `(dokument_id, side_nummer)`
**Fil:** `skript/init_db.py` (skjema).
Dagens vern (én transaksjon + UNIQUE `idempotency_key`) er reelt, men
implisitt — et fremtidig skript som setter inn sider utenom API-et har ingen
skranke. **Fiks:** `ALTER TABLE jobs ADD CONSTRAINT unik_side UNIQUE
(dokument_id, side_nummer);` (billig, umiddelbar).
**Klassifisering:** utledet fra kode.

## 4. Det som er gjort riktig (verifisert)

- **Commit-før-rpush-mønsteret** — beviste sin verdi i en ekte hendelse i
  denne økten (ikke bare i test)
- Terminaltilstander respekteres nå konsekvent i både prosessering og
  lese-API (`/tekst`, `/felter`)
- Optimistisk låsing + self-transitions for re-claim er riktig tenkt
- Side-per-jobb-arkitekturen beviste isolasjonsegenskapen live: 10/10 sider
  gjenopprettet etter infrastrukturfeil uten å røre andre dokumenter

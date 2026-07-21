# ADR-002 — Køabstraksjon for blandede profiler

- **Status:** Forslag (betinget — se [README](README.md)).
- **Dato:** 2026-07-21
- **Kontekst:** §6.1 er avklart til **blandet**: containerisert
  nettverks-prod *og* en separat luftgap-installasjon fra én kodebase.
  Gjenbrukskoden (`base_worker.py`) hardbinder Redis (`redis.from_url`,
  `BLPOP`, `RPUSH`). Redis er utmerket i container, men vondt å drive
  native på et luftgappet Windows.

## Beslutning (foreslått)

Innfør en **kø-port** som workerne bruker, med to implementasjoner valgt
av konfig. Postgres (jobstate/audit) er uendret felles for begge.

```python
class Ko(ABC):
    def legg_til(self, ko: str, jobb: dict) -> None: ...
    def hent(self, ko: str, timeout: int) -> tuple | None:  # (kvittering, jobb)
        ...
    def bekreft(self, kvittering) -> None: ...      # ack
    def til_dlq(self, ko: str, jobb: dict, feil: str) -> None: ...
```

| Profil | Implementasjon | Merknad |
|--------|----------------|---------|
| Containerisert prod | `RedisKo` | Høy gjennomstrømming, native backpressure; behold reconciliation som dual-write-nett |
| **Luftgap (Windows)** | `PostgresKo` | `SELECT … FOR UPDATE SKIP LOCKED` på en `ko`-tabell — **ingen ekstra broker** (Postgres kreves allerede), kjører native |

## Konsekvenser

- Én kodebase, to backends, valgt av miljøkonfig (§3.3 Configuration).
- **Korrekthetsbonus:** med `PostgresKo` ligger kø og jobstate i *samme*
  database, så «legg i neste kø» kan gjøres **transaksjonelt** med
  tilstandsoppdateringen — det lukker dual-write-gapet i `base_worker`
  (DB-commit → Redis-push er ikke atomisk) for luftgap-profilen.
- `RedisKo` beholder høyere gjennomstrømming for prod; `PostgresKo` er
  rikelig for luftgap-installasjonens mindre last.
- Krever at `base_worker` refaktoreres til å bruke porten i stedet for
  direkte `self._redis`-kall (én avgrenset endring).

## Alternativer vurdert

- **Kun Redis (også luftgap):** forkastet — Redis native på Windows er
  skjørt og krever ekstra drift i det miljøet som har minst drift.
- **Kun Postgres-kø (også prod):** mulig, men lavere gjennomstrømming enn
  Redis ved høy prod-last; abstraksjonen lar oss velge per profil.
- **Tredjeparts meldingskø (Kafka/RabbitMQ):** forkastet for luftgap
  (tung å overføre/drive offline); kan vurderes for prod-profilen senere
  bak samme port.

# Sikkerhetskopi og gjenoppretting

Postgres er **eneste kilde til sannhet** i V2.1 (jobs, results, audit_log,
dead_letter_queue). Alt annet er transport eller avledet data. Denne
strategien følger av det:

| Lager | Sikkerhetskopieres? | Begrunnelse |
|-------|--------------------|-------------|
| **Postgres** | ✅ Daglig `pg_dump` + GFS-retention | Kilde til sannhet. `audit_log` skal aldri slettes (NAV-krav) — uten backup er kravet ikke reelt oppfylt |
| **Originaldokumenter** (`data/inntak`, `data/behandlet`) | ✅ Inkrementell kopi | Append-only: en fil endres aldri etter skriving, så «finnes i mål = ferdig» er korrekt og billig |
| **Redis** | ❌ | Ren transport. Gjenoppbygges fra Postgres: `make rebuild-redis` |
| **Milvus / MinIO / etcd** | ❌ | Avledet søkeindeks. Reindekseres fra Postgres + originalfiler (RoutingWorker sender APPROVED-dokumenter til `sok:8003/indekser`) |
| **Label Studio** | ⚠️ Egen volum | Annoteringsdata; ta med `label_studio_data`-volumet i infrastruktur-backup ved behov |
| **AI-modeller** | ❌ | Kan lastes ned på nytt (`make last-ned-modeller`); finjusterte modeller versjonsbackups av `skript/finjuster.py` |

## Garantier

- **RPO (maks datatap): 24 timer** med standardintervallet. Senk
  `BACKUP_INTERVALL_TIMER` for lavere RPO; for RPO i minutter, se
  «Videre arbeid» under.
- **RTO (gjenopprettingstid):** minutter — `pg_restore` av en komprimert
  dump + `make rebuild-redis`.
- **Ingen stille korrupsjon:** en dump får ikke sitt endelige navn før
  `pg_restore --list` har lest hele innholdsfortegnelsen. sha256 lagres
  ved siden av og kontrolleres før hver gjenoppretting.
- **Sporbarhet:** hver kjøring skrives til `audit_log`
  (`event_type=SIKKERHETSKOPI`) med fil, størrelse, sjekksum og varighet.

## Retention (GFS)

Standard: **7 daglige + 4 ukentlige + 0 månedlige** (eldste kopi
~28 dager). I tillegg beholdes alltid alle kopier tatt inneværende dag.
Overstyres med `BACKUP_DAGLIGE`, `BACKUP_UKENTLIGE`, `BACKUP_MAANEDLIGE`.

> **Hvorfor 0 månedlige?** NAV tillater ikke dokumentlagring over
> 6 måneder, og kravet gjelder også innholdet i sikkerhetskopier:
> `OPPBEVARING_MAKS_DAGER (150) + eldste kopi (~28) ≤ 180`.
> Se [OPPBEVARING.md](OPPBEVARING.md). Skru på månedlige kopier kun
> der 6-månedersregelen ikke gjelder.

Filer som ikke matcher `nav_archive_YYYYMMDD_HHMMSS.dump` røres aldri
av oppryddingen.

## Drift

### Lokalt (docker compose)

`backup`-tjenesten kjører som daemon og tar en kopi hver 24. time:

```bash
make start                     # backup-tjenesten følger med
make sikkerhetskopi            # ta en ekstra kopi nå
make sikkerhetskopi-status     # siste kjøring (fil, størrelse, verifisert)
make sikkerhetskopi-verifiser FIL=nav_archive_20260716_020000.dump
```

Kopiene havner i `./data/sikkerhetskopi/` (overstyr med `BACKUP_STI`
i `.env`). **Lokal standard er samme disk som databasen — det beskytter
mot feiloperasjoner, ikke disktap.** I produksjon: pek `BACKUP_STI` mot
annen fysisk lagring (NFS/S3-mount).

### Kubernetes

`k8s/15-sikkerhetskopi.yaml`: CronJob kl. 02:00, `concurrencyPolicy:
Forbid`, egen PVC (`nav-backup`). Bruk en storage class på annen
infrastruktur enn postgres-PVC-en.

```bash
kubectl create job --from=cronjob/nav-sikkerhetskopi manuell-backup -n kubeflow
```

## Gjenoppretting

### Øvelse (anbefalt månedlig): gjenopprett til testdatabase

```bash
make gjenopprett FIL=nav_archive_20260716_020000.dump DB=nav_archive_restore_test
```

Verifiser radtall mot produksjonsdatabasen, og slett testdatabasen
etterpå. En backup som aldri er gjenopprettet er bare et håp.

### Reell katastrofe: gjenopprett hoveddatabasen

1. Stopp alt som skriver: `docker compose stop api preprocessing_worker ocr_worker nlp_worker routing_worker reconciliation_worker`
2. `make gjenopprett FIL=<nyeste dump>`
3. **`make rebuild-redis`** — køene skal alltid gjenoppbygges fra Postgres
4. **`make oppbevaring`** — fjern innhold som utløp mellom dump og
   gjenoppretting (6-månedersregelen, se [OPPBEVARING.md](OPPBEVARING.md))
5. Start tjenestene igjen: `make start`
6. Reindekser søk ved behov (APPROVED-dokumenter re-rutes, eller kjør
   reindeksering mot `sok:8003/indekser`)

Rekkefølgen 2→3 er kritisk: Redis-innhold eldre enn databasen gir
ghost-jobber (ReconciliationWorker rydder dem, men unngå det).

## Videre arbeid (bevisst utelatt nå)

- **PITR / WAL-arkivering** (`archive_mode=on` + f.eks. pgBackRest):
  senker RPO fra timer til sekunder. Neste steg når volumet krever det.
- **Offsite-replikering** av backup-mappen (S3 med object lock for
  ransomware-vern).
- **Prometheus-alarm** på `status.json`-alder > 26 timer.

# Oppbevaringsbegrensning — 6-månedersregelen

NAV tillater ikke lagring av dokumenter i mer enn **6 måneder**.
Dette dokumentet beskriver hvor dokumentinnhold finnes i systemet,
hva som slettes automatisk, og hvordan etterlevelse bevises.

## Hvor dokumentinnhold og persondata lever

| Lager | Innhold | Håndtering |
|-------|---------|------------|
| `data/inntak`, `data/behandlet` | Original-PDF, side-PNG/PDF | ✂️ Slettes av oppbevaringsjobben |
| Postgres `results` | Full OCR-tekst, entiteter (navn, fnr, adresse) | ✂️ Raden slettes |
| Postgres `jobs` | filnavn, filsti, feiltekster | ✂️ Anonymiseres — raden beholdes som prosesstatistikk uten innhold |
| Postgres `dead_letter_queue` | payload_snapshot kan inneholde dokumenttekst | ✂️ Snapshot og feilmelding overskrives |
| Milvus (søkeindeks) | tekst, navn, dato, embedding | ✂️ `DELETE /dokument/{fil_id}` på søketjenesten (alle sider) |
| Label Studio | gjennomgangsoppgaver med OCR-tekst/bilde | ✂️ Best effort via API (hopper over hvis utilgjengelig) |
| Backup-speilet av originalfiler | kopier av inntak/behandlet | ✂️ Backup-daemonen sletter filer eldre enn grensen (mtime) |
| Postgres `audit_log` | **kun tekniske hendelser** — tilstandsskifter, feil­årsaker, aldri dokumentinnhold | ✅ Beholdes for alltid (NAV-krav om sporbarhet) — ingen konflikt |

`audit_log` er verifisert innholdsfri: `details` inneholder felter som
`{"grunn": "milvus_utilgjengelig"}`, aldri tekst fra dokumenter.
**Skriv aldri dokumenttekst eller entiteter til audit_log.**

## Totalbudsjettet: 180 dager inkluderer sikkerhetskopiene

En dump tatt i dag inneholder dokumenter som er opptil `maks_dager`
gamle. Beholdes dumpen i N dager, er innholdet opptil
`maks_dager + N` gammelt. Derfor:

```
OPPBEVARING_MAKS_DAGER  +  eldste backup-kopi  ≤  180 dager
        150             +        ~28 (7/4/0)   =  178  ✓
```

Standardene er satt deretter: dokumenter slettes etter **150 dager**,
og backup-GFS kjører **7 daglige / 4 ukentlige / 0 månedlige**
(`BACKUP_MAANEDLIGE=0`). Øker du én, må du senke den andre.

**Etter gjenoppretting fra backup skal oppbevaringsjobben alltid
kjøres umiddelbart** — den fjerner innhold som rakk å utløpe mellom
dump og gjenoppretting:

```bash
make oppbevaring
```

## Kjøring

| Miljø | Mekanisme |
|-------|-----------|
| Lokalt | `oppbevaring`-tjenesten i docker-compose (daemon, hver 24. time) |
| K8s | CronJob kl. 03:00 ([k8s/17-oppbevaring.yaml](../k8s/17-oppbevaring.yaml)) — etter backup kl. 02:00, slik at dumpen alltid tas før sletting |

```bash
make oppbevaring-torrkjoring   # vis hva som VILLE blitt slettet
make oppbevaring               # slett utløpt innhold nå
```

## Bevis for etterlevelse

Hver sletting skrives til `audit_log` med
`event_type=SLETTET_OPPBEVARING` og detaljer (alder i dager, antall
filer, om søkeindeksen ble ryddet). Revisjonsspørsmål:

```sql
SELECT count(*), min(created_at), max(created_at)
FROM audit_log WHERE event_type = 'SLETTET_OPPBEVARING';

-- Finnes utløpt innhold? (skal være 0 rader)
SELECT j.job_id FROM jobs j JOIN results r ON r.job_id = j.job_id
WHERE COALESCE(j.completed_at, j.updated_at) < NOW() - INTERVAL '150 days';
```

## Feilhåndtering

- **Milvus nede under sletting:** DB-innhold og filer slettes uansett
  (viktigst); indeks-oppføringen logges som ikke slettet og tas i
  neste runde — jobben er idempotent.
- **Tørrkjøring** (`--torrkjoring`) endrer ingenting og kan kjøres
  når som helst for revisjon.

# Audit-record-skjema (leveranse §7.4) — forslag

> **STATUS: FORSLAG.** Skjemadesign kan gå videre uten volumtallet — det
> trenger kun §6.4-avklaringen (oppbevaring/immutabilitet), som dette
> dokumentet **tvinger fram** nederst. Bygger på det gjenbrukte
> `init_db.py`-skjemaet (se [revisjon](revisjon-gjenbrukskode.md)).

## Mål

Non-negotiable §4: *hver result skal kunne spores til nøyaktig modell- og
regelversjon som produserte den.* Dagens monolitt stempler kun `api` +
`prompt` i `versjon`-blokken — det holder ikke. Dette skjemaet gjør
provenansen førsteklasses og spørrbar.

## Base (gjenbrukt, uendret)

`jobs`, `results`, `audit_log`, `dead_letter_queue` fra `init_db.py`.
Solid utgangspunkt (idempotens, DLQ, reconciliation-indekser).

## Utvidelse 1 — versjonskolonner (§3.3 Versioning)

Provenansen legges på `results` (eller en egen `resultat_proveniens`),
fylt ved hvert steg, aldri etterpå-endret:

```sql
ALTER TABLE results ADD COLUMN IF NOT EXISTS norhand_versjon      TEXT;
ALTER TABLE results ADD COLUMN IF NOT EXISTS ocr_motor_versjon    TEXT;  -- easyocr/rapidocr + versjon
ALTER TABLE results ADD COLUMN IF NOT EXISTS uttrekk_regel_versjon TEXT; -- delt/tekstuttrekk
ALTER TABLE results ADD COLUMN IF NOT EXISTS konfidens_terskel    NUMERIC(4,3); -- verdien som gjaldt
ALTER TABLE results ADD COLUMN IF NOT EXISTS llm_versjon          TEXT;  -- Borealis, KUN når LLM ble brukt (/spor)
ALTER TABLE results ADD COLUMN IF NOT EXISTS prompt_versjon       TEXT;
ALTER TABLE results ADD COLUMN IF NOT EXISTS api_versjon          TEXT;
```

Regel: `llm_versjon` er NULL når ingen LLM ble kalt — det er i seg selv en
sporbar kjensgjerning (dokumentet gikk deterministisk vei).

## Utvidelse 2 — immutabilitet på audit_log (§6.4)

`audit_log` skal være **append-only**. Forslag (avventer governance):

```sql
REVOKE UPDATE, DELETE ON audit_log FROM app_rolle;   -- app kan kun INSERT/SELECT
-- valgfritt sterkere: hash-lenke (forrige rads hash) for tamper-evidens
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS forrige_hash TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS rad_hash     TEXT;  -- sha256(job_id|event|from|to|worker|details|forrige_hash)
```

Hash-lenken gjør at en slettet/endret rad brytes synlig — nyttig for et
system hvis output kan ankes/revideres i ettertid. **Om dette kreves er en
governance-beslutning (§6.4), ikke en teknisk.**

## Utvidelse 3 — oppbevaring (§6.4)

To ulike policyer, ulik behandling:

| Data | Hvor | Foreslått default | Åpent |
|------|------|-------------------|-------|
| Dokumentbilde/rå tekst i Label Studio | gjennomgangskø | slett N dager etter at korreksjon er hentet inn i trening | **N = ?** |
| Operasjonell jobstate (`jobs`, `results`) | Postgres | slett/arkiver etter M dager | **M = ?** |
| `audit_log` | Postgres | lengre, muligens immutabel — se over | **vindu + immutabilitet = ?** |

Implementasjon: en `rydd_oppbevaring`-jobb (Task Scheduler / cron) som
sletter etter policy og selv auditerer hva den slettet.

## Bro til DAGENS system (ikke betinget av volum)

Uavhengig av skalering bør monolittens `versjon`-blokk utvides fra
`{api, prompt}` til å inkludere `norhand`-, `uttrekk_regel`- og
`terskel`-versjon (og `llm` når `/spor` brukte den). Dette er den samme
§4-disiplinen, og den mangler i dag. Konkret:

- Definér `UTTREKK_REGEL_VERSJON` i `delt/tekstuttrekk.py`.
- La kvalitetsporten (`valider_modell.promuster`) skrive en
  `modeller/norhand/nav_versjon.txt` ved promotering, som API-et leser.
- Ett `_versjon_stempel()`-hjelpeverktøy i `dokument_api.py`, brukt på alle
  svar-veier.

Dette er en avgrenset, additiv endring (nye felt i svaret; eksisterende
klienter ignorerer dem) og kan gjøres **nå**, som første konkrete steg som
også gagner det eventuelle skalerte systemet. Venter på klarsignal for å
røre den kjørende serveren.

## Åpne beslutninger (dine — §6.4)

1. Oppbevaringsvindu for Label Studio-data (N dager).
2. Oppbevaringsvindu for operasjonell jobstate (M dager).
3. Audit-oppbevaring + om audit trenger immutabilitet/tamper-evidens.

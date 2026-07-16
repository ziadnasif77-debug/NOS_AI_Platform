# Fase 4 — API, sikkerhet og GDPR/oppbevaring

**Metode:** delegert sikkerhetsgjennomgang av API-laget + egne live-spørringer
mot Postgres for persondata-livssyklus. Klassifisering per funn.

---

## Del A — API og sikkerhet

### F4-1 · KRITISK · Ingen maks filstørrelse ved opplasting (minne-DoS)
**Fil:** `last_opp.py:133` — `innhold = await fil.read()` (hele filen i minnet),
deretter `fitz.open(stream=...)` (dobbelt forbruk). Ingen body-limit.
**Klassifisering:** utledet fra kode.
**Konsekvens:** én 10 GB PDF fra en klient med gyldig nøkkel dreper API-prosessen.
**Fiks:** strøm til grense (413 over `MAKS_OPPLASTING_BYTES`, f.eks. 100 MB) +
proxy `client_max_body_size`.

### F4-2 · Høy · Ingen grense på sideantall (amplifisering)
**Fil:** `last_opp.py:135,155-186,200-203`. En PDF med 200 000 sider = 200 000
job-rader + 400 000 audit-rader + 200 000 Redis-meldinger i én transaksjon.
**Klassifisering:** utledet fra kode.
**Fiks:** `MAKS_SIDER_PER_DOKUMENT` (f.eks. 2000) → 422.

### F4-3 · Høy · Ingen øvre grense på `antall` i søk
**Fil:** `sok/hoved.py:295,306-319`, proxy `api/ruter/sok.py:10`. `antall`
ubundet → `limit=antall*3` mot Milvus. `sok.py` sender rå `data: dict`.
**Klassifisering:** utledet fra kode. **Fiks:** Pydantic `antall: int = Field(10, ge=1, le=100)`.

### F4-4 · Høy · Ingen rate limiting noe sted
**Fil:** hele `api/hoved.py`, `sok/hoved.py`. Spesielt `/sporsmal` er dyrt
(synkrone LLM-kall, opptil 32 biter × 90s) uten kvote.
**Klassifisering:** utledet fra kode. **Fiks:** `slowapi` eller proxy-throttling per nøkkel.

### F4-5 · Middels · Informasjonslekkasje: rå `str(exception)` i klientresponser
**Fil:** 20+ steder — `hoved.py:125,144`, `sok.py:22`, `gjennomgang.py:32,49`,
`last_opp.py:238,265,288,337,460,578,657,682`, `sporsmal.py:213`,
`sok/hoved.py:267,287,325`. Lekker Postgres-/Milvus-interne detaljer, filstier,
downstream-URL-er.
**Klassifisering:** utledet fra kode. **Fiks:** `logger.exception(...)` + generisk `detail="Intern feil"`.

### F4-6 · Høy · Innebygd standardhemmelig + «tom nøkkel = åpen»
**Fil:** `.env.example:32,41` (`API_NOKKEL=nav-secret-2026`, samme til to formål),
`autentisering.py:79-80` (`if not api_nokkel: return None` → fail-open).
**Klassifisering:** utledet fra kode. **Fiks:** placeholder i eksempelfil + fail-closed i prod.

### F4-7 · Middels · CORS defaulter til `*` med alle metoder/headers
**Fil:** `hoved.py:33-39`. Begrenset skade (header-auth, ingen credentials), men
unødig bredt for internt statlig API. **Fiks:** eksplisitt origin-liste, feil i prod hvis usatt.

### F4-8 · Middels · `/metrics` åpent, udokumentert valg
**Fil:** `hoved.py:51,81-84`, `sok/hoved.py:31`. Eksponerer rutenavn, volum,
statuskoder, latens uten nøkkel. (`/openapi.json` er dokumentert; `/metrics` ikke.)
**Fiks:** nettverks-ACL/metrics-token + dokumenter valget.

### F4-9 · Middels · Delt nøkkel = ingen autorisasjonsgranularitet på sletting
**Fil:** `sok/hoved.py:270-287` (`DELETE /dokument/{fil_id}`). Enhver klient med
felles-nøkkelen kan tømme søkeindeksen. Ingen rolleskille lese/slette i
api_nokkel-modus. **Fiks:** egen scope/rolle (OIDC `roles`) eller separat
retention-nøkkel; sok kun på internt nett.

### F4-10 · Lav · `korriger` og `GET /dokument/{job_id}` mangler input-validering
**Fil:** `gjennomgang.py:35-49` (uvalidert `fil_id` + rå `data` til LS),
`hoved.py:129-144` (job_id ikke validert før proxy). **Fiks:** `_valider_job_id` + Pydantic.

### F4-11 · Lav · Manglende sikkerhets-headere
Ingen HSTS/`X-Content-Type-Options`/`X-Frame-Options`/CSP. `/docs` serverer HTML. **Fiks:** enkel middleware.

---

## Del B — GDPR og oppbevaring (persondata-livssyklus)

Live-spor av persondata gjennom alle lag:

| Lag | Persondata | Slettes ved oppbevaring (150 d)? | Verifisert |
|---|---|---|---|
| `data/inntak` PDF + `data/behandlet` PNG | Rådokument | ✅ `oppbevaring.py` sletter filstier | bekreftet ved kjøring (tidligere økt: 12 filer slettet) |
| `results.ocr_result/nlp_result` | Full tekst + entiteter (fnr, navn) | ✅ raden slettes | bekreftet ved kjøring (results-rader → 0) |
| `jobs.file_name/file_path` | filnavn + sti | ✅ anonymiseres | bekreftet ved kjøring |
| Milvus | tekst, navn, dato, embedding | ✅ `DELETE /dokument/{id}` | bekreftet ved kjøring (søk → 0 treff) |
| **`audit_log.details.filnavn`** | **Originalt filnavn — ALDRI slettet** | ❌ **NEI** | **bekreftet ved kjøring (se F4-12)** |
| `dead_letter_queue.payload_snapshot` | fil_sti (UUID, ikke PII) | ✅ overskrives | bekreftet ved kjøring |

### F4-12 · HØY (GDPR) · Filnavn-PII overlever for alltid i audit_log
**Fil:** `last_opp.py:172-174` skriver `{"filnavn": filnavn, ...}` til
`audit_log.details` ved OPPRETTET. `audit_log` slettes aldri (NAV-krav).
`oppbevaring.py` anonymiserer `jobs.file_name` men **rører aldri audit_log**.
**Klassifisering:** bekreftet ved kjøring — live-spørring viser
`{"filnavn": "2254711543.pdf", ...}` i audit_log.
**Konsekvens:** ekte NAV-filnavn inneholder ofte persondata
(«soknad_ola_nordmann_12345678901.pdf»). Da overlever fnr/navn i et register
som per policy aldri slettes — direkte konflikt med
oppbevaringsbegrensningen og GDPR art. 5(1)(e).
**Fiks:** ikke skriv råt filnavn til audit. Lagre en hash eller kun
`dokument_id`; hvis filnavn må spores, legg det i `jobs.file_name` (som
anonymiseres) og referer dokument_id fra audit. Rydd eksisterende
audit-rader: `UPDATE audit_log SET details = details - 'filnavn' WHERE ...`.

### F4-13 · KRITISK (policy+kode) · Retensjonstid 150 d vs. NAV-krav
**Fil:** `oppbevaring.py:37` (`OPPBEVARING_MAKS_DAGER=150`).
**Klassifisering:** policy-beslutning (ikke kodefeil).
**Bevis:** koden bruker 150 dager. Det tidligere oppgitte NAV-kravet var
~90 dager (3 mnd), mens senere krav i samtalen var 6 måneder. **Disse tre tallene
(90 / 150 / 180) er ikke forsonet.** `.env.example:47` sitt `90` gjelder
finjusteringsintervall, ikke oppbevaring — ikke bland dem.
**Krever NAV-avklaring:** hva er den juridisk bindende oppbevaringstiden? Sett
`OPPBEVARING_MAKS_DAGER` deretter og juster backup-budsjettet (F4-14).

### F4-14 · Middels · Backup-GFS-budsjett avhenger av retensjonsvalget
**Fil:** `sikkerhetskopi.py` (`BACKUP_MAANEDLIGE=0` som standard).
**Klassifisering:** policy+kode. Nåværende default (7/4/0 → eldste ~28 d) gir
`150 + 28 = 178 ≤ 180`. **Men** hvis retensjon settes til 90 d (F4-13), er
budsjettet fortsatt greit; hvis noen skrur på månedlige kopier (6 mnd) bryter
det enhver retensjon < 180 d. Backup-innhold ER persondata og teller med.
**Fiks:** lås sammenhengen i kode — la `sikkerhetskopi.py` nekte å beholde
kopier eldre enn `OPPBEVARING_MAKS_DAGER` (delvis gjort via `rydd_utlopte_filer`
for filspeilet, men IKKE for selve pg_dump-ene som inneholder slettede rader).

### F4-15 · Lav · `/tekst` som valideringsbypass
**Fil:** `last_opp.py` (`/dokument/{id}/tekst`). **Klassifisering:** bekreftet
ved kodelesing — advarsel ER lagt inn (docstring + README) om at dette er et
visnings-/revisjonsendepunkt og at forretningsuttrekk skal gå via
`/felter`/`/sporsmal`. Punkt (5) dermed adressert; gjenstår ev. å kreve egen
scope for endepunktet.

---

## Gjort bra (verifisert)

- **Konstant-tid nøkkelsammenligning** (`autentisering.py:82`, `hmac.compare_digest`)
- **SQL fullt parameterisert** overalt — ingen injeksjon funnet
- **Milvus-ekspresjonsinjeksjon avverget** (charset-validering + allowlist)
- **OIDC/JWT solid**: `algorithms=["RS256"]` (ingen alg-confusion), aud/iss/exp validert
- **Ingen path traversal**: filsti bygges av server-generert uuid4
- **Prompt-injection-forsvar** i `/sporsmal` (dokumenttekst = data)
- **Fnr holdes utenfor søkeindeksen**, serveres kun autentisert
- **Alle utgående kall har timeout**, ingen bruker-styrte URL-er (ingen SSRF)
- **Persondata-sletting fungerer** for alle lag UNNTATT audit_log-filnavn (F4-12)

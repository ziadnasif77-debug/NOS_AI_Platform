# Fase 7 — Samlet sluttrapport (Deep Audit)

**System:** NAV Archive Intelligence System V2.1 — automatisk digitalisering,
analyse og søk i 30–60 millioner historiske NAV-dokumenter (norske persondata).
**Metode:** 7 faser, deterministisk inventar + delegert dyplesing + **live
verifikasjon** mot kjørende stack. Hvert funn er klassifisert `bekreftet ved
kjøring` / `utledet fra kode` / `policy-beslutning`.
**Grunnlag:** phase-0 … phase-6 i denne mappen.

---

## 1. Executive Summary

Systemet er en **arkitektonisk solid, gjennomtenkt prototype på vei mot
produksjon**. Kjernemønsteret — Postgres som eneste sannhet, Redis som
gjenoppbyggbar transport, commit-før-rpush, side-per-jobb-isolasjon — er
korrekt og **bevist live i denne revisjonen** (Redis-nede-test: jobb trygt
QUEUED; 10/10 sider gjenopprettet etter infrastrukturfeil).

Men revisjonen avdekket **én kritisk integritetssvikt i kjernefunksjonen** og
**ett kritisk GDPR-hull**, samt en rekke produksjonshardening-mangler:

- **Kvalitetsporten hviler på falske tall (F3-1):** OCR-/NLP-konfidensene som
  avgjør REVIEW vs. APPROVED er hardkodede konstanter (TrOCR 0.88, Marker 0.90,
  LayoutLMv3 0.91) — ikke modellenes faktiske usikkerhet. Håndskrift auto-
  godkjennes alltid, selv om det er det minst pålitelige moduset. Dette
  undergraver hele kvalitetssikringen systemet er bygget rundt.
- **Persondata overlever for alltid (F4-12):** originalt filnavn skrives til
  `audit_log` som per NAV-krav aldri slettes — ekte NAV-filnavn inneholder ofte
  fnr/navn. Direkte konflikt med oppbevaringsbegrensningen.
- **Retensjonstiden er ikke juridisk avklart (F4-13):** koden bruker 150 dager;
  90 / 150 / 180 er nevnt uten forsoning. Krever NAV-beslutning.

Ingen av disse gjør systemet ubrukelig, men alle tre må lukkes før reell
produksjon med persondata.

## 2. Karakterer (/10)

| Dimensjon | Karakter | Begrunnelse (fra fasefunn) |
|---|---:|---|
| **Arkitektur** | 8.0 | Kjernemønster korrekt og live-bevist (fase 1). Trekk: app-lag-only state machine (F1-1), SPOF-er uten HA (F1-3). |
| **Kodekvalitet** | 7.5 | Konsistent norsk, rikelige docstrings, 94 % cov på kjernelogikk (fase 6). Trekk: hardkodet konfidens (F3-1), docstring lover mer enn kode (F3-2), store filer (F6-3). |
| **Ytelse** | 7.0 | Opplasting 1000 sider 1,9 s målt (fase 5). Trekk: tilkobling-per-jobb uten pool (F2-1) er første flaskehals ved skala. |
| **Sikkerhet** | 5.5 | Solid grunnmur (konstant-tid, parameterisert SQL, OIDC, ingen SSRF/traversal). Trekk: ingen filstørrelse/rate-limit (F4-1..4), `str(exc)`-lekkasje (F4-5), fail-open nøkkel (F4-6). |
| **Skalerbarhet** | 5.5 | KEDA + GPU-strategi forberedt. Trekk: RWO-PVC blokkerer horisontal spredning (F5-4), tilkoblingstak (F2-1), audit_log-vekst uten indeks (F2-6). |
| **AI-pipeline** | 5.0 ⬇ | **Nedjustert fra 6.0 etter gjennomgang:** F3-1 (falsk kvalitetsport for håndskrift/tabell) er trolig rapportens farligste tekniske funn og rammer selve kjerneverdien (fange usikre dokumenter). En pipeline hvis kvalitetsport er en illusjon for to dokumenttyper kan ikke skåre over midt på treet, uansett hvor korrekt mod11/RRF/deterministisk-uttrekk er. Positivt (fase 3): mod11 matematisk korrekt, RRF kanonisk, deterministisk-over-modell riktig prinsipp. Negativt: F3-1 (kritisk), F3-2 (anti-hallusinering-hull), F3-3 (ikke-deterministisk fylke), F3-4 (engelsk OCR). |
| **Produksjonsklarhet** | 5.0 | Backup/oppbevaring/model-serving live-bevist. Trekk: ingen .dockerignore (F5-1), Postgres eksponert (F5-2), ingen graceful shutdown (F2-2), manglende probes/limits i K8s (F5-7,8), GDPR-hull (F4-12). |

**Snitt: 6.2/10** (etter nedjustering av AI-pipeline 6.0→5.0 pga. F3-1) —
«avansert prototype / tidlig produksjon», konsistent med brukerens egen
vurdering ved oppstart.

## 3. Alle funn etter alvorlighet

> **Om klassifisering:** hvert enkelt funn er trippel-klassifisert
> (`bekreftet ved kjøring` / `utledet fra kode` / `policy-beslutning`) i sin
> kilde-fasefil (phase-1…6 — verifisert: alle 51 funn har eksplisitt
> `Klassifisering:`-linje). KRITISK-tabellen under gjentar klassifiseringen
> inline; HØY/MIDDELS/LAV-listene er kompakte pekere til fasefilene der hvert
> punkts klassifisering står. De fleste HØY/MIDDELS er `utledet fra kode`
> unntatt der annet er merket (f.eks. F2-2 «bekreftet live»).

### KRITISK
| ID | Funn | Klassifisering |
|---|---|---|
| F3-1 | Hardkodet OCR/NLP-konfidens driver kvalitetsporten | bekreftet ved kjøring |
| F4-12 | Filnavn-PII overlever for alltid i audit_log | bekreftet ved kjøring |
| F4-13 | Retensjonstid 150 d ikke juridisk avklart (90/150/180) | policy-beslutning |
| F5-1 | Ingen .dockerignore (hemmeligheter i build-kontekst) | bekreftet ved kjøring |
| F5-2 | Postgres publisert til host, credentials nav/nav | bekreftet ved kjøring (`docker port` → `0.0.0.0:5432`) |
| F5-3 | Ingen minnegrenser i compose (OOM på delt GPU) | utledet fra kode |
| F5-4 | K8s RWO-PVC monteres av flere pods (deploy henger) | utledet fra kode |
| F4-1 | Ingen maks filstørrelse (minne-DoS) | utledet fra kode |

### HØY
F2-1 (ingen connection pool), F2-2 (ingen graceful shutdown — bekreftet live),
F2-3 (dobbeltbehandling ved process>60s), F2-4 (unlock uten eierskapssjekk),
F3-2 (anti-hallusinering-hull), F3-3 (ikke-deterministisk fylke), F4-2 (ingen
sidegrense), F4-3 (ingen søk-grense), F4-4 (ingen rate limiting), F4-6 (fail-open
nøkkel), F5-5 (floating pip), F5-6 (root i container), F5-7 (K8s uten limits),
F5-8 (K8s uten probes), F5-9 (ingen Prometheus i K8s).

### MIDDELS
F1-1 (state machine app-lag), F1-5 (mangler UNIQUE side), F2-5/F2-7 (dedup/
exactly-once), F2-6 (manglende indekser), F3-4 (engelsk OCR), F3-5 (kryssvalidering-
feil), F3-6 (grådig JSON-regex), F3-7 (BM25 score-0), F4-5 (str(exc)-lekkasje),
F4-7 (CORS *), F4-8 (/metrics åpent), F4-9 (sletting uten granularitet), F4-14
(backup-budsjett), F5-10..15, F6-2/F6-3.

### LAV
F1-2/F1-4 (død kø/tilstand), F2-8/F2-9, F4-10/F4-11, F4-15 (/tekst-bypass —
allerede advart), F5-16, F6-1/F6-4/F6-5.

## 4. Farligst for reell produksjon (må lukkes først)

1. **F3-1 — falsk kvalitetsport.** Systemets hele verdiforslag er «fang usikre
   dokumenter til menneskelig gjennomgang». Med hardkodet konfidens slipper
   håndskrift alltid gjennom. Uten fiks er kvalitetssikringen en illusjon.
2. **F4-12 — evig PII i audit_log.** Juridisk eksponering under GDPR; oppdages
   typisk først ved tilsyn.
3. **F5-2 — eksponert Postgres m/ trivielle credentials.** Direkte
   datainnbrudds-vektor for hele persondatalageret.
4. **F4-1/F4-2 — ubegrenset opplasting.** Én forespørsel kan ta ned tjenesten.
5. **F2-2 + F2-3 — deploy dreper jobber / dobbeltbehandling.** Hver K8s-
   rullering under last gir forsinkelser og mulige doble sideeffekter.

## 5. Beste tiltak etter (effekt ÷ innsats)

| Rang | Tiltak | Effekt | Innsats |
|---|---|---|---|
| 1 | `.dockerignore` (F5-1) | Kritisk sikkerhet | Minutter |
| 2 | `lang="no"` i PaddleOCR (F3-4) | Bedre OCR på alt | 1 linje |
| 3 | Bind Postgres til 127.0.0.1 (F5-2) | Lukker innbruddsvektor | 1 linje |
| 4 | **SIGTERM-handler i run-løkken (F2-2)** | **Stopper jobbtap ved hver deploy** | **~10 linjer** |
| 5 | **Slutt å logge råt filnavn til audit (F4-12, fremover-fiks)** | **Lukker GDPR-hull for NYE dokumenter** | **1-2 linjer** |
| 6 | Maks filstørrelse + sidegrense (F4-1/F4-2) | Stopper DoS | Timer |
| 7 | Fjern `str(exc)` fra responser (F4-5) | Stopper info-lekkasje | Timer |
| 8 | `AND locked_by=%s` i _frigi_las (F4-4/F2-4) | Lukker race | 1 linje |
| 9 | UNIQUE(dokument_id,side_nummer) + reconciliation-indekser (F1-5/F2-6) | Skala + integritet | Timer |
| 10 | Retroaktiv rydding av filnavn i eksisterende audit (F4-12) | Lukker GDPR-hull for GAMLE data | Timer + NAV-avklaring |
| 11 | Connection pool / pgbouncer (F2-1) | Skala-flaskehals | Dager |

> **VIKTIG om F3-1 (falsk kvalitetsport):** dette er systemets **#1 farligste
> funn** (seksjon 4), men står bevisst LAVT i effekt÷innsats-tabellen fordi
> ekte modellkonfidens krever dager med modellarbeid (`output_scores=True`,
> softmax-utledning per modell). Innsatsen senker rangen — den senker IKKE
> alvorligheten. Rekkefølge betyr «hva gir mest per krone», ikke «hva er
> viktigst». F3-1 må planlegges som eget arbeidsstykke uavhengig av
> quick-wins-lista, og inntil det er gjort bør håndskrift/tabell-dokumenter
> **tvinges til gjennomgang uansett konfidens** (midlertidig 1-linjes
> mitigering: rut alltid HANDSKRIFT/Marker-resultater til Label Studio).

## 6. Refaktorering vs. omskriving

**Ingen fil trenger full omskriving.** Kjernearkitekturen er sunn.

**Refaktorering anbefalt:**
- `last_opp.py` (684 l) → splitt per ressurs (F6-3)
- `lag1.py`/`lag2.py` → skill modell-inferens fra konfidens-utledning, gjør
  konfidens ekte (F3-1)
- `base_worker.py` → connection pool + SIGTERM + lås-eierskap (F2-1,2,4)
- `tekstuttrekk.py` → utvid anti-hallusinering til alle mønsterfelter (F3-2);
  `finn_fylke` deterministisk (F3-3)

**Bevisst beholdt som er:** legacy-tjenestene (7 HTTP-tjenester, 13 py-filer +
Dockerfiles/krav = 39 filer i legacy-kategorien, null trafikk — jf. fase 0 K1)
— ikke refaktorer, men vurder å fjerne fra repoet hvis de aldri skal brukes.

## 7. Beslutninger som krever DERES team / NAV (ikke Claude Code)

**Viktig avgrensning (F4-12 skal IKKE stå her udelt):** GDPR-hullet med filnavn
i audit_log har to deler som må skilles:
- **Fremover-fiksen er en ren kodefeil — starter NÅ, uten å vente på NAV:**
  slutt å skrive råt filnavn til `audit_log.details` (bruk hash/dokument_id).
  Dette er riktig uansett hva NAV bestemmer om retensjon. Ligger som tiltak
  #5 i effekt÷innsats-lista (1-2 linjer). Krever ingen ekstern avklaring.
- **Bare det retroaktive + varigheten krever NAV** (punkt 1 og 3 under).

Følgende er **ikke kodefeil** — de krever juridisk/organisatorisk avklaring:

1. **Oppbevaringstid (F4-13):** Hva er den juridisk bindende maksimale
   lagringstiden? De tre tallene i omløp: **90 dager** (3 mnd, tidligere oppgitt
   NAV-krav), **150 dager** (dagens kode-default, `oppbevaring.py:37`), **180
   dager** = det samlede budsjett-TAKET (oppbevaring + eldste backup-kopi, der
   «180» er valgt fordi 6 måneders arkivvindu ≈ 180 dager). Disse er ikke
   forsonet. **Arkivloven vs. GDPR-minimering må avklares** — statlige arkivkrav
   kan PÅBY lengre lagring enn GDPR tillater.
2. **Retroaktiv rydding av eksisterende audit-filnavn (F4-12, del 2):** De
   filnavnene som ALLEREDE er logget — skal de slettes/hashes retroaktivt?
   Teknisk trivielt (`UPDATE audit_log SET details = details - 'filnavn'`), men
   om audit «aldri skal endres» er et NAV-prinsipp, trengs godkjenning for å
   røre historiske rader.
3. **audit_log-innhold prinsipielt (F4-12, del 3):** NAV-kravet «audit slettes
   aldri» vs. «audit skal ikke inneholde persondata» — bekreft at anonymisert
   audit (kun dokument_id) tilfredsstiller sporbarhetskravet.
4. **Backup-innhold som persondata (F4-14):** Godtar juristene at pg_dump-er
   inneholder persondata inntil retensjonsgrensen? Bør dumpene krypteres og få
   eget hardt slettebudsjett? (Merk: `BACKUP_MAANEDLIGE=0` er allerede satt i
   koden — bekreftet ved kjøring — så aritmetikken 150+~28 ≤ 180 holder i dag,
   MEN det finnes ingen kode som HÅNDHEVER at pg_dump-er ikke overlever
   budsjettet; det hviler på GFS-tallene. Se F4-14, fortsatt «middels».)
5. **Kvalitetsport-terskler (relatert F3-1):** Når ekte konfidens innføres —
   hvilke terskler er faglig forsvarlige for auto-APPROVED uten gjennomgang?
6. **Autorisasjonsmodell (F4-9):** Delt nøkkel eller rolleskille (lese vs. slette)?

---

## Vedlegg — fasefiler
- `phase-0-inventory.md` — 156 filer, 14 815 linjer
- `phase-1-architecture-pipeline.md` — 5 funn
- `phase-2-workers-infra.md` — 9 funn (2 live-verifisert)
- `phase-3-ai-pipeline.md` — 7 funn (F3-1 kritisk)
- `phase-4-api-security-gdpr.md` — 15 funn (F4-12/F4-13 kritisk)
- `phase-5-infra-scale-resilience.md` — 16 funn (4 kritisk, live-tester)
- `phase-6-tests-quality.md` — testtall forsonet: 248+42=290, cov 32 % enhet

## Rettelse etter ekstern gjennomgang av fase 0
Rammingen «42 uten test, hvorav 39 legacy → 3 aktive» i fase 0 var upresis.
Korrekt (fase 0-tillegg K1): 13 legacy .py + 13 trivielle + **16 aktive-logikk-
filer** uten enhetstest. Av de 16 er kun **2 aktiv forespørselsbane uten noen
test** — `api/ruter/gjennomgang.py` og `api/ruter/sok.py` (nytt fase-6-punkt
F6-0). Resten er ML-/driftsverktøy eller har live-/integrasjonsdekning. Punkt
(6) er i tillegg nå bevist på BLANDET DONE/FAILED-tilstand, ikke bare
alle-FAILED (fase 1).

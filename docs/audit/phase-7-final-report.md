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
| **AI-pipeline** | 6.0 | mod11/RRF/deterministisk-over-modell korrekt (fase 3). Trekk: hardkodet konfidens (F3-1, kritisk), anti-hallusinering-hull (F3-2), ikke-deterministisk fylke (F3-3), engelsk OCR på norsk (F3-4). |
| **Produksjonsklarhet** | 5.0 | Backup/oppbevaring/model-serving live-bevist. Trekk: ingen .dockerignore (F5-1), Postgres eksponert (F5-2), ingen graceful shutdown (F2-2), manglende probes/limits i K8s (F5-7,8), GDPR-hull (F4-12). |

**Snitt: 6.4/10** — «avansert prototype / tidlig produksjon», konsistent med
brukerens egen vurdering ved oppstart.

## 3. Alle funn etter alvorlighet

### KRITISK
| ID | Funn | Klassifisering |
|---|---|---|
| F3-1 | Hardkodet OCR/NLP-konfidens driver kvalitetsporten | bekreftet ved kjøring |
| F4-12 | Filnavn-PII overlever for alltid i audit_log | bekreftet ved kjøring |
| F4-13 | Retensjonstid 150 d ikke juridisk avklart (90/150/180) | policy-beslutning |
| F5-1 | Ingen .dockerignore (hemmeligheter i build-kontekst) | bekreftet ved kjøring |
| F5-2 | Postgres publisert til host, credentials nav/nav | utledet fra kode |
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
| 4 | Maks filstørrelse + sidegrense (F4-1/F4-2) | Stopper DoS | Timer |
| 5 | Fjern `str(exc)` fra responser (F4-5) | Stopper info-lekkasje | Timer |
| 6 | `AND locked_by=%s` i _frigi_las (F4-4/F2-4) | Lukker race | 1 linje |
| 7 | UNIQUE(dokument_id,side_nummer) + reconciliation-indekser (F1-5/F2-6) | Skala + integritet | Timer |
| 8 | Fjern filnavn fra audit / hash det (F4-12) | Lukker GDPR-hull | Timer |
| 9 | Ekte modellkonfidens (F3-1) | Redder kvalitetsporten | Dager (modellarbeid) |
| 10 | Connection pool / pgbouncer (F2-1) | Skala-flaskehals | Dager |

## 6. Refaktorering vs. omskriving

**Ingen fil trenger full omskriving.** Kjernearkitekturen er sunn.

**Refaktorering anbefalt:**
- `last_opp.py` (684 l) → splitt per ressurs (F6-3)
- `lag1.py`/`lag2.py` → skill modell-inferens fra konfidens-utledning, gjør
  konfidens ekte (F3-1)
- `base_worker.py` → connection pool + SIGTERM + lås-eierskap (F2-1,2,4)
- `tekstuttrekk.py` → utvid anti-hallusinering til alle mønsterfelter (F3-2);
  `finn_fylke` deterministisk (F3-3)

**Bevisst beholdt som er:** legacy-lagene (39 filer, null trafikk) — ikke
refaktorer, men vurder å fjerne fra repoet hvis de aldri skal brukes.

## 7. Beslutninger som krever DERES team / NAV (ikke Claude Code)

Disse er **ikke kodefeil** — de krever juridisk/organisatorisk avklaring:

1. **Oppbevaringstid (F4-13):** Hva er den juridisk bindende maksimale
   lagringstiden for disse dokumentene? 90 dager (3 mnd), 150, eller 6 måneder?
   Koden må settes til det bekreftede tallet, og backup-budsjettet (F4-14)
   justeres deretter. **Arkivloven vs. GDPR-minimering må avklares** — statlige
   arkivkrav kan faktisk PÅBY lengre lagring enn GDPR tillater; da trengs
   juridisk avklaring om hvilket regime som gjelder disse spesifikke dokumentene.
2. **Backup-innhold som persondata (F4-14):** Godtar juristene at pg_dump-er
   inneholder persondata i inntil retensjonsgrensen? Skal dumpene krypteres og
   ha eget slettebudsjett?
3. **audit_log-innhold (F4-12):** NAV-kravet «audit slettes aldri» — er det
   forenlig med at audit ikke skal inneholde persondata? Bekreft at anonymisert
   audit (kun dokument_id, ikke filnavn/tekst) tilfredsstiller sporbarhetskravet.
4. **Kvalitetsport-terskler (relatert F3-1):** Når ekte konfidens innføres —
   hvilke terskler er juridisk/faglig forsvarlige for auto-APPROVED av
   persondokumenter uten menneskelig gjennomgang?
5. **Autorisasjonsmodell (F4-9):** Skal alle klienter dele én nøkkel, eller
   kreves rolleskille (lese vs. slette/GDPR-sletting)?

---

## Vedlegg — fasefiler
- `phase-0-inventory.md` — 156 filer, 14 815 linjer
- `phase-1-architecture-pipeline.md` — 5 funn
- `phase-2-workers-infra.md` — 9 funn (2 live-verifisert)
- `phase-3-ai-pipeline.md` — 7 funn (F3-1 kritisk)
- `phase-4-api-security-gdpr.md` — 15 funn (F4-12/F4-13 kritisk)
- `phase-5-infra-scale-resilience.md` — 16 funn (4 kritisk, live-tester)
- `phase-6-tests-quality.md` — testtall forsonet: 248+42=290, cov 32 % enhet

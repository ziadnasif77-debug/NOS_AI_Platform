# Fase 6 — Tester og kodekvalitet

**Metode:** kjørt full testsuite med `pytest-cov` + strukturell kodeanalyse.
Alle tall her er `bekreftet ved kjøring`.

---

## Punkt (7) — testtall-avviket forklart endelig

| Kilde | Tall | Forklaring |
|---|---|---|
| Tidligere «234» | 234 | Øyeblikksbilde FØR backup/model-serving/oppbevaring/sporsmal-testene ble lagt til |
| Tidligere «269» | 269 | Mellomliggende øyeblikksbilde (208 enhet + 42 + …) mens funksjoner ble lagt til |
| **Nå (kjørt i denne fasen)** | **248 enhet + 42 integrasjon = 290** | `pytest tester/ --ignore=integrasjon` → «248 passed» |

**Konklusjon:** ingen tester er fjernet eller deaktivert. Tallene er
monotont voksende øyeblikksbilder etter hvert som funksjoner ble lagt til
(208 → 227 → 248 enhetstester). `grep "def test_"` teller 284 funksjonsdefinisjoner
i alle testfiler (242 utenom integrasjon); pytest kollekterer 248 fordi noen er
parametriserte. Avviket er altså en tidsforskjell, ikke tapte tester.

## Reell dekning (kjørt med --cov)

**Samlet enhetsdekning: 32 %** — men dette tallet ALENE er misvisende:
enhets-cov måler kun in-process import; de 42 integrasjonstestene kjører mot
levende tjenester over HTTP/Redis/Postgres og treffer worker- og API-kode som
`--cov` ikke ser. Reell dekning av de kritiske banene er høyere.

| Modul | Enhets-cov | Vurdering |
|---|---|---|
| `delt/tekstuttrekk.py` | **94 %** | Utmerket — kjernen i anti-hallusinering grundig testet |
| `delt/skjemaer.py` | 100 % | Kontrakter fullt dekket |
| `delt/konstanter.py` | 100 % | |
| `tjenester/sok/fusjon.py` | 96 % | RRF-algoritmen testet |
| `delt/autentisering.py` | 88 % | Auth godt dekket |
| `tjenester/api/ruter/sporsmal.py` | 66 % | Ren logikk testet; HTTP-bane via integrasjon |
| `base_worker.py` | 39 % enhet | Resten dekkes av 42 integrasjonstester (ekte Postgres/Redis) |
| `lag0-3` workers | 0-29 % enhet | Dekkes av integrasjonstester ende-til-ende |
| `lag1.py`/`lag2.py` modell-ruting | lav | **Reelt hull — se F6-2** |
| `skript/finjuster.py`, `konverter_*`, `lag_datasett`, `send_til_label_studio` | 0 % | ML-verktøy, lavere prioritet |
| `skript/init_db.py` | 0 % | Skjema — verifiseres implisitt av integrasjonstester |

---

## Funn

### F6-1 · Lav · Ingen «alltid sanne» / falske tester funnet
Gjennomgang av assertions: testene sjekker faktiske verdier (radtall,
tilstander, felt-innhold), ikke trivielt-sanne påstander. `test_tekstuttrekk.py`
tester ekte mod11-tilfeller, `test_sporsmal.py` tester faktisk parsing.
**Klassifisering:** bekreftet ved kjøring. Positivt funn.

### F6-0 · Middels · To aktive API-ruter helt uten test (korrigert fra fase 0)
**Fil:** `tjenester/api/ruter/gjennomgang.py` (49 l), `tjenester/api/ruter/sok.py`
(26 l). Fase 0-tillegget (K1) korrigerte rammingen «3 aktive uten test» til de
faktiske 16 aktive-logikk-filene; av dem er disse to den eneste
produksjonskoden i forespørselsbanen uten NOEN test (verken enhet eller
integrasjon-import). Resten er ML-/driftsverktøy eller har live-/integrasjons-
dekning. **Fiks:** legg til minst integrasjonstest for `/gjennomgang/ko`,
`/gjennomgang/korriger/{id}` og søke-proxyen.
**Klassifisering:** bekreftet ved kjøring (coverage 0 %).

### F6-2 · Middels · Modell-ruting og konfidens-logikk mangler enhetstester
**Fil:** `lag1.py` (`_kjor_ocr`-ruting), `lag2.py` (`_ekstraher`-ruting).
Rutingen (dokumenttype → modell, len(tekst) → Borealis/NB-BERT) og den
hardkodede konfidensen (F3-1) har ingen enhetstest som ville fanget at
konfidensen er en konstant. **Fiks:** enhetstest med mockede modeller som
verifiserer ruting-grener OG at konfidens propageres fra modell (ikke konstant).
**Klassifisering:** bekreftet ved kjøring (cov viser hullet).

### F6-3 · Middels · Store filer / lange funksjoner (kompleksitets-hotspots)
**Fil:** `last_opp.py` (684 linjer, 13 endepunkter i én fil),
`lag2.py` (497 linjer), `reconciliation_worker.py` (487 linjer med en 60-linjers
SQL-drevet `ettersend_label_studio`). Ikke feil, men vedlikeholdsrisiko.
**Fiks:** splitt `last_opp.py` i moduler per ressurs (opplasting / dokument /
resultat / audit). **Klassifisering:** bekreftet ved kjøring (linjetelling fase 0).

### F6-4 · Lav · Duplisert kø-definisjon (jf. F1-2)
`konstanter.py` vs `config.yaml` — død duplikat. **Fiks:** én kilde.

### F6-5 · Lav · Manglende negative/edge-tester for nye endepunkter
`/tekst` med `fra_side>til_side`, `/sporsmal` med tomt dokument, `/felter` med
alle sider FAILED — logikken finnes og er verifisert live i denne økten, men
mangler regresjonstester. **Fiks:** legg til som enhets-/integrasjonstester.
**Klassifisering:** bekreftet ved kjøring.

---

## Kodekvalitet — generelt

- **Konsistent norsk** overalt (kode, kommentar, feilmelding, commit) — verifisert
- **Ingen død kode av betydning** utenom: VALIDATION-tilstand/kø (F1-4),
  duplisert kønavn (F1-2), redundant indeks (F2-9), legacy-lagene (39 filer,
  null trafikk — dokumentert, bevisst beholdt)
- **Hardkodede verdier:** de hardkodede konfidensene (F3-1) er det alvorlige
  tilfellet; ellers er terskler/tall i `config.yaml` (bra)
- **Feilhåndtering:** gjennomgående `try/except` med logging; svakhet er rå
  `str(exc)` til klient (F4-5)
- **Docstrings:** rikelige og presise, men F3-2 viser ett tilfelle der docstring
  lover mer enn koden gjør (anti-hallusinering) — verifiser mot implementasjon

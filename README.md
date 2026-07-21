# NAV Dokument-API

Et frittstående, klientnøytralt dokument-API som kjører **native på
Windows med GPU** ([skript/dokument_api.py](skript/dokument_api.py)).
Leser et dokument **én gang**, trekker ut felter og svarer — og **lagrer
ingenting**: ingen database, ingen søkeindeks, ingen arkiv.
Kildedokumentene er allerede arkivert et annet sted.

> **Live API-dokumentasjon (Swagger UI):** `http://localhost:8600/dokumentasjon`
> (OpenAPI 3: `/openapi.json`). Eksponeres du gjennom en tunnel, bytt
> `localhost` med tunneladressen.

Brukes fra GUI-er ([skript/api_klient_gui.py](skript/api_klient_gui.py)),
UiPath, curl eller egne skript. Full brukerdok:
[docs/api_dokumentasjon.md](docs/api_dokumentasjon.md) · komplett
regelverk (R1–R60): [docs/regler_lokal_api.md](docs/regler_lokal_api.md).

---

## Kontrakten

| Du sender | Du får |
|---|---|
| Fil alene | HELE den utleste teksten, ordrett — deterministisk, aldri via modell |
| Fil + `korriger=ja` | LLM-korrigert OCR-tekst i tillegg (rå tekst beholdes alltid) |
| Fil + spørsmål | Spørsmål besvares (tallvakt) / JSON-mal fylles (kodevalidert) |
| Tekst alene | Generelt modellsvar, ærlig merket `uten_dokument` |

**Ingenting av dette lagres.** Svaret returneres til kalleren, så
forkastes dokumentet. Vil du ha modellen til å lære av et dokument, sender
du korreksjonen inn i treningsløkken (se under) — det er den eneste veien
data bevares, og bare midlertidig, til finjusteringen har kjørt.

---

## Endepunkter

| Endepunkt | Gjør |
|---|---|
| `POST /spor` | fil + spørsmål → svar fra Borealis · fil UTEN spørsmål → hele teksten ordrett · valgfritt `korriger=ja` |
| `POST /analyser` | fil → deterministiske felter, alle datoer (med begrunnelse), strekkoder, håndskriftdeteksjon, full tekst |
| `POST /uttrekk` | fil → komplett strukturert JSON: alle nøkler alltid til stede, identifikatorer sjekksumvalidert |
| `POST /fyll_skjema` | fil + din egen JSON-mal → malen utfylt fra dokumentet, kodevalidert felt for felt (avvik rapporteres) |
| `POST /jobb` | fil → `jobb_id` med en gang; OCR av HELE dokumentet kjører i bakgrunnen (store skanninger) |
| `GET /dokumentasjon` · `/openapi.json` · `/hjelp` | Swagger UI · maskinlesbart skjema · tjenestestatus |

---

## Nøkkelegenskaper

- **Regionbasert OCR** ([delt/region_ocr.py](delt/region_ocr.py)):
  EasyOCR (eller RapidOCR på CPU når GPU-en er full) leser trykt tekst,
  usikre håndskriftregioner leses i tillegg av **norhand** (TrOCR), beste
  motor vinner per region, fletting i leserekkefølge. Adaptivt motorvalg
  etter ledig VRAM (R51), batch-lesing og tids-/antallstak for
  håndskriftmodellen (R52/R55).
- **Kodevakter, ikke løfter** ([delt/tekstuttrekk.py](delt/tekstuttrekk.py)):
  tallvakt (tall i svar må stå ordrett i dokumentet), mod11-validering
  (fnr/konto/orgnr), KID (mod10/mod11), aritmetisk konsistens i
  skjemautfylling, aldri stille trunkering. Modellen foreslår, koden
  verifiserer — mattematikk slår gjetning for strukturerte felter.
- **Borealis 4B** (Nasjonalbibliotekets GGUF Q8 via llama.cpp/CUDA):
  filhash-cache gjør oppfølgingsspørsmål på samme dokument øyeblikkelige.
- **Brukerstyrt uten kodeendring:** [egne_regler.txt](egne_regler.txt)
  (svarstil) og [egne_etiketter.txt](egne_etiketter.txt) (nye
  dato-etiketter) leses umiddelbart — nye dokumenttyper krever aldri
  kodefiks.
- **Sikkerhet:** valgfri `X-API-Key` (`API_NOKKEL`), CORS av som standard
  (`CORS_ORIGINS`), rate-limiting per klient (`RATE_LIMIT_PER_MIN`, standard
  120/min), generiske feilmeldinger (detaljer kun i serverloggen).
- **Sporbarhet (§4):** hvert svar stemples med full proveniens — API-,
  prompt-, norhand-, uttrekk-regel- og terskelversjon (og LLM-modell når
  `/spor` brukte den) — så et result kan spores til nøyaktig det som
  produserte det.
- **Oppbevaring (GDPR):** [skript/rydd_gjennomgang.py](skript/rydd_gjennomgang.py)
  (`make rydd`) rydder gamle gjennomgangsbilder etter `OPPBEVARING_DAGER`
  — tørrkjøring som standard, `--slett` for å faktisk slette.
- **Generelt verktøy for lovtekster:**
  [skript/hent_lovtekst.py](skript/hent_lovtekst.py) henter enhver lov fra
  Lovdata.

---

## AI-modeller

Alle modeller kjører **100 % offline** etter første nedlasting.

| Nøkkel | Modell | Bruk |
|--------|--------|------|
| `norhand` | `Sprakbanken/TrOCR-norhand-v3` | Håndskrift-OCR — den ENESTE trente modellen som finjusteres i løkken |
| `borealis` | `NbAiLab/borealis-4b-instruct-preview` (GGUF Q8) | Norsk LLM — svar/utfylling |

Trykt tekst leses av EasyOCR/RapidOCR (henter egne vekter automatisk). Kun
disse to modellene brukes i leseløypa. Tidligere lastet prosjektet også
`nb-bert`, `nb-bert-ner`, `qwen3-embed`, `layoutlmv3` og Marker — for
klassifisering, NER, vektorsøk og layout — men de funksjonene er fjernet,
og modellene med dem (2026-07-21).

```bash
python skript/last_ned_modeller.py     # last ned de to modellene (én gang)
```

---

## Treningsløkke (valgfri modellforbedring)

Modellen (norhand/TrOCR) forbedres av menneskelige korreksjoner. Hele
løkken kjøres av én orkestrator, `make trening`:

```
dårlig lest dokument (lav OCR-konfidens ELLER håndskrift ELLER tomt resultat)
   → AUTOMATISK til Label Studio            (serveren, i bakgrunnen — se under)
   → menneske retter teksten
   → skript/kjor_treningslop.py:
        1. eksporter_fra_label_studio.py     (→ data/finjustering/trocr_*.json)
        2. finjuster.py                       (trener norhand/TrOCR → KANDIDAT, ikke live)
        3. valider_modell.py                  (kvalitetsport: CER kandidat vs live)
   → godkjent → promotert → server-omstart tar modellen i bruk
   → avvist  → live står urørt (rull-tilbake tilgjengelig)
```

**Kvalitetsport før produksjon** (steg 3): trening lager en *kandidat*,
ikke en live modell. Porten måler tegnfeilrate (CER) for kandidat mot live
på et **fast valideringssett** ([data/validering/](data/validering/README.md))
og promoterer bare hvis kandidaten er minst like god (`CER_MARGIN`). En
dårlig korreksjonsbatch stoppes dermed i porten, ikke i produksjon. Forrige
live tas vare på i `modeller/norhand-forrige` for umiddelbar rull-tilbake
(`python skript/valider_modell.py --rull-tilbake`). Uten valideringssett
promoteres ingenting automatisk.

Orkestratoren (`kjor_treningslop.py`) skriver et sammendrag av hvert løp
(antall korreksjoner, CER live/kandidat, port-utfall, varighet) til stdout
og `data/logger`. Planlegg tilbakevendende kjøring med Windows Task
Scheduler.

**Kontroll + observabilitet med Prefect** (valgfritt, Apache 2.0): kjør
løkka fra et web-UI og se NØYAKTIG hvilket steg som evt. feilet, med logg
og traceback. Prefect ligger i et eget venv (`.venv-prefect`); flyten
([skript/prefect_flyt.py](skript/prefect_flyt.py)) kaller treningsskriptene
i hovedmiljøet via subprocess, så det ikke kolliderer med torch.

```bash
python -m venv .venv-prefect && .venv-prefect/Scripts/pip install prefect
make prefect-server   # UI på http://127.0.0.1:4200
make prefect-kjor     # kjør løkka som flyt
```

**Auto-gjennomgang** (det første steget): leser serveren et dokument
dårlig, sender den det selv til Label Studio for korreksjon — i en
bakgrunnstråd, så svaret til klienten aldri forsinkes. Svaret merker det
med `sendt_til_gjennomgang`. Utløses av lav OCR-konfidens (< 0.85),
håndskrift, eller nesten tom lesing.

Dette er **AV som standard** — det aktiveres kun når du setter både
`LABEL_STUDIO_URL` og `LABEL_STUDIO_API_KEY`. Uten dem lagres og sendes
ingenting; serveren bare leser, svarer og forkaster. Det er også den
eneste delen som bevarer data (bildet + rå tekst i Label Studio,
midlertidig, til korreksjonen er hentet inn i treningen).

Modellene lastes ved oppstart, så en nytrent modell tas i bruk etter en
omstart av serveren.

---

## Kjøring

```bash
python skript/dokument_api.py            # starter serveren på :8600
python skript/api_klient_gui.py          # GUI-klienten (kobler til :8600)
```

Miljøvariabler (alle valgfrie): `API_NOKKEL` (krev X-API-Key),
`CORS_ORIGINS`, `DOKUMENT_API_PORT` (standard 8600), `BOREALIS_KONTEKST`,
`OCR_MOTOR` (auto/easy/rapid). Se [.env.example](.env.example).

**Kjør som tjeneste** (starter ved oppstart, restarter ved krasj — uten
Docker): [skript/tjeneste/LES_MEG.md](skript/tjeneste/LES_MEG.md).

### Offline-distribusjon (isolert server uten internett)

```bash
python skript/pakk_for_offline.py        # på en maskin MED internett → offline_pakke/
# kopier offline_pakke/ + prosjektet + modeller til serveren, deretter:
python skript/installer_offline.py       # installerer wheels uten internett
python skript/sjekk_miljo.py             # verifiserer Python/GPU/DLL/modeller
```

Full guide: [docs/offline_installasjon.md](docs/offline_installasjon.md).

---

## Testing

```bash
python -m pytest tester/ -q             # 71 enhetstester (server stoppet, så GPU er fri)
python skript/kjor_korpus.py            # regresjonskorpus: ekte dokumenter mot fasit
```

Korpuset ([tester/korpus/](tester/korpus/)) kjører ekte dokumenter mot en
fasit skrevet av et menneske og rapporterer treffprosent — «virker det?»
som et tall, ikke en magefølelse.

---

## Historikk

Prosjektet hadde tidligere også et distribuert mikrotjeneste-system
(Postgres/Redis/Milvus/Kubernetes) for masse-arkivering og søk. Det ble
fjernet 2026-07-21: dokumentene er allerede arkivert et annet sted, så
det er ikke lenger behov for arkiv eller søk her. Denne serveren
behandler ett dokument om gangen og lagrer ingenting — se
[docs/regler_lokal_api.md](docs/regler_lokal_api.md) for fail-open-
filosofien (flagg og forklar, aldri stille feil).

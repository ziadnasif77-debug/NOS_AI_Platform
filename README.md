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
UiPath, curl eller egne skript.

| Dokumentasjon | Hva |
|---|---|
| [docs/endepunkter.md](docs/endepunkter.md) | **Komplett endepunktreferanse** — felter inn/ut, hvilke som bruker modellen, klientfeller |
| [docs/api_dokumentasjon.md](docs/api_dokumentasjon.md) | Arbeidsflyter og eksempler |
| [docs/regler_lokal_api.md](docs/regler_lokal_api.md) | Regelverket R1–R67 |
| [docs/prosjektjournal.md](docs/prosjektjournal.md) | **Prosjektjournal** — status mot konseptutredningen, lærdommer, milepæler |
| [docs/naar_noe_gaar_galt.md](docs/naar_noe_gaar_galt.md) | **Feilboka** — symptom → årsak → hva du gjør. Skrevet for drift uten utvikler og uten internett |
| `GET /dokumentasjon` | Swagger UI med svarmodeller og innebygd veiledning |

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

**`POST /dokument` er hovedveien** — ett kall med brytere for alt under.
Dokumentet leses én gang uansett hvor mange deler du ber om, og
modelldelene er AV som standard, så det raske forblir raskt.

```bash
curl -X POST http://localhost:8600/dokument \
     -F "fil=@dokument.pdf" \
     -F "struktur=ja" -F "koordinater=ja" \
     -F "sporsmal=Hva er totalbeløpet?"
```

| Bryter | Gjør | Modell? |
|---|---|---|
| `tekst` (standard på) | Hele den utleste teksten | nei |
| `felter` (standard på) | Deterministiske felter + datoer med begrunnelse | nei |
| `struktur` | Komplett strukturert uttrekk (som `/uttrekk`) | nei |
| `koordinater` | Beviste funn med bokser per side — til utheving i en GUI | nei |
| `sporsmal` | Fritt spørsmål med tallvakt | ja* |
| `skjema_mal` + `skjema_motor` | Din JSON-mal utfylt (`felter`/`auto`/`modell`) | avhenger |
| `korriger` | LLM-korrigert OCR-tekst ved siden av den rå | ja |

\* Sidespørsmål (`les side 10`), strekkodespørsmål og spørsmål etter
sjekksumvaliderte identifikatorer besvares av **koden**, ikke modellen —
de virker også når Borealis er nede. `kilde` i svaret sier hvilken vei
som ble tatt.

**Øvrige endepunkter:**

| Endepunkt | Gjør |
|---|---|
| `POST /forhandssjekk` | Kvalitetsdom FØR prosessering (dpi, skarphet, tomme sider) — **uten GPU**. `dom`: god/tvilsom/avvis |
| `POST /sladd` | Sladder det som kan BEVISES (fnr, konto, orgnr, KID, telefon, epost). Navn/adresser deklareres udekket |
| `POST /ekko` | Diagnose: svarer med NØYAKTIG hva serveren mottok. Bruk den før du gjetter på klientoppsettet |
| `POST /jobb` → `GET /jobb/{id}` | Store skanninger: `jobb_id` med en gang, OCR i bakgrunnen |
| `POST /innsyn` → `GET /innsyn/{id}` | Direktevisning: strømmer lesingen hendelse for hendelse |
| `POST /dokument/operasjoner` | Operasjonslista som EGEN ressurs — på `/dokument` overstyrer feltet bryterne i stillhet |
| `POST /spor` | Spørsmål **uten** fil: generelt modellsvar, merket `uten_dokument`. Det er den ene tingen `/dokument` ikke kan (den krever fil) |
| `GET /dokumentasjon` · `/openapi.json` · `/hjelp` | Swagger UI · maskinlesbart skjema · tjenestestatus |

⚠️ `/analyser`, `/uttrekk` og `/fyll_skjema` er FJERNET. De ga fakta
`/dokument` også gir, i tre andre JSON-former, og fantes bare fordi de
kom først. Erstatning: `felter=ja`, `struktur=ja` og `skjema_mal=…`.
Detaljer: [docs/endepunkter.md](docs/endepunkter.md).

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
  verifiserer — matematikk slår gjetning for strukturerte felter.
- **Koden svarer der koden VET** — en 4B-modell skal ikke telle sider
  eller gjengi sifre den ikke trenger å tolke. Sidespørsmål,
  strekkodeverdier og sjekksumvaliderte identifikatorer rutes
  deterministisk forbi modellen, og virker også når Borealis er nede.
  Identifikatorsvar lister ALLE treff (en bunke kan gjelde flere
  personer) — modellen ville valgt ett.
- **Koordinater per funn** (`koordinater=ja`): hvert beviste funn med
  boks og side, i et deklarert koordinatrom — så en GUI kan uthevet
  treffet i dokumentet og saksbehandleren slipper å lete manuelt.
  Fungerer både på OCR-veien (bildepiksler) og tekstlags-PDF
  (PDF-punkter).
- **Borealis 4B** (Nasjonalbibliotekets GGUF Q8 via llama.cpp/CUDA):
  filhash-cache gjør oppfølgingsspørsmål på samme dokument øyeblikkelige.
- **Alle regler ett sted:** mappa [regler/](regler/) styrer hva modellen
  svarer — [prompter.md](regler/prompter.md) (all prompttekst, ingen
  ligger i koden), [egne_regler.txt](regler/egne_regler.txt) (svarstil)
  og [egne_etiketter.txt](regler/egne_etiketter.txt) (nye dato-etiketter).
  Alle tre leses umiddelbart, uten omstart — nye dokumenttyper og nye
  regler krever aldri kodefiks. Se [regler/LES_MEG.md](regler/LES_MEG.md).
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

### Bytte språkmodell — med port og angreknapp (R188/R189)

Serveren tar den nyeste `.gguf` i `modeller/borealis-gguf`, så et bytte
er teknisk sett «kopier inn en fil». Det er nettopp problemet: en modell
som ikke får plass gir et **nativt krasj uten traceback**, og en som er
dårligere ser helt normal ut. Bruk derfor porten:

```bash
.pyruntime\python.exe skript\bytt_modell.py <ny-modell.gguf>
```

Den kjører hele runden og stopper ved første grunn til å la være:
filsignatur → VRAM-budsjett (får den plass, OG blir det nok igjen til
OCR?) → promptankre → mål dagens modell → bytt → mål den nye → døm.
**Dommen faller på konfidensintervaller, ikke på to tall** (R148/R189):
er forskjellen ikke skillbar fra tilfeldighet, byttes ingenting. Går noe
galt, rulles forrige modell tilbake automatisk.

```bash
.pyruntime\python.exe skript\bytt_modell.py --sjekk <fil>   # bare sjekk, endrer ingenting
.pyruntime\python.exe skript\bytt_modell.py --status        # hva kjører nå?
.pyruntime\python.exe skript\bytt_modell.py --rull-tilbake  # angre
```

Forrige modell ligger i `modeller/borealis-forrige` og **slettes aldri
automatisk**. Alt dette finnes også som knapper i kontrollpanelet under
fanen **Modeller** — laget for at serveren skal kunne stelles uten at
noen kan koden.

Målingen bruker spørsmålskorpuset
([tester/korpus/sporsmaal_syntetisk_bunke.json](tester/korpus/sporsmaal_syntetisk_bunke.json)):

```bash
.pyruntime\python.exe skript\kjor_sporsmaalskorpus.py
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

## Drift: hold API-et oppe

```bash
oppstart\start_api_med_vakthund.bat
```

Starter API-et og passer på det. Dør eller henger det, startes det på
nytt — og **exitkoden skrives til `data/logger/vakthund.log`**.

Det siste er ikke pynt. Da API-et stoppet gjentatte ganger over to døgn,
sluttet loggen midt i en rekke `/hjelp → 200`: ingen traceback, ingen
oppføring i Windows' hendelseslogg. Uten exitkoden ga to døgn med krasj
null informasjon. Med den vet man med én gang om det var et native
krasj (`0xC0000005` — llama.cpp/CUDA, ingen Python-feil å lete etter)
eller om noe drepte prosessen utenfra (`0xFFFFFFFF`).

Vakthunden starter ikke en server til hvis en allerede svarer — den
legger seg til å overvåke.

## Kjøring

```bash
python skript/dokument_api.py            # starter serveren på :8600
python skript/api_klient_gui.py          # GUI-klienten (kobler til :8600)
```

Miljøvariabler (alle valgfrie): `API_NOKKEL` (krev X-API-Key),
`CORS_ORIGINS`, `DOKUMENT_API_PORT` (standard 8600), `BOREALIS_KONTEKST`,
`OCR_MOTOR` (auto/easy/rapid), `OCR_MAKS_SIDER`/`OCR_TAK_SIDER`,
`STREKKODE_MAKS_SIDER`, `FORHANDSSJEKK_MAKS_SIDER`,
`RATE_LIMIT_PER_MIN`. Se [.env.example](.env.example).

> Serveren binder til `0.0.0.0`, altså er den nåbar fra andre maskiner på
> nettet med en gang. Sett `API_NOKKEL` før du eksponerer den.

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
python -m pytest tester/ -q             # 505 enhetstester (server stoppet, så GPU er fri)
python skript/kjor_korpus.py            # regresjonskorpus mot kjørende server
```

Korpuset ([tester/korpus/](tester/korpus/)) kjører dokumenter mot en
fasit skrevet av et menneske og rapporterer treffprosent — «virker det?»
som et tall, ikke en magefølelse. Fasitene ligger i git; dokumentene
gjør ikke.

**Korpuset inneholder KUN syntetiske dokumenter.** Fasit-verdier lever
evig i git-historikken, så et ekte dokument ville lekket person- og
betalingsopplysninger inn i kodelageret — også når selve filen holdes
utenfor. Trenger du et vanskelig trekk (skjev skanning, termopapir,
håndskrift), gjenskap trekket syntetisk. Se
[tester/korpus/README.md](tester/korpus/README.md).

---

## Historikk

Prosjektet hadde tidligere også et distribuert mikrotjeneste-system
(Postgres/Redis/Milvus/Kubernetes) for masse-arkivering og søk. Det ble
fjernet 2026-07-21: dokumentene er allerede arkivert et annet sted, så
det er ikke lenger behov for arkiv eller søk her. Denne serveren
behandler ett dokument om gangen og lagrer ingenting — se
[docs/regler_lokal_api.md](docs/regler_lokal_api.md) for fail-open-
filosofien (flagg og forklar, aldri stille feil).

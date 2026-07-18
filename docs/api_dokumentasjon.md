# NAV dokument-API — brukerdokumentasjon

Interaktiv dokumentasjon (Swagger UI): **`GET /dokumentasjon`**
Maskinlesbar spesifikasjon (OpenAPI 3): **`GET /openapi.json`**
Status og oversikt: **`GET /hjelp`**

Basis-URL lokalt: `http://localhost:8600` — via tunnel: din
trycloudflare-adresse. Er serveren startet med `API_NOKKEL`, kreves
headeren `X-API-Key` på alle kall (unntatt `/hjelp`).

## Kontrakten (kort)

| Du sender | Du får |
|---|---|
| Fil alene (uten `sporsmal`) | HELE den utleste teksten, ordrett — deterministisk, aldri via modell (R47) |
| Fil + `korriger=ja` | I tillegg: LLM-korrigert OCR-tekst i eget felt (rå tekst beholdes alltid) |
| Fil + tekst | Bestillingen utføres: spørsmål besvares med tallvakt; JSON-mal fylles med kodevalidering |
| Tekst alene (uten fil) | Generelt modellsvar — ærlig merket `uten_dokument: true` |

## De fire arbeidsflytene

### 1. Fil → alt innhold, uendret

```bash
curl -X POST http://localhost:8600/spor -F "fil=@dokument.pdf"
```

Svar: `svar` = hele teksten, `kilde: deterministisk_fulltekst`.
Skannede filer OCR-es automatisk (regionruting: EasyOCR + norhand for
håndskrift); OCR-artefakter beholdes — ingen tillegg, ingen utelatelser.

### 2. Fil → forbedret innhold

```bash
curl -X POST http://localhost:8600/spor -F "fil=@skannet.pdf" \
     -F "sporsmal=hent ut hele teksten" -F "korriger=ja"
```

Svar: `korrigert_tekst` (åpenbare OCR-feil rettet fra kontekst, strenge
antihallusineringsregler) VED SIDEN AV den rå teksten — aldri i stedet.

### 3. Fil + tekst → utfør bestillingen

```bash
# Spørsmål (tallvakt verifiserer at tall i svaret står i dokumentet)
curl -X POST http://localhost:8600/spor -F "fil=@faktura.pdf" \
     -F "sporsmal=Hva er totalbeløpet?"

# JSON-mal (limes rett i sporsmal-feltet ELLER sendes til /fyll_skjema)
curl -X POST http://localhost:8600/fyll_skjema -F "fil=@faktura.pdf" \
     -F "skjema=<min_mal.json"
```

Skjemautfylling er kodevalidert felt for felt (struktur-lås, tallvakt,
typesjekker, aritmetisk konsistens) — alle inngrep deklareres i `avvik`.

### 4. Tekst alene → svar

```bash
curl -X POST http://localhost:8600/spor \
     -F "sporsmal=Hva er folketrygden?"
```

Svar merkes `uten_dokument: true` — generell modellkunnskap, ikke
dokumentfakta, og tallvakten gjelder derfor ikke.

## Øvrige endepunkter

- `POST /analyser` — deterministisk analyse: felter, alle datoer
  (klassifisert med begrunnelse), strekkoder/QR, håndskrift, full tekst
- `POST /uttrekk` — komplett strukturert totaluttrekk med fast skjema:
  alle nøkler alltid til stede, identifikatorer sjekksumvalidert
- `POST /jobb` → `GET /jobb/{id}` → `POST /spor (jobb_id=...)` —
  store skannede dokumenter: ubegrenset sideantall i bakgrunnen,
  fremdrift og tidsestimat, spørsmål besvares øyeblikkelig etterpå
- `GET /jobb/{id}/tekst`, `POST /jobb/{id}/avbryt`

## Python-eksempel

```python
import requests

BASIS = "http://localhost:8600"

# Fil alene -> alt innhold
with open("dokument.pdf", "rb") as f:
    fullt = requests.post(f"{BASIS}/spor", files={"fil": f}).json()["svar"]

# Fil + sporsmal -> svar
with open("dokument.pdf", "rb") as f:
    svar = requests.post(f"{BASIS}/spor", files={"fil": f},
                         data={"sporsmal": "Hva er fristen?"}).json()
    print(svar["svar"], svar["tall_verifisert"])
```

## Ærlighetsfelter i alle svar

`advarsel` (all trunkering/usikkerhet sies fra om), `tall_verifisert`,
`avvik`, `svar_avkortet`, `ocr_brukt`/`ocr_motorer`, `fra_cache`,
`tid_sekunder`, `versjon` (api + prompt + modellmotor). Fullstendig
regelverk: `docs/regler_lokal_api.md` (R1–R47).

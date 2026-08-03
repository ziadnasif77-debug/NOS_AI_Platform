# Endepunktreferanse — NAV dokument-API

Komplett oversikt over HVERT endepunkt: hva det gjør, hvilke felter det
tar imot, hva det svarer med, og om modellen brukes.

Alt her er **verifisert mot en kjørende server** (2026-08-03), ikke lest
ut av koden alene. Brukerdokumentasjonen med arbeidsflyter ligger i
[api_dokumentasjon.md](api_dokumentasjon.md); regelverket R1–R47 i
[regler_lokal_api.md](regler_lokal_api.md).

Basis-URL lokalt: `http://localhost:8600`. Er serveren startet med
`API_NOKKEL`, kreves headeren `X-API-Key` på alle kall unntatt `/hjelp`.

---

## Velg riktig endepunkt

| Vil du … | Bruk |
|---|---|
| Ha ETT kall som gjør alt du trenger | **`POST /dokument`** ← anbefalt |
| Bare lese teksten ordrett | `POST /spor` (uten `sporsmal`) |
| Ha komplett strukturert JSON med faste nøkler | `POST /uttrekk` |
| Fylle din egen JSON-mal | `POST /dokument` med `skjema_mal` |
| Behandle et STORT skannet dokument | `POST /jobb` → `GET /jobb/{id}` |
| Avvise et dårlig skann FØR GPU-en brukes | `POST /forhandssjekk` |
| Sladde beviste identifikatorer (fnr, konto, …) | `POST /sladd` |
| Finne ut hva serveren FAKTISK mottok fra deg | `POST /ekko` |

**`/dokument` er hovedveien.** De øvrige dokumentendepunktene er eldre og
beholdes bevisst for å ikke bryte eksisterende integrasjoner (særlig
UiPath). De gir stort sett SAMME fakta, men i ULIKE JSON-former — se
[Samme faktum, ulike stier](#samme-faktum-ulike-stier).

---

## POST /dokument

Ett kall, brytere for hva som skal gjøres. Dokumentet leses **én gang**,
uansett hvor mange deler du ber om.

### Felter inn

| Felt | Verdier | Standard | Modell? |
|---|---|---|---|
| `fil` | filparten | *påkrevd* | — |
| `tekst` | ja/nei | ja | nei |
| `felter` | ja/nei | ja | nei |
| `struktur` | ja/nei | nei | nei |
| `svar` | ja/nei | nei | **ja** |
| `sporsmal` | fritekst | — | **ja** (slår på `svar` selv) |
| `skjema` | ja/nei | nei | avhenger av motor |
| `skjema_mal` | din JSON-mal | — | slår på `skjema` selv |
| `skjema_motor` | `felter` / `auto` / `modell` | `modell` | se under |
| `korriger` | ja/nei | nei | **ja** |
| `maks_sider` | tall | — | nei |
| `strekkoder` | ja/nei | ja | nei |
| `operasjoner` | JSON-liste | — | avhenger av typene |

Modelldelene er **AV som standard**, slik at det raske forblir raskt.
Sender du `sporsmal` eller `skjema_mal` uten å sette bryteren, slås den
på av seg selv — hensikten er åpenbar.

Ukjent bryterverdi gir **400**, ikke stille «nei». Ukjent FELTNAVN gir
200 med en linje i `kvalitet.advarsler` — du får aldri et felt ignorert
i stillhet.

### De tre skjemamotorene

| Motor | Modell? | Hva den gjør |
|---|---|---|
| `felter` | nei | Fletter `{feltnavn}`-plassholdere deterministisk. Virker selv om Borealis er nede. |
| `auto` | delvis | Regel der den kan **bevise**, modell for resten. Svarer med `kilde_per_felt` per felt. |
| `modell` | ja | Borealis fyller, koden validerer (`avvik`). Standard. |

`auto` er som regel riktig valg: du får bevis der bevis finnes, og
`kilde_per_felt` forteller nøyaktig hvilke felter som er gjettet.

### Svar

```
ok, filnavn, valg, tekst, antall_tegn, felter, struktur, svar, skjema,
korriger, korrigert_tekst, strekkoder, handskrift, kvalitet, fra_cache,
tid_sekunder, kilde, versjon
```

Deler du ikke ba om er `null`. `kilde` sier om modellen faktisk kjørte
(se [Ærlighetsfelter](#ærlighetsfelter)).

---

## POST /uttrekk

Komplett strukturert totaluttrekk med **fast skjema** — alle nøkler
alltid til stede, tomt er `""` / `[]`. Aldri modell.

Svar: `ok, dokument, identifikatorer, kontakt, adresser, datoer,
perioder, belop, tekst, strekkoder, handskrift, kvalitet, versjon`

Merk formen: `belop` er en **liste av objekter** med kontekst, ikke ett
tall.

```json
"belop": [{"verdi": 463.0, "raatekst": "463,00",
           "kontekst": "… Pris Kr: 463,00 + Utlegg Kr: …"}]
```

Dokumentets EGEN dato ligger under `dokument.dokumentdato` — ikke i
`datoer`. Der ligger datoene dokumentet HANDLER om.

Tilsvarende innhold fås fra `/dokument` med `struktur=ja`, under
nøkkelen `struktur`.

---

## POST /analyser

Deterministisk analyse. Aldri modell.

Svar: `ok, filnavn, trenger_ocr, ocr_brukt, kilde, felter, datoer,
datoer_detaljert, dokumentdato, strekkoder, tekst, antall_tegn`

`trenger_ocr` er det eneste feltet som ikke finnes noe annet sted.

---

## POST /spor

Den eldste veien. Oppfører seg ulikt etter hva du sender:

| Du sender | Du får | Modell? |
|---|---|---|
| `fil` alene | HELE teksten ordrett, `kilde: deterministisk_fulltekst` | **nei** (R47) |
| `fil` + `sporsmal` | Svar fra Borealis med tallvakt | ja |
| `fil` + `sporsmal` som er en JSON-mal | Rutes automatisk til skjemautfylling | ja |
| `sporsmal` alene | Generelt modellsvar, merket `uten_dokument: true` | ja |
| `jobb_id` + `sporsmal` | Svar mot en ferdig bakgrunnsjobb | ja |
| `+ korriger=ja` | I tillegg `korrigert_tekst` | ja |

Har **ingen** `dokumentdato`. Trenger du både svar og felter i samme
kall, bruk `/dokument`.

---

## POST /fyll_skjema

Fyller din egen JSON-mal. Samme tre motorer som `/dokument`.

> ⚠️ **Feltet heter `skjema` her — ikke `skjema_mal`.**
> Motorfeltet heter `skjema_motor` på BEGGE endepunktene.
> Sender du `skjema_mal` hit, får du 400. Sender du `motor` i stedet for
> `skjema_motor`, får du 200 med en linje i `advarsler` — og motoren
> faller tilbake til `modell`, som koster GPU-tid.

Svar: `ok, filnavn, fra_cache, advarsler, versjon, motor, skjema, avvik,
tid_sekunder, kilde` (+ `kilde_per_felt`, `modell_brukt` for `auto`;
+ `ukjente_felter`, `tilgjengelige_felter` for `felter`/`auto`)

Har ingen `dokumentdato`-nøkkel, men du kan be om verdien i malen med
plassholderen `{dokumentdato}`.

---

## Bakgrunnsjobber — store skannede dokumenter

| Kall | Gjør |
|---|---|
| `POST /jobb` | Starter OCR av HELE dokumentet i bakgrunnen → `jobb_id` med en gang |
| `GET /jobb/{id}` | Status, fremdrift (`sider_ferdig`/`sider_totalt`), tidsestimat — og når ferdig: `felter`, `datoer`, **`dokumentdato`**, `strekkoder`, `handskrift` |
| `GET /jobb/{id}/tekst` | Hele teksten når jobben er ferdig |
| `POST /jobb/{id}/avbryt` | Stopper en kø/pågående jobb |
| `POST /spor` med `jobb_id` | Spør mot den ferdige jobben — uten å sende fila på nytt |

Bruk dette når dokumentet er for stort til å vente på i ett kall.
Ellers er `/dokument` enklere.

---

## POST /innsyn — direktevisning

Starter en inspeksjonsøkt: dokumentet behandles i en bakgrunnstråd som
strømmer hendelser (side rendret, forbehandlet, hver region lest,
andrepasset …).

`POST /innsyn` → `{ok, innsyn_id}`, deretter poll
`GET /innsyn/{id}?fra=N` → `{ok, status, hendelser, neste, resultat,
feil}`. `neste` er indeksen du sender som `fra` neste gang, så du bare
får det som er nytt.

Beregnet på GUI-et, som tegner lesingen LIVE. Sender **aldri** til Label
Studio — ren inspeksjon. Gir ingen felter eller dokumentdato.

---

## POST /forhandssjekk — kvalitetsdom FØR prosessering

Avviser dårlige skann på ~sekundet i stedet for å bruke 30 s GPU på
søppel. Rendrer sidene ved samme oppløsning som OCR ville brukt og måler
skarphet, lys, piksler og tomme sider — men kjører **aldri** OCR og
rører aldri modellen.

| Felt inn | Betyr |
|---|---|
| `fil` | dokumentet (påkrevd) |
| `maks_sider` | hvor mange sider som vurderes (tak 10) |

Svar: `dom` (`god`/`tvilsom`/`avvis`), `tekstlag`, `trenger_ocr`,
`sider[]` (dpi, piksler, skarphet, lys, blekk_andel, tom, uleselig,
advarsler per side), `anbefaling` på norsk.

Bruk `dom` som port i roboten:

```
god     → POST /dokument
tvilsom → prosesser, men flagg for menneskelig kontroll
avvis   → be om nytt skann — ikke bruk GPU-en
```

Merk:

- Dokumenter **med tekstlag** får alltid `god` uten sidevurderinger —
  OCR kjøres aldri på dem, så skannkvalitet er irrelevant.
- Dømmingen skjer på **rendrede piksler**, ikke nominell dpi: for et
  opplastet bilde er dpi-en formatets antakelse (PNG=96), ikke en
  egenskap ved bildet. `dpi` rapporteres som informasjon.
- Én tom side blant innholdssider gir `tvilsom`, ikke `avvis` — tosidig
  skanning legger rutinemessig inn blanke baksider.

---

## POST /sladd — sladd beviste identifikatorer

Sladder **kun det som kan bevises**: fødselsnummer, kontonummer og
organisasjonsnummer (mod11), KID (sjekksum + etikettkrav), telefon og
epost (format). Matematikk, aldri modell. Hvert funn erstattes synlig
med `[SLADDET type]`.

| Felt inn | Betyr |
|---|---|
| `fil` | dokumentet (påkrevd) |
| `typer` | kommaseparert utvalg, f.eks. `fodselsnummer,telefon`. Standard: alle |
| `maks_sider` | OCR-sidegrense for skannede dokumenter |

Svar: `sladdet_tekst`, `funn` (type + antall), `antall_sladdet`,
`typer_valgt`, `ikke_dekket`, `advarsel`, `advarsler`, `kilde`.

**Grensene deklareres i hvert svar, ikke bare her:**

- `ikke_dekket: ["navn", "adresser"]` — de kan ikke bevises
  deterministisk (NER er fjernet med vilje), og en gjettet sladding som
  ser fullført ut er farligere enn ingen. Sladdingen er derfor **ikke
  alene tilstrekkelig for offentliggjøring** (offentleglova).
- OCR-forbeholdet: på skannede dokumenter kan et feillest siffer gjøre
  at sjekksummen ikke slår til — nummeret blir da stående **usladdet**.
  Meldes i `advarsler` når OCR ble brukt.

Dato-/beløpsvakten fra feltuttrekket gjelder også her: «01.01.2024 114
kroner» kan aldri limes sammen til et «fødselsnummer» og sladdes — en
falsk positiv i sladding fjerner lovlig saksinnhold.

---

## POST /ekko — diagnose

Svarer med **NØYAKTIG hva serveren mottok fra deg**. Behandler ikke
dokumentet.

```json
{"content_type": "…", "antall_deler": 2,
 "parser_ser": {"fil": "Taxi fra.pdf", "fil_bytes": 51234,
                "tekstfelt_navn": ["sporsmal"],
                "tekstfelter": {"sporsmal": "…"}},
 "raa_deler": [{"content_disposition": "…", "innhold_lengde": 51234}]}
```

**Bruk denne FØR du gjetter på klientoppsettet.** Kommer et felt ikke
fram, viser `raa_deler` den rå `Content-Disposition` slik den faktisk
kom, og `parser_ser` hva parseren fikk ut. Det er forskjellen mellom å
se problemet og å gjette på det.

---

## Metadata

| Kall | Gir |
|---|---|
| `GET /hjelp` | Oversikt over endepunktene + status. Krever ikke API-nøkkel. |
| `GET /dokumentasjon` | Swagger UI |
| `GET /openapi.json` | OpenAPI 3-spesifikasjon |

---

## Samme faktum, ulike stier

Endepunktene deler **bare** `ok`, `tekst` og `strekkoder` på toppnivå.
Bytter du endepunkt, brekker klientens JSON-stier.

**Dokumentdato** — fire kilder, samme underliggende logikk
(`finn_dokumentdato`), fire stier:

| Endepunkt | Sti |
|---|---|
| `/dokument` | `felter.dokumentdato.dato` |
| `/uttrekk` | `dokument.dokumentdato.dato` |
| `/analyser` | `dokumentdato.dato` |
| `GET /jobb/{id}` | `dokumentdato.dato` |

Ikke i `/spor`, `/fyll_skjema` (men `{dokumentdato}` virker i malen),
`/innsyn`, `/ekko`.

**Beløp** — ulik form OG type:

| Endepunkt | Form |
|---|---|
| `/dokument`, `/analyser` | `felter.belop` = `463.0` (tall) |
| `/uttrekk` | `belop` = liste av `{verdi, raatekst, kontekst}` |

Derfor: **velg ett endepunkt og bli der.** `/dokument` med brytere
dekker det de andre gjør, med stier som ikke flytter seg.

---

## Feltnavn som skiller seg

| Betydning | `/dokument` | `/fyll_skjema` |
|---|---|---|
| JSON-malen | `skjema_mal` | **`skjema`** |
| Motoren | `skjema_motor` | `skjema_motor` |

Dette er den vanligste fella. Sender du feil navn, sier API-et fra —
enten med 400 (manglende påkrevd felt) eller med en linje i
`advarsler`/`kvalitet.advarsler`.

---

## Ærlighetsfelter

Felter som finnes for at du skal kunne stole på svaret — eller la være.

| Felt | Betyr |
|---|---|
| `kilde` | Inneholder `borealis` ⇒ modellen bidro. Ellers rent deterministisk. |
| `kilde_per_felt` | (`auto`) Hvilke felter som er BEVIST og hvilke som er gjettet |
| `modell_brukt` | (`auto`) Om modellen faktisk ble kalt |
| `tall_verifisert` | Hvert tall i svaret står ordrett i dokumentet |
| `avvik` | Hva kodevalideringen måtte gripe inn i |
| `svar_avkortet` | Svaret ble kuttet |
| `advarsler` / `kvalitet.advarsler` | Bl.a. ukjente felt som ble ignorert |
| `ocr_brukt`, `ocr_motorer` | Om og hvordan OCR kjørte |
| `fra_cache` | Teksten kom fra cache (samme fil analysert før) |
| `versjon.uttrekk_regler` | Hvilken versjon av det deterministiske regelverket som svarte |

`kilde` er det raskeste toppnivåsjekket en robot kan gjøre:

```
kilde inneholder "borealis"  →  modellen bidro, la et menneske se på det
kilde er "deterministisk"    →  regex + mod11, ingen gjetning
```

---

## Klientfeller (UiPath / .NET)

**Argumentrekkefølge — BEGGE tar verdien først, navnet sist:**

```vb
New FileFormDataPart(filsti, "fil")
New TextFormDataPart("auto", "skjema_motor")
New TextFormDataPart("{""kunde"":""{navn}""}", "skjema_mal")
```

Snur du det, kaster UiPath `The format of value '{…}' is invalid` FØR
requesten sendes — andre argument er NAVNET og må være et gyldig token.
Slipper en verdi likevel gjennom som navn, svarer API-et 400 med presis
retting.

**Usiterte feltnavn (R63):** .NET sender `name=sporsmal` uten
anførselstegn. Parseren krevde anførselstegn og droppet da ALLE
tekstfelter i stillhet — mens fila kom fram, fordi et filnavn med
mellomrom MÅ siteres. Rettet; parseren godtar nå begge former, samt bare
LF som linjeskift, `filename*=UTF-8''…` (norske filnavn med æøå) og eget
tegnsett per del.

**Tunnel-URL:** en trycloudflare-hurtigtunnel får NY tilfeldig adresse
hver gang den startes. Får klienten plutselig et svar som ikke er JSON
(«Unexpected character … 'e'» — Cloudflares `error code: 1033`), er det
som regel en utdatert URL, ikke en API-feil.

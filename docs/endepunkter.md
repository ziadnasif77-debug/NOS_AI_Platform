# Endepunktreferanse — NAV dokument-API

Komplett oversikt over HVERT endepunkt: hva det gjør, hvilke felter det
tar imot, hva det svarer med, og om modellen brukes.

Alt her er **verifisert mot en kjørende server** (2026-08-03), ikke lest
ut av koden alene. Brukerdokumentasjonen med arbeidsflyter ligger i
[api_dokumentasjon.md](api_dokumentasjon.md); regelverket R1–R107 i
[regler_lokal_api.md](regler_lokal_api.md).

> Eksempelnumrene i denne fila er alle `12345678910` — et tall som med
> vilje IKKE består mod11. Ingen ellevesifrede verdier som kan ligne et
> ekte fødselsnummer skal ligge i repoet.

Basis-URL lokalt: `http://localhost:8600`. Er serveren startet med
`API_NOKKEL` eller `API_NOKLER`, kreves headeren `X-API-Key` på alle kall
unntatt `/hjelp` — se [Klientidentitet](#klientidentitet--navngitte-api-nøkler-r91).

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
| Ha et RYDDET svar uten utgåtte navn | `POST /api/v2/dokument` |
| Kjøre en operasjonsliste som egen ressurs | `POST /dokument/operasjoner` |

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
| `koordinater` | ja/nei | nei | nei |
| `maks_sider` | tall | — | nei |
| `strekkoder` | ja/nei | ja | nei |
| `datoer_detaljert` | ja/nei | ja | nei |
| `profil` | `full` / `sammendrag` | `full` | nei |
| `opphav` | `ingen` / `viktige` / `alle` | `viktige` | nei |
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
ok, status, filnavn, valg, dokumentprofil, opphav, tekst, antall_tegn,
antall_sider, felter, struktur, svar, skjema, korriger, korrigert_tekst,
strekkoder, handskrift, kvalitet, varsler, fra_cache, tid_sekunder,
kilde, versjon
```

Deler du ikke ba om er `null`. `kilde` sier om modellen faktisk kjørte
(se [Ærlighetsfelter](#ærlighetsfelter)).

**`status` — ett ord for hele svaret.** `ok` er ikke nok: den er `true`
også når OCR-en ga opp på tre sider, fordi forespørselen som sådan gikk
igjennom. `status` skiller de tilfellene:

| `status` | Betydning |
|---|---|
| `ok` | Alt du ba om ble levert uten varsler |
| `delvis` | Levert, men noe manglet eller ble hoppet over — les `varsler` |
| `feil` | En del du ba om kunne ikke leveres |

**`varsler[]` — advarsler du kan programmere mot.** De samme
advarslene lå før bare som fri tekst i `kvalitet.advarsler`, hvor en
klient måtte lete etter delstrenger for å reagere. Nå følger de også
med som objekter — `{type, kode, alvor, detalj}` — der `kode` er stabil
og `detalj` er den opprinnelige teksten. Fritekstlista blir stående;
den er ikke fjernet.

| `alvor` | Handling |
|---|---|
| `info` | Til opplysning; svaret er fullstendig |
| `advarsel` | Svaret er brukbart, men noe manglet |
| `feil` | En etterspurt del mangler |

**`profil=sammendrag` — når du ikke trenger persondata.** Spør du bare
om en dato, er det ingen grunn til at svaret skal inneholde
fødselsnummer, adresse og kontonummer. `profil=sammendrag` kutter
person- og kontaktseksjonene, og `dokumentprofil.utelatt[]` navngir
hva som ble tatt bort — ingenting forsvinner i stillhet.

**`datoer_detaljert=nei`** dropper `datoer`-lista fra svaret (den
utgjør typisk ~40 % av responsen på et flersidig dokument).
`dokumentprofil` beholder alle daterte felter uansett.

**`opphav` — ett oppslag for «hvor kom dette fra?» (R88).** API-et
forklarte proveniens på fem uavhengige måter — `dato_kilde`,
`dato_sikkerhet`, `part.sikkerhet`, `kilde_per_felt` og `kilde` — med
hvert sitt ordforråd, og to av dem brukte samme ord om ulike ting. En
klient som ville vite «hvor sikkert er dette, og hvorfor?» måtte lære
alle fem.

`opphav` er ett kart: JSON Pointer (RFC 6901) inn, opphavet ut. Samme
pekersyntaks som `problem.errors[].pointer` allerede bruker.

```json
"opphav": {
  "/dokumentprofil/part/fnr": {
    "metode": "etikett", "konfidens": "hoy",
    "begrunnelse": "Fødselsnummeret står under «Dokumentet gjelder» …",
    "side": null},
  "/dokumentprofil/part/fodselsdato": {
    "metode": "avledet", "konfidens": "hoy",
    "begrunnelse": "Regnet ut av fødselsnummerets seks første siffer …",
    "side": null}
}
```

To LUKKEDE ordforråd, aldri gjenbrukt til noe annet:

| `metode` | Betyr |
|---|---|
| `sjekksum` | Matematisk bevist (mod11/mod10) — ikke et mønstertreff |
| `etikett` | Ordet står i dokumentet, rett ved verdien |
| `posisjon` | Utledet av plasseringen (brevhode, signaturblokk) |
| `metadata` | Fra filens metadata, ikke fra teksten |
| `strekkode` | Dekodet av strekkodeleseren |
| `regel` | Deterministisk mønsterregel |
| `modell` | Gjettet av språkmodellen — ikke bevist |
| `avledet` | FØLGER av en annen verdi; står ikke nødvendigvis i dokumentet |
| `ingen` | Fant ingenting — `begrunnelse` sier hvorfor |

`konfidens` er den samme skalaen som overalt ellers: `hoy`, `middels`,
`lav`, `ingen`.

**Kartet erstatter ingenting.** `dato_kilde`, `dato_sikkerhet`,
`part.sikkerhet` og `kilde_per_felt` står urørt ved siden av — `opphav`
er en PROJEKSJON av dem, ikke en sjette uavhengig mening. Kombinerer du
med `profil=sammendrag`, faller pekerne til de utelatte seksjonene bort:
en peker til et fjernet felt ville lekket nettopp det bryteren skjuler.

### dokumentprofil — følger ALLTID med (R79)

Et dokument har egenskaper som gjelder uansett hva du spurte om: hvor
mange sider det har, når det er datert, hvem det gjelder. De kommer
derfor i hvert svar, i BEGGE kontraktene (brytere og `operasjoner`),
uten at du ber om dem. Alt er deterministisk — ingen modell er
involvert, og et felt som ikke kan fastslås er `null` med en
begrunnelse ved siden av.

Formen er SEKSJONERT og fast: hver seksjon og hvert felt er alltid til
stede. Tomt er `null` eller `[]` — aldri en manglende nøkkel. Endres
formen senere, går `skjemaversjon` opp, så du ser det på tallet i
stedet for når noe brekker. Se
[dokumentprofil_skjema.md](dokumentprofil_skjema.md) for begrunnelsen.

```json
{
  "skjemaversjon": "1.4",

  "sammendrag": {"navn": "Ola Nordmann", "fnr": "12345678910",
                 "dokumentdato": "2026-05-12", "dokumenttype": "vedtak",
                 "ytelse": "dagpenger", "saksnummer": "4417820",
                 "antall_sider": 10, "antall_dokumenter": 5,
                 "konfidens": "middels", "sikkerhet": "middels"},

  "dokumenter": [
    {"sider": [1,2], "dato": "2026-05-12", "type": "vedtak",
     "tittel": "Vedtak om dagpenger", "eier_navn": "Ola Nordmann",
     "eier_fnr": "12345678910", "eier_sikkerhet": "merket"},
    {"sider": [3], "dato": "2026-06-08", "type": "klage",
     "tittel": "Klage på vedtak", "eier_navn": null, "eier_fnr": null,
     "eier_sikkerhet": "umerket"}
  ],

  "fil":   {"filnavn": "vedtak.pdf", "antall_sider": 12,
            "blanke_sider": [7], "uleselige_sider": null},

  "part":  {"navn": "Ola Nordmann", "fnr": "12345678910",
            "fodselsdato": "1990-01-01", "fastslatt": true,
            "grunnlag": "etikett", "sikkerhet": "merket",
            "begrunnelse": "Fødselsnummeret står under «Dokumentet gjelder» …"},
  "eier": { /* samme objekt som "part" — se aliasene under */ },

  "andre_fodselsnummer": [
    {"fnr": "<saksbehandlerens nr>", "rolle": "annen",
     "etikett": "Saksbehandler", "navn": "Kari Hansen"}
  ],
  "andre_personer": [ /* samme liste som "andre_fodselsnummer" */ ],

  "dokument": {
    "type": "vedtak", "tittel": "Vedtak om dagpenger", "sprak": "norsk",
    "kontornavn": "NAV Arbeid", "fylke": "Oslo",
    "dato": "2026-05-08", "dato_norsk": "08.05.2026", "ar": 2026,
    "alder": {"dager": 89, "tekst": "2 måneder gammelt", "fremtidig": false},
    "dato_kilde": "etikett", "dato_sikkerhet": "hoy",
    "dato_begrunnelse": "etiketten «Vedtaksdato» står rett før datoen",
    "dato_side": 1,
    "periode_start": "2025-01-01", "periode_slutt": "2025-12-31",
    "spenn_fra": null, "spenn_til": null, "flere_dokumenter": false
  },

  "sak":   {"saksnummer": "4417820", "journalnummer": "2026001234",
            "vedtaksnummer": "55/9911", "dokumentnummer": null,
            "referanse": null, "sakstype": null},

  "ytelse": {"navn": "dagpenger", "type": null, "utfall": null,
             "gyldig_fra": null, "gyldig_til": null, "status": null,
             "implementasjon": "delvis"},

  "dekning": {"ytelse": "delvis", "sakstype": "ingen",
              "signatur_sider": "ingen", "uleselige_sider": "ingen",
              "forklaring": "«ingen» betyr at systemet ikke leter etter feltet ennå …"},

  "okonomi": {"dagsats": 1234.00, "manedsbelop": 24680.00,
              "utbetalt_belop": null, "tilbakebetalingsbelop": null,
              "utbetalingsdato": null, "valuta": "NOK",
              "kontonummer": [], "kid": []},

  "arbeid": {"arbeidsgiver": "Rema 1000 AS", "stilling": "Butikkmedarbeider",
             "stillingsprosent": 80, "startdato": null, "sluttdato": null,
             "arsinntekt": null, "manedslonn": null,
             "organisasjonsnummer": ["923609016"]},

  "kontakt": {"telefoner": ["22222222"], "eposter": ["ola@example.no"],
              "adresser": [{"gate": "Storgata 12", "postnummer": "0181",
                            "poststed": "OSLO"}]},

  "koder": {"lest": true,
            "qr": [{"side": 1, "verdi": "https://…", "type": "QRCODE"}],
            "strekkode": [{"side": 3, "verdi": "9912345", "type": "CODE128"}],
            "qr_kode_side": 1, "strekkode_side": 3},

  "visuelt": {"stempel_datoer": [{"dato": "2026-05-20", "side": 2,
                                  "type": "mottatt", "rolle": "behandling"}],
              "stempel_sider": [2], "signatur_sider": null,
              "handskrift_funnet": false}
}
```

**`sammendrag` — start her (R74).** De få feltene de fleste er ute
etter. `sikkerhet` er det SVAKESTE leddet, ikke et gjennomsnitt: er
eieren usikker, hjelper det ikke at datoen er sikker, og en fil med
flere dokumenter er aldri `hoy`.

**`dokumenter[]` — en fil er ikke nødvendigvis ett dokument (R74).** En
skannet saksmappe inneholder gjerne vedtak, inntektsmelding,
legeerklæring og klage — hver med sin dato, sin type og noen ganger sin
person. Da er ett `eier`-felt og én `dokument.dato` for hele filen
misvisende, uansett hvor riktig hver enkelt verdi er isolert sett.
Delingen følger dokumentDATOENE: en side med en ny dato med rolle
«dokument» starter et nytt dokument. Lista har alltid minst én
oppføring. **Er `sammendrag.antall_dokumenter` større enn 1, les
`dokumenter[]` — ikke toppnivåfeltene.**

**Tre datofelter som ikke er det samme (R80):**

| Felt | Betydning |
|------|-----------|
| `dokument.dato` | Da dokumentet ble skrevet, fattet, signert, utstedt |
| `dokument.periode_start`/`_slutt` | Perioden dokumentet GJELDER FOR («dagpenger for perioden …») |
| `dokument.spenn_fra`/`_til` | Datospennet når filen er en BUNKE av flere daterte dokumenter |

**Saks-, økonomi- og arbeidsfelter krever en etikett (R71).** De hentes
bare når ordet står i dokumentet — et tall uten etikett blir aldri et
vedtaksnummer, og et beløp uten etikett blir aldri en dagsats.
Etiketten må stå hel (`stilling` treffer ikke inne i
`Stillingsprosent`), men bøyning godtas (`Dagsatsen er kr 1 234`), og
æøå leses som `å`/`aa`/`a`.

**Felter merket `null` som ikke betyr «ingenting»:**
`fil.uleselige_sider` og `visuelt.signatur_sider` er `null` fordi de
krever analyse vi ikke har bygget ennå — ikke fordi dokumentet mangler
dem. `dekning` sier hvilke det gjelder, så du slipper å lære lista
utenat. `fil.blanke_sider` er `null` når teksten ikke har sidemarkører,
og en liste når den har.

En dato som bare NEVNES i teksten — en frist, en fødselsdato — blir
aldri dokumentdato. Finnes ingen dato som kan knyttes til dokumentet
selv, er `dokumentdato` `null` og `dokumentdato_begrunnelse` sier
hvorfor. Stempeldatoer («Mottatt NAV 20.05.2024») ligger i
`stempel_datoer` og blir aldri dokumentdato (R68).

**Navn som finnes i to utgaver.** Tre felter har fått et nytt navn ved
siden av det gamle. Begge peker på NØYAKTIG samme verdi, en test vokter
at de ikke gliser fra hverandre, og ingen av de gamle navnene fjernes i
denne versjonen:

| Nytt navn | Gammelt navn | Hvorfor det nye |
|---|---|---|
| `part` | `eier` | «Part» er forvaltningslovens ord (§ 2 e). I dokumenthåndtering betyr «dokumenteier» arkivets eier eller saksbehandleren — altså akkurat den personen R69 skal holde UTENFOR feltet. |
| `andre_fodselsnummer` | `andre_personer` | Lista inneholder fødselsnummer, ikke personer. En klient som leste navnet bokstavelig ventet seg personposter. |
| `sammendrag.konfidens` | `sammendrag.sikkerhet` | `sikkerhet` leses like gjerne som *security* som *confidence*. |

Konfidensskalaen har nå ÉN verdimengde overalt: `hoy`, `middels`,
`lav`, `ingen`. Ordet `usikker` var et fjerde navn på det `lav` allerede
het, så en klient som filtrerte på `lav` aldri traff sammendraget.

**`part` / `eier` — personen dokumentet gjelder (R69):**

Et NAV-dokument nevner ofte flere personer med fødselsnummer: den saken
gjelder, saksbehandleren, legen, arbeidsgiverens kontakt. Nummeret
kobles derfor til etiketten nærmest foran seg, og bare et POSITIVT
eiersignal kvalifiserer. `sikkerhet` sier hva vi bygger på:

`fastslatt` er svaret på det de fleste faktisk lurer på — «har vi en
part eller ikke?» — som én boolsk verdi, i stedet for at hver klient må
kjenne igjen hvilke av fem `sikkerhet`-ord som betyr ja. `grunnlag`
sier hva funnet BYGGER PÅ (`etikett`, `eneste_nummer`, `ingen`); det er
en kategori, ikke et trinn på konfidensskalaen, og skal ikke
sammenlignes med `>`/`<`.

| `sikkerhet` | Betydning | `fnr` |
|-------------|-----------|-------|
| `merket` | Nummeret står under en eier-etikett | fylt |
| `flertydig` | Flere ULIKE numre under eier-etiketter | `null` |
| `bare_andre_roller` | Alle numre hører til saksbehandler/lege/arbeidsgiver o.l. | `null` |
| `umerket` | Numre finnes, men ingen etikett viser hvem dokumentet gjelder | `null` |
| `ingen` | Ingen fødselsnummer består mod11 | `null` |

Et nummer hentes **ikke** bare fordi det står i teksten.

De ØVRIGE fødselsnumrene kastes ikke — de er ekte opplysninger, og en
klient kan trenge dem. Men de ligger i `andre_personer`, med rolle
og etikett, **aldri sammen med eierens**. Eierens nummer gjentas aldri
der. Kan eieren ikke fastslås, er `fnr` null og ALLE numrene ligger i
`andre_personer` — ingenting forsvinner, men ingenting utgir seg
for å være dokumentets heller.

**`koder`:** `lest: false` betyr at skanningen var slått av — da sier
`qr_kode_side: null` ikke at koden mangler, bare at det ikke ble sett
etter den. `qr_kode_side`/`strekkode_side` er FØRSTE side med en kode;
alle forekomstene ligger i `qr`- og `strekkode`-listene.

**Kategoriverdier kommer også som `{kode, term}` (R94).**
`dokument.type_kodet`, `ytelse.navn_kodet` og `sak.sakstype_kodet` står
ved siden av den rå verdien. Koden er stabil — forgren på den — og
termen er for et menneske. Kodene er skrevet uten æøå fordi de matches
mot OCR-tekst; termen har dem:

```json
"type": "legeerklaring",
"type_kodet": {"kode": "legeerklaring", "term": "Legeerklæring"}
```

Uten verdi er hele paret `null`. `{"kode": null, "term": null}` ville
sagt at det finnes en type som bare mangler navn.

**`ytelser[]` — et dokument kan gjelde flere (R95).** Et AAP-vedtak
viser nesten alltid til sykepengeperioden som tok slutt. Med ett felt
forsvant den. Lista har alle, i den rekkefølgen de står i teksten.

`ytelse.navn` er den mest SPESIFIKKE (lengste treff) og ligger alltid i
lista — men er ikke nødvendigvis `ytelser[0]`. Sammenfaller de ikke, er
begge riktige; de svarer på ulike spørsmål.

**`hjemler[]` — hva dokumentet VISER TIL (R96).** Ikke det samme som
`hjemmel`, som sier hvilken lov som GJALDT da dokumentet ble skrevet:

| Felt | Spørsmål |
|---|---|
| `hjemmel` | Hvilken lov gjaldt da dokumentet ble skrevet? (av datoen alene) |
| `hjemler[]` | Hvilke bestemmelser siterer dokumentet? |

Oppslaget går mot loven som gjaldt, så «kapittel 8» blir sykepenger i et
2024-vedtak og uførepensjon i et 1994-vedtak. Uten dokumentdato er
henvisningen `flertydig: true` med `lov: null` — å velge én av to lover
uten grunnlag ville gitt et svar som ser riktig ut.

Et UDELT paragrafnummer (`§ 29`) hører til en annen lov enn
folketrygdloven, som nummererer kapittel-ledd (`§ 8-2`). Den tas med med
`lov: null` og en `merknad` (R97) — å tilskrive den folketrygdloven ville
vært en påstand vi vet er feil, og å droppe den ville skjult noe som
faktisk står i dokumentet.

**`ytelse`** er en plassholder. Reglene kommer senere; feltet er med fra
første dag så kontrakten ikke må endres når de gjør det. `ytelse.status`
er reservert for ytelsens EGEN status (`innvilget`, `lopende`,
`opphort`) og står `null` inntil den leses. Hvor langt systemet er
kommet, sto tidligere i det samme feltet — to helt ulike opplysninger
under ett navn — og ligger nå i `dekning`.

**`dekning` — hva systemet leter etter ennå.** Et `null`-felt kan bety
to ting: dokumentet har ikke opplysningen, eller vi har ikke bygget
lesingen. Forskjellen avgjør om en klient skal melde avvik eller vente.

| Verdi | Betydning |
|---|---|
| `full` | Feltet leses, og `null` betyr at dokumentet mangler det |
| `delvis` | Noe fastslås, ikke alt |
| `ingen` | Systemet leter ikke etter feltet ennå — `null` sier ingenting om dokumentet |

### Sidespørsmål besvares av KODEN

Peker spørsmålet på en side («les side 10», «sida 3», «s. 2»), ruter
koden det deterministisk — sidemarkørene `[Side i av n]` er
kodegenererte og dermed pålitelige:

| Spørsmål | Hva skjer | Modell? |
|---|---|---|
| `les side 10` | Siden gjengis **ordrett** | **nei** |
| `les side 99` (finnes ikke) | «Dokumentet har 10 sider — side 99 finnes ikke.» | **nei** |
| `hva er beløpet på side 3?` | Modellen får **kun side 3** | ja |

De to første virker **selv når Borealis er nede** — de går forbi
503-porten. `svar.modell_brukt` og `kilde` sier hvilken vei som ble tatt.

Bakgrunn: en liten modell som får hele bunken roter bort
sideindekseringen (målt: svarte «Side 10 finnes ikke» på et 10-siders
dokument der `[Side 10 av 10]` sto i klartekst). Sidetelling er
matematikk, ikke språkforståelse.

### Strekkode-/QR-spørsmål besvares også av koden

| Spørsmål | Svar | Modell? |
|---|---|---|
| `hva er strekkoden?` | `CODE128 (side 3): 1002345678911` | **nei** |
| `hent strekkoden fra side 1` | «Ingen strekkode på side 1. Dokumentet har strekkode på side 3.» | **nei** |

Verdien er **dekodet** av en strekkodeleser — symbologien har egen
sjekksum. Samme grunn som over: målt ga «hva er strekkoden?» svaret
«Finnes ikke i dokumentet» mens den dekodede verdien lå i `strekkoder`
i *samme* svar.

Sendte du `strekkoder=nei`, går spørsmålet til modellen i stedet: en tom
liste betyr da at vi ikke *så etter*, og «ingen funnet» ville vært en
løgn.

### Identifikatorspørsmål besvares av uttrekket

Spør du etter en **sjekksumvalidert** identifikator, svarer koden fra
uttrekket — samme finnere som `/sladd` og `koordinater=ja`:

| Spørsmål | Svar |
|---|---|
| `hva er KID?` | `1002345678911` |
| `hva er kontonummeret?` | `2 kontonummer: 12345678910, 12345678910` |
| `hva er fødselsnummeret?` | `2 fødselsnummer: 12345678910, 12345678910` |
| `hva er kontonummeret på side 2?` | bare side 2 sitt |

Dekker `fødselsnummer`, `kontonummer`, `organisasjonsnummer`, `KID`
(mod11/Luhn) og `telefon`/`epost` (format).

To grunner til at dette er bedre enn modellen:

1. **Alle treff, ikke ett.** En bunke kan gjelde flere personer — den
   over har to av hver. Modellen velger én; koden svarer med begge og
   sier hvor mange.
2. **Ingen gjetning ved feil.** Består ikke kontrollsifferet, finnes
   ikke nummeret — og svaret sier hvorfor, i stedet for å levere et tall
   som *ser* riktig ut.

### koordinater=ja — bokser per bevist funn

Samme finnere som `/sladd` (mod11/sjekksum/format, aldri modell), med
posisjon på siden:

```json
"koordinater": {
  "koordinatrom": "pdf_punkter",
  "sider": [{"side": 1, "bredde": 595.3, "hoyde": 841.9,
             "funn": [{"type": "organisasjonsnummer",
                       "tekst": "889 000 007",
                       "bokser": [[331.7, 726.0, 408.9, 736.6]]}]}],
  "antall_funn": 1
}
```

- **`koordinatrom` må leses:** OCR-dokumenter gir bokser i
  `forbehandlet_bilde_piksler` (perspektiv-/skjevhetsrettet bilde);
  tekstlags-PDF-er gir `pdf_punkter` (72 per tomme). Sidedimensjonene
  følger med i samme rom, så en utheving kan skaleres riktig.
- `bokser` er en liste: OCR kan dele et gruppert nummer over flere
  bokser.
- Ren tekstopplasting har ingen sider — da er `koordinater` `null` og
  grunnen står i `kvalitet.advarsler`.
- Et funn som ikke består kontrollen finnes ikke — heller ikke her.
  (OCR som leser orgnr-et feil ⇒ ingen boks, ikke en gal boks.)

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

## v2 — samme innhold, ryddet form

`POST /api/v2/dokument` tar **nøyaktig samme felter** som `/dokument` og
gjør nøyaktig samme arbeid. Bare svarformen er en annen. Det er ingen
egen kodevei — to veier ville drevet fra hverandre, slik de to
`/dokument`-kontraktene en gang gjorde.

v1 har 21 toppnøkler uten ordning: fakta om dokumentet, opplysninger om
forespørselen og diagnostikk ligger om hverandre. v2 deler dem i tre
(R103):

```json
{
  "ok": true,
  "status": "ok",
  "data":        { "part": …, "dokument": …, "sak": …, "ytelser": [ … ],
                   "hjemler": [ … ], "tekst": …, "felter": … },
  "metadata":    { "filnavn": …, "antall_sider": 2, "fil": { … },
                   "skjemaversjon": "1.4", "versjon": { … } },
  "diagnostikk": { "status": "ok", "varsler": [], "kvalitet": { … },
                   "opphav": { … }, "dekning": { … },
                   "modell_brukt": false, "tid_sekunder": 0.6 }
}
```

| Gruppe | Svarer på |
|---|---|
| `data` | Hva står i DOKUMENTET |
| `metadata` | Hva ble sendt inn, og hva svarte |
| `diagnostikk` | Hvordan gikk det |

`fil` er metadata — den handler om filen vi fikk, ikke om innholdet.
`dekning` er diagnostikk — den sier hva SYSTEMET kan ennå. `ok` og
`status` blir liggende på rot: de svarer på ulike spørsmål (R83), og
begge skal kunne leses uten å gå ned et nivå.

**Utgåtte navn finnes ikke i v2 (R104):**

| Borte i v2 | Bruk |
|---|---|
| `eier` | `part` |
| `andre_personer` | `andre_fodselsnummer` |
| `sammendrag.sikkerhet` | `sammendrag.konfidens` |
| `part.sikkerhet` | `part.grunnlag` |
| `ytelse.implementasjon` | `dekning.ytelse` |
| `dokument.ar` | `dokument.aarstall` |

Den siste er en omdøping, ikke en fjerning: `ar` sto rett ved siden av
`alder.aar` — to skrivemåter av samme bokstav, to betydninger.

**v1 er UENDRET og fjernes ikke.** v2 er en projeksjon av det v1 alt
bygger (R102), ikke omvendt: v1 er i drift hos skjøre klienter og gjerdet
inn av over 800 tester, og å legge om produksjonsveien dit ville vært
risiko uten gevinst utenfra.

Feilsvar har samme form i begge versjoner — RFC 9457 er allerede en
standard, og to feilformer ville tvunget klienten til å håndtere begge.

### POST /dokument/operasjoner

Samme motor som feltet `operasjoner` på `/dokument`, men som egen
ressurs. Grunnen (R105): på `/dokument` overstyrer feltet bryterne i
**stillhet** — sender du `felter=ja` sammen med `operasjoner`, skjer det
ingenting med bryteren, og svaret ser ut som om begge deler ble utført.
En egen URL gjør valget synlig.

Her er `operasjoner` **påkrevd**: uten feltet får du 400 i stedet for et
svar som stilltiende ble noe annet. Feltveien på `/dokument` beholdes
uendret. v2-formen ligger på `/api/v2/dokument/operasjoner`.

---

## Klientidentitet — navngitte API-nøkler (R91)

Med ÉN delt nøkkel er hver forespørsel anonym. Da har spørsmålet «bruker
noen fortsatt dette?» ikke noe svar, og et utgått felt må stå for alltid
— for sikkerhets skyld. Revisjonen kalte dette forutsetningen for å
kunne fjerne noe som helst.

```
API_NOKKEL=<den gamle, delte>              ← virker uendret
API_NOKLER=uipath-fakturamottak:<nøkkel>,arkiv-batch:<nøkkel>
```

Begge gjelder samtidig. En klient som ennå ikke har byttet, slipper inn
med den gamle nøkkelen og får `klient_id: "eldre-nokkel"` i loggen — så
man ser hvem som gjenstår, uten at noe brekker.

Navnet er klientens ID i tilgangsloggen, så det bør si hvem det er:
`uipath-fakturamottak`, ikke `nokkel1`. **Nøkkelen logges aldri** — et
navn i en logg er nyttig, en nøkkel i en logg er en lekkasje som
overlever i sikkerhetskopier. Oppstarten sier fra om nøkler under 24
tegn, og om to navn som deler nøkkelverdi (da er `klient_id` vilkårlig,
og hele ordningen hviler på det feltet).

### Hvem bruker hva

```bash
python skript/klientrapport.py --dager 30
```

```bash
python skript/klientrapport.py --sti /analyser --dager 365
```

**Utgåtte felter er merket i spesifikasjonen (R99).** Fem felter har
`deprecated: true` i `/openapi.json` — `eier`, `andre_personer`,
`sammendrag.sikkerhet`, `part.sikkerhet` og `ytelse.implementasjon` —
hver med det nye navnet i beskrivelsen. Ingen av dem fjernes før v2.

`Sunset`-headeren (RFC 8594) sendes IKKE, fordi v2 ikke har noen
besluttet dato. Et vilkårlig tidspunkt ville vært et løfte ingen har
tatt (R100).

**Loggen roterer (R101).** `TILGANGSLOGG_MAKS_MB` (standard 10) og
`TILGANGSLOGG_ARKIV` (standard 12) — omtrent et halvt år ved normal
last. Rapporten leser arkivfilene i tillegg til den aktive, ellers ville
en spørring over 365 dager sett noen få dager og meldt «ingen bruker
dette».

**Hva rapporten kan og ikke kan svare på (R92).** Loggen ser
FORESPØRSELEN. Den svarer sikkert på om noen fortsatt kaller
`/analyser`, eller sender en utgått bryter. Den kan **ikke** si om noen
leser `eier` i stedet for `part` — begge står i samme svar, og serveren
ser ikke hva klienten plukker ut. Utgåtte SVARfelter må derfor varsles i
`varsler[]` og fjernes etter et annonsert løp, aldri fordi rapporten
«viser» at de er ubrukte.

En sti rapporten ikke kjenner gir **feil**, ikke et tomt svar (R93) —
ellers ville en skrivefeil sett ut som grønt lys for å pensjonere et
endepunkt.

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

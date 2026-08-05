# API- og skjemarevisjon — august 2026

Åtte uavhengige revisjoner av `/dokument`-API-et, kjørt parallelt med hvert
sitt mandat, deretter kryssgjennomgått. Alt her er **verifisert mot koden
eller målt**; anslag er merket **[anslag]**.

**Status: FORSLAG. Ingen kode er endret.** Implementering venter på
godkjenning.

| Revisjon | Mandat |
|---|---|
| 1 | API-kontrakt: endepunkter, statuskoder, kontraktsflate |
| 2 | Skjema og datalinje: hvor beregnes samme faktum to ganger |
| 3 | Responsutforming: fire alternativer, dupliseringsdom per felt |
| 4 | Semantikk og feltnavn |
| 5 | Rørgate: dobbeltarbeid fra opplasting til svar |
| 6 | Ytelse og skalerbarhet (målt) |
| 7 | Personvern og sikkerhet |
| 8 | API-et som produkt: kontraktsgrenser, versjonering |

---

## 1. Sammendrag

**Premisset i bestillingen holder ikke helt.** Responsen er ikke stor på
grunn av duplisering. Målt på et ekte standardsvar (10-siders bunke,
ingen brytere satt): **33 424 byte**, hvorav

- `felter.datoer_detaljert` alene: **12 949 B (39 %)** — større enn
  selve dokumentteksten (7 836 B)
- innrykk (`indent=2`): **6 976 B (20,9 %)**
- alle duplikater til sammen: ~800 B (**2,4 %**)

**gzip alene gir −80,8 %** (33 424 → 6 422 B), uten å røre kontrakten.
Ingen komprimering finnes i kodebasen (verifisert: 0 treff på
`gzip|deflate|Content-Encoding`).

Dupliseringen er altså ikke problemet. **De reelle problemene er fem:**

**1. Ærlighetsfeltet lyver.** `kilde` er dokumentert som «det raskeste
toppnivåsjekket en robot kan gjøre» — inneholder den `borealis`, bidro
modellen. Den lyver på begge veier: på bryter-veien telles en FEILET
modelldel som «modellen kjørte» (`.get("modell_brukt")` gir `None`, og
`None is False` er falskt), og på operasjoner-veien er `kilde` hardkodet
`"motor"` uansett. En robot som ruter på dette hopper over menneskelig
kontroll i nettopp de tilfellene den ikke skal.

**2. Samme faktum beregnes av kodeveier som kan gi ULIKE svar.** Ikke
teoretisk — målt:

- `felter.fodselsnummer` rapporterer et **bankkontonummer** som
  fødselsnummer (entallsfinneren mangler etikettvakten flertallsfinneren
  har). Samme verdi går inn i skjemautfylling via `felter_flatt`.
- `periode_start` betyr «perioden dokumentet gjelder for» i profilen og
  «datospennet i bunken» i `felter_flatt` — 2026-04-02 mot 01.08.2019 i
  samme svar.
- Modellen får dokumentdatoen regnet ut med `maks=30` mens profilen
  bruker `maks=200`: målt 01.02.2020 i prompten mot 28.05.2026 i
  profilen, og prompten sier «svar med NØYAKTIG denne datoen».

**3. Én forespørsel kan legge beslag på GPU-en i minutter.**
`MAKS_OPERASJONER=20` × opptil 5 modellkall per `svar`-operasjon = **100
genereringer**, serialisert bak GPU-låsen. Målt 0,3–2,8 s per generering
→ **30–280 s** i én HTTP-forespørsel, mot en socketfrist på 120 s.

**4. Uttrekket er kvadratisk.** `_tallkandidater_med_posisjon` skanner
`opptatt`-lista lineært per kandidat; begge vokser med teksten.
Målt vekst per dobling: `finn_alle_fodselsnummer` **4,08×** (2,0× =
lineært). En 117 000-tegns bunke bruker 1,53 s ren regex-CPU bare på den
obligatoriske profilen.

**5. Fjerning av felter er umulig i dag.** Én delt `API_NOKKEL`, og
tilgangsloggen registrerer `"nokkel": bool` — ikke hvilken. Spørsmålet
«hvem leser fortsatt dette feltet?» kan ikke besvares. Enhver
deprekering er et sjansespill. **Dette er forutsetningen for hele
migreringsplanen, ikke et sidepoeng.**

---

## 2. Kryssgjennomgang

### 2.1 Funn flere revisjoner fant uavhengig av hverandre

Disse er de sikreste, fordi de ble nådd via ulike innfallsvinkler.

| Funn | Revisjoner | Vekt |
|---|---|---|
| `kilde` lyver (to ulike feilmoduser) | 1, 3, 8 | **3** |
| De to `/dokument`-kontraktene har divergert | 1, 3, 8 | **3** |
| Datoformat er inkonsekvent inne i profilen | 2, 3, 4 | **3** |
| `analyser_bytes`-resultater kastes og regnes på nytt | 2, 5, 6 | **3** |
| Dokumentasjonen beskriver felter som ikke finnes | 1, 3, 4, 8 | **4** |
| `sikkerhet` betyr flere uforenlige ting | 4, 8 | 2 |
| Strekkodeskanning er standard på og dominerer kaldt kall | 5, 6 | 2 |
| Modellkall-eksplosjon på operasjoner-veien | 5, 6 | 2 |
| R79/R80 finnes to ganger i regelverket (verifisert: 77 ID-er, 2 dubletter) | 1, 8 | 2 |

### 2.2 Motsigelser — og hvordan de er avgjort

**M1 — Er responsen for stor?**
Revisjon 3 målte 11 800 tegn og konkluderte «13 % å hente, ikke verdt
det». Revisjon 6 målte 33 424 B og fant 39 % i ett felt.
**Ikke en motsigelse:** revisjon 3 målte eksempelfila (`felter=false`),
revisjon 6 målte et ekte standardsvar (`felter=ja`, som er standard).
**Avgjort:** revisjon 6 sitt tall er det relevante. Men *begge* tar feil
om løsningen — svaret er verken å fjerne duplikater (2,4 %) eller å
normalisere (13 %), men **gzip (80,8 %)**, som ingen av dem foreslo som
hovedgrep fordi det ligger utenfor begges mandat. Dette er den sterkeste
grunnen til å kjøre flere revisjoner: hovedgevinsten lå i sprekken
mellom to mandater.

**M2 — Skal dokumentprofilen alltid følge med (R79)?**
Revisjon 3 og 8: ja, den er produktet. Revisjon 5 og 6: den koster 51 ms
av 64 ms ved cachetreff og har gjort `struktur=nei` virkningsløs.
Revisjon 7: klienten kan ikke velge bort persondata.
**Avgjort: profilen blir værende obligatorisk, men tre ting skilles ad
som i dag blandes.** (a) *Kostnaden* er ikke profilens skyld — mesteparten
er dobbeltberegning (§9 P1-3/P1-4) og forsvinner uten å røre kontrakten.
(b) At `struktur=nei` ikke lenger virker er en **feil**, ikke en
avveining. (c) Personvernbehovet løses med `profil=full|sammendrag`,
utløst av personvern — ikke av størrelse. Revisjon 3 utformet selv den
eneste varianten den ville forsvare, og den brukes: standard `full`,
ukjent verdi gir 400, aldri autoaktivering, og `utelatt[]` navngir hva
som mangler.

**M3 — Skal `eier` hete `part`?**
Revisjon 4: ja, `eier` er juridisk feil og feil i farlig retning —
«dokumenteier» betyr *arkiveier/saksbehandler* i dokumentforvaltning,
nøyaktig personen feltet skal utelukke. Revisjon 3: ingen brytende
endringer. Revisjon 8: brytende endringer kun i v2.
**Avgjort: revisjon 4 har rett i semantikken, revisjon 8 setter
rammen.** `part` legges til som alias nå (additivt), `eier` merkes utgått,
og fjernes først i v2 — som uansett ikke kan skje før klientidentitet
finnes (§1 punkt 5).

**M4 — Skal duplikater fjernes?**
Revisjon 3: behold alle sju, med speiltester. Revisjon 7: fjern
`sammendrag.fnr`, `sammendrag.navn`, `eier.fodselsdato`.
**Avgjort: revisjon 3 vinner på prinsippet, revisjon 7 på de konkrete
feltene — men mekanismen er skopet, ikke sletting.** `profil=sammendrag`
utelater dem for den som ikke skal ha dem. Ett unntak: `eier.fodselsdato`
fjernes uansett, fordi revisjon 4 viste at den er **systematisk gal** for
alle født etter 1999 (hardkodet `1900 + aar`). Den er ikke et duplikat —
den er feil.

**M5 — Skal svaret få `data`/`metadata`/`diagnostics`?**
Revisjon 8: ja, additivt nå, fullført i v2. Revisjon 3: svaret skal ikke
vokse.
**Avgjort: utsatt.** Revisjon 8 sin egen begrunnelse taler mot å haste:
uten klientidentitet kan de flate tvillingene aldri fjernes, så trinn 1
ville lagt til ~400 B permanent uten å kunne fullføres. Gjøres når
klientidentitet er på plass.

### 2.3 Ett falskt funn — korrigert

Revisjon 2 meldte `andre_personer[0].fnr == eier.fnr` som kontraktsbrudd.
**Det er en artefakt av revisjonsmaterialet:** jeg erstattet to ULIKE
fødselsnummer med samme plassholder da eksempelfila ble laget. Det
opprinnelige svaret har to forskjellige numre. Koden er riktig.
Tas ikke videre.

---

## 3. Dupliseringsrevisjon

Kategorier: **ekte** (samme verdi, samme kilde, ingen tilleggsverdi) ·
**bevisst** (kontraktsverdi) · **avledet** (utledet av annet felt) ·
**presentasjon** (samme verdi, annet publikum) · **diagnostikk** ·
**motstrid** (samme navn, ULIK verdi — det farlige).

| Felt | Sted 1 | Sted 2 | Sted 3 | Type | Anbefaling |
|---|---|---|---|---|---|
| `antall_sider` | rot | `profil.fil` | `profil.sammendrag` | ekte | **Behold.** Rotfeltet finnes med samme betydning i `/analyser`, `/forhandssjekk`, `/jobb` — det er stien som overlever et endepunktbytte. Legg til speiltest. |
| `filnavn` | rot | `profil.fil` | — | bevisst | **Behold.** Rotfeltet er kvittering på at multipart-delen kom fram (R63); profilens er dokumentidentitet. Samme verdi, to ærender. |
| `strekkoder` | rot | `profil.koder.strekkode` | — | bevisst | **Behold.** Rotlista er alle koder samlet; profilen deler på symbologi og legger til `lest`/`merknad`, som skiller «ingen koder» fra «vi så ikke etter». |
| `sammendrag.*` | `sammendrag` | seksjonene | — | presentasjon | **Behold hele.** 7 av 9 er kopier, men `sikkerhet` finnes ingen andre steder. Fjernes blokka, byttes datduplisering mot **logikkduplisering** — fem klienter beregner «sikkerhet» fem litt ulike måter og oppdager aldri at de er uenige. |
| fnr/navn | `profil.eier` | `svar.svar` | `skjema.skjema` | **motstrid** | **Behold alle tre.** Tre ulike opphav med ulik garanti. I det ekte svaret er de UENIGE (`"NOR-ETTERNAVN, OLA"` mot `"Ola Nordmann"`, `kilde_per_felt.navn: "modell"`). Sammenslåing ville slettet nettopp signalet. Meld uenigheten i `varsler` i stedet. |
| `modell_brukt` | rot (`kilde`) | `svar`/`skjema` | `kilde_per_felt` | bevisst | **Behold alle tre** — tre kornstørrelser for tre formål. Legg til `modell_brukt: bool` på rot, så robotens sjekk ikke er delstrengsøk. |
| `dato` / `dato_norsk` | `profil.dokument` | — | — | avledet | **Behold, men gjør konsekvent.** `arbeid.startdato` og `okonomi.utbetalingsdato` er norske i en ISO-seksjon — dét er defekten, ikke paret. |
| `dokument.ar` | av `dato[:4]` | — | — | avledet | **Behold**, men døp `dokumentaar` — den står i dag ved siden av `alder.aar` (0.19), to skrivemåter av samme bokstav, to betydninger. |
| `eier.fodselsdato` | av `fnr[:6]` | — | — | **feil** | **Fjern.** Hardkodet `1900 + aar` gir feil århundre for alle født etter 1999. Er ikke et duplikat, men en gjetning presentert som faktum. |
| `okonomi.valuta` | konstant | — | — | **feil** | **Fjern eller døp `valuta_antatt`.** Hardkodet `"NOK"`, aldri lest fra dokumentet. |
| `dokument.type` | `profil.dokument.type` | `sammendrag.dokumenttype` | `struktur.dokument.dokumenttype` | ekte + navnesprik | **Behold verdiene, samle navnet** på `dokumenttype`. |
| `datoer` | `felter.datoer` | `felter.datoer_detaljert` | `struktur.datoer` | **motstrid** | **Skill dem.** `struktur.datoer` mangler `rolle`/`type_kodet` som `datoer_detaljert` har — OpenAPI påstår at de er like. Gjør `datoer_detaljert` til egen bryter (39 % av svaret). |
| `valg` | rot | — | — | diagnostikk | Behold — ekko av forespørselen, billig og nyttig. |
| `fra_cache`, `tid_sekunder` | rot | — | — | diagnostikk | Behold i v1; flytt til `diagnostikk` i v2. |

**Sum ekte duplisering: ~800 B av 33 424 B = 2,4 %.** Å fjerne alt ville
spart mindre enn en tidel av hva gzip gir gratis.

---

## 4. Endepunktskart

| Sti | Inn | Behandling | Ut | Avhengigheter |
|---|---|---|---|---|
| `POST /dokument` (bryter) | fil + 7 ja/nei-brytere + `sporsmal`/`skjema_mal` | analysecache → `DokumentKontekst` → valgte deler | 21 toppnøkler | deler cache med /analyser, /spor, /uttrekk, /sladd |
| `POST /dokument` (operasjoner) | fil + `operasjoner[]` | samme kjerne, `Operasjonsmotor` | **13** toppnøkler — 9 mangler helt | samme |
| `POST /spor` | fil og/eller `sporsmal`, `jobb_id` | 5 ulike ruter | **5 ulike svarformer** | leser ferdige `/jobb` |
| `POST /uttrekk` | fil | `strukturert_uttrekk` | fast JSON-skjema | — |
| `POST /analyser` | fil | `analyser_bytes` direkte | **4 ulike former**, ingen `versjon` | — |
| `POST /fyll_skjema` | fil + `skjema` (malen) | mal + kodevalidering | `{skjema, avvik, kilde_per_felt}` | — |
| `POST /jobb` → `GET /jobb/{id}` | fil, `Idempotency-Key` | asynkron, én arbeidstråd | 202 ny / **200 med annen kropp** ved gjenbruk | → `/spor?jobb_id` |
| `POST /forhandssjekk` | fil | kvalitetsdom før GPU | `dom: god/tvilsom/avvis` | port foran `/dokument` |
| `POST /sladd` | fil, `typer` | sjekksumbevist sladding | `sladdet_tekst`, `ikke_dekket` | — |
| `POST /innsyn` → `GET /innsyn/{id}` | fil | strømmet visning | hendelser + base64-bilder | nøkkelbeskyttet |
| `POST /ekko` | hva som helst | diagnose av multipart | det serveren mottok | UiPath-feilsøking |
| `GET /hjelp`, `/openapi.json`, `/dokumentasjon` | — | — | — | åpne uten nøkkel |

**Hovedproblem:** fem endepunkter produserer samme deterministiske fakta
fra samme cache i fem ulike JSON-former. `felter` betyr **flat
entitetsdict** i `/analyser` og `/jobb`, men **wrapper**
`{felter, datoer, datoer_detaljert, dokumentdato}` i `/dokument`.
Dokumentasjonens egen konklusjon — «velg ett endepunkt og bli der» — er
en innrømmelse av at kontrakten er fem kontrakter.

---

## 5. Foreslått arkitektur

Skillet innføres **additivt i v1** og fullføres i v2:

| Lag | Innhold | Løfte |
|---|---|---|
| **Kontrakt** | `dokumentprofil`, `felter`, `struktur`, `svar`, `skjema`, `resultater`, `strekkoder`, `handskrift`, `ok`, `problem`, `versjon.kontrakt` | navn og typer endres ikke uten major; nøkler kan legges til |
| **Observerbart** | `kvalitet`, `varsler`, `kilde`, `modell_brukt`, `tall_verifisert`, `kilde_per_felt` | nye verdier kan komme; ingen uttømmende `switch` |
| **Internt** | `fra_cache`, `tid_sekunder`, `sendt_til_gjennomgang`, `versjon.modell`, `versjon.ocr_konfidens_terskel`, `ocr_motorer` | ingen kompatibilitetsløfte |

**Interne detaljer som lekker ut i dag og bør flyttes:**
`sendt_til_gjennomgang` (Label Studio-tilstand), `versjon.ocr_konfidens_terskel`
(egentlig `LS_KONFIDENS_TERSKEL`, ikke en API-parameter), `versjon.modell`
(filnavn med kvantiseringsnivå), `ytelse.status` (vårt veikart),
`skjema.tilgjengelige_felter` (24 interne uttrekksnavn).
Og `/analyser` returnerer den interne analysedicten filtrert **kun** på
understrek-prefiks — ett nytt felt uten understrek publiseres automatisk.

**Én proveniensmodell** erstatter fem vokabularer, adressert med RFC 6901
JSON Pointer — samme syntaks som allerede brukes i `problem.errors[].pointer`:

```jsonc
"opphav": {
  "/dokumentprofil/eier/fnr": {
    "metode": "etikett", "konfidens": "hoy",
    "begrunnelse": "Fødselsnummeret står under «Opplysninger om» …",
    "side": 2
  },
  "/skjema/navn": {"metode": "modell", "konfidens": "lav"}
}
```

To lukkede vokabularer, aldri gjenbrukt til noe annet:
- `metode`: `sjekksum` | `etikett` | `posisjon` | `metadata` | `strekkode` | `regel` | `modell` | `avledet` | `ingen`
- `konfidens`: `hoy` | `middels` | `lav` | `ingen` — **én skala overalt**

Dagens `dato_sikkerhet`, `eier.sikkerhet`, `kilde_per_felt`,
`dato_begrunnelse`, `dato_kilde` blir da **visninger** av én kilde i
stedet for fem uavhengig beregnede verdier. Nivå styres per kall
(`opphav=ingen|viktige|alle`, standard `viktige`).

---

## 6. Foreslått responsskjema (v1.4, additivt)

Kun det som endres vises; alt annet er urørt.

```jsonc
{
  "ok": true,
  "status": "delvis",            // NYTT: ok | delvis | feil — når en del feilet
  "modell_brukt": true,          // NYTT: bool, erstatter delstrengsøk i «kilde»
  "kilde": "borealis+deterministisk",   // beholdes, men RETTES (se §9 P0-4)

  "dokumentprofil": {
    "skjemaversjon": "1.2",
    "sammendrag": {
      "…": "…",
      "konfidens": "middels",    // omdøpt fra «sikkerhet»; skala hoy/middels/lav/ingen
      "les_dokumenter": true     // NYTT: maskinlesbar form av «er antall_dokumenter > 1»
    },
    "part": { … },               // NYTT navn; «eier» beholdes som alias, merket utgått
    "eier": { … },               // UTGÅTT fra v1.4, fjernes i v2
    "andre_fodselsnummer": [ … ],// omdøpt fra «andre_personer» — feltet er nummer, ikke personer
    "dokument": {
      "dokumentdato": "2026-05-28",       // NYTT navn, «dato» beholdes
      "dokumentdato_norsk": "28.05.2026",
      "dokumentaar": 2026,                 // NYTT navn, «ar» beholdes
      "dokumentperiode": {"fra": "…", "til": "…"},   // NYTT, erstatter periode_start/slutt
      "…": "…"
    },
    "arbeid": {
      "startdato": "2019-08-01",           // RETTET til ISO
      "startdato_norsk": "01.08.2019",     // NYTT
      "…": "…"
    }
    // eier.fodselsdato FJERNET (feil århundre etter 1999)
    // okonomi.valuta FJERNET eller omdøpt valuta_antatt
  },

  "varsler": [                   // NYTT: strukturerte, erstatter kvalitet.advarsler-strenger
    {"type": "https://…/problems/tom-side", "alvor": "info",
     "detail": "side 7 (nesten) tom", "pointer": "/dokumentprofil/fil/blanke_sider"},
    {"type": "https://…/problems/modell-mot-bevis", "alvor": "advarsel",
     "detail": "skjema.navn (modell) avviker fra bevist part.navn",
     "pointer": "/skjema/skjema/navn"}
  ],

  "opphav": { … },               // NYTT, se §5
  "kvalitet": { … }              // beholdes, merket utgått til fordel for varsler
}
```

Ny bryter: `profil=full|sammendrag` (standard `full`, ukjent verdi → 400,
aldri autoaktivering). `sammendrag`-formen returnerer
`{skjemaversjon, sammendrag, utelatt:[…]}` — utelatte seksjoner navngis,
ingenting forsvinner i stillhet.

Ny bryter: `datoer_detaljert=ja|nei` (standard **nei**) — 39 % av svaret.

---

## 7. Sannhetskildematrise

| Faktum | Sannhetskilde | Produsert av | Lagres? | Avledet? | Returneres? |
|---|---|---|---|---|---|
| dokumenttekst | PDF-tekstlag / OCR | `analyser_bytes` | cache (32) + `data/jobber/` | nei | `tekst` |
| sideantall | `fitz` | `analyser_bytes` | ktx | nei | 3 steder (speil) |
| dokumentdato | klassifiserte datoer | `finn_dokumentdato` | ktx | nei | **14+ steder, 2 formater** ⚠ |
| fødselsnummer (part) | mod11 + etikett | `finn_dokument_eier` | ktx.profil | nei | `part.fnr` |
| fødselsnummer (alle) | mod11 | `finn_alle_fodselsnummer` | ktx.struktur | nei | `struktur.identifikatorer` |
| — men også | **uten etikettvakt** | `finn_fodselsnummer` | ktx.felter | nei | `felter.fodselsnummer` ⚠ **kan gi kontonummer** |
| navn | etikett eller modell | `_navn_ved` / Borealis | ktx.profil / skjema | nei | 6 steder, **kan avvike** ⚠ |
| beløp | 4 ulike begreper | `finn_belop`/`finn_totalbelop`/`finn_alle_belop`/`_merket_belop` | ktx | nei | 10 steder ⚠ |
| periode | **2 ulike begreper under ett navn** | `gjelder_periode` / `dokumentets_periode` | ktx | nei | 5 steder ⚠ |
| strekkoder | pyzbar (egen sjekksum) | `les_strekkoder_bytes` | cache | nei | 2 steder |
| ytelse | `finn_ytelse` | ✅ én kilde | ktx | nei | 6 steder |
| saksnummer | `finn_saksnummer` | ✅ én kilde | ktx | nei | 5 steder |
| telefon | `_telefon_treff` | ✅ én skanner | ktx | nei | 4 steder |
| hjemmel/lov | dokumentdato + register | `lov_for_dato` | mtime-bufret | ja | `hjemmel` |
| `sammendrag.sikkerhet` | eier + dato + antall | `_sammendrag` | — | **ja** | `sammendrag` |
| `eier.fodselsdato` | `fnr[:6]` | `_fodselsdato_av_fnr` | — | **ja, og feil** ⚠ | fjernes |

⚠ = mer enn én autoritativ kilde, eller kilder som kan gi ulikt svar.

---

## 8. Versjoneringsstrategi

**I dag: fire uavhengige tellere, ingen regel.**
`API_VERSJON` (`1.3.0`) har stått urørt gjennom **45 commits** mens
`koordinater`, hele `operasjoner`-kontraktet, `hjemmel`, `sammendrag` og
`dokumenter[]` kom til. `/api/v1` er kosmetikk — `_sti()` stripper
prefikset, og `/api/v2/…` gir 404. Feilsvar har ingen versjon i det hele
tatt.

**Foreslått:**

```jsonc
"versjon": {
  "kontrakt": "1.4.0",        // SemVer over det PUBLIKE skjemaet
  "skjema": {"dokumentprofil": "1.2", "uttrekk": "1.0"},
  "produksjon": {"uttrekk_regler": "u6", "prompt": "p10", "modell": "…"}
}
```

| Endring | Utslag |
|---|---|
| nytt felt / ny enum-verdi / nytt endepunkt | `kontrakt` minor |
| felt merket utgått (leveres fortsatt) | `kontrakt` minor + `Deprecation`/`Sunset` |
| felt **fjernet**, type endret, semantikk endret | **kun `/api/v2`** |
| ny prompt / nye regler / ny modell, samme skjema | kun `produksjon.*` |

**Vakt:** en test som serialiserer `_openapi()`-skjemaene + profilens
nøkkelsett og sammenligner mot en sporet fasitfil. Avvik ⇒ «skjemaet er
endret — bump `versjon.kontrakt`». Det er den ene testen som ville
stoppet alle fire tellerproblemene.

**Deprekeringsløp** (minimum 12 mnd for kontraktsfelter):
merket (`deprecated: true` i OpenAPI) → varslet (`Deprecation`/`Sunset`
RFC 8594 + linje i `varsler[]`) → tomt (`null`, aldri fjernet) → borte (v2).

**Forutsetning:** navngitte API-nøkler per klient og `klient_id` i
tilgangsloggen. Uten det kan ingen fjerning gjøres med kunnskap.

---

## 9. Ytelsesforbedringer

Alle tall målt der ikke annet står.

### P0 — kritisk

**P0-1 · Kvadratisk identifikatorskanning**
Problem: `_tallkandidater_med_posisjon` (tekstuttrekk.py:1299-1302)
skanner `opptatt` lineært per kandidat. Målt vekst per dobling: **4,08×**
(1,42 ms → 247,82 ms fra 7 335 til 117 375 tegn).
Endring: sorter `opptatt` og bruk `bisect`/intervallmaske; forhåndsberegn
linjestart-indeks i `_navn_ved`.
Effekt: **[anslag]** 248 → under 25 ms ved 117 k tegn.
Risiko: **lav funksjonelt, men koden er sikkerhetskritisk** — dato/beløp-
vakten hindrer at «01.01.2024 114 kroner» blir et falskt fødselsnummer.
`test_falske_identifikatorer.py` må være grønn før og etter.

**P0-2 · Strekkodeskanning er 92 % av et kaldt kall**
Problem: målt live 945 ms mot 84 ms med `strekkoder=nei`. Hver side
rendres til bilde selv på PDF med fullt tekstlag. Standard PÅ.
Endring: på tekstlags-PDF, skann bare sider der PyMuPDF melder innebygde
bilder; eventuelt lavere oppløsning for kodeskanning.
Effekt: **−883 ms**, ~10× raskere kaldt kall. Null effekt på skann.
Risiko: **middels-høy** — commit 9798200 («skann HELE dokumentet») viser
at området har hatt regresjoner. Må testes mot korpuset (koder på side
3 og 10).

**P0-3 · Én forespørsel kan holde GPU-en i minutter**
Problem: 20 operasjoner × 5 modellkall = 100 genereringer à 0,3–2,8 s =
**30–280 s**, mot socketfrist 120 s, mens den holder 1 av 2
kapasitetsplasser.
Endring: budsjett per forespørsel (f.eks. maks 8 genereringer) + frist;
returner ferdige resultater med ærlig advarsel.
Effekt: **[anslag]** verste synkrone kall fra ~280 s til under 25 s.
Risiko: lav-middels — klienter som sender 20 spørsmål får delvis svar.

**P0-4 · `kilde` lyver**
Problem: bryter-veien teller feilet modelldel som «modellen kjørte»;
operasjoner-veien hardkoder `"motor"`. Dokumentert som robotens
ærlighetssjekk.
Endring: rett regelen; legg til `modell_brukt: bool` på rot i **begge**
veier; utvid `test_kilde_aerlig.py` til å teste den EKTE regelen, ikke en
lokal kopi.
Effekt: ingen ytelsesgevinst — korrekthet.
Risiko: ingen.

### P1 — høy

**P1-1 · gzip + kompakt JSON.** Ingen komprimering finnes (0 treff).
Målt: 33 424 → **6 422 B (−80,8 %)** med gzip; innrykk alene er 20,9 %.
Endring: `gzip` når `Accept-Encoding: gzip`; `indent=2` kun på forespørsel.
Risiko: lav, men UiPath må verifiseres — den klienten er skjør.
**Størst gevinst i hele revisjonen, null kontraktsendring.**

**P1-2 · `datoer_detaljert` er 39 % av standardsvaret.**
Målt 12 949 B av 33 424 B — større enn dokumentteksten.
Endring: egen bryter, standard AV.
Risiko: middels — kontraktsbrudd for klienter som leser den. Additivt
alternativ: behold feltet, fjern `kontekst`-strengen per dato.

**P1-3 · Analysen kastes og regnes på nytt.** `_les_dokument` plukker ikke
opp `felter`/`datoer`/`datoer_detaljert`/`dokumentdato` som ligger ferdig
i samme dict. Målt 18,0 + 19,3 ms.
**Viktigere enn tiden:** de to versjonene er ULIKE — `analyser_bytes` har
PDF-metadata og `skrevet_for_hand`-merking, `ktx` har det ikke. Derfor kan
`/analyser` og `/dokument` svare ulik dokumentdato for samme fil, og
advarselen «datoen er håndskrevet» kan aldri utløses i profilen.
Effekt: −19 til −28 ms; ~30–40 % av et cachet kall.

**P1-4 · Datokjeden kjøres to ganger i `DokumentKontekst`.** Målt 12,53 ms
mot 5,25 ms for ett pass = **7,28 ms bortkastet**.
Risiko: lav — `sett_dato_roller` muterer på stedet; delt liste må sjekkes.

**P1-5 · Kapasitetsgulvet overstyrer målingen.** Serveren måler
`fra.gpu = 1`, men `MIN_SAMTIDIGE = 2` løfter grensen til 2. Målt metning:
**1,6–1,7 req/s uansett N**; 4 tråder deterministisk arbeid gir **0,90×**
(GIL — `re` slipper den ikke). Og `KOE_VENT_S` (180 s) er **lengre enn**
`SOCKET_TIDSAVBRUDD_S` (120 s): klienten står i kø forbi serverens egen
frist uten å få vite det.
Endring: senk køfristen under socketfristen; si ærlig i `/hjelp` at
grensen er hevet over målingen.

### P2 — middels

**P2-1 · Ingen svarcache for modellkall.** Samme spørsmål på samme dokument
koster full modelltid (målt 2 777 ms). Nøkkel må inneholde promptversjon
og modellfil, ellers overlever en stale cache en promptendring.

**P2-2 · Skjemadelen bygger felttabellen på nytt.** Målt 12,03 ms mot
**0,01 ms** når tabellen gis ferdig.

**P2-3 · Nullfelter og konstantlister.** 41,9 % av eksempelsvaret er
«ikke ny informasjon», men gevinsten er ~2 % av et ekte svar.
**Ikke gjør dette for ytelsens skyld — gevinsten forsvarer ikke bruddet.**

**P2-4 · Minnetak i antall, ikke byte.** `_analyse_cache` teller 32
oppføringer; en OCR-rad bærer `_sider_regioner` — **[anslag]** 0,25–0,75 MB
per rad. `_jobber` har **ingen** eviction og holder full tekst for
prosessens levetid. `/jobb`-køen er ubegrenset og køede jobber holder hele
filen i minne.

### P3 — lav

**P3-1 · Tydelig terskel for `/jobb`.** Dokumentasjonen sier bare «for
stort til å vente på». En klient kan lovlig be om `maks_sider=50`
synkront; med prosjektets egne OCR-tall er det 55 s i beste fall og
**850 s** når OCR faller til CPU — mot 120 s socketfrist.

**P3-2 · Grammatikkbundet JSON** fjerner retry-kallet i skjemautfylling.
Risiko: `transformers_nf4`-veien har ikke funksjonen; krever fallback.

**P3-3 · `_opptatt_cache` uten lås.** Målt bomstraff +1,84 ms (+10,2 %).
Marginalt, men reelt — og den styrer hvilke tall som blir fnr vs konto,
så et dokument kan i prinsippet påvirke et annets uttrekk.

---

## 10. Sikkerhetsforbedringer

**Godt løst, bør bevares:** språkmodellen kjører **100 % lokalt**
(verifisert: null utgående HTTP i `dokument_api.py`); tilgangsloggen er
verifisert fri for persondata over 80 000 linjer; `hmac.compare_digest` på
alle POST-stier før ruting; CORS restriktivt som standard; `/sladd` nekter
å gjette og melder ærlig hva den ikke dekker.

| Data | Klassifisering | Forekomster i ett svar | Anbefaling |
|---|---|---|---|
| Fødselsnummer | STRENGT SENSITIV | 3 direkte + 1 avledet + fritekst | Én kanonisk (`part.fnr`). Utelates i `profil=sammendrag`. Aldri i logg. |
| Helseopplysning (`ytelse`) | STRENGT SENSITIV (GDPR art. 9) | 3 | **Merkes som art. 9-data.** Ytelseskoden alene avslører helsestatus. |
| Kontonummer | SENSITIV | 1 | Behold; vurder maskering med eksplisitt bryter for full verdi |
| Navn | SENSITIV | 5 | Behold `part.navn`; utelates i `profil=sammendrag` |
| Fødselsdato | SENSITIV | 1 (avledet, **og feil**) | **Fjern** |
| KID | SENSITIV | 3 | To av tre er ren duplisering |

**Funn som må rettes:**

| # | Funn | Alvor |
|---|---|---|
| S1 | `data/jobber/*.json` lagrer **full dokumenttekst permanent** — ingen TTL, ingen rydding, ingen kryptering. Verifisert: 37 KB-filer med 35 200 tegn. Og `rydd_gjennomgang.py` påstår i sin egen docstring at gjennomgangsmappa er «det ENESTE stedet systemet bevarer data» — **det stemmer ikke**. | **HØY** |
| S2 | Label Studio-eksporten treffer systematisk de mest sensitive dokumentene (utløser på håndskrift/lav konfidens ⇒ håndskrevne legeerklæringer **alltid**). Sender råtekst, side-1-PNG og navn. Bildet skrives først til OS-temp **utenfor `nav/`** (bryter CLAUDE.md §1) og overlever et prosesskrasj. | **HØY** |
| S3 | `dokumentprofil` returneres uansett hva klienten ba om — et kall med bare `sporsmal` får fnr, fødselsdato, adresse, telefon, e-post, arbeidsgiver, årsinntekt, kontonummer og KID. | **HØY** |
| S4 | `raasvar` returnerer inntil 1500 tegn ukontrollert modellutdata ved feil — nettopp det klienter limer inn i supportsaker. | MIDDELS |
| S5 | Fødselsnummer injiseres i skjemaprompten **selv når malen ikke ber om det**. `refererte_felt` er allerede importert og kan filtrere. | MIDDELS |
| S6 | `/sladd` sin `ikke_dekket` sier bare «navn, adresser». Faktisk udekket er også arbeidsgiver, inntekt, diagnosetekst, saksnummer, datoer. | MIDDELS |
| S7 | Rå unntakstekst returneres til klienten på `/innsyn` — omgår `_serverfeil`-disiplinen. | MIDDELS |
| S8 | `tilgang.log` roterer ikke: 11,5 MB / 80 162 linjer. IP-adresser er personopplysninger. | LAV |
| S9 | `LLM_URL` i `.env` er død konfigurasjon — antyder et eksternt LLM-endepunkt som ikke finnes. Fjernes; den gir feil inntrykk i en personvernvurdering. | LAV |

---

## 11. Migreringsplan

Ingen omskriving. Fire faser, hver med grønn testsuite før neste.

### Fase 1 — korrekthet og ærlighet (ingen kontraktsendring)

Feil som gir GALE SVAR i dag. Alle er additive eller rene rettelser.

1. `finn_fodselsnummer` får samme etikettvakt som flertallsvarianten
   (rapporterer i dag kontonummer som fnr)
2. `_ANDEL_ETTER`-regexen: `\b` etter `%` feiler på «100 % av»
3. `finn_postnummer_sted` får selskapsform-vakten `finn_adresser` har
4. `kilde`/`modell_brukt` rettes i **begge** `/dokument`-veier; testen
   testes mot den ekte regelen
5. `periode_start` i `felter_flatt` skilles fra profilens begrep
6. Dokumentdatoen regnes ÉN gang (`maks`-grensene 200/30/15 samles)
7. `_les_dokument` gjenbruker `analyser_bytes`-resultatene (P1-3/P1-4)
8. `_opptatt_cache` får lås
9. `eier.fodselsdato` fjernes; `okonomi.valuta` gjøres ærlig
10. Datoformat: `arbeid.startdato`/`sluttdato`, `okonomi.utbetalingsdato`
    til ISO med `_norsk`-tvilling
11. R79/R80-dublettene i regelverket løses opp
12. `docs/endepunkter.md` rettes (`dokument_eier`/`andre_fodselsnummer`
    finnes ikke); `dokumentprofil_skjema.md` oppdateres til 1.1

### Fase 2 — ytelse og sikkerhet (ingen kontraktsendring)

13. gzip (**−80,8 %**) — største enkeltgevinst
14. Strekkodeskanning hoppes over på tekstlags-PDF (**−883 ms**)
15. Modellkall-budsjett per forespørsel (P0-3)
16. O(n²) → O(n log n) i identifikatorskanningen (P0-1)
17. `KOE_VENT_S` under `SOCKET_TIDSAVBRUDD_S`
18. Retensjon på `data/jobber/` + rett docstring-påstanden (S1)
19. Label Studio-bildet under `nav/`; planlagt rydding (S2)
20. `raasvar` og `/innsyn`-feil sladdes (S4, S7)
21. Identifikatorlista i prompten filtreres mot malens felter (S5)
22. `ikke_dekket` utvides til den reelle listen (S6)

### Fase 3 — kontraktsutvidelser (additivt, `versjon.kontrakt` 1.4.0)

23. `part` som alias for `eier`; `eier` merkes utgått
24. `andre_fodselsnummer` som alias for `andre_personer`
25. `konfidens` én skala; `sikkerhet` merkes utgått
26. `varsler[]` strukturert ved siden av `kvalitet.advarsler`
27. `status: ok|delvis|feil`
28. `datoer_detaljert`-bryter (standard av) og `profil=full|sammendrag`
29. `opphav`-sidekartet (standard `viktige`)
30. `dekning`-seksjon; `ytelse.status` frigjøres
31. Speiltester for `filnavn`/`antall_sider`/`strekkoder`
32. Skjema-regresjonstest som tvinger `versjon.kontrakt` opp

### Fase 4 — v2 (krever klientidentitet først)

33. **Navngitte API-nøkler + `klient_id` i tilgangsloggen** — forutsetning
34. `/api/v2` som ekte rute; v1 produseres som projeksjon av v2
35. Utgåtte navn fjernes; `data`/`metadata`/`diagnostikk` fullføres
36. `operasjoner` flyttes til egen ressurs (`POST /dokument/operasjoner`)
37. `Kodet {kode, term}` utvides til `dokumenttype`, `ytelse`, `sakstype`
38. `hjemler[]` og `ytelser[]` som lister (flere lover/ytelser per dokument)

---

## FINAL RECOMMENDATION

### 1. Hva må endres straks
Fase 1 i sin helhet — dette er ikke forbedringer, det er feil som gir gale
svar: et kontonummer rapportert som fødselsnummer, to felter ved navn
`periode_start` med ulik betydning, modellen som får en annen dokumentdato
enn profilen melder, og `kilde` som lyver i nettopp de tilfellene den skal
fange. Deretter gzip og strekkodefiksen, som er de to største målte
gevinstene og ikke rører kontrakten.

### 2. Hva må IKKE endres
- **Dupliseringen.** 2,4 % av svaret. `sammendrag` særlig — fjerning bytter
  datduplisering mot logikkduplisering.
- **«Alle nøkler alltid til stede» (R44/R79).** Skillet mellom «vi så etter
  og fant ingenting» og «vi så ikke etter» er bærende. Prisen er 6 %.
- **Ærlighetsfeltene** — `tall_verifisert`, `avvik`, `kilde_per_felt`,
  `modell_brukt`, `fra_cache`, `advarsler`. De er over nivået for API-er av
  denne typen.
- **Den flate bryter-responsen.** UiPath-klienter er i drift og skjøre.
- **`/sladd` sin nektelse av å gjette.**
- **Multipart-toleransen (R63).**

### 3. Hva kan vente
`data`/`metadata`/`diagnostikk`-omstruktureringen, `opphav`-sidekartet,
navneendringene og v2. Alle forutsetter klientidentitet for å kunne
fullføres — uten den legger man bare til felter som aldri kan fjernes.

### 4. Endelig form
`/dokument` beholder dagens form med additive tillegg (§6). Ingen
omstrukturering før v2, og v2 ikke før man vet hvem som leser hva.

### 5. De ti største problemene
1. `kilde` lyver på begge veier — robotens ærlighetssjekk
2. `felter.fodselsnummer` kan rapportere et kontonummer
3. 100 modellkall mulig i én forespørsel (30–280 s GPU)
4. `periode_start` betyr to ting under ett navn
5. Modellen får en annen dokumentdato enn profilen melder
6. O(n²) i identifikatorskanningen (4,08× per dobling)
7. Full dokumenttekst lagres permanent uten retensjon, mot egen påstand
8. De to `/dokument`-kontraktene har divergert funksjonelt
9. Ingen klientidentitet ⇒ ingen felter kan noensinne fjernes
10. `sikkerhet` betyr fire ting, `kilde` fire, `status` tre

### 6. De ti med høyest avkastning
1. **gzip** — −80,8 %, null kontraktsendring
2. **Strekkoder av på tekstlags-PDF** — −883 ms (92 % av kaldt kall)
3. **Rett `kilde`/`modell_brukt`** — én regel, fjerner en tillitsfeil
4. **Etikettvakt i `finn_fodselsnummer`** — fjerner feil identifikator
5. **Gjenbruk `analyser_bytes`-resultatene** — −28 ms *og* fjerner avvik
6. **Modellkall-budsjett** — fjerner den verste haleristen
7. **`datoer_detaljert` som bryter** — −39 % av standardsvaret
8. **Retensjon på `data/jobber/`** — fjerner høyeste personvernfunn
9. **O(n²) → O(n log n)** — beskytter mot store bunker
10. **Navngitte API-nøkler** — låser opp alt i fase 4

---

## Metode og forbehold

Åtte revisjoner kjørte parallelt med hvert sitt mandat og uten kjennskap
til hverandres funn. Hver ble instruert til å lese den faktiske koden, vise
fil:linje, og aldri finne på tall. Revisjon 6 ble i tillegg pålagt å vise
kommandoen bak hvert måltall eller merke det **[anslag]**.

**Ikke målt:** OCR-veien (ville lastet OCR-modeller på et 8 GB-kort som
Borealis allerede bruker, og utløst automatisk Label Studio-eksport);
`_sider_regioner`-størrelsen i cachen; treffraten for en eventuell
svarcache; tokenize-kostnaden i `_tilpass_kontekst`.

**Én måling gjelder en foreldet prosess:** serveren på 8600 kjørte
`skjemaversjon 1.0` mens disken har 1.1. Profilen på disk er 123 % større
enn den live-målte, så live-tallene er konservative.

**Ett falskt funn ble luket ut** i kryssgjennomgangen — se §2.3.

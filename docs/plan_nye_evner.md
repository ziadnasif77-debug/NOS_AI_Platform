# Plan: tre foreslåtte evner — vurdert mot koden

Skrevet 2026-08-03. **Status: evne 1 (/forhandssjekk) er BYGGET** samme
dag — se `docs/endepunkter.md` og `tester/test_forhandssjekk.py`.
Kalibreringen avdekket at dømming på nominell dpi var feil (PNG=96 er
formatets antakelse, ikke bildets egenskap); dommen skjer på rendrede
piksler. Orientering (90°/180°) ble utsatt som planlagt.

Evne 2 og 3 er fortsatt ubesluttede. Slett dokumentet når alt er avgjort.

Alle tre respekterer «ingen lagring»: de leser en forespørsel og svarer,
uten å skrive noe om dokumentet til disk.

Rekkefølgen under er etter **kost/nytte målt mot koden slik den er**, og
den er en annen enn den opprinnelige listen foreslo. Begrunnelsen står
under hver enkelt.

---

## 1. `POST /forhandssjekk` — avvis dårlige skann før GPU-en brukes

**Hvorfor først:** målingene finnes allerede. Dette er å eksponere kode
vi har, ikke å skrive ny bildebehandling.

### Det som allerede finnes

| Finnes i dag | Hvor |
|---|---|
| Skarphet (Laplacian-varians), lysnivå, oppløsningsvakt | `delt/forbehandling.py` → `vurder_kvalitet()` |
| Ærlige advarsler på norsk («uskarpt bilde — ta et nytt bilde …») | samme |
| Skjevhetsvinkel i grader | `rett_skjevhet()` |
| Perspektiv-/belysningsrapport | `forbehandle_side()` → `rapport` |
| Naturlig oppløsning for en innebygd bildeside | `dokument_api.ocr_skala()` (R51) |

`forbehandle_side()` returnerer allerede `{"kvalitet", "perspektiv_rettet",
"belysning_flatet", "skjevhet_grader", "linjer_fjernet"}`.

### Det som må bygges

1. **Endepunkt** `POST /forhandssjekk` i ruteren, ved siden av `/ekko`.
   Rendrer sidene, kaller `vurder_kvalitet()` per side, og **stopper
   der** — ingen OCR, ingen modell.
2. **DPI-utledning** per side. `ocr_skala()` regner allerede ut
   `naturlig = bredde_px / side.rect.width`; trekk den ut som en egen
   funksjon som returnerer tallet i stedet for en `fitz.Matrix`, så både
   OCR-veien og forhåndssjekken bruker SAMME regnestykke.
3. **Tomme sider:** andel ikke-hvite piksler under en terskel.
4. **Orientering (90°/180°):** dette er den eneste virkelig nye biten.
   Se risiko under.
5. **Samlet dom:** `{ok, sider:[…], dom: "god"|"tvilsom"|"avvis",
   advarsler:[…]}` slik at en robot kan gate på ett felt.

### Risiko

- **Orienteringsdeteksjon er ikke gratis.** Å avgjøre om en side står
  180° feil krever enten en OSD-modell (Tesseract har `image_to_osd`, som
  vi ikke bruker) eller en heuristikk på linjeprofil som er upålitelig på
  skjema. **Anbefaling: lever punkt 1–3 og 5 først, og la orientering
  være et eget spørsmål.** Halve verdien ligger i DPI + skarphet + tomme
  sider, og de er sikre.
- Terskelverdiene i `forbehandling.py` er kalibrert for å BESTEMME om et
  steg skal kjøres, ikke for å DØMME et dokument. De må trolig justeres,
  og det bør gjøres mot regresjonskorpuset (`tester/korpus/`), ikke mot
  ett dokument.

### Omfang

Lite. Endepunkt + uttrekk av DPI-funksjonen + tester. Ingen endring i
lesemotoren, så ingen risiko for å forringe dagens uttrekk.

---

## 2. `POST /sladd` — sladding av det vi kan BEVISE

**Hvorfor nummer to:** halve forslaget er en perfekt match, den andre
halvparten er ikke mulig deterministisk i dag. Å levere den delen vi kan
bevise er riktig; å love resten er ikke.

### Det som allerede finnes

Alle finnerne er på plass i `delt/tekstuttrekk.py`, og de er
sjekksum-/formatvaliderte:

`finn_alle_fodselsnummer`, `finn_alle_kontonummer`,
`finn_alle_organisasjonsnummer`, `finn_alle_kid`, `finn_alle_telefoner`,
`finn_alle_eposter` — pluss `finn_postnummer_sted`.

Mod11 gjør dette til matematikk, ikke gjetning. Det er nettopp derfor
denne evnen passer prosjektet.

### Det forslaget overser

- **Navn kan vi IKKE sladde deterministisk.** `utvid_entiteter` sier det
  rett ut i egen docstring: deterministiske treff vinner for strukturerte
  felter, mens *navn beholdes fra modellen*. NER er fjernet. En
  navnesladding ville altså være en gjetning — og **ufullstendig sladding
  er farligere enn ingen sladding**, fordi den ser fullført ut.
- **Adresser** er i samme kategori: `finn_adresser` finner mønstre, men
  garanterer ikke dekning.
- **Visuell sladding av en PDF krever koordinater** (evne 3). Uten dem
  kan vi sladde TEKSTEN vi returnerer, men ikke produsere en sladdet PDF.

### Forslag til ærlig avgrensning

Endepunktet leverer sladdet **tekst**, og sier eksplisitt i svaret hva
som ble sladdet og hva som IKKE dekkes:

```
{ok, sladdet_tekst, funn: [{type, antall}], ikke_dekket: ["navn", "adresse"],
 advarsel: "Navn og adresser sladdes ikke — de kan ikke bevises
            deterministisk. Manuell gjennomgang er påkrevd."}
```

Den advarselen er ikke en unnskyldning, den er poenget: brukeren skal
vite nøyaktig hvor grensen går før dokumentet sendes ut av huset.

### Risiko

- **Overdreven sladding** er også en feilmodus: et saksnummer som ligner
  et kontonummer må ikke forsvinne. Mod11 beskytter mot dette, men
  telefon/epost-mønstrene er svakere. Testene må dekke begge retninger —
  at det som SKAL sladdes forsvinner, og at det som IKKE skal sladdes
  blir stående.
- Juridisk: hvis noen tror dette er nok for `offentleglova`, er skaden
  reell. Advarselen må stå i selve svaret, ikke bare i dokumentasjonen.

### Omfang

Moderat. Ingen ny deteksjon — bare erstatning + rapport + grundige
tester på begge feilretninger.

---

## 3. Koordinater per uttrekt felt

**Hvorfor sist:** høyest verdi, men klart størst arbeid — og forslaget
undervurderer det. Påstanden «du kaster dem bare» stemmer ikke helt.

### Det som allerede finnes

- `delt/region_ocr.py` regner ut `"boks": [x0, y0, x1, y1]` per region.
- `POST /innsyn` **returnerer dem allerede** (`_innsyn_arbeider`).

### De tre reelle hindringene

1. **Bare side 1.** I `ocr_pdf_bytes`: `if i == 0: side1_regioner =
   resultat["regioner"]`. For side 2 og utover brukes regionene til å
   regne konfidens og motorstatistikk, og forkastes deretter. Må utvides
   til å beholde bokser per side (med et tak, ellers vokser svaret
   ubegrenset på en 300-siders bunke).

2. **Tekstlags-PDF-er har INGEN regioner.** Da kjører ikke OCR i det hele
   tatt. Dette er den vanligste dokumenttypen i NAV-post, altså har
   nettopp høyvolum-tilfellet ingen koordinater i dag. Løsningen finnes —
   `fitz` gir ordkoordinater via `page.get_text("words")` — men det er en
   **egen kodevei** som må gi samme svarform som OCR-veien.

3. **Koblingen mangler — dette er selve jobben.** `flett_regioner()`
   returnerer en `str`. Regex-finnerne i `tekstuttrekk.py` kjører på den
   sammenflettede strengen. Det finnes ingen `tegnposisjon → region`-kart,
   så et treff på «tegn 1234» kan ikke føres tilbake til en boks.

   Veien videre: la `flett_regioner` i tillegg returnere et
   offset-register (`[(start, slutt, region_indeks), …]`), og la
   finnerne returnere treffposisjon. Da blir oppslaget en enkel
   binærsøk-operasjon. Dette er gjørbart og ryddig — men det rører
   **fletting OG alle finnerne**, altså kjernen i det som i dag er
   grønt på 355 tester.

### Foreslått rekkefølge hvis den velges

1. Offset-register ut av `flett_regioner` — uten å endre den returnerte
   teksten. Testes mot at teksten er byte-identisk med før.
2. Én finner (f.eks. `finn_alle_organisasjonsnummer`) utvides med
   posisjon, og oppslaget bevises ende-til-ende på ett OCR-dokument.
3. Deretter resten av finnerne, én om gangen.
4. Bokser for alle sider (med tak).
5. Tekstlagsveien via `fitz`.

Steg 1–2 er en ekte skalprøve: virker de, er resten mekanisk. Virker de
ikke, har vi brukt lite.

### Risiko

- Rører kjernen. Bør gjøres med regresjonskorpuset (`skript/kjor_korpus.py`)
  som port, ikke bare enhetstestene.
- Svarstørrelse: koordinater for hvert felt på hver side kan mangedoble
  JSON-en. Trenger et valg (`koordinater=ja`), av som standard — samme
  prinsipp som modelldelene på `/dokument`.

---

## De øvrige forslagene — kort

| Forslag | Vurdering |
|---|---|
| Avkrysningsbokser / signatur | Passer filosofien godt («koden avgjør, ikke modellen»), men krever samme koordinatgrunnlag som evne 3. Naturlig **etter** den, ikke før. |
| PDF-signaturvalidering | Kryptografisk visshet, sterkeste tenkelige belegg. Selvstendig og lite koblet til resten. God kandidat, men smal nytte: forutsetter at dokumentene faktisk er signert. |
| Tabelluttrekk + sumkontroll | Sumkontrollen er svært i prosjektets ånd. Selve tabellgjenkjenningen er derimot et stort problem i seg selv. |
| `/metrics`, HMAC-signert svar, kanari ved oppstart | Alle tre er små, uavhengige og null-lagring. Kanari-dokumentet er den beste av dem: en fast testfil som leses ved oppstart og sammenlignes med et kjent resultat fanger miljø-/modelldrift med en gang. |
| `callback_url` på `/jobb` | Enkelt og gjør UiPath-integrasjonen bedre. Merk at det gjør serveren til en HTTP-KLIENT mot en adresse klienten oppgir — det må avgrenses (tillatelsesliste), ellers er det en åpen videresender. |
| Bokmål/nynorsk/samisk | `gjett_sprak()` finnes allerede i `tekstuttrekk.py`. Å utvide den og si ærlig ifra ved lav tiltro passer godt. Lite arbeid. |

**Ikke anbefalt** (og her er den opprinnelige vurderingen riktig):
semantisk søk, automatisk dokumentklassifisering, dashbord. De ble
fjernet med hensikt; å hente dem tilbake visker ut det tydeligste ved
prosjektet — at det gjør én ting og nekter å bli en plattform.

---

## Anbefaling

Ta **1** først (liten, trygg, hever treffsikkerheten uten å røre
lesemotoren), deretter **2** i den avgrensede formen. **3** er verdt å
gjøre, men fortjener en egen økt med korpuset som port — ikke å bli
klemt inn ved siden av noe annet.

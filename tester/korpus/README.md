# Regresjonskorpus

Dokumenter med en fasit skrevet av et menneske. Kjøres med:

```
python skript/kjor_korpus.py                    # alle
python skript/kjor_korpus.py syntetisk_bunke    # ett navnefilter
```

## Hvorfor dette finnes

Systemet ble lenge forbedret ett dokument om gangen: noen møtte et
problem, vi målte, vi fikset, vi la til en regel. Det ga gode
enkeltfikser, men ingen oversikt — vi kunne aldri svare på om en endring
hjalp på ÉN fil og skadet fem andre. To ganger ble ytelsen dessuten
finjustert mot syntetiske testbilder som ikke lignet virkelige
dokumenter, og feilene ble derfor ikke oppdaget før en bruker traff dem.

Korpuset gjør «virker det?» om fra en mening til et tall.

Regelen som følger av det: **før du legger til en ny regel, spør hvor
mange dokumenter i korpuset den fikser.** Er svaret «ett», er det
sannsynligvis ikke en regel, men et spesialtilfelle.

## Personvern — KUN syntetiske dokumenter

**Korpuset skal bare inneholde syntetiske dokumenter.** Fasitene ligger
i git, og verdiene i dem (numre, beløp, navn) blir dermed liggende i
historikken for alltid. Derfor:

- Dokumenter merket «SYNTETISK TESTDOKUMENT — genererte data, ingen
  ekte personer», med fødselsnumre fra de offisielle syntetiske seriene
  (måned +80/+90) og konstruerte sjekksum-gyldige org.nr/kontonumre.
- ALDRI ekte kvitteringer, fakturaer eller brev — heller ikke «bare som
  dokument på disk»: fasiten som beskriver dem lekker verdiene inn i git.
- Trenger du et vanskelig trekk fra et ekte dokument (skjev skanning,
  termopapir, håndskrift), GJENSKAP trekket i et syntetisk dokument.

Dagens korpus er én 10-siders syntetisk NAV-bunke i to utgaver — med
tekstlag og skannet fra papir — som til sammen dekker: vedtak,
beregningstabell, faktura, egenerklæring, legeerklæring, inntektsmelding,
nesten tom side, bildeside uten tekstlag, nynorsk-klage fra en annen
person, og returslipp.

## Hvordan det er delt

| Hva | Hvor | I git? |
|---|---|---|
| Fasit (`*.json`) | `tester/korpus/` | **Ja** — definisjonen av «riktig» skal ha historikk |
| Dokumentene | `data/korpus/` | **Nei** — `data/` er i .gitignore |

Mangler en fil lokalt, hoppes den over med beskjed i stedet for å felle
kjøringen.

## Legge til et dokument

1. Lag (eller generer) et SYNTETISK dokument og legg det i `data/korpus/`.
2. Lag `tester/korpus/<samme-navn>.json`.
3. **Les fasiten av ORIGINALEN med egne øyne** — ikke av hva systemet
   svarer. Skriver du ned det systemet allerede gjør, tester du bare at
   det fortsetter å gjøre det samme, også når det er feil.
4. Kjør `python skript/kjor_korpus.py <navn>` og se at avvikene er ekte.

## Formatet

```json
{
  "fil": "syntetisk_bunke_tekstlag.pdf",
  "beskrivelse": "Hva slags dokument, og hva som er vanskelig ved det",
  "fasit_lest_av": "menneske, fra dokumentet 2026-08-03",

  "felter": {
    "felter.felter.saksnummer": "4417820",
    "felter.dokumentdato.dato": "12.05.2026",
    "struktur.identifikatorer.kid": ["1002345678911"]
  },

  "felter_maa_inneholde": {
    "struktur.identifikatorer.fodselsnummer": ["12345678910"]
  },

  "tekst_maa_inneholde": ["Saksnummer: 4417820"],
  "tekst_maa_ikke_inneholde": ["gjennem-"],

  "kjent_svakhet": {
    "side8": "Bildeside uten tekstlag leses ikke ennå (hybridlesing planlagt)"
  },

  "maks_sekunder": 5
}
```

Kjøreren poster til **`POST /dokument` med `struktur=ja`** — hovedveien.
Punktstiene slås opp i det svaret: `felter.felter.*` er entallsfeltene,
`struktur.identifikatorer.*` er de komplette listene.

**`felter`** — eksakt sammenligning (tall med liten toleranse, tekst
ordrett). Lister indekseres med tall (`struktur.belop.0.verdi`).

**`felter_maa_inneholde`** — delmengde-sjekk for lister: verdiene må
FINNES, men lista låses ikke (rekkefølge/OCR-støy skal ikke felle en
sjekk på noe annet enn det den gjelder).

**`tekst_maa_inneholde`** — biter som må finnes i den utleste teksten.
Bruk korte, robuste biter — ikke hele setninger som ryker på ett
OCR-feiltegn.

**`tekst_maa_ikke_inneholde`** — biter som IKKE skal finnes. Vokter mot
at OCR dikter innhold (målt: en nesten tom side ga to «leste» linjer som
ikke sto på papiret).

**`kjent_svakhet`** — feil vi VET om, men ikke har fikset. De felles
ikke kjøringen; de skrives ut til slutt. Dette er med vilje: et korpus
som later som alt er bra, er verdiløst. Når en svakhet fikses, flyttes
den opp i `felter` som en vanlig sjekk.

**`maks_sekunder`** rapporteres, men feller ikke kjøringen:
analysecachen svarer på millisekunder når samme fil er kjørt før, og en
grense som «består» fordi svaret kom fra cache måler ingenting. Ytelse
måles mot en fersk server, korpuset er til for riktighet.

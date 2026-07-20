# Regresjonskorpus

Ekte dokumenter med en fasit skrevet av et menneske. Kjøres med:

```
python skript/kjor_korpus.py                 # alle
python skript/kjor_korpus.py taxikvittering  # ett
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

## Hvordan det er delt

| Hva | Hvor | I git? |
|---|---|---|
| Fasit (`*.json`) | `tester/korpus/` | **Ja** — definisjonen av «riktig» skal ha historikk |
| Dokumentene | `data/korpus/` | **Nei** — `data/` er i .gitignore |

Dokumentene holdes utenfor kodelageret med vilje: de inneholder ekte
person- og betalingsopplysninger. Mangler en fil lokalt, hoppes den over
med beskjed i stedet for å felle kjøringen.

## Legge til et dokument

1. Legg filen i `data/korpus/`.
2. Lag `tester/korpus/<samme-navn>.json`.
3. **Les fasiten av ORIGINALEN med egne øyne** — ikke av hva systemet
   svarer. Skriver du ned det systemet allerede gjør, tester du bare at
   det fortsetter å gjøre det samme, også når det er feil.
4. Kjør `python skript/kjor_korpus.py <navn>` og se at avvikene er ekte.

## Formatet

```json
{
  "fil": "taxikvittering.pdf",
  "beskrivelse": "Hva slags dokument, og hva det er vanskelig ved det",
  "fasit_lest_av": "menneske, fra originalbildet 2026-07-20",

  "felter": {
    "kontakt.telefoner": ["97335868"],
    "belop.0.verdi": 463.0,
    "datoer.0": "12.06.2026"
  },

  "tekst_maa_inneholde": ["TOTAL", "486"],

  "kjent_svakhet": {
    "identifikatorer.organisasjonsnummer": "OCR leser NO994230964MVA som NU9H423096AMVA"
  },

  "maks_sekunder": 8
}
```

**`felter`** slås opp med punktsti i svaret fra `POST /uttrekk`.
Lister indekseres med tall (`belop.0.verdi`). Tall sammenlignes med
liten toleranse, tekst ordrett.

**`tekst_maa_inneholde`** er biter som må finnes i den utleste teksten.
Bruk korte, robuste biter — ikke hele setninger som ryker på ett
OCR-feiltegn.

**`kjent_svakhet`** er feil vi VET om, men ikke har fikset. De felles
ikke kjøringen; de skrives ut til slutt. Dette er med vilje: et korpus
som later som alt er bra, er verdiløst. Når en svakhet fikses, flyttes
den opp i `felter` som en vanlig sjekk — se `soknad_handskrift.json`,
der beløpsfeilen ble flyttet da R60 rettet den.

**`maks_sekunder`** rapporteres, men feller ikke kjøringen:
analysecachen svarer på millisekunder når samme fil er kjørt før, og en
grense som «består» fordi svaret kom fra cache måler ingenting. Ytelse
måles mot en fersk server, korpuset er til for riktighet.

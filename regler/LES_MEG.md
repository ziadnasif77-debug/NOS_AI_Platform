# regler/ — alt som styrer hva systemet svarer

Skal du legge til en regel eller en prompt, skjer det HER. Ingen andre
steder. Filene i tabellen under leses på nytt så snart du lagrer —
**ingen omstart av serveren**.

| Fil | Hva den styrer | Hvem endrer den |
|-----|----------------|-----------------|
| [`prompter.md`](prompter.md) | All tekst som sendes til språkmodellen | Utvikler (går i git) |
| [`lover.md`](lover.md) | Hvilke lover vi slår opp i, og hvordan de skilles | Utvikler (går i git) |
| [`egne_regler.txt`](egne_regler.txt) | Stil og form på svarene fra `/spor` | Dere selv, når som helst |
| [`egne_etiketter.txt`](egne_etiketter.txt) | Nye ord foran datoer i nye dokumenttyper | Dere selv, når som helst |
| [`dokumenttype_forventninger.txt`](dokumenttype_forventninger.txt) | Hvilke felter en dokumenttype SKAL ha (`klassifiser` melder `mangler`) — og premisset for mellombåndet i gjennomgangsrutingen (R187), se under | Dere selv, når som helst |

## Hvilken fil skal jeg i?

**«Modellen skal svare på en annen måte»** — f.eks. alltid hele
setninger, alltid valutakode, alltid nynorsk → `egne_regler.txt`.
Én regel per linje, `#` foran betyr kommentar. Virker ved neste
forespørsel.

**«Modellen bommer på en type dokument»** — den tar med feil, hopper
over noe, eller misforstår en instruks → `prompter.md`. Finn blokka som
gjelder (`spor.dokumentsporsmal` for spørsmål om dokumenter,
`fyll_skjema.mal` for utfylling av JSON-maler, `korriger.*` for
OCR-retting), legg til en linje, og øk `versjon` nederst i fila.

**«Dokumentet bruker et ord vi ikke kjenner foran datoen»** — f.eks.
«hentedato» → `egne_etiketter.txt`, én linje: `hentedato = hentedato`.

**«En dokumenttype skal alltid ha visse felter»** — f.eks. «en faktura
uten beløp er defekt» → `dokumenttype_forventninger.txt`, én linje:
`faktura = belop, dato, organisasjonsnummer`. `klassifiser`-operasjonen
melder da `mangler` for felter som ikke ble funnet. **Vær klar over
dobbeltrollen (R187):** den samme tabellen er BEVISET mellombåndet i
gjennomgangsrutingen bruker for å holde lavkonfidens-dokumenter unna
menneskelig gjennomgang (når `GJENNOMGANG_NEDRE` er senket). Snevrer
du en type inn til lette felter (f.eks. `brev = dato`), frikjenner du
i praksis nesten alle slike dokumenter fra gjennomgang — endringer her
bør derfor ses i sammenheng med båndet, ikke bare med rapporten.

**«Vi skal slå opp i en lov til»** → `lover.md`. Hent teksten med
`skript/hent_lovtekst.py`, legg til en blokk i registeret. Merk at
folketrygdlovene av 1966 og 1997 bruker de SAMME paragrafnumrene om
ULIKE ting — derfor svarer `delt/lover.py` «flertydig» på en referanse
uten lov i stedet for å velge.

**«Svaret må GARANTERT være riktig»** — da holder ikke en prompt. En
språkmodell følger en instruks nesten alltid, og «nesten» er ikke godt
nok for et tall i et vedtak. Slikt håndheves av kode, og står som
**KODE** i [`../docs/regler_lokal_api.md`](../docs/regler_lokal_api.md).
Tallvakten (R3) er eksempelet: modellen blir bedt om å gjengi tall
ordrett, OG koden sjekker etterpå at hvert tall i svaret faktisk står i
dokumentet.

## Stilregler uten å røre fila — og A/B-test av prompten (R251)

Trenger du en stilregel for ÉN forespørsel (eller vil styre den fra
UiPath uten å redigere filer på serveren), send multipart-feltet
`stilregler` til `POST /spor` eller `POST /dokument` — én regel per
linje, samme konvensjon og NØYAKTIG samme filter og tak som
`egne_regler.txt`. Forskjellen er at avviste linjer RAPPORTERES i
svaret (`stilregler_avvist`, med grunn) i stedet for bare å logges.
Reglene legges etter filreglene og før kjernereglene — kjernereglene
har fortsatt siste ord.

Vil du måle en promptendring i stedet for å synse: rediger B-blokka
`spor.dokumentsporsmal_b` i [`prompter.md`](prompter.md) (den starter
som en kopi av standardblokka), øk `versjon`, og kjør

```bash
.pyruntime\python.exe skript\kjor_sporsmaalskorpus.py --promptvariant a
.pyruntime\python.exe skript\kjor_sporsmaalskorpus.py --promptvariant b
```

— samme korpus, samme fasit, to tall som kan sammenlignes. Hvert svar
deklarerer hvilken variant som svarte (`promptvariant` i svaret), så to
kjøringer aldri kan forveksles. Ankrene «Dokument:» og «Spørsmål:» må
stå ordrett i begge blokkene (klippepunkter — `tester/test_stilregler.py`
vokter dem).

## Rekkefølgen når et svar blir til

1. `egne_regler.txt` legges inn i prompten FØRST (stil og form).
2. Kjernereglene fra `prompter.md` legges inn ETTER — språkmodeller
   vekter det som står sist tyngst, så kjernereglene får siste ord
   uansett hva som står i `egne_regler.txt` (R8.1).
3. Koden avviser på forhånd linjer i `egne_regler.txt` som prøver å
   oppheve kjernereglene eller be om utregning — de logges som
   `egne_regler: AVVIST (R8.1)`. **Dette er skadebegrensning, ikke en
   garanti:** avvisningen kjenner igjen kjente formuleringer, og en
   formulering den ikke kjenner slipper forbi. Det følger av formen —
   en blokkeringsliste kan ikke gjøres komplett. Målt: før filteret ble
   utvidet slapp seks av åtte angrepslinjer gjennom, blant dem
   engelske og nynorske varianter (R168). **Skrivetilgang til
   `regler/` er derfor sikkerhetsfølsomt** — den som kan endre disse
   filene, kan påvirke hvert eneste svar serveren gir.
4. Etter at modellen har svart, kjører KODE-vaktene: tallvakt,
   eksklusjonsvakt, skjemavalidering. De kan overprøve modellen.

Kort sagt: prompten styrer, koden garanterer.

## Etter en endring

`egne_regler.txt`, `egne_etiketter.txt` og
`dokumenttype_forventninger.txt` krever ingenting — de virker med én
gang. Endrer du `prompter.md`, gjør dette:

```bash
.pyruntime\python.exe -m pytest tester/test_prompter_samlet.py -q
```

Den sjekker at alle blokker finnes, at ingen plassholder står ufylt, at
klippingen mot kontekstvinduet fortsatt treffer riktig sted, og at
ingen har limt prompttekst tilbake inn i Python-koden.

## Hvorfor alt ligger her

Promptene lå spredt på seks steder i `dokument_api.py`, pluss en egen,
eldre kopi i `spor_pdf.py`. Kopien hadde sakket akterut — den manglet
både tallregelen og sideregelen, så samme dokument kunne få ulikt svar
avhengig av hvilken vei det gikk. Å endre én regel betydde å lete
gjennom tusenvis av kodelinjer, og `docs/regler_lokal_api.md` kunne si
noe annet enn det modellen faktisk fikk.

Nå er det ett sted å lete, ett sted å endre, og en test som sier ifra
hvis noen sprer dem igjen.

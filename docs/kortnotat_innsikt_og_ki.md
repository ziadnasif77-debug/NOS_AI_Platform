# Kortnotat til Innsikt og KI

**Til:** Kjetil Åmdal-Sævik, Innsikt og KI
**Fra:** RPA-teamet, NAV Økonomi Stønad
**Dato:** 20. august 2026
**Vedlegg:** [Business case — KI-basert dokumentbehandling](business_case_ki_dokumentbehandling.md) · [Datagrunnlag vi mangler](datagrunnlag_business_case.md)

---

## Hva dette er

Vi har siden juni 2026 prøvd ut KI for dokumentbehandling i Økonomi Stønad
gjennom å bygge en fungerende løsning, ikke en skisse. Dette notatet er
kortversjonen; business caset i vedlegget er førsteutkastet vi ønsker
innspill på.

Vi vil være tydelige på én ting med en gang: **vi har en løsning som virker,
og vi mangler tallene som avgjør om den er verdt å satse på.** Det er derfor
vi ber om hjelp nå, og ikke etter at vi har regnet oss frem til en gevinst
vi ikke kan belegge.

## Hva som faktisk finnes i dag

En frittstående dokumenttjeneste som kjører **lokalt på én maskin med GPU,
uten sky og uten internett**. Den leser et dokument én gang, svarer, og
lagrer ingenting.

Den kan i dag, verifisert med tester og målinger:

- lese trykt tekst, skannede sider og **håndskrift** (Nasjonalbibliotekets
  norhand-modell)
- hente ut kontrollerte felter — beløp, datoer, fødselsnummer, kontonummer,
  KID, organisasjonsnummer — der **kun verdier som består matematisk
  kontroll slipper gjennom**
- peke ut hvert funn med side og posisjon i dokumentet, som dokumentbevis
- svare på spørsmål om dokumentet, fylle en JSON-mal, og gi en kvalitetsdom
  («god / tvilsom / avvis») før behandling
- se flere dokumenter som **én sak**: tidslinje, sammendrag og flagging av
  motsigelser mellom dokumenter
- kalles fra UiPath — flat svarform, formstabilitet håndhevet av tester,
  eget diagnoseendepunkt

Omfang: 380 commits, 245 nummererte og dokumenterte regler, over 1 700
automatiske tester, målerapporter for hvert ledd i kjeden, og et
beslutningsregister som også dokumenterer det vi prøvde og forkastet.

## Det bærende prinsippet

**Modellen foreslår — koden verifiserer.**

Av de 245 reglene er **215 håndhevet av programkode**, ikke av instruksjoner
til språkmodellen. Konkret betyr det at et tall i et modellsvar må stå
ordrett i dokumentet for å slippe gjennom, at identifikatorer valideres med
kontrollsiffer, og at spørsmål koden kan besvare eksakt rutes helt forbi
modellen — de virker også når språkmodellen er nede.

Vi bruker altså **deterministiske regler der resultatet kan bevises, og KI
der dokumentet krever tolkning**. Det er et bevisst valg, ikke en
begrensning: for NAV er etterprøvbarhet og sporbarhet en forutsetning, ikke
en luksus. Løsningen fatter ingen vedtak; den forbereder grunnlaget, og
usikre dokumenter rutes til menneske.

Alle modeller er åpne og norske (Nasjonalbibliotekets Borealis og norhand),
kjører lokalt, og tjenesten gjør ingen utgående nettverkskall i drift.

## Hva vi ikke vet — og som avgjør business caset

Dette er de ærlige hullene, og de er grunnen til at vi ikke oppgir en
gevinst i kroner:

| Ukjent | Hvorfor det avgjør alt |
|---|---|
| Årlig dokument- og sidevolum i Økonomi Stønad | Uten volum finnes ingen gevinstberegning |
| Dagens tidsbruk per dokument | Baseline for enhver tidsbesparelse |
| **Skannet andel** og **sider per dokument** | Avgjør alene om drift krever én maskin eller flere. Våre målinger viser at antakelsen betyr mer for kostnaden enn all teknisk optimalisering til sammen |
| Dagens feilrate og kostnad per dokument | Nødvendig for ROI |

I tillegg er løsningen i hovedsak validert mot **syntetiske** dokumenter.
De to gangene vi har prøvd den mot ekte dokumenter, avdekket begge feil de
syntetiske testene ikke kunne vist — og begge er rettet. Det er nettopp
derfor neste steg må være en pilot på ekte NAV-data.

## Hva vi anbefaler

**Ikke produksjonssetting.** En avgrenset, målt pilot på én til to
dokumenttyper, der dagens prosess og løsningen måles mot hverandre på det
samme utvalget, med KPI-er og suksesskriterier fastsatt **før** oppstart.
Detaljert opplegg i vedleggets kapittel 8.

## Hva vi ønsker fra Innsikt og KI

1. **Kvalitetssikring av business caset** — særlig gevinstmodellen og
   KPI-ene. Vi har bevisst latt alle tall stå som TBD fremfor å anslå dem,
   og trenger hjelp til å gjøre dem målbare på riktig måte.
2. **Hjelp til å hente baseline-tallene** i tabellen over, og til å vurdere
   hvilke kilder i NAV som kan gi dem.
3. **Råd om metode**: hvordan NAV vanligvis dokumenterer effekt av KI-tiltak,
   og hvilke krav en pilot må oppfylle for å telle som beslutningsgrunnlag.
4. **Avklaring av rammene**: personvern og behandlingsgrunnlag for pilot,
   sikkerhetskrav, og hvor en lokal GPU-server kan plasseres i NAVs miljø.

Vi stiller gjerne med en kort demonstrasjon av den kjørende løsningen i
møtet — 15 minutter på ekte skjerm sier mer enn dette notatet.

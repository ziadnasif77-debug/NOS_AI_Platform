# Business case — KI-basert dokumentbehandling i NAV Økonomi Stønad

**Status:** Førsteutkast — arbeidsdokument til kvalitetssikring med NAV Innsikt og KI
**Dato:** 20. august 2026
**Kortversjon:** [kortnotat_innsikt_og_ki.md](kortnotat_innsikt_og_ki.md)
**Datagrunnlag som mangler:** [datagrunnlag_business_case.md](datagrunnlag_business_case.md)

**Grunnlag:** Det tekniske utforskningssporet (spor 2) i konseptutredningen
«Utforskning av KI og intelligent automatisering i Nav økonomi stønad», med
den lokalt kjørende løsningen «NAV Dokument-API» og tilhørende
[prosjektjournal](prosjektjournal.md), [målerapport](fase0_beslutningsrapport.md),
[regelverk R1–R250](regler_lokal_api.md) og testsuite.

> **Om tallene i dette dokumentet:** Alle tall er enten målt i prosjektet —
> og da med måleforholdene oppgitt — eller merket **TBD** («må måles»).
> Ingen tall er anslått. Der en gevinst er en hypotese, står det at den er
> en hypotese.

---

## 1. Executive Summary

Saksbehandling i NAV Økonomi Stønad bygger i stor grad på dokumenter:
søknader med vedlegg som kontoutskrifter, fakturaer, lønnsdokumentasjon,
vedtak og klager — ofte skannet, av varierende kvalitet, og til dels
håndskrevne. Å lese disse dokumentene, finne beløp, datoer, kontonummer og
parter, kontrollere at dokumentasjonen er komplett og se flere dokumenter i
sammenheng, er i dag manuelt arbeid. Hvor mye tid dette faktisk tar i NAV,
er ikke målt, og det er den viktigste ukjente i dette dokumentet (**TBD**).

Det som foreslås, er ikke å kjøpe eller bygge noe nytt, men å **prøve ut noe
som allerede finnes og virker**: Siden juni 2026 er det, som del av
konseptutredningens tekniske utforskningsspor, bygget en frittstående
dokumenttjeneste som kjører helt lokalt på NAV-kontrollert maskinvare, uten
sky og uten internett. Tjenesten leser et dokument én gang, trekker ut tekst
(også håndskrift), henter ut kontrollerte felter, svarer på spørsmål, fyller
ut maler og kan se flere dokumenter i sammenheng som én sak — og lagrer
ingenting. Den er bygget for robotisert bruk (UiPath) fra første dag.

KI er relevant fordi en vesentlig del av dokumentene ikke kan leses maskinelt
med regler alene: skannede sider krever tekstgjenkjenning, håndskrift krever
en egen håndskriftmodell, og frie spørsmål («hva er totalbeløpet?») krever
språkforståelse. Løsningen bruker utelukkende åpne, norske modeller
(Nasjonalbibliotekets Borealis og norhand) som kjører lokalt — ingen data
forlater maskinen.

Det bærende prinsippet skiller denne løsningen fra generell «KI-tekst»:
**modellen foreslår — koden verifiserer.** Alt som kan garanteres matematisk
eller regelbasert (fødselsnummer, kontonummer, beløp, datoer, sidetall),
garanteres av programkode, ikke av KI-modellen. Av prosjektets 245
dokumenterte regler er 215 håndhevet av kode.

Den potensielle gevinsten er redusert manuell lesetid, raskere
saksbehandling, bedre sporbarhet og færre oversette opplysninger. **Ingen av
disse gevinstene er dokumentert i NAV-kontekst ennå**, og dette dokumentet
presenterer dem derfor som hypoteser, ikke fakta. Anbefalingen er ikke
produksjonssetting, men en kontrollert, målt pilot som sammenligner dagens
prosess med løsningen på ekte NAV-dokumenter — slik at en eventuell videre
satsing bygger på tall, ikke antakelser.

---

## 2. Bakgrunn og dagens situasjon

### 2.1 Problemet

Behandling av økonomisk stønad krever dokumentasjon fra søker. Dokumentene
kommer i mange former: PDF med tekstlag, skannede papirdokumenter, mobilfoto,
og håndskrevne skjema. Saksbehandleren må i dag typisk:

- åpne og lese hvert dokument manuelt
- finne konkrete opplysninger (beløp, datoer, kontonummer, parter, perioder)
- vurdere om dokumentasjonen er komplett for dokumenttypen
- sammenholde opplysninger på tvers av flere dokumenter i samme sak
- oppdage motsigelser (ulike beløp for samme post, umulige datorekkefølger)

**Følgende må valideres med faktiske NAV-data (alle TBD):** hvor mange
dokumenter og sider som behandles per år, hvor stor andel som er skannet
kontra digitalt født, gjennomsnittlig sidetall per dokument, hvor mye tid som
brukes per dokument i dag, dagens feilrate, og hvilke dokumenttyper som er
hyppigst. Prosjektets egen målerapport er eksplisitt på at to av disse —
skannet andel og sider per dokument — betyr mer for dimensjonering og gevinst
enn alt annet til sammen.

### 2.2 Hva som er bygget

Utforskningssporet har siden juni 2026 produsert en kjørende tjeneste, ikke
et konsept:

- Én lokal dokumenttjeneste (HTTP-API) som kjører på én Windows-maskin med
  GPU, i én mappe, uten eksterne avhengigheter, og som fungerer helt uten
  internett etter installasjon.
- 380 commits, et regelverk med 245 nummererte og dokumenterte regler
  (R1–R250) der hver regel angir om den håndheves av kode eller av prompt,
  over 1 700 automatiske tester, et ADR-register over bevisste veivalg (også
  det som ble prøvd og forkastet), og en løpende prosjektjournal slik
  konseptutredningens kapittel 8 krever.
- Målte ytelsesrapporter (Phase 0/1) der hvert ledd i kjeden er målt, ikke
  anslått — inkludert kjøringer på 500 og 1 000 sider med dokumentert full
  dekning og null stille avkorting.

**Viktig ærlighetspunkt:** tjenesten er en **utprøvingsplattform, ikke et
produksjonssystem**. API-et er ikke utgitt til noen klient, alle ytelsestall
er målt på én utviklermaskin (RTX 3070 med 8 GB GPU-minne), og testkorpuset
består med hensikt av syntetiske dokumenter (ekte dokumenter ville lekket
personopplysninger inn i kodehistorikken). To manuelle valideringer mot ekte
dokumenter er gjennomført — begge avdekket feil de syntetiske testene ikke
kunne vist, og begge førte til rettelser. Det understreker hvorfor en pilot
på ekte data er neste nødvendige steg.

---

## 3. Problem / Opportunity

Den forretningsmessige muligheten ligger i at dokumentlesing er en repetitiv,
tidkrevende og feilutsatt del av saksbehandlingen som kan forberedes
maskinelt, mens vurdering og vedtak forblir hos mennesket:

- **Tidsbruk:** Første gjennomlesing og uthenting av nøkkelopplysninger kan
  gjøres maskinelt på sekunder (målt 25.08.2026 på utviklermaskinen: 0,9
  sekunder for et tisiders dokument med tekstlag; 2,2–3,2 sekunder per side
  for skannede dokumenter — den høye enden når språkmodellen deler GPU-en
  med OCR, som er driftstilstanden på én maskin med 8 GB).
  Dagens manuelle tid per dokument er **TBD**.
- **Kapasitet:** Maskinell forbehandling frigjør saksbehandlertid til
  vurdering. Effekten avhenger av volum og dagens tidsbruk (**TBD**).
- **Kvalitet:** Kodevalidering fanger opplysninger som er lette å overse
  eller taste feil manuelt: alle fødselsnummer og kontonummer i et dokument
  valideres matematisk, alle beviste funn kan pekes ut med posisjon i
  dokumentet, og motsigelser mellom dokumenter i samme sak flagges automatisk.
- **Skalerbarhet:** En maskinell prosess skalerer med maskinvare, ikke med
  bemanning. Skaleringsbehovet er i dag ukjent fordi volumtallene er ukjente
  (**TBD**).
- **Sporbarhet:** Hvert svar stemples med hvilke versjoner (API, regler,
  prompt, modell) som produserte det, og hvert felt kan spores til metode,
  konfidens og side i dokumentet. Det er en kvalitet dagens manuelle prosess
  ikke har på samme form.

Muligheten er altså ikke «KI erstatter saksbehandling», men **maskinell
dokumentforberedelse med dokumenterbar kontroll** — der beslutninger forblir
menneskelige.

---

## 4. Foreslått løsning

### 4.1 Forretningsmessig nivå

Løsningen er en lokal dokumenttjeneste som saksbehandlingsprosessen (manuelt,
via en GUI, eller automatisert via UiPath-roboter) kan sende et dokument til
og få tilbake:

- hele teksten, også fra skannede og håndskrevne dokumenter
- kontrollerte nøkkelfelter (beløp, datoer, fødselsnummer, kontonummer, KID,
  organisasjonsnummer) — kun verdier som består matematisk validering
- svar på konkrete spørsmål om dokumentet
- en utfylt mal med feltene prosessen trenger
- en kvalitetsdom før behandling («god / tvilsom / avvis») så dårlige
  skanninger fanges tidlig
- flere dokumenter sett i sammenheng som én sak, med tidslinje, sammendrag og
  flaggede motsigelser

Ingenting lagres: dokumentet leses, besvares og forkastes. Kildedokumentene er
allerede arkivert i NAVs systemer, og tjenesten er bevisst bygget uten arkiv,
database og søkeindeks.

### 4.2 Teknisk nivå — de viktigste mekanismene

**«Modellen foreslår — koden verifiserer.»** Dette er løsningens bærende
prinsipp, og det er dokumentert regel for regel: av 245 regler i regelverket
er 215 håndhevet av programkode; kun 11 er rene instrukser til
språkmodellen, og for hver av disse som betyr noe, står det en kodevakt bak.
Konkret:

- **Tallvakt:** Ethvert tall i et modellsvar må stå ordrett i dokumentet,
  ellers holdes svaret tilbake. Modellen kan altså ikke dikte opp et beløp.
  (Kjent og dokumentert grense: vakten garanterer at tall ikke er
  *oppdiktet*, ikke at de er *relevante* for spørsmålet — derfor består
  menneskelig kontroll.)
- **Matematisk validering:** Fødselsnummer, kontonummer og
  organisasjonsnummer valideres med kontrollsiffer (mod11), KID med
  mod10/mod11, og fødselsnummer i tillegg mot en datoport (kontrollsifrene
  kan stemme ved uflaks i sammenlimte OCR-linjer; en umulig fødselsdato
  avslører det). Prinsippet er «et nummer vi ikke kan bevise, finnes ikke».
- **Koden svarer der koden vet:** Spørsmål om sidetall, strekkoder og
  sjekksumvaliderte identifikatorer rutes deterministisk forbi modellen.
  Disse svarene virker også når språkmodellen er nede, og svaret oppgir alltid
  hvilken vei som ble tatt.
- **Deterministiske regler der informasjon kan verifiseres; KI der dokumentet
  krever tolkning.** OCR-tekst, feltuttrekk, datonormalisering,
  dokumenttype-forventninger, saksgruppering, tidslinje og sakssammendrag er
  ren kode. Språkmodellen (Borealis 4B) brukes bare til det som krever
  semantikk: frie spørsmål, sammendrag, OCR-korrigering og utfylling av
  felter koden ikke kan bevise. Begrunnelsen er dokumentert erfaring: en
  språkmodell formulerer alltid et svar, også når den tar feil — garantier må
  derfor ligge i kode.
- **Målt determinisme:** Samme dokument gir samme svar hver gang. Dette er
  ikke en påstand, men en port som kjøres: ti kjøringer på fire ulike
  svarveier, alle identiske — og en 500-siders jobb lest med én og med seks
  tråder ga bit for bit identisk tekst (samme sha256). Porten har selv
  avdekket og rettet to reelle determinismebrudd.
- **Åpne, norske, lokale modeller:** EasyOCR/RapidOCR (trykt tekst), norhand
  v3 (Nasjonalbibliotekets håndskriftmodell — den eneste modellen som
  finjusteres videre), Borealis 4B (Nasjonalbibliotekets norske språkmodell)
  og Doc-UFCN (linjesegmentering). Alt kjører offline; tjenesten gjør ingen
  utgående nettverkskall i drift.

---

## 5. Hva løsningen kan gjøre

### A. Implementert (finnes i kode, dekket av tester)

| Funksjon | Beskrivelse |
|---|---|
| OCR, trykt tekst | EasyOCR på GPU / RapidOCR på CPU, adaptivt motorvalg etter ledig GPU-minne; motorvalget fryses per dokument så side 1 og side 150 leses likt |
| Håndskrift | Regionbasert: usikre regioner leses i tillegg av norhand (TrOCR), med Doc-UFCN-andrepass, arbitrering («aldri ødelegge korrekt lest tekst») og eget håndskrift-felt i svaret |
| Tekstuttrekk | Hele teksten, deterministisk, med sidemarkører og dokumentert null stille avkorting (verifisert på 500- og 1 000-siders jobber) |
| Strukturelt uttrekk og feltuttrekk | Komplett dokumentprofil; felter med én felles datogrammatikk (alt normaliseres til ISO 8601) |
| Validering av identifikatorer og tall | mod11 (fnr/konto/orgnr), mod10/mod11 (KID), datoport på fnr, beløpsnormalisering, etikettkrav for merkede felter |
| Koordinater / dokumentbevis | Hvert bevist funn med boks og side i et deklarert koordinatrom — en GUI kan utheve funnet, og saksbehandleren slipper å lete |
| Spørsmål mot dokument | Fritt spørsmål med tallvakt og bevisvalg (målt: bedre treff med 24 % mindre kontekst); kodesvar der koden vet |
| Skjemautfylling | Fyller brukerens **JSON-mal** (ikke PDF-skjema) med tre motorer: deterministisk, modell, eller hybrid der bare ubeviste felter går til modellen; strukturlås, tallvakt per felt og aritmetisk konsistenskontroll |
| Kvalitetskontroll av dokumenter | Forhåndssjekk uten GPU: dom «god / tvilsom / avvis» på skarphet, lys, oppløsning og tomme sider — før ressurser brukes |
| Sladding | Sladder det som kan bevises (fnr, konto, orgnr, KID, telefon, e-post); deklarerer eksplisitt at navn og adresser ikke dekkes |
| Saksnivå (nytt, aug. 2026) | Flere dokumenter som én sak: gruppering på saksnummer (aldri på fødselsnummer — det beviser samme person, ikke samme sak), tidslinje, motsigelsesdeteksjon, sakssammendrag i ren kode, proveniens på saksnivå, spørsmål om saken med koden først |
| Sporbarhet | Versjonsstempel (API/prompt/modell) på hvert svar, proveniens per felt (metode, konfidens, side), tilgangslogg med lukket feltsett (aldri innhold), korrelasjons-ID, måleendepunkt |
| Modellversjonering og modellbytte | Modellbytte kun gjennom en port som måler før/etter med statistisk test og ruller tilbake automatisk; forrige modell slettes aldri automatisk; vektfil-avtrykk varsler uventede endringer |
| API-integrasjon (UiPath/RPA) | Flat svarstruktur, formstabilitet håndhevet av tester, diagnoseendepunkt, presise feilmeldinger for kjente .NET-/UiPath-feller, idempotensnøkler, API-nøkler med klientidentitet, rate-limiting |
| Batch/bakgrunnsbehandling | Jobb-endepunkt for store skanninger (jobb-ID, fremdrift, eierkontroll), direktevisning med hendelsesstrøm, reservert kapasitet for interaktive forespørsler (målt: interaktiv median 6 ms under batch-last) |
| Trenings- og forbedringssløyfe | Dårlige lesinger sendes automatisk til Label Studio for menneskelig korreksjon (av som standard, krever eksplisitt aktivering); korreksjoner finjusterer håndskriftmodellen; kvalitetsport (tegnfeilrate med konfidensintervall) avgjør promotering; rull-tilbake finnes; GDPR-sletteverktøy for korreksjonsarkivet |
| Drift | Vakthund med exitkode-diagnose, enkeltinstansvern, offline-installasjon med kontrollsummer, portabilitetsvakt (alt i én mappe), feilbok for drift uten utvikler |

### B. Delvis implementert / kjente begrensninger

- **Tabellrekonstruksjon:** virker for PDF med tekstlag; OCR-veien er ikke
  koblet på, og høyrejusterte tabellkolonner (typisk i kontoutskrifter:
  skille «inn på konto» fra «ut av konto») er et kjent, uløst problem —
  dokumentert mot et ekte dokument.
- **Modellens lesekvalitet har et målt tak:** 129 av 133 spørsmål i
  testkorpuset besvares riktig; de fire siste er diagnostisert som
  leseforståelsesgrenser hos en 4-milliarder-parameters modell på 8 GB GPU.
  Større GPU og modell er den dokumenterte veien videre.
- **Kalibrering av konfidensterskler:** mekanismen finnes, men terskelen som
  ruter dokumenter til manuell gjennomgang (0,85) er ennå ikke kalibrert mot
  fasit; mellombåndet i gjennomgangsrutingen er bevisst avslått inntil
  kalibreringen foreligger.
- **Kvalitetsporten for håndskriftmodellen er bygget, men valideringssettet
  mangler** — uten det promoteres ingen nytrent modell automatisk (bevisst
  «trygg» tilstand).
- **Sladding dekker ikke navn og adresser** (kun det som kan bevises
  maskinelt). Full anonymisering krever mer.
- **Én maskin:** ingen horisontal skalering, køen er intern i prosessen;
  distribuert arkitektur er bevisst utsatt til reelle volumtall foreligger
  (ADR-0006).
- **Testkorpuset er lite og syntetisk;** saksnivået er foreløpig kun validert
  mot syntetiske saker.

### C. Mulig videreutvikling (ikke påbegynt, i tråd med utredningens kap. 9)

- Multimodale synsmodeller (VLM) — krever mer GPU-minne enn dagens 8 GB
- Systematisk sammenligning av flere åpne språkmodeller side om side
- Kunnskapssøk (RAG) over rutiner og rundskriv — bevisst holdt utenfor
  (krever varig indeks og egen personvernvurdering; hører i egen pilot)
- Brevutkast — bevisst ikke påbegynt: en 4B-modell kan ikke garantere
  kvaliteten et utgående brev krever
- Sammenligning av to dokumenter; agentteknologi; kommersielle KI-tjenester
  (personvernvurdering må komme først)

---

## 6. Business Value

Alle gevinster under er **hypoteser inntil de er målt i pilot**. For hver
gevinst angis hvordan den kan måles — måleinfrastrukturen (måleendepunkt,
ytelsesrigg, spørsmålskorpus med fasit, determinismeport) finnes allerede i
løsningen.

| Verdidriver | Hypotese | Slik måles den |
|---|---|---|
| Redusert behandlingstid per dokument | Maskinell førstelesing + feltuttrekk erstatter deler av manuell lesing | Tidsstudie: samme dokumentbunke behandlet med og uten løsningen; dagens tid er baseline (TBD) |
| Redusert manuelt arbeid | Saksbehandler verifiserer i stedet for å lete | Andel felter som fylles maskinelt og godkjennes uendret av mennesket |
| Økt kapasitet | Flere saker per årsverk ved samme bemanning | Dokumenter behandlet per time, før/etter, på representativt utvalg |
| Færre feil / bedre datakvalitet | Matematisk validering fanger tastefeil og OCR-feil; motsigelser flagges | Feilrate i uttrukne felter mot manuell fasit; antall flaggede motsigelser som viser seg reelle |
| Raskere saksbehandling | Kortere tid fra mottak til komplett saksbilde | Ledetid per sak i pilotgruppe mot kontrollgruppe |
| Bedre sporbarhet | Hvert felt kan spores til side, metode og versjon | Kvalitativ vurdering med fagmiljø; andel funn med proveniens |
| Bedre skalerbarhet | Kapasitet kjøpes som maskinvare, ikke bemanning | Målt sider/sekund på målmaskin (riggen finnes); kostnad per dokument |
| Grunnlag for videre automatisering | Strukturerte, validerte felter kan mate UiPath-prosesser | Antall prosess-steg som kan konsumere feltene direkte |

---

## 7. KPI-er og målemodell

Foreslåtte KPI-er for pilot. Ingen baseline-verdier oppgis her — baseline
etableres som pilotens første aktivitet.

**Effektivitet**

- Tid per dokument (manuell baseline vs. med løsning) — baseline TBD
- Dokumenter/sider behandlet per time
- Ledetid fra dokumentmottak til komplett saksbilde

**Kvalitet**

- OCR-nøyaktighet (tegnfeilrate, CER) på ekte NAV-dokumenter — måles mot
  menneskelig fasit
- Feltuttrekk-nøyaktighet (presisjon/dekning per felttype: beløp, dato, fnr,
  konto)
- Svar-nøyaktighet på et NAV-spesifikt spørsmålskorpus med fasit (metoden
  finnes; dagens syntetiske korpus: 97 %)
- Feilrate: andel maskinelle funn som underkjennes av mennesket
- Tallvakt-rate: hvor ofte modellsvar holdes tilbake av vaktene (finnes
  allerede som måltall i tjenesten)

**Automatiseringsgrad**

- Andel dokumenter som passerer uten manuell kontroll
- Andel dokumenter rutet til manuell gjennomgang, og hvor stor andel av disse
  som faktisk trengte det (kalibrering av terskelen)
- Andel spørsmål besvart deterministisk av kode kontra av modell (feltet
  finnes i hvert svar)

**Økonomi og drift**

- Kostnad per dokument (se kapittel 9)
- Behandlingstid før/etter, ende til ende
- Oppetid, feilrate i drift, andel jobber som ender i feiltilstand

**Volumtall som selve piloten skal fremskaffe**

- Skannet andel av dokumentmengden
- Sider per dokument (fordeling, ikke bare snitt)

---

## 8. Pilotforslag

**Mål:** Dokumentere målbar effekt (tid, kvalitet, automatiseringsgrad) av
løsningen på ekte NAV-dokumenter, sammenlignet med dagens manuelle prosess —
og fremskaffe volumtallene som avgjør dimensjonering og økonomi.

**Avgrensning (forslag, fastsettes med fagmiljøet):** Én eller to
dokumenttyper med antatt høyt volum og klar struktur, for eksempel
kontoutskrifter og fakturaer som vedlegg til søknad om økonomisk stønad.
Kontoutskrift er allerede delvis validert mot ett ekte eksemplar og har en
kjent, navngitt svakhet (høyrejusterte tabellkolonner) som piloten vil belyse
ærlig.

**Datasett:** Et representativt utvalg ekte dokumenter (endelig antall
fastsettes med statistisk begrunnelse), med menneskelig fasit etablert for
felter og spørsmål. Utvalget må dekke variasjonen: tekstlag, skann, foto,
håndskrift, god og dårlig kvalitet.

**Baseline og målemetode:** Først måles dagens prosess (tid per dokument,
feilrate) på utvalget. Deretter behandles samme utvalg med løsningen, med
saksbehandler i kontrollrollen. KPI-ene i kapittel 7 måles i begge løp.
Målemetoden forhåndsregistreres før piloten starter, slik at
suksesskriteriene ikke kan justeres i etterkant.

**Suksesskriterier:** Fastsettes tallfestet sammen med Innsikt og KI før
oppstart — for eksempel krav til feltnøyaktighet på kritiske felter, målbar
tidsreduksjon, og at andelen dokumenter som feilaktig passerer uten kontroll
ligger under en avtalt grense. (Bevisst ikke tallfestet her: uten baseline
ville tallene vært gjetning.)

**Sikkerhets- og personvernkrav:**

- Personvernkonsekvensvurdering (DPIA) og avklart behandlingsgrunnlag **før**
  første ekte dokument behandles
- All kjøring lokalt på NAV-kontrollert maskin; ingen skytjenester; løsningen
  gjør ingen utgående nettverkskall i drift (verifisert egenskap, ikke løfte)
- Treningsløkken (Label Studio) holdes avslått i pilotens første fase — da
  lagres ingenting; eventuell aktivering behandles som egen
  personvernbeslutning
- API-nøkkel med klientidentitet, tilgangslogg (logger aldri dokumentinnhold),
  avtalt oppbevaringstid for jobbmetadata (standard 30 dager, kan settes
  lavere)

**Evaluering:** Skriftlig rapport mot de forhåndsregistrerte KPI-ene,
inkludert det som ikke virket. Prosjektets etablerte praksis — hver feil
dokumenteres med måling og rotårsak — videreføres i piloten.

**Krav for eventuell produksjonssetting (etter pilot, egen beslutning):**
dokumentert KPI-oppnåelse, DPIA for produksjonsbruk, driftsorganisasjon med
navngitt mottaker for alarmer, dimensjonert maskinvare basert på pilotens
volumtall (målt anbefaling: GPU med minst 12 GB, helst 16 — dagens 8 GB er
den dokumenterte flaskehalsen), redundans (dagens løsning er én maskin), og
integrasjonsavklaring mot NAVs systemportefølje.

---

## 9. Økonomi

Prosjektet har bevisst ikke oppgitt kronebeløp der grunnlag mangler;
kapasitetskostnad er så langt uttrykt i målte maskintimer. Strukturen under
fylles ut i og etter pilot.

**Kostnadsstruktur**

| Post | Innhold | Beløp |
|---|---|---|
| Utviklingskostnad (påløpt) | Utforskningssporet frem til i dag | TBD |
| Videre utvikling | Pilottilpasning, NAV-spesifikt korpus, kjente svakheter (tabeller) | TBD |
| Infrastruktur (GPU/server) | Pilot: én maskin med GPU ≥ 12 GB (helst 16), målt begrunnelse foreligger; produksjon avhenger av volumtall | TBD |
| Drift | Overvåking (vakthund finnes); driftsorganisasjon må bemannes | TBD |
| Vedlikehold | Regelverk, tester, feilretting | TBD |
| Modellforvaltning | Modellbytteport og treningsløkke finnes; arbeidsinnsats per år | TBD |
| Integrasjon | UiPath-prosesser, ev. fagsystemintegrasjon | TBD |
| Testing/kvalitetssikring | Fasit-etablering på ekte dokumenter (manuelt arbeid) | TBD |
| Opplæring | Saksbehandlere og drift; feilbok og kontrollpanel finnes | TBD |
| Modell-lisenser | Åpne modeller, ingen løpende kostnad per kall; lisensvilkår må verifiseres formelt | 0 / TBD |
| Dagens manuelle behandling | Kostnad per dokument i dag — pilotens baseline | TBD |

**Formler (fylles med pilotens tall)**

- Årlig gevinst = Dokumentvolum per år × (tid per dokument før − tid per
  dokument etter) × timekostnad + verdsatt kvalitetsgevinst
- Netto årlig gevinst = Årlig gevinst − årlige drifts- og
  forvaltningskostnader
- ROI = (akkumulert netto gevinst i analyseperioden − total investering) /
  total investering × 100 %
- Tilbakebetalingstid = total investering / netto årlig gevinst
- Kostnad per dokument = (årlig driftskostnad + annualisert investering) /
  dokumentvolum per år

**Målt kapasitetsgrunnlag som allerede finnes** (utviklermaskin, 8 GB GPU):
0,32–0,45 skannede sider per sekund — den lave enden er målt 25.08.2026 med
språkmodellen boende på samme GPU (OCR faller da til CPU-motor fordi ledig
GPU-minne er under kravet), og det er driftstilstanden på én maskin. Et
tisiders tekstlagsdokument tar 0,9 sekunder. Under konseptutredningens
*antatte* belastning (250 000 sider/dag, 50 % skannet) ville dagens
maskintype kreve om lag 15–21 maskiner i topplast — men ved 10 % skannet
andel om lag 3–5, og ved 20 sider per dokument holder én. Dette illustrerer
hvorfor volumtallene må måles før noe kjøpes: antakelsen avgjør mer enn
optimaliseringen. Det peker også på samme sted som kapittel 12: neste
maskinvaresteg er mer GPU-minne (så OCR og språkmodell ikke konkurrerer),
ikke flere maskiner. Kilde: `data/ytelsesmaalinger/20260825-083622.json`.

---

## 10. Risiko

| Risiko | Vurdering | Eksisterende kontrollmekanismer |
|---|---|---|
| Feilaktig OCR | Reell, særlig ved dårlig skannkvalitet og håndskrift | Forhåndssjekk avviser/flagger dårlige skann før behandling; konfidensmåling per region; dårlige lesinger kan rutes til menneskelig korreksjon; delvis lesing merkes alltid eksplisitt |
| Feilaktig modellrespons | Reell og dokumentert: modellen kan hente feil opplysning fra riktig side (fire kjente tilfeller i korpuset) | Tallvakt, eksklusjons- og feltvakter, personbinding (svar om feil person holdes tilbake), kodesvar der koden vet, kilde-felt i hvert svar |
| Hallusinasjon | Begrenset for tall (tallvakt); dokumentert restrisiko: et ekte, men irrelevant tall kan passere | Menneskelig kontroll består; begrensningen er skriftlig dokumentert, ikke skjult |
| Personvern | Håndterbar: lokal kjøring, ingenting lagres som standard | Ingen utgående nettverkskall; sladdefunksjon (med deklarerte grenser); tilgangslogg uten innhold; 30 dagers oppbevaring av jobbmetadata; GDPR-sletteverktøy; DPIA kreves før pilot |
| Informasjonssikkerhet | Håndterbar, men må gjennomgås mot NAVs krav | API-nøkler med klientidentitet, rate-limiting, CORS lukket, nøkkelrotasjon, eierkontroll på jobber og saker, generiske feilmeldinger utad; sikkerhetskontrollene er testdekket |
| Modellendringer | Kontrollert | Modellbytte kun gjennom måleport med statistisk dom og automatisk rull-tilbake; forrige modell bevares alltid |
| Avhengighet av modeller | Lav for kjernefunksjoner | Deterministisk vei ved siden av modellen: tekst, felter, validering og hele saksnivået virker når språkmodellen er nede |
| Driftsstabilitet | Kjent svakhet: én maskin (ingen redundans) | Vakthund med automatisk omstart og exitkode-diagnose, enkeltinstansvern, feilbok for drift uten utvikler; redundans må bygges før produksjon |
| Integrasjon | Håndterbar | Kontrakten er formstabil og testhåndhevet; diagnoseendepunkt; kjente UiPath-feller er dokumentert og håndtert |
| Manglende datakvalitet | Reell: løsningen er i hovedsak validert syntetisk | Pilotens hovedformål; to ekte-valideringer har allerede vist at ekte dokumenter avdekker feil syntetiske ikke kan |
| Feil bruk av automatiserte beslutninger | Prinsipiell risiko som må styres organisatorisk | Løsningen fatter ingen vedtak og er bygget som beslutningsstøtte; usikre dokumenter rutes til menneske; grensen må forankres i rutine og opplæring |

---

## 11. Governance og kontroll

- **Sporbarhet:** Hvert svar stemples med versjon av API, prompt-regelverk og
  modell. Hvert felt bærer proveniens: metode (sjekksum/etikett/posisjon/
  modell m.fl.), konfidensnivå og side. Tilgangsloggen har et lukket,
  testhåndhevet feltsett som aldri inneholder dokumentinnhold.
- **Modellversjoner:** Modellfiler identifiseres ved navn og avtrykk; bytte
  skjer kun gjennom måleporten; forrige modell bevares for umiddelbar
  rull-tilbake.
- **Regelversjoner:** All prompttekst ligger i én versjonert regelfil (ikke i
  kode, håndhevet av test); regelverket R1–R250 dokumenterer per regel om den
  garanteres av kode eller styres av prompt.
- **Validering og kvalitetssikring:** Over 1 700 automatiske tester,
  determinismeport, spørsmålskorpus med menneskelig fasit, kvalitetsport med
  konfidensintervall for nytrente modeller, og et ADR-register som
  dokumenterer også det som ble valgt bort.
- **Logging:** Tilgangslogg med rotasjon, jobblogger, vakthundlogg med
  exitkoder, måleendepunkt for drift.
- **Human-in-the-loop:** Usikre lesinger rutes til menneskelig korreksjon;
  korreksjoner forbedrer håndskriftmodellen kun via kvalitetsporten;
  saksbehandler beslutter alltid.
- **Rollback:** Både språkmodell og håndskriftmodell har bevart forrige
  versjon og dokumentert rull-tilbake-prosedyre.
- **Tilgangskontroll:** API-nøkler per klient, eierkontroll på jobber, innsyn
  og saker (fremmed ID gir «finnes ikke», ikke bekreftelse).
- **Datalagring:** Ingenting lagres som standard; jobb- og saksmetadata
  (aldri dokumenttekst) har definert oppbevaringstid; treningsdata krever
  eksplisitt aktivering og har GDPR-sletteverktøy.
- **Offline-drift:** Hele løsningen kjører uten internett, kan installeres
  offline med kontrollsumverifisering, og en portabilitetsvakt sikrer at
  ingenting lekker ut av installasjonsmappen.

---

## 12. Skaleringspotensial

**Verdi i dagens pilot:** avgrenset til én–to dokumenttyper i NAV Økonomi
Stønad, med mål om dokumentert effekt og reelle volumtall. Gevinsten her er
primært redusert lesetid og bedre kontroll i én prosess — pluss
beslutningsgrunnlaget selv.

**Mulig verdi ved videre skalering (betinget av pilotresultat):**

- **Flere dokumenttyper:** Nye dokumenttyper og felter kan legges til via
  regelfiler uten kodeendring (dokumenttype-forventninger, egne etiketter,
  egne regler leses live). Dokumenttyper med tabellstruktur krever
  utviklingsarbeid som er kjent og navngitt.
- **Flere prosesser:** Journalens dekningskart mot utredningens kapittel 9
  viser hvor: saksbehandlingsstøtte (spørsmål, sammendrag, mangelkontroll) er
  delvis på plass; brevutkast, dokumentsammenligning og kunnskapssøk er
  bevisst ikke påbegynt og ville kreve egne beslutninger.
- **Volumskalering:** Dagens løsning er én maskin uten horisontal skalering —
  et bevisst valg inntil volumtall foreligger. Målingene viser at skalering
  primært er et OCR-kapasitetsspørsmål (OCR bruker 96 % av tiden på skannede
  dokumenter; språkmodellen er ikke flaskehalsen), og at riktig neste
  maskinvaresteg er et GPU-kort på minst 12 GB, ikke flere maskiner av dagens
  type.

---

## 13. Anbefaling

Det anbefales **ikke** å implementere løsningen i produksjon nå. Det
anbefales en kontrollert pilot i tre steg:

1. **Mål de to ukjente først (billigst, størst beslutningsverdi):** skannet
   andel og sider per dokument på ekte dokumentstrøm i Økonomi Stønad. Disse
   to tallene avgjør alene om fremtidig drift krever én maskin eller en
   klynge, og dermed størstedelen av kostnadsbildet. Måleriggen finnes og kan
   kjøres på en målmaskin.
2. **Etabler formelt samarbeid med Innsikt og KI og personvernmiljøet:**
   kvalitetssikre dette business caset, gjennomfør DPIA og avklar
   behandlingsgrunnlag før første ekte dokument behandles.
3. **Gjennomfør piloten i kapittel 8** med forhåndsregistrerte KPI-er, målt
   baseline og skriftlig evaluering — inkludert det som ikke virker.
   Beslutning om videre skalering tas på pilotens tall, ikke før.

Prosjektets egen historikk er det beste argumentet for denne rekkefølgen:
flere ganger har en måling snudd en konklusjon som virket opplagt
(GPU-trimming, kvantisering, parallellisering). Å måle før man beslutter har
hver gang vært billigere enn å bygge på en antakelse.

---

## 14. Åpne spørsmål / informasjon vi mangler fra NAV

Detaljert liste med foreslåtte kilder: [datagrunnlag_business_case.md](datagrunnlag_business_case.md).

**Volum og baseline**

- Årlig dokumentvolum og antall sider i Økonomi Stønad
- Skannet andel av dokumentmengden og fordeling av sider per dokument
- Dagens behandlingstid per dokument og per sak
- Antall årsverk/timer brukt på dokumenthåndtering i dag
- Dagens feilrate og dagens kostnad per dokument

**Prosess og prioritering**

- Hvilke dokumenttyper som er mest relevante og hyppigst
- Hvilke prosesser som har størst gevinstpotensial, og hvor UiPath allerede er
  i bruk
- Verifiserte kodeverk: NAVs temakoder for ytelser og blankettnummer→ytelse
  (prosjektets liste er bevisst tom i påvente av verifiserte verdier)

**Krav og rammer**

- NAVs krav til sikkerhet, personvern, logging og arkivering; behandlings-
  grunnlag for pilot
- Om og hvor en lokal GPU-server kan plasseres i NAVs miljø
- Krav til redundans og driftsorganisasjon, inkludert navngitt mottaker for
  driftsalarmer
- Formell verifisering av lisensvilkår for modellene

**Data til validering**

- Tilgang til et representativt utvalg ekte dokumenter med mulighet for å
  etablere menneskelig fasit
- Eksisterende systemintegrasjoner løsningen må forholde seg til ved en senere
  produksjonsvurdering

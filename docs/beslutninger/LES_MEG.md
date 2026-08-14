# Beslutninger og arkitekturgjeld (ADR-register)

Her står valgene som er tatt, hvorfor de ble tatt, og hva de koster.

## Hvorfor dette finnes

Prosjektet har hatt et sterkt regelverk for *hva som er galt i koden*
([regler_lokal_api.md](../regler_lokal_api.md), R1→). Det har ikke hatt
noe sted for *hva vi bevisst har valgt bort*. Forskjellen er ikke
akademisk:

- «RAG er ikke bygget» ser ut som en mangel. **«RAG er bevisst utelatt,
  fordi det krever en varig indeks og hele personvernhistorien vår er at
  ingenting lagres»** er en beslutning — og den kan etterprøves,
  utfordres og omgjøres av noen andre enn den som tok den.
- Uten registeret bor slike valg i hodet til én person, eller i en
  kommentar ingen finner. Det er nettopp den kunnskapen som forsvinner
  når noen slutter.

Konseptutredningen krever dette eksplisitt (§29: *«Architectural Debt is
tracked explicitly. Midlertidige løsninger er tillatt bare når årsaken,
risikoen og tidspunktet for ny vurdering er kjent og registrert»*).

## Reglene

1. **Én fil per beslutning**, navngitt `ADR-NNNN-kort-tittel.md`.
2. **Malen i [MAL.md](MAL.md) er obligatorisk.** Alle felter fylles ut.
   Står et felt tomt, er beslutningen ikke tatt ennå.
3. **«Vi gjør det senere» er ikke en begrunnelse.** En midlertidig
   løsning uten *review trigger* er ikke tillatt (§29).
4. **Review trigger skal være MÅLBAR** når det er mulig: køalder,
   sider/sekund, latens, antall integrasjoner, VRAM — ikke «når vi får
   tid».
5. **Sikkerhets- og personverngjeld** godtas ikke som vanlig teknisk
   gjeld uten en eksplisitt risikovurdering.
6. En post **lukkes først** når exit-strategien er gjennomført.

## Forholdet til R-loggen

De to utfyller hverandre, og blandes ikke:

| | [regler_lokal_api.md](../regler_lokal_api.md) | Dette registeret |
|---|---|---|
| Svarer på | Hva var GALT, og hva håndhever at det ikke skjer igjen | Hva VALGTE vi, og hva koster valget |
| Utløses av | En feil som ble funnet og rettet | Et veiskille der flere veier var mulige |
| Lukkes | Aldri — den er en historikk | Når exit-strategien er gjennomført |

## Registeret

| ADR | Beslutning | Status | Review-trigger |
|---|---|---|---|
| [0001](ADR-0001-ingen-rag-i-dokumentmotoren.md) | RAG bygges ikke inn i dokumentmotoren | Gjeldende | Behov for søk på tvers av dokumenter |
| [0002](ADR-0002-layoutlmv3-og-vlm.md) | LayoutLMv3 fjernet; VLM utsatt til maskinvare finnes | Gjeldende | Kort med ≥16 GB VRAM tilgjengelig |
| [0003](ADR-0003-norhand-beholdes.md) | norhand beholdes framfor en generell VLM for håndskrift | Gjeldende | En VLM slår norhand målbart på norsk håndskrift |
| [0004](ADR-0004-mellombaand-av-som-standard.md) | Mellombåndet i gjennomgangsrutingen er AV som standard | Midlertidig | Kalibreringstabellen har nok data (ECE < 0,05) |
| [0005](ADR-0005-kontekst-auto-tak.md) | Maskinprofilen hever aldri konteksten over et fast tak | Gjeldende | Et krasjfritt løp på et større kort er dokumentert |
| [0006](ADR-0006-plattformlag-utsatt.md) | Kø/database/multi-node utsettes til Phase 0 er målt | Gjeldende | Målt bottleneck som lokal fan-out ikke løser |

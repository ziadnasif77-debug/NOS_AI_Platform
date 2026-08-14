# ADR-0001: RAG bygges ikke inn i dokumentmotoren

**Dato:** 2026-08-13
**Status:** Gjeldende

---

## Decision — hva er faktisk besluttet?

Retrieval-Augmented Generation (søk på tvers av dokumenter) bygges IKKE
inn i denne tjenesten. Skal Nav ha kunnskapssøk i rutiner og rundskriv,
blir det en egen pilot med egne data.

## Reason — hvilket problem eller krav utløste beslutningen?

Konseptutredningen kap. 9.4 ber om utforskning av RAG, og en fersk
arkitekturanbefaling foreslo det som en naturlig utvidelse. Vurderingen
tvang fram spørsmålet om det hører hjemme her.

## Alternatives Considered

1. **Bygge RAG inn i dokumentmotoren.** Forkastet: krever en varig
   indeks, som er det motsatte av tjenestens bærende prinsipp.
2. **Midlertidig indeks med TTL.** Forkastet: en indeks som slettes er
   fortsatt en indeks mens den lever, og personvernvurderingen blir den
   samme — bare vanskeligere å forklare.
3. **Egen pilot med egne data (valgt).** Rutiner og rundskriv er ikke
   borgerdokumenter, og har en helt annen personvernprofil.

## Trade-offs

Vinnes: tjenestens sterkeste egenskap beholdes hel — «leser én gang,
svarer, forkaster; ingen database, ingen søkeindeks». Det er hele
personvernhistorien i én setning, og den tåler ikke et unntak.

Ofres: kunnskapssøk kommer ikke som en gratis utvidelse av noe som
allerede virker. Det må bygges et annet sted, med egen innsats.

## Decision Value

Redusert risiko. En tjeneste som ikke lagrer noe, trenger ingen
retensjonspolicy, ingen slettedokumentasjon og ingen vurdering av hva
en indeks avslører på tvers av saker.

## Debt Introduced

Ingen i denne tjenesten. Vaktprinsippene herfra (tallvakt, provenance,
kodevalidering) må gjenskapes i RAG-piloten — de arves ikke automatisk.

## Risk

At noen senere legger inn en indeks «bare midlertidig» uten å se at det
opphever prinsippet. Motvirkes ved at denne ADR-en er lenket fra
README-avsnittet om hva tjenesten ikke gjør.

## Owner

Prosjekteier NAV dokument-AI.

## Review Trigger

Et konkret, dokumentert behov for søk PÅ TVERS av dokumenter i denne
tjenesten — ikke i en egen pilot.

## Review Date

2027-02-01

## Exit Strategy

Beslutningen omgjøres bare sammen med en ny personvernvurdering og en
eksplisitt endring av «lagrer ingenting»-løftet i README og
dokumentprofil_skjema.md §2.7.

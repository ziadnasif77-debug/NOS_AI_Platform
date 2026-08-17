# ADR-0005: Maskinprofilen hever aldri kontekstvinduet over et fast tak

**Dato:** 2026-08-15
**Status:** Gjeldende

---

## Decision

Maskinprofilen (R190) utleder kontekstvinduet av kortet, men hever det
aldri over `KONTEKST_AUTO_TAK` (8192) av seg selv. Over det sier den fra
at kortet tåler mer, og lar et menneske sette verdien.

## Reason

Prosjektet skal kunne kopieres til en ukjent server og bruke det
maskinvaren gir. Da må takene skaleres opp — men nettopp
kontekstvinduet er verdien som felte tjenesten sist.

## Alternatives Considered

1. **Skalere fritt opp etter regnestykket.** Forkastet: 8192 på 8 GB ga
   segfault under KV-cache-allokering. Ingen exception, ingen traceback,
   ingen logg. Den som står med serveren uten utviklertilgang ville hatt
   null å feilsøke på.
2. **Ikke skalere i det hele tatt.** Forkastet: da arver et 24 GB-kort
   småkortets grenser, som er hele problemet R190 løser.
3. **Skalere opp til et tak, si fra over det (valgt).**

## Trade-offs

Vinnes: automatikken kan aldri gamble med en feilmodus som ikke
etterlater bevis.

Ofres: et stort kort får ikke alt det kunne fått uten at et menneske
gjør et bevisst valg. På et 80 GB-kort er det en reell begrensning.

## Decision Value

Redusert risiko. Asymmetrien er poenget: nedskalering er alltid trygt,
oppskalering kan drepe prosessen.

## Debt Introduced

Taket er satt av forsiktighet, ikke av måling. Det finnes ingen data på
hva som faktisk er trygt over 8192 — bare at 8192 IKKE var trygt på 8 GB.

## Risk

At taket blir stående lenge etter at det er unødvendig, og at ingen
oppdager at store kort underutnyttes. Motvirket av at profilen SIER hva
kortet kunne tatt, hver eneste oppstart.

## Owner

**Ziad Nasif** — eier av dokument-API-et, og den som svarer når
review-triggeren slår inn. Overføres skriftlig i denne fila hvis
eierskapet flyttes.

## Review Trigger

Et krasjfritt løp med kontekst > 8192 er dokumentert på et større kort
(minst en uke i drift, ingen 0xC0000005 i `vakthund.log`).

## Review Date

2027-02-01

## Exit Strategy

Hev `KONTEKST_AUTO_TAK` til den dokumenterte verdien, og noter
målingen i R190 slik ankeret er notert. Brent-finger-mekanismen står
uansett igjen som nett under.

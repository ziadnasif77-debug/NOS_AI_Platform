# ADR-0004: Mellombåndet i gjennomgangsrutingen er AV som standard

**Dato:** 2026-08-13
**Status:** Midlertidig

---

## Decision

`GJENNOMGANG_NEDRE` settes lik `LS_KONFIDENS_TERSKEL`, altså et TOMT
mellombånd. Mekanismen (R187) finnes og er testet, men slår ikke inn før
noen aktiverer den bevisst.

## Reason

Tre-bånds ruting (auto / andre-sjekk / menneske) er anbefalt praksis, og
andre-sjekken vår er deterministisk (typeforventninger, R186). Men
båndet ville hvilt på terskelen 0.85 — en verdi ingen har målt (R149).

## Alternatives Considered

1. **Slå båndet på med en gang.** Forkastet: en umålt terskel skulle
   ikke få en umålt nabo. Feilen ville vært usynlig — dokumenter som
   ALDRI når et menneske, og ingen som merker det.
2. **Ikke bygge mekanismen.** Forkastet: da må den bygges under press
   senere, når volumet krever det.
3. **Bygge, teste, la den stå av (valgt).**

## Trade-offs

Vinnes: dagens oppførsel er bevart eksakt, og mekanismen er klar den
dagen tallene finnes.

Ofres: gevinsten (færre unødvendige manuelle gjennomganger) hentes ikke
inn ennå.

## Decision Value

Redusert risiko. Å sulte treningsløkka er en skade som først synes
måneder senere, i form av en dårligere håndskriftmodell.

## Debt Introduced

En mekanisme som står ubrukt er en mekanisme ingen tester i praksis.
Den kan råtne uten at noen merker det — motvirket av at den har egne
tester som kjører i hver suite.

## Risk

At båndet slås på uten at kalibreringstabellen er fylt, fordi noen leser
`.env.example` og tror verdien bare er en innstilling. Motvirket av
advarselsteksten der og i feilboka.

## Owner

**Ziad Nasif** — eier av dokument-API-et, og den som svarer når
review-triggeren slår inn. Overføres skriftlig i denne fila hvis
eierskapet flyttes.

## Review Trigger

Kalibreringstabellen (`delt/kalibrering.py`) har nok observasjoner til
at ECE kan regnes ut, og ECE < 0,05. Krever `KALIBRERING_ANDEL` > 0 i
noen uker.

## Review Date

2026-12-01

## Exit Strategy

Enten: senk `GJENNOMGANG_NEDRE` til den målte, forsvarlige verdien og
oppdater R187 med tallet. Eller: fjern mekanismen hvis målingen viser at
terskelen 0.85 ikke skiller godt fra dårlig lesing i det hele tatt.

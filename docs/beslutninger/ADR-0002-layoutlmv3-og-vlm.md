# ADR-0002: LayoutLMv3 er fjernet, og VLM utsettes til maskinvaren finnes

**Dato:** 2026-08-13
**Status:** Gjeldende

---

## Decision

LayoutLMv3 tas ikke inn igjen. Vision-Language-modeller (PaddleOCR-VL,
DeepSeek-OCR o.l.) prøves ikke før maskinvaren tåler dem, og da som en
MÅLT sammenligning mot dagens løype — ikke som et bytte.

## Reason

En arkitekturanbefaling utenfra foreslo LayoutLMv3 som sentral
komponent. Modellen lå faktisk i prosjektet og ble fjernet 2026-07-21
fordi den ikke forsvarte plassen på kortet.

## Alternatives Considered

1. **Ta LayoutLMv3 inn igjen.** Forkastet: den er fra 2022, ble målt
   som ikke verdt GPU-plassen her, og 2026-alternativene (kompakte
   VLM-er på under 1B) er både mindre og sterkere.
2. **Ta inn en VLM nå.** Forkastet: kortet har ~1130 MB hodrom med
   Borealis og OCR lastet. En VLM ville konkurrert om nøyaktig det
   minnet, og utslaget er et nativt krasj, ikke en feilmelding.
3. **Vente og måle når maskinvaren finnes (valgt).**

## Trade-offs

Vinnes: ingen halv løsning som spiser VRAM uten å bevise gevinst.
Ofres: tabeller, signaturer og komplekse layouter håndteres fortsatt
bare av OCR + regler.

## Decision Value

Redusert risiko og redusert driftskostnad. En modell til på et fullt
kort er den kjente veien til 0xC0000005.

## Debt Introduced

Dokumenttyper med tung layout (tabeller, skjemaer med avkryssing)
forblir dårligere lest til dette tas opp igjen.

## Risk

At feltet beveger seg raskere enn review-datoen, og at vi står med en
løsning som er to generasjoner bak når maskinvaren endelig kommer.
Motvirkes av vaktlisten i prosjektjournalen.

## Owner

Prosjekteier NAV dokument-AI.

## Review Trigger

Et kort med ≥16 GB VRAM er tilgjengelig for tjenesten. Maskinprofilen
(`python -m delt.maskinprofil`) sier hva kortet tåler.

## Review Date

2027-02-01

## Exit Strategy

Side-om-side-kjøring mot `tester/korpus/` og
`sporsmaal_syntetisk_bunke.json` med samme port som modellbyttet
(bootstrap-KI, ikke punkttall). Vinner VLM-en målbart, dokumenteres
byttet i en ny ADR.

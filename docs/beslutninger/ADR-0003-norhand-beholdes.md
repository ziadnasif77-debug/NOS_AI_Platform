# ADR-0003: norhand beholdes framfor en generell VLM for håndskrift

**Dato:** 2026-08-13
**Status:** Gjeldende

---

## Decision

Håndskrift leses fortsatt av norhand (TrOCR fra Nasjonalbiblioteket)
med treningsløkke, ikke av en generell vision-modell.

## Reason

Anbefalingen utenfra pekte på moderne VLM-er som erstatning for hele
OCR-løypa, håndskrift inkludert.

## Alternatives Considered

1. **Bytte til en generell VLM.** Forkastet: alle publiserte målinger
   er på engelsk/kinesisk. Ingen av dem er dokumentert på norsk
   håndskrift.
2. **Kjøre begge og velge beste per region.** Forkastet nå: to
   modeller på ett 8 GB-kort er ikke mulig ved siden av Borealis.
3. **Beholde norhand (valgt).**

## Trade-offs

Vinnes: den ENE komponenten som blir bedre av at NAV bruker den —
korreksjoner fra Label Studio trener modellen videre, med kvalitetsport
og rollback. Det er en ressurs som vokser, ikke en som forvitrer.

Ofres: en VLM ville kanskje lest bedre ut av boksen, og vi vet det ikke
uten å måle.

## Decision Value

Målbar verdi. Treningsløkka er prosjektets eneste mekanisme for å bli
bedre på NORSK håndskrift over tid; et bytte nullstiller den.

## Debt Introduced

Vi mangler et tall på hvor god norhand faktisk er mot alternativene.
Valideringssettet `data/validering/norhand.json` finnes ennå ikke, så
kvalitetsporten er inert (R148).

## Risk

At vi beholder en svakere modell av lojalitet til løkka rundt den.
Motvirkes av at exit-strategien er en måling, ikke en mening.

## Owner

**Ziad Nasif** — eier av dokument-API-et, og den som svarer når
review-triggeren slår inn. Overføres skriftlig i denne fila hvis
eierskapet flyttes.

## Review Trigger

En VLM slår norhand målbart på et norsk håndskriftsett — eller
valideringssettet blir fylt og viser at norhand er svakere enn antatt.

## Review Date

2027-02-01

## Exit Strategy

Fyll `data/validering/norhand.json`, kjør begge mot det, og la
kvalitetsporten dømme (bootstrap-KI). Vinner alternativet, byttes det
med `bytt_grunnmodell.py` og korreksjonsarkivet retrenes på ny basis.

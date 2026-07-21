# Valideringssett for kvalitetsporten

Dette settet er «fasiten» kvalitetsporten (`skript/valider_modell.py`)
måler nye norhand-modeller mot. Uten et slikt sett kan porten ikke
bekrefte at en nytrent modell er trygg — da promoteres den **ikke**
automatisk.

## Format

Lag fila `norhand.json` her:

```json
[
  { "fil_sti": "data/validering/bilder/prove_01.png", "tekst": "Ola Nordmann" },
  { "fil_sti": "data/validering/bilder/prove_02.png", "tekst": "Storgata 1, 0155 Oslo" }
]
```

- `fil_sti` — et håndskriftbilde (samme type norhand leser i drift).
- `tekst` — den korrekte lesingen (fasit), skrevet av et menneske.

Se `norhand.eksempel.json` for et startpunkt.

## To jernregler

1. **Holdes atskilt fra treningsdataene.** Bruker du de samme bildene til
   både trening og validering, måler du hvor godt modellen *husker* — ikke
   hvor godt den *generaliserer*. Velg 20–50 eksempler som aldri havner i
   trocr_*.json.
2. **Endres aldri.** Et fast sett gjør CER-tallene sammenlignbare mellom
   løp. Vil du utvide dekningen, lag heller et nytt, større sett og bytt i
   ett — ikke rediger det eksisterende bit for bit.

## Hva porten gjør

Ved hvert treningsløp (`make trening`):

1. `finjuster.py` trener en **kandidat** (`modeller/norhand-kandidat`) —
   live-modellen røres ikke.
2. Porten måler tegnfeilrate (CER) for både live og kandidat på dette
   settet.
3. Er kandidaten minst like god (CER ≤ live + `CER_MARGIN`) → **promoteres**
   (forrige live tas vare på i `modeller/norhand-forrige`).
4. Ellers → **avvises**; live står urørt.

Rull tilbake til forrige modell når som helst:

```bash
python skript/valider_modell.py --rull-tilbake
```

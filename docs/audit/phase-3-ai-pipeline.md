# Fase 3 — OCR, NLP, deterministisk uttrekk og søk

**Metode:** full kodegjennomgang (modeller ikke kjørt i denne fasen — funn er
`bekreftet ved kodelesing` med mindre annet nevnt). Ett funn er også
`bekreftet ved kjøring` (F3-1, den hardkodede linjen lest direkte).

---

## Funn

### F3-1 · KRITISK · Hardkodede konfidenser driver kvalitetsporten
**Fil:** `lag1.py:136` (TrOCR **0.88**), `lag1.py:147` (Marker **0.90**),
`lag1.py:156` (BLANDET = snitt m/hardkodet 0.90), `lag2.py:261` (LayoutLMv3
**0.91**), `lag2.py:293` (Borealis **0.87**), `lag2.py:382` (NB-BERT **0.82**).
Kun `lag1.py:118` (PaddleOCR) er ekte modellkonfidens.
**Klassifisering:** bekreftet ved kjøring (linje `return tekst, 0.88, ...` lest
direkte) + utledet konsekvens.
**Konsekvens — integritetssvikt i kvalitetsporten:** `lag1.py:71`
`godkjent = konfidens >= terskel` med terskel 0.85. **Håndskrift (TrOCR→0.88)
og tabeller (Marker→0.90) blir ALLTID auto-godkjent** og aldri sendt til
gjennomgang — selv om håndskrift er det minst pålitelige moduset. Dette er
kjernen i hele kvalitetsdiskusjonen i dette systemet: porten som skal fange
usikker OCR hviler på konstanter, ikke på modellenes faktiske usikkerhet.
**Fiks:** TrOCR: `generate(..., output_scores=True, return_dict_in_generate=
True)` + softmax-snitt over sekvensen. LayoutLMv3: `softmax(logits).max(-1)`-
snitt over ikke-`O`-tokens. Marker eksponerer ingen score → merk «konfidens
ukjent» og rut alltid til gjennomgang i stedet for å påstå 0.90.

### F3-2 · Høy · Anti-hallusinering dekker kun fnr/konto/ytelse/fylke
**Fil:** `tekstuttrekk.py:215-274` (`utvid_entiteter`).
**Klassifisering:** bekreftet ved kodelesing.
**Bevis:** for `telefon`, `epost`, `dato`, `belop`, `saksnummer` gjelder det
deterministiske mønsteret bare *hvis* funksjonen finner noe (`:233-235`,
`verdi is not None`). Finner den ingenting, blir en hallusinert modellverdi
(f.eks. `belop: 99999` uten kilde) liggende. Bare fnr/konto (mod11) og
ytelse/fylke (whitelist) har en faktisk gate. Docstring hevder mer enn koden
gjør.
**Fiks:** for hvert mønsterfelt uten deterministisk treff: verifiser en evt.
modellverdi mot samme regex (`re.fullmatch`), ellers popp feltet — samme
mønster som fnr/konto.

### F3-3 · Høy · `finn_fylke` er ikke-deterministisk (set-iterasjon)
**Fil:** `konstanter.py:69-74` + `tekstuttrekk.py:199-208`.
**Klassifisering:** bekreftet ved kodelesing.
**Bevis:** `NORSKE_FYLKER` er et `set` (uordnet). `finn_fylke` returnerer
*første* regex-treff. På «Troms og Finnmark» matcher både `\bTroms\b` og
`\bTroms og Finnmark\b`, og hvilket som returneres avhenger av settets
iterasjonsrekkefølge → **ikke-deterministisk fylke** lagres og indekseres.
I tillegg er Troms/Finnmark lagt til separat, men ingen andre historiske
fylker — inkonsekvent.
**Fiks:** iterer en **lengdesortert liste** (lengste navn først) i `finn_fylke`,
bruk `list` ikke `set`. Beslutt eksplisitt om historiske fylker skal støttes
(policy — se fase 7).

### F3-4 · Middels · PaddleOCR kjører engelsk språkmodell på norske dokumenter
**Fil:** `lag1.py:112` — `PaddleOCR(..., lang="en", ...)`.
**Klassifisering:** bekreftet ved kodelesing.
**Konsekvens:** forringet gjenkjenning av `æ ø å` og norske ord → forgifter NER,
deterministisk uttrekk og embedding nedstrøms. Lav innsats, stor effekt.
**Fiks:** `lang="no"` (eller `lang="latin"`).

### F3-5 · Middels · Kryssvalidering sammenligner fnr-fødselsdato mot vilkårlig dokumentdato
**Fil:** `lag2.py:479-492` (`_kryssvalider`, gated bak `lag5_kryssvalidering`).
**Klassifisering:** bekreftet ved kodelesing.
**Bevis:** tar `fnr[:4]` (DDMM=fødselsdato) mot `entiteter["dato"]` = *første
dato i dokumentet* (`tekstuttrekk.py:83`), ikke fødselsdato. Et vedtaksbrev
datert 2024 for en person født 1980 gir alltid `fnr_dato_mismatch`. Håndterer
heller ikke D-nummer (dag+40).
**Fiks:** fjern, eller sammenlign kun mot et faktisk fødselsdato-felt + håndter
D-nummer. (Funksjonen er av som standard, derav middels.)

### F3-6 · Middels · `_parse_borealis_json`: grådig regex kan tape all data
**Fil:** `lag2.py:334` — `re.search(r"\{.*\}", svar, re.DOTALL)` (grådig,
første `{` til siste `}`). Ved prosa med flere klammer blir fanget streng
ugyldig JSON → `return {}` stille (alle felter tapt).
**Klassifisering:** bekreftet ved kodelesing.
**Fiks:** prøv `json.loads` på hele svaret først; ved feil, finn balanserte
klammer. Logg på DEBUG når parsing gir `{}` (stille datatap synlig).

### F3-7 · Middels/Lav · BM25/RRF: score-0-dokumenter får rang + snapshot-race
**Fil:** `sok/hoved.py:387-388` (ingen filtrering av BM25-score=0), `:315-319`
(indeks-uthenting og snapshot under separate låstak), `:382` (rå `.split()`
uten lowercase).
**Klassifisering:** bekreftet ved kodelesing.
**Fiks:** filtrer score≤0; hold indeks+snapshot under samme lås (eller returner
(fil_id, tekst)-par); lowercase ved indeksering og søk.

---

## Svar på kjent punkt (4) fra kvalitetsvinkelen

Kvalitetsporten (`_bestem_beslutning`, `lag3.py:81-105`) er **logisk korrekt**:
lav OCR/NLP-konfidens, valideringsfeil og anomali gir alle REVIEW med riktig
Label Studio-prosjekt. Men porten mates av **delvis falske konfidenser (F3-1)**
— så en logisk korrekt port kan slippe usikre håndskriftsdokumenter gjennom
fordi input-tallet er en konstant 0.88. Dette er den viktigste enkeltsvakheten
i AI-pipelinen.

## Gjort bra (verifisert ved kodelesing)

- **mod11-matematikken er korrekt** (`tekstuttrekk.py:21-48`): FNR to
  kontrollsifre, konto ett, `r==10`/`r==11→0` håndtert, ingen off-by-one.
  Solid grunnmur for anti-hallusinering.
- **RRF korrekt** (`fusjon.py:28,37`): `1/(k+rang+1)` 0-basert = standard
  `1/(k+rank)`, `k=60` kanonisk. Fusjonerer komplette dokumenter.
- **Deterministisk-over-modell er riktig prinsipp**; fnr/konto/ytelse/fylke-
  gatene er godt utført (hullet er de andre mønsterfeltene, F3-2).
- **Idempotent per-side-indeksering** (fil_id, side_nummer).
- **Milvus-ekspresjonsinjeksjon avverget** via allowlist-validering av filtre.
- **Konsistent embedding** (dim 1024, COSINE, normalisert) ved indeksering og søk.
- **Ingenting arabisk** noe sted — all kode/kommentar/streng er norsk.

# Ytelses- og arkitekturanalyse — ekstern revisjon mot 2026-standarden

Basert på nettresearch (kilder nederst) sammenlignet med vårt system,
2026-07-18.

## 1. Hvordan brukes ekstraksjonsresultater moderne i 2026?

Bransjen konvergerer mot: (a) hybride pipeliner — layoutbevisste
parsere for effektivitet + visjon-språkmodeller (VLM) selektivt for de
vanskeligste sidene, (b) hybrid søk (vektor + nøkkelord) over
strukturerte resultater som produksjonsstandard, (c) innebygde
menneske-i-løkken-gjennomgangskøer, (d) komponerbar automatisering
(resultater rett inn i fagsystemer via API/webhooks).

**Vårt system mot dette:** deterministisk kjerne med sjekksummer,
ærlighetsflagg, versjonsstempling og REVIEW-ruting er HELT i tråd med
beste praksis («gi hvert verktøy jobben det er best til»). Det som
mangler: hybrid søk/RAG over arkivet (qwen3-embed ligger ubrukt på
disk), VLM-fallback for komplekse sider, og gjennomgangs-UI for
lokal-API-et (Label Studio finnes kun i Docker-løpet).

## 2. Gir flere skjermkort høyere fart — hele systemet eller deler?

**Deler.** Fordeling per komponent:

| Komponent | Effekt av flere GPU-er |
|---|---|
| OCR (skannede sider) | NÆR LINEÆR skalering — sider er uavhengige («embarrassingly parallel»); 2 GPU-er ≈ dobbel gjennomstrømning. Krever én arbeidstråd per GPU (vi har én global). |
| Borealis (ett spørsmål) | Nesten INGEN effekt — 7B-modellen bor på ett kort; flere kort hjelper kun SAMTIDIGE spørsmål. |
| Deterministisk uttrekk | Ingen effekt — CPU-arbeid på millisekunder allerede. |
| Kombinert drift | STOR effekt av å skille OCR-GPU fra LLM-GPU: i dag deler alt ett 8 GB-kort og serialiseres bak samme lås. |

## 3. Blir OCR raskere?

Ja — tre uavhengige spaker, med dokumenterte tall:

1. **Motorbytte:** EasyOCR rangeres i 2026 som «prototypings-nivået».
   PaddleOCR PP-OCRv5 med batching måles til ~190 sider/min på
   RTX 4080 og ~380 sider/min på RTX 3090/5090-klassen. Vår målte
   fart: ~2–8 s/side (EasyOCR + norhand sekvensielt) ≈ 10–30
   sider/min. **Potensial: 5–15×** uten ny maskinvare.
2. **Sidebatching:** vi OCR-er én side om gangen; moderne motorer
   tar batch på 8–16 sider per GPU-kall.
3. **Regionruteren beholdes:** arkitekturen vår (usikre regioner til
   spesialist) er riktig — motorene under er utskiftbare (generelt
   design). norhand beholdes for håndskrift.

## 4. Lesing på brøkdeler av et sekund — beste metode og ressurser

- **Tekstlags-PDF-er: allerede under sekundet hos oss** (deterministisk
  uttrekk går på millisekunder). Ingen endring nødvendig.
- **Én skannet side:** oppnåelig på ~0,3–1 s med PP-OCRv5/RapidOCR +
  TensorRT på moderne GPU (RTX 5090 måles til <700 ms p99; RTX 3090
  ~1 s). På vår RTX 3070: realistisk ~1–2 s/side med motorbytte.
- **Hundrevis av skannede sider på under et sekund:** fysisk umulig på
  ett forbrukerkort — dette er gjennomstrømnings-, ikke latens-
  problemet. 500 sider på <1 min krever 2–3 moderne GPU-er med
  batching; på <1 s kreves en GPU-park (~50+). Ærlig materialfysikk.
- **Ressursanbefaling (best verdi):** ett 24 GB-kort (RTX 3090/4090)
  → rom til både LLM og OCR uten lås-kollisjon, større kontekst,
  raskere attention. Kort nr. 2 gir deretter lineær OCR-skalering.

## 5. Er systemet programmert optimalt? (revisjonens dom)

**Logikk/arkitektur: moderne beste praksis.** Deterministisk-først,
matematisk validering, aldri stille kutt, versjonering, generelt
skjema — researchen bekrefter disse valgene punkt for punkt.

**Kjøre-/serveringslaget: 2022-nivå. Betydelig fart ligger på bordet:**

| # | Funn | Belegg | Gevinst |
|---|---|---|---|
| 1 | Borealis kjøres via transformers + bitsandbytes + eager attention — den tregeste kjente stien | bnb måles ~64 % tregere enn Marlin-kjerner; EXL2 147 % raskere enn bnb; llama.cpp/GGUF Q4 vesentlig raskere på forbruker-GPU | 2–4× på alle LLM-svar + frigjort VRAM |
| 2 | EasyOCR som hovedmotor for trykt tekst | 2026-benchmarks: PaddleOCR v5 5–15× raskere med batching | OCR-tid fra minutter til sekunder |
| 3 | Én global GPU-lås serialiserer OCR, LLM og jobber | Mikrotjeneste-referansearkitekturer kjører disse uavhengig | Parallellitet ved blandet last |
| 4 | Ingen filhash-cache i synkronløpet — samme fil re-OCR-es per spørsmål | Standard IDP-praksis: prosessér én gang, spør mange ganger (jobbsystemet vårt gjør dette riktig) | Øyeblikkelige oppfølgingsspørsmål |
| 5 | attn_implementation="eager" | sdpa er gratis oppgradering | 10–30 % raskere prefill |
| 6 | stdlib ThreadingHTTPServer | Grei for test; FastAPI/uvicorn for produksjon (Docker-løpet har det alt) | Robusthet, ikke fart |
| 7 | qwen3-embed ubrukt — ingen hybrid søk over arkiv | Hybrid søk er 2026-produksjonsstandarden for gjenfinning | Arkiv-spørsmål i skala |

**Anbefalt rekkefølge:** (1) sdpa + filhash-cache (timer), (2) Borealis
→ llama.cpp/GGUF (én dag, størst enkeltgevinst), (3) PaddleOCR i
regionruteren + sidebatching (1–2 dager), (4) arbeidstråd per GPU ved
kort nr. 2, (5) hybrid søk med qwen3-embed.

## 6. GJENNOMFØRT 2026-07-18 — målte resultater

| Tiltak | Målt effekt |
|---|---|
| Borealis → offisiell GGUF Q8 (NbAiLab) via llama.cpp/CUDA, med transformers som automatisk fallback | Modell-lasting 90 s → **3 s**; generering ~12 → **34 tok/s**; Q8 er MER presis enn gammel nf4 |
| Filhash-cache (SHA-256) rundt hele analysen; /spor, /analyser og /uttrekk deler samme ekstraksjonsvei | Oppfølgingsspørsmål på samme fil: 30–60 s → **0,4 s** |
| sdpa-attention i transformers-fallback | 10–30 % raskere prefill når fallback brukes |
| Motorlag i regionruteren (OCR_MOTOR=easy/rapid) | Målt på denne maskinen: EasyOCR-GPU 0,80 s/side VS RapidOCR-CPU 1,34 s/side → easy forblir standard; rapid er GPU-avlastningsvalg. 5–15×-tallene fra research krever dedikert/større GPU + batching. |
| Ende-til-ende målt via tunnel | Tekst-PDF-spørsmål: **0,3 s**; serveroppstart til klar: **8 s** |

Funn underveis: Borealis-GGUF-repoet inneholder også mmproj
(synsprojektor) — modellen kan på sikt lese sider som BILDER (VLM),
som er 2026-retningen for komplekse sider.

Gjenstår fra planen: sidebatching i OCR, arbeidstråd per GPU (krever
kort nr. 2), hybrid søk med qwen3-embed.

## Kilder

- gigagpu.com: OCR-benchmarks, sider/min per GPU, flerGPU-skalering
- codesota.com: PaddleOCR vs Tesseract vs EasyOCR 2026
- markaicode.com: vLLM vs llama.cpp offisielle benchmarks
- tensorrigs.com: GGUF vs GPTQ vs AWQ kvantiseringsguide
- Red Hat Developer: llama.cpp vs vLLM valg av inferensmotor
- arxiv 2605.18818: mikrotjenestearkitektur for OCR+LLM i produksjon
- PaddleOCR-VL-1.5 (arxiv 2601.21957): 0.9B VLM, 1.43 sider/s på A100
- koreadeep.com: IDP 2026 enterprise-guide (VLM vs legacy-OCR-kjerner)
- omdena.com / firecrawl.dev: dokumentparsing og RAG-praksis 2026

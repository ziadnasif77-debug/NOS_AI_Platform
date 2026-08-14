# Phase 0 — beslutningsrapport

**Dato:** 2026-08-15
**Status:** Utkast — målt på utviklermaskin, IKKE på målserveren
**Grunnlag:** `skript/kjor_ytelsesmaaling.py`, rådata i
`data/ytelsesmaalinger/20260815-014541.json`
**Krav den svarer på:** Implementeringsspesifikasjon v1.6 §24.1

---

## 0. Hva denne rapporten er — og ikke er

Konseptutredningen krever at Phase 1 ikke starter før hvert ledd er
målt, og at ingen ny infrastruktur vurderes uten en målt bottleneck,
en baseline og en benchmark som kan avkrefte hypotesen (§20.0).

Tallene under er **ekte målinger**, ikke anslag. Men de er målt på en
utviklermaskin med ett 8 GB-kort. **De dimensjonerer ikke en NAV-server.**

Riggen er derfor et skript, ikke et notat:

```
.pyruntime\python.exe skript\kjor_ytelsesmaaling.py
```

Kjør den på målmaskinen, og denne rapporten kan skrives om med tall som
gjelder. Det er den eneste veien til et forsvarlig beslutningsgrunnlag.

**Målemaskin:** NVIDIA RTX 3070, 8192 MB VRAM · 12 kjerner · 32 GB RAM
· Borealis 4B Q8 via llama.cpp · OCR: RapidOCR (CPU)

---

## 1. End-to-End Performance Profile

Hvert ledd målt for seg. Cachen er beseiret (unik fil per runde);
cachetreff måles separat fordi det er en ekte egenskap, ikke juks.

| Ledd | Median | P95 | P99 | n | Hva det dekker |
|---|---|---|---|---|---|
| Tekstlag, felter | **1,40 s** | 2,11 s | 2,11 s | 12 | Opplasting + parsing + deterministisk motor + aggregering |
| Tekstlag, struktur | 1,22 s | 5,56 s | 5,56 s | 12 | + komplett strukturert uttrekk |
| Tekstlag + spørsmål | 1,58 s | 1,85 s | 1,85 s | 6 | + Borealis |
| **Skannet, 10 sider** | **35,86 s** | 37,15 s | 37,15 s | 4 | + OCR |
| Cachetreff | 0,055 s | 0,067 s | — | 4 | Samme dokument om igjen |
| 4 samtidige | 1,94 s | 2,66 s | — | 4 | Alle svarte 200 |

**Avledet:**

| Størrelse | Målt |
|---|---|
| OCR | **3,42 s/side = 0,29 sider/s** (40 sider målt) |
| Tekstlag | ~7,1 sider/s (10 sider på 1,40 s) |
| Modellkall | **0,41 s per kall** |
| Cache | 25× raskere enn kald lesing |
| Samtidighet | 4 parallelle → 1,50 svar/s, ingen 503 |

Merk P95 på `struktur` (5,56 s): én utligger i første runde, resten
under 2,2 s. Med n=12 er P95 følsom for én måling — tallet er tatt med
som det er, ikke silt bort.

---

## 2. Top Bottlenecks

### 1. OCR — og den er ikke der man tror

OCR bruker **96 %** av tiden på et skannet dokument (35,86 s totalt,
hvorav ~34,5 s OCR). Språkmodellen bruker 0,41 s per kall.

Det bekrefter konseptutredningens hovedfunn med vår egen måling:
*«OCR, not language-model parsing, dominates end-to-end latency.»*

### 2. Den EGENTLIGE flaskehalsen er VRAM

Dette er rapportens viktigste funn, og det endrer anbefalingen
fullstendig.

Under målingen sto OCR på **CPU**, ikke GPU:

```
ocr_motor_i_bruk: "rapid"      ledig_gpu_mb: 1149
easyocr_enhet:    "ikke_lastet"  krever_ledig_gpu_mb: 2600
```

Borealis Q8 legger beslag på kortet, og OCR får ikke de 2600 MB den
trenger. Da faller den til RapidOCR på CPU — som er trygt og korrekt
(R51/R140), men mye tregere:

| OCR-vei | s/side | sider/s | Kilde |
|---|---|---|---|
| RapidOCR på CPU | 3,42 | 0,29 | Denne målingen |
| EasyOCR på GPU | ~0,50 | ~2,0 | R51, samme maskin |

**Faktor 6,9.** Flaskehalsen er altså ikke «for lite regnekraft» — det
er at OCR ikke kommer til kortet.

### 3. Ikke en flaskehals: språkmodellen

0,41 s per kall. Utredningens Phase 3 (Borealis-pool, `--parallel N`)
er derfor **ikke** utløst av denne målingen.

---

## 3. Capacity Baseline

Utredningens belastningsprofil, regnet mot målte tall:

| Forutsetning (fra §4) | Verdi |
|---|---|
| Sider/dag | 250 000 |
| Skannet andel | 50 % → 125 000 OCR-sider/dag |
| Peak | 60 % over 4 timer → **5,2 OCR-sider/s** |

Med utredningens egen formel
(`peak / målt_per_worker × sikkerhetsfaktor 1,3`):

| OCR-vei | Arbeidere ved peak | Maskintimer/dag (snitt) |
|---|---|---|
| **CPU-fallback (målt her)** | **23** | 119,7 |
| **GPU-OCR (R51)** | **4** | 17,4 |

Samme last. Samme kode. Forskjellen er om OCR får kortet.

### Følsomhet — de to tallene ingen har målt

Utredningen merker begge som antakelser (§27). De styrer alt:

| Hvis … | OCR-sider/dag | Arbeidere (CPU / GPU) |
|---|---|---|
| Skannet andel 50 % *(antatt)* | 125 000 | 23 / 4 |
| Skannet andel 10 % | 25 000 | 5 / 1 |
| Snitt 20 sider/dok, ikke 500 | 5 000 | 1 / 1 |

**Måles disse to før noe kjøpes, kan hele Phase 2–4 vise seg unødvendig.**
Et NAV-dokument på 500 sider i snitt er en arkivboks, ikke et brev.

---

## 4. Cost Baseline

Ingen kroner her — vi har ikke priser, og et oppdiktet tall er verre
enn ingen. Kostnaden uttrykkes i maskintimer, som er det som faktisk
skal kjøpes:

| Scenario | Maskintimer/dag | I praksis |
|---|---|---|
| CPU-OCR, 125 000 sider | 119,7 | ~5 maskiner i døgndrift bare for snittlasten |
| GPU-OCR, 125 000 sider | 17,4 | Under én maskin |
| GPU-OCR, 25 000 sider | 3,5 | En brøkdel av én maskin |

Den billigste kapasitetsøkningen er ikke en maskin til. Det er å
frigjøre 1,5 GB VRAM på maskinen som allerede står der.

---

## 5. Evidence Selection Baseline

Utredningen krever at candidate selection måles mot en
*first-12k-character baseline*. Den baselinen er dagens oppførsel:
`MAKS_LLM_TEGN = 12000`.

Målt med spørsmålskorpuset (46 spørsmål, `make sporsmaalskorpus`):

| Mål | Baseline |
|---|---|
| Riktige svar | **42 av 46 (91 %)** |
| Av dette modellen | 33 av 37 |
| Av dette koden (kontrollgruppe) | 9 av 9 |
| Determinisme (R6) | Grønn — samme svar hver gang |
| Tallvakt-utslag | 0 av 46 |
| Tid per svar | 0,63 s |

**Kjent svakhet, og den er ikke avkorting.** De fire feilene har ett
mønster: spørsmål om side 9–10 besvares fra side 1–3. Dokumentet er
7 176 tegn — godt innenfor 12 000, så modellen SÅ sidene. Den skiller
ikke dokumentene i en bunke fra hverandre.

På «hvor mye skylder parten i renter?» — som dokumentet ikke oppgir —
svarte modellen fakturabeløpet. **Tallvakten stoppet det ikke og kan
ikke:** tallet står i dokumentet, det svarer bare på et annet spørsmål.
Vakten garanterer at tall ikke er DIKTET, ikke at de er RELEVANTE.

Det er nettopp dette Evidence Selection skal løse, og de fire
spørsmålene er måltavlen: en kandidatløsning som fikser dem uten å
ødelegge de 42 andre, er målbart bedre.

---

## 6. Top Risks

| Risiko | Konsekvens | Tiltak |
|---|---|---|
| Kjøpe maskinvare på antatt last | For dyrt eller for lite | Mål skannet andel og sider/dokument FØRST |
| Skalere arbeidere i stedet for å frigjøre VRAM | 23 maskiner der 4 holder | Prøv kvantisering/GPU-lag før innkjøp |
| Bunkeforveksling i modellsvar | Feil svar som ser riktig ut | Evidence Selection; menneskelig kontroll består |
| Tallvakt gir falsk trygghet | Irrelevant tall passerer som svar | Dokumentert i korpuset; ikke fjern menneskelig kontroll |
| Umålte terskler (0,85) | Feilruting ingen oppdager | `KALIBRERING_ANDEL` > 0 i noen uker (R149) |
| Målingene tas for å gjelde NAV-serveren | Feil dimensjonering | Denne rapportens §0; riggen kjøres på målmaskinen |

---

## 7. Recommended Next Step

**Ikke Phase 2.** Utredningen tillater den først når lokal fan-out etter
optimalisering ikke holder (§24.1), og vi har ikke engang prøvd den
billigste optimaliseringen ennå.

Rekkefølge, billigst først:

1. **Mål de to ukjente på ekte NAV-data:** skannet andel og
   sider/dokument. Dette er den ene handlingen som kan endre alt.
2. **Frigjør VRAM så OCR kommer på GPU.** To gratis forsøk, begge
   målbare med verktøy som allerede finnes:
   - Kvantisert Borealis (Q4 i stedet for Q8) frigjør ~1,5–2 GB.
     Kvalitetstapet måles av `bytt_modell.py`, som nekter byttet hvis
     modellen blir målbart dårligere.
   - `BOREALIS_GPU_LAG` lavere flytter lag til RAM. Modellen bruker
     0,41 s/kall, så det er rom å gi av.
   Lykkes én av dem: 23 arbeidere → 4.
3. **Kjør riggen på målserveren** og skriv denne rapporten om.
4. **Så, og bare så,** vurder Phase 1 (lokal page fan-out).

---

## 8. Required ADRs

| ADR | Beslutning | Status |
|---|---|---|
| [0006](beslutninger/ADR-0006-plattformlag-utsatt.md) | Kø/database/multi-node utsatt til Phase 0 er målt | Gjeldende — denne rapporten er grunnlaget |
| Ny, foreslått | Kvantiseringsnivå for Borealis (Q8 vs Q4) | Åpen — avventer måling i steg 2 |
| Ny, foreslått | OCR-motorvalg når VRAM er knapp | Åpen — dagens fallback er trygg, men kostbar |

## 9. Architectural Debt Register

| Gjeld | Hvorfor akseptert nå | Review-trigger |
|---|---|---|
| OCR faller til CPU på et fullt kort | Alternativet er nativt krasj (R140). Trygt, men 6,9× tregere | Kort med ≥16 GB, eller Borealis kvantisert ned |
| Ett kort brukes; kort 1+ står ubrukt | Flerkort krever arbeid ingen har målt behov for | To kort tilgjengelig OG målt bottleneck |
| Terskelen 0,85 er umålt | Kalibreringsmekanismen finnes, men er av | ECE beregnbar (R149) |
| Valideringssettet for norhand finnes ikke | Kvalitetsporten er dermed inert (R148) | Før neste modellbytte for håndskrift |
| Bunkeforveksling i modellsvar | Evidence Selection ikke bygget | Fire korpus-spørsmål; se §5 |

---

## 10. Exit-gate: kan Phase 1 starte?

Utredningen krever måling av sju ledd før Phase 1 (§24.1):

| Ledd | Målt? |
|---|---|
| Upload/Parsing | ✅ inngår i 1,40 s |
| OCR | ✅ 3,42 s/side |
| NAV Deterministic Engine | ✅ inngår i 1,40 s |
| Evidence Selection | ✅ baseline 42/46 |
| Borealis | ✅ 0,41 s/kall |
| Validation/Aggregation | ✅ inngår i 1,40 s |
| Samlet P95/P99 | ✅ per scenario over |

**Formelt: ja.** Reelt: tallene er fra feil maskin, og de to viktigste
inngangsverdiene er fortsatt antakelser. Anbefalingen i §7 er derfor å
lukke de to hullene før Phase 1 startes — ikke fordi porten er stengt,
men fordi svaret kan bli at Phase 1 heller ikke trengs.

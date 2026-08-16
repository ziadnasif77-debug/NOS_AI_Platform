# Phase 0 — beslutningsrapport

**Dato:** 2026-08-15
**Status:** Utkast, revidert 2026-08-15 etter forsøk — målt på utviklermaskin, IKKE på målserveren
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

## 1b. 500-sidersmålingen (§30)

Kravet: «500-siders scanned path fullfører med full OCR coverage når
dette kreves, uten stille truncation». Det kunne ikke prøves uten et
500-siders skannet dokument, og et slikt fantes ikke. Bygget med
`skript/lag_stor_bunke.py` (`make storbunke`) av den syntetiske
10-siders bunken, gjentatt — sidene settes inn som REFERANSER, så fila
blir 3,6 MB i stedet for ~180.

| Måling | Resultat |
|---|---|
| Status | **ferdig** |
| Sider | **500 av 500** |
| Sidemarkører i teksten | **500 av 500** — ingen mangler |
| Tid | 31,4 min (1882 s) |
| Fart | 0,27 sider/s (3,76 s/side) |
| Tegn lest | 359 863 |
| OCR-regioner | rapidocr 13 450 · norhand+ufcn 318 |
| Strekkoder funnet | 100 |
| **Policy-avvik** | **ingen** — den frosne policyen holdt i 31 minutter |
| Tilstander | `kjorer → ferdig` |

**Kravet er innfridd: ingen stille avkorting.** Alle 500 sidemarkører
står i teksten, og `sider_ferdig == sider_totalt == 500`.

**Farten faller svakt over lengden:** 0,30 sider/s de første 150 sidene,
0,27 samlet. Rundt 10 % degradering over en halvtime. Ikke dramatisk,
men det betyr at en kort måling overvurderer kapasiteten — og
dimensjonering skal gjøres på det LANGE tallet:

| Grunnlag | sider/s | Arbeidere ved 5,2 sider/s |
|---|---|---|
| 10-siders bunke | 0,29 | 23 |
| **500-siders bunke (ekte)** | **0,27** | **25** |

**Det viktigste funnet er negativt, og det er meningen:** OCR-policyen
ble frosset ved jobbstart og holdt gjennom hele løpet uten ett avvik
(R199). Det var her den kunne sviktet — over 31 minutter varierer
VRAM-situasjonen, og før R199 ville motorvalget blitt tatt på nytt per
side.

**Én ærlighetsnote om målingen selv:** første utgave av måleskriptet
rapporterte at `[Side 500 av 500]` manglet. Det var skriptet som spurte
feil sted — jobbsvaret bærer ikke teksten, den hentes fra
`/jobb/{id}/tekst`. Systemet var riktig hele tiden. Et måleverktøy kan
lyve på nøyaktig samme måte som koden det måler.

---

## 1c. Lokal fan-out (§24.1) — porten til Phase 2

Spesifikasjonen slipper ikke Phase 2 (RabbitMQ/Redis, flere noder) løs
før lokal fan-out ETTER optimalisering ikke lenger tilfredsstiller
målkravene. Den porten kan bare åpnes av en måling, og målingen fantes
ikke: jobbarbeideren leser sidene én om gangen.

`skript/kjor_fanout_maaling.py` måler det. Én «Page Task» = rendre siden
+ `ocr_side`, altså nøyaktig det arbeidet en fan-out ville delt på.
30 sider, 12 logiske kjerner, `OCR_MOTOR=rapid` (policyen maskinen
faktisk fryser med Borealis på kortet).

| Modus | sider/s | speedup | kjerner brukt | tekst |
|---|---|---|---|---|
| sekvensiell (i dag) | 0,311 | 1,00× | 5,0 | — |
| 6 tråder gjennom `ocr_side` | 0,302 | **0,97×** | **5,0** | identisk |
| 6 tråder uten modullåsen | 0,437 | 1,41× | 8,7 | **2 av 30 sider avvek** |

**Kjernerekken er beviset, ikke speedup-en.** Seks tråder bruker NØYAKTIG
de samme 5,0 kjernene som én. `ocr_side` holder en modulglobal lås rundt
hele siden, så trådene står i kø uansett hvor mange de er. Det er en
måling, ikke en lesning av koden.

Uten låsen løftes kjernebruken 5,0 → 8,7 og farten 1,41×. Men to sider
ble LEST ANNERLEDES, og da er farten verdiløs: R6 krever at samme
dokument gir samme svar.

### Hvor avviket kom fra — og hva det åpner

En sonde (`--uten-ufcn`) satte UFCN-andrepasset ut av spill og gjentok
målingen:

| | speedup uten lås | tekst |
|---|---|---|
| med UFCN-andrepass | 1,41× | 2 sider avvek |
| uten UFCN-andrepass | 1,30× | **identisk** |

Avviket kommer altså fra HÅNDSKRIFTPASSET, ikke fra RapidOCR. norhand
(TrOCR) leser i BATCH, og parallelle tråder setter batchene sammen ulikt
fra gang til gang — en generativ modell gir da litt ulikt svar.

Sonden ga også et tall ingen hadde: **UFCN-andrepasset koster 24,7 % av
tiden** (0,311 → 0,413 sider/s når det er borte) — langt mer enn
andelen regioner tilsier (318 av 13 768 = 2,3 % i 500-sidersmålingen).

Det gjør den smale fiksen REGNBAR i stedet for gjettet: låser man bare
håndskriftpasset og lar RapidOCR gå parallelt, blir 24,7 % av tiden
seriell og resten 1,30× raskere:

| | sider/s | speedup | arbeidere ved peak |
|---|---|---|---|
| i dag | 0,27 | 1,00× | 25 |
| smal lås (regnet) | 0,33 | **1,21×** | **21** |

### Prosess-fan-out: ikke bare nytteløst — skadelig

Seks prosesser uten trådpinning ble målt til de KOLLAPSET: alle seks lå
på ~95 % CPU og hadde brent 9 700 CPU-sekunder HVER (~16 CPU-timer til
sammen) uten å bli ferdige med 180 sider, mens minnebruken sto i 17 GB.
72 ONNX-tråder på 12 kjerner, og hvert barn med sin egen norhand på CPU
fordi seks CUDA-kontekster ikke får plass på kortet.

Dette er verdt å si høyt fordi det er nøyaktig hva «bare legg til flere
arbeidere» produserer.

### Dommen

**Lokal fan-out, ferdig optimalisert, gir 1,21× med determinismen i
behold.** Peak-kravet er 5,2 OCR-sider/s; én maskin gir 0,33. Gapet er
~16×, og ingen trådstrategi lukker det.

**Porten til Phase 2 er dermed formelt åpen** — men bare under
belastningsantakelsen i §3, som fortsatt ikke er målt. Ved 10 % skannet
andel kreves 4 maskiner, og ved 20 sider/dokument i snitt holder ÉN.
Antakelsen avgjør mellom en klynge og en PC, og fan-out-tallet endrer
ikke det bildet.

### Den smale fiksen ble bygget, strøk sin egen port — og avdekket en eldre feil

Låsene ble delt i tre, jobbarbeideren fikk trådet sidelesing med
rekkefølgen bevart, og maskineriet virket: **1,38×**. Likevel strøk det
determinismeporten — **2 av 30 sider ble lest annerledes**, også etter
at ALL håndskriftbruk var serialisert. Hypotesen om et kappløp ble
dermed målt og forkastet.

Årsaken var et **tidsbudsjett**:

```
_les_med_norhand:   if brukt >= MAKS_NORHAND_SEKUNDER: break
UFCN-andrepasset:   if brukt >= MAKS_NORHAND_SEKUNDER * 2: break
```

Hvor mange håndskriftregioner en side rakk avhang av hvor rask maskinen
var akkurat da — og under tråder teller også ventingen på låsene med i
budsjettet.

**Dette var et R6-brudd som fantes uten en eneste tråd (R204).** Samme
dokument lest på en travel server ga allerede et annet svar enn på en
rolig. Det hadde ligget der hele tiden, uoppdaget nettopp fordi det ikke
var reproduserbart. Parallelliteten gjorde det reproduserbart for første
gang — funnet er større enn funksjonen som avdekket det.

### Rettingen: klokka ut av avgjørelsen

Taket er nå et **antall regioner**, utledet av den FROSNE enheten
(R199): 12 på GPU, 2 på CPU, dobbelt i andrepasset. Tallene er valgt
slik at de treffer det tidsbudsjettet faktisk ga.

Byttet endrer hva som leses, så det ble målt på tre nivåer før det ble
standard:

| Nivå | Resultat |
|---|---|
| OCR-tekst, CPU | **0 av 10 sider** endret seg |
| OCR-tekst, GPU | 1 av 10 — «Homburg v. d. Höhe.» gikk fra **tre identiske linjer til én** |
| Spørsmålskorpus | **109 av 133 (82 %)** — nøyaktig som før, «samme svar hver gang» |

Den ene GPU-endringen er verdt å lese to ganger: de to regionene
tidsbudsjettet rakk EKSTRA, produserte duplikater. Taket fjernet dem.

### Resultat

| | sider/s | speedup | tekst |
|---|---|---|---|
| sekvensiell | 0,31 | 1,00× | — |
| 6 tråder, før | 0,30 | 0,97× | identisk |
| 6 tråder, med narrow lock | 0,43 | 1,38× | 2 sider avvek |
| **6 tråder + deterministisk tak** | **0,43** | **1,38×** | **identisk** |

Begge bryterne står nå PÅ (`OCR_PARALLELLE_SIDER`,
`OCR_DETERMINISTISK_TAK`), og en vakttest nekter kombinasjonen
parallellitet UTEN taket.

**Men gevinsten flytter fortsatt ingen arkitekturbeslutning:** 1,38× tar
25 arbeidere til 18, og begge tall er en klynge. Gapet til 5,2 sider/s
er ~16×, og §24.1-dommen fra forrige avsnitt står uendret.

### 500-siders maalingen paa nytt — gevinsten er stoerre i stor skala

Riggens 30 sider ga 1,38×. Den EKTE veien, gjennom serveren og
jobbsystemet, ga mer:

| | Basis (R200) | Med parallellitet |
|---|---|---|
| Tid | 31,4 min | **18,5 min** |
| Fart | 0,27 sider/s | **0,45 sider/s** |
| s/side | 3,76 | **2,22** |
| Dekning | 500/500 | **500/500** |
| Sidemarkører | 500/500 | **500/500** |
| `rapidocr`-regioner | 13 450 | **13 450** — identisk |
| `norhand+ufcn` | 318 | 250 |
| Policy-avvik | ingen | **ingen** |
| Strekkoder | 100 | 100 |

**1,70× totalt — mot 1,38× på 30 sider.** Og gevinsten deler seg i to,
for de to endringene ble målt hver for seg:

| | Tid | sider/s | Bidrag |
|---|---|---|---|
| R200-basis (tidsbudsjett, sekvensiell) | 31,4 min | 0,27 | — |
| Deterministisk tak, sekvensiell | 27,7 min | 0,30 | 1,13× |
| **Deterministisk tak + parallell** | **18,5 min** | **0,45** | **1,50×** |

Det deterministiske taket er altså ikke gratis i den forstand at det
koster noe — det GA 1,13×, fordi de 68 ekstra norhand-regionene
tidsbudsjettet rakk, produserte duplikater ingen hadde bruk for.

Grunnen til at parallelliteten gir mer i stor skala enn på 30 sider
står i R200-tallene: basiskjøringen DEGRADERTE over lengden (0,30 →
0,27 sider/s), mens den parallelle holdt 0,44–0,45 flatt gjennom hele
kjøringen. Parallelliteten fjernet degraderingen.

### Determinismen, prøvd i full skala

De to 500-siders kjøringene ble sammenlignet på selve teksten:

```
parallell    len 358641  sha256 67b875bc069797e0
sekvensiell  len 358641  sha256 67b875bc069797e0
IDENTISKE:   True
```

500 sider, 13 450 OCR-regioner, seks tråder mot én — **bit for bit det
samme dokumentet**. Det er den sterkeste determinismeprøven i prosjektet,
og den gjelder nettopp den veien produksjonen bruker.

**Én ærlighetsnote om målingen selv.** Riggen meldte FØRST at de to
hashene var ulike. Det var riggen som tok feil: den hashet hele
HTTP-svaret, og `/jobb/{id}/tekst` svarer med en JSON-konvolutt som
inneholder `jobb_id`. Id-en er ny for hver kjøring og har fast lengde —
så lengden stemte og hashen ikke, som ser nøyaktig ut som et
determinismebrudd. Samme familie som R200-feilen: måleriggen kan lyve på
samme måte som koden den måler, og et oppsiktsvekkende funn må
etterprøves før det blir en påstand.

### Kapasitet, oppdatert

| | sider/s | arbeidere ved peak |
|---|---|---|
| Basis (R200) | 0,27 | 25 |
| Deterministisk tak alene | 0,30 | 23 |
| **Tak + parallellitet** | **0,45** | **15** |

**Ti maskiner færre.** Det er en ekte sum — men den flytter fortsatt
ikke §24.1-dommen: gapet til 5,2 sider/s er 11,6× i stedet for 19×, og
én maskin er fortsatt ikke nok under belastningsantakelsen i §3. Ved
10 % skannet andel holder tre maskiner, og ved 20 sider/dokument holder
én. Antakelsen avgjør fortsatt mer enn optimaliseringen.

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

Hypotesen var at OCR på GPU ville løse dette. **Den ble prøvd, og
svaret er mer nyansert enn ventet — se §2b.**

### 3. Ikke en flaskehals: språkmodellen

0,41 s per kall. Utredningens Phase 3 (Borealis-pool, `--parallel N`)
er derfor **ikke** utløst av denne målingen.

---

## 2b. Forsøket: kan OCR få kortet tilbake?

Hypotesen fra første utkast av denne rapporten var at det å frigjøre
VRAM ville gi OCR kortet og løse kapasitetsproblemet. Den ble prøvd med
`BOREALIS_GPU_LAG` (flytter modellag til RAM). Resultatet endret
konklusjonen.

| Oppsett | Ledig VRAM | OCR-motor | s/side målt | Modell s/kall |
|---|---|---|---|---|
| Standard (alle lag på GPU) | 1149 MB | rapid på **CPU** | **3,42** (stabil) | **0,41** |
| `BOREALIS_GPU_LAG=28` | 2900 MB | easy på **GPU** | **38,97 · 5,31 · 4,94** | — |
| `BOREALIS_GPU_LAG=22` | 3570 MB | easy på **GPU** | **2,76** | 1,46 |

**Tre funn, i stigende viktighet:**

**(1) Ja, OCR kommer tilbake på GPU.** Frigjøres nok VRAM, bytter
motorvalget fra `rapid`/CPU til `easy`/GPU av seg selv. Mekanismen
virker som den skal.

**(2) Gevinsten er 1,24×, ikke 6,9×.** Første utkast av denne rapporten
antok ~0,5 s/side på GPU basert på R51. Det tallet ble målt på ETT
bilde uten håndskriftpass og uten Borealis residerende. Målt her, på en
ekte 10-siders bunke med alt i drift: **2,76 s/side**. R51-tallet er
ikke feil, men det gjelder en annen situasjon, og det var galt av meg å
regne kapasitet på det.

**(3) DET FARLIGE FUNNET: å så vidt krysse terskelen er verre enn å
la være.** Ved 2900 MB ledig — over kravet på 2600 — tar OCR GPU-en,
men har ikke rom å arbeide i. Tre kjøringer ga 38,97, 5,31 og 4,94
s/side: median **55 % tregere enn CPU-reserven**, med en hale 11×
verre. Ustabiliteten er selve problemet: en tjeneste som noen ganger
bruker 5 s/side og noen ganger 39 kan ikke kapasitetsplanlegges.

Terskelen `OCR_MINSTE_LEDIG_GPU_MB = 2600` er kalibrert for å hindre
KRASJ (R140) — ikke for å sikre FART. Mellom ca. 2600 og 3500 MB ledig
ligger det et bånd der systemet ruter seg selv inn i det verste av to
verdener. Se R194 og gjeldsposten i §9.

**Konsekvens for Q4-hypotesen:** Q4_K_M ville frigjort ~1500 MB og
landet på ~2650 MB ledig — midt i det farlige båndet. Den ville altså
sannsynligvis gjort ting VERRE, ikke bedre. Forsøket ble derfor ikke
gjennomført (llama.cpp nekter dessuten å rekvantisere fra q8_0, så det
ville krevd nedlasting av originalvekter eller en ferdig Q4-fil).

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

| OCR-vei | s/side | Arbeidere ved peak | Maskintimer/dag (snitt) |
|---|---|---|---|
| CPU-fallback (standard i dag) | 3,42 | **23** | 119,7 |
| GPU, trangt (`GPU_LAG=28`) | 5,31 median | **36** | 184,4 |
| **GPU med rom (`GPU_LAG=22`)** | **2,76** | **19** | 95,8 |

**Dette er hele historien om 8 GB-kortet: 23 arbeidere blir til 19.**
Ikke 4. Det finnes ingen innstilling på dette kortet som løser
kapasitetsproblemet — kortet er rett og slett for lite til å kjøre
begge modellene godt samtidig. Og prisen for de 19 er at modellen blir
3,6× tregere (0,41 → 1,46 s/kall), som rammer den interaktive bruken.

### Følsomhet — de to tallene ingen har målt

Utredningen merker begge som antakelser (§27). De styrer alt:

| Hvis … | OCR-sider/dag | Arbeidere (CPU / beste GPU-oppsett) |
|---|---|---|
| Skannet andel 50 % *(antatt)* | 125 000 | 23 / 19 |
| Skannet andel 10 % | 25 000 | 5 / 4 |
| Snitt 20 sider/dok, ikke 500 | 5 000 | 1 / 1 |

Legg merke til hva tabellen sier: **belastningsantakelsen betyr mer enn
maskinvaretrimmingen.** Å halvere sider/dokument sparer 22 arbeidere; å
trimme kortet sparer 4.

**Måles disse to før noe kjøpes, kan hele Phase 2–4 vise seg unødvendig.**
Et NAV-dokument på 500 sider i snitt er en arkivboks, ikke et brev.

---

## 4. Cost Baseline

Ingen kroner her — vi har ikke priser, og et oppdiktet tall er verre
enn ingen. Kostnaden uttrykkes i maskintimer, som er det som faktisk
skal kjøpes:

| Scenario | Maskintimer/dag | I praksis |
|---|---|---|
| 8 GB-kort, CPU-OCR, 125 000 sider | 119,7 | ~5 maskiner i døgndrift bare for snittlasten |
| 8 GB-kort, best mulig (GPU_LAG=22) | 95,8 | ~4 maskiner — og treg interaktiv bruk |
| 25 000 sider (10 % skannet) | 23,9 | Én maskin |
| 5 000 sider (20 sider/dok) | 4,8 | En brøkdel av én maskin |

Merk hva som IKKE står her: et scenario der 8 GB-kortet løser
250 000 sider. Det finnes ikke. Kostnaden styres av to ting — hvor mye
som faktisk er skannet, og om kortet er stort nok til at OCR og
språkmodell får plass ved siden av hverandre uten å trenge hverandre.

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
   sider/dokument. Dette er fortsatt den ene handlingen som kan endre
   alt — er andelen 10 % i stedet for 50 %, holder én maskin.
2. **Ikke bruk tid på å trimme 8 GB-kortet.** Det er prøvd og målt
   (§2b): beste oppnåelige er 19 arbeidere mot 23, og prisen er en 3,6×
   tregere språkmodell. Det er ikke en løsning, det er en omfordeling
   av smerten.
3. **Spesifiser kortet, ikke antall maskiner.** Behovet er ett kort der
   Borealis OG OCR får plass med rom — ikke så vidt plass (§2b, funn 3).
   Med Borealis Q8 (~4,5 GB residererende), OCR-arbeidsrom (~3,5 GB) og
   KV-cache: **minst 12 GB, helst 16.** `python -m delt.maskinprofil`
   sier hva et gitt kort vil gi før det kjøpes.
4. **Kjør riggen på målserveren** og skriv denne rapporten om.
5. **Så, og bare så,** vurder Phase 1 (lokal page fan-out).

Det viktigste denne rapporten endret: første utkast anbefalte å trimme
maskinen vi har. Målingen viste at det ikke virker. **Å oppdage det
koster noen timer; å oppdage det etter å ha bygget Phase 2 rundt en feil
antakelse koster måneder.**

---

## 8. Required ADRs

| ADR | Beslutning | Status |
|---|---|---|
| [0006](beslutninger/ADR-0006-plattformlag-utsatt.md) | Kø/database/multi-node utsatt til Phase 0 er målt | Gjeldende — denne rapporten er grunnlaget |
| Ny, foreslått | Kvantiseringsnivå for Borealis (Q8 vs Q4) | **Lukket uten forsøk** — Q4 ville landet på ~2650 MB ledig, midt i det farlige båndet (§2b) |
| Ny, foreslått | Heve `OCR_MINSTE_LEDIG_GPU_MB` fra 2600 til ~3500 | Åpen — n=3 på én maskin er for tynt til å endre en sikkerhetsterskel (R148-disiplin) |
| Ny, foreslått | OCR-motorvalg når VRAM er knapp | Åpen — dagens fallback er trygg, men kostbar |

## 9. Architectural Debt Register

| Gjeld | Hvorfor akseptert nå | Review-trigger |
|---|---|---|
| OCR faller til CPU på et fullt kort | Alternativet er nativt krasj (R140). Trygt, og målt bare 1,24× tregere enn beste GPU-oppsett | Kort med ≥12 GB |
| **Terskelen 2600 MB slipper OCR inn på et for trangt kort** | Målt median 55 % tregere enn CPU, med 11× hale (R194). Terskelen hindrer krasj, ikke treghet | Målinger fra 2+ maskiner før verdien endres |
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

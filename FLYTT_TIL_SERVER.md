# Flytte NAV dokument-API til en ny server (via USB)

Denne mappa (`nav`) er **selv-inneholdt**: prosjektets egen Python (`.pyruntime`),
alle pakker (`.python`), modeller (`modeller`), OCR-modeller (`.EasyOCR`) og de
nødvendige MSVC-DLL-ene ligger fysisk i mappa. Du kopierer HELE mappa og kjører
**ett** filnavn: `START_ALT.bat`. Ingen system-Python, ingen VC++-redist, ingen
internett kreves for kjerne-API-et.

Det ENESTE serveren må ha i tillegg er en **NVIDIA-GPU + driver** (maskinvare).

---

## Steg 0 — før du kopierer (på DENNE maskinen)

Kjør miljøsjekken for å bekrefte at kilden er grønn:

```bat
.pyruntime\python.exe skript\sjekk_miljo.py
```

Alt skal være `[OK]` (spesielt seksjon **[8] Portabilitet**). Da er mappa klar.

---

## Steg 1 — kopier mappa til USB-disken

> ⚠️ **VIKTIG: USB-disken MÅ være formatert som `exFAT` eller `NTFS` — IKKE `FAT32`.**
> `modeller\` inneholder filer på **4,6 GB** (safetensors), og FAT32 nekter filer
> over 4 GB. Sjekk i Utforsker → høyreklikk disken → Egenskaper → «Filsystem».
> Er den FAT32: formater til exFAT (høyreklikk → Formater → exFAT) først.

Med USB-disken som f.eks. `E:`:

```bat
robocopy D:\nav E:\nav /E /R:1 /W:1 /MT:16
```

`/E` tar med alt (også de gitignorerte `.python`, `.pyruntime`, `.venv-prefect`,
`modeller`, `.EasyOCR`, `.cache`, `cloudflared.exe`, `.env`). Total størrelse
≈ **37 GB**. Verifiser etterpå at `E:\nav` er ~37 GB.

**Sparetips (valgfritt):** Serveren kjører Borealis via GGUF-fila (3,9 GB), så
`modeller\borealis\` (de fire safetensors-filene, ~15 GB, transformers-fallback)
er ikke nødvendig i drift. Vil du spare plass/tid, hopp over den:
```bat
robocopy D:\nav E:\nav /E /R:1 /W:1 /MT:16 /XD "D:\nav\modeller\borealis"
```

---

## Steg 2 — på den nye serveren: sjekk GPU-driveren

Kjerne-OCR og `/spor` (Borealis) trenger NVIDIA-driver (CUDA 12.4-kompatibel,
Windows-driver **r550 eller nyere**). CUDA-toolkit trengs IKKE — det er buntet.

```bat
nvidia-smi
```

Ser du kortet + en drivernummer ≥ 550: klart. Får du «not recognized» eller for
gammel driver: installer nyeste **GeForce/Studio-driver** fra nvidia.com først.

---

## Steg 3 — kopier fra USB til serveren

Anbefalt måldisk/-sti: kort og uten mellomrom. `D:\nav` er best (da virker den
medfølgende Prefect-venv-en direkte, offline). Med USB som `E:`:

```bat
robocopy E:\nav D:\nav /E /R:1 /W:1 /MT:16
```

> Legger du mappa på en ANNEN sti enn `D:\nav`, virker alt likevel — men Prefect-UI
> (`:4200`) trenger å bygge sin venv på nytt første gang (krever internett den ene
> gangen). Dokument-API-et (`:8600`) påvirkes ikke.

---

## Steg 4 — smoketest på serveren (bekreft at flyttingen lyktes)

```bat
cd /d D:\nav
set PYTHONNOUSERSITE=1
set EASYOCR_MODULE_PATH=%CD%\.EasyOCR
.pyruntime\python.exe skript\sjekk_miljo.py
```

Les rapporten:
- **ALT GRØNT** → serveren er klar, gå til steg 6.
- **[3] GPU** advarsel → driveren mangler/for gammel (steg 2).
- **[8] msvcp140 ikke fra nav** → kopieringen tok ikke med `.pyruntime\`-DLL-ene
  (kopier hele mappa på nytt), eller installer VC++ 2015-2022 x64-redist.
- **[5]/[6] modeller mangler** → USB-kopien var ufullstendig (kopier på nytt).

---

## Steg 5 — (valgfritt) slå på autentisering før ekstern tilgang

Serveren kjører **åpent uten X-API-Key** med mindre `API_NOKKEL` er satt som
ekte maskin-miljøvariabel. Skal API-et eksponeres (cloudflared-tunnel), sett den
FØR start (krever admin-cmd):

```bat
setx /M API_NOKKEL "en-sterk-tilfeldig-streng"
```

(`.env`-fila leses ikke av koden i dag — bruk `setx /M`.)

---

## Steg 6 — start alt (ETT filnavn)

Dobbeltklikk **`START_ALT.bat`** — eller fra cmd:

```bat
D:\nav\START_ALT.bat
```

Den bruker `.pyruntime`, setter nav-lokalt miljø selv, og starter:
- **API** → http://127.0.0.1:8600/hjelp
- **Prefect-UI** → http://127.0.0.1:4200 (hoppes pent over hvis venv ikke kan bygges)

Åpne http://127.0.0.1:8600/dokumentasjon (Swagger) og test `/analyser` på en
skannet PDF **og** `/spor` — det er disse som avslører manglende GPU/driver.

---

## Steg 7 — (valgfritt) ekstern tilgang via tunnel

```bat
D:\nav\START_SERVER.bat
```
eller manuelt:
```bat
D:\nav\cloudflared.exe tunnel --url http://localhost:8600
```
Den offentlige lenken vises i tunnel-vinduet (`https://….trycloudflare.com`).

---

## Rask sjekkliste

- [ ] USB er exFAT/NTFS (ikke FAT32)
- [ ] `robocopy … /E` — hele mappa (~37 GB) kopiert
- [ ] `nvidia-smi` viser kortet, driver ≥ 550
- [ ] `sjekk_miljo.py` = ALT GRØNT
- [ ] (ved eksponering) `setx /M API_NOKKEL …`
- [ ] `START_ALT.bat` → `/hjelp` svarer, `/spor` gir svar

# Offline-installasjon på isolert server — komplett kravstudie

For flytting av det lokale dokument-API-et til en server UTEN internett.
Alt må være med på forhånd; ingenting kan lastes ned eller feilsøkes
mot nett på serveren. Denne studien dekker HVER avhengighet.

**Omfang:** det lokale, selvstendige dokument-API-et
(`skript/dokument_api.py` + `delt/`) — alt vi har bygd og som kjører
native med GPU. Den fulle Docker-pipelinen (`tjenester/`) er en SEPARAT
distribusjon (krever offline Docker-images, Postgres, Redis, Milvus) og
dekkes IKKE her — si fra hvis den også skal offline-pakkes.

---

## 1. Maskinvare- og systemkrav (serveren)

| Krav | Detalj | Verifiseres av |
|---|---|---|
| OS | Windows x64 (samme som byggemaskinen) | `sjekk_miljo.py` [1] |
| Python | 3.11.x (nøyaktig — pip-hjul er ABI-bundet til minor-versjon) | [1] |
| RAM | ≥ 16 GB (32 GB anbefalt; store dokumenter + modell) | manuelt |
| Disk | ~15 GB: offline_pakke (~8 GB) + modeller (~4–17 GB) + prosjekt | manuelt |
| GPU (anbefalt) | NVIDIA med **driver ≥ 550** (for CUDA 12.4) | [3] |
| GPU-minne | 8 GB for Borealis 4B (mer for 12B/27B) | [3] |

**Uten GPU:** systemet KJØRER på CPU, men OCR og Borealis blir tregt.
`sjekk_miljo.py` advarer tydelig hvis GPU/CUDA mangler.

---

## 2. NVIDIA-driver — den ENE tingen pip ikke kan fikse

`torch` er CUDA 12.4-utgaven. Selve CUDA-runtime følger med torch-hjulet,
men **NVIDIA-driveren** må være installert på serveren av IT på forhånd:

- Sjekk på serveren: kommandoen `nvidia-smi` skal vise kortet og en
  driverversjon ≥ 550.
- Er driveren for gammel/mangler: torch faller til CPU (systemet virker,
  men tregt) — `sjekk_miljo.py` [3] sier fra.
- Driveren er IKKE en pip-pakke og kan ikke pakkes i offline_pakke.
  Trenger serveren ny driver, må IT laste den (fra en nett-PC) på
  forhånd. Dette er den eneste eksterne forutsetningen.

---

## 3. Python-avhengigheter (alle pakkes automatisk)

Låste versjoner i `krav_lokal.txt`. `pakk_for_offline.py` henter disse
+ ALLE transitive avhengigheter som hjul.

**Kjerne (OCR/bilde/PDF):** PyMuPDF, numpy, pillow,
opencv-python-headless, easyocr, rapidocr-onnxruntime, onnxruntime, pyzbar
**Språkmodell:** torch+torchvision (cu124), llama-cpp-python (cu124),
transformers, accelerate, bitsandbytes, huggingface-hub
**Dokumentformater:** python-docx, openpyxl
**Nett/verktøy:** requests, beautifulsoup4 · **Test:** pytest

Kritisk om indekser: `torch`/`torchvision` (CUDA) og `llama-cpp-python`
(CUDA) finnes IKKE på vanlig PyPI — pakkeskriptet henter dem fra
PyTorch- og abetlen-indeksene. Offline installeres ALT fra én mappe.

---

## 4. Skjulte auto-nedlastede ressurser (den vanligste fellen)

Disse lastes normalt ned fra nett ved FØRSTE bruk — og vil da FEILE på
en isolert server. Pakkes derfor eksplisitt:

| Ressurs | Hva | Håndtering |
|---|---|---|
| **EasyOCR-modeller** | `craft_mlt_25k.pth` + `latin_g2.pth` (~93 MB) i `~/.EasyOCR/model` | Kopieres av pakkeskriptet; installer legger dem på serveren. **Uten disse feiler all OCR.** |
| RapidOCR-modeller | 3 ONNX-filer | Følger MED pip-pakken — ingen ekstra handling |
| pyzbar/zbar-DLL | Strekkode-dekoder (C-bibliotek) | Følger MED Windows-hjulet |
| Borealis-modell | GGUF (~4 GB) eller transformers (~16 GB) | Kopieres SEPARAT (se pkt. 5) |

---

## 5. Modeller (kopieres separat — ikke i offline_pakke)

Modeller er for store for pip. Kopier `modeller/`-mappen manuelt til
serveren (USB/nettverk). Minimum for det lokale API-et:

- `modeller/borealis-gguf/*.gguf` — Borealis (llama.cpp-backend, anbefalt)
  ELLER `modeller/borealis/` — transformers-utgaven (fallback)
- EasyOCR-modellene håndteres av installer (pkt. 4)

`sjekk_miljo.py` [6] bekrefter at en Borealis-modell finnes.

---

## 6. Fremgangsmåte

**På DENNE maskinen (med nett):**
```
python skript/pakk_for_offline.py
```
Lager `offline_pakke/` (~8 GB: alle hjul + EasyOCR-modeller + manifest).

**Kopier til serveren:** hele prosjektmappen, `offline_pakke/`, og
`modeller/`.

**På SERVEREN (uten nett):**
```
python installer_offline.py     # installerer alt + kjører sjekk
```
Eller manuelt:
```
python -m pip install --no-index --find-links offline_pakke/wheels -r krav_lokal.txt
python skript/sjekk_miljo.py
```

**Start tjenesten:**
```
python skript/dokument_api.py
```

---

## 7. Verifisering — sjekklisten `sjekk_miljo.py` kjører

1. Python 3.11 · 2. Alle 17 bibliotekene importerer · 3. GPU/CUDA
tilgjengelig · 4. zbar-DLL lastet · 5. EasyOCR-modeller på plass ·
6. Borealis-modell finnes · 7. Ekte deterministisk uttrekk gir dato +
beløp + orgnr. Grønt på alle sju = systemet er klart.

---

## 8. Brannmur / port

- API-et lytter på port **8600** (`DOKUMENT_API_PORT` for å endre).
- Åpne porten lokalt i serverens brannmur for klientene som skal nå den.
- cloudflared-tunnelen er IKKE aktuell på en isolert server (krever
  utgående nett) — klientene når API-et direkte på serverens IP:8600.
- Vil du kreve autentisering: sett `API_NOKKEL` før start (klientene
  sender `X-API-Key`).

---

## 9. Feilsøking uten nett (siden du ikke kan spørre om hjelp)

| Symptom | Årsak | Løsning |
|---|---|---|
| `pip install` feiler på et hjul | Server-plattform/Python ≠ byggemaskin | Bygg pakken på nytt på en maskin lik serveren |
| OCR henger/feiler ved oppstart | EasyOCR-modeller mangler | Kopier `offline_pakke/easyocr_modeller/*.pth` til `~/.EasyOCR/model/` |
| `torch.cuda.is_available()` = False | Driver < 550 eller mangler | IT installerer nyere NVIDIA-driver; til da kjører alt på CPU |
| `llama.dll` lastes ikke | CUDA-DLL-sti | dokument_api forhåndslaster torch sine DLL-er automatisk — sørg for at torch er installert |
| Borealis lastes ikke | Ingen .gguf i modeller/borealis-gguf | Kopier modellfilen dit; `sjekk_miljo.py` [6] bekrefter |
| pyzbar ImportError | zbar-DLL | Reinstaller pyzbar-hjulet fra wheels-mappen |

Alt annet: `sjekk_miljo.py` peker på nøyaktig hva som mangler.

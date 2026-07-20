"""
Regionbasert OCR-ruting — leser blandede dokumenter (trykt + håndskrift)
med riktig modell per tekstregion, og fletter resultatet i leserekkefølge.

Flyt per side:
    1) EasyOCR detekterer alle tekstregioner og leser dem
       (rask, svært god på trykt tekst)
    2) Regioner med lav lesekonfidens leses I TILLEGG av norhand
       (Sprakbanken/TrOCR-norhand-v3 — spesialist på norsk håndskrift)
    3) Per region vinner motoren med høyest konfidens — ingen gjetning,
       begge motorers svar og konfidens beholdes i resultatet
    4) Alle regioner flettes i leserekkefølge: linjegruppering på vertikal
       overlapp (median-høyde-basert), topp→bunn, venstre→høyre.
       Flettealgoritmen (flett_regioner) er ren funksjon — testbar alene.

Modellene lastes én gang (lat), GPU med CPU-fallback ved for lite ledig
minne (R51 — se MINSTE_LEDIG_GPU under).
Trådsikker: én lås rundt motorkallene (GPU-en tar én jobb om gangen).
"""
import os
import threading

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NORHAND_STI = os.path.join(ROT, "modeller", "norhand")

# Under denne EasyOCR-konfidensen prøves norhand i tillegg på regionen
TERSKEL_TRYKT = 0.60

# R51: EasyOCR trenger ledig VRAM til arbeidsbuffere PER SIDE, ikke bare
# til vektene. Er kortet nesten fullt (typisk: Borealis har lagt beslag
# på det), lekker allokeringene over i Windows' delte minne og går over
# PCIe — GPU-en viser 100 % bruk mens den i praksis står og venter.
# Målt på RTX 3070 8 GB: 0,4 s med ledig minne mot 17 s uten.
# CPU er da BEDRE enn en overfylt GPU, så vi velger CPU bevisst.
#
# Kravet er satt etter måling, ikke gjetning: EasyOCRs vekter tar ~310
# MiB, og arbeidsbufferne skalerer med bildestørrelsen. Etter at den
# unødige oppskaleringen ble fjernet (ocr_skala i dokument_api) er
# sidebildene ~4× mindre, så 800 MiB gir god margin for en A4-side.
MINSTE_LEDIG_GPU_MB = int(os.environ.get("OCR_MINSTE_LEDIG_GPU_MB", "800"))

_las = threading.Lock()

# Delt GPU-lås: OCR og språkmodellen ligger på SAMME kort. Kjører de
# samtidig, konkurrerer de om minnet og begge blir tregere (målt: modell
# alene 3,3 s → 18,5 s samtidig med OCR). Denne låsen slippes bare rundt
# faktisk GPU-arbeid, så OCR på CPU aldri blokkerer modellen.
GPU_LAS = threading.RLock()

_easyocr = {"leser": None, "gpu": False}
_norhand = {"prosessor": None, "modell": None, "enhet": None}


def ledig_gpu_mb() -> float:
    """Ledig VRAM i MiB — 0.0 når det ikke finnes CUDA-kort."""
    try:
        import torch
        if not torch.cuda.is_available():
            return 0.0
        return torch.cuda.mem_get_info()[0] / (1024 * 1024)
    except Exception:
        return 0.0


def frigjor_gpu() -> None:
    """Gir PyTorch sine ubrukte, hurtigbufrede blokker tilbake til
    driveren. Frigjør IKKE modellvekter (verken EasyOCRs eller
    llama.cpp sine) — de skal bli liggende, ellers må de lastes på nytt
    for hver forespørsel. Kalles etter hver OCR-side."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def motorstatus() -> dict:
    """Hvilken enhet hver motor faktisk endte på — eksponeres i
    GET /hjelp så en stille CPU-fallback aldri går ubemerket hen."""
    return {
        "ocr_motor_valgt": OCR_MOTOR,
        "ocr_motor_i_bruk": _valgt["motor"] or "ikke_valgt_enda",
        "easyocr_enhet": ("ikke_lastet" if _easyocr["leser"] is None
                          else ("gpu" if _easyocr["gpu"] else "cpu")),
        "norhand_enhet": _norhand["enhet"] or "ikke_lastet",
        "ledig_gpu_mb": round(ledig_gpu_mb()),
        "krever_ledig_gpu_mb": MINSTE_LEDIG_GPU_MB,
    }


# ------------------------------------------------------------------ #
#  Motorer (lat lasting, GPU → CPU-fallback)                          #
# ------------------------------------------------------------------ #

def _hent_easyocr():
    if _easyocr["leser"] is None:
        import easyocr
        # R51: at et CUDA-kort FINNES er ikke nok — det må være plass på
        # det. torch.cuda.is_available() sier bare det første, og en
        # overfylt GPU er målt 20× tregere enn CPU (se toppen av filen).
        ledig = ledig_gpu_mb()
        gpu = ledig >= MINSTE_LEDIG_GPU_MB
        if not gpu and ledig > 0:
            print(f"  [OCR] Bare {ledig:.0f} MiB ledig VRAM (krever "
                  f"{MINSTE_LEDIG_GPU_MB}) — EasyOCR kjører på CPU, som er "
                  "raskere enn en overfylt GPU.")
        _easyocr.update(leser=easyocr.Reader(["no", "en"], gpu=gpu), gpu=gpu)
    return _easyocr["leser"]


# Valgbar motor for trykt tekst (generelt motorlag):
#   auto (standard) — velger etter hva maskinen faktisk har plass til:
#                     ledig VRAM  → EasyOCR på GPU (best lesekvalitet)
#                     fullt kort  → RapidOCR på CPU
#   easy            — tving EasyOCR (GPU om det er plass, ellers CPU)
#   rapid           — tving RapidOCR på CPU; avlaster GPU-en helt
#
# R51, målt på RTX 3070 8 GB med Borealis Q8_0 lastet (samme bilde):
#   EasyOCR  GPU  0,5 s  |  EasyOCR  CPU  6–8 s  |  EasyOCR overfylt GPU  17 s
#   RapidOCR CPU  1,1 s
# Derfor: når kortet er fullt er RapidOCR på CPU ~7× raskere enn å tvinge
# EasyOCR gjennom en CPU den ikke er bygget for — og den lar samtidig
# språkmodellen beholde GPU-en for seg selv, så de to kan jobbe PARALLELT
# i stedet for å vente på hverandre.
OCR_MOTOR = os.environ.get("OCR_MOTOR", "auto").strip().lower()
_rapid = {"motor": None}
_valgt = {"motor": None}      # hva auto faktisk landet på


def _hent_rapid():
    if _rapid["motor"] is None:
        from rapidocr_onnxruntime import RapidOCR
        _rapid["motor"] = RapidOCR()
    return _rapid["motor"]


def _velg_motor_for_maskinen() -> str:
    """Avgjør motor én gang, ut fra ledig VRAM her og nå."""
    if _valgt["motor"] is not None:
        return _valgt["motor"]
    if OCR_MOTOR in ("easy", "rapid"):
        _valgt["motor"] = OCR_MOTOR
        return OCR_MOTOR
    ledig = ledig_gpu_mb()
    if ledig >= MINSTE_LEDIG_GPU_MB:
        _valgt["motor"] = "easy"          # GPU har plass → beste kvalitet
    else:
        try:                              # fullt kort → rask CPU-motor
            _hent_rapid()
            _valgt["motor"] = "rapid"
            print(f"  [OCR] Bare {ledig:.0f} MiB ledig VRAM — bruker "
                  "RapidOCR på CPU (~1 s/side) i stedet for EasyOCR, og "
                  "lar språkmodellen beholde GPU-en.")
        except Exception as exc:
            _valgt["motor"] = "easy"      # RapidOCR mangler → EasyOCR/CPU
            print(f"  [OCR] RapidOCR utilgjengelig ({exc}) — EasyOCR på CPU.")
    return _valgt["motor"]


def _les_regioner(bilde_np) -> list:
    """Motoruavhengig regionlesing: liste av (punkter, tekst, konfidens)."""
    if _velg_motor_for_maskinen() == "rapid":
        try:
            resultat, _ = _hent_rapid()(bilde_np)
            return [(r[0], r[1], float(r[2])) for r in (resultat or [])]
        except Exception:
            pass   # RapidOCR feilet på denne siden → fall tilbake til EasyOCR
    return _hent_easyocr().readtext(bilde_np, detail=1, paragraph=False)


def _hent_norhand():
    """Laster TrOCR-norhand-v3. fp16 på GPU hvis det er plass, ellers CPU."""
    if _norhand["modell"] is None:
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        prosessor = TrOCRProcessor.from_pretrained(NORHAND_STI)
        modell = VisionEncoderDecoderModel.from_pretrained(NORHAND_STI)
        modell.eval()
        enhet = "cpu"
        try:
            import torch
            # R51: samme minnekrav som EasyOCR — et fullt kort gjør
            # norhand tregere enn CPU, ikke raskere
            if torch.cuda.is_available() and ledig_gpu_mb() >= MINSTE_LEDIG_GPU_MB:
                modell = modell.half().to("cuda")
                enhet = "cuda"
        except Exception:
            modell = modell.float().to("cpu")
            enhet = "cpu"
        _norhand.update(prosessor=prosessor, modell=modell, enhet=enhet)
    return _norhand["prosessor"], _norhand["modell"], _norhand["enhet"]


def _norhand_les(bilde_np) -> tuple:
    """Leser ett region-utsnitt med norhand. Returnerer (tekst, konfidens).
    Konfidensen er geometrisk snitt av token-sannsynlighetene."""
    import numpy as np
    import torch
    from PIL import Image

    prosessor, modell, enhet = _hent_norhand()
    bilde = Image.fromarray(bilde_np).convert("RGB")
    piksler = prosessor(images=bilde, return_tensors="pt").pixel_values
    if enhet == "cuda":
        piksler = piksler.half().to("cuda")
    try:
        with torch.no_grad():
            ut = modell.generate(
                piksler, max_new_tokens=96,
                output_scores=True, return_dict_in_generate=True,
            )
    except torch.cuda.OutOfMemoryError:
        # GPU full (Borealis + EasyOCR) → flytt norhand til CPU og prøv igjen
        _norhand.update(modell=modell.float().to("cpu"), enhet="cpu")
        return _norhand_les(bilde_np)

    sekvens = ut.sequences[0]
    tekst = prosessor.batch_decode(ut.sequences, skip_special_tokens=True)[0].strip()

    # Geometrisk snitt av sannsynligheten for hvert valgt token
    sannsynligheter = []
    gen_tokens = sekvens[1:]
    for tok, score in zip(gen_tokens, ut.scores):
        p = torch.softmax(score[0].float(), dim=-1)[tok].item()
        sannsynligheter.append(max(p, 1e-9))
    if sannsynligheter:
        konf = float(np.exp(np.mean(np.log(sannsynligheter))))
    else:
        konf = 0.0
    return tekst, konf


# ------------------------------------------------------------------ #
#  Skriftslag-klassifisering per region (håndskrift vs trykt)         #
# ------------------------------------------------------------------ #

def _skriftslag(bilde_np, tekst: str) -> str:
    """Klassifiserer et region-utsnitt som «handskrift» eller «trykt»
    med et billig bildetrekk: i trykt tekst er hver bokstav en egen
    sammenhengende komponent (~1 komponent per tegn), mens løkkeskrift/
    signaturer binder bokstavene sammen (langt færre komponenter per
    tegn). Uavhengig av OCR-konfidens — fanger håndskrift som EasyOCR
    leser trygt."""
    try:
        import cv2
        tegn_antall = sum(1 for c in tekst if not c.isspace())
        if tegn_antall < 3:
            return "trykt"     # for kort til å avgjøre
        grat = cv2.cvtColor(bilde_np, cv2.COLOR_RGB2GRAY)
        _, binaer = cv2.threshold(
            grat, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )
        antall, _, stats, _ = cv2.connectedComponentsWithStats(binaer, connectivity=8)
        # Filtrer bort støyprikker (små flekker fra skanning)
        min_areal = max(6, (bilde_np.shape[0] // 12) ** 2)
        komponenter = sum(
            1 for i in range(1, antall) if stats[i, cv2.CC_STAT_AREA] >= min_areal
        )
        return "handskrift" if komponenter / tegn_antall < 0.55 else "trykt"
    except Exception:
        return "trykt"


# ------------------------------------------------------------------ #
#  Arbitrering mellom motorene (ren funksjon — testbar alene)         #
# ------------------------------------------------------------------ #

def velg_motor(easy_tekst: str, easy_konf: float,
               nh_tekst: str, nh_konf: float) -> str:
    """Velger hvilken motor som vinner en region.

    norhands konfidens (geometrisk token-snitt) er systematisk overmodig
    og IKKE kalibrert mot EasyOCR sin — naiv «høyest vinner» ødelegger
    korrekt lest trykt tekst. Derfor:
      * Regioner med tall (beløp, datoer, nummer) beskyttes: norhand er
        trent på historisk håndskrift og leser ofte feil på sifre —
        EasyOCR beholdes med mindre den nesten helt har gitt opp.
      * norhand vinner bare når EasyOCR klart har feilet (< 0.45) eller
        med solid margin (> 0.30)."""
    if not nh_tekst:
        return "easyocr"
    sifre = sum(c.isdigit() for c in easy_tekst)
    if sifre >= 2 and easy_konf >= 0.35:
        return "easyocr"
    if easy_konf < 0.45 and nh_konf >= 0.50:
        return "norhand"
    if nh_konf - easy_konf > 0.30:
        return "norhand"
    return "easyocr"


# ------------------------------------------------------------------ #
#  Fletting i leserekkefølge (ren funksjon — testbar alene)           #
# ------------------------------------------------------------------ #

def flett_regioner(regioner: list) -> str:
    """Fletter regioner til tekst i leserekkefølge.

    Algoritme:
      1) Linjegruppering: regioner hvis vertikale midtpunkt ligger innenfor
         0.6 × medianhøyde av linjens løpende midtpunkt, hører til samme linje.
      2) Linjer sorteres topp→bunn, regioner i hver linje venstre→høyre.
      3) Regioner på samme linje skilles med mellomrom, linjer med linjeskift.

    regioner: liste av {"boks": [x0, y0, x1, y1], "tekst": str, ...}
    """
    regioner = [r for r in regioner if r.get("tekst", "").strip()]
    if not regioner:
        return ""

    hoyder = sorted(r["boks"][3] - r["boks"][1] for r in regioner)
    median_hoyde = hoyder[len(hoyder) // 2]
    terskel = max(median_hoyde * 0.6, 1.0)

    sortert = sorted(
        regioner, key=lambda r: ((r["boks"][1] + r["boks"][3]) / 2, r["boks"][0])
    )
    linjer = []   # [{"midt": float, "regioner": [...]}]
    for r in sortert:
        midt = (r["boks"][1] + r["boks"][3]) / 2
        for linje in linjer:
            if abs(midt - linje["midt"]) <= terskel:
                linje["regioner"].append(r)
                linje["midt"] = sum(
                    (q["boks"][1] + q["boks"][3]) / 2 for q in linje["regioner"]
                ) / len(linje["regioner"])
                break
        else:
            linjer.append({"midt": midt, "regioner": [r]})

    linjer.sort(key=lambda l: l["midt"])
    ut = []
    for linje in linjer:
        linje["regioner"].sort(key=lambda r: r["boks"][0])
        ut.append(" ".join(r["tekst"].strip() for r in linje["regioner"]))
    return "\n".join(ut)


# ------------------------------------------------------------------ #
#  Hovedinngang: OCR av én side med regionruting                      #
# ------------------------------------------------------------------ #

def ocr_side(bilde_np) -> dict:
    """OCR av ett sidebilde (numpy RGB) med regionbasert modellruting.

    Returnerer {"tekst": flettet tekst, "regioner": [
        {"boks": [x0,y0,x1,y1], "tekst": str, "motor": "easyocr"|"norhand",
         "konfidens": float, "easyocr_tekst": str, "easyocr_konfidens": float,
         "norhand_tekst": str|None, "norhand_konfidens": float|None}
    ]}"""
    with _las:
        # Motoren velges og lastes her (ikke inne i løkken) så vi VET om
        # den havnet på GPU før vi bestemmer om GPU-låsen trengs.
        if _velg_motor_for_maskinen() == "easy":
            _hent_easyocr()
        try:
            if _paa_gpu():
                # OCR og språkmodellen deler samme kort — la dem aldri
                # kjøre samtidig, ellers konkurrerer de om minnet og
                # begge blir tregere (målt: 3,3 s → 18,5 s).
                with GPU_LAS:
                    return _ocr_side_intern(bilde_np)
            # OCR på CPU (R51-fallback): ingen GPU-lås, så språkmodellen
            # kan svare parallelt på kortet uten å vente på OCR.
            return _ocr_side_intern(bilde_np)
        finally:
            frigjor_gpu()


def _paa_gpu() -> bool:
    """Bruker noen av OCR-motorene GPU-en akkurat nå?"""
    return bool(_easyocr["gpu"]) or _norhand["enhet"] == "cuda"


def _ocr_side_intern(bilde_np) -> dict:
    """Selve sidebehandlingen. Kalles alltid med _las holdt (og med
    GPU_LAS i tillegg når motorene ligger på GPU)."""
    funn = _les_regioner(bilde_np)

    h, b = bilde_np.shape[0], bilde_np.shape[1]
    regioner = []
    for punkter, tekst, konf in funn:
        xs = [p[0] for p in punkter]
        ys = [p[1] for p in punkter]
        x0, y0 = max(int(min(xs)) - 3, 0), max(int(min(ys)) - 3, 0)
        x1, y1 = min(int(max(xs)) + 3, b), min(int(max(ys)) + 3, h)

        region = {
            "boks": [x0, y0, x1, y1],
            "tekst": tekst.strip(),
            "motor": "easyocr",
            "konfidens": float(konf),
            "easyocr_tekst": tekst.strip(),
            "easyocr_konfidens": float(konf),
            "norhand_tekst": None,
            "norhand_konfidens": None,
        }

        # Lav konfidens → sannsynlig håndskrift/degradert → prøv norhand
        if konf < TERSKEL_TRYKT and (x1 - x0) >= 8 and (y1 - y0) >= 8:
            try:
                nh_tekst, nh_konf = _norhand_les(bilde_np[y0:y1, x0:x1])
                region["norhand_tekst"] = nh_tekst
                region["norhand_konfidens"] = round(nh_konf, 3)
                if velg_motor(tekst.strip(), float(konf), nh_tekst, nh_konf) == "norhand":
                    region["tekst"] = nh_tekst
                    region["motor"] = "norhand"
                    region["konfidens"] = nh_konf
            except Exception:
                pass   # norhand utilgjengelig → behold EasyOCR-lesningen

        region["konfidens"] = round(float(region["konfidens"]), 3)
        # Visuell klassifisering: håndskrift eller trykt — uavhengig
        # av hvilken motor som leste regionen
        region["skrift"] = _skriftslag(bilde_np[y0:y1, x0:x1], region["tekst"])
        if region["motor"] == "norhand":
            region["skrift"] = "handskrift"
        regioner.append(region)

    return {"tekst": flett_regioner(regioner), "regioner": regioner}

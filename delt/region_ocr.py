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

Modellene lastes én gang (lat), GPU med CPU-fallback ved fullt minne.
Trådsikker: én lås rundt motorkallene (GPU-en tar én jobb om gangen).
"""
import os
import threading

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NORHAND_STI = os.path.join(ROT, "modeller", "norhand")

# Under denne EasyOCR-konfidensen prøves norhand i tillegg på regionen
TERSKEL_TRYKT = 0.60

_las = threading.Lock()
_easyocr = {"leser": None, "gpu": False}
_norhand = {"prosessor": None, "modell": None, "enhet": None}


# ------------------------------------------------------------------ #
#  Motorer (lat lasting, GPU → CPU-fallback)                          #
# ------------------------------------------------------------------ #

def _hent_easyocr():
    if _easyocr["leser"] is None:
        import easyocr
        try:
            import torch
            gpu = torch.cuda.is_available()
        except Exception:
            gpu = False
        _easyocr.update(leser=easyocr.Reader(["no", "en"], gpu=gpu), gpu=gpu)
    return _easyocr["leser"]


# Valgbar motor for trykt tekst (generelt motorlag):
#   easy  (standard) — EasyOCR på GPU; raskest på denne maskinen (målt)
#   rapid            — RapidOCR/PP-modeller på CPU; avlaster GPU-en
OCR_MOTOR = os.environ.get("OCR_MOTOR", "easy").strip().lower()
_rapid = {"motor": None}


def _les_regioner(bilde_np) -> list:
    """Motoruavhengig regionlesing: liste av (punkter, tekst, konfidens)."""
    if OCR_MOTOR == "rapid":
        try:
            if _rapid["motor"] is None:
                from rapidocr_onnxruntime import RapidOCR
                _rapid["motor"] = RapidOCR()
            resultat, _ = _rapid["motor"](bilde_np)
            return [(r[0], r[1], float(r[2])) for r in (resultat or [])]
        except Exception:
            pass   # RapidOCR utilgjengelig → EasyOCR
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
            if torch.cuda.is_available():
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

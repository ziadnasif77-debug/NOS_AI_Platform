# -*- coding: utf-8 -*-
"""Håndskriftspesifikk tekstlinje-segmentering med Doc-UFCN (NorHand).

Bruker Teklia/doc-ufcn-norhand-v1-line — en liten (49 MB) U-FCN trent på
NorHand-datasettet (norske håndskrevne dokumenter) — til å finne
tekstLINJENE på en side. Motivasjon: EasyOCR er trent på trykt/scene-
tekst og segmenterer løkkeskrift dårlig, mens TrOCR-norhand er en
LINJEmodell som står og faller på gode linjeutsnitt.

Modellarkitekturen og for-/etterbehandlingen under er en tro,
selvstendig port av doc-ufcn-biblioteket (MIT-lisens, Teklia
<https://gitlab.teklia.com/dla/doc-ufcn>) — selve pip-pakken støtter
ikke Python 3.11, derfor bæres de ~150 nødvendige linjene her med
attribusjon i stedet for å installere den.

Kjører på CPU som standard (en 49 MB CNN på 768 px tar ~1–2 s og
koster NULL GPU-minne ved siden av Borealis). DOC_UFCN_ENHET=cuda
tvinger GPU om ønskelig.
"""
import os
import threading

import numpy as np

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELL_STI = os.environ.get("DOC_UFCN_STI",
                            os.path.join(ROT, "modeller", "doc-ufcn-norhand"))
ENHET = os.environ.get("DOC_UFCN_ENHET", "cpu")

# Fra parameters.yml i modellrepoet (normalisering + klasser).
MEAN = [209, 204, 191]
STD = [51, 51, 50]
INPUT_STORRELSE = 768
MIN_KOMPONENT = 50          # min. konturareal (piksler) — som i originalen
KLASSER = 3                 # bakgrunn, horisontal linje, vertikal linje

_tilstand = {"modell": None, "feilet": False}
_las = threading.Lock()


def tilgjengelig() -> bool:
    """Er linjemodellen på plass (og har ikke feilet)?"""
    return (not _tilstand["feilet"]
            and os.path.isfile(os.path.join(MODELL_STI, "model.pth")))


# ------------------------------------------------------------------ #
#  Arkitektur — tro port av doc_ufcn/model.py (MIT, Teklia)           #
# ------------------------------------------------------------------ #

def _bygg_modell():
    import torch

    class DocUFCNModell(torch.nn.Module):
        def __init__(self, antall_klasser):
            super().__init__()
            self.dilated_block1 = self._dilatert_blokk(3, 32)
            self.dilated_block2 = self._dilatert_blokk(32, 64)
            self.dilated_block3 = self._dilatert_blokk(64, 128)
            self.dilated_block4 = self._dilatert_blokk(128, 256)
            self.pool = torch.nn.MaxPool2d(2, 2)
            self.conv_block1 = self._konv_blokk(256, 128)
            self.conv_block2 = self._konv_blokk(256, 64)
            self.conv_block3 = self._konv_blokk(128, 32)
            self.last_conv = torch.nn.Conv2d(64, antall_klasser, 3,
                                             stride=1, padding=1)
            self.softmax = torch.nn.Softmax(dim=1)

        @staticmethod
        def _dilatert_blokk(inn, ut):
            lag = [torch.nn.Conv2d(inn, ut, 3, stride=1, dilation=1,
                                   padding=1, bias=False),
                   torch.nn.BatchNorm2d(ut, track_running_stats=False),
                   torch.nn.ReLU(inplace=True), torch.nn.Dropout(p=0.4)]
            for d in (2, 4, 8, 16):
                lag += [torch.nn.Conv2d(ut, ut, 3, stride=1, dilation=d,
                                        padding=d, bias=False),
                        torch.nn.BatchNorm2d(ut, track_running_stats=False),
                        torch.nn.ReLU(inplace=True), torch.nn.Dropout(p=0.4)]
            return torch.nn.Sequential(*lag)

        @staticmethod
        def _konv_blokk(inn, ut):
            return torch.nn.Sequential(
                torch.nn.Conv2d(inn, ut, 3, stride=1, padding=1, bias=False),
                torch.nn.BatchNorm2d(ut, track_running_stats=False),
                torch.nn.ReLU(inplace=True), torch.nn.Dropout(p=0.4),
                torch.nn.ConvTranspose2d(ut, ut, 2, stride=2, bias=False),
                torch.nn.BatchNorm2d(ut, track_running_stats=False),
                torch.nn.ReLU(inplace=True), torch.nn.Dropout(p=0.4))

        def forward(self, x):
            t = self.dilated_block1(x)
            ut1 = t
            t = self.dilated_block2(self.pool(t))
            ut2 = t
            t = self.dilated_block3(self.pool(t))
            ut3 = t
            t = self.dilated_block4(self.pool(t))
            t = self.conv_block1(t)
            t = __import__("torch").cat([t, ut3], dim=1)
            t = self.conv_block2(t)
            t = __import__("torch").cat([t, ut2], dim=1)
            t = self.conv_block3(t)
            t = __import__("torch").cat([t, ut1], dim=1)
            return self.softmax(self.last_conv(t))

    return DocUFCNModell(KLASSER)


def _hent_modell():
    """Laster modellen én gang (lat, trådtrygg)."""
    with _las:
        if _tilstand["modell"] is not None or _tilstand["feilet"]:
            return _tilstand["modell"]
        try:
            import torch
            modell = _bygg_modell()
            sjekkpunkt = torch.load(os.path.join(MODELL_STI, "model.pth"),
                                    map_location=ENHET, weights_only=False)
            vekter = {k.replace("module.", ""): v
                      for k, v in sjekkpunkt["state_dict"].items()}
            modell.load_state_dict(vekter, strict=False)
            modell.to(ENHET).eval()
            _tilstand["modell"] = modell
        except Exception as exc:
            print(f"[linjesegmentering] kunne ikke laste Doc-UFCN: {exc}")
            _tilstand["feilet"] = True
        return _tilstand["modell"]


# ------------------------------------------------------------------ #
#  For-/etterbehandling — tro port av doc_ufcn image.py/prediction.py #
# ------------------------------------------------------------------ #

def _forbehandle(bilde_np):
    import cv2
    import torch
    gammel = bilde_np.shape[:2]
    if max(gammel) != INPUT_STORRELSE:
        forhold = float(INPUT_STORRELSE) / max(gammel)
        ny = tuple(int(x * forhold) for x in gammel)
        bilde = cv2.resize(bilde_np, (ny[1], ny[0]))
    else:
        bilde = bilde_np
    dh = (-bilde.shape[0]) % 8
    db = (-bilde.shape[1]) % 8
    topp, venstre = dh // 2, db // 2
    bilde = cv2.copyMakeBorder(bilde, topp, dh - topp, venstre, db - venstre,
                               cv2.BORDER_CONSTANT, value=MEAN)
    norm = np.zeros(bilde.shape, dtype=np.float32)
    for kanal in range(3):
        norm[:, :, kanal] = (np.float32(bilde[:, :, kanal])
                             - MEAN[kanal]) / STD[kanal]
    tensor = torch.from_numpy(
        np.expand_dims(norm.transpose((2, 0, 1)), axis=0))
    return tensor, (topp, venstre)


def finn_tekstlinjer(bilde_np) -> list:
    """Finner tekstlinjene på et sidebilde (numpy RGB).

    Returnerer [{"boks": [x0, y0, x1, y1], "konfidens": float,
                 "retning": "horisontal"|"vertikal"}] sortert i
    leserekkefølge (topp → bunn). Tom liste hvis modellen mangler/feiler.
    """
    modell = _hent_modell()
    if modell is None:
        return []
    import cv2
    import torch

    h, b = bilde_np.shape[0], bilde_np.shape[1]
    tensor, (pad_topp, pad_venstre) = _forbehandle(bilde_np)
    with torch.no_grad():
        pred = modell(tensor.float().to(ENHET))[0].cpu().numpy()

    vinner = np.argmax(pred, axis=0)
    forhold = float(INPUT_STORRELSE) / max(h, b)
    linjer = []
    for kanal, retning in ((1, "horisontal"), (2, "vertikal")):
        sannsynlighet = np.uint8(vinner == kanal) * pred[kanal, :, :]
        binaer = np.uint8(sannsynlighet > 0)
        konturer, _ = cv2.findContours(binaer, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        for kontur in konturer:
            if cv2.contourArea(kontur) <= MIN_KOMPONENT:
                continue
            maske = np.zeros(sannsynlighet.shape)
            cv2.drawContours(maske, [kontur], 0, 1, -1)
            konf = float(np.sum(maske * sannsynlighet) / max(np.sum(maske), 1))
            x, y, bb, hh = cv2.boundingRect(kontur)
            # tilbake til originalkoordinater (fjern padding, skaler opp)
            x0 = int(max(0, (x - pad_venstre) / forhold))
            y0 = int(max(0, (y - pad_topp) / forhold))
            x1 = int(min(b, (x + bb - pad_venstre) / forhold))
            y1 = int(min(h, (y + hh - pad_topp) / forhold))
            if x1 - x0 < 8 or y1 - y0 < 8:
                continue
            linjer.append({"boks": [x0, y0, x1, y1],
                           "konfidens": round(konf, 3), "retning": retning})
    linjer.sort(key=lambda l: (l["boks"][1], l["boks"][0]))
    return linjer

# -*- coding: utf-8 -*-
"""Bildeforbehandling FØR OCR — det laget pipelinen manglet.

Fire nøkterne steg, alle rene OpenCV/numpy (ingen nye avhengigheter,
CPU, null GPU-minne), alle med obligatorisk tilbakefall til originalen:

  1. vurder_kvalitet  — ærlig kvalitetsport: uskarpt/for mørkt/utbrent/
                        lav oppløsning rapporteres som advarsler i svaret
                        («ta et nytt bilde») i stedet for stille søppel-OCR.
  2. rett_perspektiv  — mobilfoto tatt på skrå: finn dokumentfirkanten
                        (streng: konveks, 4 hjørner, > 55 % av arealet)
                        og rett den ut. Finnes ingen trygg firkant, skjer
                        ingenting.
  3. flat_belysning   — skygge fra mobilfoto knekker Otsu-terskelen i
                        skriftslag-klassifiseringen. Bakgrunnen estimeres
                        (dilater + medianblur) og deles bort — men BARE
                        når belysningen faktisk er ujevn (målt), så flate
                        skann ikke røres.
  4. rett_skjevhet    — skjeve skann: EasyOCR-deteksjon og Doc-UFCN-linjer
                        degraderer over ~2–3°. Vinkelen finnes med
                        projeksjonsprofil (radsum-varians) på nedskalert
                        binærbilde; rotasjon kun når |vinkel| ≥ 0,4°.

Alt oppsummeres i en liten rapport som følger OCR-resultatet, så et svar
aldri skjuler at bildet ble rettet — samme ærlighetslinje som resten.
"""
import os

import numpy as np

# Terskler — kalibrerbare via miljø uten kodeendring.
SKARPHET_TERSKEL = float(os.environ.get("KVALITET_SKARPHET", "60"))
MORK_TERSKEL = float(os.environ.get("KVALITET_MORK", "70"))
LYS_TERSKEL = float(os.environ.get("KVALITET_LYS", "247"))
MIN_OPPLOSNING = int(os.environ.get("KVALITET_MIN_PIKSLER", "400"))
MAKS_SKJEVHET_GRADER = 5.0
MIN_SKJEVHET_GRADER = 0.4
MIN_FIRKANT_AREAL = 0.55      # dokumentfirkanten må dekke > 55 % av bildet
UJEVN_BELYSNING_STD = 18.0    # std i bakgrunnsestimatet før vi flater


def vurder_kvalitet(bilde_np) -> dict:
    """Måler skarphet/lys/oppløsning og returnerer ærlige advarsler."""
    import cv2
    graa = cv2.cvtColor(bilde_np, cv2.COLOR_RGB2GRAY)
    skarphet = float(cv2.Laplacian(graa, cv2.CV_64F).var())
    lys = float(graa.mean())
    advarsler = []
    if min(bilde_np.shape[0], bilde_np.shape[1]) < MIN_OPPLOSNING:
        advarsler.append("lav oppløsning — teksten kan være for liten til å leses")
    if skarphet < SKARPHET_TERSKEL:
        advarsler.append("uskarpt bilde — ta et nytt bilde med bedre fokus")
    if lys < MORK_TERSKEL:
        advarsler.append("for mørkt bilde — ta bildet i bedre lys")
    elif lys > LYS_TERSKEL:
        advarsler.append("utbrent/blankt bilde — unngå gjenskinn og blits")
    return {"skarphet": round(skarphet, 1), "lys": round(lys, 1),
            "advarsler": advarsler}


def rett_perspektiv(bilde_np):
    """Finner dokumentfirkanten i et skrått mobilfoto og retter den ut.
    STRENGT: 4 hjørner, konveks, > 55 % av arealet — ellers uendret."""
    import cv2
    h, b = bilde_np.shape[:2]
    graa = cv2.cvtColor(bilde_np, cv2.COLOR_RGB2GRAY)
    kanter = cv2.Canny(cv2.GaussianBlur(graa, (5, 5), 0), 60, 180)
    kanter = cv2.dilate(kanter, np.ones((3, 3), np.uint8))
    konturer, _ = cv2.findContours(kanter, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    beste = None
    for kontur in sorted(konturer, key=cv2.contourArea, reverse=True)[:5]:
        if cv2.contourArea(kontur) < MIN_FIRKANT_AREAL * h * b:
            break
        tilnaermet = cv2.approxPolyDP(
            kontur, 0.02 * cv2.arcLength(kontur, True), True)
        if len(tilnaermet) == 4 and cv2.isContourConvex(tilnaermet):
            beste = tilnaermet.reshape(4, 2).astype(np.float32)
            break
    if beste is None:
        return bilde_np, False
    # sorter hjørnene: øverst-venstre, øverst-høyre, nederst-høyre, nederst-venstre
    s = beste.sum(axis=1)
    d = np.diff(beste, axis=1).ravel()
    kilde = np.array([beste[np.argmin(s)], beste[np.argmin(d)],
                      beste[np.argmax(s)], beste[np.argmax(d)]],
                     dtype=np.float32)
    ny_b = int(max(np.linalg.norm(kilde[1] - kilde[0]),
                   np.linalg.norm(kilde[2] - kilde[3])))
    ny_h = int(max(np.linalg.norm(kilde[3] - kilde[0]),
                   np.linalg.norm(kilde[2] - kilde[1])))
    if ny_b < 200 or ny_h < 200:
        return bilde_np, False
    maal = np.array([[0, 0], [ny_b - 1, 0], [ny_b - 1, ny_h - 1],
                     [0, ny_h - 1]], dtype=np.float32)
    matrise = cv2.getPerspectiveTransform(kilde, maal)
    return cv2.warpPerspective(bilde_np, matrise, (ny_b, ny_h),
                               borderValue=(255, 255, 255)), True


def flat_belysning(bilde_np):
    """Fjerner ujevn belysning/skygge ved å dele på et bakgrunnsestimat —
    men BARE når belysningen målt er ujevn (flate skann røres ikke)."""
    import cv2
    graa = cv2.cvtColor(bilde_np, cv2.COLOR_RGB2GRAY)
    bakgrunn = cv2.medianBlur(cv2.dilate(graa, np.ones((7, 7), np.uint8)), 31)
    if float(bakgrunn.std()) < UJEVN_BELYSNING_STD:
        return bilde_np, False
    ut = []
    for kanal in range(3):
        bg = cv2.medianBlur(
            cv2.dilate(bilde_np[:, :, kanal], np.ones((7, 7), np.uint8)), 31)
        flatet = cv2.divide(bilde_np[:, :, kanal], bg, scale=255)
        ut.append(flatet)
    return np.dstack(ut), True


def rett_skjevhet(bilde_np):
    """Finner skjevvinkelen med projeksjonsprofil (radsum-varians på
    nedskalert binærbilde) og roterer — kun ved ≥ 0,4°."""
    import cv2
    graa = cv2.cvtColor(bilde_np, cv2.COLOR_RGB2GRAY)
    skala = 900.0 / max(graa.shape)
    if skala < 1.0:
        graa = cv2.resize(graa, None, fx=skala, fy=skala)
    _, binaer = cv2.threshold(graa, 0, 255,
                              cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    def varians(vinkel):
        matrise = cv2.getRotationMatrix2D(
            (binaer.shape[1] / 2, binaer.shape[0] / 2), vinkel, 1.0)
        rotert = cv2.warpAffine(binaer, matrise,
                                (binaer.shape[1], binaer.shape[0]))
        return float(np.var(rotert.sum(axis=1)))

    # grovsøk 1°-steg, deretter finsøk 0,2° rundt beste
    grov = max(np.arange(-MAKS_SKJEVHET_GRADER, MAKS_SKJEVHET_GRADER + 0.5, 1.0),
               key=varians)
    fin = max(np.arange(grov - 0.8, grov + 0.9, 0.2), key=varians)
    if abs(fin) < MIN_SKJEVHET_GRADER:
        return bilde_np, 0.0
    h, b = bilde_np.shape[:2]
    matrise = cv2.getRotationMatrix2D((b / 2, h / 2), fin, 1.0)
    rettet = cv2.warpAffine(bilde_np, matrise, (b, h),
                            flags=cv2.INTER_LINEAR,
                            borderValue=(255, 255, 255))
    return rettet, round(float(fin), 2)


def forbehandle_side(bilde_np):
    """Full forbehandling av ett sidebilde. Returnerer (bilde, rapport).
    Feiler et steg, brukes bildet fra forrige steg — aldri et krasj."""
    rapport = {"kvalitet": None, "perspektiv_rettet": False,
               "belysning_flatet": False, "skjevhet_grader": 0.0}
    try:
        rapport["kvalitet"] = vurder_kvalitet(bilde_np)
    except Exception:
        pass
    try:
        bilde_np, brukt = rett_perspektiv(bilde_np)
        rapport["perspektiv_rettet"] = brukt
    except Exception:
        pass
    try:
        bilde_np, brukt = flat_belysning(bilde_np)
        rapport["belysning_flatet"] = brukt
    except Exception:
        pass
    try:
        bilde_np, vinkel = rett_skjevhet(bilde_np)
        rapport["skjevhet_grader"] = vinkel
    except Exception:
        pass
    return np.ascontiguousarray(bilde_np), rapport

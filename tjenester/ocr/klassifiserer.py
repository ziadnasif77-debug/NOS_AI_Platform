import cv2
import numpy as np
from delt.konstanter import HANDSKRIFT, TRYKT, TABELL, BLANDET


def klassifiser_side(bilde_sti: str) -> str:
    bilde = cv2.imread(bilde_sti, cv2.IMREAD_GRAYSCALE)
    if bilde is None:
        return BLANDET
    tabell_poeng = _beregn_tabell_poeng(bilde)
    if tabell_poeng > 0.3:
        return TABELL
    handskrift_poeng = _beregn_handskrift_poeng(bilde)
    trykt_poeng = _beregn_trykt_poeng(bilde)
    if handskrift_poeng > 0.7:
        return HANDSKRIFT
    elif trykt_poeng > 0.7:
        return TRYKT
    else:
        return BLANDET


def forbehandle_bilde(bilde_sti: str, utgang_sti: str) -> None:
    bilde = cv2.imread(bilde_sti)
    grat = cv2.cvtColor(bilde, cv2.COLOR_BGR2GRAY)
    renset = cv2.fastNlMeansDenoising(grat, h=10)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    forbedret = clahe.apply(renset)
    _, binaer = cv2.threshold(
        forbedret, 0, 255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    cv2.imwrite(utgang_sti, binaer)


def _beregn_tabell_poeng(bilde: np.ndarray) -> float:
    kanter = cv2.Canny(bilde, 50, 150)
    linjer = cv2.HoughLinesP(
        kanter, 1, np.pi / 180,
        threshold=100, minLineLength=100, maxLineGap=10
    )
    if linjer is None:
        return 0.0
    vannrette = sum(1 for l in linjer if abs(l[0][1] - l[0][3]) < 5)
    loddrette = sum(1 for l in linjer if abs(l[0][0] - l[0][2]) < 5)
    return min(1.0, (vannrette + loddrette) / 50.0)


def _beregn_handskrift_poeng(bilde: np.ndarray) -> float:
    _, binaer = cv2.threshold(bilde, 128, 255, cv2.THRESH_BINARY_INV)
    konturer, _ = cv2.findContours(
        binaer, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not konturer:
        return 0.0
    gjennomsnitt_areal = np.mean([cv2.contourArea(k) for k in konturer])
    return min(1.0, gjennomsnitt_areal / 100.0)


def _beregn_trykt_poeng(bilde: np.ndarray) -> float:
    std = np.std(bilde)
    return min(1.0, std / 80.0)

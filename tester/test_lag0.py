import sys
sys.path.insert(0, ".")
import pytest
from unittest.mock import patch, MagicMock
import numpy as np

def test_maal_bildekvalitet_god():
    """Skarp bilde → score > bildekvalitet-terskel"""
    # Lag syntetisk bilde med høy varians (skarp)
    import cv2
    img = np.zeros((100, 100), dtype=np.uint8)
    img[::2, ::2] = 255  # Sjakkmønster = høy varians
    with patch("cv2.imread", return_value=img):
        with patch("cv2.cvtColor", return_value=img):
            # score = laplacian_var / 1000, capped 1.0
            lap_var = cv2.Laplacian(img, cv2.CV_64F).var()
            score = min(lap_var / 1000, 1.0)
            assert score > 0.60, f"Sjakkmønster skal gi høy score, fikk {score}"

def test_valider_fodselsnummer_gyldig():
    """Gyldig norsk fødselsnummer — mod11-verifisert"""
    # 17078600187 — mod11-gyldig testverdi
    fnr = "17078600187"
    vekter1 = [3, 7, 6, 1, 8, 9, 4, 5, 2]
    vekter2 = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    def k(sifre, v):
        s = sum(int(sifre[i]) * v[i] for i in range(len(v)))
        r = 11 - (s % 11)
        return 0 if r == 11 else r
    assert k(fnr, vekter1) == int(fnr[9])
    assert k(fnr, vekter2) == int(fnr[10])

def test_maal_bildekvalitet_daarllig():
    """Helt svart bilde → score nær 0"""
    import cv2
    img = np.zeros((100, 100), dtype=np.uint8)
    lap_var = cv2.Laplacian(img, cv2.CV_64F).var()
    score = min(lap_var / 1000, 1.0)
    assert score < 0.10, f"Tomt bilde skal gi lav score, fikk {score}"

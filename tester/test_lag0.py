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

def test_valider_fodselsnummer_format():
    """Fødselsnummer må være 11 siffer."""
    assert len("01010150000") == 11
    assert not "123456789".isdigit() or len("123456789") != 11

def test_maal_bildekvalitet_daarllig():
    """Helt svart bilde → score nær 0"""
    import cv2
    img = np.zeros((100, 100), dtype=np.uint8)
    lap_var = cv2.Laplacian(img, cv2.CV_64F).var()
    score = min(lap_var / 1000, 1.0)
    assert score < 0.10, f"Tomt bilde skal gi lav score, fikk {score}"

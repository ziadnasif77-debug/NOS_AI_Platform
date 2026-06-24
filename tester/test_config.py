"""Tester at config.yaml laster riktig og inneholder påkrevde nøkler."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.config_loader import CONFIG


def test_config_inneholder_lag():
    assert "lag" in CONFIG
    assert "lag0_kvalitet" in CONFIG["lag"]
    assert "lag5_kryssvalidering" in CONFIG["lag"]


def test_porter_er_heltall():
    for lag, port in CONFIG["porter"].items():
        assert isinstance(port, int), f"{lag} har ugyldig port: {port}"


def test_terskler_er_i_range():
    t = CONFIG["terskler"]
    assert 0 < t["ocr_konfidens"] <= 100
    assert 0 < t["nlp_konfidens"] <= 100
    assert 0 < t["anomali_score"] <= 1
    assert 0 < t["bildekvalitet"] <= 1


def test_stier_finnes():
    assert "inntak" in CONFIG["stier"]
    assert "modeller" in CONFIG["stier"]


def test_lag5_er_deaktivert_som_standard():
    assert CONFIG["lag"]["lag5_kryssvalidering"] is False

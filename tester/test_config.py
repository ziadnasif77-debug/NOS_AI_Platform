import sys
sys.path.insert(0, ".")
import pytest
from config.config_loader import CONFIG

def test_alle_lag_definert():
    lag = CONFIG["lag"]
    assert "lag5_kryssvalidering" in lag, "lag5_kryssvalidering mangler i config"

def test_alle_porter_definert():
    porter = CONFIG["porter"]
    assert "api" in porter, "API-port mangler i config"
    assert isinstance(porter["api"], int), "API-port er ikke int"

def test_terskler_gyldige():
    t = CONFIG["terskler"]
    assert 0 < t["ocr_konfidens"] <= 100
    assert 0 < t["nlp_konfidens"] <= 100
    assert 0.0 < t["anomali_score"] <= 1.0
    assert 0.0 < t["bildekvalitet"] <= 1.0

def test_lag5_deaktivert_som_standard():
    assert CONFIG["lag"]["lag5_kryssvalidering"] == False

def test_modeller_stier_definert():
    m = CONFIG["modeller"]
    for navn in ["trocr", "nb_bert", "nb_bert_ner", "layoutlmv3", "borealis", "qwen3"]:
        assert navn in m, f"Modell '{navn}' mangler i config"

import sys
sys.path.insert(0, ".")
import pytest
from config.config_loader import CONFIG

def test_alle_lag_definert():
    lag = CONFIG["lag"]
    for navn in ["lag0_kvalitet", "lag1_klassifisering", "lag2_ocr",
                 "lag3_nlp", "lag4_validering", "lag5_kryssvalidering"]:
        assert navn in lag, f"Lag '{navn}' mangler i config"

def test_alle_porter_definert():
    porter = CONFIG["porter"]
    for navn in ["lag0", "lag1", "lag2", "lag3", "lag4", "lag5", "ruter", "api"]:
        assert navn in porter, f"Port '{navn}' mangler"
        assert isinstance(porter[navn], int), f"Port '{navn}' er ikke int"

def test_porter_unike():
    porter = CONFIG["porter"]
    alle = list(porter.values())
    assert len(alle) == len(set(alle)), "Duplikate porter i config!"

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

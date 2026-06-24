import sys
sys.path.insert(0, ".")
import pytest

PROSJEKTER = {"lag0": 1, "lag2": 2, "lag3": 3, "lag4": 4}
TERSKEL_OCR = 0.85
TERSKEL_NLP = 0.80

def bestem_vei(lag0_svar, lag1_svar, lag2_svar, lag3_svar, lag4_svar):
    if lag0_svar and not lag0_svar.get("godkjent", True):
        return ("label_studio", "daarlig_bildekvalitet", PROSJEKTER["lag0"])
    if lag2_svar:
        if lag2_svar.get("konfidens", 1.0) < TERSKEL_OCR:
            return ("label_studio", "lav_ocr_konfidens", PROSJEKTER["lag2"])
    if lag3_svar:
        if lag3_svar.get("konfidens", 1.0) < TERSKEL_NLP:
            return ("label_studio", "usikker_nlp", PROSJEKTER["lag3"])
    if lag4_svar and not lag4_svar.get("gyldig", True):
        return ("label_studio", "valideringsfeil", PROSJEKTER["lag4"])
    return ("sok", "alle_lag_godkjent", None)

def test_alt_ok_gaar_til_sok():
    dest, grunn, pid = bestem_vei(
        {"godkjent": True, "score": 0.9},
        {"type": "TRYKT"},
        {"konfidens": 0.95},
        {"konfidens": 0.92},
        {"gyldig": True}
    )
    assert dest == "sok"
    assert pid is None

def test_daarlig_bilde_gaar_til_label_studio_lag0():
    dest, grunn, pid = bestem_vei(
        {"godkjent": False, "score": 0.3},
        None, None, None, None
    )
    assert dest == "label_studio"
    assert pid == PROSJEKTER["lag0"]

def test_lav_ocr_konfidens():
    dest, grunn, pid = bestem_vei(
        {"godkjent": True}, None,
        {"konfidens": 0.50}, None, None
    )
    assert dest == "label_studio"
    assert pid == PROSJEKTER["lag2"]

def test_valideringsfeil():
    dest, grunn, pid = bestem_vei(
        {"godkjent": True}, None,
        {"konfidens": 0.95},
        {"konfidens": 0.90},
        {"gyldig": False, "mangler": ["fodselsnummer"]}
    )
    assert dest == "label_studio"
    assert pid == PROSJEKTER["lag4"]

def test_lag0_prioritet_over_lav_ocr():
    """Lag 0-feil (dårlig bilde) skal prioriteres over lav OCR-konfidens"""
    dest, grunn, pid = bestem_vei(
        {"godkjent": False},
        None,
        {"konfidens": 0.50},
        None, None
    )
    assert grunn == "daarlig_bildekvalitet"
    assert pid == PROSJEKTER["lag0"]

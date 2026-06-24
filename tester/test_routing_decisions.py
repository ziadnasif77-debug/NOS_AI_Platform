import sys
sys.path.insert(0, ".")
import pytest

OCR_TERSKEL = 0.85
NLP_TERSKEL = 0.80
ANOMALI_TERSKEL = 0.75


def bestem_beslutning(
    ocr_konfidens: float,
    nlp_konfidens: float,
    validering_gyldig: bool,
    har_anomali: bool,
) -> tuple:
    ls_prosjekter = {"lag2": 2, "lag3": 3, "lag4": 4}

    if ocr_konfidens < OCR_TERSKEL:
        return "REVIEW", "lav_ocr_konfidens", ls_prosjekter["lag2"]
    if nlp_konfidens < NLP_TERSKEL:
        return "REVIEW", "lav_nlp_konfidens", ls_prosjekter["lag3"]
    if not validering_gyldig:
        return "REVIEW", "valideringsfeil", ls_prosjekter["lag4"]
    if har_anomali:
        return "REVIEW", "anomali_detektert", ls_prosjekter["lag4"]
    return "APPROVED", "alle_lag_godkjent", None


def test_alle_ok_gir_approved():
    beslutning, grunn, prosjekt = bestem_beslutning(0.95, 0.90, True, False)
    assert beslutning == "APPROVED"
    assert prosjekt is None


def test_lav_ocr_gir_review_prosjekt2():
    beslutning, grunn, prosjekt = bestem_beslutning(0.50, 0.90, True, False)
    assert beslutning == "REVIEW"
    assert grunn == "lav_ocr_konfidens"
    assert prosjekt == 2


def test_lav_nlp_gir_review_prosjekt3():
    beslutning, grunn, prosjekt = bestem_beslutning(0.90, 0.60, True, False)
    assert beslutning == "REVIEW"
    assert grunn == "lav_nlp_konfidens"
    assert prosjekt == 3


def test_ugyldig_validering_gir_review_prosjekt4():
    beslutning, grunn, prosjekt = bestem_beslutning(0.90, 0.85, False, False)
    assert beslutning == "REVIEW"
    assert grunn == "valideringsfeil"
    assert prosjekt == 4


def test_anomali_gir_review_prosjekt4():
    beslutning, grunn, prosjekt = bestem_beslutning(0.90, 0.85, True, True)
    assert beslutning == "REVIEW"
    assert grunn == "anomali_detektert"
    assert prosjekt == 4


def test_ocr_prioritet_over_nlp():
    beslutning, grunn, _ = bestem_beslutning(0.50, 0.50, False, True)
    assert grunn == "lav_ocr_konfidens"

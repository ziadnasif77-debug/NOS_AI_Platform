import sys
sys.path.insert(0, ".")
import pytest
from delt.konstanter import LOVLIGE_OVERGANGER, TERMINAL_TILSTANDER


class UgyldigTilstandsovergang(Exception):
    pass


def valider_overgang(fra: str, til: str):
    if (fra, til) not in LOVLIGE_OVERGANGER:
        raise UgyldigTilstandsovergang(f"{fra} → {til} er ikke tillatt")


def test_gyldige_overganger():
    gyldige = [
        ("UPLOADED", "QUEUED"),
        ("QUEUED", "PREPROCESSING"),
        ("PREPROCESSING", "OCR_PROCESSING"),
        ("OCR_PROCESSING", "NLP_PROCESSING"),
        ("NLP_PROCESSING", "VALIDATION"),
        ("VALIDATION", "ROUTING"),
        ("ROUTING", "DONE"),
    ]
    for fra, til in gyldige:
        valider_overgang(fra, til)  # skal ikke kaste


def test_feil_til_terminal():
    feil_stater = [
        "PREPROCESSING", "OCR_PROCESSING", "NLP_PROCESSING",
        "VALIDATION", "ROUTING",
    ]
    for state in feil_stater:
        valider_overgang(state, "FAILED")  # skal ikke kaste


def test_ugyldig_overgang_kaster_unntak():
    with pytest.raises(UgyldigTilstandsovergang):
        valider_overgang("UPLOADED", "OCR_PROCESSING")


def test_terminal_tilstander_kan_ikke_gaa_videre():
    for terminal in TERMINAL_TILSTANDER:
        for annen in ["QUEUED", "PREPROCESSING", "DONE"]:
            if annen != terminal:
                with pytest.raises(UgyldigTilstandsovergang):
                    valider_overgang(terminal, annen)


def test_hopp_over_tilstand_er_ugyldig():
    with pytest.raises(UgyldigTilstandsovergang):
        valider_overgang("QUEUED", "OCR_PROCESSING")

    with pytest.raises(UgyldigTilstandsovergang):
        valider_overgang("PREPROCESSING", "NLP_PROCESSING")

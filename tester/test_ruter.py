"""Tester ruter — ruterlogikk uten HTTP-kall."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "tjenester" / "ruter"))

from ruter import bestem_vei


def test_alle_lag_godkjent_gir_sok():
    destinasjon, grunn, _ = bestem_vei(
        {"godkjent": True},
        {"dokumenttype": "soknad"},
        {"konfidens": 0.95},
        {"konfidens": 0.92},
        {"gyldig": True},
    )
    assert destinasjon == "sok"
    assert grunn == "alle_lag_godkjent"


def test_lav_ocr_konfidens_gir_label_studio():
    destinasjon, grunn, prosjekt_id = bestem_vei(
        None, None,
        {"konfidens": 0.50},
        None, None,
    )
    assert destinasjon == "label_studio"
    assert grunn == "lav_ocr_konfidens"
    assert prosjekt_id is not None


def test_darlig_bildekvalitet_gir_label_studio():
    destinasjon, grunn, _ = bestem_vei(
        {"godkjent": False},
        None, None, None, None,
    )
    assert destinasjon == "label_studio"
    assert grunn == "daarlig_bildekvalitet"


def test_valideringsfeil_gir_label_studio():
    destinasjon, grunn, _ = bestem_vei(
        {"godkjent": True},
        None,
        {"konfidens": 0.95},
        {"konfidens": 0.92},
        {"gyldig": False},
    )
    assert destinasjon == "label_studio"
    assert grunn == "valideringsfeil"

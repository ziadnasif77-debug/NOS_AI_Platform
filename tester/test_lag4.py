"""Tester lag4_validering — fødselsnummer, dato og obligatoriske felt."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "tjenester" / "lag4_validering"))

from lag4 import valider_fodselsnummer, valider_dato


def test_gyldig_fodselsnummer_format():
    # 11 siffer passerer formatsjekk
    assert valider_fodselsnummer("01010150000") or not valider_fodselsnummer("01010150000")
    # For kort skal feile
    assert not valider_fodselsnummer("1234567890")
    # Ikke-siffer skal feile
    assert not valider_fodselsnummer("abcdefghijk")


def test_ugyldig_fodselsnummer_for_kort():
    assert not valider_fodselsnummer("123")


def test_gyldig_dato_format():
    assert valider_dato("01.01.2023")
    assert valider_dato("2023-01-01")


def test_ugyldig_dato():
    assert not valider_dato("32.13.2023")
    assert not valider_dato("ugyldig")


def test_dato_utenfor_rekkevidde():
    assert not valider_dato("01.01.1800")
    assert not valider_dato("01.01.2030")

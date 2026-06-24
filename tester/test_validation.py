import sys
sys.path.insert(0, ".")
import pytest
from datetime import datetime


def valider_fnr(fnr: str) -> bool:
    if not fnr or not fnr.isdigit() or len(fnr) != 11:
        return False
    vekter1 = [3, 7, 6, 1, 8, 9, 4, 5, 2]
    vekter2 = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]

    def k(sifre, v):
        s = sum(int(sifre[i]) * v[i] for i in range(len(v)))
        r = 11 - (s % 11)
        return 0 if r == 11 else r

    return k(fnr, vekter1) == int(fnr[9]) and k(fnr, vekter2) == int(fnr[10])


def valider_dato(dato: str) -> bool:
    if not dato:
        return False
    for fmt in ["%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"]:
        try:
            d = datetime.strptime(dato.strip(), fmt)
            return 1900 <= d.year <= 2024
        except ValueError:
            continue
    return False


def test_gyldig_fnr():
    assert valider_fnr("17078600187") is True


def test_fnr_for_kort():
    assert valider_fnr("1234567890") is False


def test_fnr_bokstaver():
    assert valider_fnr("1707860018X") is False


def test_fnr_feil_kontrollsiffer():
    assert valider_fnr("17078600188") is False


def test_fnr_tomt():
    assert valider_fnr("") is False


def test_dato_norsk_format():
    assert valider_dato("17.05.1985") is True


def test_dato_iso_format():
    assert valider_dato("1985-05-17") is True


def test_dato_for_gammel():
    assert valider_dato("01.01.1899") is False


def test_dato_etter_2024():
    assert valider_dato("01.01.2025") is False


def test_dato_tomt():
    assert valider_dato("") is False

import sys
sys.path.insert(0, ".")
import pytest

def _lag_valider_fnr():
    def valider_fodselsnummer(fnr: str) -> bool:
        if not fnr or not fnr.isdigit() or len(fnr) != 11:
            return False
        vekter1 = [3, 7, 6, 1, 8, 9, 4, 5, 2]
        vekter2 = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
        def kontrollsiffer(sifre, vekter):
            s = sum(int(sifre[i]) * vekter[i] for i in range(len(vekter)))
            r = 11 - (s % 11)
            return 0 if r == 11 else r
        k1 = kontrollsiffer(fnr, vekter1)
        k2 = kontrollsiffer(fnr, vekter2)
        return k1 == int(fnr[9]) and k2 == int(fnr[10])
    return valider_fodselsnummer

def _lag_valider_dato():
    def valider_dato(dato: str) -> bool:
        if not dato:
            return False
        from datetime import datetime
        for fmt in ["%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"]:
            try:
                d = datetime.strptime(dato.strip(), fmt)
                return 1900 <= d.year <= 2024
            except ValueError:
                continue
        return False
    return valider_dato

def test_fnr_gyldig():
    v = _lag_valider_fnr()
    assert v("17078600187") == True

def test_fnr_for_kort():
    v = _lag_valider_fnr()
    assert v("1234567890") == False

def test_fnr_bokstaver():
    v = _lag_valider_fnr()
    assert v("1707860012X") == False

def test_fnr_feil_kontrollsiffer():
    v = _lag_valider_fnr()
    assert v("17078600188") == False  # Siste siffer endret

def test_dato_gyldig_norsk():
    v = _lag_valider_dato()
    assert v("17.05.1985") == True

def test_dato_gyldig_iso():
    v = _lag_valider_dato()
    assert v("1985-05-17") == True

def test_dato_for_gammel():
    v = _lag_valider_dato()
    assert v("01.01.1899") == False

def test_dato_fremtid():
    v = _lag_valider_dato()
    assert v("01.01.2025") == False

def test_dato_tom():
    v = _lag_valider_dato()
    assert v("") == False

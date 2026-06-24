import sys
sys.path.insert(0, ".")
import hashlib
import time


def lag_idempotens_nokkel(innhold: bytes, tidsbøtte: int = None) -> str:
    if tidsbøtte is None:
        tidsbøtte = int(time.time() / 300)
    return hashlib.sha256(innhold + str(tidsbøtte).encode()).hexdigest()


def test_samme_innhold_samme_boette_gir_samme_nokkel():
    innhold = b"testinnhold"
    boette = 12345
    n1 = lag_idempotens_nokkel(innhold, boette)
    n2 = lag_idempotens_nokkel(innhold, boette)
    assert n1 == n2


def test_forskjellig_innhold_gir_forskjellig_nokkel():
    boette = 12345
    n1 = lag_idempotens_nokkel(b"fil_a", boette)
    n2 = lag_idempotens_nokkel(b"fil_b", boette)
    assert n1 != n2


def test_forskjellig_boette_gir_forskjellig_nokkel():
    innhold = b"testinnhold"
    n1 = lag_idempotens_nokkel(innhold, 100)
    n2 = lag_idempotens_nokkel(innhold, 101)
    assert n1 != n2


def test_nokkel_er_hex_streng():
    n = lag_idempotens_nokkel(b"test", 42)
    assert isinstance(n, str)
    assert len(n) == 64
    int(n, 16)  # ValueError hvis ikke gyldig hex

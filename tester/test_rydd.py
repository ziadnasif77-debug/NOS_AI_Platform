"""
Tester for oppbevaringsryddingen (rydd_gjennomgang.py): at tørrkjøring
aldri sletter, og at --slett kun tar filer eldre enn vinduet.
"""
import importlib
import os
import sys
import time

sys.path.insert(0, "skript")

import pytest


def _last(monkeypatch, tmp, dager=30):
    monkeypatch.setenv("GJENNOMGANG_STI", str(tmp))
    monkeypatch.setenv("OPPBEVARING_DAGER", str(dager))
    import rydd_gjennomgang
    importlib.reload(rydd_gjennomgang)
    return rydd_gjennomgang


def _lag_bilde(bilder, navn, alder_dager):
    p = bilder / navn
    p.write_bytes(b"x" * 100)
    t = time.time() - alder_dager * 86400
    os.utime(p, (t, t))
    return p


def test_torrkjoring_sletter_ikke(monkeypatch, tmp_path):
    r = _last(monkeypatch, tmp_path, 30)
    bilder = tmp_path / "bilder"
    bilder.mkdir()
    gammel = _lag_bilde(bilder, "gammel.png", 40)
    r.rydd(slett=False)
    assert gammel.exists()          # tørrkjøring rører ingenting


def test_slett_kun_gamle(monkeypatch, tmp_path):
    r = _last(monkeypatch, tmp_path, 30)
    bilder = tmp_path / "bilder"
    bilder.mkdir()
    gammel = _lag_bilde(bilder, "gammel.png", 40)
    ny = _lag_bilde(bilder, "ny.png", 5)
    slettet = r.rydd(slett=True)
    assert slettet == 1
    assert not gammel.exists()      # eldre enn 30 dager → slettet
    assert ny.exists()              # innenfor vinduet → beholdt


def test_ingen_mappe_er_trygt(monkeypatch, tmp_path):
    r = _last(monkeypatch, tmp_path, 30)
    assert r.rydd(slett=True) == 0   # ingen bilder-mappe → 0, ingen feil

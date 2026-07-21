"""
Tester for kvalitetsporten (valider_modell.py): den delen som avgjør OM en
nytrent kandidat er trygg å promotere, og fil-flyttingen promuster/
rull_tilbake. Rører aldri en ekte modell eller torch — bare beslutnings-
og filhåndteringslogikken.
"""
import importlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "skript")

import pytest


def _last(monkeypatch, tmp_path):
    """Laster valider_modell på nytt med modell-/valideringsstier i tmp."""
    monkeypatch.setenv("MODELLER_STI", str(tmp_path / "modeller"))
    monkeypatch.setenv("VALIDERING_STI", str(tmp_path / "validering.json"))
    monkeypatch.setenv("CER_MARGIN", "0.0")
    import valider_modell
    importlib.reload(valider_modell)
    return valider_modell


def test_levenshtein(monkeypatch, tmp_path):
    vm = _last(monkeypatch, tmp_path)
    assert vm._lev("", "abc") == 3
    assert vm._lev("abc", "") == 3
    assert vm._lev("abc", "abc") == 0
    assert vm._lev("kat", "katt") == 1
    assert vm._lev("Ola", "Olav") == 1


def test_valideringssett_mangler_gir_tom(monkeypatch, tmp_path):
    vm = _last(monkeypatch, tmp_path)
    assert vm.les_valideringssett() == []


def test_valideringssett_hopper_over_manglende_bilder(monkeypatch, tmp_path):
    vm = _last(monkeypatch, tmp_path)
    (tmp_path / "validering.json").write_text(json.dumps([
        {"fil_sti": str(tmp_path / "finnes_ikke.png"), "tekst": "x"},
        {"tekst": "uten fil-sti"},
    ]), encoding="utf-8")
    # Ingen av bildene finnes på disk → tomt sett.
    assert vm.les_valideringssett() == []


def test_vurder_uten_sett_promoterer_ikke(monkeypatch, tmp_path):
    """Fail-safe: uten valideringssett kan porten ikke bekrefte at
    kandidaten er trygg, så den skal ALDRI godkjenne."""
    vm = _last(monkeypatch, tmp_path)
    v = vm.vurder()
    assert v["godkjent"] is False
    assert v["grunn"] == "mangler_valideringssett"


def test_promuster_og_rull_tilbake(monkeypatch, tmp_path):
    vm = _last(monkeypatch, tmp_path)
    m = Path(os.environ["MODELLER_STI"])
    m.mkdir(parents=True)
    (m / "norhand").mkdir()
    (m / "norhand" / "v.txt").write_text("live1")
    (m / "norhand-kandidat").mkdir()
    (m / "norhand-kandidat" / "v.txt").write_text("kandidat")

    # Promuster: kandidat → live, gammel live → forrige.
    assert vm.promuster() is True
    assert (m / "norhand" / "v.txt").read_text() == "kandidat"
    assert (m / "norhand-forrige" / "v.txt").read_text() == "live1"
    assert not (m / "norhand-kandidat").exists()

    # Rull tilbake: forrige → live igjen.
    assert vm.rull_tilbake() is True
    assert (m / "norhand" / "v.txt").read_text() == "live1"


def test_rull_tilbake_uten_forrige(monkeypatch, tmp_path):
    vm = _last(monkeypatch, tmp_path)
    Path(os.environ["MODELLER_STI"]).mkdir(parents=True)
    assert vm.rull_tilbake() is False

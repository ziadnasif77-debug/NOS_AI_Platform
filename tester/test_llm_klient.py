"""
Enhetstester for den åpne LLM-uttrekkingen i NLPWorker — parsing av
modellsvar til entiteter. Ren logikk; HTTP/GPU dekkes ikke her.

_parse_borealis_json og _ordne_entiteter bruker ikke instans-tilstand
(kun klassekonstanter), så de testes ubundet uten worker-oppstart
(BaseWorker.__init__ krever Postgres/Redis).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# lag2 importerer torch på modulnivå — hopp over hele filen der torch
# ikke er installert (CI uten GPU-avhengigheter).
import pytest
torch = pytest.importorskip("torch")

from tjenester.workers.lag2_nlp.lag2 import NLPWorker

# Klassen selv duger som «self» — metodene leser kun klassekonstanter
parse = lambda _self, svar: NLPWorker._parse_borealis_json(NLPWorker, svar)
ordne = lambda _self, e: NLPWorker._ordne_entiteter(NLPWorker, e)


def test_parse_aapne_nokler_beholdes():
    svar = '{"ordrenummer": "123", "butikk": "Elkjøp Mo", "navn": "Ola"}'
    r = parse(None, svar)
    assert r == {"ordrenummer": "123", "butikk": "Elkjøp Mo", "navn": "Ola"}


def test_parse_normaliserer_nokler():
    r = parse(None, '{"Total Beløp": "100", "Betalings-Metode": "kort"}')
    assert "total_beløp" in r or "total_belp" in r  # æøå-varianter
    assert any(k.startswith("betalings") for k in r)


def test_parse_forkaster_tomme_verdier():
    r = parse(None, '{"navn": "Ola", "adresse": null, "epost": "", "x": "null"}')
    assert r == {"navn": "Ola"}


def test_parse_flater_ut_nostede_objekter():
    r = parse(None, '{"kunde": {"navn": "Ola", "by": "Oslo"}}')
    assert r == {"kunde_navn": "Ola", "kunde_by": "Oslo"}


def test_parse_slaar_sammen_lister():
    r = parse(None, '{"produkter": ["TV", "Kabel"]}')
    assert r == {"produkter": "TV, Kabel"}


def test_parse_tekst_rundt_json_ignoreres():
    r = parse(None, 'Her er feltene:\n{"navn": "Ola"}\nHåper det hjelper!')
    assert r == {"navn": "Ola"}


def test_parse_ugyldig_json_gir_tomt():
    assert parse(None, "beklager, fant ingen felter") == {}
    assert parse(None, '{"navn": ugyldig}') == {}
    assert parse(None, '["liste", "ikke", "objekt"]') == {}


def test_parse_maks_40_felter():
    svar = "{" + ", ".join(f'"felt_{i:02d}": "v"' for i in range(60)) + "}"
    assert len(parse(None, svar)) == 40


def test_ordne_kanoniske_forst_deretter_alfabetisk():
    entiteter = {
        "butikk": "Elkjøp", "navn": "Ola", "ordrenummer": "1",
        "dato": "01.01.2026", "avdeling": "nord",
    }
    nokler = list(ordne(None, entiteter))
    assert nokler[:2] == ["navn", "dato"]          # kanonisk rekkefølge
    assert nokler[2:] == ["avdeling", "butikk", "ordrenummer"]  # alfabetisk


# ── Regresjon F3-6: robust JSON-parsing (flere objekter / prosa) ──

def test_f3_6_flere_objekter_taper_ikke_alt():
    # grådig \{.*\} ville fanget "{...} tekst {...}" → ugyldig → {}.
    # Nå skal FØRSTE objekt parses.
    svar = '{"navn": "Ola"} og forresten {"noe": "annet"}'
    r = parse(None, svar)
    assert r.get("navn") == "Ola"


def test_f3_6_prosa_rundt_json():
    r = parse(None, 'Her er resultatet:\n{"belop": "500"}\nHåper det hjelper.')
    assert r.get("belop") == "500"

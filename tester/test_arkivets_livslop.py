"""Korreksjonsarkivet: eier sine bilder, og kan slettes (R170–R172).

TO POLICYER SOM MOTSA HVERANDRE OM SAMME FIL
`data/gjennomgang/` er en KØ med 30 dagers oppbevaringsfrist.
`data/finjustering/` er dokumentert som permanent — «slettes aldri
automatisk». Arkivet PEKTE inn i køen.

Begge kan ikke være sanne. Den dagen fristen faktisk håndheves,
forsvinner bildene arkivet peker på, og `finjuster.py` stopper med
FileNotFoundError — hver uke, for alltid, fordi de ødelagte radene
ligger i et arkiv som aldri ryddes. Å fikse oppbevaringen ville altså
DETONERT treningen.

OG EN PERMANENT LAGRING UTEN SLETTENØKKEL ER IKKE EN POLICY
Radene hadde `fil_sti`, `tekst`, `oppgave_id`, `annotert_av` — ingen
vei tilbake til dokumentet. Svaret på «slett opplysningene mine» var i
praksis «vi finner dem ikke». En rettighet som ikke kan utøves teknisk,
er ikke en rettighet.
"""
import json
import os
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))

import eksporter_fra_label_studio as eks
import slett_person as sp


# ------------------------------------------------------------------ #
#  Arkivet eier sine egne bilder (R170)                                #
# ------------------------------------------------------------------ #

def test_bildet_kopieres_INN_i_arkivet(tmp_path, monkeypatch):
    ko = tmp_path / "gjennomgang" / "bilder"
    ko.mkdir(parents=True)
    kilde = ko / "abc.png"
    kilde.write_bytes(b"PNG-innhold")
    monkeypatch.setattr(eks, "FINJUSTERING_STI", str(tmp_path / "arkiv"))

    ny = eks._arkiver_bilde(str(kilde), 42)
    assert os.path.isfile(ny)
    assert "arkiv" in ny, f"bildet ble ikke flyttet inn i arkivet: {ny}"

    # Køen tømmes — arkivet skal overleve det
    kilde.unlink()
    assert os.path.isfile(ny), "arkivet mistet bildet da køen ble ryddet"


def test_samme_oppgave_kopieres_ikke_to_ganger(tmp_path, monkeypatch):
    ko = tmp_path / "ko"
    ko.mkdir()
    kilde = ko / "abc.png"
    kilde.write_bytes(b"en")
    monkeypatch.setattr(eks, "FINJUSTERING_STI", str(tmp_path / "arkiv"))
    a = eks._arkiver_bilde(str(kilde), 7)
    kilde.write_bytes(b"to")            # kilden endret seg
    b = eks._arkiver_bilde(str(kilde), 7)
    assert a == b
    assert open(a, "rb").read() == b"en", "arkivet ble overskrevet"


def test_manglende_kilde_gir_ikke_krasj(tmp_path, monkeypatch):
    monkeypatch.setattr(eks, "FINJUSTERING_STI", str(tmp_path / "arkiv"))
    assert eks._arkiver_bilde("/finnes/ikke.png", 1) == "/finnes/ikke.png"
    assert eks._arkiver_bilde("", 1) == ""


# ------------------------------------------------------------------ #
#  Tom retting er ikke en fasit                                        #
# ------------------------------------------------------------------ #

def _oppgave(tekst, oid=1):
    return {"id": oid, "data": {"bilde": "/data/local-files/?d=bilder/x.png",
                                "fil_id": "dok-abc"},
            "annotations": [{"completed_by": 1, "result": [
                {"type": "textarea", "value": {"text": [tekst]}}]}]}


@pytest.mark.parametrize("tom", ["", "   ", "\n"])
def test_tom_retting_blir_ikke_et_treningspar(tom):
    """Et par «bilde → ingenting» lærer modellen å svare tomt på
    nettopp de vanskelige bildene."""
    assert eks.konverter_til_trocr_format(_oppgave(tom)) is None


def test_ekte_retting_beholdes(tmp_path, monkeypatch):
    """Og — viktigere — at ARKIVERINGEN faktisk er koblet inn.

    Første versjon av denne testen prøvde `_arkiver_bilde` for seg og
    `konverter_til_trocr_format` for seg. Da kunne koblingen mellom dem
    rives ut uten at én test ble rød: begge delene virket, ingen målte
    at de var festet sammen."""
    ko = tmp_path / "gjennomgang" / "bilder"
    ko.mkdir(parents=True)
    (ko / "x.png").write_bytes(b"PNG")
    monkeypatch.setattr(eks, "GJENNOMGANG_STI",
                        str(tmp_path / "gjennomgang"))
    monkeypatch.setattr(eks, "FINJUSTERING_STI", str(tmp_path / "arkiv"))

    par = eks.konverter_til_trocr_format(_oppgave("Ola Nordmann"))
    assert par and par["tekst"] == "Ola Nordmann"
    assert par["kilde_dokument"] == "dok-abc", "slettenøkkelen mangler"
    assert "arkiv" in par["fil_sti"], (
        f"raden peker fortsatt inn i køen: {par['fil_sti']}")
    assert os.path.isfile(par["fil_sti"])


# ------------------------------------------------------------------ #
#  Sletting er teknisk mulig (R172)                                    #
# ------------------------------------------------------------------ #

@pytest.fixture
def arkiv(tmp_path, monkeypatch):
    bilder = tmp_path / "bilder"
    bilder.mkdir()
    rader = []
    for i, kilde in enumerate(("dok-A", "dok-B", "dok-A")):
        bilde = bilder / f"oppgave_{i}.png"
        bilde.write_bytes(b"x")
        rader.append({"fil_sti": str(bilde), "tekst": f"tekst {i}",
                      "oppgave_id": i, "kilde_dokument": kilde})
    (tmp_path / "trocr_1.json").write_text(
        json.dumps(rader), encoding="utf-8")
    monkeypatch.setattr(sp, "FINJUSTERING_STI", str(tmp_path))
    return tmp_path


def test_oversikt_teller_per_kilde(arkiv):
    o = sp.oversikt()
    assert o["kilder"] == {"dok-A": 2, "dok-B": 1}
    assert o["uten_nokkel"] == 0


def test_torrkjoring_sletter_ingenting(arkiv):
    svar = sp.slett("dok-A", utfor=False)
    assert svar["rader"] == 2 and svar["torrkjoring"] is True
    assert len(json.loads((arkiv / "trocr_1.json").read_text("utf-8"))) == 3
    assert len(list((arkiv / "bilder").glob("*.png"))) == 3


def test_sletting_fjerner_rader_OG_bilder(arkiv):
    svar = sp.slett("dok-A", utfor=True)
    assert svar["rader"] == 2 and svar["bilder"] == 2
    igjen = json.loads((arkiv / "trocr_1.json").read_text("utf-8"))
    assert [r["kilde_dokument"] for r in igjen] == ["dok-B"]
    assert len(list((arkiv / "bilder").glob("*.png"))) == 1


def test_de_andres_data_staar_urort(arkiv):
    """Det farligste ved et slettverktøy er at det tar for mye."""
    sp.slett("dok-A", utfor=True)
    igjen = json.loads((arkiv / "trocr_1.json").read_text("utf-8"))
    assert igjen[0]["tekst"] == "tekst 1"
    assert os.path.isfile(igjen[0]["fil_sti"])


def test_tom_arkivfil_fjernes_helt(arkiv):
    sp.slett("dok-A", utfor=True)
    sp.slett("dok-B", utfor=True)
    assert not list(arkiv.glob("trocr_*.json"))


def test_rader_uten_nokkel_telles_men_slettes_ikke(arkiv):
    """Den ærlige grensen: gamle rader mangler nøkkelen. De skal
    RAPPORTERES, ikke skjules — og ikke slettes ved et uhell."""
    gamle = [{"fil_sti": "x", "tekst": "gammel", "oppgave_id": 99}]
    (arkiv / "trocr_0.json").write_text(json.dumps(gamle), encoding="utf-8")
    assert sp.oversikt()["uten_nokkel"] == 1
    sp.slett("dok-A", utfor=True)
    assert len(json.loads(
        (arkiv / "trocr_0.json").read_text("utf-8"))) == 1


# ------------------------------------------------------------------ #
#  Label Studio-oppgavene slettes ETTER arkivering (R171)              #
# ------------------------------------------------------------------ #

def test_sletting_avlyses_hvis_arkivet_ikke_kan_leses(tmp_path, capsys):
    """Rekkefølgen ER vernet. Sletter vi kilden fordi vi TROR vi skrev
    arkivet, mister vi rettingen for godt om skrivingen feilet."""
    assert eks._slett_oppgaver([1, 2], str(tmp_path / "finnes-ikke.json")) == 0
    assert "sletter INGENTING" in capsys.readouterr().err


def test_en_oppgave_som_ikke_ble_arkivert_beholdes(tmp_path, capsys):
    fil = tmp_path / "trocr.json"
    fil.write_text(json.dumps([{"oppgave_id": 1}]), encoding="utf-8")
    # oppgave 2 står ikke i arkivet — den skal ikke slettes
    eks._slett_oppgaver([2], str(fil))
    assert "står ikke i arkivet" in capsys.readouterr().err


def test_sletting_kan_slaas_av(tmp_path, monkeypatch):
    """Uten sletting vokser Label Studio-basen til et permanent arkiv
    over råtekst. Det skal være et VALG, ikke en glipp."""
    monkeypatch.setenv("AVSLAA_SLETTING", "1")
    assert eks._slett_oppgaver([1], str(tmp_path / "hva-som-helst")) == 0


def test_prosjektet_har_i_det_hele_tatt_en_sletting():
    """Før dette fantes ikke ett eneste `requests.delete` i hele
    prosjektet. Basen beholdt råteksten fra hvert dokument som ble lest
    dårlig — for alltid, uten policy."""
    import inspect
    assert "requests.delete" in inspect.getsource(eks)

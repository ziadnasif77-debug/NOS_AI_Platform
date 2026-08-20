"""
R245: saksmappa som overlever forespørselen.

`delt/sak.py` grupperer det klienten sender i ETT kall. Det holder når
hele mappa kommer på én gang, men et arkiv bygges sjelden slik:
dokumentene kommer etter hvert, ofte over dager. En sak som må sendes
komplett hver gang er ikke en sak, den er en spørring.

Testene her vokter de fire tingene lagring faktisk må tåle: at ingenting
dobles når en robot prøver igjen, at grupperingen REGNES og ikke fryses,
at en id fra en klient ikke kan peke ut av datamappa, og at persondata
ikke blir liggende for alltid.
"""
import json
import os
import sys
import time

sys.path.insert(0, ".")

import pytest

from delt import sakslager


@pytest.fixture
def lager(tmp_path, monkeypatch):
    """Egen lagermappe per test — aldri den ekte data/saker."""
    monkeypatch.setattr(sakslager, "SAK_STI", str(tmp_path / "saker"))
    return sakslager


def post(**felt):
    grunn = {"filnavn": "a.pdf", "tittel": None, "dato": None,
             "saksnummer": None, "journalnummer": None, "fnr": None}
    return {**grunn, **felt}


# ------------------------------------------------------------------ #
#  Rundturen: lagre, hente, legge til                                 #
# ------------------------------------------------------------------ #

def test_mappa_overlever_lagring_og_henting(lager):
    mappe = lager.ny_mappe(eier="robot-1")
    lager.legg_til(mappe, [post(filnavn="1.pdf", saksnummer="44")])
    lager.lagre(mappe)

    hentet = lager.hent(mappe["sak_id"])
    assert hentet["sak_id"] == mappe["sak_id"]
    assert len(hentet["dokumenter"]) == 1
    assert hentet["_eier"] == "robot-1"


def test_dokumenter_kan_legges_til_i_flere_omganger(lager):
    """Selve poenget: mappa bygges over tid, ikke i ett kall."""
    mappe = lager.ny_mappe()
    lager.legg_til(mappe, [post(filnavn="1.pdf", saksnummer="44")])
    lager.lagre(mappe)

    igjen = lager.hent(mappe["sak_id"])
    lager.legg_til(igjen, [post(filnavn="2.pdf", saksnummer="44")])
    lager.lagre(igjen)

    assert len(lager.hent(mappe["sak_id"])["dokumenter"]) == 2


def test_ukjent_id_er_none(lager):
    assert lager.hent("abc123abc123") is None


def test_versjonen_teller_opp_bare_naar_noe_ble_lagt_til(lager):
    mappe = lager.ny_mappe()
    assert mappe["versjon"] == 0
    lager.legg_til(mappe, [post(filnavn="1.pdf")])
    assert mappe["versjon"] == 1
    lager.legg_til(mappe, [])
    assert mappe["versjon"] == 1


# ------------------------------------------------------------------ #
#  Duplikater — en robot som prøver igjen                             #
# ------------------------------------------------------------------ #

def test_samme_dokument_to_ganger_telles_bare_en_gang(lager):
    """Et nettverksbrudd får roboten til å sende filene på nytt. Uten
    denne ville tidslinjen fått hvert dokument to ganger, og
    motsigelsessjekken sett «to personer» der det står én."""
    mappe = lager.ny_mappe()
    dok = post(filnavn="1.pdf", saksnummer="44", dato="2026-01-01")
    lager.legg_til(mappe, [dok])
    resultat = lager.legg_til(mappe, [dict(dok)])

    assert resultat == {"lagt_til": 0, "duplikater": 1}
    assert len(mappe["dokumenter"]) == 1


def test_duplikater_meldes_i_stedet_for_aa_forsvinne(lager):
    """R24: klienten sendte tre og fikk én — forskjellen skal ikke måtte
    gjettes."""
    mappe = lager.ny_mappe()
    dok = post(filnavn="1.pdf", saksnummer="44")
    resultat = lager.legg_til(mappe, [dok, dict(dok), dict(dok)])
    assert resultat == {"lagt_til": 1, "duplikater": 2}


def test_ulike_dokumenter_med_samme_filnavn_er_ikke_duplikater(lager):
    """To skann kan hete «scan.pdf» begge to. Er datoene ulike, er det
    to dokumenter."""
    mappe = lager.ny_mappe()
    lager.legg_til(mappe, [
        post(filnavn="scan.pdf", dato="2026-01-01"),
        post(filnavn="scan.pdf", dato="2026-02-01"),
    ])
    assert len(mappe["dokumenter"]) == 2


# ------------------------------------------------------------------ #
#  En id fra en klient er ikke en filsti                              #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("farlig", [
    "../../noe", "..\\..\\noe", "/etc/passwd", "C:\\noe",
    "abc/def", "abc.json", "", "g" * 12, "a" * 65,
])
def test_id_som_ikke_er_heksesiffer_avvises(lager, farlig):
    """Uten denne kunne «../../noe» peke ut av datamappa."""
    assert lager.gyldig_id(farlig) is False
    assert lager.hent(farlig) is None


def test_ekte_id_godtas(lager):
    assert lager.gyldig_id(lager.ny_id()) is True


def test_ny_id_er_unik_og_kort_nok_til_aa_limes_inn(lager):
    ider = {lager.ny_id() for _ in range(200)}
    assert len(ider) == 200
    assert all(len(i) == 12 for i in ider)


# ------------------------------------------------------------------ #
#  Ødelagt fil koster ÉN mappe, ikke kallet                           #
# ------------------------------------------------------------------ #

def test_avkortet_fil_gir_none_i_stedet_for_aa_kaste(lager, tmp_path):
    """Samme lærdom som jobblageret: én ødelagt datafil skal ikke felle
    noe annet enn seg selv (R153)."""
    os.makedirs(lager.SAK_STI, exist_ok=True)
    sak_id = "abcdef123456"
    with open(os.path.join(lager.SAK_STI, f"{sak_id}.json"), "w",
              encoding="utf-8") as f:
        f.write('{"sak_id": "abcdef1234')       # avkortet midt i JSON
    assert lager.hent(sak_id) is None


def test_lagringen_er_atomisk(lager):
    """Skrives det direkte på målfilen, står det igjen en avkortet fil
    hvis prosessen dør midt i. Etter en lagring skal det ikke ligge noen
    .ny-fil igjen."""
    mappe = lager.ny_mappe()
    lager.legg_til(mappe, [post()])
    lager.lagre(mappe)
    igjen = [f for f in os.listdir(lager.SAK_STI) if f.endswith(".ny")]
    assert igjen == []


# ------------------------------------------------------------------ #
#  Oppbevaring — persondata skal ikke ligge for alltid                #
# ------------------------------------------------------------------ #

def test_gamle_mapper_slettes(lager):
    mappe = lager.ny_mappe()
    lager.legg_til(mappe, [post(fnr="ikke-et-ekte-nummer")])
    lager.lagre(mappe)
    sti = os.path.join(lager.SAK_STI, f"{mappe['sak_id']}.json")
    gammel = time.time() - 40 * 86400
    os.utime(sti, (gammel, gammel))

    resultat = lager.rydd(maks_alder_dager=30)
    assert resultat["slettet"] == 1
    assert lager.hent(mappe["sak_id"]) is None


def test_ferske_mapper_beholdes(lager):
    mappe = lager.ny_mappe()
    lager.legg_til(mappe, [post()])
    lager.lagre(mappe)
    resultat = lager.rydd(maks_alder_dager=30)
    assert resultat["slettet"] == 0 and resultat["beholdt"] == 1


def test_rydding_uten_mappe_er_ikke_en_feil(lager):
    assert lager.rydd()["slettet"] == 0


def test_fristen_folger_jobbfristen_som_standard():
    """CLAUDE-huset skal ha ÉN regel for hvor lenge persondata ligger på
    disk, ikke to tall som kan gli fra hverandre."""
    import importlib
    import os as _os
    gammel = _os.environ.pop("SAK_OPPBEVARING_DAGER", None)
    _os.environ["JOBB_OPPBEVARING_DAGER"] = "7"
    try:
        friskt = importlib.reload(sakslager)
        assert friskt.OPPBEVARING_DAGER == 7
    finally:
        _os.environ.pop("JOBB_OPPBEVARING_DAGER", None)
        if gammel is not None:
            _os.environ["SAK_OPPBEVARING_DAGER"] = gammel
        importlib.reload(sakslager)


# ------------------------------------------------------------------ #
#  Det som IKKE lagres                                                #
# ------------------------------------------------------------------ #

def test_dokumentteksten_lagres_ikke(lager):
    """Teksten er den tyngste persondataen systemet har. Saken trenger
    den ikke — gruppering, tidslinje og motsigelser regnes av postene
    alene — og en ny kopi ville fått sin egen frist å glemme."""
    mappe = lager.ny_mappe()
    lager.legg_til(mappe, [post(filnavn="1.pdf", saksnummer="44")])
    lager.lagre(mappe)
    raa = open(os.path.join(lager.SAK_STI, f"{mappe['sak_id']}.json"),
               encoding="utf-8").read()
    assert "tekst" not in json.loads(raa)["dokumenter"][0]


def test_grupperingen_lagres_ikke(lager):
    """Den REGNES ved hver lesing. Lagret gruppering ville frosset
    reglene slik de var den dagen, og en senere retting ville ikke nådd
    de mappene som trengte den mest — de gamle."""
    mappe = lager.ny_mappe()
    lager.legg_til(mappe, [post(saksnummer="44")])
    lager.lagre(mappe)
    lagret = lager.hent(mappe["sak_id"])
    for forbudt in ("saker", "tidslinje", "motsigelser", "relasjoner"):
        assert forbudt not in lagret, (
            f"«{forbudt}» er lagret — den skal regnes ved lesing")

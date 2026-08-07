"""En jobb tilhører den som lastet den opp (R153).

`/innsyn` hadde eierkontrollen, og begrunnelsen sto skrevet ved siden
av: «Nøkkelen er GYLDIG — men er den den SAMME? Uten dette kunne enhver
autentisert klient lese enhver annens økt, og økta bærer hele
dokumentteksten.»

`/jobb` bærer nøyaktig det samme — hele teksten, `felter` med
fødselsnummer og kontonummer — og hadde ingen kontroll. Målt med to
ekte nøkler: klient B leste klient A-s dokument, mens /innsyn svarte
404 på samme forsøk. Samme fil, samme utvikler, én rute som glemte.

TRE DØRER, IKKE ÉN
    GET  /jobb/<id>            statusen, med felter
    GET  /jobb/<id>/tekst      hele dokumentteksten
    POST /jobb/<id>/avbryt     å stoppe en annens arbeid
    POST /spor  jobb_id=<id>   å SPØRRE om en annens dokument

Den siste er lettest å glemme og like alvorlig: svaret siterer teksten.

404, ikke 403 — en fremmed skal ikke få vite at id-en finnes.
"""
import os
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api


class _Handler:
    """Bare det `_eier_jobben` trenger."""
    _eier_jobben = api.Handler._eier_jobben

    def __init__(self, klient_id):
        self._klient_id = klient_id


def test_eieren_slipper_inn():
    assert _Handler("uipath")._eier_jobben({"_eier": "uipath"})


def test_en_annen_klient_stenges_ute():
    assert not _Handler("testmaskin")._eier_jobben({"_eier": "uipath"})


def test_uten_nokkel_stenges_ute_fra_en_eid_jobb():
    assert not _Handler(None)._eier_jobben({"_eier": "uipath"})


def test_gamle_jobber_uten_eier_er_alles():
    """Jobber lagret av en eldre versjon har ingen eier. Å låse dem ute
    ville brutt en poll som var i gang da serveren ble oppgradert — og
    etter oppbevaringsfristen finnes de ikke lenger."""
    assert _Handler("hvem-som-helst")._eier_jobben({"jobb_id": "gammel"})


def _get(sti, klient_id, jobber):
    """Kjører den EKTE GET-ruteren med en oppdiktet klient.

    Kildetelling holder ikke: en vakt som bare teller kall til
    `_eier_jobben` blir grønn av `... and False`. Det er utfallet som
    skal måles, ikke at kallet står der."""
    H = api.Handler

    class Fake:
        _do_get_intern = H._do_get_intern
        _sti = H._sti
        _eier_jobben = H._eier_jobben
        _forventet_versjon = H._forventet_versjon
        path = sti
        headers = {}

        def __init__(self):
            self._klient_id = klient_id
            self.svar = None

        def _autorisert(self):
            return True

        def _rate_ok(self):
            return True

        def _svar(self, kode, data, hoder=None):
            self.svar = (kode, data)
            return (kode, data)

    f = Fake()
    # `_do_get_intern`, ikke `do_GET`: den ytre er bare sikkerhetsnettet
    # som gjør en uventet feil om til 500, og den ville svelget alt her.
    # Ingen `try` rundt — en feil skal STOPPE testen, ikke hoppe over
    # den. En vakt som hopper over seg selv er en garanti som ikke
    # finnes, men ser ut som den gjør.
    f._do_get_intern()
    return f.svar


FERDIG = {"jobb_id": "hemmelig1", "status": "ferdig", "versjon": 2,
          "tekst": "Fodselsnummer staar her", "antall_tegn": 23,
          "opprettet": "2026-08-08 10:00:00", "_eier": "uipath"}


@pytest.mark.parametrize("sti", ["/jobb/hemmelig1", "/jobb/hemmelig1/tekst"])
def test_en_fremmed_klient_faar_404_ikke_dokumentet(sti, monkeypatch):
    """Selve lekkasjen, målt på utfallet."""
    monkeypatch.setattr(api, "_jobber", {"hemmelig1": dict(FERDIG)})
    svar = _get(sti, "testmaskin", api._jobber)
    assert svar is not None, "ruteren svarte ikke"
    assert svar[0] == 404, f"fremmed klient fikk {svar[0]}"
    assert "Fodselsnummer" not in str(svar[1])


@pytest.mark.parametrize("sti", ["/jobb/hemmelig1", "/jobb/hemmelig1/tekst"])
def test_eieren_selv_faar_jobben_sin(sti, monkeypatch):
    """Speilet. Uten dette ville testen over vært grønn om ruteren
    svarte 404 på alt."""
    monkeypatch.setattr(api, "_jobber", {"hemmelig1": dict(FERDIG)})
    svar = _get(sti, "uipath", api._jobber)
    assert svar is not None and svar[0] == 200, f"eieren fikk {svar}"


def test_eieren_naar_aldri_ut_i_statussvaret(monkeypatch):
    """Kommer eieren ut, lekker den hvem ANDRE som bruker serveren."""
    monkeypatch.setattr(api, "_jobber", {"hemmelig1": dict(FERDIG)})
    svar = _get("/jobb/hemmelig1", "uipath", api._jobber)
    assert "_eier" not in svar[1] and "uipath" not in str(svar[1])


def test_eieren_lagres_til_disk_og_overlever_omstart(tmp_path, monkeypatch):
    """`_jobb_lagre` siler bort underscore-nøkler. Gjorde den det med
    eieren også, mistet den rettmessige eieren tilgangen til sin egen
    jobb ved neste omstart — og alle andre fikk den."""
    monkeypatch.setattr(api, "JOBB_STI", str(tmp_path))
    api._jobb_lagre({"jobb_id": "abc123", "status": "ferdig",
                     "opprettet": "2026-08-08 10:00:00",
                     "_eier": "uipath", "_data": b"skal ikke lagres"})
    import json
    lagret = json.loads((tmp_path / "abc123.json").read_text("utf-8"))
    assert lagret["_eier"] == "uipath"
    assert "_data" not in lagret, "filbytene skal aldri til disk"


def test_skrivingen_er_atomisk(tmp_path, monkeypatch):
    """Prosessen dør faktisk — README dokumenterer 0xC0000005 fra
    llama.cpp. Dør vi midt i skrivingen, skal den forrige filen stå
    urørt, ikke bli avkortet."""
    monkeypatch.setattr(api, "JOBB_STI", str(tmp_path))
    api._jobb_lagre({"jobb_id": "abc123", "status": "kø", "_eier": "a"})
    assert not list(tmp_path.glob("*.ny")), "midlertidig fil ble stående"
    api._jobb_lagre({"jobb_id": "abc123", "status": "ferdig", "_eier": "a"})
    import json
    assert json.loads(
        (tmp_path / "abc123.json").read_text("utf-8"))["status"] == "ferdig"


def test_en_odelagt_jobbfil_stopper_ikke_oppstarten(tmp_path, monkeypatch):
    """Én ødelagt fil skal koste ÉN jobb. Før dette fanget oppstarten
    bare FileNotFoundError, så en avkortet fil (JSONDecodeError, som er
    en ValueError) drepte serveren — og vakthunden startet på nytt og
    traff samme fil. En evig løkke med en datafil som årsak."""
    monkeypatch.setattr(api, "JOBB_STI", str(tmp_path))
    monkeypatch.setattr(api, "_jobber", {})
    (tmp_path / "avkortet.json").write_text('{"jobb_id": "x", "sta',
                                            encoding="utf-8")
    (tmp_path / "frisk.json").write_text(
        '{"jobb_id": "frisk", "status": "ferdig", '
        '"opprettet": "2026-08-08 10:00:00"}', encoding="utf-8")
    api._jobb_last_fra_disk()          # skal IKKE kaste
    assert "frisk" in api._jobber, "den friske jobben gikk tapt"
    assert "x" not in api._jobber

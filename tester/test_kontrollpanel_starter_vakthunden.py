"""
Kontrollpanelet er den ENESTE veien inn — så alt må starte derfra.

Brukeren kjører `start_kontrollpanel.bat` og ingenting annet. Da kan
ikke vakthunden ligge bak en .bat noen må huske å kjøre ved siden av:
gjør den det, kjører serveren uovervåket akkurat i den situasjonen
overvåkingen finnes for.

Bakgrunnen er målt. Vakthunden fanget hver død og skrev exitkoden —
men ingen oppstartsvei startet den. Panelet kjente bare
`start_api.bat`, og `start_alt.bat` gjorde det samme. Over to døgn døde
API-et gjentatte ganger uten at noe fanget hvorfor.

Den andre halvparten er stopp. Vakthunden holder ingen port og har
ingen vindustittel — de to kjennetegnene alt stopp-maskineri leter
etter. Drepes bare API-et, ser vakthunden en død server og starter den
igjen ~20 sekunder senere. Brukeren ser en tjeneste som «starter av seg
selv» og en «Stopp»-knapp som ikke virker.
"""
import io
import os

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUI = os.path.join(ROT, "skript", "api_klient_gui.py")
OPPSTART = os.path.join(ROT, "oppstart")


def _les(sti):
    return io.open(sti, encoding="utf-8", errors="replace").read()


def _tjenester():
    """Tjenestetabellen fra GUI-en, uten å importere tkinter.

    `ast.literal_eval` duger ikke: tabellen bruker fargekonstanter
    (`CYAN`, `BLAA` …) som er navn, ikke literaler. Vi tolker treet selv
    og lar et navn bli sin egen streng — fargene betyr ingenting her,
    det er `bat`, `vokter` og `key` testene ser på."""
    import ast
    tre = ast.parse(_les(GUI))

    def verdi(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return node.id                  # f.eks. CYAN
        if isinstance(node, ast.Dict):
            return {verdi(k): verdi(v)
                    for k, v in zip(node.keys, node.values)}
        if isinstance(node, (ast.List, ast.Tuple)):
            return [verdi(e) for e in node.elts]
        return None

    for node in tre.body:
        if isinstance(node, ast.Assign) and any(
                getattr(m, "id", "") == "KONTROLL_TJENESTER"
                for m in node.targets):
            return verdi(node.value)
    pytest.fail("fant ikke KONTROLL_TJENESTER i api_klient_gui.py")


def _api_tjeneste():
    for t in _tjenester():
        if t["key"] == "api":
            return t
    pytest.fail("ingen «api»-tjeneste i kontrollpanelet")


# ------------------------------------------------------------------ #
#  1. Panelet starter vakthunden, ikke API-et direkte                  #
# ------------------------------------------------------------------ #

def test_panelet_starter_vakthunden():
    """Kjernen: én knapp, og overvåkingen følger med."""
    assert _api_tjeneste()["bat"] == "start_api_med_vakthund.bat", (
        "Kontrollpanelet må starte vakthunden. Starter det "
        "start_api.bat, kjører serveren uovervåket for en bruker som "
        "aldri åpner en .bat selv.")


def test_baten_panelet_peker_paa_finnes():
    """En .bat som ikke finnes gir en «Starter …» som aldri blir grønn."""
    for t in _tjenester():
        sti = os.path.join(OPPSTART, t["bat"])
        assert os.path.isfile(sti), f"{t['key']}: mangler {t['bat']}"


def test_ingen_oppstartsvei_starter_api_et_uovervaaket():
    """Alle veier inn skal gå via vakthunden — ellers finnes det en
    dør der serveren kjører uten at noe fanger at den dør."""
    for navn in ("start_alt.bat",):
        kilde = _les(os.path.join(OPPSTART, navn))
        assert "start_api_med_vakthund.bat" in kilde, (
            f"{navn} starter API-et uten vakthund")
        # «start_api.bat» som eget ord skal ikke lenger stå der.
        # (start_api_med_vakthund.bat inneholder ikke strengen
        # «start_api.bat», så et enkelt søk holder.)
        assert "start_api.bat" not in kilde, (
            f"{navn} har fortsatt en uovervåket oppstartsvei")


# ------------------------------------------------------------------ #
#  2. Stopp må treffe vokteren FØRST                                   #
# ------------------------------------------------------------------ #

def test_api_tjenesten_navngir_sin_vokter():
    """Stopp-koden trenger å vite hvilken prosess som må dø først."""
    assert _api_tjeneste().get("vokter") == "vakthund.py"


def test_panelet_har_en_maate_aa_finne_vokteren_paa():
    kilde = _les(GUI)
    assert "_pids_for_python" in kilde, (
        "uten et prosessøk på kommandolinje finner panelet aldri "
        "vakthunden — den har verken port eller vindustittel")


def test_vokteren_drepes_for_porten():
    """Rekkefølgen ER innholdet i denne fiksen.

    Drepes porten først, rekker vakthunden å se en død server og starte
    den på nytt før den selv blir stoppet — og «Stopp» ser ut til å
    ikke virke."""
    kilde = _les(GUI)
    start = kilde.index("def _stopp_tjeneste")
    slutt = kilde.index("def _start_alt")
    kropp = kilde[start:slutt]
    # Måler KALLENE («self._navn(»), ikke navnene: kommentaren over
    # koden nevner begge, og et rent tekstsøk fant kommentaren først.
    i_vokter = kropp.index("self._pids_for_python(")
    i_port = kropp.index("self._pids_paa_port(")
    assert i_vokter < i_port, (
        "vakthunden må drepes FØR porten, ellers starter den API-et "
        "på nytt mens vi stopper det")


def test_stopp_alt_bat_stopper_ogsaa_vakthunden():
    """Samme hull fantes i .bat-en, og den er dokumentert i LES_MEG."""
    kilde = _les(os.path.join(OPPSTART, "stopp_alt.bat"))
    assert "vakthund.py" in kilde, (
        "stopp_alt.bat kan ikke stoppe vakthunden — den overlever "
        "«Stopp alt» og starter API-et igjen")

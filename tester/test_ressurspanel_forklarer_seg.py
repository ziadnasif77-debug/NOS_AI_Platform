"""
Ressursgrafene måler HELE maskinen — panelet må si det.

Målt tilfelle: brukeren trykket «STOPP ALT». Alle fire tjenestene ble
faktisk stoppet, og kortene viste rød prikk og «Stoppet». Rett under sto
CPU på 89 %, GPU på 100 % og VRAM på 7,0/8,0 GB.

Den eneste rimelige tolkningen av det bildet er at stoppknappen ikke
virket. Den var feil: maskinen ble holdt av en videokonvertering
(ffmpeg) og et annet prosjekts testkjøring — programmer panelet verken
starter, stopper eller kjenner til.

Det tok tre kommandoer i et terminalvindu å finne ut. Panelet ble bygget
nettopp for at det ikke skal trengs, så feilen er panelets: rammen sto
rett under tjenestelista og leses da som tjenestenes eget forbruk.
"""
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import api_klient_gui as gui


# ------------------------------------------------------------------ #
#  Rammen må si hva den måler                                         #
# ------------------------------------------------------------------ #

def test_rammen_sier_at_den_maaler_hele_maskinen():
    """Uten «hele maskinen» i tittelen står grafene under overskriften
    «Tjenester på denne maskinen» og arver dens betydning."""
    import inspect
    kilde = inspect.getsource(gui.KontrollPanel)
    plass = kilde.index("ressursramme = tema_rammefelt")
    tittel = kilde[plass:plass + 300]
    assert "HELE maskinen" in tittel, (
        "ressursrammen sier ikke at den måler hele maskinen — da leses "
        "den som tjenestenes eget forbruk")


# ------------------------------------------------------------------ #
#  Prosentene må kunne holdes opp mot grafen                          #
# ------------------------------------------------------------------ #

class _FalskProsess:
    def __init__(self, pid, navn, prosent):
        self.pid = pid
        self.info = {"name": navn, "cpu_percent": prosent}


def _falsk_psutil(prosesser, kjerner=12):
    class Falsk:
        @staticmethod
        def cpu_count():
            return kjerner

        @staticmethod
        def process_iter(_felt):
            return prosesser
    return Falsk


def test_prosenten_er_av_maskinen_ikke_av_en_kjerne(monkeypatch):
    """psutil teller 100 % per kjerne. «ffmpeg 620 %» ved siden av en
    graf som stopper på 100 er et tall ingen kan bruke."""
    monkeypatch.setattr(gui, "psutil", _falsk_psutil(
        [_FalskProsess(111, "ffmpeg.EXE", 620.0)]))
    maaler = gui.RessursMaaler.__new__(gui.RessursMaaler)
    navn, prosent = maaler.topp_cpu()[0]
    assert navn == "ffmpeg.EXE"
    assert prosent == pytest.approx(620.0 / 12)


def test_de_tyngste_kommer_forst(monkeypatch):
    monkeypatch.setattr(gui, "psutil", _falsk_psutil([
        _FalskProsess(111, "liten.exe", 24.0),
        _FalskProsess(222, "ffmpeg.EXE", 600.0),
        _FalskProsess(333, "mellom.exe", 120.0)]))
    maaler = gui.RessursMaaler.__new__(gui.RessursMaaler)
    assert [n for n, _ in maaler.topp_cpu()] == [
        "ffmpeg.EXE", "mellom.exe", "liten.exe"]


def test_egen_prosess_og_systemtomgang_telles_ikke(monkeypatch):
    """«System Idle Process» (pid 0) står for all ledig tid og ville
    ligget øverst hver eneste gang."""
    monkeypatch.setattr(gui, "psutil", _falsk_psutil([
        _FalskProsess(0, "System Idle Process", 1100.0),
        _FalskProsess(4, "System", 400.0),
        _FalskProsess(os.getpid(), "pythonw.exe", 300.0),
        _FalskProsess(999, "ffmpeg.EXE", 200.0)]))
    maaler = gui.RessursMaaler.__new__(gui.RessursMaaler)
    assert [n for n, _ in maaler.topp_cpu()] == ["ffmpeg.EXE"]


def test_uten_psutil_faller_den_stille_tilbake(monkeypatch):
    """Panelet skal virke også der psutil mangler — da uten lista."""
    monkeypatch.setattr(gui, "psutil", None)
    maaler = gui.RessursMaaler.__new__(gui.RessursMaaler)
    assert maaler.topp_cpu() == []


# ------------------------------------------------------------------ #
#  Selve tilfellet: alt stoppet, maskinen likevel opptatt             #
# ------------------------------------------------------------------ #

def _panel(status):
    p = gui.KontrollPanel.__new__(gui.KontrollPanel)
    p._status = status
    return p


def test_sier_uttrykkelig_at_lasten_kommer_utenfra():
    """Setningen som manglet. Uten den er fire røde prikker over en
    CPU-graf i 89 % umulig å tolke som noe annet enn en feil."""
    p = _panel({"api": "stoppet", "prefect": "stoppet", "tunnel": "stoppet"})
    tekst = p._forbrukertekst(89.0, [("ffmpeg.EXE", 52.0),
                                     ("python.exe", 18.0)])
    assert "Alle tjenestene over er stoppet" in tekst
    assert "ANDRE programmer" in tekst
    assert "ffmpeg.EXE 52 %" in tekst


def test_ingen_paastand_om_andre_programmer_naar_noe_kjorer():
    """Kjører en tjeneste, er det ikke lenger noe mysterium — og da
    ville setningen vært direkte misvisende."""
    p = _panel({"api": "kjorer", "prefect": "stoppet"})
    tekst = p._forbrukertekst(89.0, [("python.exe", 61.0)])
    assert "Alle tjenestene over er stoppet" not in tekst
    assert "python.exe 61 %" in tekst


def test_stille_maskin_uten_tjenester_utloser_ingen_advarsel():
    """Alt stoppet OG maskinen rolig er den normale hviletilstanden."""
    p = _panel({"api": "stoppet"})
    tekst = p._forbrukertekst(3.0, [("explorer.exe", 2.0)])
    assert "ANDRE programmer" not in tekst


def test_tom_liste_gir_tom_tekst():
    p = _panel({"api": "stoppet"})
    assert p._forbrukertekst(90.0, []) == ""

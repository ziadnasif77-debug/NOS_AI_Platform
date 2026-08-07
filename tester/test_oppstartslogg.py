"""
Oppstartsloggen skal ALDRI slettes — den er beviset.

Bakgrunnen er målt: over to døgn døde API-et gjentatte ganger.
Vakthunden fanget hver død og skrev exitkoden med teksten «se
oppstart_api.log for traceback». Men `_skjult.vbs` — den andre
oppstartsveien — omdirigerte med `>`, som TØMMER fila. Loggen viste
fem omstarter samme dag og ÉN oppstartsbanner: hver eneste traceback
bak dem var slettet av oss selv.

To skrivere, én fil, og bare den ene visste at den ødela den andres
arbeid. Denne testen holder dem i sync.
"""
import io
import os
import re

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VBS = os.path.join(ROT, "oppstart", "_skjult.vbs")
VAKTHUND = os.path.join(ROT, "skript", "vakthund.py")


def _les(sti):
    return io.open(sti, encoding="utf-8", errors="replace").read()


def test_vbs_legger_til_og_skriver_ikke_over():
    """Den ekte feilen: `>` i stedet for `>>`."""
    kilde = _les(VBS)
    assert " >> " in kilde, (
        "_skjult.vbs må legge TIL loggen (>>). Med > tømmes fila, og "
        "vakthundens tracebacker slettes av neste oppstart.")
    # Sjekken må gjelde KOMMANDOEN som bygges, ikke hele fila: « > »
    # forekommer også som VBScripts større-enn i størrelsessjekken for
    # rotasjonen, og `2>&1` er en helt legitim stderr-omdirigering.
    kommandolinjer = "".join(
        l for l in kilde.splitlines()
        if "kommando" in l or (l.strip().startswith('"') and " q " in l))
    assert " > " not in kommandolinjer, (
        f"_skjult.vbs bygger fortsatt en overskrivende « > »-"
        f"omdirigering:\n{kommandolinjer}")
    assert "2>&1" in kilde, "stderr skal fortsatt fanges"


def test_vakthunden_apner_i_tilleggsmodus():
    """Speilet: vakthunden må heller ikke skrive over."""
    kilde = _les(VAKTHUND)
    assert 'open(logg_api, "a"' in kilde, (
        "vakthund.py må åpne oppstart_api.log med «a». Med «w» sletter "
        "den sin egen forrige krasjlogg ved hver omstart.")


def test_vakthunden_kaprer_ikke_fila_cmd_alt_eier():
    """Den andre halvparten av «to skrivere, én fil».

    Startes vakthunden av `_skjult.vbs`, omdirigerer cmd allerede hele
    .bat-en til oppstart_api.log — og det håndtaket er EKSKLUSIVT på
    Windows. Åpnet vakthunden samme fil selv, døde den med
    PermissionError før den rakk å starte noe. Målt, ikke antatt: det
    skjedde i det kontrollpanelet ble koblet til vakthunden.

    Regelen: er vår egen stdout alt fanget, arver barnet den."""
    kilde = _les(VAKTHUND)
    assert "def _barnets_utgang" in kilde
    assert "isatty" in kilde, (
        "vakthunden må kunne skille et konsoll fra en fanget stdout — "
        "ellers kaprer den fila cmd allerede holder")


def test_barnets_utgang_arver_naar_stdout_er_fanget(monkeypatch, tmp_path):
    """Kjører den ekte funksjonen i begge tilstander."""
    import sys
    sys.path.insert(0, os.path.join(ROT, "skript"))
    import vakthund

    class FangetStdout:
        def isatty(self):
            return False

    class Konsoll:
        def isatty(self):
            return True

    # ROT peker på en midlertidig mappe: testen skal ALDRI ta i den
    # levende oppstart_api.log. Gjorde den det, feilet den her med
    # nøyaktig den PermissionError-en den er skrevet for å forhindre —
    # fordi en kjørende vakthund holder fila. En test som konkurrerer
    # med produksjon om et filhåndtak måler noe annet enn den tror.
    monkeypatch.setattr(vakthund, "ROT", str(tmp_path))

    monkeypatch.setattr(vakthund.sys, "stdout", FangetStdout())
    assert vakthund._barnets_utgang() is None, (
        "med fanget stdout skal barnet ARVE, ikke åpne fila på nytt")

    monkeypatch.setattr(vakthund.sys, "stdout", Konsoll())
    ut = vakthund._barnets_utgang()
    assert ut is not None and hasattr(ut, "write"), (
        "i et konsoll skal vakthunden åpne loggfila selv")
    ut.close()
    assert (tmp_path / "data" / "logger" / "oppstart_api.log").is_file()


def test_begge_skriverne_peker_paa_samme_fil():
    """Er de blitt to ULIKE filer, er testene over uten mening — men
    da må det være et bevisst valg, ikke en glipp.

    `start_alt.bat` sender loggstien inn i _skjult.vbs som argument;
    vakthunden bygger sin egen. Sammenligningen går derfor mot
    .bat-fila, ikke mot .vbs-en."""
    bat = _les(os.path.join(ROT, "oppstart", "start_alt.bat"))
    assert "oppstart_api.log" in bat
    assert "oppstart_api.log" in _les(VAKTHUND)


def test_begge_roterer_saa_loggen_ikke_vokser_fritt():
    """En logg som bare legges til, må roteres et sted. Uten dette
    ville fiksen over byttet «slettet bevis» mot «full disk»."""
    assert "MoveFile" in _les(VBS), "_skjult.vbs roterer ikke"
    assert "_roter_om_stor" in _les(VAKTHUND), "vakthund.py roterer ikke"


def test_rotasjonen_beholder_forrige_vindu():
    """Rotasjon som SLETTER i stedet for å arkivere er samme feil i ny
    innpakning. Begge sider skal flytte til «.1»."""
    assert '.1' in _les(VBS)
    assert '".1"' in _les(VAKTHUND) or "sti + \".1\"" in _les(VAKTHUND)


def test_roter_om_stor_virker(tmp_path, monkeypatch):
    """Kjører den ekte funksjonen — en rotasjonsrutine som aldri er
    prøvd er en rutine som svikter den dagen loggen blir stor."""
    import sys
    sys.path.insert(0, os.path.join(ROT, "skript"))
    import vakthund

    logg = tmp_path / "oppstart_api.log"
    logg.write_bytes(b"x" * 2048)

    monkeypatch.setattr(vakthund, "MAKS_LOGG_MB", 10)
    vakthund._roter_om_stor(str(logg))
    assert logg.exists(), "liten logg skal IKKE roteres"

    # Nå over grensen
    monkeypatch.setattr(vakthund, "MAKS_LOGG_MB", 0)
    vakthund._roter_om_stor(str(logg))
    assert (tmp_path / "oppstart_api.log.1").exists(), "arkivet mangler"
    assert not logg.exists(), "originalen skulle vært flyttet"
    assert (tmp_path / "oppstart_api.log.1").read_bytes() == b"x" * 2048


def test_roter_om_stor_taaler_at_fila_ikke_finnes():
    """Første oppstart på en ny maskin: ingen logg ennå."""
    import sys
    sys.path.insert(0, os.path.join(ROT, "skript"))
    import vakthund
    vakthund._roter_om_stor(os.path.join(ROT, "finnes", "ikke.log"))

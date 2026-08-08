"""Oppbevaringsryddingen (rydd_gjennomgang.py).

At tørrkjøring aldri sletter, at --slett kun tar filer eldre enn
vinduet — og at UTFALLET er mulig å skille fra utsiden.

Det siste var hullet (R158). `rydd()` returnerte ett tall, og
tørrkjøring returnerte det SAMME tallet som ekte sletting: «3» betydde
enten «tre filer ble slettet» eller «tre filer er forfalt og står der
fortsatt». `__main__` kastet dessuten verdien og satte ingen exitkode.

En jobb i Oppgaveplanleggeren kunne dermed kjøre hver uke i månedsvis,
skrive «ville slettet: …» til loggen, og aldri utløse et varsel. En
oppbevaringspolicy som ikke blir håndhevet, men ser ut som den blir
det, er verre enn ingen policy — det er nøyaktig den påstanden
docstringen i dette skriptet selv gjør om README.
"""
import importlib
import os
import subprocess
import sys
import time

sys.path.insert(0, "skript")

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _last(monkeypatch, tmp, dager=30):
    monkeypatch.setenv("GJENNOMGANG_STI", str(tmp))
    monkeypatch.setenv("OPPBEVARING_DAGER", str(dager))
    # ISOLER LABEL STUDIO-BASEN (R179). Ryddingen spør nå basen om
    # hvilke bilder som venter på retting. Uten dette leste testene den
    # EKTE basen på maskinen — og «skaanet» ble 7 her og 0 hos neste
    # utvikler. Samme feilklasse som «1557 passed var bare sant på én
    # maskin» (R174), bare i miniatyr.
    monkeypatch.setenv("LABEL_STUDIO_BASE_DATA_DIR",
                       str(tmp / "ingen-label-studio"))
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
    svar = r.rydd(slett=True)
    assert svar["slettet"] == 1
    assert not gammel.exists()      # eldre enn 30 dager → slettet
    assert ny.exists()              # innenfor vinduet → beholdt


def test_ingen_mappe_er_trygt(monkeypatch, tmp_path):
    r = _last(monkeypatch, tmp_path, 30)
    svar = r.rydd(slett=True)
    assert svar["slettet"] == 0     # ingen bilder-mappe → 0, ingen feil
    assert svar["mappe_mangler"] is True


# ------------------------------------------------------------------ #
#  Utfallet må være mulig å skille fra utsiden (R158)                  #
# ------------------------------------------------------------------ #

def test_torrkjoring_og_ekte_sletting_gir_ULIKE_svar(monkeypatch, tmp_path):
    """Selve hullet. Returnerte de samme verdi, kunne ingen kaller —
    og ingen jobbplanlegger — se at policyen ikke ble håndhevet."""
    r = _last(monkeypatch, tmp_path, 30)
    bilder = tmp_path / "bilder"
    bilder.mkdir()
    for i in range(3):
        _lag_bilde(bilder, f"gammel{i}.png", 40)

    # Bare nøklene denne testen HANDLER om. En eksakt ordbok-likhet
    # gjorde at hvert nye felt i svaret brakk testen uten at noe var
    # galt — og et rødt lys som ikke betyr noe blir slått av (R179).
    def _kjerne(d):
        return {k: d[k] for k in
                ("funnet", "slettet", "torrkjoring", "mappe_mangler")}

    torr = r.rydd(slett=False)
    assert _kjerne(torr) == {"funnet": 3, "slettet": 0, "torrkjoring": True,
                             "mappe_mangler": False}
    ekte = r.rydd(slett=True)
    assert _kjerne(ekte) == {"funnet": 3, "slettet": 3, "torrkjoring": False,
                             "mappe_mangler": False}
    assert torr != ekte


def test_exitkoden_sier_om_policyen_ble_haandhevet(monkeypatch, tmp_path):
    r = _last(monkeypatch, tmp_path, 30)
    assert r._exitkode({"funnet": 0, "slettet": 0, "torrkjoring": True,
                        "mappe_mangler": False}) == 0
    assert r._exitkode({"funnet": 3, "slettet": 3, "torrkjoring": False,
                        "mappe_mangler": False}) == 0
    assert r._exitkode({"funnet": 3, "slettet": 0, "torrkjoring": True,
                        "mappe_mangler": False}) == 1
    assert r._exitkode({"funnet": 0, "slettet": 0, "torrkjoring": True,
                        "mappe_mangler": True}) == 2


def _kjor(tmp_path, *args):
    """Kjører skriptet som en jobbplanlegger ville gjort: eget
    prosessrom, omdirigert utdata, og ingen UTF-8-konsoll."""
    miljo = dict(os.environ, GJENNOMGANG_STI=str(tmp_path),
                 OPPBEVARING_DAGER="30", PYTHONIOENCODING="cp1252")
    return subprocess.run(
        [sys.executable, os.path.join(ROT, "skript", "rydd_gjennomgang.py"),
         *args], cwd=ROT, env=miljo, capture_output=True, text=True,
        encoding="utf-8", errors="replace")


def test_forfalte_filer_i_torrkjoring_gir_exitkode_1(tmp_path):
    bilder = tmp_path / "bilder"
    bilder.mkdir()
    _lag_bilde(bilder, "gammel.png", 40)
    r = _kjor(tmp_path)
    assert r.returncode == 1, r.stderr
    assert "FORFALT" in r.stderr


def test_manglende_mappe_gir_exitkode_2(tmp_path):
    r = _kjor(tmp_path)
    assert r.returncode == 2, r.stderr
    assert "INGEN oppbevaringspolicy" in r.stderr


def test_utfort_sletting_gir_exitkode_0(tmp_path):
    bilder = tmp_path / "bilder"
    bilder.mkdir()
    _lag_bilde(bilder, "gammel.png", 40)
    r = _kjor(tmp_path, "--slett")
    assert r.returncode == 0, r.stderr


def test_meldingene_overlever_en_konsoll_uten_utf8(tmp_path):
    """Hver melding her har æøå. Under omdirigering til fil kastet
    `print` UnicodeEncodeError FØR skriptet rakk å si hva det gjorde —
    og exitkoden ble 1 uansett utfall. Dette er den eneste fila i
    treningsløkka som manglet stdout-vakten."""
    bilder = tmp_path / "bilder"
    bilder.mkdir()
    _lag_bilde(bilder, "gammel.png", 40)
    r = _kjor(tmp_path, "--slett")
    assert "UnicodeEncodeError" not in r.stderr, r.stderr
    assert "Slettet 1" in r.stdout


def test_stien_utledes_fra_prosjektrota_ikke_arbeidsmappa(tmp_path):
    """Oppgaveplanleggeren starter i System32. Med en relativ sti pekte
    «./data/gjennomgang» et helt annet sted, mappa fantes ikke, og
    skriptet meldte «ingenting å rydde» med exitkode 0 — en policy som
    rapporterer suksess fordi den leter på feil sted (CLAUDE.md §1)."""
    miljo = {k: v for k, v in os.environ.items() if k != "GJENNOMGANG_STI"}
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'" + os.path.join(ROT, "skript")
         + "'); import rydd_gjennomgang as m; print(m.GJENNOMGANG_STI)"],
        cwd=str(tmp_path), env=miljo, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    assert ROT.lower() in r.stdout.strip().lower(), (
        f"stien ble {r.stdout.strip()!r}, ikke under prosjektrota")

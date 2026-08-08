"""Rotasjon av API-nøkler — verdien skal ALDRI vises (R169).

En nøkkel som har vært synlig én gang er brent: i en terminal som
scroller, i et skjermbilde, i en chatlogg, i en samtale med en
assistent. Det er nettopp derfor du roterer.

Skriver rotasjonen ut den NYE verdien, har den brent den i samme
øyeblikk som den lagde den — og du står der du startet. Derfor skriver
skriptet bare et fingeravtrykk.

Testene her bruker en midlertidig .env. De rører aldri den ekte.
"""
import io
import os
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))

import roter_nokkel as rn

EN_ENV = """# Kommentar
API_NOKKEL=gammel-hemmelig-verdi-1234
API_NOKLER=uipath:gammel-uipath-verdi,testmaskin:gammel-test-verdi
PORT=8600
export ANNET=noe
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    sti = tmp_path / ".env"
    sti.write_text(EN_ENV, encoding="utf-8")
    monkeypatch.setattr(rn, "ENV_STI", str(sti))
    return sti


def test_finner_alle_nokkelnavn(env):
    """`API_NOKLER` er en liste — hver oppføring er en egen nøkkel."""
    navn = rn.nokkelnavn(rn.les_env(str(env)))
    assert set(navn) == {"API_NOKKEL", "uipath", "testmaskin"}


def test_verdien_staar_ALDRI_i_det_som_returneres(env):
    """Kjernen. Alt skriptet gir fra seg går rett i en terminal."""
    svar = rn.roter("API_NOKKEL")
    assert svar["ok"]
    ny = rn._verdi_paa_linja(
        [l for l in env.read_text(encoding="utf-8").splitlines()
         if l.startswith("API_NOKKEL=")][0])[1]
    assert ny not in str(svar), "den nye verdien lekket ut i svaret"
    assert "gammel-hemmelig-verdi-1234" not in str(svar)


def test_nokkelen_ble_faktisk_byttet(env):
    for_ = rn.nokkelnavn(rn.les_env(str(env)))["API_NOKKEL"]
    svar = rn.roter("API_NOKKEL")
    etter = rn.nokkelnavn(rn.les_env(str(env)))["API_NOKKEL"]
    assert for_ != etter
    assert svar["gammelt_avtrykk"] == for_
    assert svar["nytt_avtrykk"] == etter


def test_den_nye_nokkelen_er_lang_nok(env):
    """`secrets.token_urlsafe(32)` gir 43 tegn og 256 bits entropi.
    Serveren krever selv en minstelengde."""
    rn.roter("API_NOKKEL")
    ny = rn._verdi_paa_linja(
        [l for l in env.read_text(encoding="utf-8").splitlines()
         if l.startswith("API_NOKKEL=")][0])[1]
    assert len(ny) >= 40


def test_to_rotasjoner_gir_to_ulike_nokler(env):
    """`secrets`, ikke `random`. En forutsigbar nøkkel er ingen nøkkel."""
    a = rn.roter("API_NOKKEL")["nytt_avtrykk"]
    b = rn.roter("API_NOKKEL")["nytt_avtrykk"]
    assert a != b


def test_en_navngitt_nokkel_roteres_ALENE(env):
    """De andre i `API_NOKLER` skal stå urørt — ellers låser du ut alle
    klientene for å bytte én."""
    for_ = rn.nokkelnavn(rn.les_env(str(env)))
    rn.roter("uipath")
    etter = rn.nokkelnavn(rn.les_env(str(env)))
    assert etter["uipath"] != for_["uipath"]
    assert etter["testmaskin"] == for_["testmaskin"]
    assert etter["API_NOKKEL"] == for_["API_NOKKEL"]


def test_resten_av_fila_staar_urort(env):
    """En .env bærer mer enn nøkler. Mister du PORT eller en
    kommentar, oppdager du det på verste tidspunkt."""
    rn.roter("API_NOKKEL")
    linjer = env.read_text(encoding="utf-8").splitlines()
    assert "# Kommentar" in linjer
    assert "PORT=8600" in linjer
    assert "export ANNET=noe" in linjer


def test_sikkerhetskopi_tas_for_skriving(env, tmp_path):
    svar = rn.roter("API_NOKKEL")
    kopi = tmp_path / svar["sikkerhetskopi"]
    assert kopi.exists()
    assert "gammel-hemmelig-verdi-1234" in kopi.read_text(encoding="utf-8")


def test_ingen_midlertidig_fil_blir_staaende(env, tmp_path):
    """Skrivingen er atomisk (tmp + os.replace). En halvskrevet .env
    låser deg ute av din egen server."""
    rn.roter("API_NOKKEL")
    assert not list(tmp_path.glob("*.ny"))


def test_ukjent_nokkel_gir_feil_og_lar_fila_vaere(env):
    for_ = env.read_text(encoding="utf-8")
    svar = rn.roter("finnes-ikke")
    assert not svar["ok"]
    assert "uipath" in svar["kjente"]
    assert env.read_text(encoding="utf-8") == for_


def test_manglende_env_gir_feil_ikke_krasj(tmp_path, monkeypatch):
    monkeypatch.setattr(rn, "ENV_STI", str(tmp_path / "finnes-ikke.env"))
    assert rn.roter("API_NOKKEL")["ok"] is False


def test_skriptet_skriver_aldri_ut_en_verdi():
    """Kildekontroll. En `print` av selve verdien ville gjort hele
    verktøyet meningsløst — og det er en linje noen legger inn i beste
    mening, for å være hjelpsom."""
    import inspect
    import re
    kilde = inspect.getsource(rn)
    # Bare PRINT-linjer. Et grovere søk («ny_verdi)») treffer helt
    # legitime funksjonskall og gjør vakten til støy — og en vakt som
    # roper på riktig kode blir slått av, ikke fikset.
    for linje in kilde.splitlines():
        s = linje.strip()
        if not (s.startswith("print(") or s.startswith("sys.stdout.write")):
            continue
        # VARIABELEN, ikke ordet. Første forsøk traff
        # `print("… (avtrykk, ikke verdi):")` — altså prosa som forklarer
        # nettopp at verdien IKKE vises. En vakt som slår ned på teksten
        # som beskriver den riktige oppførselen, måler bokstaver og ikke
        # mening.
        uten_strenger = re.sub(r'"[^"]*"|\'[^\']*\'', "", s)
        assert "ny_verdi" not in uten_strenger, (
            f"verdien kan lekke ut i en utskrift: {s}")
    # Og returverdien skal bare bære avtrykk, aldri nøkkelen selv.
    assert '"nytt_avtrykk": fingeravtrykk(ny_verdi)' in kilde
    assert '"verdi"' not in kilde

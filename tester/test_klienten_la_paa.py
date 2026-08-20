"""
R240: at klienten legger på er ikke en serverfeil.

Målt 2026-08-20. Et skannet saksmappe-dokument ble lest ferdig, klassifisert
og sendt til Label Studio. Idet 200-svaret skulle skrives ut, ga klienten
opp å vente, og serverloggen fikk dette:

    !!! Uventet serverfeil (korrelasjon=6d92a5b0...):
    Traceback (most recent call last):
      ...
    ConnectionAbortedError: [WinError 10053] An established connection was
    aborted by the software in your host machine

Forespørselen LYKTES. Likevel ser den ut som et krasj i loggen.

Hvorfor det er verdt en test og ikke bare en opprydning: vakthunden finnes
fordi tjenesten falt gjentatte ganger uten at noe fanget hvorfor
(`skript/vakthund.py`). Da er falske krasj i loggen ikke støy — de er det
som gjør en ekte krasj vanskelig å finne. En logg man må sile manuelt er
en logg ingen leser.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import dokument_api as api


class _Falsk:
    """Nok av en handler til å kalle `_serverfeil` uten en ekte socket."""

    def __init__(self):
        self.command = "POST"
        self.path = "/dokument"
        self.svar = []

    _KLIENTEN_LA_PAA = api.Handler._KLIENTEN_LA_PAA
    _serverfeil = api.Handler._serverfeil

    def _korrelasjonsid(self):
        return "test-korrelasjon"

    def _svar(self, kode, kropp):
        self.svar.append((kode, kropp))
        return "svar-sendt"


def test_klientavbrudd_gir_ingen_stakksporing(capsys):
    h = _Falsk()
    h._serverfeil(ConnectionAbortedError(10053, "aborted"))
    ut = capsys.readouterr()
    samlet = ut.out + ut.err

    assert "Uventet serverfeil" not in samlet, (
        "klientavbrudd logges fortsatt som en uventet serverfeil — da "
        "drukner ekte krasj i falske")
    assert "Traceback" not in samlet
    assert "klienten lukket forbindelsen" in samlet


def test_klientavbrudd_forsoker_ikke_aa_svare():
    """Socketen ligger nede. Et 500-svar kan ikke leveres, og forsøket
    ville bare kastet en gang til."""
    h = _Falsk()
    h._serverfeil(ConnectionResetError("reset"))
    assert h.svar == [], (
        "serveren prøvde å skrive et svar på en forbindelse klienten "
        "allerede har lukket")


def test_alle_tre_avbruddstypene_dekkes():
    """Windows gir ConnectionAborted, Linux ConnectionReset, og en
    halvskrevet kropp gir BrokenPipe. Mappa skal kunne kopieres til en
    hvilken som helst server, så alle tre må behandles likt."""
    for feil in (ConnectionAbortedError("a"), ConnectionResetError("b"),
                 BrokenPipeError("c")):
        h = _Falsk()
        h._serverfeil(feil)
        assert h.svar == [], f"{type(feil).__name__} ble ikke gjenkjent"


def _fanget(feil):
    """En exception som FAKTISK er kastet — den har en stakksporing,
    slik en ekte feil i serveren har."""
    try:
        raise feil
    except type(feil) as e:
        return e


def test_ekte_feil_logges_fortsatt_i_sin_helhet(capsys):
    """Motprøven — R240 skal ikke gjøre serveren tauser om ekte feil."""
    h = _Falsk()
    h._serverfeil(_fanget(ValueError("noe gikk virkelig galt")))
    ut = capsys.readouterr()
    samlet = ut.out + ut.err

    assert "Uventet serverfeil" in samlet
    assert "Traceback" in samlet
    assert "noe gikk virkelig galt" in samlet
    assert h.svar and h.svar[0][0] == 500, (
        "en ekte feil skal fortsatt gi klienten et ærlig 500-svar")


def test_feilen_logges_selv_uten_aktiv_exception(capsys):
    """`_serverfeil` fikk exceptionen som argument, men leste den fra
    omgivelsene. Kalt utenfor en except-blokk skrev den «NoneType: None»
    — taushet nettopp der loggen skal si mest."""
    h = _Falsk()
    h._serverfeil(ValueError("stillhet er verst"))
    ut = capsys.readouterr()
    samlet = ut.out + ut.err

    assert "NoneType: None" not in samlet
    assert "stillhet er verst" in samlet


def test_klienten_faar_ikke_se_detaljene():
    """Uendret fra før: stakksporingen kan lekke interne stier."""
    h = _Falsk()
    h._serverfeil(ValueError("hemmelig sti C:\\noe\\internt"))
    _kode, kropp = h.svar[0]
    assert "hemmelig" not in str(kropp)
    assert kropp["ok"] is False

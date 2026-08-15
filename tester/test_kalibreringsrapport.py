"""
Kalibreringsrapporten (R197): veien UT av kalibreringsdataene.

Mekanismen for å samle inn fantes (R149), og regnestykket fantes
(delt/kalibrering.py) — men ingenting koblet dem, så spørsmålet
«betyr konfidensen noe?» kunne fortsatt ikke besvares. En innsamling
uten en vei ut er verre enn ingen innsamling: den ser ut som om noen
måler.
"""
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import kalibreringsrapport as kr


# ------------------------------------------------------------------ #
#  «Var lesingen riktig?» — definisjonen fasiten hviler på            #
# ------------------------------------------------------------------ #

def test_identisk_tekst_er_riktig():
    assert kr._cer("Saksnummer: 4417820", "Saksnummer: 4417820") == 0.0


def test_mellomromsretting_er_ikke_en_feillesing():
    """En annotatør retter ofte et mellomrom uten at lesingen var gal.
    Paa en region paa 18 tegn er ett mellomrom 5,6 % CER — en fasit som
    straffer det maaler annotatoervaner, ikke OCR-kvalitet."""
    assert kr.var_riktig("Saksnummer: 4417820", "Saksnummer:4417820")
    assert kr.var_riktig("Ola  Nordmann", "Ola Nordmann")


def test_ekte_tegnfeil_paa_kort_tekst_teller_som_feil():
    """Motprøven: ett FEIL tegn er en feillesing, ogsaa paa kort tekst."""
    assert not kr.var_riktig("Ola Nordmann", "Ola Nordmenn")
    assert not kr.var_riktig("4 812,00", "9 812,00")


def test_ekte_feillesing_teller_som_feil():
    cer = kr._cer("Beloep: 4 812,00", "Beloep: 9 812,00")
    assert cer > 0


def test_tom_retting_er_ikke_riktig():
    assert kr._cer("noe tekst", "") == 1.0


# ------------------------------------------------------------------ #
#  Parene som bygges fra Label Studio                                 #
# ------------------------------------------------------------------ #

def _oppgave(konfidens, raa, rettet, med_annotering=True):
    o = {"id": 1, "data": {"konfidens": konfidens, "tekst": raa,
                           "bilde": "/data/x.png", "fil_id": "abc"}}
    if med_annotering:
        o["annotations"] = [{"completed_by": 1, "result": [
            {"type": "textarea", "value": {"text": [rettet]}}]}]
    return o


@pytest.fixture
def falsk_eksport(monkeypatch):
    import eksporter_fra_label_studio as eks

    def _lag(oppgaver):
        monkeypatch.setattr(eks, "hent_fullforte_oppgaver",
                            lambda pid: oppgaver)
        monkeypatch.setattr(eks, "_arkiver_bilde", lambda *a: "arkiv/x.png")
        return eks
    return _lag


def test_konfidens_regnes_om_fra_prosent(falsk_eksport):
    """Label Studio lagrer konfidensen i PROSENT (sendingen ganger med
    100), mens tabellen regner i 0-1. Bommer omregningen, havner ALT i
    den øverste bøtta og tabellen blir meningsløs."""
    falsk_eksport([_oppgave(95.0, "tekst", "tekst")])
    par, _ = kr.hent_par(prosjekt_id=1)
    assert par == [(0.95, True)]


def test_feillest_dokument_blir_et_negativt_par(falsk_eksport):
    falsk_eksport([_oppgave(60.0, "Beloep 4812", "Beloep 9812 kroner ekstra")])
    par, _ = kr.hent_par(prosjekt_id=1)
    assert len(par) == 1 and par[0][1] is False


def test_oppgaver_uten_konfidens_telles_som_hoppet_over(falsk_eksport):
    """Et datasett som stille mister halvparten av observasjonene gir en
    tabell som ser solid ut. Derfor telles det som ikke kan brukes."""
    o = _oppgave(90.0, "a", "a")
    del o["data"]["konfidens"]
    falsk_eksport([o])
    par, hoppet = kr.hent_par(prosjekt_id=1)
    assert par == []
    assert sum(hoppet.values()) == 1


def test_uannotert_oppgave_hoppes_over(falsk_eksport):
    falsk_eksport([_oppgave(90.0, "a", "", med_annotering=False)])
    par, hoppet = kr.hent_par(prosjekt_id=1)
    assert par == [] and sum(hoppet.values()) == 1


def test_ugyldig_konfidens_hoppes_over(falsk_eksport):
    falsk_eksport([_oppgave(9000.0, "a", "a")])
    par, hoppet = kr.hent_par(prosjekt_id=1)
    assert par == [] and sum(hoppet.values()) == 1


# ------------------------------------------------------------------ #
#  Rapporten skal si fra når den ikke kan svare                       #
# ------------------------------------------------------------------ #

def test_tomt_grunnlag_gir_veiledning_ikke_en_tabell(capsys):
    kode = kr.skriv_rapport([], {"ingen retting": 3})
    ut = capsys.readouterr().out
    assert kode == 1
    assert "KALIBRERING_ANDEL" in ut, (
        "en tom rapport skal si HVORDAN tabellen fylles, ikke bare at "
        "den er tom")


def test_adr_0004_aapnes_ikke_paa_tynt_grunnlag(capsys):
    """Fem observasjoner er ikke nok til å åpne en beslutning som
    handler om å ta dokumenter FRA menneskelig gjennomgang."""
    kr.skriv_rapport([(0.95, True)] * 5, {})
    ut = capsys.readouterr().out
    assert "venter fortsatt" in ut


def test_overmodighet_ropes_ut(capsys):
    """Den farlige retningen: systemet er sikrere enn det har grunn til,
    så dokumenter slipper forbi terskelen uten at noen ser dem."""
    par = [(0.95, False)] * 20 + [(0.95, True)] * 5
    kr.skriv_rapport(par, {})
    ut = capsys.readouterr().out
    assert "OVERMODIGE" in ut

"""
Tester for S5: identifikatorlista i skjema-prompten filtreres mot MALEN.

Bakgrunnen er R57. Den deterministiske parseren VET hvilket av tallene
på en kvittering som er et gyldig telefonnummer, og den kunnskapen skal
modellen få i stedet for å gjette. Men lista ble bygget uansett hva
malen inneholdt: en mal som bare ba om et beløp fikk fødselsnummer og
kontonummer servert til språkmodellen. Persondata ingen hadde bedt om,
og plass som ellers går til dokumentteksten.

Den vanskelige delen er norsk orddanning. «kontonummer» er konto+nummer,
men «kontornavn» er kontor+navn — og begge inneholder «konto». Matchet
vi på delstreng alene, ville en mal som spør om KONTORETS navn fått
personens kontonumre.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from delt.tekstuttrekk import identifikatortyper_i_mal


# ------------------------------------------------------------------ #
#  1. Malen styrer                                                     #
# ------------------------------------------------------------------ #

def test_mal_uten_identifikatorer_ber_om_ingen():
    """Kjernen i S5: her ble fødselsnummeret sendt til modellen før."""
    assert identifikatortyper_i_mal({"belop": "", "dato": ""}) == set()


def test_mal_som_ber_om_fnr_far_fnr():
    assert "fodselsnummer" in identifikatortyper_i_mal({"fodselsnummer": ""})
    assert "fodselsnummer" in identifikatortyper_i_mal({"fnr": ""})
    assert "fodselsnummer" in identifikatortyper_i_mal({"personnummer": ""})


def test_bare_de_etterspurte_typene_kommer_med():
    typer = identifikatortyper_i_mal({"telefon": "", "belop": ""})
    assert typer == {"telefonnummer"}


def test_flere_typer_samtidig():
    typer = identifikatortyper_i_mal(
        {"kontonummer": "", "orgnr": "", "epost": ""})
    assert typer == {"kontonummer", "organisasjonsnummer", "epost"}


# ------------------------------------------------------------------ #
#  2. Norsk orddanning — der delstrengsmatching tar feil               #
# ------------------------------------------------------------------ #

def test_kontornavn_ber_ikke_om_kontonummer():
    """Fella. «kontornavn» inneholder delstrengen «konto», men spør om
    NAV-kontorets navn. Med delstrengsmatching ville malen fått
    personens kontonumre servert til modellen."""
    assert identifikatortyper_i_mal({"kontornavn": ""}) == set()


def test_kontonummer_kommer_likevel_med():
    """Motprøven — vakten over må ikke ha slått ut det ekte treffet."""
    assert identifikatortyper_i_mal({"kontonummer": ""}) == {"kontonummer"}
    assert identifikatortyper_i_mal({"konto": ""}) == {"kontonummer"}


@pytest.mark.parametrize("felt", ["organisering", "organisasjon"])
def test_ord_som_bare_ligner_orgnr_teller_ikke(felt):
    assert "organisasjonsnummer" not in identifikatortyper_i_mal({felt: ""})


# ------------------------------------------------------------------ #
#  3. Formen på malen skal ikke ha noe å si                            #
# ------------------------------------------------------------------ #

def test_nostede_maler_leses():
    mal = {"person": {"kontakt": {"telefon": ""}}, "sum": ""}
    assert identifikatortyper_i_mal(mal) == {"telefonnummer"}


def test_lister_leses():
    mal = {"mottakere": [{"epost": ""}, {"epost": ""}]}
    assert identifikatortyper_i_mal(mal) == {"epost"}


def test_plassholdere_i_tekst_leses():
    """«Ring {telefon}» ber om telefonnummeret like mye som en egen
    nøkkel gjør."""
    assert identifikatortyper_i_mal({"melding": "Ring {telefon} ved spørsmål"}) \
        == {"telefonnummer"}


def test_aeoa_og_understrek_spiller_ingen_rolle():
    for navn in ("fødselsnummer", "fodselsnummer", "fodsels_nummer",
                 "Fødselsnummer", "fodselsNummer"):
        assert "fodselsnummer" in identifikatortyper_i_mal({navn: ""}), navn


def test_tom_mal_krasjer_ikke():
    for mal in ({}, [], None, "", {"a": None}):
        assert identifikatortyper_i_mal(mal) == set()


# ------------------------------------------------------------------ #
#  4. Prompten som faktisk bygges                                      #
# ------------------------------------------------------------------ #

def test_hintlista_nevner_ikke_fnr_nar_malen_ikke_ber_om_det(monkeypatch):
    """Ende til ende. MERK hva som måles: dokumentteksten SELV står i
    prompten uansett — modellen kan ikke lese et dokument den ikke får.
    Det S5 gjelder er HINTLISTA vi legger til på toppen: «- <nr> er et
    gyldig fødselsnummer». Den løfter nummeret fram og gjør det til noe
    modellen er bedt om å bruke, i en mal som ikke spurte."""
    import dokument_api as api
    from syntetiske_nummer import lag_fnr

    fnr = lag_fnr(0)
    dokument = (f"Kvittering\nFnr: {fnr}\nKontonummer: 1234.56.78903\n"
                f"Beløp: kr 486,00\nTelefon: 41288903\n")
    sett = {}

    def falsk_generer(prompt, *a, **kw):
        sett["prompt"] = prompt
        return '{"belop": "486,00"}', None

    monkeypatch.setattr(api, "_borealis_generer", falsk_generer)
    api.fyll_skjema_kjerne(dokument, {"belop": ""})

    prompt = sett["prompt"]
    for hint in (f"- {fnr} er et gyldig", "- 1234.56.78903 er et gyldig",
                 "- 41288903 er et gyldig"):
        assert hint not in prompt, f"hintet «{hint}…» skulle vært filtrert"
    # dokumentteksten er der, som den skal
    assert fnr in prompt


def test_prompten_nevner_fnr_nar_malen_ber_om_det(monkeypatch):
    """Motprøven: R57 skal fortsatt virke. Filtreringen må ikke ha tatt
    fra modellen den kunnskapen den trenger."""
    import dokument_api as api
    from syntetiske_nummer import lag_fnr

    fnr = lag_fnr(0)
    dokument = f"Skjema\nFnr: {fnr}\nBeløp: kr 486,00\n"
    sett = {}

    def falsk_generer(prompt, *a, **kw):
        sett["prompt"] = prompt
        return '{"fodselsnummer": "%s"}' % fnr, None

    monkeypatch.setattr(api, "_borealis_generer", falsk_generer)
    api.fyll_skjema_kjerne(dokument, {"fodselsnummer": ""})

    assert f"- {fnr} er et gyldig fødselsnummer" in sett["prompt"]

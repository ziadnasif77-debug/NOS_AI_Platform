"""
Vakt mot omvendte feltnavn — på ALLE ruter, ikke bare noen.

Bakgrunnen er målt mot den kjørende serveren. UiPath bygger
`TextFormDataPart` med VERDIEN først og NAVNET sist (R63). Bytter en
utvikler om, havner verdien som feltnavn. På `/dokument` ble det stoppet
med 400. På `/spor` skjedde dette:

    riktig vei   → svar = «Beløp: 38 250,50 kr»
    omvendt vei  → svar = hele dokumentteksten
                   ok: true, advarsel: null, HTTP 200

Spørsmålet nådde aldri fram, «sporsmal» ble tomt, R47 slo inn («fil uten
spørsmål → returner teksten ordrett»), og roboten fikk et fullstendig
vellykket svar som ikke var svaret på spørsmålet den stilte. Det er den
farligste feilmodusen i hele API-et: ikke et krasj, men et galt svar som
ser riktig ut.

Fire av åtte POST-ruter manglet vakten. Denne testen holder alle åtte i
sjakk, og fanger den neste ruten som legges til uten et feltsett.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api


# ------------------------------------------------------------------ #
#  1. Fritekst som feltnavn — den varianten ordlista ikke fanget       #
# ------------------------------------------------------------------ #

def test_sporsmal_som_feltnavn_gjenkjennes():
    """Den ekte feilen: hele spørsmålet havner som navn."""
    assert api._ser_ut_som_verdi("Hva er beløpet?")
    assert api._ser_ut_som_verdi("Hvem gjelder vedtaket")
    assert api._ser_ut_som_verdi("x" * 41)


def test_bryterverdi_som_feltnavn_gjenkjennes_fortsatt():
    """Den opprinnelige varianten skal ikke ha falt ut."""
    for verdi in ("ja", "nei", "auto", "felter", "modell", "PÅ", "off"):
        assert api._ser_ut_som_verdi(verdi), verdi


def test_ekte_feltnavn_slipper_gjennom():
    """Speilet — uten dette beviser testene over ingenting.

    Prøven går gjennom `_sjekk_feltnavn`, ikke `_ser_ut_som_verdi`
    direkte, fordi det er DEN veien serveren bruker: bare navn som
    allerede er UKJENTE for ruten blir vurdert som mulig omvendte.

    Skillet er ikke pedanteri. «felter» og «modell» er både gyldige
    feltnavn OG gyldige bryterverdier, så `_ser_ut_som_verdi("felter")`
    er sann — og skal være det. Den kjennes igjen som feltnavn først, og
    nås derfor aldri av verdiprøven."""
    for rute, kjente in sorted(api._FELTSETT_PER_RUTE.items()):
        sendt = {navn: "ja" for navn in kjente}
        milde, omvendte = api._sjekk_feltnavn(sendt, kjente)
        assert not omvendte, (
            f"{rute}: vakten tar disse EKTE feltnavnene for verdier: "
            f"{omvendte}")
        assert not milde, f"{rute}: {milde} er ukjente for sin egen rute"


def test_ukjent_men_uskyldig_navn_er_bare_mildt():
    """Et navn som verken er en verdi eller fritekst skal gi en mild
    advarsel, ikke 400. Ellers ville en klient med en skrivefeil fått
    forespørselen avvist i stedet for et svar med varsel."""
    milde, omvendte = api._sjekk_feltnavn({"tullefelt": "x"},
                                          api._KJENTE_FELT_DOKUMENT)
    assert milde == ["tullefelt"]
    assert omvendte == []


# ------------------------------------------------------------------ #
#  2. Alle POST-ruter er dekket                                        #
# ------------------------------------------------------------------ #

def _post_ruter_i_koden():
    """Rutene serveren faktisk svarer på i POST-veien, lest ut av
    kilden. En hardkodet liste ville råtnet i det noen la til en rute.

    `inspect.getsource` gir nøyaktig metodekroppen — å klippe i filen på
    tekstsøk traff feil sted og ga tom liste."""
    import inspect
    blokk = inspect.getsource(api.Handler._do_post_intern)
    return set(re.findall(r'sti == "(/[a-z_/]+)"', blokk))


def test_hver_post_rute_har_et_feltsett():
    """Fanger den neste ruten som legges til uten vakt.

    `/ekko` er det ENESTE unntaket, og det er bevisst: den finnes for å
    vise klienten nøyaktig hva serveren mottok. Avviste den en omvendt
    del med 400, ville den skjult akkurat det feilsøkeren kom for å se."""
    UNNTAK = {"/ekko"}
    ruter = _post_ruter_i_koden()
    assert ruter, "fant ingen POST-ruter — testen leser feil sted"
    udekket = sorted(ruter - set(api._FELTSETT_PER_RUTE) - UNNTAK)
    assert not udekket, (
        f"Disse POST-rutene har ingen feltnavnvakt: {udekket}. Legg dem "
        f"i _FELTSETT_PER_RUTE med feltene de faktisk godtar. Er ruten "
        f"med vilje uten vakt, før den opp i UNNTAK her — så er det et "
        f"valg og ikke en glipp.")


def test_feltsettene_peker_paa_ekte_ruter():
    """Motsatt vei: et feltsett for en rute som ikke finnes er dødt
    vedlikehold, og skjuler at ruten det gjaldt er borte."""
    ruter = _post_ruter_i_koden()
    ukjente = sorted(set(api._FELTSETT_PER_RUTE) - ruter)
    assert not ukjente, f"feltsett uten rute: {ukjente}"


def test_spor_kjenner_feltene_den_faktisk_leser():
    """`_KJENTE_FELT_SPOR` må dekke det håndtereren leser, ellers
    avvises en gyldig forespørsel — eller verre, en gyldig verdi blir
    tatt for et omvendt navn."""
    for felt in ("sporsmal", "jobb_id", "korriger", "maks_sider",
                 "strekkoder"):
        assert felt in api._KJENTE_FELT_SPOR, felt


# ------------------------------------------------------------------ #
#  3. Feilsvaret sier hva som er galt                                  #
# ------------------------------------------------------------------ #

def test_feilsvaret_navngir_bade_det_gale_og_det_riktige():
    """En 400 som bare sier «feil felt» hjelper ingen. Svaret skal
    navngi det omvendte navnet OG listen over gyldige."""
    svar = api._omvendt_felt_feil(["Hva er beløpet?"],
                                  api._KJENTE_FELT_SPOR)
    assert svar["ok"] is False
    assert "Hva er beløpet?" in svar["ukjente_felt"]
    assert "sporsmal" in svar["kjente_felt"]
    assert svar["feil"]

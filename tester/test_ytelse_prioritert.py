"""Hvilken ytelse dokumentet GJELDER — ikke hvilke det NEVNER (R183).

Den gamle regelen var én linje: `max(treff, key=len)` over hele teksten.
Målt på et helt vanlig NAV-skjema:

    «NAV 04-01.03 / Søknad om dagpenger ved arbeidsledighet»
    + standardavsnittet «er du sykmeldt, søk sykepenger …»
    →  arbeidsavklaringspenger   (AAP)

Ikke fordi AAP ble nevnt oftest — det ble nevnt ÉN gang — men fordi
«arbeidsavklaringspenger» er det lengste navnet i lista (23 tegn) og
«dagpenger» det korteste (9). AAP slo alt det ble nevnt sammen med, og
dagpenger kunne bare vinne når det sto HELT alene i dokumentet.

Lengderegelen var ment for OVERLAPPENDE navn: «uførepensjon» skal ikke
bli «pensjon». Den ble brukt på navn som ikke deler ett eneste tegn.
Målt har lista i dag NULL overlappende par — regelen vernet altså mot et
tilfelle som ikke finnes, mens den ødela det som faktisk skjer. Selve
omslutningssaken er beholdt, men løst ved OMSLUTNING, som er det den
handler om.

Beviset rangeres nå etter hvor lett det lar seg forfalske av
standardtekst: skjemanummer > tittel > brødtekst. Og der beviset ikke
rekker, svarer koden ingenting — med en grunn. Å gjette er ikke et
svar mottakeren kan skille fra et funn.
"""
import sys

sys.path.insert(0, ".")

import pytest

from delt.konstanter import NORSKE_YTELSER
from delt.tekstuttrekk import (GENERISKE_BLANKETTER, _skjema_ytelse,
                               _ytelsestreff, finn_alle_ytelser,
                               finn_skjemanummer, finn_ytelse,
                               finn_ytelse_prioritert)

# Selve dokumentet fra målingen: tittelen sier dagpenger, brødteksten
# ramser opp åtte andre ytelser som standardinformasjon.
SOKNAD_DAGPENGER = """NAV 04-01.03
Søknad om dagpenger ved arbeidsledighet

Er du sykmeldt, skal du søke om sykepenger i stedet.
Har du nedsatt arbeidsevne, kan arbeidsavklaringspenger være aktuelt.
Er du over 62 år kan du ha rett til alderspensjon.
Ved omsorg for barn gjelder foreldrepenger, svangerskapspenger,
pleiepenger og omsorgspenger. Se også reglene om uføretrygd.
"""

LEGEERKLARING = """NAV 08-07.04
Legeerklæring ved arbeidsuførhet

Denne erklæringen kan brukes ved søknad om sykepenger,
arbeidsavklaringspenger, uføretrygd, pleiepenger eller omsorgspenger.
"""

AAP_VEDTAK = """Vedtak om arbeidsavklaringspenger
Vedtaksdato: 17.05.2024
Du har mottatt sykepenger fram til 30.04.2024.
"""


# ------------------------------------------------------------------ #
#  Selve regresjonen                                                   #
# ------------------------------------------------------------------ #

def test_soknad_om_dagpenger_er_dagpenger_ikke_aap():
    """Feilen som utløste hele regelen."""
    assert finn_ytelse(SOKNAD_DAGPENGER) == "dagpenger"


def test_vedtaket_er_om_ytelsen_i_tittelen_ikke_den_det_vises_til():
    """Nesten hvert NAV-vedtak åpner med å nevne ytelsen det avløser.
    Kalte vi det tvetydig, tidde vi om de vanligste dokumentene vi får."""
    assert finn_ytelse(AAP_VEDTAK) == "arbeidsavklaringspenger"


def test_ingenting_gaar_tapt_lista_har_fortsatt_alle():
    """Entallsfeltet svarer på «hva gjelder saken», lista på «hva
    nevnes». Å skjerpe det første skal ikke tømme det andre."""
    alle = finn_alle_ytelser(SOKNAD_DAGPENGER)
    assert alle[0] == "dagpenger"
    assert "arbeidsavklaringspenger" in alle
    assert len(alle) == 9


# ------------------------------------------------------------------ #
#  Negative regler: når koden skal la være å svare                     #
# ------------------------------------------------------------------ #

def test_generisk_blankett_faar_ingen_ytelse():
    """En legeerklæring lister ytelsene skjemaet KAN brukes til. Ingen
    av dem er sakens tema, og teksten alene kan ikke skille dem."""
    dom = finn_ytelse_prioritert(LEGEERKLARING)
    assert dom["navn"] is None
    assert dom["grunn"] == "generisk_blankett"
    # …men kandidatene er ikke kastet — de er nettopp det et menneske
    # trenger for å avgjøre raskt.
    assert "arbeidsavklaringspenger" in dom["kandidater"]


def test_flere_i_teksten_uten_holdepunkt_i_tittelen():
    brev = ("NAV Arbeid og ytelser\nPostboks 354, 8601 Mo i Rana\n\n"
            "Utbetalingene omfatter sykepenger for januar, dagpenger for "
            "februar og etterbetaling av uføretrygd.")
    dom = finn_ytelse_prioritert(brev)
    assert dom["navn"] is None
    assert dom["grunn"] == "flere_i_teksten"
    assert dom["kandidater"] == ["sykepenger", "dagpenger", "uforetrygd"]


def test_en_enkelt_ytelse_i_broedteksten_er_godt_nok():
    """Negative regler skal ikke bli en av-bryter: står det ÉN ytelse og
    ingenting motsier den, er det et svar."""
    brev = ("NAV Arbeid og ytelser\nPostboks 354, 8601 Mo i Rana\n\n"
            "Vi har registrert kravet ditt om sykepenger.")
    dom = finn_ytelse_prioritert(brev)
    assert dom["navn"] == "sykepenger"
    assert dom["kilde"] == "tekst"


def test_uten_ytelse_er_det_ingen_grunn_heller():
    """«Ingen ytelse nevnt» er ikke det samme som «vi nektet å velge».
    Blandes de, kan ingen telle hvor ofte roboten faktisk står fast."""
    dom = finn_ytelse_prioritert("Et brev uten ytelser. Datert 01.03.2024.")
    assert dom == {"navn": None, "kilde": None, "grunn": None,
                   "kandidater": []}


# ------------------------------------------------------------------ #
#  Omslutning — saken lengderegelen EGENTLIG fantes for                #
# ------------------------------------------------------------------ #

def test_kortere_navn_inne_i_et_lengre_er_samme_forekomst():
    """Ett treff som ligger helt inne i et annet er samme ord skrevet
    kortere. Der — og bare der — vinner det lange."""
    treff = _ytelsestreff("Saken gjelder gjenlevendepensjon.")
    assert [n for _, _, n in treff] == ["gjenlevendepensjon"]


def test_to_ulike_ytelser_er_to_opplysninger():
    """De deler ingen tegn. Da er lengden på ordet uten betydning."""
    treff = _ytelsestreff("sykepenger og dagpenger")
    assert [n for _, _, n in treff] == ["sykepenger", "dagpenger"]


# ------------------------------------------------------------------ #
#  Skjemanummer — mekanismen, ikke tallene                             #
# ------------------------------------------------------------------ #

def test_skjemanummer_leses_ut_av_teksten():
    assert finn_skjemanummer(SOKNAD_DAGPENGER) == "NAV 04-01.03"
    assert finn_skjemanummer("uten nummer") is None


def test_skjemanummertabellen_er_tom_med_vilje():
    """Jeg har ikke en verifisert liste over NAVs blankettnummer, og et
    oppdiktet nummer ville gitt en SIKKER feilklassifisering med
    HØYESTE prioritet — den overstyrer både tittel og tekst. Er fila
    fylt ut senere, skal denne testen endres bevisst."""
    assert _skjema_ytelse() == {}


def test_bare_kjente_ytelsesnavn_godtas_i_tabellen(tmp_path, monkeypatch):
    """En tastefeil i regelfila skal ikke skape en ytelse resten av
    systemet ikke kjenner."""
    import delt.tekstuttrekk as tu
    fil = tmp_path / "skjemanummer_ytelse.txt"
    fil.write_text("# kommentar\n"
                   "NAV 04-01.03 = dagpenger\n"
                   "NAV 99-99.99 = fantasiytelse\n", encoding="utf-8")
    monkeypatch.setattr(tu, "_regelfil", lambda navn: str(fil))
    monkeypatch.setattr(tu, "_SKJEMA_YTELSE_BUFFER", None)
    assert tu._skjema_ytelse() == {"NAV 04-01.03": "dagpenger"}


def test_skjemanummer_slaar_tittelen(tmp_path, monkeypatch):
    """Blanketten er trykt på arket. Den lar seg ikke påvirke av
    ordvalg, og går derfor foran overskriften."""
    import delt.tekstuttrekk as tu
    fil = tmp_path / "skjemanummer_ytelse.txt"
    fil.write_text("NAV 04-01.03 = sykepenger\n", encoding="utf-8")
    monkeypatch.setattr(tu, "_regelfil", lambda navn: str(fil))
    monkeypatch.setattr(tu, "_SKJEMA_YTELSE_BUFFER", None)
    dom = tu.finn_ytelse_prioritert(SOKNAD_DAGPENGER)
    assert dom["navn"] == "sykepenger"        # ikke «dagpenger» fra tittelen
    assert dom["kilde"] == "skjemanummer"


# ------------------------------------------------------------------ #
#  At forutsetningene mine faktisk holder                              #
# ------------------------------------------------------------------ #

def test_lista_har_ingen_overlappende_navn_i_dag():
    """Hele begrunnelsen for å fjerne lengderegelen. Kommer det en dag
    et par som overlapper, skal denne bli rød — ikke for at noe er galt,
    men for at omslutningsregelen da faktisk brukes, og bør få en test
    med ekte data i stedet for denne."""
    par = [(a, b) for a in NORSKE_YTELSER for b in NORSKE_YTELSER
           if a != b and a in b]
    assert par == []


@pytest.mark.parametrize("type_", sorted(GENERISKE_BLANKETTER))
def test_generiske_blanketter_er_ekte_dokumenttyper(type_):
    """Et navn som ikke finnes i `_DOKUMENTTYPER` ville aldri matchet,
    og unntakslista ville stått der som ren dekorasjon."""
    from delt.tekstuttrekk import _DOKUMENTTYPER
    assert type_ in {navn for navn, _ in _DOKUMENTTYPER}

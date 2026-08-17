"""
Livssyklusen skal brukes av observability også (§30, R214).

§30, andre kulepunkt: «Canonical state machine er dokumentert én gang og
brukt av API, eventer, adaptere og OBSERVABILITY.»

De tre første kom på plass med R198. Den fjerde var et hull som ingen
hadde sett etter, fordi de tre andre var så synlige: `/metrics` kunne
fortelle hvor mange forespørsler som kom inn og hvor lang tid de tok,
men ikke hvor mange jobber som endte i `feil` — eller hvor mange som ble
stående i `i_ko` fordi arbeidstråden var død.

Det er nettopp de to spørsmålene en vakthavende stiller klokka tre om
natta.

ETIKETTEN ER DEN OFFENTLIGE VERDIEN
Ikke den interne. Ellers ville et dashbord vist «pågår» og «kjorer» som
to forskjellige ting — og æøå i en metrikk-etikett er dessuten forbudt
av §26, av nøyaktig samme grunn som i JSON: en maskinlesbar verdi skal
ikke kreve tegnsett.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

from delt import maalinger, tilstander


@pytest.fixture(autouse=True)
def tomme_maalinger():
    maalinger.nullstill()
    yield
    maalinger.nullstill()


def test_metrikken_finnes_og_er_beskrevet():
    """En metrikk uten HELP-linje er et tall ingen tør tolke."""
    maalinger.tell("nav_jobb_tilstand_total", tilstand="ferdig")
    ut = maalinger.tekst()
    assert "nav_jobb_tilstand_total" in ut
    assert "# HELP nav_jobb_tilstand_total" in ut
    assert "# TYPE nav_jobb_tilstand_total counter" in ut


def test_jobbtilstander_telles_naar_de_endres():
    import dokument_api as api
    jobb = {"jobb_id": "t1", "status": "kø", "versjon": 1}
    api._jobb_status(jobb, "sender")
    api._jobb_status(jobb, "pågår")
    ut = maalinger.tekst()
    assert 'tilstand="sender"' in ut
    assert 'tilstand="kjorer"' in ut, (
        "den INTERNE verdien «pågår» havnet i metrikken — da viser "
        "dashbordet to navn for samme tilstand")


def test_ingen_metrikk_etikett_har_aeoeaa():
    """§26 forbyr æøå i maskinlesbare verdier. En metrikk-etikett er
    like maskinlesbar som en JSON-enum."""
    for t in tilstander.OFFENTLIGE:
        maalinger.tell("nav_jobb_tilstand_total", tilstand=t)
    ut = maalinger.tekst()
    for linje in ut.splitlines():
        if linje.startswith("nav_jobb_tilstand_total"):
            assert not (set("æøåÆØÅ") & set(linje)), linje


def test_avvist_overgang_telles_IKKE():
    """En ulovlig overgang skal ikke se ut som at noe skjedde. Telles
    den, ville en avbrutt jobb som en tråd prøvde å gjøre «ferdig», stått
    som ferdig i statistikken mens API-et sa avbrutt."""
    import dokument_api as api
    jobb = {"jobb_id": "t2", "status": "avbrutt", "versjon": 3}
    api._jobb_status(jobb, "ferdig")
    assert 'tilstand="ferdig"' not in maalinger.tekst()


def test_metrikken_kan_ikke_felle_en_jobb():
    """Observability er til for jobben, ikke omvendt."""
    import inspect
    import dokument_api as api
    kilde = inspect.getsource(api._jobb_status)
    plass = kilde.index("nav_jobb_tilstand_total")
    assert "try:" in kilde[:plass], (
        "metrikkallet er ikke beskyttet — en feil i tellingen ville "
        "stoppet en jobb som ellers gikk fint")


def test_alle_kanoniske_tilstander_kan_telles():
    """Dukker det opp en tilstand metrikken ikke kjenner, er de to
    listene på vei fra hverandre — og da er §30 brutt igjen."""
    for t in tilstander.OFFENTLIGE:
        maalinger.tell("nav_jobb_tilstand_total", tilstand=t)
    ut = maalinger.tekst()
    for t in tilstander.OFFENTLIGE:
        assert f'tilstand="{t}"' in ut

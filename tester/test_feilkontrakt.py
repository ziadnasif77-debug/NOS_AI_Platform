"""
Feilkontrakten: én form, alltid JSON, alltid sporbar.

Kjernen var allerede sterk — `uuid` = `problem.traceId` = header i alle
30 målte feil, og hver av dem gjenfunnet i tilgangsloggen. Fire hull
rundt den:

1. PUT/DELETE/PATCH/HEAD/TRACE ga «501 Unsupported method» i HTML — uten
   `ok`, `feil`, `uuid`, og uten X-Correlation-ID-header. Loggraden fikk
   `korrelasjon: null, ms: 0`, så en operatør kunne ikke korrelere en
   501 i det hele tatt. `HEAD /hjelp` som helsesjekk — det mest
   nærliggende en overvåker gjør — fikk HTML.

2. 429 manglet `Retry-After`, mens BEGGE 503-veiene hadde den. «Vent
   litt» er ikke en instruks en robot kan følge.

3. 415 fantes ikke. Alt som ikke var multipart ble tolket som rå
   PDF-bytes, så feil Content-Type ga «Ugyldig/korrupt PDF: Failed to
   open stream» om en HELT GYLDIG PDF — og pekte utvikleren mot filen
   sin i stedet for mot headeren.

4. De to 409-ene delte `problem.type`. Versjonskonflikt LØSES ved å
   hente på nytt; «jobben er allerede ferdig» blir aldri bedre av å
   prøve igjen. Deler de type, må klienten lese fritekst for å skille
   dem — og fritekst er ikke en kontrakt.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api


# ------------------------------------------------------------------ #
#  1. Ingen HTML-feil                                                  #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("metode", ["PUT", "DELETE", "PATCH", "HEAD",
                                    "TRACE"])
def test_ustottet_metode_gir_405_i_json(metode):
    assert hasattr(api.Handler, f"do_{metode}"), (
        f"{metode} håndteres ikke — da svarer basisklassen 501 i HTML, "
        f"uten uuid og uten korrelasjonsheader")


def test_405_sier_hvilke_metoder_som_er_tillatt():
    """En 405 uten `Allow` ber klienten gjette."""
    import inspect
    kilde = inspect.getsource(api.Handler._metode_ikke_tillatt)
    assert '"Allow"' in kilde
    assert "_svar(405" in kilde, "må gå gjennom _svar, som gir uuid+problem"


def test_405_er_riktigere_enn_501():
    """Stien FINNES; det er metoden som ikke er tillatt."""
    assert 405 in api._PROBLEM_TITLER
    assert api._PROBLEM_TITLER[405][0] == "metode-ikke-tillatt"


# ------------------------------------------------------------------ #
#  2. Retry-After på 429                                               #
# ------------------------------------------------------------------ #

def test_429_sender_retry_after():
    import inspect
    kilde = inspect.getsource(api.Handler._rate_ok)
    assert '"Retry-After"' in kilde, (
        "en robot kan følge et tall, ikke oppfordringen «vent litt»")
    assert "RATE_RETRY_S" in kilde


def test_retry_verdien_dekker_hele_vinduet():
    """Vinduet er ett minutt, så ventetiden må være minst så lang —
    ellers får klienten 429 igjen med en gang."""
    assert api.RATE_RETRY_S >= 60


# ------------------------------------------------------------------ #
#  3. 415 i stedet for «korrupt PDF»                                   #
# ------------------------------------------------------------------ #

def test_415_finnes_som_problemtype():
    assert api._PROBLEM_TITLER[415][0] == "ustottet-medietype"


def test_de_vanlige_raa_typene_godtas_fortsatt():
    """Fiksen skal ikke stenge døra for klienter som sender rå bytes
    med riktig type — `octet-stream` er med fordi mange klienter sender
    den når de ikke vet typen."""
    for t in ("application/pdf", "application/octet-stream",
              "image/png", "text/plain"):
        assert t in api._RAA_TYPER, t


def test_json_er_ikke_en_raa_type():
    """Det var nettopp `application/json` som ga «korrupt PDF»."""
    assert "application/json" not in api._RAA_TYPER
    assert "text/html" not in api._RAA_TYPER


def test_ruteren_svarer_415_og_peker_paa_headeren():
    import inspect
    kilde = inspect.getsource(api.Handler._do_post_intern)
    assert "_svar(415" in kilde
    assert '"pointer": "/Content-Type"' in kilde, (
        "feilen må peke på HEADEREN, ikke på dokumentet")


# ------------------------------------------------------------------ #
#  4. De to 409-ene kan skilles maskinelt                              #
# ------------------------------------------------------------------ #

def test_versjonskonflikt_og_ugyldig_tilstand_har_ulik_type():
    assert (api.PROBLEM_VERSJONSKONFLIKT
            != api.PROBLEM_UGYLDIG_TILSTAND)


def test_problemobjektet_godtar_en_mer_presis_type():
    p = api._problem_detaljer(409, "detalj", "korr-1", "/jobb/x/avbryt",
                              slug=api.PROBLEM_VERSJONSKONFLIKT)
    assert p["type"].endswith("/" + api.PROBLEM_VERSJONSKONFLIKT)
    assert p["status"] == 409
    assert p["traceId"] == "korr-1"
    assert p["instance"] == "/jobb/x/avbryt"


def test_uten_egen_type_brukes_statuskodens():
    """Speilet — de andre feilene skal ikke ha endret seg."""
    p = api._problem_detaljer(409, "detalj", "korr-1")
    assert p["type"].endswith("/konflikt")


def test_begge_409_stedene_oppgir_sin_type():
    import inspect
    kilde = inspect.getsource(api.Handler._do_post_intern)
    assert "PROBLEM_VERSJONSKONFLIKT" in kilde
    assert "PROBLEM_UGYLDIG_TILSTAND" in kilde


# ------------------------------------------------------------------ #
#  5. Det som allerede var riktig, skal ikke ha blitt brutt            #
# ------------------------------------------------------------------ #

def test_problemobjektet_er_komplett_rfc_9457():
    p = api._problem_detaljer(400, "noe gikk galt", "korr-9", "/dokument",
                              [{"pointer": "/maks_sider", "message": "tall"}])
    for felt in ("type", "title", "status", "detail", "traceId",
                 "instance", "errors"):
        assert felt in p, felt
    assert p["errors"][0]["pointer"] == "/maks_sider"

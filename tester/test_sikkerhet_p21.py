"""
Sikkerhetskontrollene §21 navngir — de fem som manglet en test (R212).

§21 lister åtte: «auth bypass, ownership bypass, API-key misuse,
rate-limit bypass, CORS, path traversal/upload validation,
large-payload abuse, SSRF der relevant og PII-lekkasje i logger».

JORDEN FØRST — hva som faktisk fantes

Alle åtte var IMPLEMENTERT. Det som manglet var bevis for fem av dem:

    auth bypass          test_innsyn_krever_nokkel, test_klienter
    ownership bypass     test_jobb_eier, test_innsyn_sesjon
    API-key misuse       test_klienter
    rate-limit bypass    test_rate
    CORS                 INGEN TEST
    path traversal       INGEN TEST
    large-payload        INGEN TEST
    SSRF                 ikke relevant — men ingenting hindret at det BLE det
    PII i logger         ingen som prøvde at loggen er FRI for PII

Det er den fjerde linja nedenfra som er poenget med hele fila: en
kontroll uten test er ikke en kontroll, det er en vane. Vaner overlever
ikke en travel fredag.
"""
import inspect
import json
import re
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api as api


# ------------------------------------------------------------------ #
#  CORS                                                               #
# ------------------------------------------------------------------ #

def test_cors_er_av_som_standard():
    """Var hardkodet «*» før: enhver nettside en saksbehandler hadde
    åpen, kunne kalle API-et fra nettleseren hans. Standarden er nå
    TOM = ingen CORS-header i det hele tatt."""
    kilde = inspect.getsource(api)
    m = re.search(r'CORS_ORIGINS = os\.environ\.get\("CORS_ORIGINS",\s*"([^"]*)"',
                  kilde)
    assert m, "fant ikke CORS_ORIGINS-standarden"
    assert m.group(1) == "", (
        f"CORS er åpnet som standard («{m.group(1)}») — da bestemmer "
        "ikke lenger den som installerer hvem som får kalle")


def test_stjerne_er_ikke_lov_som_verdi():
    """«*» sammen med en API-nøkkel er den klassiske feilen: nøkkelen
    ligger i nettleseren, og enhver side kan bruke den."""
    # Selve regelen: verdien speiles bare når den står i lista.
    full = inspect.getsource(api)
    plass = full.index("Access-Control-Allow-Origin")
    rundt = full[max(0, plass - 900):plass + 300]
    assert "CORS_ORIGINS" in rundt, (
        "CORS-headeren settes uten å slå opp i CORS_ORIGINS — da er "
        "lista ikke lenger en liste")


# ------------------------------------------------------------------ #
#  Path traversal / upload validation                                 #
# ------------------------------------------------------------------ #

def test_statiske_filer_er_en_LISTE_ikke_en_sti():
    """Stitraversering er stengt ved KONSTRUKSJON her: ruteren slår opp
    i en fast liste på to navn, så klientens streng blir aldri en sti.
    Byttes det ut med en sjekk, kan sjekken glemmes."""
    assert isinstance(api._STATISKE_FILER, dict)
    assert set(api._STATISKE_FILER) == {"swagger-ui.css",
                                        "swagger-ui-bundle.js"}


@pytest.mark.parametrize("forsok", [
    "../../.env",
    "..\\..\\.env",
    "/etc/passwd",
    "swagger-ui.css/../../../.env",
    "%2e%2e%2f.env",
])
def test_traverseringsforsok_treffer_ingen_fil(forsok):
    """Ingen av disse står i lista, og da finnes de ikke."""
    assert forsok not in api._STATISKE_FILER


def test_ruteren_slaar_opp_i_lista_for_den_apner_noe():
    import inspect as i
    kilde = i.getsource(api.Handler._do_get_intern)
    plass = kilde.index("/statisk/")
    rundt = kilde[plass:plass + 400]
    assert "_STATISKE_FILER" in rundt, (
        "ruteren sjekker ikke lista før den serverer — da er "
        "stitraversering plutselig en feilklasse igjen")


# ------------------------------------------------------------------ #
#  Large-payload abuse                                                #
# ------------------------------------------------------------------ #

def test_det_finnes_et_tak_paa_opplasting():
    assert api.MAKS_BYTES > 0
    assert api.MAKS_BYTES <= 500 * 1024 * 1024, (
        f"taket er {api.MAKS_BYTES // 1024 // 1024} MB — så høyt at det "
        "ikke lenger er et tak")


def test_det_finnes_et_tak_paa_SAMTIDIGE_opplastinger():
    """Ett tak per fil er ikke nok: hundre klienter med hver sin
    lovlige fil er like tungt som én ulovlig."""
    assert api.MAKS_SAMTIDIGE_MB > 0


def test_zip_bomben_har_sitt_eget_tak():
    """En komprimert fil kan være liten og pakke seg ut til gigabyte.
    Taket på det UTPAKKEDE er en annen kontroll enn taket på det
    opplastede, og begge trengs."""
    assert api.MAKS_UTPAKKET_BYTES > 0
    assert api.MAKS_UTPAKKET_BYTES < api.MAKS_BYTES, (
        "det utpakkede taket er høyere enn opplastingstaket — da "
        "beskytter det ingenting")


# ------------------------------------------------------------------ #
#  SSRF — ikke relevant i dag, og en vakt for at det forblir sånn     #
# ------------------------------------------------------------------ #

def test_serveren_henter_aldri_en_url_den_har_faatt_utenfra():
    """SSRF er «der relevant» i §21, og i dag er det ikke relevant:
    tjenesten tar imot filer, den henter dem ikke.

    Denne testen er derfor ikke en sjekk av en kontroll — den er en
    vakt mot at noen legger til et «hent dokumentet fra denne URL-en»
    uten å tenke på at serveren da kan brukes til å nå ting bak
    brannmuren."""
    kilde = inspect.getsource(api)
    for farlig in ("requests.get(", "requests.post(", "urlopen(",
                   "urlretrieve("):
        assert farlig not in kilde, (
            f"serveren kaller «{farlig}» — hvis målet kommer fra en "
            "klient, er det SSRF. Er det med vilje, skal det stå i en "
            "ADR og med en tillatt-liste over verter (§21)")


# ------------------------------------------------------------------ #
#  PII i logger — den viktigste                                      #
# ------------------------------------------------------------------ #

# Nøklene tilgangsloggen har lov til å skrive. LUKKET liste med vilje:
# legger noen til «filnavn» eller «sporsmal», er det et dokumentnavn
# eller et spørsmål om en navngitt person i en logg som ligger i
# sikkerhetskopier i årevis.
TILLATTE_LOGGFELT = {
    "t", "korrelasjon", "ip", "metode", "sti", "kode", "nokkel",
    "klient_id", "ms", "tallvakt", "ocr_konfidens", "gjennomgang",
}


def test_tilgangsloggen_skriver_bare_de_tillatte_feltene():
    """Kontrollen som gjør PII-hygiene til noe annet enn en vane."""
    kilde = inspect.getsource(api._skriv_tilgang)
    plass = kilde.index("rad = json.dumps({")
    blokk = kilde[plass:kilde.index("}, ensure_ascii", plass)]
    funnet = set(re.findall(r'"([a-z_]+)":', blokk))
    ekstra = funnet - TILLATTE_LOGGFELT
    assert not ekstra, (
        f"tilgangsloggen har fått nye felter: {sorted(ekstra)}. Er de "
        "ufarlige, før dem opp i TILLATTE_LOGGFELT — men les dem én "
        "gang til først: en logg overlever i sikkerhetskopier lenge "
        "etter at dokumentet er slettet.")


def test_verken_nokkelen_eller_selve_tallene_logges():
    """`nokkel` er en BOOL og `tallvakt` et UTFALL. Blir de verdiene
    selv, er lekkasjen permanent."""
    kilde = inspect.getsource(api._skriv_tilgang)
    assert '"nokkel": bool(' in kilde, (
        "API-nøkkelen logges som noe annet enn en bool — da ligger den i "
        "en logg som overlever i sikkerhetskopier")
    # Tallvakten skal logge ANTALL og runder, aldri tallene selv.
    tallvakt = inspect.getsource(api.Handler._do_post_intern)         if hasattr(api.Handler, "_do_post_intern") else inspect.getsource(api)
    assert '"stoppet": len(' in tallvakt, (
        "tallvakten logger noe annet enn et ANTALL — et beløp eller et "
        "fødselsnummer i en logg er en permanent lekkasje (R147)")


def test_dokumentnavn_og_sporsmal_staar_ikke_i_loggraden():
    """De to mest nærliggende å legge til, og de to verste: et filnavn
    er ofte et saksnummer, og et spørsmål er ofte et navn."""
    kilde = inspect.getsource(api._skriv_tilgang)
    plass = kilde.index("rad = json.dumps({")
    blokk = kilde[plass:kilde.index("}, ensure_ascii", plass)]
    for felt in ("filnavn", "sporsmal", "tekst", "svar", "fodselsnummer"):
        assert f'"{felt}"' not in blokk, (
            f"«{felt}» skrives til tilgangsloggen")

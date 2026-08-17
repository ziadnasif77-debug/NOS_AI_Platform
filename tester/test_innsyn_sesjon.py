"""
/innsyn som en kortlivet ØKT, med kontrollert utløp (§15.1, R209).

§15.1 beskriver /innsyn presist: «en kortlivet visningssesjon og ikke en
persistent Job. Standard TTL er 30 minutter. […] Hvis noden faller, kan
sesjonen utløpe og klienten får en kontrollert
session-expired/worker-unavailable respons; jobb- og result-data hentes
separat. /innsyn metadata skal ha correlation til jobb/principal.
Eventuelle midlertidige sidebilder slettes automatisk etter TTL.»

Tre av kravene var alt på plass, og det er verdt å si: TTL på nøyaktig
1800 sekunder, eierkontroll per økt, og sidebilder som ligger i økta —
altså borte i samme øyeblikk som den.

To manglet:

1. UTLØP SÅ UT SOM «FINNES IKKE». En utløpt økt ga `404 Ukjent
   innsyn_id` — samme svar som en id som aldri har eksistert, og samme
   som en annens økt. Klienten kunne ikke skille «du kom for sent» fra
   «du tok feil id», og §15.1 ber uttrykkelig om det første.

2. KORRELASJON DEKKET BARE HALVPARTEN. `eier` ga principal; ingenting
   knyttet økta til dokumentet den viste.

KONFLIKTEN SOM GJORDE (1) VANSKELIG
R153 krever at en FREMMED får 404 — ikke 403 — så han ikke kan bekrefte
at id-en finnes. Når økta er slettet, vet vi ikke lenger hvem den
tilhørte, og da må alle få samme svar. Gravsteinen løser det: tre felt
(id, eier, utløpstidspunkt), ingen dokumentdata. Eieren får «utløpt»,
alle andre får fortsatt 404.
"""
import sys
import time

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api as api


@pytest.fixture(autouse=True)
def tom_tilstand():
    api._innsyn_okter.clear()
    api._innsyn_gravsteiner.clear()
    yield
    api._innsyn_okter.clear()
    api._innsyn_gravsteiner.clear()


# ------------------------------------------------------------------ #
#  TTL-en §15.1 navngir                                               #
# ------------------------------------------------------------------ #

def test_levetiden_er_30_minutter():
    """§15.1: «Standard TTL er 30 minutter»."""
    assert api.INNSYN_LEVETID_S == 1800


def test_utlopt_okt_ryddes_bort():
    api._innsyn_okter["a1"] = {"status": "ferdig", "hendelser": [],
                               "resultat": {"tekst": "hemmelig"},
                               "start": time.time() - api.INNSYN_LEVETID_S - 1,
                               "eier": "kari"}
    api._rydd_innsyn()
    assert "a1" not in api._innsyn_okter


def test_sidebildene_forsvinner_med_okta():
    """§15.1: «Eventuelle midlertidige sidebilder slettes automatisk
    etter TTL». De ligger I økta, så det skjer av seg selv — men da må
    ingenting bære dem videre."""
    api._innsyn_okter["a1"] = {
        "status": "ferdig", "hendelser": [{"bilde_b64": "AAAA" * 1000}],
        "resultat": None, "start": time.time() - api.INNSYN_LEVETID_S - 1,
        "eier": "kari"}
    api._rydd_innsyn()
    rester = str(api._innsyn_gravsteiner)
    assert "AAAA" not in rester, (
        "sidebildedata overlevde i gravsteinen — den skal bære tre felt, "
        "ikke en kopi")


# ------------------------------------------------------------------ #
#  Gravsteinen: kontrollert utløp UTEN å lekke                        #
# ------------------------------------------------------------------ #

def test_gravsteinen_baerer_bare_tre_felt():
    api._innsyn_okter["a1"] = {
        "status": "ferdig", "hendelser": [], "resultat": {"tekst": "x"},
        "start": time.time() - api.INNSYN_LEVETID_S - 1, "eier": "kari",
        "dokument_id": "abc123", "filnavn": "vedtak.pdf"}
    api._rydd_innsyn()
    g = api._innsyn_gravsteiner["a1"]
    assert set(g) == {"eier", "utlopt", "grunn"}, (
        f"gravsteinen bærer {sorted(g)} — §15.1 sier at data ikke skal "
        "bli liggende, og hvert ekstra felt er et skritt mot en kopi")
    assert g["eier"] == "kari"


def test_fortrengt_okt_gravlegges_ogsaa():
    """Antallsgrensen kaster ut den eldste. Også DEN eieren fortjener
    et svar som sier hva som skjedde."""
    naa = time.time()
    for i in range(api.INNSYN_MAKS_OKTER + 2):
        api._innsyn_okter[f"o{i}"] = {"status": "ferdig", "hendelser": [],
                                      "resultat": None, "start": naa,
                                      "eier": "kari"}
    api._rydd_innsyn()
    assert len(api._innsyn_okter) <= api.INNSYN_MAKS_OKTER
    assert api._innsyn_gravsteiner, "fortrengte økter ble ikke gravlagt"
    assert any(g["grunn"] == "fortrengt"
               for g in api._innsyn_gravsteiner.values())


def test_gravsteiner_utloper_de_ogsaa():
    """Ellers vokser de til de er et register over alt som har vært."""
    api._innsyn_gravsteiner["gammel"] = {
        "eier": "kari", "grunn": "utlopt",
        "utlopt": time.time() - api.INNSYN_GRAVSTEIN_S - 1}
    api._rydd_innsyn()
    assert "gammel" not in api._innsyn_gravsteiner


def test_antallet_gravsteiner_har_tak():
    naa = time.time()
    for i in range(api.INNSYN_MAKS_GRAVSTEINER + 25):
        api._innsyn_gravsteiner[f"g{i}"] = {"eier": "k", "utlopt": naa,
                                            "grunn": "utlopt"}
    api._rydd_innsyn()
    assert len(api._innsyn_gravsteiner) <= api.INNSYN_MAKS_GRAVSTEINER


# ------------------------------------------------------------------ #
#  Svarveien: eieren får vite, den fremmede får ikke                  #
# ------------------------------------------------------------------ #

def test_utlop_og_fremmed_behandles_ULIKT_i_koden():
    """Kjernen i R209. Uten skillet er de to kravene — «si fra ved
    utløp» (§15.1) og «ikke bekreft at id-en finnes» (R153) — umulige
    samtidig."""
    import inspect
    kilde = inspect.getsource(api.Handler._do_get_intern)
    assert "session_expired" in kilde, "ingen kontrollert utløpsrespons"
    assert 'gravstein.get("eier") == meg' in kilde, (
        "utløpsresponsen sjekker ikke eierskap — da lekker den at en "
        "fremmed id har eksistert (R153)")
    assert '"Ukjent innsyn_id"' in kilde, (
        "404-svaret for fremmede er borte")


def test_utlopssvaret_forteller_hvor_dataene_er():
    """§15.1: «jobb- og result-data hentes separat». En feilmelding som
    bare sier «utløpt» lar klienten stå like fast."""
    import inspect
    kilde = inspect.getsource(api.Handler._do_get_intern)
    plass = kilde.index("session_expired")
    tekst = kilde[plass:plass + 1200]
    assert "/jobb/" in tekst, (
        "utløpsmeldingen sier ikke hvor resultatet kan hentes i stedet")


# ------------------------------------------------------------------ #
#  Korrelasjon til jobb/principal                                     #
# ------------------------------------------------------------------ #

def test_okta_korrelerer_til_bade_principal_og_dokument():
    """§15.1: «/innsyn metadata skal ha correlation til
    jobb/principal». `eier` dekket principal; `dokument_id` mangler."""
    import inspect
    kilde = inspect.getsource(api.Handler._innsyn)
    assert '"eier"' in kilde
    assert '"dokument_id"' in kilde, (
        "økta knyttes ikke til dokumentet den viste")


def test_dokument_id_er_en_hash_ikke_innholdet():
    """En korrelasjonsnøkkel skal ikke være noe å lekke."""
    import inspect
    kilde = inspect.getsource(api.Handler._innsyn)
    assert "hashlib.sha256(innhold)" in kilde


def test_klienten_ser_hvor_lenge_okta_lever():
    """Levetiden skal være synlig, ikke noe man oppdager ved å bomme."""
    import inspect
    kilde = inspect.getsource(api.Handler._do_get_intern)
    assert "utloper_om_sekunder" in kilde

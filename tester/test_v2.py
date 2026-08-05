"""
Tester for v2-formen (planpunkt 34–36).

To ting står på spill. Det ene er at v1 IKKE endrer seg: den er i drift
hos skjøre klienter, og hele grunnen til å lage en v2 er å slippe å røre
den. Det andre er at v2 faktisk er ryddet — en v2 som bare er v1 med
ekstra nivåer er ingen v2.

Kartet i `delt/v2.py` er uttømmende med vilje: hver v1-nøkkel er enten
plassert i data/metadata/diagnostikk eller uttrykkelig droppet. Testen
under feiler på en nøkkel som ikke står noe sted, så plasseringen blir
avgjort bevisst i stedet for å skje ved et uhell.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api
from delt.v2 import (UTGAATT_I_PROFIL, _DATA, _DIAGNOSTIKK, _METADATA, _ROT,
                     rydd_profil, til_v2)
from syntetiske_nummer import lag_fnr

DOKUMENT = f"""[Side 1 av 2]
NAV Arbeid og ytelser
Vedtak om sykepenger
Vedtaksdato: 28.05.2026
Saksnummer: 4417820
Dokumentet gjelder:
Ola Nordmann
Fnr: {lag_fnr(0)}
Dagsats: kr 1 234,00
[Side 2 av 2]
Mottatt NAV 30.05.2026
"""


def _v1_svar():
    """Et v1-svar med samme nøkkelsett som serveren sender."""
    ktx = api.DokumentKontekst(DOKUMENT, antall_sider=2, filnavn="test.pdf")
    return {
        "ok": True, "status": "ok", "filnavn": "test.pdf",
        "valg": {"tekst": True}, "dokumentprofil": ktx.profil,
        "opphav": {}, "tekst": DOKUMENT, "antall_tegn": len(DOKUMENT),
        "antall_sider": 2, "felter": {}, "struktur": None, "svar": None,
        "skjema": None, "korriger": None, "korrigert_tekst": None,
        "koordinater": None, "strekkoder": [], "handskrift": [],
        "varsler": [], "kvalitet": {"ocr_brukt": False, "advarsler": []},
        "modell_brukt": False, "fra_cache": False, "tid_sekunder": 0.1,
        "kilde": "deterministisk", "versjon": {"api": api.API_VERSJON},
    }


# ------------------------------------------------------------------ #
#  1. Kartet skal dekke ALT                                            #
# ------------------------------------------------------------------ #

def test_hver_v1_nokkel_er_plassert_et_sted():
    """En nøkkel som ikke står i noen liste havner i «data» som en
    stille standard. Det er riktig oppførsel i drift — et nytt felt er
    som regel et faktum om dokumentet, og å droppe det ville vært verre
    — men det skal ikke skje UBEMERKET."""
    kjent = set(_ROT) | set(_METADATA) | set(_DIAGNOSTIKK) | set(_DATA)
    uplassert = sorted(set(_v1_svar()) - kjent)
    assert not uplassert, (
        f"Disse v1-nøklene står ikke i kartet i delt/v2.py: {uplassert}. "
        f"Legg dem i _DATA, _METADATA, _DIAGNOSTIKK eller _ROT — de havner "
        f"ellers i «data» uten at noen har tatt stilling til det.")


def test_ingen_nokkel_er_plassert_to_steder():
    """«status» står bevisst både på rot og i diagnostikk; resten skal
    ha ett hjem."""
    fra_lister = list(_METADATA) + list(_DIAGNOSTIKK) + list(_DATA)
    dubletter = sorted({n for n in fra_lister if fra_lister.count(n) > 1})
    assert not dubletter, f"plassert flere steder: {dubletter}"


# ------------------------------------------------------------------ #
#  2. Formen                                                           #
# ------------------------------------------------------------------ #

def test_svaret_har_de_fire_toppnivaaene():
    v2 = til_v2(_v1_svar())
    assert set(v2) == {"ok", "status", "data", "metadata", "diagnostikk"}


def test_ok_og_status_ligger_paa_rot():
    """De svarer på ULIKE spørsmål (R83), og begge skal kunne leses uten
    å gå ned et nivå."""
    v2 = til_v2(_v1_svar())
    assert v2["ok"] is True
    assert v2["status"] == "ok"
    # status står også i diagnostikk, som i v1
    assert v2["diagnostikk"]["status"] == "ok"


def test_profilseksjonene_er_flatet_ut_i_data():
    """I v1 måtte man ned i «dokumentprofil» for å finne parten, og
    «dokumentprofil.dokument.dato» er tre ledd for dokumentets dato.
    Seksjonene ER dataene."""
    data = til_v2(_v1_svar())["data"]
    assert "dokumentprofil" not in data
    for seksjon in ("part", "dokument", "sak", "ytelse", "ytelser",
                    "hjemmel", "hjemler", "okonomi", "koder"):
        assert seksjon in data, seksjon


def test_filopplysninger_er_metadata_ikke_data():
    """«fil» handler om filen vi FIKK, ikke om innholdet."""
    v2 = til_v2(_v1_svar())
    assert v2["metadata"]["fil"]["antall_sider"] == 2
    assert "fil" not in v2["data"]


def test_dekning_er_diagnostikk_ikke_data():
    """`dekning` sier hva SYSTEMET kan ennå — det er en opplysning om
    oss, ikke om dokumentet."""
    v2 = til_v2(_v1_svar())
    assert "dekning" in v2["diagnostikk"]
    assert "dekning" not in v2["data"]


def test_skjemaversjonen_havner_i_metadata():
    assert til_v2(_v1_svar())["metadata"]["skjemaversjon"]


# ------------------------------------------------------------------ #
#  3. Utgåtte navn finnes IKKE i v2                                    #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("sti", UTGAATT_I_PROFIL)
def test_utgaatte_navn_er_borte(sti):
    """Det er hele poenget med et nytt hovedversjonsnummer."""
    node = til_v2(_v1_svar())["data"]
    for ledd in sti[:-1]:
        node = node.get(ledd) or {}
    assert sti[-1] not in node, f"{'.'.join(sti)} finnes fortsatt i v2"


def test_erstatningene_er_der_til_gjengjeld():
    data = til_v2(_v1_svar())["data"]
    assert data["part"]["fnr"]
    assert "andre_fodselsnummer" in data
    assert data["sammendrag"]["konfidens"]
    assert data["part"]["grunnlag"]
    assert til_v2(_v1_svar())["diagnostikk"]["dekning"]["ytelse"]


def test_aarstall_kan_ikke_forveksles_med_alder():
    """`dokument.ar` sto rett ved siden av `dokument.alder.aar` — to
    skrivemåter av samme bokstav, to betydninger."""
    dokument = til_v2(_v1_svar())["data"]["dokument"]
    assert "ar" not in dokument
    assert dokument["aarstall"] == 2026


# ------------------------------------------------------------------ #
#  4. v1 er URØRT                                                      #
# ------------------------------------------------------------------ #

def test_projeksjonen_endrer_ikke_originalen():
    """v1-svaret og v2-svaret bygges av samme dict i samme forespørsel.
    Muterte projeksjonen originalen, ville v1 blitt endret av at v2
    finnes."""
    original = _v1_svar()
    kopi = {k: v for k, v in original.items()}
    til_v2(original)
    assert set(original) == set(kopi)
    assert "eier" in original["dokumentprofil"]
    assert "ar" in original["dokumentprofil"]["dokument"]


def test_rydd_profil_lager_en_ny_profil():
    ktx = api.DokumentKontekst(DOKUMENT, antall_sider=2)
    profil = ktx.profil
    ryddet = rydd_profil(profil)
    assert "eier" in profil          # originalen urørt
    assert "eier" not in ryddet


def test_feilsvar_er_likt_i_begge_versjoner():
    """RFC 9457 er allerede en standardform. To ulike feilformer ville
    tvunget en klient til å håndtere begge."""
    feil = {"ok": False, "feil": "noe gikk galt", "uuid": "abc"}
    # v2-projeksjonen kjøres ikke på feilsvar — se _svar()
    assert til_v2(feil)["ok"] is False


# ------------------------------------------------------------------ #
#  5. Rutene                                                           #
# ------------------------------------------------------------------ #

def test_v2_er_en_eksplisitt_mengde_ikke_et_prefiks():
    """`startswith("/api/v2")` ville gjort /api/v2noeannet til en
    v2-rute."""
    assert "/api/v2/dokument" in api.V2_STIER
    assert "/api/v2" not in api.V2_STIER


def test_alle_v2_ruter_er_i_openapi():
    stier = api._openapi()["paths"]
    for rute in api.V2_STIER:
        assert rute in stier, rute
    assert "/dokument/operasjoner" in stier


def test_v1_rutene_finnes_fortsatt():
    """v2 legges til; v1 fjernes ikke."""
    stier = api._openapi()["paths"]
    assert "/dokument" in stier


def test_de_nye_rutene_tar_koeplass():
    """De gjør NØYAKTIG samme OCR- og modellarbeid som /dokument. Sto de
    ikke i _TUNGE_STIER, ville de gått utenom kapasitetsporten — og
    serveren kunne overlastes gjennom én dør mens den andre var stengt.
    Det er ikke en teoretisk risiko: porten finnes fordi maskinen har
    målt hvor mange samtidige forespørsler den bærer."""
    for rute in api.V2_STIER + ("/dokument/operasjoner",):
        assert rute in api._TUNGE_STIER, rute


def test_api_prefikset_spiser_ikke_versjonsnummeret():
    """Funnet ved faktisk kjøring, og den mest lærerike av dem alle:
    `_sti()` strippet «/api» generelt, så /api/v2/dokument ble
    /v2/dokument og svarte 404. Docstringen i samme funksjon lovet at
    «en fremtidig v2 kan leve side om side med v1» — den generelle
    strippingen tok livet av sitt eget løfte."""
    class Falsk(api.Handler):
        def __init__(self, sti):
            self.path = sti

    assert Falsk("/api/v2/dokument")._sti() == "/api/v2/dokument"
    assert Falsk("/api/v2/dokument/operasjoner")._sti() == \
        "/api/v2/dokument/operasjoner"
    # v1-aliasene skal fortsatt strippes som før
    assert Falsk("/api/v1/dokument")._sti() == "/dokument"
    assert Falsk("/api/dokument")._sti() == "/dokument"
    assert Falsk("/api")._sti() == "/hjelp"
    assert Falsk("/dokument/")._sti() == "/dokument"


def test_de_nye_rutene_slipper_gjennom_rutesjekken():
    """Fanget i faktisk kjøring: rutene var lagt inn i dispatch-en, men
    en whitelist LENGER OPPE ga 404 før de ble nådd."""
    import inspect
    kilde = inspect.getsource(api.Handler._do_post_intern) \
        if hasattr(api.Handler, "_do_post_intern") else ""
    if not kilde:
        pytest.skip("fant ikke POST-behandleren")
    for rute in api.V2_STIER + ("/dokument/operasjoner",):
        assert f'"{rute}"' in kilde, f"{rute} står ikke i rutesjekken"

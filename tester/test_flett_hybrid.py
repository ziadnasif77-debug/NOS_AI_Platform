"""
Hybrid malfletting (skjema_motor=auto): det HANDFASTE deterministisk,
RESTEN med modell — men modellen rører ALDRI et felt regelen alt har
bevist, og alt den finner går gjennom tallvakten.

Modellen mockes her (monkeypatch av fyll_skjema_kjerne), så testene er
raske og GPU-frie og prøver KOBLINGEN: hvilke felter havner hos modellen,
hva overstyres, og hva skjer når modellen er nede.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api
from dokument_api import flett_mal_hybrid


# Tekst med felter regelen KAN bevise: telefon (8 sifre), postnr+sted,
# ytelse (kanonisk ord). Personnavnet har INGEN fast form — bare modellen
# kan hente det.
DOK = (
    "HADSEL TRYGDEKONTOR\n"
    "Telefon 76118610\n"
    "8450 STOKMARKNES\n"
    "Gjelder barnetrygd for Terje Karlsen.\n"
)


@pytest.fixture
def mock_modell(monkeypatch):
    """Erstatter modellkallet med en deterministisk stub, så vi kan styre
    nøyaktig hva «modellen» svarer — og bekrefte HVILKEN delmal den fikk."""
    kall = {}

    def _stub(dok, mal):
        kall["mal"] = mal
        # Stubben later som den fant et navn for hvert felt den blir bedt om
        svar = {k: "Terje Karlsen" for k in mal}
        return {"ok": True, "skjema": svar, "avvik": []}

    monkeypatch.setattr(dokument_api, "fyll_skjema_kjerne", _stub)
    return kall


def test_deterministisk_uten_a_roere_modellen(mock_modell):
    """Alle felter finnes deterministisk → modellen skal IKKE kalles."""
    mal = {"tlf": "{telefon}", "sted": "{poststed}", "stonad": "{ytelse}"}
    res = flett_mal_hybrid(DOK, mal)
    assert res["modell_brukt"] is False
    assert "mal" not in mock_modell            # stubben ble aldri kalt
    assert res["skjema"]["tlf"] == "76118610"
    assert all(k == "deterministisk"
               for k in res["kilde_per_felt"].values())


def test_bare_manglende_felt_gaar_til_modellen(mock_modell):
    """«navn» har ingen regel → bare DET sendes til modellen, ikke de
    feltene regelen alt har bevist."""
    mal = {"tlf": "{telefon}", "kunde": "{navn}"}
    res = flett_mal_hybrid(DOK, mal)
    assert res["modell_brukt"] is True
    # modellen fikk KUN det manglende feltet
    assert list(mock_modell["mal"].keys()) == ["navn"]
    # telefon forble deterministisk, navn kom fra modellen
    assert res["kilde_per_felt"]["telefon"] == "deterministisk"
    assert res["kilde_per_felt"]["navn"] == "modell"
    assert res["skjema"] == {"tlf": "76118610", "kunde": "Terje Karlsen"}


def test_modellen_overstyrer_aldri_bevist_felt(mock_modell):
    """Selv om stubben ville svart på telefon, får den aldri sjansen —
    et deterministisk bevist felt sendes ikke til modellen."""
    mal = {"tlf": "{telefon}"}
    res = flett_mal_hybrid(DOK, mal)
    assert res["modell_brukt"] is False
    assert res["skjema"]["tlf"] == "76118610"


def test_faller_tilbake_til_deterministisk_uten_borealis():
    """Er modellen nede, skal det HANDFASTE fortsatt komme ut — og de
    manglende feltene rapporteres ærlig som ukjente, ikke gjettes."""
    mal = {"tlf": "{telefon}", "kunde": "{navn}"}
    res = flett_mal_hybrid(DOK, mal, borealis_klar=False)
    assert res["modell_brukt"] is False
    assert res["skjema"]["tlf"] == "76118610"
    assert res["skjema"]["kunde"] is None      # ikke funnet, ikke gjettet
    assert "navn" in res["ukjente_felter"]


def test_tom_modellverdi_gir_ukjent_ikke_falsk(monkeypatch):
    """Svarer modellen tomt på et felt, skal feltet forbli tomt/ukjent —
    ikke fylles med en tom streng som om noe ble funnet."""
    def _stub_tom(dok, mal):
        return {"ok": True, "skjema": {k: "" for k in mal}, "avvik": []}
    monkeypatch.setattr(dokument_api, "fyll_skjema_kjerne", _stub_tom)

    res = flett_mal_hybrid(DOK, {"kunde": "{navn}"})
    assert res["skjema"]["kunde"] is None
    assert "navn" in res["ukjente_felter"]
    assert res["kilde_per_felt"].get("navn") != "modell"


def test_avvik_fra_tallvakten_kommer_med(monkeypatch):
    """Tallvaktens avvik (fra rens_skjemasvar via fyll_skjema_kjerne) skal
    bæres videre til klienten, ikke svelges."""
    def _stub_avvik(dok, mal):
        return {"ok": True, "skjema": {k: "Terje Karlsen" for k in mal},
                "avvik": ["belop: ikke i dokumentet"]}
    monkeypatch.setattr(dokument_api, "fyll_skjema_kjerne", _stub_avvik)

    res = flett_mal_hybrid(DOK, {"kunde": "{navn}"})
    assert res["avvik"] == ["belop: ikke i dokumentet"]

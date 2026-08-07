"""
POST /spor har ÉN form — uansett hvilken vei som svarte.

Ruten hadde fire 200-veier med hvert sitt nøkkelsett. Målt: bare `ok` og
`svar` var med i alle; 22 av 24 nøkler kom og gikk.

    fil + spørsmål        18 nøkler
    fil uten spørsmål     17
    spørsmål uten fil      9
    tomt dokument          8   ← og UTEN «versjon»

Den siste er verst på to måter. R39 sier uttrykkelig at hvert
/spor-svar bærer `versjon` — den gjorde ikke det. Og en robot som leser
`svar["tall_verifisert"]` virket på hvert dokument med lesbar tekst og
krasjet på den første blanke siden i bunken, i produksjon.

Alle veier bygger nå svaret gjennom `_spor_svar`, som starter fra et
fast skjelett. Kalleren overstyrer bare det den vet.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api


# Formen kontrakten lover. Endres den, skal det være et VALG — derfor
# står settet her og ikke bare implisitt i koden.
FORVENTEDE_NOKLER = {
    "ok", "modus", "filnavn", "sporsmal", "svar", "melding",
    "uten_dokument", "trenger_ocr", "ocr_brukt", "ocr_motorer",
    "strekkoder", "handskrift", "korrigert_tekst", "tall_verifisert",
    # R147: hvilke tall vakten stoppet, og hvor mange modellrunder som
    # trengtes. `tall_verifisert` sa bare ja/nei, og resten sto som
    # PROSA i `advarsel` — en klient som ville telle hvor ofte vakten
    # slår til, måtte tolke en setning (R132).
    "uverifiserte_tall", "tallvakt_forsok",
    "tolket_sporsmal", "svar_avkortet", "advarsel", "fra_cache",
    "tid_sekunder", "kilde", "versjon",
}

MODI = {"uten_dokument", "fulltekst", "tomt_dokument", "dokumentsporsmal"}


def test_skjelettet_har_akkurat_de_lovede_noklene():
    assert set(api._spor_svar()) == FORVENTEDE_NOKLER


def test_tomt_kall_gir_alle_nokler_med_null():
    """Ingen nøkkel mangler bare fordi kalleren ikke visste noe."""
    svar = api._spor_svar()
    for nokkel in FORVENTEDE_NOKLER:
        assert nokkel in svar, nokkel


@pytest.mark.parametrize("modus", sorted(MODI))
def test_hver_vei_gir_samme_nokkelsett(modus):
    """Kjernen: formen står stille uansett hvilken vei som svarte."""
    assert set(api._spor_svar(modus=modus)) == FORVENTEDE_NOKLER


def test_versjon_er_alltid_med_og_alltid_komplett():
    """R39: hvert /spor-svar bærer `versjon`. To av de gamle veiene
    bygget den uten «modell», og én utelot den helt."""
    versjon = api._spor_svar()["versjon"]
    assert set(versjon) == {"api", "prompt", "modell"}
    assert versjon["api"]


def test_ukjent_felt_stoppes_i_stedet_for_aa_snike_seg_inn():
    """En skrivefeil i et kallsted ville ellers lagt til en nøkkel bare
    dén veien — nøyaktig feilen skjelettet finnes for å hindre."""
    with pytest.raises(KeyError):
        api._spor_svar(tall_verifiseret=True)      # skrivefeil med vilje


def test_kalleren_overstyrer_skjelettet():
    """Speilet — uten dette kunne skjelettet vært en tom skall som
    ignorerte alt kalleren sa."""
    svar = api._spor_svar(modus="fulltekst", svar="hei", tall_verifisert=True)
    assert svar["svar"] == "hei"
    assert svar["tall_verifisert"] is True
    assert svar["modus"] == "fulltekst"
    assert svar["ok"] is True


def test_alle_kallsteder_bruker_byggefunksjonen():
    """Fanger den neste veien noen legger til med sitt eget dict.

    Leser rutekoden og krever at hvert 200-svar på /spor-veien går
    gjennom `_spor_svar`. Et håndskrevet dict der ville gjenskapt
    nøyaktig problemet dette punktet lukket."""
    import inspect
    import re
    kilde = inspect.getsource(api.Handler._do_post_intern)
    # Klipp ut /spor-delen: fra der jobb_ref settes til slutten.
    start = kilde.index("jobb_ref = ")
    spor = kilde[start:]
    # Hvert «_svar(200, {» her er et håndskrevet dict utenom skjelettet.
    haandskrevne = re.findall(r"_svar\(200,\s*\{", spor)
    assert not haandskrevne, (
        f"{len(haandskrevne)} 200-svar på /spor-veien bygger sitt eget "
        f"dict i stedet for å bruke _spor_svar. Da kan nøkkelsettet "
        f"skille lag igjen.")
    assert "_spor_svar(" in spor, "fant ingen kall til byggefunksjonen"


def test_modusverdiene_er_de_dokumenterte():
    """`modus` finnes for at klienten ikke skal måtte gjette veien ut
    fra hvilke felt som er fylt. Da må verdirommet være lukket."""
    import inspect
    import re
    kilde = inspect.getsource(api.Handler._do_post_intern)
    brukt = set(re.findall(r'modus="([a-z_]+)"', kilde))
    assert brukt, "ingen modus satt i rutekoden"
    assert brukt <= MODI, f"udokumentert modus: {sorted(brukt - MODI)}"

"""
Kanonisk livssyklus (R198) og frosset OCR-policy (R199).

Begge er krav fra implementeringsspesifikasjonen (§6.1, §26, §27.1,
§30). Det som gjorde dem verdt å rette først, var at avviket allerede
var synlig i kontrakten: OpenAPI erklærte «ko»/«arbeider» mens svaret
inneholdt «kø»/«pågår» — verdier med æøå, som §26 uttrykkelig forbyr i
maskinlesbare enum-verdier.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

from delt import tilstander


# ------------------------------------------------------------------ #
#  Den offentlige livssyklusen er den §6.1 krever                     #
# ------------------------------------------------------------------ #

def test_livssyklusen_er_den_spesifikasjonen_krever():
    assert list(tilstander.OFFENTLIGE) == [
        "i_ko", "sender", "kjorer", "sammenstiller",
        "ferdig", "delvis", "feil", "avbrutt"]


def test_ingen_offentlig_verdi_har_aeoeaa():
    """§26: ingen maskinlesbar enum-verdi inneholder æ, ø eller å. En
    klient som forgrener på en statuskode skal ikke måtte håndtere
    tegnsett for å lese den."""
    for verdi in tilstander.OFFENTLIGE:
        assert not (set("æøåÆØÅ") & set(verdi)), verdi


def test_openapi_enum_hentes_ikke_skrives():
    """Skrevet for hånd sto det «ko» og «arbeider» i spesifikasjonen
    mens svaret inneholdt «kø» og «pågår»."""
    import dokument_api as api
    spek = api._openapi()
    for sti in ("/jobb", "/jobb/{jobb_id}"):
        for _metode, op in (spek["paths"].get(sti) or {}).items():
            svar = ((op.get("responses") or {}).get("200") or {})
            skjema = (((svar.get("content") or {}).get("application/json")
                       or {}).get("schema") or {})
            status = (skjema.get("properties") or {}).get("status")
            if status and "enum" in status:
                assert status["enum"] == list(tilstander.OFFENTLIGE), (
                    f"{sti} erklærer en annen enum enn state machine")


# ------------------------------------------------------------------ #
#  Adapteren: interne navn slipper aldri ut                           #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("intern,offentlig", [
    ("kø", "i_ko"), ("ko", "i_ko"),
    ("pågår", "kjorer"), ("arbeider", "kjorer"),
    ("sender", "sender"), ("sammenstiller", "sammenstiller"),
    ("ferdig", "ferdig"), ("delvis", "delvis"),
    ("feil", "feil"), ("avbrutt", "avbrutt"),
    ("avbrytes", "kjorer"),
])
def test_interne_tilstander_mappes(intern, offentlig):
    assert tilstander.offentlig(intern) == offentlig


def test_ukjent_tilstand_lekker_ikke_ut_som_seg_selv():
    """En tilstand ingen har definert skal ikke kunne dukke opp i
    kontrakten som om den var gyldig."""
    assert tilstander.offentlig("noe_helt_nytt") == "feil"
    assert tilstander.offentlig(None) == "feil"
    assert tilstander.offentlig("") == "feil"


def test_gamle_lagrede_jobber_mappes_ogsaa():
    """Jobber som lå på disk fra før bruker de gamle navnene. De skal
    ikke bli «feil» ved en omstart."""
    for gammel in ("kø", "pågår"):
        assert tilstander.offentlig(gammel) in tilstander.OFFENTLIGE
        assert tilstander.offentlig(gammel) != "feil"


# ------------------------------------------------------------------ #
#  Overganger — maskinen skal beskrive systemet, ikke pynte på det    #
# ------------------------------------------------------------------ #

def test_terminale_tilstander_er_endelige():
    """Den konkrete faren: en arbeidstråd rekker en siste oppdatering
    og gjør en AVBRUTT jobb «ferdig» — klienten får et resultat den
    uttrykkelig avbestilte."""
    for terminal in ("ferdig", "delvis", "feil", "avbrutt"):
        for maal in ("kjorer", "ferdig", "sammenstiller"):
            if maal == terminal:
                continue
            assert not tilstander.kan_gaa_til(terminal, maal), (
                f"{terminal} → {maal} skal være ulovlig")


def test_jobb_kan_ikke_hoppe_fra_ko_til_ferdig():
    """En jobb som går rett fra kø til ferdig har ikke lest noe."""
    assert not tilstander.kan_gaa_til("kø", "ferdig")


def test_den_normale_veien_er_lovlig():
    vei = ["kø", "sender", "pågår", "sammenstiller", "ferdig"]
    for fra, til in zip(vei, vei[1:]):
        assert tilstander.kan_gaa_til(fra, til), f"{fra} → {til}"


def test_avbrudd_er_lovlig_underveis():
    for fra in ("kø", "sender", "pågår", "sammenstiller"):
        assert tilstander.kan_gaa_til(fra, "avbrutt")


def test_samme_tilstand_er_alltid_lovlig():
    assert tilstander.kan_gaa_til("pågår", "pågår")


def test_serveren_avviser_en_ulovlig_overgang():
    """Vakten skal virke i praksis, ikke bare i modulen."""
    import dokument_api as api
    jobb = {"jobb_id": "test", "status": "avbrutt", "versjon": 3}
    api._jobb_status(jobb, "ferdig")
    assert jobb["status"] == "avbrutt", (
        "en avbrutt jobb ble «ferdig» — overgangskontrollen virker ikke")
    assert jobb["versjon"] == 3, "versjonen ble løftet av en avvist overgang"


def test_status_settes_kun_gjennom_vakten():
    """Setter noen status direkte med jobb.update(), går de UTENOM
    overgangskontrollen — og da er kontrollen bare et løfte."""
    import inspect
    import re
    import dokument_api as api
    kilde = inspect.getsource(api._jobb_arbeider)
    treff = re.findall(r"jobb\.update\([^)]*status\s*=", kilde, re.S)
    assert not treff, (
        "arbeidstråden setter status direkte i jobb.update() og omgår "
        f"dermed _jobb_status: {treff}")


# ------------------------------------------------------------------ #
#  OCR-policy frosset ved jobbstart (R199, §27.1)                     #
# ------------------------------------------------------------------ #

def test_policyen_har_det_som_paavirker_resultatet():
    from delt import region_ocr
    p = region_ocr.los_policy()
    for felt in ("motor", "enhet", "maks_norhand_per_side",
                 "maks_norhand_sekunder"):
        assert felt in p, f"policyen mangler «{felt}»"


def test_policyen_er_den_samme_to_ganger_paa_rad():
    """R6: to jobber på samme maskin skal få samme policy."""
    from delt import region_ocr
    assert region_ocr.los_policy() == region_ocr.los_policy()


def test_avvik_meldes_men_motoren_byttes_ikke():
    """Kjernen i §27.1: kan policyen ikke innfris, SIER vi fra. Vi
    bytter aldri motor midt i en jobb — da ville side 1 og side 50
    vært lest av ulike modeller, og samme dokument gitt ulikt svar
    avhengig av timing."""
    from delt import region_ocr
    holder, avvik = region_ocr.policy_holder({"motor": "en_motor_som_ikke_finnes"})
    assert holder is False
    assert avvik and "frosne" in avvik


def test_ingen_policy_er_ikke_et_avvik():
    from delt import region_ocr
    assert region_ocr.policy_holder(None) == (True, None)


def test_jobben_registrerer_policyen():
    """§27.1: «registrert i jobbmetadata». Uten det kan et resultat
    ikke spores til lesemåten som produserte det."""
    import inspect
    import dokument_api as api
    kilde = inspect.getsource(api._jobb_arbeider)
    assert 'jobb["ocr_policy"]' in kilde
    assert "los_policy()" in kilde


# ------------------------------------------------------------------ #
#  Stor bunke: ingen stille avkorting (§30)                           #
# ------------------------------------------------------------------ #

def test_jobbveien_har_ingen_skjult_sidegrense():
    """§30 krever at 500-siders scanned path fullfører med FULL
    dekning «uten stille truncation». De synkrone grensene
    (OCR_MAKS_SIDER / OCR_TAK_SIDER) gjelder /dokument — kryper en av
    dem inn i jobbarbeideren, ville en 500-siders bunke stoppet på 50
    og meldt «ferdig»."""
    import inspect
    import dokument_api as api
    kilde = inspect.getsource(api._jobb_arbeider)
    for grense in ("OCR_MAKS_SIDER", "OCR_TAK_SIDER"):
        assert grense not in kilde, (
            f"{grense} brukes i jobbarbeideren — da har /jobb en skjult "
            "sidegrense, og «ubegrenset» i dokumentasjonen er en løgn")


def test_generatoren_lager_bunke_uten_tekstlag():
    """En stor bunke MED tekstlag ville hoppet forbi OCR helt, og
    målingen ville målt noe annet enn den utgir seg for."""
    import inspect
    import lag_stor_bunke
    kilde = inspect.getsource(lag_stor_bunke)
    assert "show_pdf_page" in kilde, (
        "sidene må settes inn som referanse til det SKANNEDE bildet — "
        "ellers får bunken tekstlag og OCR kjører aldri")

"""
Bevisvalg (R195): gi modellen sidene spørsmålet gjelder, ikke hele
bunken.

Den viktigste testen her er ikke at seleksjonen treffer — det er at den
ALDRI gir modellen et tomt eller vilkårlig grunnlag. En seleksjon som
tar feil koster ett galt svar; en seleksjon som stille fjerner
konteksten et riktig svar trengte, koster tillit til alle svarene.
"""
import sys

sys.path.insert(0, ".")

import pytest

from delt import bevisvalg


BUNKE = {
    1: "Vedtak om sykepenger. Dato: 12.05.2026. Saksnummer: 4417820. "
       "Vi har innvilget soknaden din om sykepenger.",
    2: "Vedlegg 1 - Beregning av sykepenger. Dagsats 1 970. SUM 254 130.",
    3: "Krav om tilbakebetaling - faktura. Beloep aa betale kr 4 812,00. "
       "Forfallsdato 24.06.2026. KID-nummer 1002345678911.",
    9: "Klage paa vedtak om arbeidsavklaringspengar. Fraa Marit Testperson. "
       "Sakstilvising: 5590114. Eg klagar paa vedtaket datert 08.05.2026.",
    10: "Returslipp - dokumentkontroll. Mottakseining: NAV Skanning Hamar. "
        "Talet paa sider: 10.",
}


# ------------------------------------------------------------------ #
#  Treffer den de sidene den skal?                                    #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("sporsmal,forventet_side", [
    ("Hva er sakstilvisinga i klagen?", 9),
    ("Hvilken mottakenhet staar paa returslippen?", 10),
    ("Hva er forfallsdatoen paa fakturaen?", 3),
    ("Hva er dagsatsen i beregningen?", 2),
])
def test_riktig_side_velges(sporsmal, forventet_side):
    """De fire som feilet i Phase 0-baselinen hadde ETT mønster:
    spørsmål om side 9–10 ble besvart fra side 1–3."""
    dom = bevisvalg.velg_sider(BUNKE, sporsmal)
    assert forventet_side in dom["valgte"], (
        f"«{sporsmal}» valgte {dom['valgte']}, ikke side {forventet_side}. "
        f"Poeng: {dom['poeng']}")


def test_utelatte_sider_navngis():
    """Ingenting skal forsvinne i stillhet (R65-prinsippet)."""
    dom = bevisvalg.velg_sider(BUNKE, "Hva er sakstilvisinga i klagen?")
    assert dom["utelatte"], "ingen sider markert som utelatt"
    assert set(dom["valgte"]) & set(dom["utelatte"]) == set()
    assert set(dom["valgte"]) | set(dom["utelatte"]) == set(BUNKE)


# ------------------------------------------------------------------ #
#  Aldri et tomt eller vilkårlig grunnlag                             #
# ------------------------------------------------------------------ #

def test_ingen_treff_gir_HELE_dokumentet():
    """Treffer ingenting, er hele dokumentet det ærligste grunnlaget.
    En seleksjon som gir modellen ingenting å svare på, er verre enn
    ingen seleksjon."""
    dom = bevisvalg.velg_sider(BUNKE, "Hva er blodtypen til hunden?")
    assert dom["alle"] is True
    assert dom["valgte"] == []


def test_spoersmaal_uten_noekkelord_gir_hele_dokumentet():
    dom = bevisvalg.velg_sider(BUNKE, "Hva er det?")
    assert dom["alle"] is True


def test_alle_sider_like_relevante_gir_hele_dokumentet():
    """Skiller ingen side seg ut, ville det å plukke tre av dem vært
    vilkårlig — og vilkårlig innsnevring er verre enn ingen."""
    like = {1: "sykepenger vedtak", 2: "sykepenger vedtak",
            3: "sykepenger vedtak"}
    dom = bevisvalg.velg_sider(like, "Hva sier vedtaket om sykepenger?")
    assert dom["alle"] is True


def test_tomt_dokument_er_trygt():
    assert bevisvalg.velg_sider({}, "Hva som helst?")["alle"] is True


def test_taket_holdes():
    dom = bevisvalg.velg_sider(BUNKE, "sykepenger vedtak klage faktura "
                                      "returslipp beregning", maks_sider=2)
    assert len(dom["valgte"]) <= 2


# ------------------------------------------------------------------ #
#  Determinisme (R6) — samme spørsmål, samme sider, hver gang         #
# ------------------------------------------------------------------ #

def test_samme_spoersmaal_gir_samme_sider():
    a = bevisvalg.velg_sider(BUNKE, "Hva er forfallsdatoen paa fakturaen?")
    b = bevisvalg.velg_sider(BUNKE, "Hva er forfallsdatoen paa fakturaen?")
    assert a == b


def test_poengsettingen_er_ren():
    """Ingen modell, ingen tilfeldighet — bare tekst inn, tall ut."""
    p1 = bevisvalg.poeng_for_side(BUNKE[3], {"forfallsdato"}, "forfallsdato?")
    p2 = bevisvalg.poeng_for_side(BUNKE[3], {"forfallsdato"}, "forfallsdato?")
    assert p1 == p2 and p1 > 0


# ------------------------------------------------------------------ #
#  Teksten modellen faktisk får                                       #
# ------------------------------------------------------------------ #

def test_sidemarkorene_beholdes():
    """Uten markørene mister modellen den ENE opplysningen som lar den
    skille dokumentene i bunken — altså nettopp forvekslingen vi
    prøver å fjerne."""
    tekst = bevisvalg.bygg_utvalgstekst(BUNKE, [9], 10)
    assert "[Side 9 av 10]" in tekst
    assert "Sakstilvising" in tekst
    assert "Vedtak om sykepenger" not in tekst


def test_flere_sider_kommer_i_rekkefolge():
    tekst = bevisvalg.bygg_utvalgstekst(BUNKE, [3, 9], 10)
    assert tekst.index("[Side 3") < tekst.index("[Side 9")


# ------------------------------------------------------------------ #
#  Serverbryteren                                                     #
# ------------------------------------------------------------------ #

def test_bevisvalg_er_paa_fordi_maalingen_baerer_det():
    """R196: PÅ som standard — men bare fordi korpuset dømte.

    På 46 spørsmål så tiltaket ut som «ikke skillbar». På 133 rettet det
    27 spørsmål og ødela 7 (McNemar p = 0,0008), og ble raskere. Det var
    korpuset som var for lite, ikke tiltaket som var for svakt."""
    sys.path.insert(0, "skript")
    import dokument_api as api
    assert api.BEVISVALG is True
    assert api.BEVISVALG_MAKS_SIDER == 5, (
        "fem sider er den MÅLTE verdien (109/133 mot 103/133 med tre) — "
        "endres den, skal korpuset kjøres på nytt")

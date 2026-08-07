"""Betyr konfidensen noe? — kalibrering av terskelen på 0.85.

Serveren sender et dokument til menneskelig gjennomgang når
OCR-konfidensen er UNDER 0.85. Det forutsetter stilltiende at tallet
betyr noe: at «0.9» faktisk er riktigere enn «0.7». Ingen har målt det,
og en terskel ingen har målt er en gjetning som har fått status som
regel.

HULLET SOM GJORDE MÅLINGEN UMULIG
Bare dokumenter UNDER terskelen fikk en menneskelig fasit. Da kan de
øverste bøttene i kalibreringstabellen — nettopp de som avgjør om
terskelen er riktig — ALDRI fylles. Målingen ville bekreftet seg selv:
vi måler bare der vi allerede visste at det var dårlig, og
treningsløkken lærer av feilene systemet visste om, aldri av dem det
gjorde med selvtillit.

`skal_kalibreringsproeve` lukker det: en liten andel av de GODT LESTE
sendes også til gjennomgang, merket som prøve — ikke som «lest dårlig».
AV som standard, fordi det koster menneskelig tid og skal være et valg.
"""
import os
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))

from delt import kalibrering as kal


# ------------------------------------------------------------------ #
#  1. Tabellen                                                         #
# ------------------------------------------------------------------ #

def test_overmodighet_vises_som_NEGATIVT_avvik():
    """Systemet lover 0.95 og holder 0.70. Det er den farlige
    retningen: dårlige dokumenter slipper gjennom uten å bli sett."""
    par = [(0.95, True)] * 7 + [(0.95, False)] * 3
    rad = kal.kalibreringstabell(par)[0]
    assert rad["botte"] == "0.9–1.0"
    assert rad["oppgitt"] == pytest.approx(0.95)
    assert rad["faktisk"] == pytest.approx(0.70)
    assert rad["avvik"] == pytest.approx(-0.25)


def test_forsiktighet_vises_som_POSITIVT_avvik():
    """Motsatt vei koster tid, ikke riktighet — men skal likevel synes."""
    par = [(0.75, True)] * 9 + [(0.75, False)]
    rad = kal.kalibreringstabell(par)[0]
    assert rad["avvik"] > 0


def test_en_perfekt_kalibrert_modell_gir_avvik_null():
    par = [(0.90, True)] * 9 + [(0.90, False)]
    assert kal.kalibreringstabell(par)[0]["avvik"] == pytest.approx(0.0)


def test_tomme_botter_utelates_i_stedet_for_aa_tegnes_som_null():
    """En bøtte uten observasjoner er ikke «0 % riktig», den er fravær
    av data — samme skille som presisjon `null` på et ubesvart felt
    (R146). Tegnet som null ville en umålt bøtte sett ut som vår verste."""
    tabell = kal.kalibreringstabell([(0.95, True), (0.95, False)])
    assert len(tabell) == 1
    assert tabell[0]["botte"] == "0.9–1.0"


def test_konfidens_1_havner_i_oeverste_botte():
    """Grensetilfellet: 1.0 skal ikke falle utenfor alle bøttene."""
    tabell = kal.kalibreringstabell([(1.0, True)])
    assert tabell and tabell[0]["botte"] == "0.9–1.0"


# ------------------------------------------------------------------ #
#  2. ECE — ett tall for hele bildet                                   #
# ------------------------------------------------------------------ #

def test_ece_er_null_naar_alt_stemmer():
    par = [(0.90, True)] * 9 + [(0.90, False)]
    assert kal.ece(par) == pytest.approx(0.0, abs=0.001)


def test_ece_vektes_etter_boettestoerrelse():
    """En bøtte med tre dokumenter skal ikke veie like mye som en med
    tre hundre — ellers avgjør støy hele tallet."""
    stor = [(0.90, True)] * 90 + [(0.90, False)] * 10     # perfekt
    liten = [(0.50, True)]                                # 0.5 lovet, 1.0 holdt
    assert kal.ece(stor + liten) < 0.02


def test_ece_fanger_grov_overmodighet():
    par = [(0.95, True)] * 5 + [(0.95, False)] * 5        # lover .95, holder .5
    assert kal.ece(par) > 0.15


def test_ece_paa_tomt_grunnlag_er_null_ikke_krasj():
    assert kal.ece([]) == 0.0


def test_overmodige_botter_navngis():
    """Bare den farlige retningen. En modell som undervurderer seg selv
    sender for mange til gjennomgang — det koster tid, ikke riktighet."""
    par = ([(0.95, True)] * 5 + [(0.95, False)] * 5          # overmodig
           + [(0.55, True)] * 10)                            # forsiktig
    botter = [r["botte"] for r in kal.overmodig(par)]
    assert "0.9–1.0" in botter
    assert "0.5–0.7" not in botter


# ------------------------------------------------------------------ #
#  3. Prøvetakingen — uten den er tabellen umulig å fylle              #
# ------------------------------------------------------------------ #

def test_av_som_standard():
    """Prøvetaking koster menneskelig gjennomgangstid. Den skal være et
    valg, ikke noe som skjer fordi ingen slo det av."""
    import dokument_api as api
    assert api.KALIBRERING_ANDEL == 0.0
    assert not kal.skal_kalibreringsproeve("noe", 0.0)


def test_samme_dokument_gir_SAMME_svar():
    """Avgjøres av en hash, ikke av en tilfeldighet per kall. Ellers
    kunne to opplastinger av samme fil gi ulikt utfall, og settet blitt
    skjevt uten at noen kunne se hvordan."""
    for _ in range(5):
        assert (kal.skal_kalibreringsproeve("abc123", 0.5)
                == kal.skal_kalibreringsproeve("abc123", 0.5))


def test_andelen_treffer_omtrent_riktig():
    """Ti prosent skal bli omtrent ti prosent — ellers er «to prosent»
    i konfigurasjonen en påstand uten dekning."""
    truffet = sum(kal.skal_kalibreringsproeve(f"dok-{i}", 0.10)
                  for i in range(4000))
    assert 300 < truffet < 500, f"{truffet} av 4000 ved andel 0.10"


def test_full_andel_tar_alt_og_tom_andel_ingenting():
    assert kal.skal_kalibreringsproeve("x", 1.0)
    assert not kal.skal_kalibreringsproeve("x", 0.0)
    assert not kal.skal_kalibreringsproeve("", 1.0)


# ------------------------------------------------------------------ #
#  4. Koblingen i serveren                                             #
# ------------------------------------------------------------------ #

def test_proeven_skygger_ikke_for_en_ekte_daarlig_lesing():
    """Rekkefølgen er en RANGERING. Et dokument som faktisk ble lest
    dårlig skal aldri merkes «kalibreringsproeve» — da ville en ekte
    feil sett ut som en stikkprøve."""
    import inspect

    import dokument_api as api
    kilde = inspect.getsource(api._kanskje_send_til_gjennomgang)
    plass = kilde.index("grunn = (")
    blokk = kilde[plass:plass + 320]
    for tidligere in ("tomt_resultat", "lav_ocr_konfidens", "handskrift"):
        assert blokk.index(tidligere) < blokk.index("kalibreringsproeve")


def test_godt_leste_dokumenter_slipper_fortsatt_unna_naar_andelen_er_null():
    import inspect

    import dokument_api as api
    kilde = inspect.getsource(api._kanskje_send_til_gjennomgang)
    assert "if not proeve:" in kilde
    assert "return None" in kilde


def test_konfidensen_og_beslutningen_havner_i_tilgangsloggen():
    """Uten dem finnes det ingen fordeling å regne kalibrering på —
    heller ikke etter at prøvetakingen er slått på."""
    import inspect

    import dokument_api as api
    logg = inspect.getsource(api._skriv_tilgang)
    assert '"ocr_konfidens"' in logg
    assert '"gjennomgang"' in logg


def test_alle_analyseveiene_noterer_det():
    """Tre veier kaller analysen. Noterer bare én av dem, blir
    fordelingen skjev på en måte ingen kan se."""
    import inspect

    import dokument_api as api
    kilde = inspect.getsource(api.Handler)
    assert kilde.count("_noter_kalibrering(a)") == 3


def test_loggen_baerer_ALDRI_dokumentinnhold():
    import inspect

    import dokument_api as api
    kilde = inspect.getsource(api.Handler._noter_kalibrering)
    for forbudt in ("tekst", "raa_tekst", "felter", "innhold"):
        assert f'analyse.get("{forbudt}")' not in kilde, forbudt

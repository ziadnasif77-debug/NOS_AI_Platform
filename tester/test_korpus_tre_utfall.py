"""Korpuset skiller «mangler» fra «galt» — og regner per felt.

Kjøreren hadde TO bøtter: `bestatt` og `feilet`. Da havnet to helt
ulike ting i samme tall:

    mangler  →  saksbehandleren SER tomrommet og fyller det selv
    galt     →  saksbehandleren ser en verdi og bygger et vedtak på den

Slått sammen kunne korpuset gå fra ti TOMME felter til ti GALE verdier
uten at prosenten rørte seg. Det er den verste formen for stille
forverring: målingen sier at ingenting har skjedd.

Og tallene regnes PER FELT. `fodselsnummer` er mod11-bevist og skal ha
presisjon 1.00; `kontornavn` har ingen sjekksum og feiler oftere. Et
snitt over de to sier ingenting om noen av dem.
"""
import os
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))

import kjor_korpus as kk


# ------------------------------------------------------------------ #
#  1. Regnestykket                                                     #
# ------------------------------------------------------------------ #

def test_presisjon_skiller_seg_fra_recall():
    """Fem forsøk: 3 riktige, 1 gal, 1 manglende.

        presisjon = 3/4  — av det jeg SVARTE på, var 3 riktige
        recall    = 3/5  — av alt som fantes, fikk jeg 3
    """
    utfall = [("fnr", "riktig")] * 3 + [("fnr", "galt"), ("fnr", "mangler")]
    rad = kk.presisjon_og_recall(utfall)["fnr"]
    assert rad == {"riktig": 3, "mangler": 1, "galt": 1,
                   "presisjon": 0.75, "recall": 0.6}


def test_et_manglende_felt_senker_recall_men_IKKE_presisjon():
    """Kjernen i skillet. Å ikke svare er ikke å svare feil."""
    rad = kk.presisjon_og_recall(
        [("f", "riktig"), ("f", "mangler")])["f"]
    assert rad["presisjon"] == 1.0
    assert rad["recall"] == 0.5


def test_en_gal_verdi_senker_BEGGE():
    """En gal verdi er verre, og det skal tallene vise."""
    rad = kk.presisjon_og_recall([("f", "riktig"), ("f", "galt")])["f"]
    assert rad["presisjon"] == 0.5
    assert rad["recall"] == 0.5


def test_aldri_besvart_gir_presisjon_None_ikke_null():
    """«0 av 0 riktige» er ikke 0 %, det er fravær av data. Skrev vi
    0.0 der, ville et felt vi ikke har målt sett ut som vårt verste."""
    rad = kk.presisjon_og_recall([("f", "mangler")])["f"]
    assert rad["presisjon"] is None
    assert rad["recall"] == 0.0


def test_hvert_felt_regnes_for_seg():
    """Et snitt over `fodselsnummer` og `kontornavn` skjuler begge."""
    kart = kk.presisjon_og_recall([
        ("felter.felter.fodselsnummer", "riktig"),
        ("felter.felter.fodselsnummer", "riktig"),
        ("felter.felter.kontornavn", "galt"),
    ])
    assert kart["felter.felter.fodselsnummer"]["presisjon"] == 1.0
    assert kart["felter.felter.kontornavn"]["presisjon"] == 0.0


def test_tomt_grunnlag_gir_tomt_kart():
    assert kk.presisjon_og_recall([]) == {}


# ------------------------------------------------------------------ #
#  2. Kjøreren merker de tre utfallene riktig                          #
# ------------------------------------------------------------------ #

def test_kjoreren_har_tre_utfall_ikke_to():
    import inspect
    kilde = inspect.getsource(kk.kjor_ett)
    kode = "\n".join(l.split("#")[0] for l in kilde.splitlines())
    for hva in ('"riktig"', '"mangler"', '"galt"'):
        assert hva in kode, f"utfallet {hva} finnes ikke i kjøreren"


def test_manglende_verdi_merkes_som_MANGLER_ikke_galt():
    """Nøkkelen finnes ikke i svaret, ELLER den er tom. Begge deler er
    et hull, ikke en påstand."""
    import inspect
    kilde = inspect.getsource(kk.kjor_ett)
    assert "faktisk is MANGLER or faktisk in (None" in kilde, (
        "et tomt felt («», [], {}) må telle som MANGLER, ikke som en "
        "gal verdi — ellers ser et uutfylt felt ut som en feillesing")


def test_meldingene_sier_HVILKEN_av_de_to():
    """En loggrad som bare sier «feilet» tvinger leseren til å gjette
    hvilken av de to kategoriene hen ser på."""
    import inspect
    kilde = inspect.getsource(kk.kjor_ett)
    assert "MANGLER (ventet" in kilde
    assert "GALT — ventet" in kilde


def test_listesjekken_teller_manglende_verdi_som_MANGLER():
    """En verdi som skulle stått i lista og ikke gjør det, er et hull —
    de andre verdiene i lista kan godt være riktige."""
    import inspect
    kilde = inspect.getsource(kk.kjor_ett)
    etter = kilde[kilde.index("felter_maa_inneholde"):]
    assert '"mangler"' in etter, (
        "en manglende listeverdi telles ikke som MANGLER")


# ------------------------------------------------------------------ #
#  3. Rapporten kan ikke skjule en gal verdi                           #
# ------------------------------------------------------------------ #

def test_rapporten_navngir_gale_verdier_saerskilt():
    import inspect
    kilde = inspect.getsource(kk.main)
    assert "GALE VERDIER" in kilde, (
        "gale verdier må stå fram — de er den alvorlige kategorien")
    assert "presisjon_og_recall" in kilde


def test_rapporten_viser_tabell_per_felt():
    import inspect
    kilde = inspect.getsource(kk.main)
    assert "per_felt" in kilde
    assert "presis" in kilde and "recall" in kilde


# ------------------------------------------------------------------ #
#  4. felter_antall — fasiten kan si «to personer» uten å liste dem    #
# ------------------------------------------------------------------ #

def test_kjoreren_forstaar_felter_antall():
    import inspect
    kilde = inspect.getsource(kk.kjor_ett)
    assert "felter_antall" in kilde


def test_faerre_enn_ventet_er_MANGLER_flere_er_GALT():
    """Retningen betyr noe. Finner vi ett fødselsnummer der fasiten sier
    to, er det et hull. Finner vi tre, har noe blitt LEST som en
    identifikator uten å være det — en påstand for mye."""
    import inspect
    kilde = inspect.getsource(kk.kjor_ett)
    etter = kilde[kilde.index("felter_antall"):]
    assert 'MANGLER — ventet' in etter
    assert 'GALT — ventet' in etter


def test_ingen_ellevesifrede_tall_i_korpusfasitene():
    """Fasitene ligger i git, og repoet ligger på GitHub. Et ellevesifret
    tall i en fil ser ut som et ekte fødselsnummer uansett hvor
    syntetisk det er ment å være — den som leser repoet kjenner ikke
    opprinnelsen.

    Fasitene sa `['12345678910', '12345678910']` — den dokumenterte
    plassholderen, to ganger, for både fnr og konto. Den ble aldri fylt
    ut, og hver kjøring meldte fire manglende verdier for noe
    dokumentet aldri inneholdt. `felter_antall` sier det samme uten å
    liste noe."""
    import glob
    import re
    mistenkt = []
    for sti in glob.glob(os.path.join(ROT, "tester", "korpus", "*.json")):
        with open(sti, encoding="utf-8") as f:
            for nr, linje in enumerate(f, 1):
                for treff in re.finditer(r"(?<!\d)\d{11}(?!\d)", linje):
                    mistenkt.append("%s:%d (%s…)"
                                    % (os.path.basename(sti), nr,
                                       treff.group(0)[:3]))
    assert not mistenkt, f"ellevesifrede tall i korpusfasit: {mistenkt}"


def test_fasitene_bruker_kanonisk_datoform():
    """R133 gjorde datoene ISO. Fasiten ble ikke oppdatert, og meldte
    derfor en GAL VERDI for noe systemet gjorde riktig — en fasit som
    er etter koden får målingen til å lyve."""
    import glob
    import json as _json
    import re
    gamle = []
    for sti in glob.glob(os.path.join(ROT, "tester", "korpus", "*.json")):
        with open(sti, encoding="utf-8") as f:
            fasit = _json.load(f)
        for felt, verdi in (fasit.get("felter") or {}).items():
            if isinstance(verdi, str) and re.fullmatch(r"\d{2}\.\d{2}\.\d{4}",
                                                       verdi):
                gamle.append("%s: %s = %s"
                             % (os.path.basename(sti), felt, verdi))
    assert not gamle, f"norsk datoform i fasit (R133 gjorde dem ISO): {gamle}"


# ------------------------------------------------------------------ #
#  Fasiten skal måle riktighet, ikke skrivemåte                       #
# ------------------------------------------------------------------ #

def _sammenlign():
    import importlib.util
    sti = os.path.join(ROT, "skript", "kjor_sporsmaalskorpus.py")
    spec = importlib.util.spec_from_file_location("_korpuskjorer", sti)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dato_paa_norsk_teller_som_samme_dato():
    """Modellen svarte «15. september 2026» på et spørsmål med fasit
    «15.09.2026», og ble talt som FEIL i seks kjøringer på rad. Det er
    samme dato. Korpuset er det eneste grunnlaget modellbytter dømmes
    på — en fasit som teller et riktig svar som galt, gjør hver
    sammenligning etter den mindre verdt."""
    m = _sammenlign()
    assert m._inneholder("Neste revurdering er 15. september 2026.",
                         "15.09.2026")
    assert m._inneholder("18. april 2026", "18.04.2026")
    assert m._inneholder("Datert 8. mai 2026", "2026-05-08")


def test_feil_dato_slipper_ikke_gjennom():
    """Slingringen gjelder SKRIVEMÅTEN, ikke datoen. Året kreves med,
    ellers kunne «15. september» truffet feil år i en bunke som spenner
    over flere."""
    m = _sammenlign()
    assert not m._inneholder("24.06.2026", "18.04.2026")
    assert not m._inneholder("15. september 2025", "15.09.2026")
    assert not m._inneholder("12. mai 2026", "15.09.2026")
    assert not m._inneholder("15. september", "15.09.2026")


def test_ikke_datoer_roeres_ikke():
    m = _sammenlign()
    assert m._datoformer("oeverst") == []
    assert m._datoformer("folketrygdloven") == []
    assert m._datoformer("31.13.2026") == [], "maaned 13 finnes ikke"

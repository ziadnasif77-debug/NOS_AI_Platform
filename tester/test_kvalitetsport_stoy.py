"""Kvalitetsporten skal skille SIGNAL fra STØY — ikke to punkttall.

Porten sa: `cer_kandidat <= cer_live + CER_MARGIN`, med margin 0.0. På
et lite valideringssett er forskjellen mellom CER 0.041 og 0.043 ren
tilfeldighet — hvilke dokumenter som tilfeldigvis havnet i settet, ikke
hvor god modellen er. Porten promoterte eller avviste altså på støy.

En fast margin løser det ikke; den flytter bare terskelen for hvilken
støy som slipper gjennom.

Nå faller dommen på et konfidensintervall regnet med bootstrap.
Overlapper intervallene til kandidat og live, KAN de ikke skilles på
dette settet — og «kandidaten er bedre» er da en påstand tallene ikke
bærer. Da promoteres ingenting: live blir stående, som er det trygge
valget.

To ting som lett blir glemt, og som er testet her:

  · Frøet er FAST. En kvalitetsport som gir ulik dom på samme inndata
    fra kjøring til kjøring er verre enn en fast margin — den er ikke
    bare upresis, den er uetterrettelig.

  · macro-CER regnes ved siden av micro. Et dokument på ti tegn som
    leses helt feil gir CER 1.0 og drar macro voldsomt opp, men rører
    knapt micro. Sprik mellom dem betyr ujevn ytelse over
    dokumentlengder — en opplysning, ikke støy å velge bort.
"""
import os
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))

import valider_modell as vm


# ------------------------------------------------------------------ #
#  1. Bootstrap-intervallet                                            #
# ------------------------------------------------------------------ #

def test_intervallet_omslutter_punktestimatet():
    feil = [2, 1, 3, 0, 5, 1, 2, 4]
    tegn = [40, 35, 50, 20, 60, 30, 45, 55]
    micro = sum(feil) / sum(tegn)
    lav, hoy = vm.bootstrap_ki(feil, tegn)
    assert lav <= micro <= hoy


def test_et_LITE_sett_gir_et_BREDT_intervall():
    """Selve poenget: bredden er et mål på hvor lite vi egentlig vet."""
    feil, tegn = [2, 1, 3], [40, 35, 50]
    smal = vm.bootstrap_ki(feil * 20, tegn * 20)
    bred = vm.bootstrap_ki(feil, tegn)
    assert (bred[1] - bred[0]) > (smal[1] - smal[0]), (
        "et sett på tre dokumenter må gi et bredere intervall enn ett "
        "på seksti — ellers måler ikke intervallet usikkerhet")


def test_samme_inndata_gir_SAMME_intervall():
    """Fast frø. En port som gir ulik dom på samme inndata fra kjøring
    til kjøring er uetterrettelig — en avvist kandidat må kunne
    undersøkes på nytt og gi samme svar.

    Settet er TRETTI dokumenter med ulike lengder, ikke fem. Den første
    versjonen av denne testen brukte fem, og besto da også UTEN frø:
    med så få dokumenter finnes det for få ulike utvalg, og avrundingen
    til fire desimaler skjulte resten. Målt på tretti gir en usådd
    bootstrap fem ulike svar av fem — da beviser testen noe."""
    feil = [(i * 3 + 1) % 9 for i in range(30)]
    tegn = [30 + (i * 7) % 90 for i in range(30)]
    assert vm.bootstrap_ki(feil, tegn) == vm.bootstrap_ki(feil, tegn)
    # …og at frøet faktisk er det som gjør det: to ULIKE frø må gi
    # ulike svar, ellers kunne testen over bestått av en helt annen
    # grunn (f.eks. at resamplingen ikke skjer i det hele tatt).
    assert (vm.bootstrap_ki(feil, tegn, froe=1)
            != vm.bootstrap_ki(feil, tegn, froe=2))


def test_tomt_sett_gir_ikke_krasj():
    assert vm.bootstrap_ki([], []) == (0.0, 0.0)


# ------------------------------------------------------------------ #
#  2. Overlapp betyr «kan ikke skilles»                                #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("a,b,forventet", [
    ((0.03, 0.05), (0.04, 0.06), True),    # delvis overlapp
    ((0.03, 0.05), (0.05, 0.07), True),    # rører hverandre i endepunktet
    ((0.01, 0.02), (0.05, 0.07), False),   # klart adskilt
    ((0.05, 0.07), (0.01, 0.02), False),   # motsatt rekkefølge
    ((0.03, 0.05), (0.03, 0.05), True),    # identiske
])
def test_overlappsjekken(a, b, forventet):
    assert vm.intervallene_overlapper(a, b) is forventet


def test_overlappsjekken_er_symmetrisk():
    a, b = (0.02, 0.04), (0.035, 0.06)
    assert vm.intervallene_overlapper(a, b) == vm.intervallene_overlapper(b, a)


# ------------------------------------------------------------------ #
#  3. macro ved siden av micro                                         #
# ------------------------------------------------------------------ #

def test_macro_avsloerer_det_micro_skjuler():
    """Ni lange dokumenter lest perfekt, ett kort lest helt feil.

        micro ≈ 0.01  — de ti feiltegnene drukner i tusen
        macro = 0.10  — ett av ti dokumenter er ubrukelig

    Begge er sanne. Bare micro ville sagt «alt er bra»."""
    feil = [0] * 9 + [10]
    tegn = [100] * 9 + [10]
    micro = sum(feil) / sum(tegn)
    macro = vm.macro_cer(feil, tegn)
    assert micro < 0.02
    assert macro == pytest.approx(0.10, abs=0.001)


def test_macro_og_micro_er_like_naar_ytelsen_er_jevn():
    """Speilet: uten dette kunne «de spriker» oppfylles av en feil i
    formelen."""
    feil, tegn = [5, 5, 5], [100, 100, 100]
    assert vm.macro_cer(feil, tegn) == pytest.approx(
        sum(feil) / sum(tegn), abs=0.001)


def test_macro_taaler_tomt_sett():
    assert vm.macro_cer([], []) == 0.0


# ------------------------------------------------------------------ #
#  4. Dommen bruker intervallene, ikke en margin                       #
# ------------------------------------------------------------------ #

def test_den_faste_marginen_er_BORTE():
    """En bryter som ser ut som en innstilling og ikke lenger styrer
    noe, er verre enn ingen (R140)."""
    assert not hasattr(vm, "CER_MARGIN"), (
        "CER_MARGIN er tilbake — da avgjør porten igjen på to punkttall")
    eksempel = open(os.path.join(ROT, ".env.example"), encoding="utf-8").read()
    linjer = [l for l in eksempel.splitlines()
              if l.strip().startswith("CER_MARGIN")]
    assert not linjer, "CER_MARGIN står fortsatt i .env.example"


def test_vurderingen_regner_intervaller():
    import inspect
    kilde = inspect.getsource(vm.vurder)
    kode = "\n".join(l.split("#")[0] for l in kilde.splitlines())
    assert "bootstrap_ki" in kode
    assert "intervallene_overlapper" in kode
    assert "CER_MARGIN" not in kode


def test_de_fire_utfallene_er_navngitt():
    """En dom uten grunn er ikke etterprøvbar. «ikke_skillbar» er det
    NYE utfallet — det fantes ikke da porten bare kunne si bedre eller
    dårligere."""
    import inspect
    kilde = inspect.getsource(vm.vurder)
    for grunn in ("ingen_live_modell", "ikke_skillbar", "bedre",
                  "daarligere"):
        assert f'"{grunn}"' in kilde, grunn


def test_likt_resultat_promoterer_IKKE():
    """Det trygge valget ved uavgjort er å la live stå. Å promotere på
    et resultat vi ikke kan skille, er å bytte ut en kjent modell med
    en ukjent uten grunn."""
    import inspect
    kilde = inspect.getsource(vm.vurder)
    plass = kilde.index("intervallene_overlapper")
    assert "godkjent = False" in kilde[plass:plass + 200]


def test_svaret_baerer_BEGGE_snittene_og_begge_intervallene():
    """Uten dem kan ingen etterprøve dommen."""
    import inspect
    kilde = inspect.getsource(vm.vurder)
    for felt in ("macro_cer_live", "macro_cer_kandidat",
                 "ki_live", "ki_kandidat"):
        assert f'"{felt}"' in kilde, felt


def test_cer_kan_gi_tallene_per_dokument():
    """Uten dem er et konfidensintervall umulig: funksjonen summerte
    feil og tegn og kastet fordelingen, og da finnes ikke noe å
    resample."""
    import inspect
    kilde = inspect.getsource(vm.cer_for_modell)
    assert "per_dokument" in kilde
    assert "feil_per_dok" in kilde and "tegn_per_dok" in kilde

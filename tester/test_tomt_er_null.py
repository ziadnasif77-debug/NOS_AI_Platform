"""
«Tomt» er null — og `[]` betyr at vi FAKTISK så etter.

To regler som hadde glidd fra hverandre:

1. TOM STRENG ER IKKE null. `strukturert_uttrekk` svarte «» der
   profilen svarer null — for NØYAKTIG samme faktum, i samme svar:

       struktur.dokument.ytelse          ""
       dokumentprofil.ytelse.navn.kode   null

   To konvensjoner for «finnes ikke» i én JSON-kropp. R126 sier det
   rett ut: en tom streng SER ut som en verdi. `if (ytelse)` er falsk
   for begge, men `!= null` i C#/.NET er SANT for «» — og da tror
   roboten den fant en ytelse.

2. `[]` ER EN PÅSTAND. Regelen er `[]` = «vi så etter og fant
   ingenting», `null` = «vi så aldri etter». Tre felt brøt den:

   * `koder.qr`/`koder.strekkode` sto som tomme lister på dokumenter
     som ALDRI ble skannet. Målt: hver .txt-, .docx- og .csv-opplasting
     fikk `lest: true` og to tomme lister, fordi dekoderen ikke kalles
     på tekstveien i det hele tatt. Feltet `lest`, som finnes nettopp
     for å hindre den løgnen, fortalte den.
   * `handskrift_funnet: false` på dokumenter som aldri ble
     bildeanalysert. Håndskrift oppdages BARE på OCR-veien.

Mønsteret som allerede var riktig — `signatur_sider: null` i feltet og
`ikke_evaluert` i `dekning` — er nå brukt for begge.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api
from delt.dokumentprofil import bygg_profil, koder_med_sider
from delt.tekstuttrekk import strukturert_uttrekk

TOMT = "[Side 1 av 1]\nEt notat uten noe som helst.\n"
RIKT = ("[Side 1 av 1]\nNAV Arbeid og ytelser\nVedtak om sykepenger\n"
        "Saksnummer: 4417820\n")


# ------------------------------------------------------------------ #
#  1. Ingen tomme strenger                                             #
# ------------------------------------------------------------------ #

def _tomme_strenger(node, sti=""):
    funn = []
    if isinstance(node, dict):
        for k, v in node.items():
            funn += _tomme_strenger(v, f"{sti}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            funn += _tomme_strenger(v, f"{sti}[{i}]")
    elif node == "":
        funn.append(sti)
    return funn


@pytest.mark.parametrize("merke,tekst", [("tomt", TOMT), ("rikt", RIKT)])
def test_struktur_bruker_null_ikke_tom_streng(merke, tekst):
    funn = _tomme_strenger(strukturert_uttrekk(tekst))
    assert not funn, (
        f"«{merke}»: tomme strenger i strukturert_uttrekk: {funn}. "
        f"Profilen svarer null for de samme faktaene — to konvensjoner "
        f"for «finnes ikke» i én kropp (R126).")


def test_samme_faktum_har_samme_tomhet_i_begge_blokkene():
    """Kjernen: struktur og profil skal si det samme om «ingenting»."""
    s = strukturert_uttrekk(TOMT)
    p = bygg_profil(TOMT, antall_sider=1, struktur=s)
    assert s["dokument"]["ytelse"] is None
    assert p["ytelse"]["navn"]["kode"] is None
    assert s["identifikatorer"]["saksnummer"] is None
    assert p["sak"]["saksnummer"] is None


# ------------------------------------------------------------------ #
#  2. [] betyr «vi så etter»                                           #
# ------------------------------------------------------------------ #

def test_uskannet_dokument_sier_vet_ikke_ikke_ingen_koder():
    uten = koder_med_sider([], lest=False)
    assert uten["qr"] is None, "tom liste påstår «ingen QR-kode»"
    assert uten["strekkode"] is None
    assert uten["lest"] is False
    assert uten["merknad"], "forbeholdet må stå der"


def test_skannet_dokument_uten_treff_sier_ingen_koder():
    """Speilet — uten dette ville testen over vært grønn om vi alltid
    svarte null."""
    med = koder_med_sider([], lest=True)
    assert med["qr"] == [] and med["strekkode"] == []
    assert med["lest"] is True


def test_tekstopplasting_teller_ikke_som_skannet():
    """Den ekte feilen, gjennom hele lesekjeden: en .txt kalles aldri
    inn til dekoderen, men sto likevel som «lest»."""
    H = api.Handler

    class Fake:
        _les_dokument = H._les_dokument

        def _svar(self, kode, data, hoder=None):
            return (kode, data)

    ktx, _, feil = Fake()._les_dokument("p.txt", "tekst", TOMT, None, True)
    assert feil is None
    assert ktx.strekkoder_lest is False, (
        "tekstveien kaller aldri dekoderen — da kan «lest» ikke være True")
    koder = ktx.profil["koder"]
    assert koder["qr"] is None and koder["strekkode"] is None


def test_handskrift_er_vet_ikke_uten_ocr():
    uten_ocr = bygg_profil(TOMT, antall_sider=1, handskrift=[],
                           handskrift_lest=False)
    assert uten_ocr["visuelt"]["handskrift_funnet"] is None, (
        "«false» er en påstand om en måling som ikke ble gjort")
    med_ocr = bygg_profil(TOMT, antall_sider=1, handskrift=[],
                          handskrift_lest=True)
    assert med_ocr["visuelt"]["handskrift_funnet"] is False


# ------------------------------------------------------------------ #
#  3. dekning sier HVORFOR feltet er null                              #
# ------------------------------------------------------------------ #

def test_dekningen_forklarer_begge_de_nye_nullene():
    """Mønsteret som alt var riktig for signatur_sider: null i feltet,
    grunnen i `dekning`. Uten det måtte klienten lese «merknad» som
    prosa for å vite om skanningen kjørte."""
    uten = bygg_profil(TOMT, antall_sider=1, strekkoder_lest=False,
                       handskrift_lest=False)
    assert uten["dekning"]["koder"] == "ikke_evaluert"
    assert uten["dekning"]["handskrift"] == "ikke_evaluert"

    med = bygg_profil(TOMT, antall_sider=1, strekkoder_lest=True,
                      handskrift_lest=True)
    assert med["dekning"]["koder"] == "full"
    assert med["dekning"]["handskrift"] == "full"


def test_feltet_og_dekningen_sier_aldri_ulike_ting():
    """En klient som stoler på `dekning` og en som leser feltet skal
    komme fram til det samme."""
    for lest in (True, False):
        p = bygg_profil(TOMT, antall_sider=1, strekkoder_lest=lest,
                        handskrift_lest=lest)
        tomt_felt = p["koder"]["qr"] is None
        sier_ikke_evaluert = p["dekning"]["koder"] == "ikke_evaluert"
        assert tomt_felt == sier_ikke_evaluert, (
            f"lest={lest}: feltet og dekningen er uenige")

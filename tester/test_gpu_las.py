"""GPU-låsen tas der kortet FAKTISK brukes (R163).

OCR og språkmodellen deler ett kort på 8 GB. `GPU_LAS` finnes for at de
aldri skal kjøre samtidig — måltallet i koden er 3,3 s → 18,5 s når de
konkurrerer, og familien over det er det tause native krasjet
0xC0000005.

FEILEN VAR EN REKKEFØLGE
`ocr_side` spurte `_paa_gpu()` FØR den kalte videre. Men
`_norhand["enhet"]` blir «cuda» først inne i `_hent_norhand`, som
kalles NEDENFOR — fra `_norhand_les_batch`. Predikatet kom altså før
årsaken.

På den første siden etter oppstart med et fullt kort var
`_easyocr["gpu"]` False og `_norhand["enhet"]` None. Ingen lås ble tatt,
og TrOCR kjørte på kortet samtidig med Borealis.

OG DEN LEGER SEG SELV
Etter første side svarer `_paa_gpu()` True, og alt ser riktig ut. En
test som leser to sider ser den aldri. Derfor måler denne vakten den
FØRSTE kallet, med tilstanden nullstilt.
"""
import os
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)

from delt import region_ocr as ro


@pytest.fixture
def nullstilt(monkeypatch):
    """Tilstanden slik den er rett etter oppstart: ingenting lastet."""
    monkeypatch.setitem(ro._easyocr, "gpu", False)
    monkeypatch.setitem(ro._norhand, "enhet", None)


def test_paa_gpu_er_usann_for_forste_kall(nullstilt):
    """Selve premisset for feilen — hvis dette blir sant en dag, er
    resten av testen ikke lenger den situasjonen den beskriver."""
    assert ro._paa_gpu() is False


class _Piksler:
    pixel_values = "piksler"


def _prosessor(images=None, return_tensors=None):
    return _Piksler()


class _Bilde:
    @staticmethod
    def fromarray(u):
        return _Bilde()

    def convert(self, _):
        return self


def _rigg(monkeypatch, enhet, sett):
    """Alt norhand-kallet trenger, uten torch og uten et ekte kort."""
    def _falsk_generer(prosessor, modell, piksler, utsnitt):
        # _is_owned() er sant bare for tråden som holder RLock-en.
        sett["holdt"] = ro.GPU_LAS._is_owned()
        return [("tekst", 0.9)]

    def _last():
        # Enheten settes HER — akkurat slik _hent_norhand gjør det, etter
        # at _paa_gpu() alt har svart False.
        ro._norhand["enhet"] = enhet
        return (_prosessor, object(), enhet)

    monkeypatch.setattr(ro, "_hent_norhand", _last)
    monkeypatch.setattr(ro, "_norhand_generer", _falsk_generer)
    pil = type(sys)("PIL")
    pil.Image = _Bilde
    monkeypatch.setitem(sys.modules, "PIL", pil)


def test_laasen_holdes_under_generate_paa_kortet(monkeypatch, nullstilt):
    """Måler at låsen faktisk HOLDES i det øyeblikket modellen kjører,
    ikke at et kall til den står et sted i kilden."""
    sett = {}
    _rigg(monkeypatch, "cuda", sett)
    ro._norhand_les_batch([object()])
    assert sett.get("holdt") is True, (
        "GPU_LAS ble IKKE holdt mens modellen kjørte på kortet")


def test_ingen_laas_naar_norhand_ligger_paa_cpu(monkeypatch, nullstilt):
    """Speilet. Låsen skal ikke tas på CPU-veien — da ville
    språkmodellen stått og ventet på noe som ikke rører kortet
    (R51-fallbacket)."""
    sett = {}
    _rigg(monkeypatch, "cpu", sett)
    ro._norhand_les_batch([object()])
    assert sett.get("holdt") is False


def test_oom_flytter_til_cpu_FOR_den_konverterer():
    """`.float()` før `.to("cpu")` gjør vektene til fp32 mens de
    fortsatt ligger på kortet — altså DOBLER minnebruken i det
    øyeblikket vi er tomme for minne, og feiler dermed tilbakefallet
    som skulle redde oss."""
    import inspect
    kilde = inspect.getsource(ro._norhand_generer)
    assert 'modell.to("cpu").float()' in kilde, (
        "OOM-tilbakefallet konverterer før det flytter")
    assert 'modell.float().to("cpu")' not in kilde


# ------------------------------------------------------------------ #
#  Én budsjettregning, ikke to uavhengige (R166)                       #
# ------------------------------------------------------------------ #
#
# Tersklene ble evaluert HVER FOR SEG og etter hverandre: EasyOCR målte
# det ledige og tok sin del, så målte norhand det som var IGJEN og tok
# sin. Ingen av dem regnet på summen, og ingen tok høyde for at
# llama.cpp allokerer compute-buffere dynamisk under neste inferens.
#
# At det holdt i praksis var en egenskap ved tallene, ikke ved
# konstruksjonen — og slike marginer er nettopp det som ga det tause
# native krasjet 0xC0000005.

def test_paaslaget_gjelder_naar_easyocr_alt_ligger_paa_kortet(monkeypatch):
    """Den kritiske forskjellen: 2000 MB ledig slapp norhand gjennom
    selv om EasyOCR alt hadde lovet bort sine arbeidsbuffere."""
    monkeypatch.setattr(ro, "ledig_gpu_mb", lambda: 2000.0)
    monkeypatch.setitem(ro._easyocr, "gpu", True)
    assert ro._gpu_budsjett_ok(ro.MINSTE_LEDIG_GPU_NORHAND_MB) is False
    # ... og den gamle regningen ville sagt ja
    assert 2000.0 >= ro.MINSTE_LEDIG_GPU_NORHAND_MB


def test_uten_easyocr_paa_kortet_er_kravet_uendret(monkeypatch):
    """Speilet. Påslaget skal ikke straffe CPU-veien — der finnes ingen
    EasyOCR-buffere å reservere for."""
    monkeypatch.setattr(ro, "ledig_gpu_mb", lambda: 2000.0)
    monkeypatch.setitem(ro._easyocr, "gpu", False)
    assert ro._gpu_budsjett_ok(ro.MINSTE_LEDIG_GPU_NORHAND_MB) is True


def test_nok_plass_til_begge_slipper_gjennom(monkeypatch):
    """Budsjettet skal ikke være en forkledd av-bryter."""
    monkeypatch.setattr(ro, "ledig_gpu_mb", lambda: 2500.0)
    monkeypatch.setitem(ro._easyocr, "gpu", True)
    assert ro._gpu_budsjett_ok(ro.MINSTE_LEDIG_GPU_NORHAND_MB) is True


def test_uten_kort_er_svaret_nei(monkeypatch):
    monkeypatch.setattr(ro, "ledig_gpu_mb", lambda: 0.0)
    assert ro._gpu_budsjett_ok(1) is False


def test_norhandlastingen_bruker_budsjettet_ikke_en_naken_maaling():
    """Kildekontroll: regnestykket skal stå ETT sted. Blir det kopiert
    tilbake til en `ledig_gpu_mb() >= …` inne i lasteren, er vi der vi
    startet."""
    import inspect
    kilde = inspect.getsource(ro._hent_norhand)
    assert "_gpu_budsjett_ok" in kilde
    assert "ledig_gpu_mb() >= MINSTE_LEDIG_GPU_NORHAND_MB" not in kilde

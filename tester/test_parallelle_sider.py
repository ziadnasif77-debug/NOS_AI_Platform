"""
Sidene leses samtidig — men dokumentet er fortsatt det samme (R203).

Målingen som utløste dette: seks tråder gjennom `ocr_side` ga 0,97× og
brukte NØYAKTIG de samme 5,0 kjernene som én tråd. Modullåsen sto rundt
hele siden, så trådene sto i kø uansett hvor mange de var.

Å fjerne låsen ga 1,41× — og to av 30 sider ble LEST ANNERLEDES.

Hypotesen var håndskriftpasset: norhand byttes til CPU for alle tråder
ved GPU-mangel, midt i en inferens. Låsen ble bygget, og hypotesen ble
MÅLT — og forkastet. Avviket var der fortsatt.

Den virkelige årsaken er et TIDSBUDSJETT (MAKS_NORHAND_SEKUNDER): hvor
mange håndskriftregioner en side rekker, avhenger av hvor rask maskinen
var akkurat da. Ingen lås kan rette det, for parallellitet ENDRER
klokketiden — det er hele poenget med den.

Og det gjør funnet større enn parallellitet: dette er et R6-brudd som
finnes I DAG, uten en eneste tråd. Samme dokument lest på en travel
maskin gir allerede et annet svar enn på en rolig.

Parallelliteten står derfor AV. Denne fila vokter tre ting:

  1. AT DEN ER AV — og hvorfor, så ingen skrur den på uten å ha byttet
     tidsbudsjettet mot et deterministisk tak først.
  2. REKKEFØLGEN. Teksten settes sammen av sidenes rekkefølge, og en
     bunke i feil rekkefølge er et ANNET dokument. Testen tvinger sidene
     til å bli ferdige i motsatt rekkefølge av den de ble sendt inn i.
  3. HVEM som får lov, den dagen den skrus på: bare RapidOCR på CPU.
"""
import sys
import threading
import time

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api as api
from delt import region_ocr


# ------------------------------------------------------------------ #
#  Hvem får lese parallelt                                            #
# ------------------------------------------------------------------ #

def test_parallellitet_er_AV_som_standard():
    """Den viktigste testen i fila, og den handler om en MÅLING.

    Maskineriet virker — seks tråder gir 1,38× — men porten det skal
    igjennom er determinisme, og den strøk: 2 av 30 sider ble lest
    annerledes, også etter at all håndskriftbruk ble serialisert.

    Ingen lås kan rette det: `_les_med_norhand` og UFCN-andrepasset har
    et TIDSBUDSJETT, så hvor mange håndskriftregioner som rekkes
    avhenger av hvor rask maskinen var akkurat da. Parallellitet endrer
    klokketiden — det er hele poenget med den.

    Skrus denne på uten at tidsbudsjettet først er byttet ut med et
    deterministisk tak, brytes R6."""
    assert region_ocr.PARALLELLE_SIDER is False, (
        "parallell sidelesing er skrudd PÅ, men den strøk "
        "determinismeporten: tidsbudsjettet i norhand-veien gjør "
        "resultatet avhengig av maskinens fart (R203)")


def test_tidsbudsjettet_er_fortsatt_der_og_er_grunnen():
    """Vakten peker på selve årsaken, så den ikke blir borte i en
    kommentar. Forsvinner tidsbudsjettet, skal noen ta stilling til om
    parallelliteten kan på — ikke oppdage det ved et uhell."""
    import inspect
    kilde = inspect.getsource(region_ocr._les_med_norhand)
    assert "MAKS_NORHAND_SEKUNDER" in kilde, (
        "tidsbudsjettet er borte fra norhand-veien — da kan "
        "determinismeporten kjøres på nytt, og parallelliteten kanskje "
        "skrus på (R203)")


def test_bare_rapid_paa_cpu_kan_leses_parallelt(monkeypatch):
    """Regelen om HVEM som kan gå parallelt, prøvd med bryteren på —
    ellers ville testen bare målt at alt er av.

    BEGGE inngangene settes eksplisitt. `_easyocr["gpu"]` er ekte delt
    tilstand: laster en annen test EasyOCR på kortet, blir den True og
    står der. Da ville denne testen feilet på noe som ikke er dens
    eget — og en test som avhenger av rekkefølgen er verre enn ingen."""
    monkeypatch.setattr(region_ocr, "PARALLELLE_SIDER", True)
    monkeypatch.setitem(region_ocr._easyocr, "gpu", False)
    assert region_ocr.kan_lese_parallelt("rapid") is True, (
        f"PARALLELLE_SIDER={region_ocr.PARALLELLE_SIDER} "
        f"easyocr_gpu={region_ocr._easyocr['gpu']}")
    assert region_ocr.kan_lese_parallelt("easy") is False
    assert region_ocr.kan_lese_parallelt("") is False


def test_easyocr_paa_gpu_slaar_av_parallellitet(monkeypatch):
    monkeypatch.setattr(region_ocr, "PARALLELLE_SIDER", True)
    monkeypatch.setitem(region_ocr._easyocr, "gpu", True)
    assert region_ocr.kan_lese_parallelt("rapid") is False


def test_bryteren_slaar_av_alt(monkeypatch):
    """Skal parallelliteten av i en fart, skal det ikke kreve en ny
    utrulling."""
    monkeypatch.setattr(region_ocr, "PARALLELLE_SIDER", False)
    assert region_ocr.kan_lese_parallelt("rapid") is False


@pytest.mark.parametrize("policy,forventet_over_1", [
    ({"motor": "rapid"}, True),
    ({"motor": "easy"}, False),
    ({}, False),
    (None, False),
])
def test_jobben_velger_traadtall_etter_den_frosne_policyen(
        policy, forventet_over_1, monkeypatch):
    """Policyen fryses ved jobbstart (R199). Det er DEN som bestemmer,
    ikke hva maskinen tilfeldigvis ville valgt nå."""
    monkeypatch.setattr(region_ocr, "PARALLELLE_SIDER", True)
    monkeypatch.setitem(region_ocr._easyocr, "gpu", False)
    n = api._sidetraader(policy)
    assert (n > 1) is forventet_over_1, (
        f"traader={n} for {policy} "
        f"(easyocr_gpu={region_ocr._easyocr['gpu']})")
    assert n >= 1


def test_jobben_leser_sekvensielt_naar_bryteren_er_av():
    """Standardtilstanden i dag: ingen jobb leser sider parallelt."""
    assert api._sidetraader({"motor": "rapid"}) == 1


def test_regelen_bor_ett_sted():
    """To steder som svarer på det samme spørsmålet blir før eller
    siden uenige."""
    import inspect
    kilde = inspect.getsource(api._sidetraader)
    assert "kan_lese_parallelt" in kilde, (
        "_sidetraader avgjør parallellitet på egen hånd i stedet for å "
        "spørre region_ocr — da kan låsene og jobben bli uenige")


# ------------------------------------------------------------------ #
#  Håndskriftlåsen må tåle gjeninntreden                              #
# ------------------------------------------------------------------ #

def test_handskriftlaasen_er_gjeninntredende():
    """`_norhand_generer` kaller `_norhand_les_batch` PÅ NYTT etter en
    GPU-OOM. Med en vanlig Lock ville tilbakefallet — det som skal
    redde oss når kortet er fullt — låst seg selv ute."""
    assert region_ocr._HANDSKRIFT_LAS.acquire(blocking=False)
    try:
        assert region_ocr._HANDSKRIFT_LAS.acquire(blocking=False), (
            "håndskriftlåsen er ikke reentrant — OOM-tilbakefallet "
            "vil låse seg fast")
        region_ocr._HANDSKRIFT_LAS.release()
    finally:
        region_ocr._HANDSKRIFT_LAS.release()


def test_all_norhand_bruk_gaar_gjennom_laasen():
    """Låsen er verdiløs hvis noen leser håndskrift utenom den."""
    import inspect
    kilde = inspect.getsource(region_ocr._norhand_les_batch)
    assert "_HANDSKRIFT_LAS" in kilde


# ------------------------------------------------------------------ #
#  Rekkefølgen — selve faren                                          #
# ------------------------------------------------------------------ #

def _pdf_med_nummererte_sider(antall):
    """Hver side får sin egen gråtone, så en stubbet OCR kan lese
    sidenummeret rett ut av bildet."""
    import fitz
    d = fitz.open()
    for i in range(antall):
        s = d.new_page(width=120, height=120)
        v = (i + 1) * 8 / 255.0
        s.draw_rect(s.rect, color=(v, v, v), fill=(v, v, v))
    ut = d.tobytes()
    d.close()
    return ut


def _kjor_jobb(monkeypatch, antall_sider, traader):
    """Kjører EN jobb gjennom den ekte arbeidstråden og gir teksten."""
    ferdig = threading.Event()

    def falsk_ocr_side(bilde):
        nr = int(round(bilde[0, 0, 0] / 8))
        # De SISTE sidene blir ferdige FØRST. Uten rekkefølgevakt i
        # koden gir dette en bunke i motsatt rekkefølge — som er et
        # annet dokument.
        time.sleep(0.01 * (antall_sider - nr))
        return {"tekst": f"SIDE{nr}", "regioner": []}

    monkeypatch.setattr(region_ocr, "ocr_side", falsk_ocr_side)
    monkeypatch.setattr(api, "_sidetraader", lambda _p: traader)
    monkeypatch.setattr(api, "_jobb_lagre", lambda _j: None)
    monkeypatch.setattr(api, "rydd_jobber", lambda: None)

    jobb_id = f"test-{antall_sider}-{traader}"
    jobb = {"jobb_id": jobb_id, "status": "kø", "versjon": 1,
            "avbrutt": False, "feil": None,
            "sider_ferdig": None, "sider_totalt": None,
            "sekunder_brukt": 0, "sekunder_igjen_estimat": None,
            "_data": _pdf_med_nummererte_sider(antall_sider)}
    api._jobber[jobb_id] = jobb
    api._jobb_ko.put(jobb_id)

    t = threading.Thread(target=api._jobb_arbeider, daemon=True)
    t.start()
    for _ in range(600):
        if jobb.get("status") in ("ferdig", "delvis", "feil", "avbrutt"):
            ferdig.set()
            break
        time.sleep(0.05)
    assert ferdig.is_set(), f"jobben ble aldri ferdig: {jobb.get('status')}"
    return jobb


def test_sidene_kommer_i_riktig_rekkefolge_selv_naar_de_blir_ferdige_baklengs(
        monkeypatch):
    """Kjernen. Stubben gjør SISTE side raskest, så en implementasjon
    som skriver sidene i den rekkefølgen de blir ferdige, gir bunken
    baklengs."""
    jobb = _kjor_jobb(monkeypatch, 8, traader=4)
    assert jobb["status"] == "ferdig", jobb.get("feil")
    tekst = jobb["tekst"]
    plasseringer = [tekst.index(f"SIDE{n}") for n in range(1, 9)]
    assert plasseringer == sorted(plasseringer), (
        "sidene står ikke i sidenummerrekkefølge i den sammensatte "
        f"teksten:\n{tekst[:400]}")
    assert jobb["sider_ferdig"] == 8


def test_parallelt_gir_samme_tekst_som_sekvensielt(monkeypatch):
    """R6: samme dokument, samme svar. Farten er verdiløs uten dette."""
    seriell = _kjor_jobb(monkeypatch, 6, traader=1)["tekst"]
    parallell = _kjor_jobb(monkeypatch, 6, traader=4)["tekst"]
    assert seriell == parallell


def test_sidemarkorene_er_med_som_for(monkeypatch):
    jobb = _kjor_jobb(monkeypatch, 5, traader=3)
    for n in range(1, 6):
        assert f"[Side {n} av 5]" in jobb["tekst"]

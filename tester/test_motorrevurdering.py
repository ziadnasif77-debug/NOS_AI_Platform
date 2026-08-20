"""
R239: OCR-motoren låses ikke til CPU for godt — og bytter aldri midt i
et dokument.

Bakgrunnen er målt, ikke antatt. 2026-08-20 sto den kjørende serveren på
RapidOCR/CPU i timevis etter at kortet var blitt ledig igjen. Årsaken var
at `_velg_motor_for_maskinen` avgjorde ÉN gang og deretter returnerte det
samme svaret ut prosessens levetid. To ting fulgte av det:

  * En server som startet mens Borealis lastet — altså hver eneste
    oppstart — låste OCR-en til CPU. Målt forskjell på de samme sidene:
    1,27 s/side på GPU mot 2,87 s/side på CPU.
  * `policy_holder` sammenligner den frosne policyen med «hva maskinen
    ville valgt nå». Når det andre tallet aldri kunne endre seg, var
    hele avvikssjekken død kode: den kunne ikke slå ut uansett hva som
    skjedde med kortet.

Testene under vokter BEGGE retninger: at revurderingen skjer, og at den
aldri skjer på et tidspunkt som ville brutt R6 (samme dokument, samme
modell for alle sider).
"""
import sys
import threading

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

from delt import region_ocr


@pytest.fixture
def fersk_motor(monkeypatch):
    """Nullstiller motorvalget rundt hver test, så rekkefølgen på
    testene aldri kan avgjøre resultatet."""
    monkeypatch.setattr(region_ocr, "_valgt", {"motor": None, "tid": 0.0})
    monkeypatch.setattr(region_ocr, "_aapne_dokumenter", [0])
    monkeypatch.setattr(region_ocr, "OCR_MOTOR", "auto")
    return region_ocr


def _lat_som_ledig(monkeypatch, mb):
    """Later som kortet har `mb` MiB ledig — både den rå målingen og
    budsjettsjekken, som er den revurderingen faktisk spør."""
    monkeypatch.setattr(region_ocr, "ledig_gpu_mb", lambda: float(mb))
    monkeypatch.setattr(region_ocr, "_gpu_budsjett_ok",
                        lambda krav: float(mb) >= krav)


# ------------------------------------------------------------------ #
#  Selve feilen: valget sto fast for godt                             #
# ------------------------------------------------------------------ #

def test_cpu_valget_er_ikke_permanent(fersk_motor, monkeypatch):
    """Kjernen i R239: blir kortet ledig, skal et nytt dokument få GPU."""
    _lat_som_ledig(monkeypatch, 500)          # fullt kort ved oppstart
    monkeypatch.setattr(region_ocr, "_hent_rapid", lambda: object())
    assert region_ocr._velg_motor_for_maskinen() == "rapid"

    # Kortet blir ledig, og karantenen er over.
    _lat_som_ledig(monkeypatch, 6000)
    monkeypatch.setattr(region_ocr, "_valgt",
                        {"motor": "rapid", "tid": -10_000.0})
    monkeypatch.setattr(region_ocr, "_hent_easyocr", lambda: None)
    monkeypatch.setitem(region_ocr._easyocr, "gpu", True)

    assert region_ocr.revurder_motor() == "easy", (
        "motoren ble ikke revurdert da kortet ble ledig — det var "
        "nettopp dette som låste serveren til CPU i timevis")


def test_karantenen_hindrer_vipping(fersk_motor, monkeypatch):
    """Et ferskt valg står i karantene, selv om kortet er ledig."""
    _lat_som_ledig(monkeypatch, 6000)
    monkeypatch.setattr(region_ocr, "_valgt",
                        {"motor": "rapid", "tid": 1e18})   # nettopp satt
    assert region_ocr.revurder_motor() == "rapid"


def test_bytter_aldri_mens_et_ANNET_dokument_leses(fersk_motor, monkeypatch):
    """R6: side 1 og side 50 av samme bunke skal leses av samme modell."""
    _lat_som_ledig(monkeypatch, 6000)
    monkeypatch.setattr(region_ocr, "_valgt",
                        {"motor": "rapid", "tid": -10_000.0})
    monkeypatch.setattr(region_ocr, "_hent_easyocr", lambda: None)
    # 2 = dokumentet som spør, PLUSS ett som alt er under lesing.
    region_ocr._aapne_dokumenter[0] = 2

    assert region_ocr.revurder_motor() == "rapid", (
        "motoren ble byttet mens et annet dokument var under lesing — da "
        "leses sidene i den bunken av ulike modeller")


def test_dokumentet_som_spor_blokkerer_ikke_seg_selv(fersk_motor, monkeypatch):
    """Regresjon. Første forsøk telte opp i `dokumentlesing` FØR
    revurderingen, og vakten («er noen i gang?») stengte da ute nettopp
    det kallet den fantes for. Motoren ble aldri revurdert — feilen så
    ut som en fiks helt til den ble kjørt mot ekte dokumenter."""
    _lat_som_ledig(monkeypatch, 6000)
    monkeypatch.setattr(region_ocr, "_valgt",
                        {"motor": "rapid", "tid": -10_000.0})
    monkeypatch.setattr(region_ocr, "_hent_easyocr", lambda: None)
    monkeypatch.setitem(region_ocr._easyocr, "gpu", True)
    region_ocr._aapne_dokumenter[0] = 1        # bare den som spør

    assert region_ocr.revurder_motor() == "easy"


def test_hele_veien_gjennom_rammen(fersk_motor, monkeypatch):
    """Samme regresjon, men via `dokumentlesing` — slik
    produksjonsveien faktisk gjør det, uten å sette telleren for hånd."""
    _lat_som_ledig(monkeypatch, 6000)
    monkeypatch.setattr(region_ocr, "_valgt",
                        {"motor": "rapid", "tid": -10_000.0})
    monkeypatch.setattr(region_ocr, "_hent_easyocr", lambda: None)
    monkeypatch.setitem(region_ocr._easyocr, "gpu", True)

    with region_ocr.dokumentlesing():
        assert region_ocr._velg_motor_for_maskinen() == "easy", (
            "rammen revurderte ikke motoren — dokumentet ble lest med "
            "CPU-motoren selv om kortet var ledig")


def test_nedgraderer_aldri(fersk_motor, monkeypatch):
    """easy → rapid ville bare gitt en ubrukt modell på kortet: koden
    laster aldri EasyOCR ut igjen."""
    _lat_som_ledig(monkeypatch, 100)           # kortet er stappfullt
    monkeypatch.setattr(region_ocr, "_valgt",
                        {"motor": "easy", "tid": -10_000.0})
    assert region_ocr.revurder_motor() == "easy"


def test_easyocr_paa_cpu_er_ingen_oppgradering(fersk_motor, monkeypatch):
    """Forsvinner plassen mellom budsjettsjekken og lastingen, skal vi
    BLI på RapidOCR: EasyOCR på CPU er målt 6–8 s/side mot RapidOCRs
    1,1 s. Et bytte da ville vært en nedgradering i forkledning."""
    _lat_som_ledig(monkeypatch, 6000)
    monkeypatch.setattr(region_ocr, "_valgt",
                        {"motor": "rapid", "tid": -10_000.0})
    monkeypatch.setattr(region_ocr, "_hent_easyocr", lambda: None)
    monkeypatch.setitem(region_ocr._easyocr, "gpu", False)   # havnet på CPU

    assert region_ocr.revurder_motor() == "rapid"


def test_tvunget_motor_revurderes_ikke(fersk_motor, monkeypatch):
    """OCR_MOTOR=rapid er en beskjed fra et menneske, ikke en måling."""
    monkeypatch.setattr(region_ocr, "OCR_MOTOR", "rapid")
    monkeypatch.setattr(region_ocr, "_hent_rapid", lambda: object())
    _lat_som_ledig(monkeypatch, 8000)          # masse plass — spiller ingen rolle
    assert region_ocr.revurder_motor() == "rapid"


# ------------------------------------------------------------------ #
#  Rammen som gjør revurderingen trygg                                #
# ------------------------------------------------------------------ #

def test_rammen_teller_opp_og_ned(fersk_motor):
    assert region_ocr._aapne_dokumenter[0] == 0
    with region_ocr.dokumentlesing():
        assert region_ocr._aapne_dokumenter[0] == 1
        with region_ocr.dokumentlesing():      # to samtidige forespørsler
            assert region_ocr._aapne_dokumenter[0] == 2
    assert region_ocr._aapne_dokumenter[0] == 0


def test_rammen_teller_ned_ogsaa_naar_lesingen_feiler(fersk_motor):
    """Ellers ville én feilet forespørsel låst motoren for alltid — en
    ny variant av nøyaktig den feilen R239 retter."""
    with pytest.raises(ValueError):
        with region_ocr.dokumentlesing():
            raise ValueError("lesingen sprakk")
    assert region_ocr._aapne_dokumenter[0] == 0


def test_bare_det_forste_dokumentet_revurderer(fersk_motor, monkeypatch):
    """Dokument nummer to i en samtidig strøm skal ikke røre motoren —
    det første holder den låst."""
    kall = []
    monkeypatch.setattr(region_ocr, "revurder_motor",
                        lambda: kall.append(1))
    with region_ocr.dokumentlesing():
        with region_ocr.dokumentlesing():
            pass
    assert len(kall) == 1


def test_rammen_taaler_mange_traader(fersk_motor):
    """Telleren er delt tilstand; uten lås ville den drevet av gårde og
    motoren blitt låst eller sluppet fri på feil tidspunkt."""
    def les():
        for _ in range(50):
            with region_ocr.dokumentlesing():
                pass

    traader = [threading.Thread(target=les) for _ in range(8)]
    for t in traader:
        t.start()
    for t in traader:
        t.join()
    assert region_ocr._aapne_dokumenter[0] == 0


# ------------------------------------------------------------------ #
#  Begge leseveiene MÅ være rammet inn                                #
# ------------------------------------------------------------------ #

def test_synkron_lesing_er_rammet_inn():
    import inspect

    import dokument_api as api
    kilde = inspect.getsource(api.ocr_pdf_bytes)
    assert "dokumentlesing()" in kilde, (
        "den synkrone veien mangler dokumentrammen — da kan motoren "
        "bytte mellom to sider i samme dokument")


def test_jobbveien_er_rammet_inn_for_policyen_fryses():
    """Rekkefølgen er ikke en detalj: fryses policyen først, ville
    rammen straks kunnet endre motoren under den."""
    import inspect

    import dokument_api as api
    kilde = inspect.getsource(api._jobb_arbeider)
    assert "dokumentlesing()" in kilde, "jobbveien mangler dokumentrammen"
    assert kilde.index("dokumentlesing()") < kilde.index("los_policy()"), (
        "rammen må åpnes FØR policyen fryses")
    assert "dokramme.close()" in kilde, (
        "rammen lukkes ikke — motoren ville stått låst for alle "
        "senere jobber")


def test_per_side_valget_er_stabilt(fersk_motor, monkeypatch):
    """`_velg_motor_for_maskinen` leses PER SIDE. Uansett hvor mye tid
    som går og hvor ledig kortet blir, må den svare det samme — ellers
    kan motoren bytte mellom side 3 og side 4 i samme dokument.

    Bare `revurder_motor` får endre valget, og den kalles bare ved
    dokumentskiller."""
    _lat_som_ledig(monkeypatch, 500)
    monkeypatch.setattr(region_ocr, "_hent_rapid", lambda: object())
    assert region_ocr._velg_motor_for_maskinen() == "rapid"

    # Kortet blir ledig, og karantenetiden er for lengst passert.
    _lat_som_ledig(monkeypatch, 8000)
    region_ocr._valgt["tid"] = -10_000.0
    monkeypatch.setattr(region_ocr, "_hent_easyocr", lambda: None)
    monkeypatch.setitem(region_ocr._easyocr, "gpu", True)

    assert region_ocr._velg_motor_for_maskinen() == "rapid", (
        "per-side-oppslaget byttet motor av seg selv — da leses sidene i "
        "ett og samme dokument av ulike modeller")

"""
Tester for den MÅLTE samtidighetsgrensen (skript/dokument_api.py).

Grensen skal ikke være et fast tall, men følge maskinen: får serveren
flere kort, mer minne eller flere kjerner, skal den ta imot flere
klienter av seg selv. Og den skal aldri love mer enn den knappeste
ressursen bærer — å slippe inn flere enn maskinen tåler gir ikke
gjennomstrømning, bare minnepress og lengre kø for alle.

Målefunksjonene hentes ut av kildefila og kjøres isolert, så testene
verken starter serveren eller laster modeller.
"""
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, ".")

from delt import maskinprofil                                   # noqa: E402

_KILDE = open("skript/dokument_api.py", encoding="utf-8").read()


def _uttrykk_etter(navn):
    """Verdien til `navn = …`, også når den går over flere linjer.

    Leste før BARE første linje. Det holdt så lenge alle konstantene var
    ettlinjede, og brøt i det øyeblikket en av dem ikke var det:
    `RESERVERT_INTERAKTIV` (ADR-0007) er tre linjer, og utdraget ga
    «SyntaxError: '(' was never closed» — en feil som ser ut som om
    KODEN er gal, mens det var lesningen av den som var det.

    Nå leses det til parentesene går opp."""
    rest = _KILDE.split(navn + " = ", 1)[1]
    ut, dybde = [], 0
    for linje in rest.splitlines():
        ut.append(linje)
        dybde += linje.count("(") - linje.count(")")
        if dybde <= 0:
            break
    return "\n".join(ut)


def _last_kapasitetskode():
    """Kjører kapasitetsdelen av dokument_api i et eget navnerom."""
    start = _KILDE.index("def _gpu_ressurser")
    slutt = _KILDE.index("_kapasitet_port = _Kapasitetsport()")
    # `maskinprofil` med: utdraget inneholder nå konstantlinjer som slår
    # opp i profilen (R190, ADR-0007), og de kjøres på nytt av exec-en
    # under. Uten navnet her feiler utdraget med NameError.
    ns = {"os": os, "threading": threading, "time": time,
          "maskinprofil": maskinprofil}
    for navn in ("SAMTIDIGE_PER_GPU", "SAMTIDIGE_UTEN_GPU", "RAM_PER_JOBB_MB",
                 "VRAM_PER_JOBB_MB", "MIN_SAMTIDIGE", "MAKS_SAMTIDIGE_TAK",
                 "KAPASITET_MAAL_S",
                 # ADR-0007: porten deler kapasiteten i to baner, og
                 # `_tak_for` slår opp i denne. Uten den her feiler
                 # utdraget med NameError — ikke fordi koden er gal,
                 # men fordi navnerommet er ufullstendig.
                 "RESERVERT_INTERAKTIV"):
        linje = _uttrykk_etter(navn)
        # `maskinprofil` med: takene hentes nå fra maskinprofilen (R190),
        # så konstantlinjene kan referere den. Profilen leser miljøet
        # selv, og gir ankermaskinens verdier her.
        ns[navn] = eval(linje, {"os": os, "int": int, "float": float,
                                "maskinprofil": maskinprofil})
    exec(_KILDE[start:slutt], ns)
    return ns


@pytest.fixture
def kap():
    return _last_kapasitetskode()


def _maal(ns, kort, vram_mb, kjerner, ram_mb):
    ns["_gpu_ressurser"] = lambda: (kort, vram_mb)
    ns["_ledig_ram_mb"] = lambda: ram_mb
    ns["os"] = type("O", (), {"cpu_count": staticmethod(lambda: kjerner),
                              "environ": {}})
    return ns["mal_kapasitet"]()


# ---------- grensen følger maskinvaren ----------
def test_flere_kort_gir_flere_samtidige(kap):
    """Kjernen i det hele: dobler du kortene, dobles kapasiteten."""
    ett = _maal(kap, 1, 20000, 64, 256000)["grense"]
    to = _maal(kap, 2, 40000, 64, 256000)["grense"]
    fire = _maal(kap, 4, 80000, 64, 256000)["grense"]
    assert to == ett * 2
    assert fire == ett * 4


def test_stor_server_tar_mange_flere_enn_liten(kap):
    liten = _maal(kap, 1, 7098, 12, 8842)["grense"]
    stor = _maal(kap, 8, 80000, 128, 512000)["grense"]
    assert stor >= liten * 4


def test_knappeste_ressurs_bestemmer(kap):
    """Mange kort hjelper ikke hvis maskinen mangler kjerner."""
    resultat = _maal(kap, 8, 80000, 2, 512000)
    assert resultat["binder"] == "cpu"
    assert resultat["grense"] <= 2


def test_lite_ledig_ram_binder(kap):
    resultat = _maal(kap, 4, 40000, 64, 900)
    assert resultat["binder"] == "ram"


def test_lite_vram_binder_selv_med_mange_kort(kap):
    """Kortene kan være mange, men nesten fulle — da teller VRAM-et."""
    resultat = _maal(kap, 4, 1400, 64, 256000)
    assert resultat["binder"] == "gpu"
    assert resultat["grense"] < 4 * kap["SAMTIDIGE_PER_GPU"]


def test_maskin_uten_gpu_faar_fortsatt_kapasitet(kap):
    """Ren CPU-maskin skal virke — bare med et lavere tak."""
    resultat = _maal(kap, 0, 0, 64, 128000)
    assert resultat["grense"] >= 2


# ---------- grenseverdier ----------
def test_aldri_under_gulvet(kap):
    """En minimal maskin skal fortsatt kunne betjene noen — ellers er
    tjenesten død i stedet for treg."""
    resultat = _maal(kap, 0, 0, 1, 200)
    assert resultat["grense"] >= kap["MIN_SAMTIDIGE"]


def test_aldri_over_taket(kap):
    """Et urimelig svar fra maskinvaremålingen skal ikke gi tusenvis av
    tråder — taket er et sikkerhetsnett."""
    resultat = _maal(kap, 999, 9_000_000, 4096, 90_000_000)
    assert resultat["grense"] <= kap["MAKS_SAMTIDIGE_TAK"]


def test_maalingen_rapporteres_saa_tallet_kan_begrunnes(kap):
    resultat = _maal(kap, 2, 20000, 32, 64000)
    assert set(resultat["maalt"]) == {"gpu_kort", "gpu_ledig_mb",
                                      "cpu_kjerner", "ram_ledig_mb"}
    assert set(resultat["fra"]) == {"gpu", "cpu", "ram"}
    assert resultat["binder"] in resultat["fra"]


# ---------- porten ----------
def test_porten_slipper_inn_opp_til_grensen(kap):
    port = kap["_Kapasitetsport"]()
    port._kapasitet = {"grense": 3, "binder": "test", "maalt": {}, "fra": {}}
    port._maalt_ved = time.monotonic() + 10_000     # ikke mål på nytt
    assert all(port.ta(0.1) for _ in range(3))
    assert port.ta(0.1) is False                    # full
    port.slipp()
    assert port.ta(0.1) is True                     # plass igjen


def test_porten_fanger_opp_oekt_kapasitet_uten_omstart(kap):
    """Poenget med å måle på nytt: setter du inn et kort mens serveren
    kjører, skal ventende klienter slippe inn — ikke vente på omstart."""
    port = kap["_Kapasitetsport"]()
    port._kapasitet = {"grense": 1, "binder": "test", "maalt": {}, "fra": {}}
    port._maalt_ved = time.monotonic() + 10_000
    assert port.ta(0.1) is True
    assert port.ta(0.1) is False                    # full ved grense 1

    def voks():
        time.sleep(0.3)
        with port._las:
            port._kapasitet = {"grense": 5, "binder": "test",
                               "maalt": {}, "fra": {}}
            port._las.notify_all()

    threading.Thread(target=voks, daemon=True).start()
    assert port.ta(3.0) is True                     # slapp inn etter vekst


def test_porten_teller_riktig_under_samtidig_bruk(kap):
    """Ingen lekkasje av plasser: 40 tråder som tar og slipper skal ende
    på null i arbeid."""
    port = kap["_Kapasitetsport"]()
    port._kapasitet = {"grense": 4, "binder": "test", "maalt": {}, "fra": {}}
    port._maalt_ved = time.monotonic() + 10_000
    topp = {"n": 0}
    las = threading.Lock()

    def arbeid():
        if port.ta(5.0):
            with las:
                port_inne = port._inne
                topp["n"] = max(topp["n"], port_inne)
            time.sleep(0.01)
            port.slipp()

    traader = [threading.Thread(target=arbeid) for _ in range(40)]
    for t in traader:
        t.start()
    for t in traader:
        t.join()
    assert port._inne == 0
    assert topp["n"] <= 4          # grensen ble aldri overskredet

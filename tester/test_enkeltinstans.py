"""Én server, én vakthund, ett panel.

Målt før fiksen, empirisk og ikke teoretisk: TO Python-servere bandt
SAMME port samtidig, begge sto oppe, og alle forespørslene gikk til den
ene uten at noe sa hvilken.

Årsaken er at Pythons `HTTPServer` setter `allow_reuse_address = 1`. På
Unix er det riktig — det omgår TIME_WAIT ved omstart. På Windows betyr
SO_REUSEADDR noe annet: den TILLATER en ny socket å binde en port som
allerede er i bruk.

Konsekvensen er ikke bare forvirring. Server nummer to laster Borealis
(~5,7 GB) på det samme 8 GB-kortet, og da har ingen av dem plass til
OCR — kortet er prosjektets trangeste ressurs.

Vakthunden hadde en `svarer()`-sjekk, men det er «sjekk, så handle» og
ikke en lås: starter to vakthunder mens API-et er nede, ser BEGGE en død
server og starter hver sin. Og vakthunden er det verste stedet å ha to
av, fordi den er bygget for å RESTARTE.

Panelet er den eneste inngangen brukeren har, så et dobbeltklikk på
snarveien er den mest sannsynlige veien til alt dette.
"""
import os
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))

from delt import enkeltinstans

PY = os.path.join(ROT, ".pyruntime", "python.exe")


# ------------------------------------------------------------------ #
#  1. Serveren nekter å være nummer to på porten                       #
# ------------------------------------------------------------------ #

def test_serveren_gjenbruker_IKKE_adressen():
    import dokument_api as api
    assert api.EnServer.allow_reuse_address == 0, (
        "allow_reuse_address er slått på igjen — på Windows lar den en "
        "ny server kapre porten til en som allerede kjører")


def test_serveren_brukes_faktisk_i_main():
    import inspect

    import dokument_api as api
    kilde = inspect.getsource(api.main)
    assert "EnServer(" in kilde
    assert "ThreadingHTTPServer((" not in kilde, (
        "main bygger serveren direkte igjen, utenom EnServer")


def test_to_servere_kan_IKKE_binde_samme_port():
    """Selve regresjonen, målt — ikke utledet fra en flaggverdi."""
    from http.server import BaseHTTPRequestHandler

    import dokument_api as api

    class Stille(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    port = 8647
    forste = api.EnServer(("127.0.0.1", port), Stille)
    try:
        with pytest.raises(OSError):
            api.EnServer(("127.0.0.1", port), Stille)
    finally:
        forste.server_close()


def test_porten_kan_bindes_paa_NYTT_etter_at_serveren_stengte():
    """Speilet, og det som avgjorde at fiksen er trygg: vakthunden
    restarter API-et, så en port som ikke slipper taket ville gjort
    vakthunden verdiløs."""
    from http.server import BaseHTTPRequestHandler

    import dokument_api as api

    class Stille(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    port = 8648
    a = api.EnServer(("127.0.0.1", port), Stille)
    threading.Thread(target=a.serve_forever, daemon=True).start()
    urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read()
    a.shutdown()
    a.server_close()
    b = api.EnServer(("127.0.0.1", port), Stille)   # skal ikke kaste
    b.server_close()


# ------------------------------------------------------------------ #
#  2. Låsen selv                                                       #
# ------------------------------------------------------------------ #

def test_andre_forsok_nektes():
    a = enkeltinstans.ta("test-enkelt")
    try:
        assert a is not None
        assert enkeltinstans.ta("test-enkelt") is None
    finally:
        if a:
            a.frigi()


def test_laasen_slippes_ved_frigi():
    a = enkeltinstans.ta("test-frigi")
    assert a is not None
    a.frigi()
    b = enkeltinstans.ta("test-frigi")
    assert b is not None
    b.frigi()


def test_ulike_navn_stenger_ikke_hverandre():
    a = enkeltinstans.ta("test-a")
    b = enkeltinstans.ta("test-b")
    try:
        assert a is not None and b is not None
    finally:
        for x in (a, b):
            if x:
                x.frigi()


def test_to_nav_mapper_paa_samme_maskin_stenger_ikke_hverandre():
    """Prosjektstien er en del av låsenavnet. To kopier av mappa er to
    ULIKE installasjoner, og den ene skal ikke hindre den andre."""
    nokkel = enkeltinstans._prosjektnokkel()
    assert nokkel
    assert nokkel == "".join(c if c.isalnum() else "_"
                             for c in ROT.lower())


BARN = """
import sys, time
sys.path.insert(0, r"{rot}")
from delt import enkeltinstans
laas = enkeltinstans.ta("test-drap")
print("FIKK" if laas else "nektet", flush=True)
if laas:
    time.sleep(120)
"""


@pytest.mark.skipif(not os.path.exists(PY), reason="prosjekt-Python mangler")
def test_laasen_frigis_naar_prosessen_DREPES():
    """Grunnen til at dette er en kjernemutex og ikke en låsefil.

    API-et dør brått: `0xC0000005` fra llama.cpp/CUDA (R122). En låsefil
    ville blitt liggende, og neste oppstart nektet for alltid av en lås
    ingen holder. Kjernen frigjør mutexen uansett hvordan prosessen
    døde."""
    skript = os.path.join(ROT, "data", "test_barn_laas.py")
    os.makedirs(os.path.dirname(skript), exist_ok=True)
    with open(skript, "w", encoding="utf-8") as f:
        f.write(BARN.format(rot=ROT))
    try:
        p = subprocess.Popen([PY, skript], stdout=subprocess.PIPE, text=True)
        try:
            assert p.stdout.readline().strip() == "FIKK"
            assert enkeltinstans.ta("test-drap") is None, (
                "vi fikk låsen mens barnet holder den")
            p.kill()
            p.wait(timeout=10)
        finally:
            if p.poll() is None:
                p.kill()
        for _ in range(20):                     # kjernen rydder ikke alltid
            time.sleep(0.1)                     # i samme øyeblikk
            etter = enkeltinstans.ta("test-drap")
            if etter:
                etter.frigi()
                break
        else:
            pytest.fail("låsen ble liggende etter at prosessen ble drept")
    finally:
        if os.path.exists(skript):
            os.remove(skript)


# ------------------------------------------------------------------ #
#  3. Alle tre inngangene tar den                                      #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("fil,navn", [
    ("skript/vakthund.py", "vakthund"),
    ("skript/api_klient_gui.py", "kontrollpanel"),
])
def test_inngangen_tar_laasen(fil, navn):
    kilde = open(os.path.join(ROT, fil), encoding="utf-8").read()
    kode = "\n".join(l.split("#")[0] for l in kilde.splitlines())
    assert "enkeltinstans" in kode, f"{fil} tar ingen lås"
    assert f'ta("{navn}")' in kode, f"{fil} tar ikke låsen «{navn}»"


def test_panelet_sier_fra_i_et_VINDU():
    """Panelet kjøres med pythonw, uten konsoll. En print til stderr
    forsvinner sporløst, og brukeren ville bare sett at ingenting
    skjedde."""
    kilde = open(os.path.join(ROT, "skript", "api_klient_gui.py"),
                 encoding="utf-8").read()
    etter = kilde[kilde.index('ta("kontrollpanel")'):]
    assert "messagebox" in etter[:1200]


def test_vakthunden_avslutter_PENT_naar_en_annen_holder_laasen():
    """Exitkode 0, ikke en feil: at det allerede går en vakthund er
    normaltilstanden når panelet startes to ganger, ikke et problem
    noen skal lete etter i loggen."""
    kilde = open(os.path.join(ROT, "skript", "vakthund.py"),
                 encoding="utf-8").read()
    etter = kilde[kilde.index('ta("vakthund")'):]
    assert "sys.exit(0)" in etter[:600]

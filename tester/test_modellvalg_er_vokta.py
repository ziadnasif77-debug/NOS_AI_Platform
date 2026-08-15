"""
Serveren skal ikke plukke opp en ødelagt modellfil (R202).

`_finn_gguf()` valgte den NYESTE .gguf-fila i modellmappa. En avbrutt
nedlasting er alltid den nyeste, og llama.cpp svarer på en ødelagt
modell med et nativt krasj uten traceback — den dyreste feilen å finne.

Skjevheten som gjorde det farlig: `bytt_modell.py` sjekket signaturen
allerede, men den er den OVERVÅKEDE veien — et menneske står og ser på.
Veien vi dokumenterer i README, «legg fila i mappa og restart», hadde
ingen sjekk. Vakten manglet nettopp der ingen ser etter.

Målt tilfelle: modeller/borealis-kandidat/…Q4_K_M.gguf, 6,5 MB, første
fire bytene 00 00 00 00 i stedet for «GGUF».
"""
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api as api


GGUF_HODE = b"GGUF" + b"\x00" * 60

# Testene skriver ekte filer til disk. Med de EKTE størrelsene (3,9 GB
# per «modell», åtte tester) ble det titalls gigabyte skriving og
# nesten fire minutter på en mekanisk disk — for å prøve en
# størrelsessammenligning. Grensen settes derfor lavt i testen, og selve
# tallet prøves for seg i test_terskelen_skiller_disk_fra_ssd.
GRENSE_MB = 1
STOR_MB = 2
LITEN_MB = 0.1


def _lag(mappe, navn, mb, hode=GGUF_HODE):
    sti = mappe / navn
    with open(sti, "wb") as f:
        if hode:
            f.write(hode)
        f.truncate(int(mb * 1024 * 1024))
    return sti


@pytest.fixture
def modellmappe(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "BOREALIS_GGUF_MAPPE", str(tmp_path))
    monkeypatch.setattr(api, "MINSTE_MODELL_MB", GRENSE_MB)
    monkeypatch.delenv("BOREALIS_GGUF", raising=False)
    return tmp_path


# ------------------------------------------------------------------ #
#  Selve tilfellet                                                    #
# ------------------------------------------------------------------ #

def test_avbrutt_nedlasting_velges_ikke_selv_om_den_er_nyest(modellmappe):
    """Kjernen: den ødelagte fila er NYERE, altså den «nyeste fil
    vinner»-regelen ville tatt nettopp den."""
    ekte = _lag(modellmappe, "ekte-Q8.gguf", STOR_MB)
    os.utime(ekte, (1000, 1000))
    ødelagt = _lag(modellmappe, "avbrutt-Q4.gguf", LITEN_MB,
                   hode=b"\x00\x00\x00\x00")
    os.utime(ødelagt, (9000, 9000))

    assert os.path.basename(api._finn_gguf()) == "ekte-Q8.gguf"


def test_halvlastet_med_gyldig_signatur_stoppes_av_storrelsen(modellmappe):
    """En nedlasting som rakk lenger HAR «GGUF» først. Da er det bare
    størrelsen som skiller den fra en ferdig modell."""
    ekte = _lag(modellmappe, "ekte-Q8.gguf", STOR_MB)
    os.utime(ekte, (1000, 1000))
    halv = _lag(modellmappe, "halv-Q4.gguf", LITEN_MB)      # gyldig signatur
    os.utime(halv, (9000, 9000))

    assert os.path.basename(api._finn_gguf()) == "ekte-Q8.gguf"


def test_ingen_brukbar_modell_gir_tom_streng_ikke_en_odelagt_fil(modellmappe):
    """Finnes BARE en ødelagt fil, skal svaret være «ingen modell» —
    ikke den ødelagte. Da melder oppstarten mangel i stedet for å
    krasje nativt."""
    # 6 MB med vilje: over størrelsesgrensen i denne testen, så det er
    # SIGNATUREN som må ta den — slik den ekte fila på 6,5 MB ble tatt.
    _lag(modellmappe, "avbrutt.gguf", 6, hode=b"\x00\x00\x00\x00")
    assert api._finn_gguf() == ""


# ------------------------------------------------------------------ #
#  Vakten skal ikke ta noe den ikke skal                              #
# ------------------------------------------------------------------ #

def test_en_ekte_modell_velges_fortsatt(modellmappe):
    _lag(modellmappe, "borealis-Q8.gguf", STOR_MB)
    assert os.path.basename(api._finn_gguf()) == "borealis-Q8.gguf"


def test_nyeste_ekte_modell_vinner_som_for(modellmappe):
    """Regelen som gjelder skal være uendret for gyldige filer."""
    gammel = _lag(modellmappe, "gammel-Q8.gguf", STOR_MB)
    os.utime(gammel, (1000, 1000))
    ny = _lag(modellmappe, "ny-Q8.gguf", STOR_MB)
    os.utime(ny, (9000, 9000))

    assert os.path.basename(api._finn_gguf()) == "ny-Q8.gguf"


def test_mmproj_hoppes_over_som_for(modellmappe):
    """Synsprojektorer er ikke språkmodeller."""
    _lag(modellmappe, "ekte-Q8.gguf", STOR_MB)
    mm = _lag(modellmappe, "mmproj-stor.gguf", STOR_MB)
    os.utime(mm, (9000, 9000))

    assert os.path.basename(api._finn_gguf()) == "ekte-Q8.gguf"


def test_eksplisitt_valg_overproves_ikke(modellmappe, monkeypatch):
    """Setter et menneske BOREALIS_GGUF, har det valgt med vilje. Da
    skal koden ikke stille bytte til noe annet — den skal gjøre som den
    får beskjed om, og la oppstarten melde fra hvis fila ikke duger."""
    monkeypatch.setenv("BOREALIS_GGUF", "jeg-valgte-denne.gguf")
    assert api._finn_gguf().endswith("jeg-valgte-denne.gguf")


def test_tom_mappe_gir_tom_streng(modellmappe):
    assert api._finn_gguf() == ""


# ------------------------------------------------------------------ #
#  Lastetiden skal kunne leses av loggen (R201)                       #
# ------------------------------------------------------------------ #

def test_lastetiden_maales_og_skrives_ut():
    """«Hvorfor tar modellen så lang tid å starte?» var et spørsmål
    ingen kunne besvare fra loggen: `verbose=False` demper llama.cpp
    sin egen timing, så svaret måtte utledes av disktypen utenfra."""
    import inspect
    kilde = inspect.getsource(api._last_borealis_bakgrunn)
    assert "start_lasting" in kilde, "lastetiden måles ikke"
    assert "MB/s" in kilde, "lesefarten skrives ikke ut"
    assert "TREG_LASTING_MB_PER_S" in kilde, (
        "ingen terskel som sier fra at det er DISKEN som er treg")


def test_terskelen_skiller_disk_fra_ssd():
    """Under 200 MB/s er det en mekanisk disk eller en opptatt disk —
    en SSD gir 500+, en NVMe 1500+."""
    assert 100 <= api.TREG_LASTING_MB_PER_S <= 400

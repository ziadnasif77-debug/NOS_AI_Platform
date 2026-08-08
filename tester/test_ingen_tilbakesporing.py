"""Uttrekket skal vokse LINEÆRT med teksten (R162).

To mønstre var kvadratiske, og begge utløses av det samme: én lang
linje med tall skilt av bindestrek eller mellomrom. Det er ikke et
konstruert angrep — det er en tabellrad eller et referansefelt som OCR
leser som én linje.

    e-post              10k 0,39 s → 20k 1,48 → 40k 6,13 → 80k 31,63 s
    strukturert_uttrekk 80k: 32,20 s

Firedobling per dobling. `MAKS_BYTES` er 200 MB og ingen av veiene har
en tekstgrense, så ett kall kunne binde en arbeidstråd i minutter — og
tråden holder en kapasitetsplass mens den står der.

Vakten måler VEKSTFAKTOREN, ikke absolutt tid. Absolutte grenser blir
røde på en travel maskin og grønne på en rask; en kvadratisk kurve
derimot er kvadratisk overalt.
"""
import os
import sys
import time

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)

from delt import tekstuttrekk as tu


def _tid(fn, *a):
    t0 = time.perf_counter()
    fn(*a)
    return time.perf_counter() - t0


def _vekst(fn, lag, n1, n2):
    """Faktoren tiden vokser med når inndata dobles."""
    t1 = _tid(fn, lag(n1))
    t2 = _tid(fn, lag(n2))
    # Gulv på 1 ms: under det måler vi klokkeoppløsning, ikke kode.
    return t2 / max(t1, 0.001)


BINDESTREKER = lambda n: "1-" * n
TREGRUPPER = lambda n: "1" + " 000" * n


def test_epostmonsteret_er_ikke_kvadratisk():
    """`\\b[\\w.+-]+@…` ga ett startpunkt per TEGN inne i et
    sammenhengende løp, og slukte hele løpet før den sporet tilbake og
    lette etter en «@» som ikke finnes."""
    faktor = _vekst(tu._EPOST.search, BINDESTREKER, 20000, 40000)
    assert faktor < 3.0, (
        f"tiden ble {faktor:.1f}× ved dobling — kvadratisk er ~4×, "
        f"lineært er ~2×")


def test_hele_uttrekket_er_ikke_kvadratisk():
    """Den som faktisk rammer en forespørsel."""
    faktor = _vekst(tu.strukturert_uttrekk, BINDESTREKER, 20000, 40000)
    assert faktor < 3.0, f"strukturert_uttrekk vokste {faktor:.1f}× ved dobling"


def test_belopsmonsteret_er_ikke_kvadratisk():
    """`(?:[ .][\\dOo]{3})*` er grådig, og mønsteret etter den kan
    feile — da spores det tilbake gruppe for gruppe fra hvert
    startpunkt."""
    faktor = _vekst(tu.finn_belop, TREGRUPPER, 1600, 3200)
    assert faktor < 3.0, f"finn_belop vokste {faktor:.1f}× ved dobling"


# ------------------------------------------------------------------ #
#  Motprøven: grensene skal ikke ha kostet oss noe ekte               #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("tekst,ventet", [
    ("Kontakt ola.nordmann@nav.no", ["ola.nordmann@nav.no"]),
    ("Kort: a@b.no", ["a@b.no"]),
    ("Med bindestrek: ola-kari@nav-it.no", ["ola-kari@nav-it.no"]),
    ("Med pluss: ola+jobb@example.co.uk", ["ola+jobb@example.co.uk"]),
])
def test_ekte_epostadresser_finnes_fortsatt(tekst, ventet):
    assert tu.finn_alle_eposter(tekst) == ventet


@pytest.mark.parametrize("tekst,ventet", [
    ("Sum kr 1 234 567,89", 1234567.89),
    ("Belop 4 812,00 kroner", 4812.0),
    ("kr 23,50", 23.5),
    ("NOK 1.234.567,89", 1234567.89),
])
def test_ekte_belop_finnes_fortsatt(tekst, ventet):
    assert tu.finn_belop(tekst) == ventet

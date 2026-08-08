"""CI får ikke nevne filer som ikke finnes (R164).

Den forrige fila refererte til FIRE ting som var slettet sammen med en
gammel Postgres/K8s-arkitektur:

    skript/init_db.py
    tester/test_integrasjon_lokal.py
    docker-compose.yml
    k8s/

Verst var K8s-steget. `Path("k8s").glob("*.yaml")` på en mappe som ikke
finnes kaster ikke — den gir en TOM generator. Løkken kjørte aldri, det
eneste `assert`-et lå INNE i løkken, og siste linje printet «alle
k8s-manifester er gyldig YAML». Steget ble grønt uten å ha validert
noe som helst.

Det er den samme feilklassen som resten av denne gjennomgangen fant om
og om igjen: en garanti som ikke finnes, men ser ut som den gjør. Den er
farligere enn et manglende steg, for et manglende steg SES.
"""
import os
import pathlib
import re

import pytest

ROT = pathlib.Path(__file__).resolve().parent.parent
CI = ROT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def innhold():
    if not CI.exists():
        pytest.fail(f"CI-fila mangler: {CI}")
    return CI.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def kjorbart(innhold):
    """CI-fila UTEN kommentarlinjer.

    Fila FORKLARER hva den erstattet — den nevner `init_db.py`, `k8s/`
    og resten i en kommentar, fordi neste leser ellers ikke vet hvorfor
    stegene mangler. En vakt som leser hele fila ville slått ned på den
    forklaringen. Det er samme feil som vakten skal fange: å måle
    teksten i stedet for det som kjøres."""
    return "\n".join(l for l in innhold.splitlines()
                     if not l.lstrip().startswith("#"))


def test_ci_nevner_bare_filer_som_finnes(innhold):
    """Selve vakten, og den kjøres også som første steg I CI — men her
    også, så en utvikler ser det før det pushes."""
    stier = set(re.findall(r"(?:python|-m pytest)\s+([\w./\\-]+\.py)", innhold))
    stier |= set(re.findall(r"--ignore=([\w./\\-]+)", innhold))
    borte = sorted(s for s in stier if not (ROT / s).exists())
    assert not borte, f"CI refererer til filer som ikke finnes: {borte}"


def test_vakten_maaler_noe(innhold):
    """Speilet: uten dette ville testen over vært grønn om regexen
    sluttet å finne noe som helst."""
    stier = set(re.findall(r"(?:python|-m pytest)\s+([\w./\\-]+\.py)", innhold))
    assert len(stier) >= 3, f"fant bare {stier} — måler vakten noe?"


@pytest.mark.parametrize("dodt", [
    "init_db.py", "test_integrasjon_lokal.py", "docker-compose", "k8s/",
    "postgres", "redis",
])
def test_den_dode_arkitekturen_er_borte(kjorbart, dodt):
    """De fire tingene, pluss tjenestene de hang på — målt på det som
    KJØRER, ikke på kommentaren som forklarer hvorfor de er borte."""
    assert dodt.lower() not in kjorbart.lower(), (
        f"CI nevner fortsatt «{dodt}» fra en arkitektur som er slettet")


def test_hoppene_er_synlige(innhold):
    """`-rs` skriver ut hvert eneste hopp med grunn. Uten den er et
    hopp visuelt identisk med en grønn kjøring i oppsummeringen.

    Kravet gjelder HOVEDSTEGET, ikke fila som helhet: `-rs` står også i
    de små, navngitte stegene, så et globalt søk var grønt selv når
    hovedkjøringen mistet flagget."""
    hoved = [l for l in innhold.splitlines()
             if "pytest tester/ -q" in l and "--junitxml" in l]
    assert hoved, "fant ikke hovedteststeget i CI"
    for linje in hoved:
        assert "-rs" in linje, (
            f"hovedsteget viser ikke hvilke tester som hoppes over: "
            f"{linje.strip()}")


def test_hoppbudsjettet_finnes(innhold):
    """Målt: på en frisk klone hopper 28 tester over fordi de leser fra
    data/, som er gitignorert. På utviklermaskinen hopper null. Uten et
    budsjett er det tallet usynlig for alle."""
    assert "Hoppbudsjett" in innhold
    assert "BUDSJETT" in innhold


def test_suksessmeldinger_oppgir_et_ANTALL(kjorbart):
    """Mønsteret som gjorde K8s-steget grønt: alt bevisarbeidet lå INNE
    i en løkke som kunne ha null gjennomløp, og suksessmeldingen sto
    utenfor. «alle k8s-manifester er gyldig YAML» over NULL filer er
    ikke en sannhet, det er et fravær som later som.

    Regelen: en suksessmelding fra et steg som teller noe, må oppgi
    ANTALLET. Et tall kan ikke lyve på den måten — 0 er synlig."""
    for linje in kjorbart.splitlines():
        s = linje.strip()
        if not s.startswith("print("):
            continue
        if "alle " not in s.lower():
            continue
        assert re.search(r"\{[^}]*\}", s), (
            f"suksessmelding uten antall — den kan være sann over null "
            f"ting: {s}")

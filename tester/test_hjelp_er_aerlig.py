"""`/hjelp` lover ikke ruter som ikke finnes (R157).

`/hjelp` er ROTA — det første en integrator leser, før OpenAPI og før
README. Den annonserte `POST /analyser`, `POST /uttrekk` og
`POST /fyll_skjema` med fyldige beskrivelser. Ingen av dem hadde en gren
i ruteren. README hadde rett hele veien: de ble fjernet. Det var
serveren som løy om seg selv.

HVORFOR INGEN VAKT SÅ DET
`test_openapi_dekker_rutene` vokter ÉN retning, og sier det selv:
«legger noen til en rute uten å dokumentere den, feiler testen». Den
motsatte — å dokumentere en rute som ikke finnes — var uvoktet. Og
`/hjelp`-nyttelasten lå ikke i noen test i det hele tatt.

R144 krever at spesifikasjonen lover det API-et faktisk gjør. Ånden var
brutt gjennom en dør regelen ikke nevnte.
"""
import inspect
import os
import re
import sys

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))

import dokument_api as api


def _lovede_ruter():
    """Rutene `/hjelp` annonserer, som (metode, sti)."""
    kilde = inspect.getsource(api.Handler._do_get_intern)
    start = kilde.index('"endepunkter"')
    slutt = kilde.index("},", start)
    return {(m.group(1), m.group(2)) for m in re.finditer(
        r'"(GET|POST) (/[^"]*)":', kilde[start:slutt])}


def _ekte_ruter():
    """Stiene ruteren FAKTISK har grener for."""
    ut = set()
    for metode, navn in (("GET", "_do_get_intern"),
                         ("POST", "_do_post_intern")):
        kilde = inspect.getsource(getattr(api.Handler, navn))
        for m in re.finditer(r'sti == "(/[^"]*)"', kilde):
            ut.add((metode, m.group(1)))
        for m in re.finditer(r'sti\.startswith\("(/[^"]*)"\)', kilde):
            ut.add((metode, m.group(1).rstrip("/")))
    ut.add(("GET", ""))
    ut.add(("GET", "/hjelp"))
    return ut


def _passer(lovet, ekte):
    """«/jobb/<id>/tekst» dekkes av grenen «/jobb/». Sammenlign på
    prefiks, ikke på likhet — ellers ville vakten krevd at ruteren
    skrev ut hver eneste variant."""
    metode, sti = lovet
    return any(m == metode and (s == sti or (s and sti.startswith(s)))
               for m, s in ekte)


def test_hjelp_lover_ingen_rute_som_ikke_finnes():
    ekte = _ekte_ruter()
    spokelser = sorted(f"{m} {s}" for m, s in _lovede_ruter()
                       if not _passer((m, s), ekte))
    assert not spokelser, (
        "/hjelp annonserer ruter ruteren ikke har: " + ", ".join(spokelser))


def test_de_tre_fjernede_endepunktene_er_borte_overalt():
    """README sier de er fjernet. Nå sier serveren det samme."""
    hjelp = inspect.getsource(api.Handler._do_get_intern)
    for sti in ("/analyser", "/uttrekk", "/fyll_skjema"):
        assert f'"POST {sti}"' not in hjelp, f"{sti} står fortsatt i /hjelp"


def test_vakten_maaler_noe_i_det_hele_tatt():
    """Speilet. Uten dette ville testen over vært grønn om
    `_lovede_ruter` sluttet å finne noe som helst."""
    lovet = _lovede_ruter()
    assert len(lovet) >= 8, f"fant bare {len(lovet)} lovede ruter"
    assert ("POST", "/dokument") in lovet
    assert ("POST", "/sladd") in lovet


# Ruter som med vilje IKKE står i lista: de er infrastruktur, ikke
# noe en integrator kaller for å få gjort en jobb.
UTELATT_MED_VILJE = {
    ("GET", "/hjelp"), ("GET", ""), ("GET", "/openapi.json"),
    ("GET", "/statisk"), ("GET", "/dokumentasjon"), ("GET", "/docs"),
    ("GET", "/innsyn"),                 # dekkes av POST /innsyn-teksten
    ("POST", "/dokument/operasjoner"),  # beskrevet inne i POST /dokument
}


def test_hjelp_fortier_ingen_rute_som_finnes():
    """Den ANDRE retningen. `/sladd` — selve sladdeendepunktet — sto
    ikke i lista i det hele tatt, og en integrator som leser rota ville
    aldri vite at det fantes. Et hull i den retningen lekker ingenting,
    men gjør rota misvisende på samme måte."""
    lovet = _lovede_ruter()
    fortiet = sorted(
        f"{m} {s}" for m, s in _ekte_ruter()
        if (m, s) not in UTELATT_MED_VILJE
        and not any(lm == m and ls.startswith(s) for lm, ls in lovet))
    assert not fortiet, (
        "ruteren har ruter /hjelp ikke nevner: " + ", ".join(fortiet))

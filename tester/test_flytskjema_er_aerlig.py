"""Flytskjemaet får ikke peke på dører som ikke finnes (R175).

Skjemaet er det FØRSTE en ny person ser. En feil der sprer seg raskere
enn en feil i koden, fordi et kart blir trodd uten å bli sjekket.

MÅLT: av 40 påstander i skjemaet stemte 8 ikke.

    /analyser · /uttrekk · /fyll_skjema    fjernet (R157)
    «hvert tall i svaret»                  koden hopper over < 3 siffer
    versjon = api/prompt/regler            faktisk api/prompt/modell
    «kjøres via Prefect-flyten»            faktisk NAV-Trening-ukentlig
    «bedre → promoter, dårligere → rull»   det finnes FIRE utfall

De tre første er samme feilklasse som resten av denne gjennomgangen har
handlet om: en påstand som er STERKERE enn det koden gjør. `/hjelp`
annonserte nøyaktig de samme tre døde rutene, i månedsvis, fordi ingen
vakt leste den nyttelasten. Denne testen leser skjemaets.
"""
import os
import re
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))

import dokument_api as api


@pytest.fixture(scope="module")
def skjema():
    """Teksten i flytskjemaet, uten å starte Tkinter."""
    kilde = open(os.path.join(ROT, "skript", "api_klient_gui.py"),
                 encoding="utf-8").read()
    start = kilde.index("FLYT_NODER = [")
    slutt = kilde.index("class FlytskjemaPanel")
    rom = {"CYAN": "", "BLAA": "", "GRONN": "", "LILLA": "", "ROSA": "",
           "ORANSJE": "", "GUL": ""}
    exec(kilde[start:slutt], rom)
    biter = [f"{t} {u}" for _n, t, u, *_ in rom["FLYT_NODER"]]
    biter += list(rom["FLYT_DETALJER"].values())
    # Etikettene som tegnes på pilene ligger inne i metoden — hentes
    # som rene strenger fra kilden.
    biter += re.findall(r'text="([^"]+)"', kilde[slutt:slutt + 6000])
    return "\n".join(biter)


def _ruter_i_koden() -> set:
    kilde = open(os.path.join(ROT, "skript", "dokument_api.py"),
                 encoding="utf-8").read()
    return set(re.findall(r'sti == "(/[\w/]+)"', kilde)) | set(
        re.findall(r'sti\.startswith\("(/\w+)/', kilde))


def test_skjemaet_nevner_bare_ruter_som_finnes(skjema):
    """Selve vakten."""
    # Negativt tilbakeblikk på både bokstav OG skråstrek: uten det
    # treffer mønsteret prosa som «felter/struktur/svar/skjema» og
    # «api/prompt/modell» — bryternavn og nøkler, ikke ruter. En vakt
    # som roper på riktig tekst blir slått av, ikke fikset.
    nevnt = set(re.findall(r"(?<![\w/])(/[a-zæøå_]+)", skjema))
    ekte = _ruter_i_koden()
    # Stier som ikke er endepunkter i det hele tatt
    ikke_ruter = {"/data", "/nav", "/tekstuttrekk", "/finjuster",
                  "/validering", "/norhand", "/skript", "/delt", "/docs"}
    spokelser = {s for s in nevnt
                 if s not in ekte and s not in ikke_ruter
                 and not any(s.startswith(e) for e in ekte)}
    assert not spokelser, (
        f"flytskjemaet peker på ruter som ikke finnes: {sorted(spokelser)}")


def test_vakten_maaler_noe(skjema):
    """Speilet: uten dette ville testen over vært grønn om regexen
    sluttet å finne noe som helst."""
    assert len(re.findall(r"(?<![\w/])(/[a-zæøå_]+)", skjema)) >= 5


@pytest.mark.parametrize("dod", ["/analyser", "/uttrekk", "/fyll_skjema"])
def test_de_fjernede_rutene_er_borte_fra_skjemaet(skjema, dod):
    """Nøyaktig de tre `/hjelp` også annonserte (R157)."""
    assert dod not in skjema, f"skjemaet lover fortsatt {dod}"


def test_versjonsstempelet_navngis_riktig(skjema):
    """Skjemaet sa «api/prompt/regler». Nøklene er api/prompt/modell —
    det finnes ingen `regler`-nøkkel i noe svar."""
    assert "api/prompt/modell" in skjema
    assert "api/prompt/regler" not in skjema


def test_tallvakten_beskrives_med_sin_grense(skjema):
    """«hvert tall i svaret» er sterkere enn koden: tall under tre
    siffer hoppes over med vilje, fordi sidetall og «to vedlegg» ellers
    ville gitt så mange falske treff at vakten ble ubrukelig."""
    assert "hvert tall i svaret står ordrett" not in skjema
    assert "TRE siffer" in skjema or "tre siffer" in skjema


def test_kvalitetsporten_har_fire_utfall_i_skjemaet(skjema):
    """Porten kan si `ikke_skillbar` — to punkttall kan ikke skilles på
    et lite sett. Et skjema som bare kjenner «bedre/dårligere» skjuler
    nettopp den dommen."""
    # ALLE FIRE ved navn. Første utkast krevde bare `ikke_skillbar` og
    # ordet «FIRE» — da var det nok å bytte tallet til «TO» og la det
    # ene navnet stå, og vakten ble grønn av et skjema som fortsatt
    # underrapporterte. Navnene er det som ikke kan fuskes bort.
    for utfall in ("bedre", "dårligere", "ikke_skillbar",
                   "ingen_live_modell"):
        assert utfall in skjema, f"utfallet «{utfall}» nevnes ikke"
    assert "FIRE utfall" in skjema or "fire utfall" in skjema


def test_porten_sier_at_kontrollsettet_mangler(skjema):
    """Sløyfen tegnes som sluttet. Den er det ikke ennå:
    `data/validering/norhand.json` finnes ikke, så porten har aldri
    kjørt mot en ekte modell. Den feiler LUKKET, så oppførselen er
    trygg — men et skjema som viser en lukket sløyfe uten å si at den
    aldri har gått rundt, lover mer enn det leverer."""
    assert not os.path.exists(
        os.path.join(ROT, "data", "validering", "norhand.json")), (
        "kontrollsettet finnes nå — fjern dette forbeholdet fra skjemaet")
    assert "aldri kjørt" in skjema


def test_treningen_navngir_det_som_FAKTISK_kjorer(skjema):
    """Skjemaet sa «Prefect-flyten». Det som kjører er den planlagte
    Windows-oppgaven; Prefect finnes, men er ikke standardveien."""
    assert "NAV-Trening-ukentlig" in skjema

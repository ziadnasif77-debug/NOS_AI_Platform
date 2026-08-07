"""
Et Idempotency-Key-replay svarer som FØRSTE kall — og bærer ikke teksten.

`POST /jobb` med samme nøkkel skal gi samme jobb. Det gjorde den, men
svaret var et helt annet:

    første kall  202, 5 nøkler
    replay       200, 19 nøkler — hele den interne jobbposten

To feil i én. Formen og statuskoden skiftet (R118), og de to feltene en
robot faktisk trenger for å fortsette — `fremdrift` og `sporsmal_senere`
— fantes IKKE i replayen.

Og verre: jobbposten inneholder `tekst`, altså hele dokumentet.
`GET /jobb/<id>` fjerner den med vilje (`k != "tekst"`); replay-veien
gjorde det ikke. En Idempotency-Key finnes nettopp fordi klienten
PRØVER PÅ NYTT ved nettverksbrudd — så dette er den normale
situasjonen, ikke unntaket.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api


def _replay_blokk():
    """Kildekoden for replay-grenen i ruteren."""
    import inspect
    kilde = inspect.getsource(api.Handler._do_post_intern)
    start = kilde.index("Idempotency-Key")
    slutt = kilde.index("jobb_id = uuid", start)
    return kilde[start:slutt]


def _opprettelse_blokk():
    """SVARET fra opprettelsen — ikke den interne jobbposten.

    Første utgave klippet fra første «sporsmal_senere», men den står nå
    i REPLAY-grenen, som kommer først i kilden. Utklippet traff dermed
    feil blokk og fant «tekst» fra jobbdictet — et internt felt som
    aldri sendes. Vi tar i stedet svaret som bygges ETTER at jobben er
    opprettet."""
    import inspect
    kilde = inspect.getsource(api.Handler._do_post_intern)
    etter = kilde.index("jobb_id = uuid")
    start = kilde.index("_svar(202", etter)
    return kilde[start:kilde.index("})", start) + 2]


def test_replay_returnerer_ikke_hele_jobbposten():
    """Den ekte feilen: `{k: v for k, v in _jobber[...].items()}` ga
    ALT, inkludert dokumentteksten."""
    blokk = _replay_blokk()
    assert "_jobber[tidligere].items()" not in blokk, (
        "replay bygger fortsatt svaret av hele den interne jobbposten — "
        "den inneholder «tekst», altså hele dokumentet")


def test_replay_svarer_med_samme_statuskode_som_opprettelsen():
    """202 begge veier. Skiftet koden, måtte klienten skrive to
    kodeveier for det som logisk er samme svar."""
    blokk = _replay_blokk()
    assert "_svar(202" in blokk, "replay skal svare 202, ikke 200"
    assert "_svar(200" not in blokk


def test_replay_har_feltene_klienten_trenger_for_aa_fortsette():
    blokk = _replay_blokk()
    for felt in ("jobb_id", "status", "versjon", "fremdrift",
                 "sporsmal_senere", "idempotent_gjenbruk"):
        assert f'"{felt}"' in blokk, f"replay mangler {felt}"


def test_begge_veier_har_samme_nokkelsett():
    """R118 på den ene veien som finnes for at retry skal være trygg."""
    nokler = lambda blokk: set(re.findall(r'"([a-z_]+)":', blokk))
    replay = nokler(_replay_blokk())
    opprett = nokler(_opprettelse_blokk())
    felles = {"ok", "jobb_id", "status", "versjon", "idempotent_gjenbruk",
              "fremdrift", "sporsmal_senere"}
    assert felles <= replay, f"replay mangler {sorted(felles - replay)}"
    assert felles <= opprett, f"opprettelse mangler {sorted(felles - opprett)}"


def test_opprettelsen_gir_versjon():
    """Den optimistiske låsingen på /jobb/<id>/avbryt KREVER `versjon`,
    og OpenAPI påsto at 202-svaret bar den. Uten den måtte klienten
    gjøre en ekstra GET bare for å kunne avbryte trygt."""
    assert '"versjon": jobb["versjon"]' in _opprettelse_blokk()


def _uten_kommentarer(blokk):
    """Bare KODEN. Kommentaren over replay-grenen forklarer at
    `GET /jobb/<id>` fjerner «tekst» — og et rent tekstsøk fant den
    forklaringen i stedet for et felt. Samme felle som i /spor-vakten."""
    return "\n".join(l for l in blokk.splitlines()
                     if not l.strip().startswith("#"))


def test_ingen_av_veiene_sender_dokumentteksten():
    """Speilet på den viktigste påstanden."""
    for navn, blokk in (("replay", _replay_blokk()),
                        ("opprettelse", _opprettelse_blokk())):
        assert '"tekst"' not in _uten_kommentarer(blokk), (
            f"{navn} sender dokumentteksten")

"""
`resultater[]` har ÉN form, og rekkefølgen avgjør ingenting.

Målt hadde lista sju ulike elementformer, avhengig av type, motor og
utfall — så en robot måtte skrive én kodevei per kombinasjon. Og
`resultater[i].data` fantes ikke i det hele tatt for `svar`, mens den
var en `str` for `tekst` og et `dict` for resten.

To ekte løgner fulgte med:

1. `{r["type"]: r for r in resultater}` KOLLAPSET to operasjoner av
   samme type. Samme to operasjoner med samme utfall, i motsatt
   rekkefølge, ga ulikt `status` OG ulikt `modell_brukt`:

       [skjema/modell FEILET, skjema/felter OK] → «ok»,   modell_brukt true
       [skjema/felter OK, skjema/modell FEILET] → «feil», modell_brukt false

   Riktig for begge er «delvis», og `modell_brukt: true` i den første er
   ren løgn — modellen ble aldri spurt.

2. `_delen_brukte_modellen` antok True for en del uten flagg. Målt meldte
   `{"type":"skjema","motor":"felter"}` — en ren kodemotor — at modellen
   kjørte, mens `motor=auto` av SAMME operasjon meldte riktig.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api
from dokument_api import (_modellen_kjorte, _samlet_status,
                          normaliser_operasjonsresultat as norm)

FORVENTEDE = {"type", "ok", "data", "feil", "utelatt", "motor",
              "modell_brukt", "avvik", "ukjente_felter",
              "tilgjengelige_felter", "kilde_per_felt", "raasvar"}

# De sju formene som faktisk fantes i koden.
FORMER = {
    "tekst OK": {"type": "tekst", "ok": True, "data": "hele teksten"},
    "felter OK": {"type": "felter", "ok": True, "data": {"felter": {}}},
    "svar OK": {"type": "svar", "ok": True, "sporsmal": "Hva?",
                "svar": "6380 kroner", "modell_brukt": True,
                "tall_verifisert": True, "tolket_sporsmal": None,
                "svar_avkortet": False, "advarsler": []},
    "skjema/felter": {"type": "skjema", "ok": True, "motor": "felter",
                      "data": {}, "modell_brukt": False,
                      "ukjente_felter": [], "tilgjengelige_felter": []},
    "skjema/auto": {"type": "skjema", "ok": True, "motor": "auto",
                    "data": {}, "kilde_per_felt": {}, "modell_brukt": True,
                    "avvik": [], "ukjente_felter": [],
                    "tilgjengelige_felter": []},
    "feilet": {"type": "svar", "ok": False, "feil": "Borealis er nede"},
    "utelatt av budsjett": {"type": "skjema", "ok": False,
                            "feil": "budsjettet er brukt", "utelatt": True},
    "skjemakjerne feilet": {"type": "skjema", "ok": False,
                            "feil": "ugyldig JSON", "raasvar": "{…"},
}


@pytest.mark.parametrize("merke", sorted(FORMER))
def test_alle_former_gir_samme_nokkelsett(merke):
    assert set(norm(FORMER[merke])) == FORVENTEDE


def test_data_er_alltid_et_objekt():
    """`tekst` la teksten rett i feltet, så `data` var `str` for én type
    og `dict` for de andre. En robot som gjør `data.felter` fikk da en
    typefeil på nøyaktig én operasjonstype."""
    for merke, res in FORMER.items():
        data = norm(res)["data"]
        assert data is None or isinstance(data, dict), (
            f"{merke}: data er {type(data).__name__}")
    assert norm(FORMER["tekst OK"])["data"] == {"tekst": "hele teksten"}


def test_svarfeltene_ligger_i_data():
    """Svaret hadde ingen `data` i det hele tatt — feltene lå på
    toppnivå. Nå er `resultater[i].data` én pålitelig sti for ALLE
    typer."""
    d = norm(FORMER["svar OK"])["data"]
    assert d["svar"] == "6380 kroner"
    assert d["sporsmal"] == "Hva?"
    assert d["tall_verifisert"] is True
    assert "advarsler" in d


def test_ukjent_resultat_blir_et_ryddig_feilsvar():
    """En operasjon som returnerer noe rart skal ikke bryte formen."""
    for rart in (None, "tekst", 42, []):
        ut = norm(rart)
        assert set(ut) == FORVENTEDE
        assert ut["ok"] is False and ut["feil"]


# ------------------------------------------------------------------ #
#  Rekkefølgen avgjør ingenting                                        #
# ------------------------------------------------------------------ #

DUPLIKAT = [
    {"type": "skjema", "ok": False, "feil": "Borealis er nede"},
    {"type": "skjema", "ok": True, "motor": "felter", "modell_brukt": False},
]


def test_status_er_uavhengig_av_rekkefolgen():
    a = _samlet_status(DUPLIKAT, [])
    b = _samlet_status(list(reversed(DUPLIKAT)), [])
    assert a == b == "delvis", (
        f"samme to operasjoner ga «{a}» og «{b}» — kollapsen er tilbake")


def test_modell_brukt_er_uavhengig_av_rekkefolgen():
    a = _modellen_kjorte(DUPLIKAT)
    b = _modellen_kjorte(list(reversed(DUPLIKAT)))
    assert a is b is False, (
        "ingen av de to kjørte modellen — den ene feilet, den andre er "
        "ren kode")


def test_delvis_er_naabar():
    """Med kollapsen kunne «delvis» aldri oppstå for like typer: den ene
    forsvant, og da var alle enten OK eller alle feilet."""
    assert _samlet_status(DUPLIKAT, []) == "delvis"


def test_alle_ok_og_alle_feilet_fortsatt_riktig():
    """Speilet — uten det kunne «delvis» vært hardkodet."""
    assert _samlet_status([{"type": "a", "ok": True},
                           {"type": "b", "ok": True}], []) == "ok"
    assert _samlet_status([{"type": "a", "ok": False},
                           {"type": "b", "ok": False}], []) == "feil"


def test_bryterveiens_dict_virker_fortsatt():
    """Samme funksjon brukes av BEGGE kontraktene. Bryterveien sender et
    dict; den skal ikke ha blitt brutt av at operasjonsveien nå sender
    en liste."""
    assert _samlet_status({"felter": {"ok": True},
                           "svar": {"ok": False}}, []) == "delvis"
    assert _modellen_kjorte({"svar": {"ok": True, "modell_brukt": True}}) \
        is True


# ------------------------------------------------------------------ #
#  Hver modellkapabel operasjon sier det uttrykkelig                    #
# ------------------------------------------------------------------ #

def test_ingen_operasjon_lar_modell_brukt_staa_apen():
    """Standarden er False nå, så en operasjon som glemmer å si fra blir
    rapportert som «modellen kjørte ikke». Det er den trygge veien —
    men da må hver av dem faktisk si det."""
    import inspect
    for navn in ("SkjemaOperasjon", "KorrigerOperasjon", "SvarOperasjon"):
        kilde = inspect.getsource(getattr(api, navn))
        # Bare KODEN, ikke kommentarene.
        kode = "\n".join(l for l in kilde.splitlines()
                         if not l.strip().startswith("#"))
        assert "modell_brukt" in kode, (
            f"{navn} sier ikke om modellen kjørte — med standard False "
            f"blir den rapportert som ren kode, uansett hva den gjorde")

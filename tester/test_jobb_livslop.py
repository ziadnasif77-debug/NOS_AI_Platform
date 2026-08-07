"""
En jobb har SAMME form i hver tilstand — og lyver ikke mens den venter.

En pollende robot leser den samme stien hvert sekund gjennom kø, arbeid
og ferdig. Målt hadde svaret tre ulike nøkkelsett, og verdiene påsto
ting som ikke var sanne:

    status «kø»:  felter {}   datoer []   antall_tegn 0   dokumentdato null
                  strekkoder []   handskrift []   ocr_motorer {}

Alt dette leses som «vi leste dokumentet og fant ingenting» — om et
dokument som ligger i kø og ikke er rørt.

Verst i avbrutt tilstand: `sider_ferdig: 2` av 10 SAMTIDIG med
`antall_tegn: 0` og `felter: {}`. Arbeidet var gjort og kastet, og
svaret påsto at det ikke fantes noe.

Og `dokumentdato` var null før ferdig, men et 12-nøkkels objekt etterpå
— så `dokumentdato.periode.fra` krasjet på HVER poll før jobben var
ferdig. Det er den vanlige tilstanden, ikke unntaket.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api


# Nøklene jobbposten har fra første stund. «avbrutt» og «feil» dukket
# opp FØRST i det de skjedde — og det er nettopp de to en poller
# trenger.
FORVENTEDE = {
    "jobb_id", "filnavn", "status", "versjon", "avbrutt", "feil",
    "sider_ferdig", "sider_totalt", "sekunder_brukt",
    "sekunder_igjen_estimat", "tekst", "antall_tegn", "felter", "datoer",
    "dokumentdato", "strekkoder", "handskrift", "ocr_motorer", "opprettet",
}


def _ny_jobb():
    """Jobbposten slik ruteren bygger den, uten HTTP."""
    import inspect
    import re
    kilde = inspect.getsource(api.Handler._do_post_intern)
    start = kilde.index('jobb = {"jobb_id": jobb_id')
    slutt = kilde.index('if slag == "tekst":', start)
    kropp = kilde[start:slutt]
    kropp = "\n".join(l for l in kropp.splitlines()
                      if not l.strip().startswith("#"))
    rom = {"jobb_id": "abc", "filnavn": "p.pdf", "time": __import__("time"),
           "_tomt_dokumentdato": api._tomt_dokumentdato}
    exec(kropp.strip(), rom)
    return rom["jobb"]


def test_alle_nokler_finnes_fra_forste_stund():
    assert set(_ny_jobb()) == FORVENTEDE


def test_avbrutt_og_feil_staar_der_for_de_skjer():
    """De to nøklene en poller trenger mest var de eneste som manglet
    til de plutselig ikke gjorde det."""
    jobb = _ny_jobb()
    assert jobb["avbrutt"] is False
    assert jobb["feil"] is None


@pytest.mark.parametrize("felt", ["felter", "datoer", "strekkoder",
                                  "handskrift", "ocr_motorer", "tekst",
                                  "antall_tegn", "sider_ferdig"])
def test_uleste_felt_er_null_ikke_tomme(felt):
    """`{}`/`[]`/`0` leses som «vi leste og fant ingenting». En jobb i
    kø er ikke rørt (R128)."""
    assert _ny_jobb()[felt] is None, (
        f"«{felt}» påstår et resultat om et dokument som ligger i kø")


def test_dokumentdato_er_et_objekt_fra_forste_stund():
    """En poller som leser `dokumentdato.periode.fra` krasjet på HVER
    poll før jobben var ferdig."""
    dd = _ny_jobb()["dokumentdato"]
    assert isinstance(dd, dict)
    assert dd["dato"] is None
    assert isinstance(dd["periode"], dict), (
        "periode må være et skjelett, ikke null — den tar med seg alle "
        "stiene under seg")
    assert dd["periode"]["fra"] is None


def test_skjelettet_folger_den_ekte_tom_grenen():
    """Bygges skjelettet for hånd, glir det fra formen
    `finn_dokumentdato` faktisk leverer. Det gjenbruker den i stedet."""
    from delt.tekstuttrekk import finn_dokumentdato
    assert set(api._tomt_dokumentdato()) == set(finn_dokumentdato([]))


# ------------------------------------------------------------------ #
#  Versjonen løftes ved HVER overgang                                  #
# ------------------------------------------------------------------ #

def test_tekstveien_lofter_versjonen():
    """Den synkrone tekstveien brukte `jobb.update` og løftet den ikke,
    så en FERDIG tekstjobb rapporterte versjon 1 — samme tall den hadde
    i kø. Optimistisk låsing kunne dermed ikke se overgangen."""
    import inspect
    kilde = inspect.getsource(api.Handler._do_post_intern)
    start = kilde.index('if slag == "tekst":')
    blokk = kilde[start:kilde.index("else:", start)]
    assert "_jobb_status(" in blokk, (
        "tekstveien må gå gjennom _jobb_status, som løfter versjonen")
    assert 'jobb.update(status="ferdig"' not in blokk


def test_jobb_status_lofter_versjonen():
    jobb = {"status": "kø", "versjon": 1}
    api._jobb_status(jobb, "ferdig", antall_tegn=5)
    assert jobb["versjon"] == 2 and jobb["status"] == "ferdig"
    assert jobb["antall_tegn"] == 5


def test_ferdig_tekstjobb_har_sidetall():
    """`sider_totalt: null` på en FERDIG jobb fikk GUI-en til å vise
    ingen fremdrift i det hele tatt. Ren tekst er 1 av 1."""
    import inspect
    kilde = inspect.getsource(api.Handler._do_post_intern)
    start = kilde.index('if slag == "tekst":')
    blokk = kilde[start:kilde.index("else:", start)]
    assert "sider_ferdig=1" in blokk and "sider_totalt=1" in blokk


# ------------------------------------------------------------------ #
#  Avbrutt jobb estimerer ikke tid som ikke kommer                     #
# ------------------------------------------------------------------ #

def test_avbrutt_nuller_estimatet():
    """Målt sto «ca. 30 s igjen» på en AVBRUTT jobb, og GUI-en skrev det
    ut uendret: «status: avbrutt — side 2 av 10 — ca. 30 s igjen»."""
    import inspect
    kilde = inspect.getsource(api._jobb_arbeider) if hasattr(
        api, "_jobb_arbeider") else open(api.__file__, encoding="utf-8").read()
    assert 'jobb.get("status") == "avbrutt"' in kilde
    # Nullingen skal stå i avbrutt-grenen, ikke bare i ferdig-grenen.
    i = kilde.index('jobb.get("status") == "avbrutt"')
    assert 'sekunder_igjen_estimat"] = None' in kilde[i:i + 400]

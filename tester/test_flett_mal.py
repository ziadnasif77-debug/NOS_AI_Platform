"""
Deterministisk malfletting: hver klient sender sitt EGET JSON-format med
{feltnavn}-plassholdere, og API-et fyller dem fra de deterministisk
funnede feltene — UTEN modell, like raskt som felter.

Disse testene vokter kontrakten: plassholdere byttes riktig, typer
bevares (tall forblir tall, manglende felt blir null), ukjente feltnavn
rapporteres i stedet for å feile stille, og nøstede maler/lister virker.
"""
import sys

sys.path.insert(0, ".")

import pytest

from delt.tekstuttrekk import felter_flatt, flett_mal, refererte_felt


# En realistisk dokumenttekst med flere deterministiske felter.
DOK = (
    "HADSEL TRYGDEKONTOR\n"
    "Telefon 76118610\n"
    "8450 STOKMARKNES\n"
    "Gjelder barnetrygd.\n"
    "Totalt 6380.00 NOK\n"
)


# ------------------------------------------------------------------ #
#  felter_flatt: flat oppslagstabell                                  #
# ------------------------------------------------------------------ #

def test_flatt_har_stabile_navn():
    flat = felter_flatt(DOK)
    for navn in ("telefon", "postnummer", "poststed", "ytelse", "belop",
                 "dokumentdato", "periode_start", "periode_slutt"):
        assert navn in flat, f"mangler forventet feltnavn: {navn}"


def test_flatt_finner_verdiene():
    flat = felter_flatt(DOK)
    assert flat["telefon"] == "76118610"
    assert flat["postnummer"] == "8450"
    assert flat["poststed"] == "STOKMARKNES"
    assert flat["ytelse"] == "barnetrygd"
    assert flat["belop"] == 6380.0


def test_flatt_manglende_felt_er_none():
    """Et dokument uten dokumentdato gir None — ikke en oppdiktet dato."""
    flat = felter_flatt(DOK)
    assert flat["dokumentdato"] is None


# ------------------------------------------------------------------ #
#  flett_mal: klientens eget format                                   #
# ------------------------------------------------------------------ #

def test_ren_plassholder_gir_egen_type():
    """«{belop}» alene skal gi TALLET 6380.0, ikke strengen «6380.0»."""
    mal = {"sum": "{belop}"}
    utfylt, _ = flett_mal(mal, DOK)
    assert utfylt["sum"] == 6380.0
    assert isinstance(utfylt["sum"], float)


def test_klienten_velger_egne_navn():
    mal = {"kontakt": "{telefon}", "sted": "{poststed}", "stonad": "{ytelse}"}
    utfylt, _ = flett_mal(mal, DOK)
    assert utfylt == {"kontakt": "76118610", "sted": "STOKMARKNES",
                      "stonad": "barnetrygd"}


def test_manglende_felt_blir_null_ikke_feil():
    mal = {"utstedt": "{dokumentdato}"}
    utfylt, _ = flett_mal(mal, DOK)
    assert utfylt["utstedt"] is None


def test_plassholder_i_tekst_gir_streng():
    """Vevd inn i tekst: strenginnsetting, ikke rå type."""
    mal = {"linje": "Ring {telefon} i {poststed}"}
    utfylt, _ = flett_mal(mal, DOK)
    assert utfylt["linje"] == "Ring 76118610 i STOKMARKNES"


def test_manglende_felt_i_tekst_blir_tom():
    mal = {"linje": "Dato: {dokumentdato}."}
    utfylt, _ = flett_mal(mal, DOK)
    assert utfylt["linje"] == "Dato: ."


def test_konstant_uten_plassholder_beholdes():
    """En verdi uten {..} er en konstant klienten vil ha uendret."""
    mal = {"kilde": "NAV-dokument-AI", "tlf": "{telefon}"}
    utfylt, _ = flett_mal(mal, DOK)
    assert utfylt["kilde"] == "NAV-dokument-AI"


def test_ikke_streng_verdier_beholdes():
    mal = {"aktiv": True, "antall": 3, "tomt": None, "tlf": "{telefon}"}
    utfylt, _ = flett_mal(mal, DOK)
    assert utfylt["aktiv"] is True
    assert utfylt["antall"] == 3
    assert utfylt["tomt"] is None


def test_nostet_mal_og_liste():
    mal = {
        "avsender": {"navn": "{kontornavn}", "tlf": "{telefon}"},
        "poster": ["{poststed}", "{postnummer}"],
    }
    utfylt, _ = flett_mal(mal, DOK)
    assert utfylt["avsender"]["tlf"] == "76118610"
    assert utfylt["poster"] == ["STOKMARKNES", "8450"]


def test_liste_som_toppniva():
    mal = [{"tlf": "{telefon}"}, {"sted": "{poststed}"}]
    utfylt, _ = flett_mal(mal, DOK)
    assert utfylt[0]["tlf"] == "76118610"
    assert utfylt[1]["sted"] == "STOKMARKNES"


def test_ukjent_feltnavn_rapporteres():
    mal = {"a": "{finnesikke}", "b": "{telefon}"}
    utfylt, rapport = flett_mal(mal, DOK)
    assert utfylt["a"] is None
    assert "finnesikke" in rapport["ukjente_felter"]
    assert "telefon" not in rapport["ukjente_felter"]


def test_rapport_lister_tilgjengelige_felter():
    _, rapport = flett_mal({"x": "{telefon}"}, DOK)
    assert "telefon" in rapport["tilgjengelige_felter"]
    assert "belop" in rapport["tilgjengelige_felter"]
    assert rapport["tilgjengelige_felter"] == sorted(
        rapport["tilgjengelige_felter"])


def test_mellomrom_i_plassholder_taales():
    mal = {"a": "{ telefon }"}
    utfylt, rapport = flett_mal(mal, DOK)
    assert utfylt["a"] == "76118610"
    assert rapport["ukjente_felter"] == []


# ------------------------------------------------------------------ #
#  refererte_felt: hvilke felter en mal trenger                       #
# ------------------------------------------------------------------ #

def test_refererte_felt_finner_alle_navn():
    mal = {"a": "{telefon}", "b": {"c": "{poststed}"},
           "d": ["{ytelse}", "konstant"], "e": "Ring {telefon} nå"}
    assert refererte_felt(mal) == ["poststed", "telefon", "ytelse"]


def test_refererte_felt_tom_uten_plassholdere():
    assert refererte_felt({"a": "konstant", "b": 5}) == []


def test_refererte_felt_tar_med_ukjent_konsept():
    """Et navn uten deterministisk regel (som «navn») skal også telles —
    det er nettopp disse den hybride motoren sender til modellen."""
    assert "navn" in refererte_felt({"kunde": "{navn}"})


# ------------------------------------------------------------------ #
#  flat-overstyring: hybrid-motoren beriker tabellen selv             #
# ------------------------------------------------------------------ #

def test_flett_med_ferdig_flat():
    """Gis flat direkte, brukes den — teksten leses ikke på nytt. Slik
    setter hybrid-motoren inn modellfunnede felter (som «navn»)."""
    flat = {"telefon": "99887766", "navn": "Terje Karlsen"}
    utfylt, rapport = flett_mal({"tlf": "{telefon}", "kunde": "{navn}"},
                                flat=flat)
    assert utfylt == {"tlf": "99887766", "kunde": "Terje Karlsen"}
    assert rapport["ukjente_felter"] == []

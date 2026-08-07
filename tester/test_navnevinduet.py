"""Et navn hører til DETTE fødselsnummeret — ikke til naboen.

Bakgrunn: køa sa at `part` og `dokumenter[].eier` hadde ulikt vindu og
kunne tilskrive et dokument feil person i en bunke. MÅLT stemte det
ikke. En fil med to ulike eiere gir `part.fnr: null` med
`grunnlag: "flertydig"` og en begrunnelse som navngir konflikten — R124
håndterer det allerede riktig — og `dokumenter[]` gir hver sin eier.

Men i den samme koden lå en verre feil. `_navn_ved` hadde tre
strategier, og de to første var avgrenset til vinduet mellom etiketten
og nummeret. Den tredje — «linja over nummeret» — var bare avgrenset av
nummerets posisjon, og gikk derfor tre ikke-tomme linjer bakover: rett
forbi etiketten som styrer nummeret, og forbi forrige persons
fødselsnummer.

Målt på fem varianter av «legen/saksbehandleren har ingen navn i
teksten» fikk FIRE av dem partens navn festet på en annen persons
nummer. Hele grunnen til at `andre_fodselsnummer` finnes er å holde de
andre STRENGT atskilt fra parten (R69) — her lekket parten inn i dem.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from delt.dokumentprofil import _navn_ved, bygg_profil, finn_dokument_eier
from delt.tekstuttrekk import (finn_dokumentdato, klassifiser_datoer,
                               sett_dato_roller, strukturert_uttrekk)
from syntetiske_nummer import lag_fnr

PART = lag_fnr(0)
ANNEN = lag_fnr(1)
PARTNAVN = "Ola Nordmann"


def _profil(tekst, sider=2):
    d = sett_dato_roller(klassifiser_datoer(tekst))
    return bygg_profil(tekst, filnavn="b.txt", antall_sider=sider,
                       datoer_detaljert=d, dokumentdato=finn_dokumentdato(d),
                       struktur=strukturert_uttrekk(tekst))


def _den_andre(tekst):
    e = finn_dokument_eier(tekst)
    return next((a for a in (e["andre_fodselsnummer"] or [])
                 if a["fnr"] == ANNEN), None)


# ------------------------------------------------------------------ #
#  1. Partens navn lekker ikke over på et annet nummer                 #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("beskrivelse,hale", [
    # Alle fire fikk «Ola Nordmann» før fiksen.
    ("tittel som ikke leses som navn", f"Lege: Dr. Hansen, {ANNEN}\n"),
    ("ingen navn i det hele tatt", f"Lege: {ANNEN}\n"),
    ("tomme linjer imellom", f"\n\nLege: Dr. Hansen, {ANNEN}\n"),
    ("etikett på egen linje", f"Kontaktperson hos arbeidsgiver:\n{ANNEN}\n"),
])
def test_partens_navn_festes_ikke_paa_en_annen_persons_nummer(beskrivelse,
                                                              hale):
    tekst = (f"Opplysninger om: {PARTNAVN}\n"
             f"Fodselsnummer: {PART}\n" + hale)
    annen = _den_andre(tekst)
    assert annen is not None, "nummeret havnet ikke i andre_fodselsnummer"
    assert annen["navn"] != PARTNAVN, (
        f"{beskrivelse}: partens navn ble festet på {annen['etikett']}s "
        f"fødselsnummer")
    assert annen["navn"] is None, (
        "det står ikke noe navn for dette nummeret — da skal feltet være "
        "null, ikke naboens navn")


def test_et_navn_som_FAKTISK_staar_der_beholdes():
    """Speilet. Uten dette kunne «fiksen» vært å nulle feltet alltid."""
    tekst = (f"Opplysninger om: {PARTNAVN}\nFodselsnummer: {PART}\n"
             f"Lege: Per Hansen, {ANNEN}\n")
    annen = _den_andre(tekst)
    assert annen["navn"] == "Per Hansen"


def test_parten_selv_beholder_navnet_sitt():
    tekst = (f"Opplysninger om: {PARTNAVN}\nFodselsnummer: {PART}\n"
             f"Lege: {ANNEN}\n")
    e = finn_dokument_eier(tekst)
    assert e["navn"] == PARTNAVN and e["fnr"] == PART


# ------------------------------------------------------------------ #
#  2. Grensene, målt direkte                                           #
# ------------------------------------------------------------------ #

def test_etiketten_er_grensen_naar_nummeret_er_merket():
    """Er nummeret merket, avgrenser etiketten personens blokk
    (`_rolle_for_forekomst`). Står navnet ikke mellom etiketten og
    nummeret, finnes det ikke — å lete lenger bak er per definisjon å
    lete i en annen persons opplysninger."""
    tekst = f"{PARTNAVN}\nFodselsnummer: {PART}\n"
    p = tekst.index(PART)
    assert _navn_ved(tekst, p, p, merket=True) is None
    # umerket er en annen sak: da ER linja over nummeret riktig kilde
    assert _navn_ved(tekst, p, p, merket=False) == PARTNAVN


def test_den_umerkede_utveien_stopper_ved_forrige_fodselsnummer():
    """Et fødselsnummer avslutter blokken til personen det hører til."""
    tekst = f"{PARTNAVN}\n{PART}\n{ANNEN}\n"
    p = tekst.index(ANNEN)
    assert _navn_ved(tekst, p, p, merket=False) is None


# ------------------------------------------------------------------ #
#  3. Det køa TRODDE var galt, og som måling avviste                   #
# ------------------------------------------------------------------ #

BUNKE = (f"[Side 1 av 2]\nNAV\nVedtak om sykepenger\nVedtaksdato: 04.03.2026\n"
         f"Opplysninger om: {PARTNAVN}\nFodselsnummer: {PART}\n\n"
         f"[Side 2 av 2]\nNAV\nVedtak om dagpenger\nVedtaksdato: 11.05.2026\n"
         f"Opplysninger om: Kari Hansen\nFodselsnummer: {ANNEN}\n")


def test_part_gjetter_IKKE_naar_bunken_gjelder_to_personer():
    """Frykten i køa var at `part` skulle plukke én av to. Den gjør ikke
    det — og denne testen låser oppførselen fast."""
    part = _profil(BUNKE)["part"]
    assert part["fnr"] is None
    assert part["fastslatt"] is False
    assert part["grunnlag"] == "flertydig"
    assert "Flere ULIKE" in part["begrunnelse"]


def test_begge_personene_er_bevart_selv_om_parten_er_ukjent():
    """«Flertydig» skal ikke bety at opplysningene kastes."""
    profil = _profil(BUNKE)
    numre = {a["fnr"] for a in profil["andre_fodselsnummer"]}
    assert numre == {PART, ANNEN}
    navn = {a["navn"] for a in profil["andre_fodselsnummer"]}
    assert navn == {PARTNAVN, "Kari Hansen"}


def test_hvert_dokument_i_bunken_har_sin_egen_eier():
    dok = _profil(BUNKE)["dokumenter"]
    assert [(d["eier_navn"], d["eier_fnr"]) for d in dok] == [
        (PARTNAVN, PART), ("Kari Hansen", ANNEN)]

"""Én grammatikk for å LESE datoer, og én avledet fødselsdato per person.

To feil med samme rot: det fantes to kodeveier for det samme, og de var
ikke enige.

1. `finn_dato` hadde sin EGEN kopi av datogrammatikken, strengt svakere
   enn `_alle_datotreff`. Målt på tolv skrivemåter leste de to fire
   ULIKT — alle fire til `finn_dato`s ugunst. Følgen: samme dato, i
   samme dokument, ble funnet av ett felt og MISTET av et annet, kun
   avhengig av hvilken kodevei som leste den. R61-fiksene for OCR ble
   gjort i den ene grammatikken og ikke i den andre.

2. Den avledede fødselsdatoen ble regnet fra `finn_fodselsnummer`, som
   gir det FØRSTE fnr-gyldige tallet. Nevner dokumentet legen før
   parten, var det legens. Svaret oppga da to ULIKE fødselsdatoer —
   legens i datolista, partens i `part.fodselsdato` — og de øvrige
   personenes ble stilltiende droppet.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from delt.dokumentprofil import bygg_profil, finn_dokument_eier
from delt.tekstuttrekk import (finn_alle_datoer, finn_dato,
                               finn_dokumentdato, finn_fodselsnummer,
                               fodselsdato_av_fnr, klassifiser_datoer,
                               sett_dato_roller, strukturert_uttrekk)
from syntetiske_nummer import lag_fnr_fodt

LEGE = lag_fnr_fodt(15, 6, 1975)
PART = lag_fnr_fodt(3, 11, 1988)
LEGE_FODT = "1975-06-15"
PART_FODT = "1988-11-03"


# ------------------------------------------------------------------ #
#  1. Én grammatikk for å lese datoer                                  #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("skrevet", [
    "12.03.2021",       # norsk, punktum
    "12/03/2021",       # norsk, skråstrek
    "2021-03-12",       # ISO
    "12. mars 2021",    # norsk månedsnavn
    "12 mars 2021",
    "12.mars.2021",     # OCR mister mellomrommet
    "12 March 2021",    # ENGELSK — fant ingenting før
    "March 12, 2021",   # ENGELSK, måned først — fant ingenting før
    "12.03 . 2021",     # OCR-mellomrom (R61) — fant ingenting før
    "DATO12.03.2021",   # limt til nabotekst
])
def test_de_to_veiene_leser_samme_dato_likt(skrevet):
    assert finn_dato(skrevet) == (finn_alle_datoer(skrevet) or [None])[0]


@pytest.mark.parametrize("skrevet", ["12 March 2021", "March 12, 2021",
                                     "12.03 . 2021"])
def test_de_tre_som_ble_MISTET_finnes_naa(skrevet):
    """Uten denne kunne «enighet» oppfylles ved at BEGGE feiler."""
    assert finn_dato(skrevet) == "2021-03-12"


def test_tosifret_aar_holdes_utenfor_med_VILJE():
    """Den ene forskjellen som er igjen, og den er et valg.

    `_alle_datotreff` merker antatt århundre med `aar_antatt`.
    `finn_dato` returnerer en bar streng, og kallerne hennes
    (`okonomi.utbetalingsdato`, `arbeid.startdato`, skjemautfyllingen)
    har ingen plass å si «århundret er gjettet». Å slippe dem gjennom
    her ville gjort en gjetning om til et faktum på veien ut."""
    assert finn_dato("12.03.21") is None
    assert finn_alle_datoer("12.03.21") == ["2021-03-12"]


def test_grammatikken_finnes_bare_ETT_sted():
    """Vakten mot at en tredje kopi vokser fram. `_alle_datotreff` er
    detektoren; alt annet skal gå gjennom den."""
    import inspect

    import delt.tekstuttrekk as tu
    kilde = inspect.getsource(tu.finn_dato)
    assert "_alle_datotreff" in kilde
    assert "re.finditer" not in kilde, (
        "finn_dato har fått sin egen regex igjen — da er det to "
        "grammatikker på nytt")


def test_feltene_fra_saksfelter_leser_de_samme_formene():
    """Kodeveien som faktisk ble rammet: `_merket_dato` går via
    `finn_dato`, så `arbeid.startdato` sto null på datoer resten av
    systemet leste fint."""
    from delt.saksfelter import arbeid_felter
    assert arbeid_felter("Ansatt fra 12 March 2021.")["startdato"] == \
        "2021-03-12"


# ------------------------------------------------------------------ #
#  2. Én avledet fødselsdato PER person                                #
# ------------------------------------------------------------------ #

DOK = (f"NAV Arbeid og ytelser\nVedtak om sykepenger\n"
       f"Vedtaksdato: 04.03.2026\n"
       f"Legeerklaering fra Lege: {LEGE}\n"
       f"Opplysninger om: Ola Nordmann\nFodselsnummer: {PART}\n")


def _avledede(tekst=DOK):
    return [d for d in sett_dato_roller(klassifiser_datoer(tekst))
            if d["type"] == "fodselsdato_fra_fnr"]


def test_de_to_fnr_ene_har_ULIKE_fodselsdatoer():
    """Grunnlaget for hele testen. Med `lag_fnr` ville begge vært født
    01.01.1990, og riktig og galt svar sett helt like ut."""
    assert LEGE_FODT != PART_FODT
    assert fodselsdato_av_fnr(LEGE)[2] == 1975
    assert fodselsdato_av_fnr(PART)[2] == 1988


def test_ingen_person_droppes_i_stillhet():
    assert {d["dato"] for d in _avledede()} == {LEGE_FODT, PART_FODT}


def test_hver_oppforing_kan_spores_til_SITT_nummer():
    """Uten dette ville to fødselsdatoer bare vært to tall."""
    kart = {d["raatekst"]: d["dato"] for d in _avledede()}
    assert kart[LEGE[:6] + "*****"] == LEGE_FODT
    assert kart[PART[:6] + "*****"] == PART_FODT


def test_den_FOERSTE_er_ikke_lenger_den_eneste():
    """Selve regresjonen: `finn_fodselsnummer` gir legens nummer her,
    og det var det eneste som ble avledet."""
    assert finn_fodselsnummer(DOK) == LEGE
    assert finn_dokument_eier(DOK)["fnr"] == PART
    assert len(_avledede()) == 2


def test_begrunnelsen_sier_at_den_IKKE_identifiserer_personen():
    """Den kan ikke vite hvem nummeret tilhører — eier-etikettene bor i
    dokumentprofil, som importerer denne fila. Da skal den si det, ikke
    la leseren anta."""
    for d in _avledede():
        assert "IKKE hvem" in d["begrunnelse"]
        assert "part.fodselsdato" in d["begrunnelse"]


def test_parten_faar_fortsatt_SIN_egen_fodselsdato():
    """Speilet: profilen skal ikke ha blitt utvannet av at lista nå har
    flere."""
    d = sett_dato_roller(klassifiser_datoer(DOK))
    p = bygg_profil(DOK, filnavn="x.txt", antall_sider=1, datoer_detaljert=d,
                    dokumentdato=finn_dokumentdato(d),
                    struktur=strukturert_uttrekk(DOK))
    assert p["part"]["fnr"] == PART
    assert p["part"]["fodselsdato"] == PART_FODT


def test_ett_fodselsnummer_gir_fortsatt_EN_oppforing():
    """Det vanlige dokumentet skal ikke ha endret seg."""
    enkel = f"Opplysninger om: Ola\nFodselsnummer: {PART}\n"
    avledet = _avledede(enkel)
    assert len(avledet) == 1 and avledet[0]["dato"] == PART_FODT


# ------------------------------------------------------------------ #
#  3. Den TREDJE grammatikken — mønsteret i saksfelter                 #
# ------------------------------------------------------------------ #

def test_merket_dato_har_ikke_sitt_eget_datomonster():
    """`_merket_dato` fanget datoen med sitt EGET mønster før den sendte
    den videre til parseren. Mønsteret var strengere enn parseren, så
    det avgjorde i praksis hvilke former feltet forsto — og forsto
    færre. Nå finner den bare ETIKETTEN."""
    import inspect

    from delt import saksfelter
    kilde = inspect.getsource(saksfelter._merket_dato)
    assert r"[0-9]{1,2}[.\-/ ][0-9]{1,2}" not in kilde, (
        "det egne datomønsteret er tilbake — da er det tre grammatikker")
    assert "finn_dato(" in kilde


@pytest.mark.parametrize("linje,forventet", [
    ("Utbetalingsdato: 25.03 . 2026", "2026-03-25"),   # OCR-mellomrom (R61)
    ("Utbetalingsdato: 25. mars 2026", "2026-03-25"),
    ("Utbetalingsdato: 25 March 2026", "2026-03-25"),  # engelsk
    ("Utbetalingsdato: 2026-03-25", "2026-03-25"),
    ("Utbetalingsdato: 25.03.2026", "2026-03-25"),
])
def test_merkede_datofelt_leser_alle_de_samme_formene(linje, forventet):
    from delt.saksfelter import okonomi_felter
    assert okonomi_felter(linje)["utbetalingsdato"] == forventet


def test_merket_dato_plukker_ikke_neste_setnings_dato():
    """Uten en grense ville «Utbetalingsdato: ikke oppgitt» hentet
    datoen fra setningen etter — en verdi som ser riktig ut og er feil."""
    from delt.saksfelter import okonomi_felter
    tekst = "Utbetalingsdato: ikke oppgitt. Vedtaket ble fattet 01.01.2020."
    assert okonomi_felter(tekst)["utbetalingsdato"] is None


def test_to_merkede_datoer_holdes_fra_hverandre():
    from delt.saksfelter import arbeid_felter
    f = arbeid_felter("Ansatt fra 01.08.2019. Sluttdato: 31.12.2024.")
    assert f["startdato"] == "2019-08-01"
    assert f["sluttdato"] == "2024-12-31"

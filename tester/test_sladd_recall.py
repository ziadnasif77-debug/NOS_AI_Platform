"""Recall for `/sladd`, MÅLT mot en fasit — ikke antatt.

Balansen her er skjev, og det avgjør hvilket tall som er styrende:

    for mye sladdet  →  irritasjon; lovlig innhold blir borte
    for lite sladdet →  PERSONOPPLYSNINGER PÅ AVVEIE

Derfor er `recall` målet, og målet er 1.00 — ikke 0.99. Et avvik skal
vises som et ANTALL («lekket 3 av 400»), ikke som en andel, for en
andel gjør tre mennesker om til et desimaltall.

Fasiten bygges på KJØRETID. Et ellevesifret tall i en fil ser ut som et
fødselsnummer uansett hvor syntetisk det er ment å være, og
portabilitetsvakten stopper det.

DET DENNE MÅLINGEN FANT MED ÉN GANG
Fire av tolv skrivemåter LEKKET: bindestrek og linjeskift, for både
fødselsnummer og kontonummer. Skanneren godtok bare mellomrom og
punktum inne i et tall — og «010190-10046» er en helt vanlig norsk
skrivemåte, mens et linjeskift midt i et nummer skjer hele tiden i
ombrukket og OCR-lest tekst (R145).
"""
import os
import re
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from delt.tekstuttrekk import finn_sladdeomraader, sladd_tekst
from syntetiske_nummer import lag_fnr, lag_kontonummer

FNR = lag_fnr(0)
FNR2 = lag_fnr(1)
KONTO = lag_kontonummer(0)


def _skrivemaater(nr):
    """Samme verdi, slik dokumenter FAKTISK skriver den."""
    return {
        "ordrett": nr,
        "mellomrom": f"{nr[:6]} {nr[6:]}",
        "punktum": f"{nr[:4]}.{nr[4:6]}.{nr[6:]}",
        "bindestrek": f"{nr[:6]}-{nr[6:]}",
        "linjeskift": f"{nr[:6]}\n{nr[6:]}",
        "parvis": " ".join(nr[i:i + 2] for i in range(0, 10, 2)) + nr[10],
    }


def _sladd(tekst):
    ut = sladd_tekst(tekst)
    return ut[0] if isinstance(ut, tuple) else ut


def _roper(sladdet, nr):
    """Står verdien igjen? Måles på SIFRENE alene — en sladding som
    bare fjerner bindestreken har ikke sladdet noe."""
    return nr in re.sub(r"\D", "", sladdet)


# ------------------------------------------------------------------ #
#  1. Recall er 1.00 — og avvik vises som et ANTALL                    #
# ------------------------------------------------------------------ #

def test_ingen_bevisbar_identifikator_lekker():
    """Selve målingen. Feiler den, sier meldingen hvor mange og hvilke
    — ikke «recall 0.83»."""
    lekket, totalt = [], 0
    for type_, nr in (("fodselsnummer", FNR), ("kontonummer", KONTO)):
        for form, skrevet in _skrivemaater(nr).items():
            totalt += 1
            tekst = f"NAV Vedtak\n{type_}: {skrevet}\nSlutt."
            if _roper(_sladd(tekst), nr):
                lekket.append(f"{type_}/{form}")
    assert not lekket, (
        f"LEKKET {len(lekket)} av {totalt} skrivemåter: {lekket}")


# Nøklene, ikke verdiene — og de hentes fra et GENERERT nummer, ikke fra
# en plassholder på elleve siffer. Portabilitetsvakten tar en slik
# plassholder, og den har rett: elleve siffer i en fil ser ut som et
# fødselsnummer uansett hva de er ment å være.
@pytest.mark.parametrize("form", sorted(_skrivemaater(FNR)))
def test_hver_skrivemaate_hver_for_seg(form):
    """Navngitt per form, så en rød test sier HVILKEN skrivemåte som
    røk uten at noen må lese en liste."""
    skrevet = _skrivemaater(FNR)[form]
    assert not _roper(_sladd(f"Fodselsnummer: {skrevet}\n"), FNR)


def test_flere_personer_i_samme_dokument():
    """En bunke gjelder ofte to. Sladdes bare den første, er den andre
    like eksponert som før."""
    tekst = (f"Opplysninger om: Ola\nFodselsnummer: {FNR[:6]}-{FNR[6:]}\n"
             f"Verge: Kari\nFodselsnummer: {FNR2}\n")
    sladdet = _sladd(tekst)
    lekket = [n for n in (FNR, FNR2) if _roper(sladdet, n)]
    assert not lekket, f"lekket {len(lekket)} av 2 personer"


# ------------------------------------------------------------------ #
#  1b. NABOEN — det målingen over ikke kunne se                        #
# ------------------------------------------------------------------ #
#
# Malen over har ALLTID en bokstav på hver side av nummeret
# («Fodselsnummer: … \nSlutt.»). Da kan den ikke oppdage det R145 selv
# innførte: skilletegnene rommer nå linjeskift, så et NABOTALL limes
# på. En dato over nummeret gir ett treff på nitten siffer, feil lengde
# — og kandidaten ble forkastet HELT.
#
# Målt før R150: tre av tre nabosammenhenger lekket, og svaret sa
# `sladding_fullstendig: true` med `mistenkt_usladdet: []`. Verre:
# kontonummeret ved siden av BLE sladdet, så utdataen så mer
# tillitvekkende ut enn en der ingenting var fjernet.

NABOER = {
    "dato over": "Vedtaksdato: 15.03.2024\n{nr}\n",
    "dato foran": "Vedtaksdato: 15.03.2024 {nr}\n",
    "belop under": "{nr}\n12345,50 kroner\n",
    "belop foran": "Utbetalt 4 500 kr {nr}\n",
    "saksnr over": "Saksnummer 4711/2026\n{nr}\n",
    "nummer paa hver side": "Ref 2026-04\n{nr}\n900 kroner\n",
}


@pytest.mark.parametrize("sammenheng", sorted(NABOER))
def test_et_nabotall_skjuler_ikke_nummeret(sammenheng):
    """Navngitt per sammenheng, så en rød test sier HVILKEN nabo som
    spiste nummeret."""
    tekst = NABOER[sammenheng].format(nr=FNR)
    assert not _roper(_sladd(tekst), FNR), (
        f"nabotallet i «{sammenheng}» limte seg på og skjulte nummeret")


def test_naboen_selv_blir_staaende():
    """Motprøven. Å sladde datoen eller beløpet ville vært den andre
    feilen — lovlig innhold som forsvinner (R53)."""
    tekst = f"Vedtaksdato: 15.03.2024\n{FNR}\nUtbetalt 12345,50 kroner\n"
    sladdet = _sladd(tekst)
    assert "15.03.2024" in sladdet
    assert "12345,50" in sladdet
    assert not _roper(sladdet, FNR)


def test_naboliming_dikter_ikke_opp_et_nummer():
    """Vakten fra R53 må overleve oppdelingen: to nabotall som TILSAMMEN
    blir elleve siffer er ikke et fødselsnummer."""
    for tekst in ("Vedtak datert 01.01.2024 114 kroner",
                  "Fra 01.01.2024 til 02.02.2024",
                  "Fakturabelop kr 103 456 789"):
        assert not finn_sladdeomraader(tekst, ("fodselsnummer",)), tekst


def test_samme_nummer_i_ULIKE_former_i_samme_dokument():
    """Dokumentet skriver nummeret én gang med bindestrek og én gang
    ordrett. Begge må bort — den ene formen sladdet er ingen sladding."""
    tekst = (f"Fodselsnummer: {FNR[:6]}-{FNR[6:]}\n"
             f"Gjentatt: {FNR}\nOver linje: {FNR[:6]}\n{FNR[6:]}\n")
    assert not _roper(_sladd(tekst), FNR)


# ------------------------------------------------------------------ #
#  2. Speilet: lovlig innhold blir stående                             #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("tekst", [
    "Vedtaksdato: 04.03.2026 og frist 05.07.2026.",
    "Belop: kr 1 234,00. Sum: 12 345,00.",
    "Saksnummer 12345678 og journalnummer 2026001234.",
    "Perioden 01.01.2026-30.06.2026 gjelder.",
    "Kapittel 8-2 til 8-34 i folketrygdloven.",
    "Postnummer 0154 Oslo, gnr 123 bnr 45.",
])
def test_lovlig_innhold_staar_igjen(tekst):
    """Uten dette kunne «recall 1.00» oppnås ved å sladde alt.

    Den siste linja er den viktigste etter R145: bindestrek er nå et
    lovlig skilletegn INNE i et tall, og da må «01.01.2026-30.06.2026»
    fortsatt ikke bli lest som ett langt nummer."""
    assert _sladd(tekst) == tekst


def test_bindestreken_limer_ikke_sammen_to_nabotall():
    """Den nye risikoen, målt direkte: to tall skilt av en bindestrek
    skal ikke bli ett. Sjekksummen er siste port, men mønsteret skal
    ikke gi den sjansen i utrengsmål."""
    tekst = "Lopenummer 123456-78903 i arkivet."
    omraader = finn_sladdeomraader(tekst)
    # ingen påstand om at det ER en identifikator — bare at hvis det
    # sladdes, så er det fordi mod11 sa ja
    for start, slutt, _type in omraader:
        assert re.sub(r"\D", "", tekst[start:slutt]).isdigit()


# ------------------------------------------------------------------ #
#  3. Det som IKKE kan bevises — og som derfor må MELDES               #
# ------------------------------------------------------------------ #

def test_ocr_forvansket_nummer_kan_ikke_sladdes():
    """Dokumentert grense, ikke en feil. OCR leser «0» som «O», tallet
    består ikke mod11, og sladdingen fjerner bare det som kan BEVISES —
    en falsk positiv sletter lovlig innhold (R129).

    Men nummeret røper fortsatt personen for et menneskelig øye. Testen
    står her for at grensen skal være SKREVET NED og målt, ikke
    oppdaget av noen som leser et sladdet dokument."""
    forvansket = FNR.replace("0", "O", 1)
    assert forvansket != FNR
    tekst = f"Fodselsnummer: {forvansket}\n"
    assert forvansket in _sladd(tekst), (
        "hvis dette begynner å bli sladdet, er beviskravet endret — "
        "og da må R129 skrives om")

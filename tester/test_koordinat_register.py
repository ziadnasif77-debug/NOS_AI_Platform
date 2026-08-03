"""
Koordinat-registeret: broen fra et tegnområde i den flettede teksten
tilbake til boksene på siden.

Steg 1 av koordinatplanen (docs/plan_nye_evner.md): flett_regioner får
en registervariant, og teksten skal være BYTE-IDENTISK med før —
flett_regioner delegerer til registervarianten, så de kan ikke
divergere. Steg 2: skalprøven — et finner-treff i den flettede teksten
føres tilbake til riktige bokser, ende til ende, uten OCR.

Ren logikk på syntetiske regioner — ingen modeller, ingen GPU.
"""
import sys

sys.path.insert(0, ".")

from delt.region_ocr import (flett_regioner, flett_regioner_med_register,
                             regioner_for_omraade)
from delt.tekstuttrekk import finn_sladdeomraader


def _region(tekst, x0, y0, x1, y1, **ekstra):
    return {"boks": [x0, y0, x1, y1], "tekst": tekst, **ekstra}


# En liten «side»: to linjer, tre regioner på linje 1, to på linje 2.
# Merk region med innledende/avsluttende blanke — flettingen stripper.
SIDE = [
    _region("Org. Nr:", 40, 100, 190, 130),
    _region(" 889 000 007 ", 210, 102, 420, 131),
    _region("MVA", 440, 99, 520, 129),
    _region("Telefon:", 40, 180, 180, 210),
    _region("22 33 44 55", 200, 182, 400, 212),
]


# ------------------------------------------------------------------ #
#  Steg 1: byte-identitet og registerkorrekthet                        #
# ------------------------------------------------------------------ #

def test_tekst_er_byte_identisk_med_flett_regioner():
    tekst, _ = flett_regioner_med_register(SIDE)
    assert tekst == flett_regioner(SIDE)
    assert tekst == "Org. Nr: 889 000 007 MVA\nTelefon: 22 33 44 55"


def test_register_peker_paa_noyaktig_regionens_tegn():
    """Kontrakten: tekst[start:slutt] er PRESIS region['tekst'].strip()."""
    tekst, register = flett_regioner_med_register(SIDE)
    assert len(register) == len(SIDE)
    for start, slutt, region in register:
        assert tekst[start:slutt] == region["tekst"].strip()


def test_register_er_sortert_og_uten_overlapp():
    _, register = flett_regioner_med_register(SIDE)
    for (s1, e1, _), (s2, e2, _) in zip(register, register[1:]):
        assert e1 < s2, "register-områder skal være adskilt av skilletegn"


def test_tom_inn_gir_tom_ut():
    assert flett_regioner_med_register([]) == ("", [])
    assert flett_regioner([]) == ""


def test_regioner_uten_tekst_er_ikke_med():
    tekst, register = flett_regioner_med_register(
        [_region("  ", 0, 0, 10, 10), _region("NAV", 0, 0, 50, 10)])
    assert tekst == "NAV"
    assert len(register) == 1


def test_leserekkefolge_bevart_i_registeret():
    """Regioner gis i «feil» rekkefølge — flettingen sorterer topp→bunn,
    venstre→høyre, og registeret skal følge LESE-rekkefølgen."""
    stokket = [SIDE[4], SIDE[1], SIDE[3], SIDE[0], SIDE[2]]
    tekst, register = flett_regioner_med_register(stokket)
    assert tekst == "Org. Nr: 889 000 007 MVA\nTelefon: 22 33 44 55"
    assert [r["tekst"].strip() for _, _, r in register] == \
        ["Org. Nr:", "889 000 007", "MVA", "Telefon:", "22 33 44 55"]


# ------------------------------------------------------------------ #
#  Oppslaget                                                           #
# ------------------------------------------------------------------ #

def test_omraade_i_en_region():
    tekst, register = flett_regioner_med_register(SIDE)
    start = tekst.index("889")
    treff = regioner_for_omraade(register, start, start + 11)
    assert [r["tekst"].strip() for r in treff] == ["889 000 007"]


def test_omraade_over_flere_regioner():
    tekst, register = flett_regioner_med_register(SIDE)
    start = tekst.index("Org")
    treff = regioner_for_omraade(register, start, tekst.index("MVA") + 3)
    assert [r["tekst"].strip() for r in treff] == \
        ["Org. Nr:", "889 000 007", "MVA"]


def test_omraade_paa_skilletegn_gir_tomt():
    tekst, register = flett_regioner_med_register(SIDE)
    mellomrom = tekst.index(" 889")          # mellomrommet FØR tallet
    assert regioner_for_omraade(register, mellomrom, mellomrom + 1) == []


# ------------------------------------------------------------------ #
#  Steg 2: skalprøven — finner-treff → bokser, ende til ende           #
# ------------------------------------------------------------------ #

def test_skalproven_orgnr_til_boks():
    """Hele kjeden uten OCR: regioner → flettet tekst →
    finn_sladdeomraader (mod11-validert treff med posisjon) →
    regioner_for_omraade → riktig boks. Dette er beviset for at
    koordinatplanen henger sammen."""
    tekst, register = flett_regioner_med_register(SIDE)
    funn = [(s, e, t) for s, e, t in finn_sladdeomraader(tekst)
            if t == "organisasjonsnummer"]
    assert len(funn) == 1
    start, slutt, _ = funn[0]
    assert tekst[start:slutt] == "889 000 007"
    bokser = [r["boks"] for r in regioner_for_omraade(register, start, slutt)]
    assert bokser == [[210, 102, 420, 131]]


def test_skalproven_telefon_til_boks():
    tekst, register = flett_regioner_med_register(SIDE)
    funn = [(s, e, t) for s, e, t in finn_sladdeomraader(tekst)
            if t == "telefon"]
    assert len(funn) == 1
    start, slutt, _ = funn[0]
    bokser = [r["boks"] for r in regioner_for_omraade(register, start, slutt)]
    assert [200, 182, 400, 212] in bokser
    # etikett-regionen «Telefon:» skal IKKE være med
    assert [40, 180, 180, 210] not in bokser


def test_funn_paa_side_gir_type_tekst_og_bokser():
    """Modulen delt/koordinater: samme finnere som /sladd, med bokser."""
    from delt.koordinater import funn_paa_side
    funn = funn_paa_side(SIDE)
    typer = {f["type"]: f for f in funn}
    assert typer["organisasjonsnummer"]["tekst"] == "889 000 007"
    assert typer["organisasjonsnummer"]["bokser"] == [[210, 102, 420, 131]]
    assert typer["telefon"]["bokser"] == [[200, 182, 400, 212]]


def test_koordinater_for_sider_teller_og_deklarerer_rommet():
    from delt.koordinater import koordinater_for_sider
    svar = koordinater_for_sider(
        [{"side": 1, "bredde": 850, "hoyde": 1100, "regioner": SIDE},
         {"side": 2, "bredde": 850, "hoyde": 1100, "regioner": []}],
        "forbehandlet_bilde_piksler")
    assert svar["koordinatrom"] == "forbehandlet_bilde_piksler"
    assert svar["antall_funn"] == 2          # orgnr + telefon på side 1
    assert [s["side"] for s in svar["sider"]] == [1, 2]
    # side uten funn er MED — «ingen funn» er også et svar
    assert svar["sider"][1]["funn"] == []


def test_ord_regioner_fra_pdfside():
    """Tekstlagsveien: ordene fra PyMuPDF blir regioner på samme form,
    og kjeden helt til bokser virker på en ekte tekst-PDF."""
    import pytest
    fitz = pytest.importorskip("fitz")

    from delt.koordinater import funn_paa_side, ord_regioner_fra_pdfside
    doc = fitz.open()
    side = doc.new_page()
    side.insert_text((72, 100), "Org. Nr: 889 000 007")
    side.insert_text((72, 140), "Telefon: 22 33 44 55")
    regioner = ord_regioner_fra_pdfside(side)
    assert all(r["tekst"].strip() for r in regioner)
    funn = funn_paa_side(regioner)
    typer = {f["type"] for f in funn}
    assert "organisasjonsnummer" in typer
    assert "telefon" in typer
    for f in funn:
        for boks in f["bokser"]:
            assert len(boks) == 4
            x0, y0, x1, y1 = boks
            assert x1 > x0 and y1 > y0
            # PDF-punkter: innenfor en A4-side (595×842)
            assert 0 <= x0 <= 595 and 0 <= y1 <= 842
    doc.close()


def test_skalproven_treff_delt_over_to_regioner():
    """OCR deler ofte et gruppert nummer i to bokser — treffet skal da
    peke på BEGGE."""
    side = [
        _region("Kontonummer:", 40, 100, 220, 130),
        _region("1234.56", 240, 101, 350, 131),
        _region("00009", 360, 102, 460, 132),
    ]
    tekst, register = flett_regioner_med_register(side)
    # «1234.56 78910» → kompakt 12345678910, verifisert mod11-gyldig
    funn = [(s, e, t) for s, e, t in finn_sladdeomraader(tekst)
            if t == "kontonummer"]
    assert len(funn) == 1
    start, slutt, _ = funn[0]
    bokser = [r["boks"] for r in regioner_for_omraade(register, start, slutt)]
    assert len(bokser) == 2

"""
Tester for dokumentrutingen (delt/dokumentruting.py, R226).

En bunke er ikke ett dokument. Modellen hentet ekte verdier fra feil
dokument — fakturaens hjemmel som svar på et spørsmål om klagen — og
det er en feil en saksbehandler ikke kan se: svaret ser riktig ut.

Testene her holder på de to tingene som må stemme:

  * nevner spørsmålet ETT dokument, hentes svaret bare derfra
  * et sammensatt ord er ikke dokumentet — «klagefristen» spør om et
    avsnitt i VEDTAKET, og skal ikke rutes til klagebrevet
"""
import sys

import pytest

sys.path.insert(0, ".")

from delt import dokumentruting                                 # noqa: E402

BUNKE = "\n".join([
    "[Side 1 av 5]",
    "ARBEIDS- OG VELFERDSETATEN",
    "Vedtak om sykepenger",
    "Du kan klage innen seks uker, jf. forvaltningsloven paragraf 29.",
    "Kari Saksbehandler",
    "seniorraadgiver",
    "[Side 2 av 5]",
    "Vedlegg 1 - Beregning av sykepenger",
    "Dagsats 1 970",
    "[Side 3 av 5]",
    "Krav om tilbakebetaling - faktura",
    "Beloep aa betale kr 4 812,00",
    "[Side 4 av 5]",
    "Klage paa vedtak om arbeidsavklaringspengar",
    "Etter folketrygdlova paragraf 11-5 skal arbeidsevna vurderast.",
    "[Side 5 av 5]",
    "Returslipp - dokumentkontroll",
    "Legg denne sida oeverst.",
])


def _rut(sporsmal):
    return dokumentruting.rut(sporsmal, BUNKE)


# ---------- det feilen handlet om ----------
def test_klagen_hentes_fra_klagebrevet():
    """«Hvilken paragraf i folketrygdlova viser klagen til?» svarte
    22-15 — fakturaens hjemmel, fra et helt annet dokument."""
    r = _rut("Hvilken paragraf i folketrygdlova viser klagen til?")
    assert r is not None and r["type"] == "klage"
    assert r["sider"] == [4]


def test_vedtaket_hentes_fra_vedtaket():
    r = _rut("Hvilken tittel har den som undertegnet vedtaket?")
    assert r is not None and r["sider"] == [1, 2]


def test_returslippen_hentes_fra_returslippen():
    r = _rut("Hvor skal returslippen ligge i bunken?")
    assert r is not None and r["sider"] == [5]


# ---------- den skal ikke koste ett eneste riktig svar ----------
def test_sammensatt_ord_er_ikke_dokumentet():
    """«klagefristen» og «klageadgangen» spør om et avsnitt i VEDTAKET,
    ikke om klagebrevet. Begge var riktige før rutingen fantes, og en
    regel som bare lette etter «klage» ville gjort dem gale."""
    for spm in ("Hvor lang er klagefristen?",
                "Hvilken paragraf gjelder klageadgangen?",
                "Hva er fakturanummeret?",
                "Hvilken vedtaksdato staar i brevet?"):
        assert _rut(spm) is None, f"{spm!r} ble rutet"


def test_to_dokumenttyper_gir_ingen_ruting():
    """«Vedtaket som det klages på» nevner to — da vet vi ikke hvilket
    dokument spørsmålet gjelder, og en gjetning her ville vært den
    samme feilen vi retter."""
    for spm in ("Hvilken dato er vedtaket som det klages paa?",
                "Er det samme person som har faatt vedtaket og som klager?",
                "Hvem skal en klage paa vedtaket sendes til?"):
        assert _rut(spm) is None, f"{spm!r} ble rutet"


def test_sporsmaal_uten_dokumenttype_roeres_ikke():
    for spm in ("Hva er bruttobeloepet for juli 2026?",
                "Hvor mange sider har filen?",
                "Hvem er mottakeren?"):
        assert _rut(spm) is None


def test_ett_dokument_rutes_ikke():
    """Er hele filen ett dokument, er det ingenting å rute mellom."""
    ett = "[Side 1 av 1]\nKrav om tilbakebetaling - faktura\nkr 4 812,00"
    assert dokumentruting.rut("Hvem skal betale fakturaen?", ett) is None


def test_tom_tekst_er_trygg():
    assert dokumentruting.rut("Hvem skal betale fakturaen?", "") is None
    assert dokumentruting.rut("", BUNKE) is None


# ---------- flertydighet ----------
def test_to_dokumenter_av_samme_type_gir_ingen_ruting():
    """Har bunken to fakturaer, er «fakturaen» flertydig. Å velge én av
    dem ville vært nøyaktig den feilen rutingen er bygget for."""
    to = "\n".join([
        "[Side 1 av 3]", "Krav om tilbakebetaling - faktura", "kr 100,00",
        "[Side 2 av 3]", "Klage paa vedtak", "Eg klagar.",
        "[Side 3 av 3]", "Krav om tilbakebetaling - faktura", "kr 200,00",
    ])
    assert dokumentruting.rut("Hvem skal betale fakturaen?", to) is None
    # klagen er fortsatt entydig i den samme bunken
    assert dokumentruting.rut("Hva staar i klagen?", to)["sider"] == [2]


# ---------- formen ----------
def test_typer_i_sporsmal_er_deterministisk():
    spm = "Hva staar i klagen?"
    forst = dokumentruting.typer_i_sporsmal(spm)
    for _ in range(5):
        assert dokumentruting.typer_i_sporsmal(spm) == forst


@pytest.mark.parametrize("type_", sorted(dokumentruting.SPORSMAALSORD))
def test_hver_type_finnes_i_dokumenttypene(type_):
    """Et spørsmålsord uten en tilsvarende dokumenttype kan aldri rute
    noe — da er det dødt, og en vakt skal si fra."""
    from delt.tekstuttrekk import DOKUMENTTYPE_TERM
    assert type_ in DOKUMENTTYPE_TERM


# ------------------------------------------------------------------ #
#  Delingen — grensene er MÅLT, ikke gjettet (R234)                   #
# ------------------------------------------------------------------ #

def _del(tekst):
    from delt.dokumentprofil import del_i_dokumenter
    return [d["sider"] for d in del_i_dokumenter(tekst, None)]


def test_forblad_uten_tittel_hoerer_til_dokumentet_etter():
    """Brukerens EKTE kontoutskrift: side 1 er sammendragssiden og
    bærer ingen tittel, mens sidene 2-8 sier «Kontoutskrift for …».
    Uten adopsjonen ble side 1 et eget dokument — mens arket selv sier
    «Side 1 av 8». Side 1 bærer dessuten en TRANSAKSJONSDATO som ble
    lest som dokumentdato, så datoen må følge med adopsjonen."""
    bunke = "\n".join([
        "[Side 1 av 3]", "Ola Nordmann", "Sammendrag", "Saldo 1 234,00",
        "07.04.2026 Overfoering innland",
        "[Side 2 av 3]", "Kontoutskrift for 1234.56.78901",
        "Dato 30.04.2026",
        "[Side 3 av 3]", "Kontoutskrift for 1234.56.78901", "forts.",
    ])
    assert _del(bunke) == [[1, 2, 3]]


def test_to_utitulerte_sider_foran_en_tittel_er_eget_dokument():
    """Grensen «rett etter». Uten den adopterte en gruppe på to
    utitulerte sider typen til den TREDJE, og vedtaket, vedlegget og
    fakturaen i testbunken ble ETT dokument kalt «faktura»."""
    bunke = "\n".join([
        "[Side 1 av 3]", "ARBEIDS- OG VELFERDSETATEN", "Postboks 6600",
        "Vedtak om sykepenger",
        "[Side 2 av 3]", "Vedlegg 1 - Beregning", "Dagsats 1 970",
        "[Side 3 av 3]", "Krav om tilbakebetaling - faktura",
        "kr 4 812,00",
    ])
    assert _del(bunke) == [[1, 2], [3]]


def test_samme_type_men_ulik_dato_er_to_dokumenter():
    """Grensen «ingen type å motsi». En arkivbunke kan spenne over
    lovskiftet i 1997: to vedtak, 32 år fra hverandre, begge kunngjør
    «vedtak». Uten grensen ble de ETT dokument, og halve bunken fikk
    feil lovhjemmel."""
    from delt.dokumentprofil import del_i_dokumenter
    from delt.tekstuttrekk import klassifiser_datoer, sett_dato_roller
    bunke = "\n".join([
        "[Side 1 av 2]", "Vedtak om ufoerepensjon",
        "Vedtaksdato: 12.03.1994",
        "[Side 2 av 2]", "Vedtak om ufoeretrygd",
        "Vedtaksdato: 12.03.2026",
    ])
    datoer = sett_dato_roller(klassifiser_datoer(bunke))
    assert len(del_i_dokumenter(bunke, datoer)) == 2


def test_kontoutskrift_er_en_egen_dokumenttype():
    """Fra brukerens ekte dokumenter: typen manglet i lista, og fordi
    ett av arkene nevner «AvtaleGiro», traff mønsteret for «kontrakt»
    — en åtte siders kontoutskrift ble klassifisert som en avtale."""
    from delt.tekstuttrekk import DOKUMENTTYPE_TERM, gjett_dokumenttype
    assert gjett_dokumenttype(
        "Kontoutskrift for 1234.56.78901 Brukskonto\n"
        "AvtaleGiro belastet 30.04.2026") == "kontoutskrift"
    assert DOKUMENTTYPE_TERM["kontoutskrift"] == "Kontoutskrift"

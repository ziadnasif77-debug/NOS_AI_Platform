"""
Finnerfikser målt fram av en 10-siders syntetisk NAV-bunke (vedtak +
beregning + faktura + egenerklæring + legeerklæring + inntektsmelding +
endringsmelding + klage på nynorsk + returslipp).

Hver test her er en FEIL som faktisk skjedde på bunken — begge
leseveiene (tekstlag og OCR) ga samme gale felter, fordi feilene lå i
finnerne, ikke i lesingen. Utdragene under er ordrett fra dokumentet.
"""
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

from syntetiske_nummer import lag_dobbeltgyldig, lag_fnr
from delt.tekstuttrekk import (finn_alle_fodselsnummer,
                               finn_alle_kontonummer, finn_alle_telefoner,
                               finn_forfallsdato, finn_postnummer_sted,
                               finn_saksnummer, finn_telefon,
                               finn_totalbelop, sladd_tekst,
                               utvid_entiteter)


# ------------------------------------------------------------------ #
#  saksnummer: merket rent nummer slår skjemakode                      #
# ------------------------------------------------------------------ #

def test_merket_saksnummer_vinner_over_skjemakode():
    """«Saksnummer: 4417820» sto på fire sider — men skjemakoden
    «NAV 08-07.04» (som identifiserer BLANKETTEN, ikke saken) vant."""
    tekst = ("Dato: 12.05.2026\nSaksnummer: 4417820\n"
             "Skjema NAV 08-07.04 - Egenerklaering")
    assert finn_saksnummer(tekst) == "4417820"


def test_sakstilvising_nynorsk():
    assert finn_saksnummer("Sakstilvising: 5590114") == "5590114"


def test_skjemakode_fortsatt_siste_utvei():
    assert finn_saksnummer("skjema NAV 04-01.03 vedlagt") == "NAV 04-01.03"


def test_skraastrek_saksnummer_uendret():
    assert finn_saksnummer("Saksnr: 21/12345 behandles") == "21/12345"


# ------------------------------------------------------------------ #
#  postnummer: Postboks-nummer er ikke postnummer                      #
# ------------------------------------------------------------------ #

def test_postboks_stjeler_ikke_postnummeret():
    """NAVs egen adresselinje: postboksnummeret (6600) kom først i
    teksten og stjal feltet fra det ekte postnummeret på samme linje."""
    postnr, sted = finn_postnummer_sted(
        "Postboks 6600 Etterstad, 0607 OSLO - Telefon 55 55 33 33")
    assert (postnr, sted) == ("0607", "OSLO")


def test_vanlig_postnummer_uendret():
    assert finn_postnummer_sted("Adresse: Storgata 1, 0181 Oslo") == \
        ("0181", "Oslo")


# ------------------------------------------------------------------ #
#  telefon: 3-2-3-mobilform + fakturanummer-eksklusjon                 #
# ------------------------------------------------------------------ #

def test_mobil_i_323_form_fanges():
    """Personens faktiske mobil («+47 412 88 903», standard norsk
    mobilgruppering) ble aldri funnet — kun parvis gruppering fantes."""
    assert finn_telefon("Telefon +47 412 88 903") == "41288903"
    assert "41288903" in finn_alle_telefoner(
        "Telefon\n+47 412 88 903\nE-post ola@eksempel.no")


def test_fakturanummer_er_ikke_telefon():
    """«Fakturanummer: 90114882» BLE telefon — åtte sifre i strekk som
    starter på 9 ser ut som en mobil, men etiketten sier fakturanummer."""
    tekst = "Fakturanummer: 90114882   Fakturadato: 03.06.2026"
    assert finn_telefon(tekst) is None
    assert finn_alle_telefoner(tekst) == []


def test_parvis_telefon_uendret():
    assert finn_telefon("Ring oss på 22 33 44 55 i dag") == "22334455"


def test_sladding_dekker_mobilformen():
    sladdet, antall = sladd_tekst("Telefon +47 412 88 903")
    assert "[SLADDET telefon]" in sladdet
    assert "412 88 903" not in sladdet
    assert antall["telefon"] == 1


# ------------------------------------------------------------------ #
#  kontonummer vs fnr: etiketten vinner når begge sjekksummer stemmer  #
# ------------------------------------------------------------------ #

DOBBELTGYLDIG = lag_dobbeltgyldig()
REFUSJON = f"Refusjon utbetales til kontonummer: {DOBBELTGYLDIG}"


def test_merket_kontonummer_stjeles_ikke_av_fnr_presedensen():
    """Nummeret består BEGGE sjekksummene (gyldig som D-nummer). Uten
    etikettvakt ble refusjonskontoen rapportert som FØDSELSNUMMER og
    manglet helt i kontonummerlista."""
    assert DOBBELTGYLDIG in finn_alle_kontonummer(REFUSJON)
    assert DOBBELTGYLDIG not in finn_alle_fodselsnummer(REFUSJON)


def test_umerket_dobbeltgyldig_beholder_fnr_presedens():
    """Uten etikett i nærheten: fnr vinner som før — ingen stille
    endring av etablert presedens."""
    tekst = f"verdien {DOBBELTGYLDIG} står her uten etikett"
    assert DOBBELTGYLDIG in finn_alle_fodselsnummer(tekst)
    assert finn_alle_kontonummer(tekst) == []


def test_ekte_fnr_med_etikett_uendret():
    fnr = lag_fnr()
    tekst = f"Foedselsnummer: {fnr}"
    assert finn_alle_fodselsnummer(tekst) == [fnr]
    assert finn_alle_kontonummer(tekst) == []


# ------------------------------------------------------------------ #
#  totalbelop: fakturaform + tabellrad-fella                           #
# ------------------------------------------------------------------ #

def test_belop_aa_betale_er_totalbelop():
    """Kravbeløpet — det eneste UTFØRBARE beløpet i bunken — kom ikke
    ut som felt i det hele tatt."""
    assert finn_totalbelop("Beloep aa betale kr 4 812,00") == 4812.0
    assert finn_totalbelop("Beløp å betale\nkr 4 812,00") == 4812.0


def test_tabellrad_faller_ikke_videre_til_neste_linje():
    """«SUM 128 100 8 550 5 550 142 200» har sifre som ikke er beløp
    (ingen desimaler) — å falle videre gjorde NESTE linje («Beregnet
    maanedsinntekt: kr 47 400») til «totalbeløp»."""
    tekst = ("SUM 128 100 8 550 5 550 142 200\n"
             "Beregnet maanedsinntekt: kr 47 400")
    assert finn_totalbelop(tekst) is None


def test_hele_fakturaoppsettet_gir_kravbelopet():
    """Beregningstabellen (side 2) kommer FØR fakturaen (side 3) — SUM-
    raden skal hoppes over og kravbeløpet vinne."""
    tekst = ("SUM 129 254 130 76 239 177 891\n"
             "Grunnlag\n"
             "Sykepengegrunnlag per aar: kr 512 400\n"
             "BETALINGSINFORMASJON\n"
             "Beloep aa betale kr 4 812,00\n"
             "Forfallsdato 24.06.2026")
    assert finn_totalbelop(tekst) == 4812.0


def test_total_kr_paa_egen_linje_uendret():
    """Taxikvitteringens form (R62) skal fortsatt virke."""
    assert finn_totalbelop("Total Kr:\n486,00") == 486.0


# ------------------------------------------------------------------ #
#  forfallsdato: nytt felt                                             #
# ------------------------------------------------------------------ #

def test_forfallsdato_fra_faktura():
    assert finn_forfallsdato("Forfallsdato 24.06.2026") == "2026-06-24"
    assert finn_forfallsdato("Betalingsfrist: 01.07.2026") == "2026-07-01"


def test_forfallsdato_er_med_i_felteruttrekket():
    tekst = ("Beloep aa betale kr 4 812,00\n"
             "Forfallsdato 24.06.2026\n"
             "KID: 1002345678911")
    felter = utvid_entiteter(tekst, {})
    assert felter["forfallsdato"] == "2026-06-24"
    assert felter["totalbelop"] == 4812.0


def test_uten_forfall_ingen_dato():
    assert finn_forfallsdato("Dato: 12.05.2026") is None


# ------------------------------------------------------------------ #
#  KID-etiketten: «KID-nummer» er standardformen på norske fakturaer   #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("tekst", [
    "KID: 1002345678911",
    "KID-nummer 1002345678911",
    "KID-nummer: 1002345678911",
    "KIDnummer 1002345678911",
    "KID nr. 1002345678911",
])
def test_kid_etikettformer(tekst):
    """«KID-nummer 1002345678911» ga INGEN treff — fakturaen i bunken ble
    bare reddet av at samme side tilfeldigvis også har en bar «KID:»."""
    from delt.tekstuttrekk import finn_alle_kid
    assert finn_alle_kid(tekst) == ["1002345678911"]


def test_kid_uten_etikett_er_ikke_kid():
    """Et løst tall er for tvetydig — etikettkravet står."""
    from delt.tekstuttrekk import finn_alle_kid
    assert finn_alle_kid("referanse 1002345678911 i saken") == []


def test_sladding_dekker_kid_nummer_formen():
    sladdet, antall = sladd_tekst("KID-nummer 1002345678911")
    assert "1002345678911" not in sladdet
    assert "KID" in sladdet          # etiketten står igjen
    assert antall["kid"] == 1

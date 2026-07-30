"""
Tester for R53 — tre feil funnet på en ekte, fotografert taxikvittering
der OCR hadde mistet desimalkommaet og «DATO» var lest som «1970».

Feilene var uavhengige, men slo ut samtidig:
  1) «NOK 463 00» ble tolket som 46300 — hundre ganger for mye, fordi
     mellomrom ble regnet som tusenskille uten å kreve tregrupper
  2) fødselsnummer var ikke validert i skjemautfyllingen, så løyvenummer
     «N02272» kom uimotsagt gjennom
  3) datofelter var ikke validert, så «1970 12 06 2026» ble stående

Ren logikk — ingen modeller, ingen tjenester.
"""
import sys

sys.path.insert(0, ".")

import pytest

from delt.tekstuttrekk import finn_alle_belop, finn_belop


# ------------------------------------------------------------------ #
#  1) Tusenskille krever tregrupper                                   #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("tekst,forventet", [
    # Selve regresjonen: OCR mistet kommaet i «463,00»
    ("PRIS NOK 463 00", 463.0),
    ("TOTAL NOK 486 00", 486.0),
    # Ekte tusenskille skal fortsatt virke
    ("utbetalt kr 12 345,50 per måned", 12345.50),
    ("kr 46 300", 46300.0),
    ("kr 1 234 567,00", 1234567.00),
    ("beløp: NOK 5000", 5000.0),
    ("sum 12.345,- totalt", 12345.0),
    # Punktum som tusenskille krever også tre sifre
    ("NOK 463.00", 463.0),
    ("NOK 46.300", 46300.0),
])
def test_belop_krever_tregrupper(tekst, forventet):
    assert finn_belop(tekst) == forventet


@pytest.mark.parametrize("tekst,forventet", [
    # R60, funnet av regresjonskorpuset: OCR leser null som bokstaven O
    # på håndskrift og matriseskrift. «kr 15 000» ble til 15 — tusen
    # ganger for lite i et beløpsfelt.
    ("Beløp jeg søker om: kr 15 OOO per måned", 15000.0),
    ("NOK 1 OOO OOO", 1000000.0),
    ("kr 2 5OO", 2500.0),
    # Skal fortsatt virke som før
    ("kr 15 000 per måned", 15000.0),
    ("kr 12 345,50", 12345.50),
])
def test_o_leses_som_null_i_belop(tekst, forventet):
    assert finn_belop(tekst) == forventet


@pytest.mark.parametrize("tekst", [
    "Reise til NOK OSLO by",
    "kr OOO",
])
def test_bokstaver_alene_blir_ikke_belop(tekst):
    """O godtas bare INNE i en tregruppe etter et tall — løpende tekst
    skal aldri kunne bli til et kronebeløp."""
    assert finn_belop(tekst) is None


@pytest.mark.parametrize("tekst,forventet", [
    # Funnet i systemrevisjonen: den VANLIGSTE norske skrivemåten manglet.
    # Uten valutaord FORAN og uten desimaler traff verken prefiks-regelen
    # eller tusenskille-med-desimaler-regelen — «12 500 kroner» ga INGEN
    # beløp, og skjemautfyllingen mistet grunnlaget sitt.
    ("Du får utbetalt 12 500 kroner i måneden", 12500.0),
    ("Beløpet er 15 000 kr", 15000.0),
    ("Sum 500 NOK", 500.0),
    ("Totalt 1 250 000 kroner", 1250000.0),
    ("Egenandel 250 kroner", 250.0),
    ("Beløp 1 234,50 kroner", 1234.50),
    ("Du skylder 12 500kr", 12500.0),          # uten mellomrom
])
def test_valutaord_ETTER_belopet(tekst, forventet):
    assert finn_belop(tekst) == forventet
    assert finn_alle_belop(tekst)[0]["verdi"] == forventet


@pytest.mark.parametrize("tekst", [
    # Suffiks-regelen må ikke gjøre løpende tall til beløp: valutaordet
    # er ankeret, akkurat som i prefiks-regelen.
    "Saksnummer 900123 i systemet",
    "Telefon 97335868",
    "Året 2026 var bra",
    "Postnummer 0150 OSLO",
    "Født 03.04.1985",
    "Vedtaksdato 12.06.2026",
    "Org.nr 923609016",
    "Side 3 av 12",
])
def test_tall_uten_valutaord_blir_ikke_belop(tekst):
    assert finn_belop(tekst) is None
    assert finn_alle_belop(tekst) == []


def test_alle_belop_paa_kvitteringstekst():
    """Hele kvitteringslinjene slik OCR faktisk leste dem: ingen av
    kronebeløpene skal blåses opp med en faktor hundre."""
    tekst = ("PRIS NOK 463 00\n"
             "+FORHAND NOK 23 00\n"
             "TOTAL NOK 486 00\n"
             "HERAV MVA12% NOK 52,07\n"
             "STARTPRIS NOK 100 00\n")
    verdier = [b["verdi"] for b in finn_alle_belop(tekst)]
    assert 463.0 in verdier
    assert 486.0 in verdier
    assert 52.07 in verdier
    assert all(v < 10_000 for v in verdier), (
        "et beløp ble hundredoblet: %r" % verdier)


# ------------------------------------------------------------------ #
#  2) og 3) Validering i skjemautfyllingen                            #
# ------------------------------------------------------------------ #

@pytest.fixture(scope="module")
def rens():
    """Henter rens_skjemasvar fra API-modulen uten å starte serveren."""
    sys.path.insert(0, "skript")
    import dokument_api
    return dokument_api.rens_skjemasvar


def _lag_gyldig_fnr() -> str:
    """Syntetisk fnr med korrekte kontrollsifre, beregnet uavhengig av
    implementasjonen som testes."""
    v1 = [3, 7, 6, 1, 8, 9, 4, 5, 2]
    v2 = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    for basis in range(10_000_000, 10_100_000):
        ni = f"01019{basis % 100000:05d}"[:9]
        s1 = sum(int(ni[i]) * v1[i] for i in range(9))
        k1 = (11 - s1 % 11) % 11
        if k1 == 10:
            continue
        ti = ni + str(k1)
        s2 = sum(int(ti[i]) * v2[i] for i in range(10))
        k2 = (11 - s2 % 11) % 11
        if k2 == 10:
            continue
        return ti + str(k2)
    raise AssertionError("fant ikke et gyldig fnr")


def test_loyvenummer_avvises_som_fodselsnummer(rens):
    """Selve regresjonen: «N02272» fra en taxikvittering er ikke et
    fødselsnummer og skal tømmes med en forklaring."""
    mal = {"fodselsnummer": None}
    svar = {"fodselsnummer": "N02272"}
    renset, avvik = rens(mal, svar, "LØYVE NR: N02272")

    assert renset["fodselsnummer"] == ""
    assert any("fødselsnummer" in a for a in avvik)


def test_gyldig_fodselsnummer_slipper_gjennom(rens):
    """Valideringen skal ikke ramme et ekte fødselsnummer."""
    fnr = _lag_gyldig_fnr()
    renset, avvik = rens({"fodselsnummer": None},
                         {"fodselsnummer": fnr},
                         "Fødselsnummer: " + fnr)

    assert renset["fodselsnummer"] == fnr
    assert avvik == []


def test_soppel_i_datofelt_avvises(rens):
    """«1970 12 06 2026» oppsto da OCR leste «DATO» som «1970».
    Det er ingen dato og skal ikke bli stående."""
    dok = "1970 12 06 2026 KL START 14 28"
    renset, avvik = rens({"dato": None}, {"dato": "1970 12 06 2026"}, dok)

    assert renset["dato"] == ""
    assert any("dato" in a.lower() for a in avvik)


def test_gyldig_dato_beholdes(rens):
    renset, avvik = rens({"dato": None}, {"dato": "12.06.2026"},
                         "DATO : 12.06.2026")

    assert renset["dato"] == "12.06.2026"
    assert avvik == []


def test_normalisert_dato_avvises_ikke_av_tallvakten(rens):
    """Datoen står i dokumentet som «12/06/2026», men modellen svarer på
    normalform «12.06.2026». Tallvakten krever eksakt token-treff, og
    felte derfor en korrekt lest dato som «tall som ikke står i
    dokumentet» — to sikkerhetsmekanismer som slo hverandre i hjel.

    Utdraget er ordrett fra OCR-en av en ekte taxikvittering, der
    datolinjen øverst i tillegg var forvansket til «1970 12 06 2026».
    """
    dok = ("TELEFON 97335868\n1970 12 06 2026\nKL START 14 28\n"
           "Bax 17415948-753230\n12/06/2026 14 :46\n")
    renset, avvik = rens({"dato": None}, {"dato": "12.06.2026"}, dok)

    assert renset["dato"] == "12.06.2026"
    assert avvik == []


def test_nullore_regnes_som_samme_belop(rens):
    """OCR leste «+FORHÅND NOK 23,00» som «#FORHAND NOK 23 Q» — ørene
    ble til en Q. Beløpet 23,00 ER i dokumentet; at ørene er null gjør
    det til samme tall som «23», og skal ikke felles av tallvakten."""
    dok = "PRIS NOK 463 00\n#FORHAND NOK 23 Q\nTOTAL NOK 486 00\n"
    renset, avvik = rens({"forhand": None}, {"forhand": "NOK 23,00"}, dok)

    assert renset["forhand"] == "NOK 23,00"
    assert avvik == []


def test_ore_som_ikke_er_null_maa_staa_ordrett(rens):
    """Unntaket gjelder bare nullører. Et endret ørebeløp skal fortsatt
    fanges — ellers kunne modellen justere kronebeløp ustraffet."""
    dok = "PRIS NOK 463 00\n#FORHAND NOK 23 Q\n"
    renset, avvik = rens({"forhand": None}, {"forhand": "NOK 23,50"}, dok)

    assert renset["forhand"] == ""
    assert any("ikke står i dokumentet" in a for a in avvik)


def test_helt_annet_belop_avvises_selv_med_nullore(rens):
    """«2300,00» er ikke «23» — heltallsdelen må selv finnes i kilden."""
    dok = "#FORHAND NOK 23 Q\n"
    renset, avvik = rens({"forhand": None}, {"forhand": "2300,00"}, dok)

    assert renset["forhand"] == ""
    assert avvik != []


def test_tallvakten_stopper_fortsatt_oppdiktede_tall(rens):
    """Unntaket for datoer skal ikke ha åpnet en dør: et beløp modellen
    har regnet seg fram til skal fortsatt fanges."""
    dok = "SUM 268,00 kroner inkludert mva"
    renset, avvik = rens({"belop": None}, {"belop": "296,71"}, dok)

    assert renset["belop"] == ""
    assert any("ikke står i dokumentet" in a for a in avvik)

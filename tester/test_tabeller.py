"""
Tester for tabellgjenoppbyggingen (delt/tabeller.py, R219).

Feilen som ga opphav til modulen var ikke at modellen diktet — den
hentet ekte tall fra feil kolonne, fordi kolonnene ikke fantes lenger i
teksten den fikk. Testene her holder på det som faktisk må stemme:

  * en verdi havner i kolonnen den STÅR i, ikke den den telles til
  * en rad med hull forskyver ikke resten av raden
  * løpende tekst blir ikke feilaktig til en tabell

Ordene skrives som (x0, y0, x1, tekst) — samme form som PyMuPDFs
`get_text("words")` og OCR-regionenes bokser, så modulen kan mates fra
begge veier.
"""
import sys

import pytest

sys.path.insert(0, ".")

from delt import tabeller                                       # noqa: E402


def _ord(rader):
    """(y, [(x, tekst), …]) → flat ordliste. Bredden anslås fra teksten."""
    ut = []
    for y, celler in rader:
        for x, tekst in celler:
            for bit in tekst.split(" "):
                ut.append((x, y, x + 5.0 * len(bit), bit))
                x += 5.0 * len(bit) + 2.0
    return ut


# Beregningstabellen fra korpusdokumentet, med de EKTE x-posisjonene
# målt i PDF-en. SUM-raden mangler «Dagsats» — det er hele poenget.
BEREGNING = _ord([
    (117, [(57, "Maaned"), (156, "Dager"), (213, "Dagsats"),
           (283, "Bruttobeloep"), (369, "Skattetrekk"), (454, "Nettobeloep")]),
    (140, [(57, "April 2026"), (156, "21"), (213, "1 970"),
           (283, "41 370"), (369, "12 411"), (454, "28 959")]),
    (163, [(57, "Mai 2026"), (156, "20"), (213, "1 970"),
           (283, "39 400"), (369, "11 820"), (454, "27 580")]),
    (186, [(57, "Juli 2026"), (156, "23"), (213, "1 970"),
           (283, "45 310"), (369, "13 593"), (454, "31 717")]),
    (240, [(57, "SUM"), (156, "129"),
           (283, "254 130"), (369, "76 239"), (454, "177 891")]),
])


@pytest.fixture
def tabell():
    funnet = tabeller.finn_tabeller(BEREGNING)
    assert len(funnet) == 1, f"forventet én tabell, fikk {len(funnet)}"
    return funnet[0]


def _rad(tabell, forste_celle):
    for rad in tabell["rader"]:
        if rad[0].strip() == forste_celle:
            return dict(zip(tabell["overskrifter"], rad))
    raise AssertionError(f"fant ingen rad som starter med {forste_celle!r}")


# ---------- det feilen handlet om ----------
def test_verdien_havner_i_kolonnen_den_staar_i(tabell):
    """Juli har brutto 45 310 og netto 31 717 — modellen svarte 31 717
    på bruttospørsmålet. Begge tall er ekte; bare kolonnen var feil."""
    juli = _rad(tabell, "Juli 2026")
    assert juli["Bruttobeloep"] == "45 310"
    assert juli["Nettobeloep"] == "31 717"
    assert juli["Dager"] == "23"


def test_hull_i_raden_forskyver_ikke_resten(tabell):
    """SUM-raden har ingen dagsats. Teller man celler, blir 254 130 til
    «Dagsats» og alt etter den forskjøvet — som var nøyaktig feilen.
    Med x-posisjonen står hver verdi der den hører hjemme, og den tomme
    kolonnen blir borte i stedet for å dytte."""
    sum_rad = _rad(tabell, "SUM")
    assert sum_rad["Bruttobeloep"] == "254 130"
    assert sum_rad["Nettobeloep"] == "177 891"
    assert sum_rad["Dager"] == "129"
    assert sum_rad["Dagsats"] == "", "tom celle skal være tom, ikke arve"


def test_overskriftene_blir_kjent_igjen_som_overskrifter(tabell):
    assert tabell["overskrifter"][0] == "Maaned"
    assert "Bruttobeloep" in tabell["overskrifter"]
    # Overskriftsraden skal IKKE også ligge som datarad.
    assert all(rad[0] != "Maaned" for rad in tabell["rader"])


def test_tekstformen_navngir_hver_verdi(tabell):
    """Modellen skal ikke trenge å telle noe som helst."""
    tekst = tabeller.som_tekst(tabell)
    assert "Bruttobeloep: 45 310" in tekst
    assert "Bruttobeloep: 254 130" in tekst
    # Den tomme cellen nevnes ikke — den har ingen verdi å oppgi.
    assert "Dagsats:" not in tekst.splitlines()[-1]


# ---------- den skal ikke se tabeller overalt ----------
def test_lopende_tekst_blir_ikke_tabell():
    """Et vedtaksbrev er ikke en tabell selv om linjene er like lange."""
    avsnitt = _ord([
        (100, [(57, "Vi har innvilget soeknaden din om sykepenger")]),
        (114, [(57, "fra og med 1. april 2026. Vedtaket bygger paa")]),
        (128, [(57, "folketrygdloven kapittel 8.")]),
    ])
    assert tabeller.finn_tabeller(avsnitt) == []


def test_to_korte_rader_er_ikke_nok():
    """Under minstekravet skal den holde seg i ro — to linjer som
    tilfeldigvis stiller opp er ikke en tabell."""
    to = _ord([
        (100, [(57, "Navn"), (200, "Ola"), (300, "Nordmann")]),
        (120, [(57, "Sak"), (200, "4417820"), (300, "aktiv")]),
    ])
    assert tabeller.finn_tabeller(to) == []


def test_tom_inndata_gir_ingenting():
    assert tabeller.finn_tabeller([]) == []
    assert tabeller.tabelltekst_for_side([]) == ""


# ---------- formen på utdata ----------
def test_vedlegget_merkes_saa_det_ikke_forveksles_med_dokumentteksten():
    ut = tabeller.tabelltekst_for_side(BEREGNING)
    assert ut.startswith("[TABELL:")
    assert "Maaned" in ut.splitlines()[0]


def test_ord_uten_tekst_hoppes_over():
    """Tomme ord finnes i ekte PDF-er og skal ikke lage tomme celler."""
    med_tomme = BEREGNING + [(600.0, 186.0, 601.0, "   ")]
    funnet = tabeller.finn_tabeller(med_tomme)
    assert len(funnet) == 1
    assert funnet[0]["kolonner"] == 6


def test_deterministisk(tabell):
    """R6: samme inndata, samme utdata — hver gang."""
    en = tabeller.tabelltekst_for_side(BEREGNING)
    for _ in range(5):
        assert tabeller.tabelltekst_for_side(BEREGNING) == en


# ---------- adapteren mot PyMuPDF ----------
class _FalskSide:
    def __init__(self, ord_=None, sprenger=False):
        self._ord = ord_ or []
        self._sprenger = sprenger

    def get_text(self, hva=None):
        if self._sprenger:
            raise RuntimeError("ordhenting feilet")
        return [(x0, y0, x1, y0 + 10, t, 0, 0, 0)
                for x0, y0, x1, t in self._ord]


def test_med_tabeller_gir_kolonnenavn_paa_verdiene():
    flat = "Vedlegg 1 - Beregning\nJuli 2026\n23\n45 310"
    ut = tabeller.med_tabeller(_FalskSide(BEREGNING), flat)
    assert "Bruttobeloep: 45 310" in ut
    assert "Bruttobeloep: 254 130" in ut


def test_hvert_tall_staar_bare_en_gang():
    """Regresjonen som kostet fire riktige svar.

    Første versjon la tabellen VED den flate teksten. Da sto hvert tall
    to ganger, side 2 og 6 fikk dobbelt så mange tall, og fire spørsmål
    som var riktige før — tre av dem om datoer — begynte å feile. Netto
    gevinst null. Teksten skal bære tallet én gang, med navn."""
    ut = tabeller.med_tabeller(_FalskSide(BEREGNING), "Beregning\n45 310")
    assert ut.count("45 310") == 1
    assert ut.count("177 891") == 1
    assert ut.count("31 717") == 1


def test_ingen_ord_forsvinner():
    """Erstatning er bare forsvarlig hvis den ikke mister noe. Hvert ord
    fra tabellen skal finnes igjen i den nye teksten."""
    ut = tabeller.med_tabeller(_FalskSide(BEREGNING), "Beregning av sykepenger")
    for _x0, _y0, _x1, ord_ in BEREGNING:
        assert ord_ in ut, f"ordet {ord_!r} forsvant i rekonstruksjonen"


def test_side_uten_tabell_faar_teksten_uendret():
    """Vi bytter ikke ut `get_text()` for sider som ikke trenger det."""
    flat = "Bare loepende tekst."
    assert tabeller.med_tabeller(_FalskSide([]), flat) == flat
    løpende = _ord([
        (100, [(57, "Vi har innvilget soeknaden din om sykepenger")]),
        (114, [(57, "fra og med 1. april 2026. Vedtaket bygger paa")]),
        (128, [(57, "folketrygdloven kapittel 8.")]),
    ])
    assert tabeller.med_tabeller(_FalskSide(løpende), flat) == flat


def test_tekst_utenfor_tabellen_blir_med():
    """Linjer som ikke er tabell, skal gjengis — ikke klippes bort."""
    blandet = BEREGNING + _ord([
        (300, [(57, "Utbetalingsmaate: bankkonto")]),
        (320, [(57, "Utbetalingsdag: den 25. i maaneden")]),
    ])
    ut = tabeller.sidetekst(blandet)
    assert "Utbetalingsmaate: bankkonto" in ut
    assert "Utbetalingsdag: den 25. i maaneden" in ut
    assert "Bruttobeloep: 45 310" in ut


def test_overskriftsraden_forsvinner_ikke_fra_teksten():
    ut = tabeller.sidetekst(BEREGNING)
    assert "[TABELL:" in ut
    assert "Bruttobeloep" in ut.splitlines()[0]


def test_kortere_rekonstruksjon_gir_originalen_tilbake(monkeypatch):
    """Sikkerhetsnettet: mister rekonstruksjonen innhold, beholdes den
    originale teksten. Bedre en flat tabell enn en side med hull."""
    monkeypatch.setattr(tabeller, "sidetekst", lambda _o: "nesten ingenting")
    lang = "A" * 4000
    assert tabeller.med_tabeller(_FalskSide(BEREGNING), lang) == lang


def test_feil_i_ordhentingen_koster_ikke_dokumentet():
    """En tabell vi ikke klarer å bygge skal gi teksten tilbake — ikke
    et unntak som velter hele analysen."""
    flat = "Viktig innhold som IKKE skal forsvinne."
    assert tabeller.med_tabeller(_FalskSide(sprenger=True), flat) == flat

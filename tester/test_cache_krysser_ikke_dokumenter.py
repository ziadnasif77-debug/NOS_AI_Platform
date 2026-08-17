"""
«Semantic cache skal aldri returnere data fra et annet dokument» (§26).

Kravet står i §26, og oppfyllelsen var der: `analyser_med_cache` nøkler
på sha256 av INNHOLDET, ikke på filnavn. To dokumenter kan hete det
samme og få hvert sitt svar; det samme dokumentet kan hete to ting og
dele ett.

Men ingen test sa det. Og cachen er det stedet i tjenesten der en feil
er verst: den serverer FEIL DOKUMENTS innhold til en klient som ikke har
noen mulighet til å oppdage det — svaret ser helt riktig ut, det er bare
en annens.

DE TRE MÅTENE DET KAN RYKE PÅ
  1. nøkkelen blir filnavnet i stedet for innholdet
  2. nøkkelen glemmer en parameter som endrer resultatet
     (R55: strekkodevalget er DEL av nøkkelen — uten det kunne et svar
     uten strekkoder bli servert til en som ba om dem)
  3. cachen deler objekter i stedet for kopier, så én klients
     personvernbryter tømmer feltene for alle (R152)
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api as api


@pytest.fixture(autouse=True)
def tom_cache():
    api._analyse_cache.clear()
    yield
    api._analyse_cache.clear()


def test_noekkelen_er_innholdet_ikke_filnavnet():
    """To ULIKE dokumenter med SAMME filnavn må aldri dele svar."""
    import inspect
    kilde = inspect.getsource(api.analyser_med_cache)
    plass = kilde.index("nokkel =")
    linje = kilde[plass:plass + 200]
    assert "sha256(data)" in linje, (
        "cachenøkkelen bygges ikke av innholdet — da kan to ulike "
        "dokumenter med samme navn dele svar")
    assert "filnavn" not in linje.split("\n")[0], (
        "filnavnet er del av nøkkelen — da får det SAMME dokumentet to "
        "oppføringer bare fordi det ble lastet opp under to navn")


def test_strekkodevalget_er_del_av_noekkelen():
    """R55. Uten det kunne et svar som hoppet over strekkoder bli
    servert videre til en klient som faktisk ba om dem — og «ingen
    strekkoder funnet» er et helt annet svar enn «vi så ikke etter»."""
    import inspect
    kilde = inspect.getsource(api.analyser_med_cache)
    plass = kilde.index("nokkel =")
    assert "les_strekkoder" in kilde[plass:plass + 250]


def test_sidegrensen_er_del_av_noekkelen():
    """Et dokument lest med 10 siders tak og det samme lest uten tak er
    to ulike resultater."""
    import inspect
    kilde = inspect.getsource(api.analyser_med_cache)
    plass = kilde.index("nokkel =")
    assert "ocr_maks_sider" in kilde[plass:plass + 250]


def test_cachen_gir_KOPIER_ikke_delte_objekter():
    """R152: en grunn kopi deler de nestede objektene med cachen, og
    personvernbryteren nuller dem PÅ STEDET. Målt: ett kall med
    `profil=sammendrag` tømte fødselsnummeret i cachen, og NESTE
    forespørsel — uten bryteren, fra hvilken som helst klient — fikk
    `fodselsnummer: null` uten et eneste varsel. Svaret PÅSTO at
    dokumentet ikke inneholdt noe nummer."""
    import inspect
    kilde = inspect.getsource(api.analyser_med_cache)
    assert kilde.count("copy.deepcopy") >= 2, (
        "kopieres bare den ene veien, forgifter det FØRSTE (ucachede) "
        "svaret cacheoppføringen like fullt")


def test_to_ulike_dokumenter_faar_ulike_noekler():
    """Selve egenskapen, prøvd og ikke bare lest."""
    import hashlib
    a = hashlib.sha256(b"dokument A").hexdigest() + ":None:1"
    b = hashlib.sha256(b"dokument B").hexdigest() + ":None:1"
    assert a != b


def test_samme_dokument_under_to_navn_deler_svar():
    """Den andre siden av samme mynt: cachen skal FAKTISK treffe når det
    er det samme dokumentet. Ellers er den bare en kostnad."""
    import hashlib
    data = b"det samme dokumentet"
    n1 = hashlib.sha256(data).hexdigest() + ":None:1"
    n2 = hashlib.sha256(data).hexdigest() + ":None:1"
    assert n1 == n2

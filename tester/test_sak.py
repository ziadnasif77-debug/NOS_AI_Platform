"""
R242: saken på tvers av filer — hva som binder dokumenter sammen.

Kjernepåstanden modulen er bygget på, og som testene her vokter: et
saksnummer beviser samme SAK, et fødselsnummer beviser samme PERSON, og
de to er ikke det samme. Én person kan ha sykepenger, dagpenger og en
tilbakebetaling gående samtidig — tre saker, ett fødselsnummer. Slår man
sammen på person, blir tre saker til én, og «hva ble utfallet?» får ett
svar der det finnes tre. Sammenblandingen ser dessuten riktig ut, for
alle dokumentene gjelder jo samme person. Det er den farlige sorten.
"""
import sys

sys.path.insert(0, ".")

from delt import sak as s
from tester.syntetiske_nummer import lag_fnr

# Bygges på kjøretid, aldri skrevet som tall i kildekoden: et ellevesifret
# tall SER ut som et fødselsnummer uansett hvor syntetisk det er ment å
# være, og en fil på GitHub leses av folk som ikke kjenner opprinnelsen.
FNR = lag_fnr()
ANNET_FNR = lag_fnr(1)


def dok(**felt):
    """Et dokument slik `del_i_dokumenter` former dem, med saksfeltene
    kalleren har trukket ut."""
    grunn = {"filnavn": "a.pdf", "tittel": None, "dato": None,
             "type": None, "sider": []}
    return {**grunn, **felt}


# ------------------------------------------------------------------ #
#  Gruppering på saksnøkkel                                           #
# ------------------------------------------------------------------ #

def test_samme_saksnummer_er_samme_sak():
    saker = s.grupper_i_saker([
        dok(filnavn="soknad.pdf", saksnummer="4417820"),
        dok(filnavn="vedtak.pdf", saksnummer="4417820"),
    ])
    assert len(saker) == 1
    assert saker[0]["nokkel"] == {"felt": "saksnummer", "verdi": "4417820"}
    assert len(saker[0]["dokumenter"]) == 2


def test_ulikt_saksnummer_er_ulike_saker():
    saker = s.grupper_i_saker([
        dok(filnavn="a.pdf", saksnummer="4417820"),
        dok(filnavn="b.pdf", saksnummer="9990001"),
    ])
    assert len(saker) == 2


def test_mellomrom_i_saksnummer_lager_ikke_to_saker():
    """«44 17 820» og «4417820» er samme nummer. Et skille som bare
    finnes i skrivemåten skal ikke bli et skille i saken."""
    saker = s.grupper_i_saker([
        dok(filnavn="a.pdf", saksnummer="44 17 820"),
        dok(filnavn="b.pdf", saksnummer="4417820"),
    ])
    assert len(saker) == 1


def test_bindingen_er_transitiv():
    """A og B deler saksnummer, B og C deler journalnummer. Alle tre er
    samme sak — det er slik en mappe henger sammen når dokumentene bærer
    ulike nøkler."""
    saker = s.grupper_i_saker([
        dok(filnavn="a.pdf", saksnummer="4417820"),
        dok(filnavn="b.pdf", saksnummer="4417820", journalnummer="12/3456"),
        dok(filnavn="c.pdf", journalnummer="12/3456"),
    ])
    assert len(saker) == 1
    assert len(saker[0]["dokumenter"]) == 3


def test_saken_navngis_etter_den_sterkeste_nokkelen():
    saker = s.grupper_i_saker([
        dok(filnavn="a.pdf", saksnummer="4417820", journalnummer="12/3456"),
    ])
    assert saker[0]["nokkel"]["felt"] == "saksnummer"


def test_grunnlaget_sier_hvorfor():
    """Ingen gruppering uten en begrunnelse et menneske kan etterprøve —
    samme krav som resten av huset stiller til et bevis."""
    saker = s.grupper_i_saker([
        dok(filnavn="a.pdf", saksnummer="4417820"),
        dok(filnavn="b.pdf", saksnummer="4417820"),
    ])
    assert "4417820" in saker[0]["grunnlag"]
    assert "2 av 2" in saker[0]["grunnlag"]


# ------------------------------------------------------------------ #
#  Det som IKKE binder                                                #
# ------------------------------------------------------------------ #

def test_dokument_uten_saksnokkel_star_alene_og_sier_hvorfor():
    saker = s.grupper_i_saker([
        dok(filnavn="a.pdf", saksnummer="4417820"),
        dok(filnavn="lost.pdf"),
    ])
    assert len(saker) == 2
    lost = [x for x in saker if x["nokkel"] is None]
    assert len(lost) == 1
    assert lost[0]["grunn"] == s.UTEN_SAKSNOKKEL
    assert "ikke bevist" in lost[0]["grunnlag"]


def test_to_dokumenter_uten_nokkel_slaas_ikke_sammen():
    """De deler ingenting bevisbart. At begge mangler nøkkel er ikke en
    likhet — det er to hull."""
    saker = s.grupper_i_saker([dok(filnavn="a.pdf"), dok(filnavn="b.pdf")])
    assert len(saker) == 2


def test_navn_binder_ingenting():
    """To ulike personer kan hete det samme, og OCR staver samme navn på
    tre måter. Et navn er et hint, og hint grupperer ikke saksmapper."""
    saker = s.grupper_i_saker([
        dok(filnavn="a.pdf", eier_navn="Ola Nordmann"),
        dok(filnavn="b.pdf", eier_navn="Ola Nordmann"),
    ])
    assert len(saker) == 2


def test_fnr_alene_slaar_ikke_sammen_saker():
    """KJERNEN i R242. Samme person, tre ytelser, tre saker."""
    saker = s.grupper_i_saker([
        dok(filnavn="syk.pdf", saksnummer="1000001", fnr=FNR),
        dok(filnavn="dag.pdf", saksnummer="2000002", fnr=FNR),
        dok(filnavn="tilbake.pdf", saksnummer="3000003", fnr=FNR),
    ])
    assert len(saker) == 3, (
        "saker ble slått sammen på fødselsnummer — samme person er ikke "
        "samme sak")


# ------------------------------------------------------------------ #
#  Personsammenfall meldes som relasjon                               #
# ------------------------------------------------------------------ #

def test_samme_person_meldes_som_relasjon():
    saker = s.grupper_i_saker([
        dok(filnavn="syk.pdf", saksnummer="1000001", fnr=FNR),
        dok(filnavn="dag.pdf", saksnummer="2000002", fnr=FNR),
    ])
    rel = s.personrelasjoner(saker)
    assert len(rel) == 1
    assert rel[0]["fnr"] == FNR
    assert rel[0]["saksindekser"] == [0, 1]
    assert "ikke slått sammen" in rel[0]["forklaring"].lower()


def test_person_i_bare_en_sak_er_ingen_relasjon():
    saker = s.grupper_i_saker([
        dok(filnavn="a.pdf", saksnummer="1000001", fnr=FNR),
        dok(filnavn="b.pdf", saksnummer="1000001", fnr=FNR),
    ])
    assert s.personrelasjoner(saker) == []


# ------------------------------------------------------------------ #
#  Determinisme (R6)                                                  #
# ------------------------------------------------------------------ #

def test_rekkefolgen_paa_inndata_endrer_ingenting():
    """Samme mappe lest i en annen rekkefølge SKAL gi samme saker."""
    d = [
        dok(filnavn="c.pdf", journalnummer="12/3456"),
        dok(filnavn="a.pdf", saksnummer="4417820"),
        dok(filnavn="b.pdf", saksnummer="4417820", journalnummer="12/3456"),
        dok(filnavn="d.pdf"),
    ]
    fasit = s.grupper_i_saker(d)
    for vri in ([d[3], d[2], d[1], d[0]], [d[1], d[3], d[0], d[2]]):
        assert s.grupper_i_saker(vri) == fasit


def test_tom_inndata_gir_ingen_saker():
    assert s.grupper_i_saker([]) == []
    assert s.grupper_i_saker(None) == []


# ------------------------------------------------------------------ #
#  Tidslinjen                                                         #
# ------------------------------------------------------------------ #

def _mappe():
    return s.grupper_i_saker([
        dok(filnavn="1.pdf", saksnummer="4417820", dato="2026-01-10",
            tittel="Søknad om sykepenger",
            type={"kode": "soknad", "term": "Søknad"}),
        dok(filnavn="3.pdf", saksnummer="4417820", dato="2026-06-12",
            tittel="Klagevedtak",
            type={"kode": "klagevedtak", "term": "Klagevedtak"}),
        dok(filnavn="2.pdf", saksnummer="4417820", dato="2026-02-03",
            tittel="Klage", type={"kode": "klage", "term": "Klage"}),
    ])[0]


def test_tidslinjen_er_kronologisk():
    t = s.tidslinje(_mappe())
    assert [h["dato"] for h in t["hendelser"]] == [
        "2026-01-10", "2026-02-03", "2026-06-12"]
    assert t["fra"] == "2026-01-10"
    assert t["til"] == "2026-06-12"


def test_hendelsen_peker_paa_dokumentet_den_kom_fra():
    """Uten kilde er en tidslinje en påstand. Med kilde er den et spor."""
    t = s.tidslinje(_mappe())
    siste = t["hendelser"][-1]
    assert siste["hendelse"] == "Klagevedtak"
    assert siste["filnavn"] == "3.pdf"


def test_dokument_uten_dato_gjettes_ikke_inn_i_rekkefolgen():
    """En tidslinje der noe er plassert på slump er verre enn en med et
    hull: hullet ser man."""
    sak = s.grupper_i_saker([
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-01-10"),
        dok(filnavn="2.pdf", saksnummer="44", tittel="Udatert notat"),
    ])[0]
    t = s.tidslinje(sak)
    assert len(t["hendelser"]) == 1
    assert len(t["uten_dato"]) == 1
    assert t["uten_dato"][0]["dokument"] == "Udatert notat"


def test_samme_dag_har_fast_rekkefolge():
    sak = s.grupper_i_saker([
        dok(filnavn="b.pdf", saksnummer="44", dato="2026-01-10"),
        dok(filnavn="a.pdf", saksnummer="44", dato="2026-01-10"),
    ])[0]
    assert [h["filnavn"] for h in s.tidslinje(sak)["hendelser"]] \
        == ["a.pdf", "b.pdf"]


def test_tom_sak_gir_tom_tidslinje():
    t = s.tidslinje({"dokumenter": []})
    assert t["hendelser"] == [] and t["fra"] is None and t["til"] is None

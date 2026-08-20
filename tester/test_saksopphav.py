"""
R246: proveniens på SAK-nivå — hva saksvaret bygger hver påstand på.

`delt/opphav.py` svarte på spørsmålet for ETT dokument. Saksvaret hadde
begrunnelser — `grunnlag` på grupperingen, `dato_kilde` på hendelsene,
`forklaring` på motsigelsene — men de var frie strenger, hver i sin
form. En klient som ville vite «hvor sikkert er dette, og hvilket
dokument står det i?» måtte lese norsk prosa og gjette.

Testene vokter tre ting: at ordforrådet er DELT med dokumentnivået (to
vokabularer for samme spørsmål blir før eller siden uenige, R111), at
ulikt sterke bevis ikke vises som like sterke, og at pekerne faktisk
peker inn i svaret de beskriver.
"""
import sys

sys.path.insert(0, ".")

import pytest

from delt import motsigelser as m
from delt import opphav
from delt import sak as s
from delt import saksopphav as so
from tester.syntetiske_nummer import lag_fnr

FNR = lag_fnr()
ANNET_FNR = lag_fnr(1)


def dok(**felt):
    grunn = {"filnavn": "a.pdf", "tittel": None, "dato": None,
             "type": None, "sider": []}
    return {**grunn, **felt}


def type_(kode, term=None):
    return {"kode": kode, "term": term or kode.capitalize()}


def _svarform(dokumenter):
    """Bygger saksvaret slik endepunktet gjør, så pekerne kan prøves mot
    den formen de faktisk skal peke inn i."""
    saker = s.grupper_i_saker(dokumenter)
    ut = [{
        "nokkel": x["nokkel"],
        "grunnlag": x["grunnlag"],
        "grunn": x["grunn"],
        "dokumenter": x["dokumenter"],
        "tidslinje": s.tidslinje(x),
        "motsigelser": m.finn_motsigelser(x),
    } for x in saker]
    return ut, s.personrelasjoner(saker)


# ------------------------------------------------------------------ #
#  Ordforrådet er DELT med dokumentnivået                             #
# ------------------------------------------------------------------ #

def test_metodene_er_de_samme_som_paa_dokumentnivaa():
    """Én klient forgrener på «metode». Bruker de to nivåene ulike ord,
    må den skrive to kodeveier for samme spørsmål (R111)."""
    assert so.METODER is opphav.METODER
    assert so.KONFIDENSNIVAA is opphav.KONFIDENSNIVAA
    assert so.NIVAAER is opphav.NIVAAER


def test_alle_oppforinger_bruker_det_lukkede_ordforradet():
    ut, rel = _svarform([
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-01-01",
            type=type_("soknad"), fnr=FNR),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-02-01",
            type=type_("vedtak"), fnr=ANNET_FNR),
    ])
    kart = so.bygg_saksopphav(ut, rel, "alle")
    assert kart
    for peker, post in kart.items():
        assert post["metode"] in so.METODER, f"{peker}: {post['metode']}"
        assert post["konfidens"] in so.KONFIDENSNIVAA


def test_hver_oppforing_har_de_faste_feltene():
    """Tomt er `null`, ikke utelatt — samme regel som resten av huset."""
    ut, rel = _svarform([dok(filnavn="1.pdf", saksnummer="44")])
    post = so.bygg_saksopphav(ut, rel)["/saker/0/nokkel"]
    for felt in ("metode", "konfidens", "begrunnelse", "dokumenter", "side"):
        assert felt in post


# ------------------------------------------------------------------ #
#  Ulikt sterke bevis vises ikke som like sterke                      #
# ------------------------------------------------------------------ #

def test_alle_dokumenter_baerer_nokkelen_gir_hoy_konfidens():
    ut, rel = _svarform([
        dok(filnavn="1.pdf", saksnummer="44"),
        dok(filnavn="2.pdf", saksnummer="44"),
    ])
    post = so.bygg_saksopphav(ut, rel)["/saker/0/nokkel"]
    assert post["metode"] == "etikett"
    assert post["konfidens"] == "hoy"
    assert post["dokumenter"] == ["1.pdf", "2.pdf"]


def test_indirekte_binding_gir_lavere_konfidens():
    """Bærer bare noen dokumenter nøkkelen, henger resten med via en
    ANNEN delt nøkkel — fortsatt bevist, men ett ledd lenger unna."""
    ut, rel = _svarform([
        dok(filnavn="1.pdf", saksnummer="44"),
        dok(filnavn="2.pdf", saksnummer="44", journalnummer="12/3456"),
        dok(filnavn="3.pdf", journalnummer="12/3456"),
    ])
    post = so.bygg_saksopphav(ut, rel)["/saker/0/nokkel"]
    assert post["konfidens"] == "middels"
    assert "3.pdf" not in post["dokumenter"], (
        "et dokument som ikke bærer nøkkelen står oppført som kilde til den")


def test_uten_nokkel_er_metoden_ingen_og_ikke_utelatt():
    """En manglende peker leses som «vi målte ikke». Her HAR vi målt —
    og fant ingenting som bandt dokumentet til noe."""
    ut, rel = _svarform([dok(filnavn="lost.pdf")])
    post = so.bygg_saksopphav(ut, rel)["/saker/0/nokkel"]
    assert post["metode"] == "ingen"
    assert post["konfidens"] == "ingen"
    assert "ikke bevist" in post["begrunnelse"]


def test_dokumentdato_er_sterkere_enn_behandlingsdato():
    """Den ene sier når dokumentet ble SKREVET, den andre når noen tok
    imot det. Å vise dem likt inviterer til å lese en mottaksdato som en
    vedtaksdato."""
    ut, rel = _svarform([
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-02-01"),
        dok(filnavn="2.pdf", saksnummer="44", behandlingsdato="2026-01-01"),
    ])
    kart = so.bygg_saksopphav(ut, rel, "alle")
    konf = {kart[p]["konfidens"]
            for p in kart if "/tidslinje/hendelser/" in p}
    assert konf == {"hoy", "middels"}


def test_flere_personer_er_sjekksum_og_rekkefolge_er_regel():
    """Det ene er matematikk (mod11), det andre en slutning. Samme ord
    for begge ville skjult forskjellen."""
    ut, rel = _svarform([
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-06-01",
            type=type_("klage"), fnr=FNR),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-01-01",
            type=type_("klagevedtak"), fnr=ANNET_FNR),
    ])
    kart = so.bygg_saksopphav(ut, rel)
    metoder = {kart[p]["metode"] for p in kart if "/motsigelser/" in p}
    assert metoder == {"sjekksum", "regel"}


def test_motsigelsesopphavet_gjengir_ikke_fodselsnumrene():
    """Begrunnelsen arves fra motsigelsen, som med vilje ikke bærer
    numrene — kartet skal ikke gjeninnføre dem."""
    ut, rel = _svarform([
        dok(filnavn="1.pdf", saksnummer="44", fnr=FNR),
        dok(filnavn="2.pdf", saksnummer="44", fnr=ANNET_FNR),
    ])
    kart = so.bygg_saksopphav(ut, rel)
    for post in kart.values():
        assert FNR not in str(post) and ANNET_FNR not in str(post)


# ------------------------------------------------------------------ #
#  Nivåene                                                            #
# ------------------------------------------------------------------ #

def test_ingen_gir_tomt_kart():
    ut, rel = _svarform([dok(filnavn="1.pdf", saksnummer="44")])
    assert so.bygg_saksopphav(ut, rel, "ingen") == {}


def test_viktige_tar_med_nokkel_og_motsigelser_men_ikke_hver_hendelse():
    ut, rel = _svarform([
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-01-01"),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-02-01"),
    ])
    kart = so.bygg_saksopphav(ut, rel, "viktige")
    assert "/saker/0/nokkel" in kart
    assert not [p for p in kart if "/tidslinje/" in p]


def test_alle_tar_med_hendelsene_og_relasjonene():
    ut, rel = _svarform([
        dok(filnavn="1.pdf", saksnummer="1000001", dato="2026-01-01",
            fnr=FNR),
        dok(filnavn="2.pdf", saksnummer="2000002", dato="2026-02-01",
            fnr=FNR),
    ])
    kart = so.bygg_saksopphav(ut, rel, "alle")
    assert [p for p in kart if "/tidslinje/hendelser/" in p]
    assert "/relasjoner/0" in kart
    assert kart["/relasjoner/0"]["metode"] == "sjekksum"


# ------------------------------------------------------------------ #
#  Pekerne peker INN i svaret                                         #
# ------------------------------------------------------------------ #

def test_pekerne_treffer_svaret_de_beskriver():
    """Et opphavskart som peker på noe som ikke finnes, er verre enn
    ingen: klienten slår opp og får ingenting, uten å vite hvorfor."""
    ut, rel = _svarform([
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-06-01",
            type=type_("klage"), fnr=FNR),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-01-01",
            type=type_("klagevedtak"), fnr=ANNET_FNR),
    ])
    svar = {"saker": ut, "relasjoner": rel}
    for peker in so.bygg_saksopphav(ut, rel, "alle"):
        node = svar
        for ledd in peker.strip("/").split("/"):
            node = node[int(ledd)] if ledd.isdigit() else node[ledd]
        # Naadde vi hit, finnes pekeren. `None` er en gyldig verdi
        # (en hendelse uten dato), så vi krever ikke sannhet.


def test_taaler_tomt_og_soppel():
    assert so.bygg_saksopphav([], []) == {}
    assert so.bygg_saksopphav(None, None) == {}
    assert so.bygg_saksopphav([None, "ikke en sak"], None) == {}

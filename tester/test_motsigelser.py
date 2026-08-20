"""
R243: motsigelser MELLOM dokumenter i samme sak.

Fra før fantes én motsigelsessjekk, og den gikk på tvers av KILDER i ett
svar: `_uenighet_med_modellen` sammenligner det modellen fylte ut mot det
uttrekket beviste, på tre felter. Ingenting sammenlignet dokument mot
dokument — og det er der en saksmappe motsier seg selv.

Testene vokter begge veier: at de to bevisbare motsigelsene FANGES, og
at modulen holder kjeft om alt den ikke kan bevise. En vakt som roper på
det uvanlige blir slått av (R180), og da fanger den heller ikke det
umulige.
"""
import sys

sys.path.insert(0, ".")

from delt import motsigelser as m
from delt import sak as s
from tester.syntetiske_nummer import lag_fnr

FNR = lag_fnr()
ANNET_FNR = lag_fnr(1)


def dok(**felt):
    grunn = {"filnavn": "a.pdf", "tittel": None, "dato": None,
             "type": None, "sider": []}
    return {**grunn, **felt}


def type_(kode, term=None):
    return {"kode": kode, "term": term or kode.capitalize()}


def en_sak(*dokumenter):
    return s.grupper_i_saker(list(dokumenter))[0]


# ------------------------------------------------------------------ #
#  To personer i samme sak                                            #
# ------------------------------------------------------------------ #

def test_to_personer_i_samme_sak_meldes():
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", tittel="Vedtak", fnr=FNR),
        dok(filnavn="2.pdf", saksnummer="44", tittel="Klage",
            fnr=ANNET_FNR),
    )
    funn = m.finn_motsigelser(sak)["funn"]
    assert len(funn) == 1
    assert funn[0]["type"] == "flere_personer"
    assert funn[0]["alvor"] == m.ALVOR_HOY
    assert "feilarkivert" in funn[0]["forklaring"]


def test_forklaringen_gjengir_ikke_fodselsnumrene():
    """Forklaringen havner i logg og i svar. Da kan den ikke bære
    identifikatorene den advarer om."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", fnr=FNR),
        dok(filnavn="2.pdf", saksnummer="44", fnr=ANNET_FNR),
    )
    forklaring = m.finn_motsigelser(sak)["funn"][0]["forklaring"]
    assert FNR not in forklaring and ANNET_FNR not in forklaring


def test_en_person_er_ingen_motsigelse():
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", fnr=FNR),
        dok(filnavn="2.pdf", saksnummer="44", fnr=FNR),
    )
    assert m.finn_motsigelser(sak)["funn"] == []


def test_dokumenter_uten_fnr_utloser_ingenting():
    """Et manglende fødselsnummer er et hull, ikke en motsigelse."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", fnr=FNR),
        dok(filnavn="2.pdf", saksnummer="44"),
    )
    assert m.finn_motsigelser(sak)["funn"] == []


# ------------------------------------------------------------------ #
#  Umulig rekkefølge                                                  #
# ------------------------------------------------------------------ #

def test_klagevedtak_for_klagen_meldes():
    """Man avgjør ikke en klage som ikke finnes."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-06-12",
            tittel="Klage", type=type_("klage", "Klage")),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-02-03",
            tittel="Klagevedtak", type=type_("klagevedtak", "Klagevedtak")),
    )
    funn = m.finn_motsigelser(sak)["funn"]
    assert len(funn) == 1
    assert funn[0]["type"] == "umulig_rekkefolge"
    assert "2026-02-03" in funn[0]["forklaring"]
    assert "Klagevedtak" in funn[0]["dokumenter"]


def test_riktig_rekkefolge_meldes_ikke():
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-02-03",
            tittel="Klage", type=type_("klage")),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-06-12",
            tittel="Klagevedtak", type=type_("klagevedtak")),
    )
    assert m.finn_motsigelser(sak)["funn"] == []


def test_samme_dato_er_ikke_umulig():
    """Et klagevedtak samme dag som klagen er raskt, ikke umulig — og
    grensen skal være på det umulige."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-02-03",
            tittel="Klage", type=type_("klage")),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-02-03",
            tittel="Klagevedtak", type=type_("klagevedtak")),
    )
    assert m.finn_motsigelser(sak)["funn"] == []


def test_vedtak_for_soknaden_meldes():
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-03-01",
            tittel="Søknad", type=type_("soknad")),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-01-01",
            tittel="Vedtak", type=type_("vedtak")),
    )
    funn = m.finn_motsigelser(sak)["funn"]
    assert [f["type"] for f in funn] == ["umulig_rekkefolge"]


def test_purring_for_kravet_meldes():
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-03-01",
            tittel="Dokumentasjonskrav", type=type_("dokumentasjonskrav")),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-02-01",
            tittel="Purring", type=type_("purring")),
    )
    assert m.finn_motsigelser(sak)["funn"][0]["type"] == "umulig_rekkefolge"


def test_bare_den_ene_typen_gir_ingen_dom():
    """Finnes det et klagevedtak, men ingen klage i mappa, sier
    rekkefølgen ingenting — klagen kan ligge i en fil vi ikke har fått."""
    sak = en_sak(
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-02-03",
            tittel="Klagevedtak", type=type_("klagevedtak")),
    )
    assert m.finn_motsigelser(sak)["funn"] == []


def test_dokument_uten_dato_teller_ikke_i_rekkefolgen():
    """Uten dato finnes ingen rekkefølge å motsi."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", tittel="Klage",
            type=type_("klage")),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-02-03",
            tittel="Klagevedtak", type=type_("klagevedtak")),
    )
    assert m.finn_motsigelser(sak)["funn"] == []


def test_eldste_av_hver_type_avgjor():
    """Finnes to klager, er det den FØRSTE som avgjør om klagevedtaket
    kan ha kommet før noen klage i det hele tatt. Her er det en klage
    før klagevedtaket, og da er saken i orden."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-01-05",
            tittel="Klage 1", type=type_("klage")),
        dok(filnavn="3.pdf", saksnummer="44", dato="2026-09-01",
            tittel="Klage 2", type=type_("klage")),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-03-03",
            tittel="Klagevedtak", type=type_("klagevedtak")),
    )
    assert m.finn_motsigelser(sak)["funn"] == []


# ------------------------------------------------------------------ #
#  Et tomt funn er ingen frikjennelse                                 #
# ------------------------------------------------------------------ #

def test_sjekkene_rapporteres_ogsaa_naar_ingenting_ble_funnet():
    """R128: uten dette kunne «funn: []» leses som «saken henger
    sammen» — en påstand modulen ikke kan gjøre."""
    svar = m.finn_motsigelser(en_sak(dok(filnavn="1.pdf", saksnummer="44")))
    assert svar["funn"] == []
    assert svar["sjekket"] == list(m.SJEKKER)


def test_ulike_belop_meldes_ikke():
    """Fristende, men feil: et vedtak og et omgjøringsvedtak SKAL ha
    ulike beløp. Uten et målt korpus ville regelen ropt på friske saker."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-01-01",
            tittel="Vedtak", type=type_("vedtak"), dagsats="1200"),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-05-01",
            tittel="Omgjøring", type=type_("vedtak"), dagsats="900"),
    )
    assert m.finn_motsigelser(sak)["funn"] == []


def test_taaler_soppel_inn():
    assert m.finn_motsigelser(None)["funn"] == []
    assert m.finn_motsigelser({})["funn"] == []
    assert m.finn_motsigelser({"dokumenter": None})["funn"] == []


def test_rekkefolgen_paa_dokumentene_endrer_ikke_funnene():
    """R6 — samme sak, samme rapport."""
    a = dok(filnavn="1.pdf", saksnummer="44", dato="2026-06-12",
            tittel="Klage", type=type_("klage"), fnr=FNR)
    b = dok(filnavn="2.pdf", saksnummer="44", dato="2026-02-03",
            tittel="Klagevedtak", type=type_("klagevedtak"), fnr=ANNET_FNR)
    assert m.finn_motsigelser(en_sak(a, b)) == m.finn_motsigelser(en_sak(b, a))


def test_begge_slag_kan_meldes_samtidig():
    a = dok(filnavn="1.pdf", saksnummer="44", dato="2026-06-12",
            tittel="Klage", type=type_("klage"), fnr=FNR)
    b = dok(filnavn="2.pdf", saksnummer="44", dato="2026-02-03",
            tittel="Klagevedtak", type=type_("klagevedtak"), fnr=ANNET_FNR)
    typer = [f["type"] for f in m.finn_motsigelser(en_sak(a, b))["funn"]]
    assert typer == ["flere_personer", "umulig_rekkefolge"]

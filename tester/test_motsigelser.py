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


def test_soknad_med_bare_mottatt_dato_teller_i_rekkefolgen():
    """Uten dette slo «vedtak før søknad» aldri ut på nettopp de
    søknadene det gjelder: de bærer bare «Mottatt», som er en
    behandlingsdato, ikke dokumentets egen."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", behandlingsdato="2026-05-01",
            tittel="Søknad", type=type_("soknad")),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-01-01",
            tittel="Vedtak", type=type_("vedtak")),
    )
    funn = m.finn_motsigelser(sak)["funn"]
    assert [f["type"] for f in funn] == ["umulig_rekkefolge"]


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


# ------------------------------------------------------------------ #
#  R248: ulike beløp — og alt regelen IKKE skal ta                    #
# ------------------------------------------------------------------ #

def test_omgjoering_er_ingen_motsigelse():
    """Kjernen i R248. Et vedtak og et omgjøringsvedtak SKAL ha ulike
    beløp — klagen førte fram. Ulike datoer er en HISTORIE, ikke to
    påstander om samme øyeblikk. En regel som roper her, roper på den
    friskeste saken i arkivet."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-01-01",
            tittel="Vedtak", type=type_("vedtak"), dagsats="1200"),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-05-01",
            tittel="Klagevedtak", type=type_("klagevedtak"), dagsats="900"),
    )
    assert m.finn_motsigelser(sak)["funn"] == []


def test_samme_dag_ulikt_belop_meldes():
    """Samme dag kan ingen av dem gå foran den andre, så begge kan ikke
    stemme."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-02-01",
            tittel="Vedtak A", type=type_("vedtak"), dagsats="1 240,00"),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-02-01",
            tittel="Vedtak B", type=type_("vedtak"), dagsats="1 480,00"),
    )
    funn = m.finn_motsigelser(sak)["funn"]
    assert [f["type"] for f in funn] == ["ulikt_belop"]
    assert "dagsats" in funn[0]["forklaring"]


def test_samme_beloep_skrevet_ulikt_er_ingen_motsigelse():
    """«1 240,00», «1240,00» og «1240» er samme beløp. Et funn som bare
    handler om skrivemåte er støy, og støy slår av vakten (R180)."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-02-01",
            dagsats="1 240,00"),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-02-01",
            dagsats="1240"),
        dok(filnavn="3.pdf", saksnummer="44", dato="2026-02-01",
            dagsats="1240,00 kroner"),
    )
    assert m.finn_motsigelser(sak)["funn"] == []


def test_ulike_slags_belop_sammenlignes_aldri():
    """Dagsats og månedsbeløp er ulike med matematisk nødvendighet. Å
    sammenligne dem er en kategorifeil, ikke et funn."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-02-01",
            dagsats="1 240,00"),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-02-01",
            manedsbelop="26 040,00"),
    )
    assert m.finn_motsigelser(sak)["funn"] == []


def test_dokument_uten_dato_utloser_ingen_belopsmotsigelse():
    """Uten dato kan ingen si hva som går foran. Da er svaret «vi vet
    ikke», og en gjetning der er verre enn taushet."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-02-01",
            dagsats="1 240,00"),
        dok(filnavn="2.pdf", saksnummer="44", dagsats="1 480,00"),
    )
    assert m.finn_motsigelser(sak)["funn"] == []


def test_umerkede_tall_blir_aldri_et_funn():
    """Bare de MERKEDE beløpsfeltene sammenlignes. Tallene i en
    beregningstabell er umerkede og finnes ikke i posten (R71)."""
    from delt.motsigelser import BELOPSFELT
    assert set(BELOPSFELT) == {"dagsats", "manedsbelop", "utbetalt_belop",
                               "tilbakebetalingsbelop"}


def test_belopssjekken_staar_i_sjekket():
    """Et tomt funn er ingen frikjennelse — og nå er det tre sjekker."""
    svar = m.finn_motsigelser(en_sak(dok(filnavn="1.pdf", saksnummer="44")))
    assert "ulikt_belop" in svar["sjekket"]


def test_forklaringen_gjengir_ikke_beloepene():
    """Forklaringen havner i logg og svar. Et tilbakebetalingsbeløp er
    økonomiske persondata — dokumentene er navngitt, og tallene står i
    dem."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-02-01",
            tilbakebetalingsbelop="18 500,00"),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-02-01",
            tilbakebetalingsbelop="15 200,00"),
    )
    forklaring = m.finn_motsigelser(sak)["funn"][0]["forklaring"]
    assert "18" not in forklaring and "15 200" not in forklaring


def test_maalingen_mot_fasit_er_med_i_repoet():
    """R248 ble MÅLT før den ble kodet. Korpuset er beviset, og det skal
    kunne kjøres på nytt når et ekte arkiv finnes."""
    import json
    import os
    sti = os.path.join("tester", "korpus", "belopsvarianter.json")
    with open(sti, encoding="utf-8") as fil:
        korpus = json.load(fil)
    fasiter = [s["fasit"] for s in korpus["saker"]]
    assert fasiter.count("legitim") >= 5, (
        "for få falsifiserende saker — de legitime er de viktigste")
    assert "motsigelse" in fasiter


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

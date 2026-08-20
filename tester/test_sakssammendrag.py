"""
R249: sakssammendrag — saken fortalt som ÉN sak.

Systemet kunne oppsummere ett dokument. Spør man i stedet «hva skjedde i
denne saken?», er svaret ikke elleve sammendrag etter hverandre.

Hvorfor dette er kode og ikke en prompt, står i modulen: R229 målte at
modellen svarte feil på alle fire bunkespørsmålene den fikk — den leser,
den holder ikke regnskap, og et sakssammendrag ER regnskap. Testene her
vokter de tre stedene et sammendrag lyver lettest: hvem saken gjelder,
hva som ble bestemt TIL SLUTT, og hvor sikkert vi vet det.
"""
import sys

sys.path.insert(0, ".")

from delt import motsigelser as m
from delt import sak as s
from delt import saksopphav as so
from delt import sakssammendrag as ss
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


def _full_sak():
    """En hel sakshistorie: søknad, krav, vedtak, klage, klagevedtak —
    og et journalnotat skrevet ETTER klagevedtaket."""
    return en_sak(
        dok(filnavn="1_soknad.pdf", saksnummer="44", fnr=FNR,
            behandlingsdato="2026-01-10", type=type_("soknad", "Søknad"),
            ytelse={"kode": "SYK", "term": "Sykepenger"}),
        dok(filnavn="2_krav.pdf", saksnummer="44", fnr=FNR,
            dato="2026-01-25", type=type_("dokumentasjonskrav",
                                          "Dokumentasjonskrav")),
        dok(filnavn="3_vedtak.pdf", saksnummer="44", fnr=FNR,
            dato="2026-02-01", type=type_("vedtak", "Vedtak"),
            ytelse={"kode": "SYK", "term": "Sykepenger"}),
        dok(filnavn="4_klage.pdf", saksnummer="44", fnr=FNR,
            dato="2026-02-15", type=type_("klage", "Klage")),
        dok(filnavn="5_klagevedtak.pdf", saksnummer="44", fnr=FNR,
            dato="2026-06-12", type=type_("klagevedtak", "Klagevedtak")),
        dok(filnavn="6_notat.pdf", saksnummer="44", fnr=FNR,
            dato="2026-08-01", type=type_("journalnotat", "Journalnotat")),
    )


# ------------------------------------------------------------------ #
#  Hvem saken gjelder                                                 #
# ------------------------------------------------------------------ #

def test_parten_fastslaas_naar_dokumentene_er_enige():
    sammendrag = ss.bygg_sammendrag(_full_sak())
    assert sammendrag["part"]["fnr"] == FNR
    assert sammendrag["part"]["antall_personer"] == 1


def test_to_personer_gir_ingen_part_i_stedet_for_et_valg():
    """Å plukke ett av to fødselsnummer ville vært å gjette hvem saken
    gjelder — samme grunn som `finn_dokument_eier` nekter."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", fnr=FNR),
        dok(filnavn="2.pdf", saksnummer="44", fnr=ANNET_FNR),
    )
    part = ss.bygg_sammendrag(sak)["part"]
    assert part["fnr"] is None
    assert part["antall_personer"] == 2
    assert "motsigelser" in part["grunnlag"]


def test_ingen_fnr_sier_hvorfor():
    part = ss.bygg_sammendrag(en_sak(dok(filnavn="1.pdf",
                                         saksnummer="44")))["part"]
    assert part["fnr"] is None and part["antall_personer"] == 0
    assert "etikett" in part["grunnlag"]


def test_ytelsen_oppgis_bare_naar_dokumentene_er_enige():
    """To ulike ytelser betyr som regel at mappa er blandet, og da er
    «den første vi fant» et tilfeldig svar."""
    enige = ss.bygg_sammendrag(_full_sak())["ytelse"]
    assert enige["kode"] == "SYK"

    blandet = en_sak(
        dok(filnavn="1.pdf", saksnummer="44",
            ytelse={"kode": "SYK", "term": "Sykepenger"}),
        dok(filnavn="2.pdf", saksnummer="44",
            ytelse={"kode": "DAG", "term": "Dagpenger"}),
    )
    assert ss.bygg_sammendrag(blandet)["ytelse"]["kode"] is None


# ------------------------------------------------------------------ #
#  Hva ble bestemt TIL SLUTT                                          #
# ------------------------------------------------------------------ #

def test_siste_avgjorelse_er_ikke_siste_dokument():
    """Kjernen. Journalnotatet er det nyeste dokumentet i mappa, men det
    avgjør ingenting. Spørsmålet «hva ble det til slutt?» besvares av
    klagevedtaket."""
    siste = ss.bygg_sammendrag(_full_sak())["siste_avgjorelse"]
    assert siste["dokument"] == "5_klagevedtak.pdf"
    assert siste["dato"] == "2026-06-12"


def test_klageinstansen_gaar_foran_uansett_dato():
    """Et omgjøringsvedtak i førsteinstans datert ETTER klagevedtaket
    endrer ikke hvem som avgjorde klagen. Det er hele poenget med en
    klageinstans."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-06-12",
            type=type_("klagevedtak", "Klagevedtak")),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-09-01",
            type=type_("vedtak", "Vedtak")),
    )
    assert ss.bygg_sammendrag(sak)["siste_avgjorelse"]["dokument"] == "1.pdf"


def test_status_etter_klage():
    sammendrag = ss.bygg_sammendrag(_full_sak())
    assert sammendrag["status"]["kode"] == "avgjort_etter_klage"
    assert sammendrag["klaget"] is True


def test_status_venter_paa_dokumentasjon():
    """Et dokumentasjonskrav uten en avgjørelse etter seg betyr at saken
    står og venter — det en saksbehandler mest av alt vil vite."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", behandlingsdato="2026-01-10",
            type=type_("soknad")),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-01-25",
            type=type_("dokumentasjonskrav")),
    )
    status = ss.bygg_sammendrag(sak)["status"]
    assert status["kode"] == "venter_paa_dokumentasjon"
    assert "2026-01-25" in status["begrunnelse"]


def test_krav_FOER_vedtaket_holder_ikke_saken_aapen():
    """Kravet ble besvart: vedtaket er datert etter det."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-01-25",
            type=type_("dokumentasjonskrav")),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-02-01",
            type=type_("vedtak")),
    )
    assert ss.bygg_sammendrag(sak)["status"]["kode"] == "avgjort"


def test_soknad_uten_avgjorelse_er_under_behandling():
    sak = en_sak(dok(filnavn="1.pdf", saksnummer="44",
                     behandlingsdato="2026-01-10", type=type_("soknad")))
    assert ss.bygg_sammendrag(sak)["status"]["kode"] == "under_behandling"


def test_uten_grunnlag_er_status_ukjent_og_ikke_en_gjetning():
    sak = en_sak(dok(filnavn="1.pdf", saksnummer="44",
                     dato="2026-03-01", type=type_("journalnotat")))
    status = ss.bygg_sammendrag(sak)["status"]
    assert status["kode"] == "ukjent"
    assert status["term"] == "Ukjent"
    assert ss.bygg_sammendrag(sak)["siste_avgjorelse"] is None


def test_statuskodene_er_et_lukket_vokabular():
    """En verdi utenfor tabellen er en feil, ikke en ny kategori."""
    for sak in (_full_sak(),
                en_sak(dok(filnavn="1.pdf", saksnummer="44")),
                en_sak(dok(filnavn="1.pdf", saksnummer="44",
                           dato="2026-01-01", type=type_("vedtak")))):
        assert ss.bygg_sammendrag(sak)["status"]["kode"] in ss.STATUSER


# ------------------------------------------------------------------ #
#  Forløpet, manglene og motsigelsene                                 #
# ------------------------------------------------------------------ #

def test_forlopet_er_kronologisk_og_utelater_stoyen():
    """Et sammendrag som gjentar alt er ikke et sammendrag. Notatet er
    med i tidslinjen, ikke i forløpet."""
    forlop = ss.bygg_sammendrag(_full_sak())["forlop"]
    assert [h["dato"] for h in forlop] == sorted(h["dato"] for h in forlop)
    assert "6_notat.pdf" not in [h["dokument"] for h in forlop]
    assert "3_vedtak.pdf" in [h["dokument"] for h in forlop]


def test_udatert_dokument_havner_ikke_i_forlopet():
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-02-01",
            type=type_("vedtak")),
        dok(filnavn="2.pdf", saksnummer="44", type=type_("klage")),
    )
    assert len(ss.bygg_sammendrag(sak)["forlop"]) == 1


def test_manglene_samles_fra_dokumentene():
    """R247 regnet dem ut per dokument; sammendraget svarer på «hva var
    ufullstendig» uten å lese dokumentene på nytt."""
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", type=type_("journalnotat"),
            mangler=["dato"]),
        dok(filnavn="2.pdf", saksnummer="44", dato="2026-02-01",
            type=type_("vedtak")),
    )
    mangler = ss.bygg_sammendrag(sak)["mangler"]
    assert mangler == [{"dokument": "1.pdf", "type": "journalnotat",
                        "mangler": ["dato"]}]


def test_motsigelsene_telles_med():
    sak = en_sak(
        dok(filnavn="1.pdf", saksnummer="44", fnr=FNR, dato="2026-02-01"),
        dok(filnavn="2.pdf", saksnummer="44", fnr=ANNET_FNR,
            dato="2026-02-01"),
    )
    funn = m.finn_motsigelser(sak)
    assert ss.bygg_sammendrag(sak, funn)["antall_motsigelser"] == len(
        funn["funn"]) >= 1


def test_taaler_tomt_og_soppel():
    for tom in (None, {}, {"dokumenter": None}, {"dokumenter": [None, 1]}):
        sammendrag = ss.bygg_sammendrag(tom)
        assert sammendrag["antall_dokumenter"] == 0
        assert sammendrag["status"]["kode"] == "ukjent"


def test_samme_sak_gir_samme_sammendrag():
    """R6 — et sammendrag som endrer seg mellom to kall er ubrukelig
    som grunnlag for en beslutning."""
    assert ss.bygg_sammendrag(_full_sak()) == ss.bygg_sammendrag(_full_sak())


# ------------------------------------------------------------------ #
#  Sammendraget er sporet i opphavskartet                             #
# ------------------------------------------------------------------ #

def test_opphavet_skiller_bevis_fra_slutning():
    """Parten er mod11 — matematikk. Status er en regel anvendt på
    dokumenttyper — en slutning. Samme merkelapp på begge ville skjult
    forskjellen (§21 i kravspesifikasjonen)."""
    sak = _full_sak()
    ut = [{"nokkel": sak["nokkel"], "grunnlag": sak["grunnlag"],
           "dokumenter": sak["dokumenter"],
           "sammendrag": ss.bygg_sammendrag(sak)}]
    kart = so.bygg_saksopphav(ut, [])
    assert kart["/saker/0/sammendrag/part"]["metode"] == "sjekksum"
    assert kart["/saker/0/sammendrag/part"]["konfidens"] == "hoy"
    assert kart["/saker/0/sammendrag/status"]["metode"] == "regel"
    assert kart["/saker/0/sammendrag/status"]["konfidens"] == "middels"


def test_ukjent_status_har_metoden_ingen():
    sak = en_sak(dok(filnavn="1.pdf", saksnummer="44"))
    ut = [{"nokkel": sak["nokkel"], "grunnlag": sak["grunnlag"],
           "dokumenter": sak["dokumenter"],
           "sammendrag": ss.bygg_sammendrag(sak)}]
    kart = so.bygg_saksopphav(ut, [])
    assert kart["/saker/0/sammendrag/status"]["metode"] == "ingen"


def test_ingen_sprakmodell_er_involvert():
    """R229: modellen svarte feil på alle fire bunkespørsmålene. Et
    sakssammendrag er regnskap, og regnskap er ikke modellens arbeid."""
    import inspect
    kilde = inspect.getsource(ss)
    for forbudt in ("borealis", "prompter", "llm", "modell_svar"):
        assert forbudt not in kilde.lower().replace("modellen", ""), forbudt

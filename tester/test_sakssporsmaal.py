"""
R250: spørsmål om SAKEN, over flere dokumenter.

`POST /spor` svarer om ett dokument. Spør man «ble vedtaket endret?»,
ligger svaret spredt over flere filer — og §15 i kravspesifikasjonen sier
hva som er fella: å svare fra det FØRSTE dokumentet som inneholder ord
som ligner spørsmålet.

To veier, og koden får første ord. Testene her vokter begge: at koden
svarer på det som ALLEREDE er bevist (og aldri lar modellen gjette om
det), og at modellveien får dokumenter KODEN har valgt — med kildene
oppgitt, for et svar uten adresse er en påstand.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

from delt import sak as s
from delt import sakssammendrag as ss
from delt import sakssporsmaal as sp
from tester.syntetiske_nummer import lag_fnr

FNR = lag_fnr()


def dok(**felt):
    grunn = {"filnavn": "a.pdf", "tittel": None, "dato": None,
             "type": None, "tekst": ""}
    return {**grunn, **felt}


def type_(kode, term=None):
    return {"kode": kode, "term": term or kode.capitalize()}


def _sak():
    return s.grupper_i_saker([
        dok(filnavn="1_soknad.pdf", saksnummer="44", fnr=FNR,
            behandlingsdato="2026-01-10", type=type_("soknad", "Søknad"),
            tekst="Søknad om sykepenger. Mottatt 10.01.2026."),
        dok(filnavn="2_vedtak.pdf", saksnummer="44", fnr=FNR,
            dato="2026-02-01", type=type_("vedtak", "Vedtak"),
            tekst="Vedtak om sykepenger. Søknaden avslås. Dagsats 0."),
        dok(filnavn="3_klage.pdf", saksnummer="44", fnr=FNR,
            dato="2026-02-15", type=type_("klage", "Klage"),
            tekst="Klage på vedtaket. Jeg mener vilkårene er oppfylt."),
        dok(filnavn="4_klagevedtak.pdf", saksnummer="44", fnr=FNR,
            dato="2026-06-12", type=type_("klagevedtak", "Klagevedtak"),
            tekst="Klagevedtak. Klagen tas til følge. Dagsats 1 240,00."),
    ])[0]


def _sammendrag():
    return ss.bygg_sammendrag(_sak())


# ------------------------------------------------------------------ #
#  Koden svarer på det som alt er bevist                              #
# ------------------------------------------------------------------ #

def test_hva_ble_det_til_slutt_besvares_av_koden():
    """Modellen skal aldri gjette på dette: svaret er alt utledet av
    dokumenttyper og datoer (R249)."""
    svar, kilder = sp._kodesvar("Hva ble det til slutt i saken?",
                                _sammendrag())
    assert "Klagevedtak" in svar
    assert "2026-06-12" in svar
    assert kilder == ["4_klagevedtak.pdf"]


def test_hvem_gjelder_saken_besvares_av_koden():
    svar, _kilder = sp._kodesvar("Hvem gjelder saken?", _sammendrag())
    assert FNR in svar


def test_ble_det_klaget_besvares_av_koden():
    svar, kilder = sp._kodesvar("Ble det klaget i saken?", _sammendrag())
    assert svar.startswith("Ja")
    assert "3_klage.pdf" in kilder


def test_klagevedtaket_telles_ikke_som_en_klage():
    """Regresjon, funnet ved å faktisk stille spørsmålet mot serveren:
    «Klagevedtak» INNEHOLDER «Klage», og et delstrengsøk på termen ga
    både klagedatoen (15.02) og klagevedtakets dato (12.06) som svar på
    «når ble det klaget?». Koden matcher nå typeKODEN."""
    svar, kilder = sp._kodesvar("Ble det klaget?", _sammendrag())
    assert "2026-02-15" in svar
    assert "2026-06-12" not in svar, (
        "klagevedtakets dato telles som en klagedato")
    assert kilder == ["3_klage.pdf"]


def test_forlopet_baerer_typekoden_ikke_bare_termen():
    """Termen er for et menneske, koden for en maskin. Uten koden må en
    klient matche på tekst — og der ligger fella over."""
    for hendelse in _sammendrag()["forlop"]:
        assert hendelse["type"], "forløpshendelse uten typekode"


def test_ingen_klage_gir_et_aerlig_nei():
    sammendrag = ss.bygg_sammendrag(s.grupper_i_saker([
        dok(filnavn="1.pdf", saksnummer="44", dato="2026-02-01",
            type=type_("vedtak"))])[0])
    svar, _ = sp._kodesvar("Ble det klaget?", sammendrag)
    assert svar.startswith("Nei")


def test_status_besvares_av_koden():
    svar, _ = sp._kodesvar("Hvor står saken?", _sammendrag())
    assert "Avgjort etter klage" in svar


def test_mangler_besvares_med_forbeholdet_sitt():
    """«Ingen mangler» er ikke det samme som «komplett» — bare MÅLTE
    felter kan mangle (R247)."""
    svar, _ = sp._kodesvar("Hva mangler i saken?", _sammendrag())
    assert "MÅLT" in svar or "målt" in svar


def test_ukjent_spoersmaal_gaar_videre_til_modellen():
    """Et trangt mønstersett er med vilje: en feilaktig deterministisk
    «treffer» er verre enn ingen, fordi den ser autoritativ ut."""
    assert sp._kodesvar("Hva slags tilrettelegging ble avtalt?",
                        _sammendrag()) is None


def test_uten_sammendrag_svarer_koden_ingenting():
    assert sp._kodesvar("Hvem gjelder saken?", None) is None


# ------------------------------------------------------------------ #
#  Utvalget når modellen skal svare                                   #
# ------------------------------------------------------------------ #

def test_spoersmaal_om_klagevedtaket_velger_klagevedtaket():
    """§15: ikke svar fra det første dokumentet som inneholder ord som
    ligner. Nevner spørsmålet dokumenttypen, skal DEN vinne."""
    utvalg = sp.velg_dokumenter(_sak()["dokumenter"],
                                "Hva står i klagevedtaket?")
    assert utvalg["valgte"][0]["filnavn"] == "4_klagevedtak.pdf"


def test_spoersmaal_om_klagen_velger_klagen_ikke_vedtaket():
    """Klagen nevner vedtaket den klager på — uten typepåslaget ville
    ordtellingen kunnet peke feil vei."""
    utvalg = sp.velg_dokumenter(_sak()["dokumenter"],
                                "Hva står i klagen?")
    assert utvalg["valgte"][0]["filnavn"] == "3_klage.pdf"


def test_utvalget_har_et_tak():
    """Hvert dokument koster kontekst, og kontekstvinduet er 3008
    tokens til prompt, dokumenter og spørsmål TIL SAMMEN."""
    utvalg = sp.velg_dokumenter(_sak()["dokumenter"], "sykepenger", maks=2)
    assert len(utvalg["valgte"]) == 2
    assert len(utvalg["utelatte"]) == 2


def test_utelatte_dokumenter_navngis():
    """R24: et svar bygget på to av fire dokumenter er et annet svar enn
    ett bygget på fire, og forskjellen skal ikke måtte gjettes."""
    utvalg = sp.velg_dokumenter(_sak()["dokumenter"], "klagevedtaket",
                                maks=1)
    assert set(utvalg["utelatte"]) == {"1_soknad.pdf", "2_vedtak.pdf",
                                       "3_klage.pdf"}


def test_uten_treff_velges_noe_likevel_og_det_sies_hvilke():
    """Et spørsmål som ikke matcher noe skal ikke gi et tomt utvalg og
    dermed et tomt svar — men kildene sier hvilke det ble."""
    utvalg = sp.velg_dokumenter(_sak()["dokumenter"], "zzz qqq", maks=2)
    assert len(utvalg["valgte"]) == 2


def test_utvalget_er_deterministisk():
    """R6 — samme sak og samme spørsmål gir samme utvalg."""
    a = sp.velg_dokumenter(_sak()["dokumenter"], "hva ble dagsatsen")
    b = sp.velg_dokumenter(_sak()["dokumenter"], "hva ble dagsatsen")
    assert [d["filnavn"] for d in a["valgte"]] == \
           [d["filnavn"] for d in b["valgte"]]


def test_utdraget_navngir_hvert_dokument():
    """Uten navnet kan modellen ikke vise til kilden, og et menneske
    ikke finne den igjen."""
    utdrag = sp.bygg_utdrag(_sak()["dokumenter"][:2])
    assert "[Dokument: 1_soknad.pdf]" in utdrag
    assert "[Dokument: 2_vedtak.pdf]" in utdrag


def test_dokumenter_uten_tekst_gir_null_poeng():
    """Saksmappa lagrer ikke teksten (R245). Et dokument uten tekst kan
    ikke besvares fra, og skal ikke late som."""
    utvalg = sp.velg_dokumenter(
        [dok(filnavn="tom.pdf", tekst=""),
         dok(filnavn="full.pdf", tekst="Vedtak om sykepenger")],
        "sykepenger", maks=1)
    assert utvalg["valgte"][0]["filnavn"] == "full.pdf"


# ------------------------------------------------------------------ #
#  Prompten bor i regelfila, ikke i koden                             #
# ------------------------------------------------------------------ #

def test_prompten_ligger_i_regelfila():
    """CLAUDE.md §4: ingen prompttekst i Python."""
    from delt import prompter
    tekst = prompter.hent("spor.sakssporsmal", dokumenter="DOK",
                          sporsmal="SPM")
    assert "DOK" in tekst and "SPM" in tekst
    assert "Finnes ikke i dokumentene" in tekst


def test_prompten_har_et_klippeanker():
    """Uten ankeret klipper `_tilpass_kontekst` bakfra, og en sak med
    tre dokumenter mister spørsmålet sitt."""
    import dokument_api as api
    assert ("\nDokumenter:\n", "\n\nSpørsmål:") in api._PROMPT_ANKRE
    from delt import prompter
    tekst = prompter.hent("spor.sakssporsmal", dokumenter="DOK",
                          sporsmal="SPM")
    assert "\nDokumenter:\n" in tekst and "\n\nSpørsmål:" in tekst


def test_ingen_prompttekst_i_modulen():
    import inspect
    kilde = inspect.getsource(sp)
    assert "Du svarer" not in kilde and "Svar KUN" not in kilde

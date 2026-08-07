"""
`profil=sammendrag` skal virke på HELE svaret.

Bryteren finnes for personvern: en klient som bare spør om en dato skal
slippe å motta fødselsnummer og adresse. Den var annonsert slik i R85 og
i OpenAPI-beskrivelsen — og den holdt ikke. Målt på det ekte svaret:

    /felter/felter/fodselsnummer   verdien, i klartekst
    /tekst                          hele dokumentet
    /felter/datoer_detaljert[]/kontekst   84 tegn råtekst rundt hver dato

`_profilform` renset `dokumentprofil`, og bare den. `tekst` og `felter`
bygges utenom, og begge er PÅ som standard. Bryteren dekket en
tredjedel av svaret.

HVORFOR TESTENE IKKE SÅ DET
Alle fire eksisterende vakter prøvde FUNKSJONEN isolert:
`api._profilform(_profil(), "sammendrag")`. Ingen bygde hele
svarkroppen og lette etter fødselsnummeret i den. Det er nøyaktig den
testen som manglet, og den står nedenfor.

RÅTEKST FJERNES, DEN SLADDES IKKE
`sladd_tekst` dekker bare det den kan BEVISE, og sier selv at navn og
adresser ikke dekkes. «Sladdet» tekst som fortsatt bærer navn og adresse
ville byttet ett falskt løfte mot et svakere.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api
import syntetiske_nummer

FNR = syntetiske_nummer.lag_fnr()
# Modellens FEIL gjetning — et annet gyldig nummer, generert av
# samme grunn: ellevesifrede tall skal ikke stå i kildekoden.
FNR_FRA_MODELLEN = syntetiske_nummer.lag_fnr(1)
KONTO = syntetiske_nummer.lag_kontonummer()
NAVN = "Ola Nordmann"
TELEFON = "76118610"
EPOST = "ola.nordmann@example.no"

DOK = f"""[Side 1 av 1]
NAV Arbeid og ytelser
Vedtak om sykepenger

Opplysninger om: {NAVN}
Fodselsnummer: {FNR}
Telefon: {TELEFON}
E-post: {EPOST}
Storgata 12 B, 8450 STOKMARKNES

Saksnummer: 4417820
Dokumentdato: 04.03.2026
Utbetales til kontonummer {KONTO}
"""

HEMMELIGHETER = {
    "fødselsnummer": FNR,
    "navn": NAVN,
    "telefon": TELEFON,
    "e-post": EPOST,
    "kontonummer": KONTO,
    "gateadresse": "Storgata 12 B",
}


def _fake():
    H = api.Handler

    class Fake:
        MAKS_OPERASJONER = H.MAKS_OPERASJONER
        _les_dokument = H._les_dokument
        _dokument_samlet = H._dokument_samlet
        _dokument_operasjoner = H._dokument_operasjoner

        def __init__(self):
            self.svar = None

        def _svar(self, kode, data, hoder=None):
            self.svar = (kode, data)
            return (kode, data)

    return Fake()


def _svar(profil="full", **ekstra):
    f = _fake()
    felt = {"felter": "ja", "struktur": "ja", "datoer_detaljert": "ja",
            "opphav": "alle", "profil": profil}
    felt.update(ekstra)
    f._dokument_samlet("prove.txt", "tekst", DOK, None, felt, True)
    return f.svar[1]


def _operasjonssvar(profil="full", operasjoner=None):
    f = _fake()
    f._dokument_operasjoner(
        "prove.txt", "tekst", DOK, None, True,
        operasjoner or '[{"type":"felter"},{"type":"tekst"}]',
        {"profil": profil})
    return f.svar[1]


def _stier_med(node, naal, sti=""):
    """Alle JSON-stier der nålen står — som verdi eller inni en streng."""
    funn = []
    if isinstance(node, dict):
        for k, v in node.items():
            funn += _stier_med(v, naal, f"{sti}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            funn += _stier_med(v, naal, f"{sti}[{i}]")
    elif isinstance(node, str) and naal in node:
        funn.append(sti)
    return funn


# ------------------------------------------------------------------ #
#  1. Kjernen — testen som manglet                                     #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("merke", sorted(HEMMELIGHETER))
def test_ingen_persondata_i_HELE_svaret(merke):
    """Bygger hele svarkroppen og leter etter verdien i den.

    De gamle vaktene prøvde `_profilform` isolert. Denne prøver det
    klienten FAKTISK mottar — og det er der de tre lekkasjene satt."""
    verdi = HEMMELIGHETER[merke]
    funn = _stier_med(_svar(profil="sammendrag"), verdi)
    assert not funn, (
        f"{merke} nådde fram i et svar som ba om profil=sammendrag:\n  "
        + "\n  ".join(funn))


def test_speilet_full_profil_leverer_dataene():
    """Uten dette beviser testen over ingenting: den ville vært grønn
    om uttrekket sluttet å finne noe som helst."""
    fullt = _svar(profil="full")
    for merke, verdi in HEMMELIGHETER.items():
        assert _stier_med(fullt, verdi), (
            f"{merke} finnes ikke engang i profil=full — da måler "
            f"personverntesten ingenting")


# ------------------------------------------------------------------ #
#  2. De tre kanalene, hver for seg                                    #
# ------------------------------------------------------------------ #

def test_raateksten_fjernes_ikke_sladdes():
    """`tekst` settes til null. Delvis sladding ville latt navn og
    adresse stå igjen — et svakere løfte, ikke et oppfylt."""
    assert _svar(profil="sammendrag")["tekst"] is None


def test_personfeltene_i_felter_nulles_men_nokkelen_blir_staaende():
    """R118: verdien holdes tilbake, formen står stille."""
    fullt = (_svar(profil="full")["felter"] or {}).get("felter") or {}
    lite = (_svar(profil="sammendrag")["felter"] or {}).get("felter") or {}
    assert "fodselsnummer" in fullt, "fixturen fant ikke noe fnr"
    for navn in api._PERSONFELT_I_FELTER:
        if navn in fullt:
            assert navn in lite, f"nøkkelen {navn} forsvant — bryter R118"
            assert lite[navn] is None, f"{navn} nådde fram"


def test_raatekstvinduet_rundt_hver_dato_fjernes():
    """«kontekst» er 84 tegn råtekst, og overlever selv `tekst=nei`
    fordi den ligger i en annen blokk."""
    datoer = (_svar(profil="sammendrag")["felter"] or {}).get(
        "datoer_detaljert") or []
    assert datoer, "fixturen ga ingen datoer å prøve"
    assert all(d.get("kontekst") is None for d in datoer)


def test_fodselsdato_fra_fnr_fjernes():
    """Oppføringen er både persondata OG en bekreftelse på at et
    mod11-gyldig nummer står i dokumentet — samme eksistenslekkasje som
    opphav-pekerne R89 fjernet."""
    typer = [d.get("type") for d in
             (_svar(profil="sammendrag")["felter"] or {}).get(
                 "datoer_detaljert") or []]
    assert "fodselsdato_fra_fnr" not in typer
    typer_fullt = [d.get("type") for d in
                   (_svar(profil="full")["felter"] or {}).get(
                       "datoer_detaljert") or []]
    assert "fodselsdato_fra_fnr" in typer_fullt, "speilet mangler"


# ------------------------------------------------------------------ #
#  3. Ingenting forsvinner i stillhet                                  #
# ------------------------------------------------------------------ #

def test_alt_som_fjernes_navngis_i_utelatt():
    """R65-løftet: en klient skal kunne SE hva den ikke fikk."""
    utelatt = _svar(profil="sammendrag")["dokumentprofil"]["utelatt"]
    assert "tekst" in utelatt
    assert any(u.startswith("felter.felter.") for u in utelatt)
    assert "felter.datoer_detaljert[].kontekst" in utelatt
    assert "part" in utelatt, "seksjonene skal fortsatt navngis"


# ------------------------------------------------------------------ #
#  4. Advarselen siterer ikke verdiene                                 #
# ------------------------------------------------------------------ #

def test_uenighetsvarselet_siterer_ikke_persondata():
    """Advarselen havner i `varsler` OG `kvalitet.advarsler`, og ingen
    av dem berøres av bryteren. Et fødselsnummer sitert der ville nådd
    fram i et svar som uttrykkelig ba om det motsatte."""
    linjer = api._uenighet_med_modellen(
        {"part": {"fnr": FNR, "navn": NAVN}},
        {"skjema": {"skjema": {"fnr": FNR_FRA_MODELLEN, "navn": "Feil Navn"},
                    "kilde_per_felt": {"fnr": "modell", "navn": "modell"}}})
    assert linjer, "advarselen skal fortsatt utløses"
    for linje in linjer:
        assert FNR not in linje and NAVN not in linje, linje
        assert FNR_FRA_MODELLEN not in linje, linje
        assert "Feil Navn" not in linje, linje
        # men den må fortsatt si HVA som er uenig, og hvor man ser
        assert "dokumentprofil.part" in linje


# ------------------------------------------------------------------ #
#  5. Samme vern på operasjonsveien (R90)                              #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("merke", sorted(HEMMELIGHETER))
def test_operasjonsveien_har_samme_vern(merke):
    """R90: bryteren må virke i BEGGE kontraktene. Uten dette mistet en
    klient vernet ved å bytte fra brytere til «operasjoner» — og
    operasjonen «felter» leverer de samme identifikatorene."""
    funn = _stier_med(_operasjonssvar(profil="sammendrag"),
                      HEMMELIGHETER[merke])
    assert not funn, (
        f"{merke} nådde fram gjennom /dokument/operasjoner:\n  "
        + "\n  ".join(funn))


# ------------------------------------------------------------------ #
#  6. Blokkene bryteren IKKE så på (R152)                              #
# ------------------------------------------------------------------ #
#
# Punkt 5 over ba bare om operasjonene «felter» og «tekst» — og det var
# nettopp derfor «struktur» slapp unna: den falt gjennom en
# `isinstance(data, dict)`-gren inn i en rensing som leter etter
# nøklene `felter` og `datoer_detaljert`. «struktur» har ingen av dem.
#
# Målt før rettingen, med profil=sammendrag:
#     resultater[struktur].data.identifikatorer.fodselsnummer  → verdien
#     korrigert_tekst                                          → HELE dokumentet
#     utelatt                                                  → []   (!)
#
# Den siste linja er den verste: svaret avga en erklæring om seg selv
# som ikke stemte.

ALLE_OPERASJONER = ('[{"type":"felter"},{"type":"tekst"},'
                    '{"type":"struktur"}]')


@pytest.mark.parametrize("merke", sorted(HEMMELIGHETER))
def test_operasjonen_struktur_har_ogsaa_vern(merke):
    """«struktur» er den PARALLELLE utvinningen av de samme
    identifikatorene — samme begrunnelse som på bryterveien."""
    funn = _stier_med(_operasjonssvar("sammendrag", ALLE_OPERASJONER),
                      HEMMELIGHETER[merke])
    assert not funn, (
        f"{merke} nådde fram gjennom operasjonen «struktur»:\n  "
        + "\n  ".join(funn))


def test_operasjonsveien_sier_hva_den_tok_bort():
    """R65: ingenting forsvinner i stillhet — heller ikke her. Uten
    dette rensa operasjonsveien i det stille, og klienten hadde ingen
    måte å se at noe var fjernet."""
    svar = _operasjonssvar("sammendrag", ALLE_OPERASJONER)
    assert svar.get("utelatt"), "operasjonsveien meldte ingenting"
    assert "resultater[struktur].data" in svar["utelatt"]


def _fullt_svar():
    """Svarkroppen slik den ser ut når ALLE delene faktisk ble fylt.

    Bygges her fordi Borealis er nede i testmiljøet: `korriger` og
    `skjema` er da alltid `None`, og en vakt som bare kjører den ekte
    veien ville aldri sett disse blokkene."""
    return {
        "tekst": DOK,
        "korrigert_tekst": DOK,
        "korriger": {"tekst": DOK, "endringer": 3},
        "struktur": {"identifikatorer": {"fodselsnummer": [FNR]}},
        "felter": {"felter": {"fodselsnummer": FNR, "navn": NAVN}},
        "skjema": {"skjema": {"soker_fodselsnummer": FNR,
                              "soker_navn": NAVN,
                              "saksnummer": "4417820"}},
        "koordinater": {"sider": [{"side": 1, "funn": [
            {"boks": [0, 0, 10, 10], "tekst": f"Fodselsnummer: {FNR}"}]}]},
        "opphav": {"/skjema/skjema/soker_fodselsnummer":
                   {"metode": "regel", "konfidens": "hoy",
                    "begrunnelse": "Bevist deterministisk av uttrekket"},
                   "/felter/felter/navn":
                   {"metode": "regel", "konfidens": "hoy",
                    "begrunnelse": "Merket i dokumentet"}},
        "dokumentprofil": {"utelatt": []},
    }


@pytest.mark.parametrize("merke", sorted(HEMMELIGHETER))
def test_alle_blokkene_i_et_fullt_svar(merke):
    """Den brede prøven: hver blokk som KAN bære dokumentet, fylt."""
    svar = api._sammendragsform(_fullt_svar())
    funn = _stier_med(svar, HEMMELIGHETER[merke])
    assert not funn, (
        f"{merke} sto igjen i:\n  " + "\n  ".join(funn))


def test_pekerne_folger_med_naar_feltet_nulles():
    """En peker til et nullet felt lekker det bryteren skulle skjule:
    at nummeret STÅR i dokumentet, og at vi beviste det. Samme klasse
    som pekerne R89 fjernet fra /part/fnr."""
    svar = api._sammendragsform(_fullt_svar())
    assert "/skjema/skjema/soker_fodselsnummer" not in svar["opphav"]
    assert "/felter/felter/navn" not in svar["opphav"]


def test_alt_som_ble_nullet_staar_i_utelatt():
    """R65 for de nye blokkene også. Uten dette meldte svaret at
    «tekst» var fjernet mens det lå ordrett i `korrigert_tekst`."""
    svar = api._sammendragsform(_fullt_svar())
    meldt = set(svar["dokumentprofil"]["utelatt"])
    for ventet in ("tekst", "korrigert_tekst", "korriger.tekst", "struktur",
                   "skjema.skjema.soker_fodselsnummer",
                   "koordinater.sider[].funn[].tekst"):
        assert ventet in meldt, f"«{ventet}» ble nullet uten å bli meldt"


def test_skjemafelt_uten_persondata_staar_igjen():
    """Motprøven. Bryteren skal ta persondata, ikke tømme skjemaet."""
    svar = api._sammendragsform(_fullt_svar())
    assert svar["skjema"]["skjema"]["saksnummer"] == "4417820"


@pytest.mark.parametrize("type_", ["tekst", "korriger", "struktur"])
def test_hver_raatekstbaerende_operasjonstype_renses(type_):
    """Prøver funksjonen direkte. Operasjonen «korriger» krever
    Borealis, som er nede i testmiljøet — så den ekte veien produserer
    den aldri, og en vakt som bare kjører den ekte veien ville vært
    grønn uansett hva koden gjorde med typen."""
    svar = api._sammendragsform_operasjoner(
        {"resultater": [{"type": type_, "ok": True,
                         "data": DOK if type_ != "struktur"
                         else {"identifikatorer": {"fodselsnummer": [FNR]}}}]})
    assert svar["resultater"][0]["data"] is None, (
        f"operasjonen «{type_}» leverte dokumentet under sammendrag")
    assert f"resultater[{type_}].data" in (svar.get("utelatt") or [])

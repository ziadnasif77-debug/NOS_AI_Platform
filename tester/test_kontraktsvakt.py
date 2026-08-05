"""
Vakter for API-kontrakten (fase 3 i arkitekturrevisjonen).

To feilklasser dekkes her:

1. SPEIL SOM KAN DIVERGERE. `filnavn`, `antall_sider` og `strekkoder`
   står flere steder i samme svar. Revisjonen konkluderte med å BEHOLDE
   dupliseringen — den har kontraktsverdi — men da må det være umulig
   for kopiene å si ulike ting. Det er en test, ikke en sletting.

2. SKJEMAET SOM ENDRER SEG I STILLHET. `API_VERSJON` sto urørt på
   1.3.0 gjennom 45 commits mens `koordinater`, hele `operasjoner`-
   kontrakten, `hjemmel`, `sammendrag` og `dokumenter[]` kom til. Tallet
   i svaret sa ingenting. Vakten under feiler når profilens nøkkelsett
   endres uten at fasiten oppdateres — da må man ta stilling til om
   versjonen skal opp.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api
from delt.dokumentprofil import SKJEMAVERSJON
from syntetiske_nummer import lag_fnr

FASIT_STI = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "fasit_profilnokler.json")

DOKUMENT = f"""[Side 1 av 2]
NAV Arbeid og ytelser
Vedtak om sykepenger
Vedtaksdato: 28.05.2026
Saksnummer: 4417820
Dokumentet gjelder:
Ola Nordmann
Fnr: {lag_fnr(0)}
Dagsats: kr 1 234,00
[Side 2 av 2]
Mottatt NAV 30.05.2026
"""


def _profil():
    ktx = api.DokumentKontekst(DOKUMENT, antall_sider=2, filnavn="test.pdf")
    return ktx.profil


# ------------------------------------------------------------------ #
#  1. Speil som ikke får divergere                                     #
# ------------------------------------------------------------------ #

def test_sideantallet_er_likt_alle_tre_steder():
    """Rot, `fil` og `sammendrag`. Verdien er den samme variabelen i dag,
    men ingenting HINDRET at de gled fra hverandre."""
    ktx = api.DokumentKontekst(DOKUMENT, antall_sider=2, filnavn="test.pdf")
    profil = ktx.profil
    assert ktx.antall_sider == profil["fil"]["antall_sider"]
    assert ktx.antall_sider == profil["sammendrag"]["antall_sider"]


def test_filnavnet_er_likt_begge_steder():
    ktx = api.DokumentKontekst(DOKUMENT, antall_sider=2, filnavn="test.pdf")
    assert ktx.filnavn == ktx.profil["fil"]["filnavn"]


def test_strekkodene_er_de_samme_i_rot_og_profil():
    """Rotlista og profilens `koder` deler samme kilde. Profilen deler
    dem på symbologi og legger til `lest`/`merknad` — men VERDIENE må
    være identiske."""
    koder = [{"type": "CODE128", "verdi": "123", "side": 3},
             {"type": "QRCODE", "verdi": "abc", "side": 1}]
    ktx = api.DokumentKontekst(DOKUMENT, strekkoder=koder, antall_sider=2)
    i_profil = ktx.profil["koder"]["qr"] + ktx.profil["koder"]["strekkode"]
    assert sorted(k["verdi"] for k in koder) == \
        sorted(k["verdi"] for k in i_profil)
    assert sorted(k["side"] for k in koder) == \
        sorted(k["side"] for k in i_profil)


def test_ett_navn_per_felt():
    """v1 ble aldri utgitt, så de doble navnene beskyttet klienter som
    ikke fantes. Hvert felt har nå ETT navn — og testen her hindrer at
    et gammelt sniker seg inn igjen fordi noen «husket» det."""
    profil = _profil()
    for gammelt in ("eier", "andre_personer"):
        assert gammelt not in profil, f"«{gammelt}» er borte — bruk det nye"
    assert "sikkerhet" not in profil["part"]         # bruk «grunnlag»
    assert "sikkerhet" not in profil["sammendrag"]   # bruk «konfidens»
    assert "implementasjon" not in profil["ytelse"]  # bruk «dekning.ytelse»
    assert "ar" not in profil["dokument"]            # bruk «aarstall»


def test_konfidensskalaen_er_EN_skala():
    """«usikker» var et fjerde ord for det «lav» allerede het, så en
    klient som filtrerte på «lav» aldri traff sammendraget."""
    lovlige = {"hoy", "middels", "lav", "ingen"}
    profil = _profil()
    assert profil["sammendrag"]["konfidens"] in lovlige
    assert profil["dokument"]["dato_sikkerhet"] in lovlige


# ------------------------------------------------------------------ #
#  2. Skjemaet skal ikke endre seg i stillhet                          #
# ------------------------------------------------------------------ #

def _nokkelsett(obj, prefiks=""):
    """Alle JSON-stier i profilen, uten verdiene."""
    ut = []
    if isinstance(obj, dict):
        for k in sorted(obj):
            ut.append(f"{prefiks}/{k}")
            ut += _nokkelsett(obj[k], f"{prefiks}/{k}")
    elif isinstance(obj, list) and obj:
        ut += _nokkelsett(obj[0], f"{prefiks}[]")
    return ut


def test_profilens_nokkelsett_er_uendret():
    """Feiler skjemaet er endret. Da skal du:
      1) vurdere om `SKJEMAVERSJON` i delt/dokumentprofil.py må opp, og
      2) kjøre denne testen med UOPPDATER_FASIT=1 for å skrive ny fasit.

    Poenget er ikke å hindre endring — det er å hindre at den skjer uten
    at noen tar stilling til versjonen."""
    naa = _nokkelsett(_profil())
    if os.environ.get("UOPPDATER_FASIT"):
        with open(FASIT_STI, "w", encoding="utf-8") as f:
            json.dump({"skjemaversjon": SKJEMAVERSJON, "nokler": naa},
                      f, ensure_ascii=False, indent=1)
        pytest.skip("fasiten er skrevet på nytt")
    if not os.path.exists(FASIT_STI):
        pytest.skip(f"ingen fasit ennå — lag den med UOPPDATER_FASIT=1")
    with open(FASIT_STI, encoding="utf-8") as f:
        fasit = json.load(f)

    nye = sorted(set(naa) - set(fasit["nokler"]))
    borte = sorted(set(fasit["nokler"]) - set(naa))
    assert not (nye or borte), (
        f"Profilskjemaet er endret.\n  NYE: {nye}\n  BORTE: {borte}\n"
        f"Fasiten gjelder skjemaversjon {fasit['skjemaversjon']}, koden "
        f"står på {SKJEMAVERSJON}. Vurder om versjonen må opp, og kjør "
        f"deretter med UOPPDATER_FASIT=1.")


def test_fasiten_gjelder_dagens_skjemaversjon():
    """Fanger det motsatte: at noen bumper versjonen uten å oppdatere
    fasiten, eller omvendt."""
    if not os.path.exists(FASIT_STI):
        pytest.skip("ingen fasit ennå")
    with open(FASIT_STI, encoding="utf-8") as f:
        fasit = json.load(f)
    assert fasit["skjemaversjon"] == SKJEMAVERSJON, (
        f"Fasiten er for skjemaversjon {fasit['skjemaversjon']}, men koden "
        f"står på {SKJEMAVERSJON}. Kjør med UOPPDATER_FASIT=1.")


# ------------------------------------------------------------------ #
#  3. Bryterne oppfører seg som resten                                 #
# ------------------------------------------------------------------ #

def test_profil_sammendrag_utelater_persondata_og_sier_hva():
    """`profil=sammendrag` finnes for personvern: en klient som bare
    spør om en dato skal slippe å motta fødselsnummer og adresse."""
    liten = api._profilform(_profil(), "sammendrag")
    assert "part" not in liten
    assert "kontakt" not in liten
    assert "fnr" not in liten["sammendrag"]
    assert "navn" not in liten["sammendrag"]
    # ingenting forsvinner i stillhet
    assert "part" in liten["utelatt"]
    assert "kontakt" in liten["utelatt"]


def test_sammendrag_beholder_saksinformasjon_uten_persondata():
    """`profil=sammendrag` er en PERSONVERNbryter, ikke en
    størrelsesbryter. `ytelser` og `hjemler` sier hva dokumentet handler
    om og hvilke bestemmelser det viser til — utelot vi dem, ville
    `utelatt` påstå at de gikk ut av personvernhensyn, og klienten mistet
    nettopp den saksinformasjonen den ba om."""
    liten = api._profilform(_profil(), "sammendrag")
    assert "ytelser" in liten
    assert "hjemler" in liten
    assert "ytelser" not in liten["utelatt"]
    assert "hjemler" not in liten["utelatt"]


def test_profil_full_er_uendret():
    profil = _profil()
    assert api._profilform(profil, "full") == profil


def test_hver_dokumenttype_har_et_lesbart_navn():
    """Uten en term faller `kodeverk()` tilbake til koden, og en bruker
    får «legeerklaring» i skjermbildet — uten æøå, fordi koden er skrevet
    slik for å kunne matches mot OCR-tekst. Det er ikke en visningsverdi."""
    from delt.tekstuttrekk import _DOKUMENTTYPER, DOKUMENTTYPE_TERM
    mangler = sorted({kode for kode, _ in _DOKUMENTTYPER}
                     - set(DOKUMENTTYPE_TERM))
    assert not mangler, f"Dokumenttyper uten term: {mangler}"


def test_hver_ytelse_har_et_lesbart_navn():
    from delt.konstanter import NORSKE_YTELSER, YTELSE_TERM
    mangler = sorted(NORSKE_YTELSER - set(YTELSE_TERM))
    assert not mangler, f"Ytelser uten term: {mangler}"


def test_ingen_term_uten_en_kode_a_hore_til():
    """Motsatt vei: en term for en kode som ikke finnes er en gammel
    verdi som ble omdøpt eller fjernet uten at tabellen fulgte etter."""
    from delt.konstanter import NORSKE_YTELSER, YTELSE_TERM
    from delt.tekstuttrekk import _DOKUMENTTYPER, DOKUMENTTYPE_TERM
    assert not sorted(set(YTELSE_TERM) - NORSKE_YTELSER)
    assert not sorted(set(DOKUMENTTYPE_TERM) - {k for k, _ in _DOKUMENTTYPER})


def test_kodet_par_og_ra_verdi_kan_ikke_avvike():
    """`type` og `type_kodet.kode` er samme faktum to steder — nok et
    speil, med samme krav som de andre."""
    profil = _profil()
    assert profil["dokument"]["type_kodet"]["kode"] == profil["dokument"]["type"]
    if profil["ytelse"]["navn"]:
        assert (profil["ytelse"]["navn_kodet"]["kode"]
                == profil["ytelse"]["navn"])


def test_uten_verdi_er_det_kodede_paret_null_ikke_et_tomt_par():
    """`{"kode": null, "term": null}` ville sagt at det FINNES en type
    som bare mangler navn. Null sier at typen ikke ble fastslått."""
    tom = api.DokumentKontekst("Helt tom tekst uten kjennetegn.",
                               antall_sider=1).profil
    assert tom["dokument"]["type_kodet"] is None
    assert tom["ytelse"]["navn_kodet"] is None


def test_dekningsgraden_folger_om_ytelsen_faktisk_ble_funnet():
    """`dekning.ytelse` sier om systemet LETER etter ytelsen ennå. Den
    lå tidligere også i `ytelse.implementasjon` — to navn på samme
    faktum — og har nå bare ett hjem."""
    profil = _profil()
    ventet = "delvis" if profil["ytelse"]["navn"] else "ingen"
    assert profil["dekning"]["ytelse"] == ventet


# ------------------------------------------------------------------ #
#  4. OpenAPI skal beskrive det svaret FAKTISK inneholder              #
# ------------------------------------------------------------------ #

def test_openapi_dekker_hver_profilseksjon():
    """`sammendrag`, `dokumenter` og `hjemmel` fantes i svaret i flere
    utgivelser uten å stå i spesifikasjonen. En integrator som leste
    /openapi.json fikk da vite mindre enn serveren sendte — og
    revisjonen fant nettopp det. Testen gjør glippen umulig."""
    spek = api._openapi()["components"]["schemas"]["Dokumentprofil"]
    mangler = sorted(set(_profil()) - set(spek["properties"]))
    assert not mangler, (
        f"Disse seksjonene er i svaret, men ikke i OpenAPI: {mangler}. "
        f"Legg dem inn i _skjemaer()['Dokumentprofil'].")


def test_ingenting_er_merket_deprecated():
    """Det finnes ikke lenger et eneste utgått felt: v1 var aldri utgitt,
    så alt som bare eksisterte for bakoverkompatibilitet er fjernet i
    stedet for å bli merket og båret videre i tolv måneder."""
    def gaa(node):
        if isinstance(node, dict):
            if node.get("deprecated"):
                yield node
            for verdi in node.values():
                yield from gaa(verdi)
        elif isinstance(node, list):
            for verdi in node:
                yield from gaa(verdi)

    merket = list(gaa(api._openapi()))
    assert not merket, (
        f"{len(merket)} felt er merket deprecated. Er et felt utgått, skal "
        f"det FJERNES så lenge API-et er uutgitt — merking er for felter "
        f"klienter allerede bruker.")


def test_ingen_brutte_referanser_i_openapi():
    """En $ref til et skjema som ikke finnes gjør at Swagger UI viser
    tomt felt i stedet for å feile."""
    spek = api._openapi()
    kjente = set(spek["components"]["schemas"])
    brutte = []

    def se(node):
        if isinstance(node, dict):
            pekt = node.get("$ref")
            if pekt and pekt.split("/")[-1] not in kjente:
                brutte.append(pekt)
            for verdi in node.values():
                se(verdi)
        elif isinstance(node, list):
            for verdi in node:
                se(verdi)

    se(spek)
    assert not brutte, f"Brutte $ref: {sorted(set(brutte))}"


def test_openapi_kjenner_hver_bryter_i_dokument():
    """Lista hentes fra `_KJENTE_FELT_DOKUMENT` — den serveren FAKTISK
    godtar — ikke fra en håndskrevet kopi her. En håndskrevet kopi ville
    bare vært et tredje sted å glemme et felt. `strekkoder` sto
    udokumentert i flere utgivelser nettopp fordi ingen sammenlignet."""
    spek = api._openapi()
    kropp = spek["paths"]["/dokument"]["post"]["requestBody"]
    felter = kropp["content"]["multipart/form-data"]["schema"]["properties"]
    mangler = sorted(api._KJENTE_FELT_DOKUMENT - set(felter))
    assert not mangler, (
        f"Serveren godtar disse bryterne, men OpenAPI nevner dem ikke: "
        f"{mangler}")


def test_hver_dokumentert_bryter_godtas_av_serveren():
    """Den motsatte veien: en bryter som står i spesifikasjonen, men
    ikke i `_KJENTE_FELT_DOKUMENT`, gir 200 med «ukjent felt»-advarsel.
    Klienten gjorde alt riktig og får likevel en advarsel."""
    spek = api._openapi()
    kropp = spek["paths"]["/dokument"]["post"]["requestBody"]
    felter = set(kropp["content"]["multipart/form-data"]["schema"]
                 ["properties"]) - {"fil"}
    ukjente = sorted(felter - api._KJENTE_FELT_DOKUMENT)
    assert not ukjente, (
        f"OpenAPI lover disse bryterne, men serveren kjenner dem ikke: "
        f"{ukjente}")

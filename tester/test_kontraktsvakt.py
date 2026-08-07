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


def test_versjonsnummeret_teller_utgivelser_ikke_utviklingsrunder():
    """API_VERSJON gikk 1.3.0 → 1.6.0 → 2.0.0 mens API-et lå på én
    maskin uten en eneste klient. «2.0.0» ville påstått at det fantes en
    1.x som ble brutt — og et versjonsnummer som lyver er verre enn
    ingen, for det er nettopp det man stoler på i stedet for å lese
    endringsloggen (R108).

    Testen holder tallet på 1.0.0 fram til FØRSTE utgivelse. Skal det
    opp, er det fordi noen utenfor maskinen bruker den forrige — og da
    endres denne testen bevisst, ikke i forbifarten."""
    assert api.API_VERSJON == "1.0.0", (
        f"API_VERSJON er {api.API_VERSJON}. Er API-et utgitt nå? I så "
        f"fall: oppdater denne testen og R108. Ellers er tallet en "
        f"utviklingsrunde ingen utenfor maskinen har sett.")
    assert SKJEMAVERSJON == "1.0", (
        f"skjemaversjon er {SKJEMAVERSJON} — samme spørsmål som over.")


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
    # Samme argument gjelder «gjeldende_lov»: den er AVLEDET av
    # dokumentdatoen alene (R113) og bærer ingen persondata.
    assert "gjeldende_lov" in liten
    assert "gjeldende_lov" not in liten["utelatt"]


def test_beholdlista_navngir_bare_seksjoner_som_finnes():
    """Fanger feilen dette var: lista beholdt «hjemmel», et navn R113
    hadde døpt om til «gjeldende_lov». Det gamle navnet traff ingenting,
    og det nye sto ikke i lista — så personvernbryteren fjernet en
    seksjon uten persondata, og «utelatt» meldte den som fjernet av
    personvernhensyn.

    Et navn i lista som ikke finnes i profilen er alltid en slik feil:
    enten er seksjonen borte, eller så er den døpt om."""
    profil = _profil()
    ukjente = sorted(n for n in api._PROFIL_SAMMENDRAG_BEHOLD
                     if n not in profil)
    assert not ukjente, (
        f"Disse står i behold-lista, men finnes ikke i profilen: "
        f"{ukjente}. Er en seksjon døpt om, må lista følge med — ellers "
        f"faller den ut av «profil=sammendrag» i stillhet.")


def test_profil_full_er_uendret_bortsett_fra_interne_felt():
    """`profil=full` skal levere alt — men de interne arbeidsfeltene
    (understrek) er ikke «alt». De finnes for at «opphav» skal slippe å
    lete opp noe uttrekket allerede vet, og de er ikke i kontrakten."""
    profil = _profil()
    levert = api._profilform(profil, "full")
    assert "_posisjon" in profil["part"], "det interne feltet skal finnes"
    assert "_posisjon" not in levert["part"], "men ALDRI i svaret"
    assert "_ord" in profil["ytelse"], "det norske ytelsesordet er internt"
    assert "_ord" not in levert["ytelse"], "men ALDRI i svaret"

    # Alt ANNET er identisk. Sammenligningen må gjelde hver seksjon, ikke
    # bare «part»: testen sto med «part» som eneste unntak, og den dagen
    # ytelsen fikk sitt eget arbeidsfelt feilet den på en endring som var
    # helt etter boka. Det er formen som skal voktes — hvilke seksjoner
    # som HAR interne felt er en detalj som får endre seg.
    def _uten_interne(node):
        if isinstance(node, dict):
            return {k: _uten_interne(v) for k, v in node.items()
                    if not k.startswith("_")}
        if isinstance(node, list):
            return [_uten_interne(v) for v in node]
        return node

    assert levert == _uten_interne(profil)


def test_ingen_interne_felt_lekker_ut():
    """Et felt med understrek i svaret ville brutt R118: nøkkelsettet er
    fast, og et arbeidsfelt hører ikke hjemme i det."""
    import re as _re
    levert = api._profilform(_profil(), "full")
    lekk = _re.findall(r'"(_[a-z_]+)"', json.dumps(levert, ensure_ascii=False))
    assert not lekk, f"interne felt i svaret: {sorted(set(lekk))}"


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


def test_kategoriverdien_ER_paret_ikke_et_par_ved_siden_av():
    """`type` og `type_kodet` bar ALLTID samme kode — speiltesten som
    håndhevet det var beviset på at paret var en kopi av seg selv. Nå ER
    verdien paret."""
    profil = _profil()
    assert set(profil["dokument"]["type"]) == {"kode", "term"}
    assert profil["dokument"]["type"]["kode"] == "vedtak"
    assert profil["dokument"]["type"]["term"] == "Vedtak"
    som_tekst = json.dumps(profil, ensure_ascii=False)
    for gammelt in ("type_kodet", "sakstype_kodet", "navn_kodet"):
        assert gammelt not in som_tekst, f"«{gammelt}» finnes ennå"


def test_uten_verdi_er_PARET_der_med_null_i_begge():
    """Formen er FAST. Klientene er RPA-roboter som leser
    `dokument.type.kode` blindt; er `type` null, finnes ikke stien, og
    roboten krasjer på dokument nummer to (R118).

    `{kode: null}` betyr «ikke fastslått» — det står i dokumentasjonen,
    og `dekning` sier hvorfor."""
    tom = api.DokumentKontekst("Helt tom tekst uten kjennetegn.",
                               antall_sider=1).profil
    assert tom["dokument"]["type"] == {"kode": None, "term": None}
    assert tom["ytelse"]["navn"] == {"kode": None, "term": None}


def test_ingen_presentasjonstvillinger():
    """`dato_norsk` var en andre RENDERING av den normaliserte verdien:
    «28. mai 2026», «28/05/2026», «2026-05-28» og «28.5.26» ga ALLE
    samme tvilling «28.05.2026». Et API som leverer ISO skal ikke også
    formatere — det gjør det ansvarlig for presentasjon i stedet for
    data."""
    assert "_norsk" not in json.dumps(_profil(), ensure_ascii=False),         "en presentasjonstvilling har sneket seg inn igjen"


def test_originalen_er_ordrett_ikke_normalisert():
    """Det som MANGLET da tvillingen forsvant: hva som faktisk STO i
    dokumentet. Leser OCR «28. mai 2026», vil du se det — ikke den
    normaliserte formen om igjen."""
    dok = api.DokumentKontekst("Dokumentdato: 28. mai 2026",
                               antall_sider=1).profil["dokument"]
    assert dok["dato"] == "2026-05-28"
    assert dok["dato_original"] == "28. mai 2026"


def test_dekning_og_konfidens_bruker_IKKE_samme_ord():
    """Den farligste sammenblandingen. «ingen» i dekning betød «vi leter
    ikke etter feltet»; «ingen» i konfidens betyr «vi lette og fant
    ingenting» — en påstand om DOKUMENTET. Samme ord, motsatt
    betydning: en klient som leste dekning-«ingen» som «mangler
    signatur» bygget en beslutning på en løgn."""
    profil = _profil()
    for verdi in profil["dekning"].values():
        if isinstance(verdi, str) and not verdi.startswith("«"):
            assert verdi in ("full", "delvis", "ikke_evaluert"), verdi
    assert profil["dokument"]["dato_sikkerhet"] in ("hoy", "middels",
                                                    "lav", "ingen")


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


# ------------------------------------------------------------------ #
#  5. Når modellen og uttrekket er uenige, SIER vi fra                 #
# ------------------------------------------------------------------ #

def test_uenighet_mellom_modell_og_uttrekk_meldes():
    """Revisjonen fant at de tre veiene til samme faktum FAKTISK var
    uenige i et ekte svar — «NOR-ETTERNAVN, OLA» mot «Ola Nordmann» —
    og konkluderte med å beholde alle tre, fordi de har ulik garanti og
    en sammenslåing ville slettet nettopp signalet.

    Men signalet ble aldri MELDT. En klient måtte sammenligne selv, og
    gjorde det ikke. Det deterministiske uttrekket er fasit: det er
    bevist med etikett og mod11, modellens verdi er ikke."""
    fnr = lag_fnr(0)
    profil = {"part": {"fnr": fnr, "navn": "Ola Nordmann"}}
    deler = {"skjema": {"skjema": {"navn": "NOR-ETTERNAVN, OLA"},
                        "kilde_per_felt": {"navn": "modell"}}}
    varsel = api._uenighet_med_modellen(profil, deler)
    assert len(varsel) == 1
    assert "uenige om «navn»" in varsel[0]
    assert "Ola Nordmann" in varsel[0]


def test_enighet_gir_ingen_stoy():
    fnr = lag_fnr(0)
    profil = {"part": {"fnr": fnr, "navn": "Ola Nordmann"}}
    deler = {"skjema": {"skjema": {"navn": "Ola Nordmann"},
                        "kilde_per_felt": {"navn": "modell"}}}
    assert api._uenighet_med_modellen(profil, deler) == []


def test_et_deterministisk_felt_sammenlignes_ikke_med_seg_selv():
    """Fylte den hybride motoren feltet DETERMINISTISK, er det samme
    kilde som profilen — da er «uenighet» meningsløst."""
    profil = {"part": {"fnr": None, "navn": "Ola Nordmann"}}
    deler = {"skjema": {"skjema": {"navn": "noe helt annet"},
                        "kilde_per_felt": {"navn": "deterministisk"}}}
    assert api._uenighet_med_modellen(profil, deler) == []


def test_varselet_faar_sin_egen_type():
    """«uenighet» skal kunne filtreres på uten tekstsøk."""
    typer = {v["kode"] for v in api._varsler(
        ["Modellen og uttrekket er uenige om «navn»: …"])}
    assert "uenighet" in typer


# ------------------------------------------------------------------ #
#  6. Sidedekning — den farligste tause avkortingen                    #
# ------------------------------------------------------------------ #

def _delvis(lest=10, totalt=500):
    """Et dokument der bare de N første sidene ga tekst."""
    tekst = "\n".join(f"[Side {i} av {totalt}]\nInnhold side {i}"
                      for i in range(1, lest + 1))
    return api.DokumentKontekst(tekst, antall_sider=totalt).profil


def test_delvis_lest_dokument_sier_det_som_et_FELT():
    """Et skannet dokument på 500 sider får som standard OCR på 10 av
    dem. Advarselen sto i `varsler` — men ved millioner av dokumenter
    leser ingen `varsler`; de leser feltet og handler på det."""
    dekning = _delvis()["dekning"]
    assert dekning["sider_lest"] == "delvis"
    assert dekning["sider"] == {"lest": 10, "totalt": 500}


def test_begrunnelsen_paastaar_ikke_noe_om_usette_sider():
    """Kjernen. Før dette sa profilen «Dokumentet inneholder ingen
    fødselsnummer» om et dokument vi hadde sett 2 % av. Setningen var
    ikke sann — vi så ikke etter i 98 %."""
    profil = _delvis()
    assert "MERK: bare 10 av 500 sider" in profil["part"]["begrunnelse"]
    assert "ikke hele dokumentet" in profil["part"]["begrunnelse"]


def test_konfidensen_kan_ikke_vaere_hoy_paa_to_prosent():
    """Konfidensen er det SVAKESTE leddet (R74), og å ha lest 10 av 500
    sider ER et svakt ledd — uansett hvor sikre de leste feltene er."""
    fnr = lag_fnr(0)
    tekst = (f"[Side 1 av 500]\nDokumentet gjelder:\nOla Nordmann\n"
             f"Fnr: {fnr}\nVedtaksdato: 17.05.2024\n")
    tekst += "\n".join(f"[Side {i} av 500]\nInnhold" for i in range(2, 11))
    profil = api.DokumentKontekst(tekst, antall_sider=500).profil
    assert profil["part"]["fnr"] == fnr          # funnet, og sikkert
    assert profil["sammendrag"]["konfidens"] == "middels"


def test_full_dekning_gir_ingen_stoy():
    """Motprøven: leses alt, skal verken forbeholdet eller nedgraderingen
    slå inn."""
    fnr = lag_fnr(0)
    tekst = (f"[Side 1 av 1]\nDokumentet gjelder:\nOla Nordmann\n"
             f"Fnr: {fnr}\nVedtaksdato: 17.05.2024\n")
    profil = api.DokumentKontekst(tekst, antall_sider=1).profil
    assert profil["dekning"]["sider_lest"] == "full"
    assert "MERK" not in (profil["part"]["begrunnelse"] or "")
    assert profil["sammendrag"]["konfidens"] == "hoy"


def test_uten_sideantall_er_dekningen_ukjent_ikke_full():
    """Vet vi ikke hvor mange sider filen har, kan vi ikke påstå at alle
    er lest. «ukjent» er det ærlige svaret."""
    from delt.dokumentprofil import sidedekning
    assert sidedekning("[Side 1 av 3]\nnoe", None)["grad"] == "ukjent"


def test_ren_tekst_uten_sidemerker_er_full_dekning():
    """Sendes teksten direkte inn, finnes ingen sidemerker — og da er
    alt vi fikk, alt som finnes."""
    from delt.dokumentprofil import sidedekning
    assert sidedekning("bare tekst, ingen merker", 1)["grad"] == "full"

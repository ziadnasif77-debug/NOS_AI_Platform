"""
Tester for NAVs offisielle temakoder (R127).

Kjernen: `ytelse.navn.kode` skal være koden ANDRE NAV-systemer snakker
(«SYK»), ikke vår interne streng fra tekstgjenkjenningen
(«sykepenger»). En RPA-robot som ruter dokumenter videre slår opp
temakoden i sitt eget kodeverk; et norsk substantiv er bare vårt.

Det norske ordet forsvinner likevel ikke — det brukes fortsatt internt,
og de to testgruppene nederst vokter nettopp det: kapitteloppslaget i
lover.py og sidesøket i opphav.py ville begge blitt feil av en tre
bokstavers kode.
"""
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api
from delt.konstanter import NAV_TEMA, NORSKE_YTELSER, YTELSE_TEMA, YTELSE_TERM
from delt.tekstuttrekk import ytelse_kodet


def _profil(tekst, **kw):
    return api.DokumentKontekst(tekst, antall_sider=1, **kw).profil


# ------------------------------------------------------------------ #
#  1. Selve kodingen                                                   #
# ------------------------------------------------------------------ #

def test_koden_er_temakoden_ikke_det_norske_ordet():
    """Det brukeren ba om, ordrett."""
    assert ytelse_kodet("sykepenger") == {"kode": "SYK",
                                          "term": "Sykepenger"}


def test_tre_utfall_betyr_tre_ulike_ting():
    """Skillet er hele poenget med at termen fylles når koden mangler.

    `{kode: null, term: null}` = vi fant ingen ytelse.
    `{kode: null, term: fylt}` = vi fant den, men har ikke koden ennå.

    Slås de to sammen, ser et dokument vi FORSTO ut som et vi ikke
    forsto — og ingen oppdager at temakodelista har et hull."""
    assert ytelse_kodet(None) == {"kode": None, "term": None}
    assert ytelse_kodet("") == {"kode": None, "term": None}
    assert ytelse_kodet("arbeidsavklaringspenger") == {
        "kode": None, "term": "Arbeidsavklaringspenger"}


def test_ukjent_navn_gir_likevel_et_par():
    """R118: formen er fast. Et navn vi ikke har i kartet i det hele
    tatt skal ikke gi en manglende nøkkel eller en tom term."""
    par = ytelse_kodet("et navn vi aldri har sett")
    assert set(par) == {"kode", "term"}
    assert par["kode"] is None and par["term"]


def test_alle_vaare_ytelser_er_vurdert_mot_temalista():
    """Vakttest: en ny ytelse i NORSKE_YTELSER må få en beslutning —
    enten en temakode eller et uttrykkelig `None` med begrunnelse.

    Uten denne ville en ny ytelse falt gjennom til `kode: null` i
    stillhet, og en robot droppet dokumentet uten at noen visste at
    lista hadde et hull."""
    mangler = sorted(NORSKE_YTELSER - set(YTELSE_TEMA))
    assert not mangler, (
        f"Disse ytelsene er ikke vurdert mot NAVs temakoder: {mangler}. "
        f"Legg dem i YTELSE_TEMA — med kode hvis den finnes, ellers "
        f"None og en kommentar om at koden ikke er mottatt ennå.")


def test_ingen_oppdiktede_ytelser_i_kartet():
    """Motsatt vei: kartet skal ikke inneholde navn detektoren aldri
    kan produsere. Da hadde vi vedlikeholdt en kode som er død."""
    assert not sorted(set(YTELSE_TEMA) - NORSKE_YTELSER)


def test_hver_brukte_temakode_har_en_term():
    """En kode uten term ville gitt `term: "SYK"` — koden gjentatt som
    om den var lesbar."""
    brukt = {k for k in YTELSE_TEMA.values() if k}
    assert not sorted(brukt - set(NAV_TEMA))


def test_temakodene_har_NAVs_form():
    """Tre store bokstaver. Fanger en avskriftsfeil («Syk», «SYKE») før
    den blir sendt videre til et system som ikke kjenner den igjen."""
    gale = sorted(k for k in NAV_TEMA if not (len(k) == 3 and k.isupper()))
    assert not gale, f"ikke gyldige temakoder: {gale}"


# ------------------------------------------------------------------ #
#  2. I profilen                                                       #
# ------------------------------------------------------------------ #

def test_profilen_leverer_temakoden():
    profil = _profil("Vedtak om sykepenger\nDokumentdato: 01.03.2024")
    assert profil["ytelse"]["navn"] == {"kode": "SYK", "term": "Sykepenger"}


def test_dekningen_ser_ytelsen_ogsaa_uten_temakode():
    """Den farlige varianten: arbeidsavklaringspenger står tydelig i
    teksten, men har ingen temakode hos oss. Målte vi dekningen på
    KODEN, ville svaret sagt «ikke_evaluert» — altså at vi aldri lette —
    om en ytelse vi leste rett ut av dokumentet."""
    profil = _profil("Vedtak om arbeidsavklaringspenger\n"
                     "Dokumentdato: 01.03.2024")
    assert profil["ytelse"]["navn"]["kode"] is None
    assert profil["ytelse"]["navn"]["term"] == "Arbeidsavklaringspenger"
    assert profil["dekning"]["ytelse"] == "delvis"


def test_uten_ytelse_er_dekningen_ikke_evaluert():
    """Speilet av testen over — ellers beviser den ingenting."""
    profil = _profil("Et brev uten ytelse.\nDokumentdato: 01.03.2024")
    assert profil["dekning"]["ytelse"] == "ikke_evaluert"


def test_samme_tema_listes_bare_en_gang():
    """Temakodene er mange-til-én: pleiepenger og omsorgspenger er begge
    OMS. Uten avduping ville lista vist samme tema to ganger, som om
    dokumentet gjaldt to ulike ordninger."""
    profil = _profil("Vedtak om pleiepenger og omsorgspenger\n"
                     "Dokumentdato: 01.03.2024")
    koder = [y["kode"] for y in profil["ytelser"]]
    assert koder == ["OMS"], koder


def test_sammendraget_projiserer_temakoden():
    """Sammendraget viser bare koden — samme projeksjon som for
    dokumenttype. Da må det være TEMAkoden der også, ellers sier
    sammendraget og seksjonen hver sin ting."""
    profil = _profil("Vedtak om dagpenger\nDokumentdato: 01.03.2024")
    assert profil["sammendrag"]["ytelse"] == "DAG"


# ------------------------------------------------------------------ #
#  3. Det norske ordet lever videre INTERNT                            #
# ------------------------------------------------------------------ #

def test_lovoppslaget_bruker_ordet_ikke_koden():
    """Grunnen til at ordet må bli igjen: `sok_ytelse("SYK")` finner
    ingenting — folketrygdlovens kapitler heter «Sykepenger». Uten dette
    ville hjemmelen blitt tom for hvert eneste dokument."""
    profil = _profil("Vedtak om sykepenger\nDokumentdato: 01.03.2024")
    assert profil["gjeldende_lov"]["ytelse_kapittel"] == "8"


def test_hjemmelen_folger_dokumentdatoen_ikke_temakoden():
    """Uføretrygd og uførepensjon deler temakoden UFO. Det taper ingen
    informasjon nettopp fordi LOVEN velges av dokumentets dato (R77) —
    denne testen er beviset for at sammenslåingen er trygg."""
    gammel = _profil("Vedtak om uførepensjon\nDokumentdato: 14.06.1994")
    ny = _profil("Vedtak om uføretrygd\nDokumentdato: 14.06.2024")
    assert gammel["ytelse"]["navn"]["kode"] == "UFO"
    assert ny["ytelse"]["navn"]["kode"] == "UFO"
    assert gammel["gjeldende_lov"]["lov"] != ny["gjeldende_lov"]["lov"]
    assert gammel["gjeldende_lov"]["status"] == "opphevet"
    assert ny["gjeldende_lov"]["status"] == "gjeldende"


def test_opphavet_peker_paa_siden_ordet_staar_paa():
    """Sidesøket må gå på ordet. Med «SYK» ville det enten bommet helt,
    eller — verre — truffet inne i «sykemelding» på en annen side og
    pekt trygt og feil."""
    from delt.opphav import bygg_opphav
    tekst = ("[Side 1 av 2]\nSykemelding mottatt.\n"
             "[Side 2 av 2]\nVedtak om sykepenger\nDokumentdato: 01.03.2024")
    ktx = api.DokumentKontekst(tekst, antall_sider=2)
    kart = bygg_opphav(ktx.profil, "alle", tekst=tekst)
    post = kart.get("/dokumentprofil/ytelse/navn")
    assert post and post["side"] == 2, post


def test_ordet_naar_aldri_ut_i_svaret():
    """Arbeidsfeltet er internt. Lakk det ut, ville kontrakten hatt to
    navn på samme ytelse — og en klient valgt feil."""
    profil = _profil("Vedtak om sykepenger\nDokumentdato: 01.03.2024")
    assert profil["ytelse"]["_ord"] == "sykepenger"
    assert "_ord" not in api._profilform(profil, "full")["ytelse"]
    assert "_ord" not in api._profilform(profil, "sammendrag")["ytelse"]

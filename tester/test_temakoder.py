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
from delt.tekstuttrekk import ytelse_betegnelse, ytelse_kodet


def _profil(tekst, **kw):
    return api.DokumentKontekst(tekst, antall_sider=1, **kw).profil


# ------------------------------------------------------------------ #
#  1. Selve kodingen                                                   #
# ------------------------------------------------------------------ #

def test_koden_er_temakoden_ikke_det_norske_ordet():
    """Det brukeren ba om, ordrett."""
    assert ytelse_kodet("sykepenger") == {"kode": "SYK",
                                          "term": "Sykepenger"}


def test_tre_utfall_betyr_tre_ulike_ting(monkeypatch):
    """Skillet består, men det bæres nå av `betegnelse` (R134).

    Før sto det i `term`, som dermed betydde TO ting: temaets navn når
    det fantes en kode, og ytelsens eget navn når det ikke gjorde det.
    Et felt hvis betydning avhenger av innholdet kan ikke leses uten å
    kjenne innholdet først — og det gjorde `term` umulig å stole på i
    det VANLIGE tilfellet, der det beskrev temaet.

        kode fylt,  betegnelse fylt  = ytelse funnet og kodet
        kode null,  betegnelse fylt  = funnet, koden mangler HOS OSS
        kode null,  betegnelse null  = ingen ytelse funnet

    Den midterste veien har ingen levende ytelse igjen: AAP var den
    siste som manglet kode, og den kom inn 06.08.2026. Derfor SIMULERES
    et hull her. Uten dette ville koden som håndterer den neste
    manglende koden stått uprøvd til dagen den trengs."""
    assert ytelse_kodet(None) == {"kode": None, "term": None}
    assert ytelse_betegnelse(None) is None
    assert ytelse_betegnelse("") is None

    import delt.tekstuttrekk as tu
    monkeypatch.setitem(tu.YTELSE_TEMA, "sykepenger", None)
    assert ytelse_kodet("sykepenger") == {"kode": None, "term": None}
    assert ytelse_betegnelse("sykepenger") == "Sykepenger"


def test_termen_beskriver_ALLTID_koden():
    """Vakten mot at de to betydningene smelter sammen igjen. Måles på
    hele kartet, ikke på et eksempel: en ny ytelse arver kravet."""
    from delt.konstanter import NAV_TEMA, YTELSE_TEMA
    for navn in YTELSE_TEMA:
        par = ytelse_kodet(navn)
        if par["kode"] is None:
            assert par["term"] is None, navn
        else:
            assert par["term"] == NAV_TEMA.get(par["kode"], par["kode"]), navn


def test_ukjent_navn_gir_likevel_et_par():
    """R118: formen er fast. Et navn vi ikke har i kartet i det hele
    tatt skal ikke gi en manglende nøkkel — men termen er null, for det
    finnes ingen kode den kunne beskrevet. Navnet selv kommer ut som
    betegnelse, så det ikke forsvinner i stillhet."""
    par = ytelse_kodet("et navn vi aldri har sett")
    assert set(par) == {"kode", "term"}
    assert par["kode"] is None and par["term"] is None
    assert ytelse_betegnelse("et navn vi aldri har sett") == \
        "et navn vi aldri har sett"


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


def test_alle_ytelsene_har_faktisk_faatt_en_kode():
    """Strengere enn testen over: ikke bare VURDERT, men KODET.

    Alle 25 har en temakode nå. Blir dette rødt, er det enten fordi en
    ny ytelse er lagt inn uten kode, eller fordi en kode ble fjernet.
    Begge deler er lovlig — `{kode: null, term: fylt}` er en dokumentert
    tilstand (R127) — men ingen av delene skal skje i forbifarten, for
    en ytelse uten kode er en ytelse ingen robot kan rute.

    Er det bevisst: flytt ytelsen inn i UTEN_KODE her, med en kommentar
    om hvem vi venter på."""
    UTEN_KODE = set()      # tom: alle har kode per 06.08.2026
    faktisk = {y for y, k in YTELSE_TEMA.items() if not k}
    assert faktisk == UTEN_KODE, (
        f"Ytelser uten temakode: {sorted(faktisk)}. Har du fått koden, "
        f"legg den i YTELSE_TEMA. Venter du fortsatt på den, før den opp "
        f"i UTEN_KODE i denne testen så det er et VALG og ikke en glipp.")


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


def test_aap_har_egen_temakode():
    """AAP var den siste ytelsen uten kode. Kapittel 11 følger med, som
    bevis på at det norske ordet fortsatt driver lovoppslaget."""
    profil = _profil("Vedtak om arbeidsavklaringspenger\n"
                     "Dokumentdato: 01.03.2024")
    assert profil["ytelse"]["navn"] == {"kode": "AAP",
                                        "term": "Arbeidsavklaringspenger"}
    assert profil["gjeldende_lov"]["ytelse_kapittel"] == "11"
    assert profil["dekning"]["ytelse"] == "delvis"


def test_dekningen_maales_paa_ordet_ikke_paa_koden(monkeypatch):
    """Den farlige varianten, simulert: en ytelse står tydelig i teksten,
    men har ingen temakode. Målte vi dekningen på KODEN, ville svaret
    sagt «ikke_evaluert» — altså at vi aldri lette — om en ytelse vi
    leste rett ut av dokumentet.

    Ingen ytelse mangler kode i dag, så hullet lages her. Den dagen en
    ny ytelse kommer inn før koden gjør det, er dette veien den går."""
    import delt.tekstuttrekk as tu
    monkeypatch.setitem(tu.YTELSE_TEMA, "sykepenger", None)
    profil = _profil("Vedtak om sykepenger\nDokumentdato: 01.03.2024")
    assert profil["ytelse"]["navn"] == {"kode": None, "term": None}
    assert profil["ytelse"]["betegnelse"] == "Sykepenger"
    assert profil["dekning"]["ytelse"] == "delvis"


def test_uten_ytelse_er_dekningen_ikke_evaluert():
    """Speilet av testen over — ellers beviser den ingenting."""
    profil = _profil("Et brev uten ytelse.\nDokumentdato: 01.03.2024")
    assert profil["dekning"]["ytelse"] == "ikke_evaluert"


def test_ulike_ytelser_med_samme_tema_listes_hver_for_seg():
    """PREMISSET ER SNUDD, med vilje (R134).

    Denne testen krevde før at pleiepenger og omsorgspenger ble slått
    sammen til ÉN oppføring, fordi begge er OMS. Begrunnelsen var at det
    ikke tapte «informasjon vi trenger», siden lovvalget avgjøres av
    dokumentdatoen og ikke av ytelsesnavnet.

    Det holdt bare så lenge lovvalg var eneste konsument. En
    saksbehandler som ruter dokumentet trenger å vite HVILKEN av de tre
    kapittel 9-ytelsene det gjelder — de har ulike vilkår og ulike
    paragrafer. Og lista heter «ytelser»: den talte temaer, under et
    navn som lovet noe annet.

    Temaet er fortsatt avduplisert der det HØRER hjemme — i `navn`, som
    er identisk for alle tre."""
    profil = _profil("Vedtak om pleiepenger og omsorgspenger\n"
                     "Dokumentdato: 01.03.2024")
    assert [y["betegnelse"] for y in profil["ytelser"]] == \
        ["Pleiepenger", "Omsorgspenger"]
    # samme tema på begge — koden er fortsatt mange-til-én
    assert {y["navn"]["kode"] for y in profil["ytelser"]} == {"OMS"}


def test_samme_ytelse_nevnt_to_ganger_er_fortsatt_en_oppforing():
    """Avdupingen er ikke fjernet, bare flyttet til riktig nøkkel."""
    profil = _profil("Vedtak om pleiepenger. Pleiepenger innvilges.\n"
                     "Dokumentdato: 01.03.2024")
    assert [y["betegnelse"] for y in profil["ytelser"]] == ["Pleiepenger"]


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


# ------------------------------------------------------------------ #
#  R134: betegnelsen sier hvilken ytelse — temaet sier hvor den rutes  #
# ------------------------------------------------------------------ #

def test_de_historiske_merkene_overlever_ut_i_svaret():
    """Målt over HELE kartet, ikke på et eksempel — en ny historisk
    ytelse arver kravet.

    `YTELSE_TERM` merker 1966-ytelsene med vilje («Uførepensjon
    (1966-loven; i dag uføretrygd)»), nettopp for at et gammelt vedtak
    ikke skal leses som om det gjaldt dagens regelverk. Temanavnet
    strøk merket: `uforepensjon` ble meldt som «Uføretrygd», en ytelse
    som ikke fantes før 1997."""
    historiske = [n for n, t in YTELSE_TERM.items() if "1966-loven" in t]
    assert historiske, "fant ingen historiske ytelser å måle på"
    for navn in historiske:
        assert "1966-loven" in (ytelse_betegnelse(navn) or ""), navn


def test_svaret_motsier_ikke_seg_selv_om_en_1966_ytelse():
    """Selve regresjonen, målt ende til ende: et 1994-vedtak sa
    `term: "Uføretrygd"` SAMTIDIG som `gjeldende_lov: ftrl-1966`.
    Uføretrygd fantes ikke i 1994 — de to feltene kunne ikke begge
    være sanne."""
    profil = _profil("NAV\nVedtak om uforepensjon\n"
                     "Vedtaksdato: 12.05.1994\nDu innvilges uforepensjon.")
    assert profil["gjeldende_lov"]["lov"] == "ftrl-1966"
    assert "1966-loven" in profil["ytelse"]["betegnelse"]
    # koden står igjen: den er det en robot ruter på, og UFO er riktig
    assert profil["ytelse"]["navn"]["kode"] == "UFO"


def test_de_tre_kapittel_9_ytelsene_kan_skilles_fra_hverandre():
    """De deler tema OMS, men har hver sine vilkår og paragrafer. Med
    bare temaet kunne en saksbehandler ikke se hvilken det gjaldt."""
    sett = set()
    for ord_, forventet in (("pleiepenger", "Pleiepenger"),
                            ("omsorgspenger", "Omsorgspenger"),
                            ("opplaeringspenger", "Opplæringspenger")):
        profil = _profil(f"Vedtak om {ord_}\nDokumentdato: 01.03.2024")
        assert profil["ytelse"]["navn"]["kode"] == "OMS"
        assert profil["ytelse"]["betegnelse"] == forventet
        sett.add(profil["ytelse"]["betegnelse"])
    assert len(sett) == 3, "tre ytelser må gi tre ulike betegnelser"


def test_hver_ytelse_har_sin_egen_betegnelse():
    """Vakten mot at betegnelsen sklir tilbake til temanavnet: alle 25
    ytelsene skal ha 25 ULIKE betegnelser. Målt før fiksen ga de 25
    ytelsene bare 16 ulike verdier."""
    betegnelser = [ytelse_betegnelse(n) for n in YTELSE_TEMA]
    assert len(set(betegnelser)) == len(YTELSE_TEMA), (
        f"{len(YTELSE_TEMA)} ytelser gir bare "
        f"{len(set(betegnelser))} ulike betegnelser")

"""
Hvilke sider svaret hviler på — som metadata, ikke som en setning (R207).

§26 krever at «alle resultater skal kunne korreleres til job_id,
modellversjon og evidence metadata». De to første fantes: `jobb_id` i
jobbsvaret, og `_versjon_stempel()` gir modell-, prompt- og
terskelversjon per svar.

Det tredje gjorde det nesten. `bevisvalg.velg_sider` regner ut valgte
sider, utelatte sider, poeng per side og en begrunnelse — og så ble alt
unntatt sidetallene kastet, mens resten ble til én norsk setning:

    «Svaret er basert på side 4, 5, 9 av 10 — de øvrige ble vurdert som
     irrelevante for spørsmålet og ikke sendt til modellen (bevisvalg)»

Den setningen er riktig og nyttig for et menneske. Men en klient som vil
vite hva svaret bygget på, måtte parse prosa — og «fritekst er ikke en
kontrakt» (R132). Nå ligger det samme ved som et objekt. Setningen blir
stående; de to har hver sin leser.

TRE VEIER MÅ SVARE LIKT
`/dokument` flatt, `/dokument` med operasjoner, og `/spor`. To veier som
er uenige om hva svaret bygget på, er verre enn om ingen av dem svarte.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api as api


# ------------------------------------------------------------------ #
#  Nøkkelen finnes i kontrakten — på alle tre veiene                  #
# ------------------------------------------------------------------ #

def test_spor_skjelettet_har_bevis():
    """R118: nøkkelen finnes ALLTID, med null der den ikke gjelder."""
    import inspect
    kilde = inspect.getsource(api._spor_svar)
    assert '"bevis": None' in kilde, (
        "/spor-skjelettet mangler «bevis» — da kommer og går nøkkelen "
        "avhengig av hvilken vei som svarte, som er nøyaktig det "
        "skjelettet finnes for å hindre")


def test_operasjonsveien_slipper_bevis_gjennom():
    """Konvolutten plukker felter fra en HVITLISTE. Står ikke «bevis»
    der, blir det stille borte på operasjonsveien mens den flate veien
    har det — og da er de to uenige."""
    assert "bevis" in api._SVAR_DATAFELT


def test_openapi_beskriver_bevis():
    """Et felt som ikke står i kontrakten, finnes ikke for en klient."""
    spek = api._openapi()
    svar = ((spek.get("components") or {}).get("schemas") or {})
    tekst = str(svar)
    assert "bevis" in tekst, "«bevis» er ikke beskrevet i OpenAPI"


# ------------------------------------------------------------------ #
#  Innholdet: nok til å etterprøve valget, ikke bare lese det         #
# ------------------------------------------------------------------ #

def _sider(**tekster):
    return {int(n[1:]): t for n, t in tekster.items()}


def test_bevis_baerer_bade_valgte_utelatte_og_poeng():
    """Sidetallene alene sier HVA som ble valgt. Poengene sier HVORFOR,
    og uten dem kan et valg leses, men ikke etterprøves."""
    from delt import bevisvalg
    sider = _sider(s1="Vedtak om sykepenger " * 20,
                   s2="Faktura fra Nordbygg Entreprenoer " * 20,
                   s3="Legeerklaering diagnose ryggsmerter "
                      "for Marit Testperson " * 20)
    b = bevisvalg.velg_sider(sider, "Hvilken diagnose har Marit Testperson?")
    for felt in ("valgte", "utelatte", "poeng", "grunn", "alle"):
        assert felt in b, f"bevisvalg gir ikke «{felt}»"
    assert b["valgte"], "ingen side ble valgt på et opplagt treff"
    assert set(b["valgte"]) | set(b["utelatte"]) == set(sider), (
        "valgte + utelatte dekker ikke alle sidene — da er det umulig å "
        "se om en side ble vurdert i det hele tatt")
    # Nøklene er INT her og blir strenger først i JSON — sammenligningen
    # gjøres derfor mot sidetallene som de er i prosessen.
    assert set(b["poeng"]) == set(sider), (
        "poeng mangler for en side — da kan et utelatt valg ikke "
        "etterprøves")


def test_ingen_seleksjon_er_en_EGEN_tilstand_ikke_et_tomt_svar():
    """Skiller seg ikke ut noen side, sendes ALT — og da er begge
    listene tomme MED `alle: true`. Det er noe helt annet enn «ingen
    side var relevant», og en klient som blander de to ville trodd at
    svaret hvilte på ingenting."""
    from delt import bevisvalg
    b = bevisvalg.velg_sider(_sider(s1="kort", s2="tekst", s3="her"),
                             "Hvilken diagnose har Marit?")
    assert b["alle"] is True
    assert b["valgte"] == [] and b["utelatte"] == []
    assert "ingen side skilte seg ut" in b["grunn"]


def test_antall_sider_settes_paa_beviset():
    """«side 4, 5, 9» betyr noe helt annet av 10 enn av 500."""
    import inspect
    kilde = inspect.getsource(api.svar_paa_sporsmal)
    assert 'bevis["antall_sider"]' in kilde


# ------------------------------------------------------------------ #
#  Setningen skal IKKE forsvinne                                      #
# ------------------------------------------------------------------ #

def test_prosaadvarselen_staar_fortsatt():
    """Objektet er for maskiner. Mennesket som leser svaret i en
    nettleser skal fortsatt få vite at bare noen sider ble brukt —
    å bytte den ut med et objekt ville flyttet problemet, ikke løst det."""
    import inspect
    kilde = inspect.getsource(api.svar_paa_sporsmal)
    assert "Svaret er basert på side" in kilde, (
        "prosaadvarselen er borte — da mister mennesket beskjeden om at "
        "svaret hviler på et utvalg")


def test_bevis_er_none_naar_seleksjonen_ikke_kjorte():
    """`null` er en PÅSTAND: bevisvalg kjørte ikke (ett dokument, eller
    en deterministisk vei uten modellen). Det er noe annet enn «alle
    sider ble brukt», og de to skal ikke se like ut."""
    import inspect
    kilde = inspect.getsource(api.svar_paa_sporsmal)
    assert "bevis = None" in kilde
    assert '"bevis": None}' in kilde, (
        "de deterministiske returveiene setter ikke «bevis» — da mangler "
        "nøkkelen der, stikk i strid med R118")

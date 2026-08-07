"""Les én gang, regn én gang — og ikke del ut noe som blir mutert.

Målt på ÉN forespørsel gikk `klassifiser_datoer` TRE ganger over samme
tekst: fra `DokumentKontekst.datoer_detaljert`, en gang til inne i
`dokumentdato_av`, og en tredje gang inne i `strukturert_uttrekk`.
Konteksten het «les-en-gang, regn-en-gang», og gjorde det for sine egne
felter — men de to funksjonene den kalte, klassifiserte på nytt selv.

`lover.kapitler` parset alle linjene i lovteksten på nytt ved hvert
kall. `_lovtekst` bufret allerede LESINGEN, så dette var ren gjentatt
parsing av en tekst som ikke kan ha endret seg: målt 1,38 ms per kall,
uendret over fire kall.

Fella som gjorde dette farligere enn det ser ut: `sett_dato_roller`
muterer dict-ene PÅ STEDET, og `strukturert_uttrekk` legger datolista
RETT inn i svaret sitt («struktur.datoer»). Gjenbrukte vi den samme
lista begge steder, ville `struktur.datoer` stilltiende fått tre nye
nøkler — en kontraktsendring smuglet inn i en ytelsesfiks.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api
from delt import lover
from syntetiske_nummer import lag_fnr

DOK = ("[Side 1 av 2]\nNAV Arbeid og ytelser\nVedtak om sykepenger\n\n"
       "Dokumentdato: 04.03.2026\nOpplysninger om: Ola Nordmann\n"
       f"Fodselsnummer: {lag_fnr(0)}\nSaksnummer: 12345678\n"
       "Perioden gjelder fra 01.01.2026 til 30.06.2026.\n"
       "[Side 2 av 2]\nKlagefrist: seks uker fra 04.03.2026.\n")


@pytest.fixture
def teller(monkeypatch):
    """Teller ekte kall til klassifiser_datoer — uansett hvilken modul
    de går gjennom."""
    import delt.tekstuttrekk as tu
    tall = {"n": 0}
    ekte = tu.klassifiser_datoer

    def talt(*a, **kw):
        tall["n"] += 1
        return ekte(*a, **kw)

    monkeypatch.setattr(tu, "klassifiser_datoer", talt)
    monkeypatch.setattr(api, "klassifiser_datoer", talt)
    return tall


# ------------------------------------------------------------------ #
#  1. Regn én gang                                                     #
# ------------------------------------------------------------------ #

def test_datoene_klassifiseres_bare_en_gang_per_dokument(teller):
    """Alle tre konsumentene ber om sitt, i den rekkefølgen /dokument
    faktisk bruker dem."""
    k = api.DokumentKontekst(DOK, antall_sider=2)
    k.datoer_detaljert
    k.dokumentdato
    k.struktur
    k.profil
    assert teller["n"] == 1, (
        f"klassifiser_datoer kjørte {teller['n']} ganger på samme tekst")


def test_rekkefolgen_spiller_ingen_rolle(teller):
    """Vakten skal ikke være avhengig av at `datoer_detaljert` tilfeldigvis
    bes om først. Her spørres det motsatt vei."""
    k = api.DokumentKontekst(DOK, antall_sider=2)
    k.struktur
    k.dokumentdato
    k.datoer_detaljert
    assert teller["n"] == 1


def test_ferdige_datoer_fra_analysen_gjenbrukes_fortsatt(teller):
    """PDF-veien leverer datoene ferdig utregnet (de har sett
    PDF-metadata som ikke overlever i ren tekst). Da skal konteksten
    ikke regne dem om — heller ikke etter denne endringen."""
    import delt.tekstuttrekk as tu
    ferdige = tu.sett_dato_roller(tu.klassifiser_datoer(DOK))
    teller["n"] = 0
    k = api.DokumentKontekst(DOK, antall_sider=2,
                             ferdig={"datoer_detaljert": ferdige})
    assert k.datoer_detaljert is ferdige
    assert teller["n"] == 0


# ------------------------------------------------------------------ #
#  2. Ikke del ut noe som blir mutert                                  #
# ------------------------------------------------------------------ #

def test_strukturens_datoer_har_IKKE_fatt_rollenoklene():
    """Selve fella. `sett_dato_roller` legger til `rolle`, `type_kodet`
    og `rolle_kodet` ved mutasjon. Deler de to konsumentene de samme
    dict-ene, dukker de tre nøklene opp i `struktur.datoer` — som er
    en kontraktsendring, ikke en ytelsesgevinst."""
    k = api.DokumentKontekst(DOK, antall_sider=2)
    k.datoer_detaljert                      # muterer sin egen kopi
    for d in k.struktur["datoer"]:
        for forbudt in ("rolle", "type_kodet", "rolle_kodet"):
            assert forbudt not in d, (
                f"«{forbudt}» lekket inn i struktur.datoer — rollelista og "
                f"strukturlista deler dict-er")


def test_de_to_listene_er_ULIKE_objekter():
    k = api.DokumentKontekst(DOK, antall_sider=2)
    a = k.datoer_detaljert
    b = k.struktur["datoer"]
    assert a is not b
    assert all(x is not y for x in a for y in b)


def test_detaljerte_datoer_HAR_rollenoklene():
    """Speilet: isolasjonen skal ikke ha tatt rollene fra den lista som
    skal ha dem."""
    k = api.DokumentKontekst(DOK, antall_sider=2)
    assert k.datoer_detaljert
    for d in k.datoer_detaljert:
        assert "rolle" in d and "type_kodet" in d


# ------------------------------------------------------------------ #
#  3. Loven parses én gang                                             #
# ------------------------------------------------------------------ #

def test_kapitlene_parses_bare_en_gang_per_lov():
    lover._kapittelbuffer.clear()
    tall = {"n": 0}
    ekte = lover._lovtekst

    def talt(lov_id):
        tall["n"] += 1
        return ekte(lov_id)

    lover._lovtekst = talt
    try:
        for _ in range(5):
            lover.kapitler("ftrl-1997")
    finally:
        lover._lovtekst = ekte
    assert tall["n"] == 1, f"lovteksten ble gjennomgått {tall['n']} ganger"


def test_kapitlene_leveres_som_KOPI():
    """Uten kopien kunne én kaller som endrer kartet sitt forgifte
    bufferet for hele prosessen — og alle senere oppslag ville sett en
    lov som ikke finnes."""
    lover._kapittelbuffer.clear()
    forste = lover.kapitler("ftrl-1997")
    forste["99"] = "Oppdiktet kapittel"
    assert "99" not in lover.kapitler("ftrl-1997")


def test_bufferet_gir_samme_svar_som_uten_buffer():
    """Fart uten samme svar er ingen gevinst."""
    lover._kapittelbuffer.clear()
    kaldt = lover.kapitler("ftrl-1997")
    varmt = lover.kapitler("ftrl-1997")
    assert kaldt == varmt and len(kaldt) > 20


# ------------------------------------------------------------------ #
#  4. De valgfrie argumentene endrer ingenting for andre kallere       #
# ------------------------------------------------------------------ #

def test_funksjonene_virker_uendret_uten_de_nye_argumentene():
    """`sjekk_miljo.py` og testene kaller dem uten `datoer`. De skal
    ikke trenge å vite om denne optimaliseringen."""
    from delt.tekstuttrekk import klassifiser_datoer, strukturert_uttrekk
    uten = strukturert_uttrekk(DOK)
    med = strukturert_uttrekk(DOK, datoer=klassifiser_datoer(DOK))
    assert uten == med

    fra_teksten = api.dokumentdato_av(DOK)
    import delt.tekstuttrekk as tu
    levert = api.dokumentdato_av(
        DOK, datoer=tu.sett_dato_roller(tu.klassifiser_datoer(DOK)))
    assert fra_teksten == levert

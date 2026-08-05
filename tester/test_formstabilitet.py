"""
Formstabilitet: NØYAKTIG samme nøkler i HVERT svar (R118).

Klientene er RPA-roboter og andre systemer som sender filer én etter
én og mapper felt BLINDT: de leser
`svar["dokumentprofil"]["dokument"]["type"]["kode"]` uten å sjekke om
stien finnes. Forsvinner en nøkkel fordi verdien mangler, krasjer
roboten på dokument nummer to — og den krasjer i produksjon, på et
dokument ingen har sett.

Kontrakten er derfor: **verdi eller `null`, aldri en manglende nøkkel.**

To ting skilles:

  OBJEKTSTIER    må være identiske i alle svar. Et objekt som blir
                 `null` når innholdet mangler, tar med seg alle stiene
                 under seg — det er nøyaktig feilen denne fila fanger.

  LISTER         kan være tomme; en robot itererer da null ganger og
                 krasjer ikke. Men er lista IKKE tom, må elementet ha
                 samme nøkler hver gang.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api
from syntetiske_nummer import lag_fnr

FNR = lag_fnr(0)
ANNEN = lag_fnr(1)

# Med vilje så ulike som mulig: fullt NAV-vedtak, tomt, fremmedspråklig,
# ikke-NAV, bunke, delvis lest. Er formen lik på tvers av DISSE, er den
# lik på tvers av det meste.
DOKUMENTER = {
    "fullt NAV-vedtak": (f"""[Side 1 av 2]
NAV Arbeid og ytelser
Vedtak om sykepenger
Vedtaksdato: 28.05.2026
Saksnummer: 4417820
Journalnummer: 2026001234
Dokumentet gjelder:
Ola Nordmann
Fnr: {FNR}
Saksbehandler: Kari Hansen
Fnr: {ANNEN}
Dagsats: kr 1 234,00
Arbeidsgiver: Rema 1000 AS
Stilling: Butikkmedarbeider
Telefon: 41288903
E-post: ola@example.no
Storgata 12, 0181 OSLO
Kontonummer: 1234.56.78903
Vedtaket er fattet etter folketrygdloven § 8-2.
[Side 2 av 2]
Mottatt NAV 30.05.2026
""", 2),
    "helt tomt": ("", 1),
    "bare mellomrom": ("   \n\n   ", 1),
    "ett ord": ("noe", 1),
    "bare et tall": ("42", 1),
    "faktura, ikke NAV": ("""Faktura 12345
Forfallsdato: 01.09.2026
Beløp: kr 486,00
KID: 1002345678911
""", 1),
    "engelsk brev": ("""Dear Sir,
This is a letter about nothing in particular.
Best regards, John Smith
""", 1),
    "kvittering uten dato": ("Kvittering\nTotalt kr 99,00\nTakk", 1),
    "ren tekst uten sidemerker": ("Vedtak om dagpenger. Datert 01.03.2024.", 1),
    "bunke med to dokumenter": (f"""[Side 1 av 2]
Vedtak om dagpenger
Vedtaksdato: 01.03.2024
Fnr: {FNR}
[Side 2 av 2]
Klage på vedtak
Dokumentdato: 15.04.2024
""", 2),
    "delvis lest, 10 av 500": (
        "\n".join(f"[Side {i} av 500]\nInnhold" for i in range(1, 11)), 500),
    "bare sidemerker": ("[Side 1 av 1]", 1),
}


def _profil(navn):
    tekst, sider = DOKUMENTER[navn]
    return api.DokumentKontekst(tekst, antall_sider=sider,
                                filnavn="test.pdf").profil


def _objektstier(node, prefiks="", lister=None):
    """Stiene en robot leser direkte. Lister samles for seg."""
    ut = set()
    if lister is None:
        lister = {}
    if isinstance(node, dict):
        for nokkel in node:
            ut.add(f"{prefiks}/{nokkel}")
            ut |= _objektstier(node[nokkel], f"{prefiks}/{nokkel}", lister)
    elif isinstance(node, list) and node:
        # bare elementskjemaet — LENGDEN er data, ikke form
        lister.setdefault(prefiks, set())
        lister[prefiks] |= _objektstier(node[0], "", {})
    return ut


FASIT = "fullt NAV-vedtak"


@pytest.mark.parametrize("navn", sorted(DOKUMENTER))
def test_samme_objektnokler_uansett_innhold(navn):
    """Kjernen. Et dokument uten dato skal ha NØYAKTIG samme nøkler som
    et fullt vedtak — bare med null i verdiene.

    Feilen dette fanget: `dokument.type` var `null` når typen ikke ble
    fastslått, i stedet for `{kode: null, term: null}`. En robot som
    leste `type.kode` krasjet på hvert dokument den ikke gjenkjente.
    Samme for `dokument.alder` og `ytelse.navn`."""
    fasit = _objektstier(_profil(FASIT))
    naa = _objektstier(_profil(navn))
    mangler = sorted(fasit - naa)
    ekstra = sorted(naa - fasit)
    assert not mangler and not ekstra, (
        f"«{navn}» har et ANNET nøkkelsett enn «{FASIT}».\n"
        f"  MANGLER: {mangler}\n  EKSTRA:  {ekstra}\n"
        f"En RPA-robot som mapper blindt krasjer på dette.")


def test_listeelementene_har_fast_skjema():
    """En tom liste er greit — roboten itererer null ganger. Men er
    lista ikke tom, må elementet ha samme nøkler hver gang."""
    sett = {}
    for navn in DOKUMENTER:
        lister = {}
        _objektstier(_profil(navn), lister=lister)
        for sti, nokler in lister.items():
            if sti not in sett:
                sett[sti] = (navn, nokler)
                continue
            forrige_navn, forrige = sett[sti]
            assert forrige == nokler, (
                f"Listeelementet {sti} har ulike nøkler:\n"
                f"  «{forrige_navn}»: {sorted(forrige)}\n"
                f"  «{navn}»: {sorted(nokler)}")


def test_ingen_nestede_objekter_blir_null():
    """Direkte formulering av regelen: er et felt et objekt i ETT svar,
    skal det være et objekt i ALLE — aldri null."""
    fasit = _profil(FASIT)

    def objektstier(node, prefiks=""):
        if isinstance(node, dict):
            yield prefiks
            for k, v in node.items():
                yield from objektstier(v, f"{prefiks}/{k}")

    forventet = set(objektstier(fasit))
    for navn in DOKUMENTER:
        profil = _profil(navn)
        for sti in sorted(forventet):
            node = profil
            for ledd in [x for x in sti.split("/") if x]:
                node = node.get(ledd) if isinstance(node, dict) else None
                if node is None:
                    break
            assert node is not None or not sti, (
                f"«{navn}»: {sti} er null, men er et OBJEKT i «{FASIT}». "
                f"Bruk et objekt med null-verdier i stedet — ellers "
                f"forsvinner alle stiene under det.")


def test_hvert_dokument_gir_samme_antall_toppseksjoner():
    """Grovsjekken en operatør kan gjøre med øyet."""
    antall = {navn: len(_profil(navn)) for navn in DOKUMENTER}
    assert len(set(antall.values())) == 1, f"ulikt antall seksjoner: {antall}"

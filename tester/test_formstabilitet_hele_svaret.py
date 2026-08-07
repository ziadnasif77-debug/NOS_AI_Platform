"""
Formstabilitet for HELE svaret — ikke bare dokumentprofilen.

`test_formstabilitet.py` vokter `DokumentKontekst(...).profil`. Den
regelen er riktig og den holder: inne i `dokumentprofil` er nøkkelsettet
identisk uansett innhold. Problemet er rekkevidden. Kontraktsrevisjonen
målte at ALLE de kritiske bruddene lå UTENFOR det gjerdet:

  * `felter.dokumentdato` mister `type_kodet` og `rolle_kodet` når ingen
    dato finnes — 12 nøkler blir 10, og de to er BORTE, ikke null.
  * `felter.datoer_detaljert[]` har fire ulike elementformer. Den gamle
    vakten så bare `node[0]`, og den avvikende oppføringen legges SIST.
  * `felter.felter` er et åpent kart: 12 nøkler på et fullt vedtak, `{}`
    på et tomt dokument.
  * Fem toppnivåobjekter er `null` når operasjonen ikke ble bedt om — og
    et objekt som blir null tar med seg alle stiene under seg.

Vakten drar derfor gjerdet ut til hele svarkroppen, for hver rute den
kan drive, og sammenligner ALLE listeelementer i stedet for det første.

HVA VAKTEN MÅLER — OG HVA DEN IKKE MÅLER
Bryterne holdes FASTE og innholdet varieres. Det er R118s kjerne: en
robot sender de samme feltene hver gang og får dokumenter den ikke har
sett. Formen skal da ikke bevege seg.

Den måler altså IKKE formendring drevet av BRYTERNE — at `svar`,
`skjema`, `korriger` og `koordinater` er `null` når operasjonen ikke ble
bedt om, og et objekt når den ble det. Det er et ekte, målt brudd, men
det hører til et eget punkt (faste skjeletter med null-verdier), og å
blande det inn her ville gjort vakten uklar om hva den lover.

GJELDSLISTA
Bruddene over finnes fortsatt. De rettes punktvis, og hvert punkt har
sin egen plass i planen. Ville vi ventet med vakten til alt var rettet,
ville den kommet etter feilene den skal forhindre. I stedet står
bruddene i `KJENTE_BRUDD` med begrunnelse: suiten er grønn, gjelda er
synlig, og et NYTT brudd blir rødt med en gang.

Hver retting fjerner en linje herfra — og
`test_hver_gjeldslinje_er_fortsatt_nodvendig` prøver hver linje ved å
FJERNE den og se om noe blir rødt. Blir den grønn uten linja, er
punktet rettet og linja skal bort. Et unntak som ikke lenger trengs er
verre enn ingen: det slår av vakten for en sti som er blitt riktig.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api
import syntetiske_nummer


# ------------------------------------------------------------------ #
#  Dokumenter som spenner fra «alt fylt» til «ingenting»              #
# ------------------------------------------------------------------ #

RIKT = """[Side 1 av 2]
NAV Arbeid og ytelser
Vedtak om sykepenger

Opplysninger om: Ola Nordmann
Fodselsnummer: {FNR}
Telefon: 76118610
E-post: ola.nordmann@example.no
Storgata 12 B, 8450 STOKMARKNES

Saksnummer: 4417820
Journalnummer: 2026001234
Dokumentdato: 04.03.2026
Gjelder perioden 01.02.2026 - 28.02.2026

Arbeidsgiver: Nordlys Transport AS
Organisasjonsnummer: 923609016
Stilling: Sjafor

Utbetales til kontonummer {KONTO}
KID: 1234567897
Belop: 38 250,50 kr

Vedtaket er fattet etter folketrygdloven § 8-2.

[Side 2 av 2]
Du har tidligere mottatt arbeidsavklaringspenger.
"""

FATTIG = "[Side 1 av 1]\nEt kort notat uten noe som helst.\n"

FLERSIDIG = """[Side 1 av 2]
Vedtak om dagpenger
Dokumentdato: 10.01.2026
Fodselsnummer: {FNR}

[Side 2 av 2]
Krav om tilbakebetaling
Dokumentdato: 22.09.2025
"""

BARE_MERKER = "[Side 1 av 1]"

# Identifikatorene genereres — de skal være mod11-gyldige, men aldri
# stå som ellevesifrede literaler i kildekoden (portabilitetsvakten
# håndhever det, og den tok denne fila da den ble skrevet).
_FNR = syntetiske_nummer.lag_fnr()
_KONTO = syntetiske_nummer.lag_kontonummer()


def _fyll(mal):
    return mal.replace("{FNR}", _FNR).replace("{KONTO}", _KONTO)


DOKUMENTER = {
    "rikt": _fyll(RIKT),
    "fattig": _fyll(FATTIG),
    "flersidig": _fyll(FLERSIDIG),
    "bare sidemerker": _fyll(BARE_MERKER),
}
FASIT = "rikt"


# ------------------------------------------------------------------ #
#  Fake-handler: låner de EKTE metodene, fanger _svar                 #
# ------------------------------------------------------------------ #

def _fake():
    """Samme mønster som test_operasjoner_http: den ekte rutekoden,
    uten socket. Klassene slås opp ved kalltid så testen tåler at andre
    moduler laster dokument_api på nytt."""
    H = api.Handler

    class Fake:
        MAKS_OPERASJONER = H.MAKS_OPERASJONER
        SLADD_ADVARSEL = getattr(H, "SLADD_ADVARSEL", "")
        _les_dokument = H._les_dokument
        _dokument_samlet = H._dokument_samlet
        _dokument_operasjoner = H._dokument_operasjoner
        _sladd = H._sladd
        _forhandssjekk = H._forhandssjekk

        def __init__(self):
            self.svar = None

        def _svar(self, kode, data, hoder=None):
            self.svar = (kode, data)
            return (kode, data)

    return Fake()


def _dokument(tekst):
    f = _fake()
    f._dokument_samlet("prove.txt", "tekst", tekst, None,
                       {"felter": "ja", "struktur": "ja", "opphav": "alle",
                        "datoer_detaljert": "ja"}, True)
    return f.svar[1]


def _operasjoner(tekst):
    f = _fake()
    f._dokument_operasjoner("prove.txt", "tekst", tekst, None, True,
                            '[{"type":"felter"},{"type":"struktur"}]', {})
    return f.svar[1]


def _sladd(tekst):
    f = _fake()
    f._sladd("prove.txt", "tekst", tekst, None, {})
    return f.svar[1]


def _forhandssjekk(tekst):
    f = _fake()
    f._forhandssjekk("prove.txt", "tekst", tekst, {})
    return f.svar[1]


RUTER = {
    "/dokument": _dokument,
    "/dokument/operasjoner": _operasjoner,
    "/sladd": _sladd,
    "/forhandssjekk": _forhandssjekk,
}


# ------------------------------------------------------------------ #
#  Gjeldslista — kjente brudd, med hvor de hører hjemme                #
# ------------------------------------------------------------------ #

# KART MED DATANØKLER — ikke brudd, og skal aldri bli det.
#
# Et JSON-objekt kan brukes på to måter: som en RECORD med faste felt
# (der R118 gjelder), eller som et KART der nøklene ER data. `opphav` er
# det siste: nøklene er RFC 6901-pekere inn i svaret, så de følger
# nødvendigvis hva som ble funnet. En klient itererer over et kart — den
# slår ikke opp en fast sti i det — og revisjonen slo fast at nettopp
# denne formen er den riktige for RPA-klienter.
#
# Skillet må stå i vakten selv. Uten det drukner de ekte funnene i 70
# «manglende» opphav-pekere, og en vakt man ikke gidder å lese er ingen
# vakt. Det som IKKE hører hjemme her er `felter.felter` og
# `kvalitet.ocr_motorer`: de utgir seg for å være records.
KART_MED_DATANOEKLER = {
    ("/dokument", "/opphav"):
        "Nøklene er JSON-pekere inn i svaret — de ER data. Klienten "
        "itererer, den slår ikke opp en fast sti.",
    ("/dokument/operasjoner", "/opphav"): "Samme kart som på /dokument.",
}

# Stier vakten SKAL se bort fra INNTIL de er rettet. Nøkkelen er
# (rute, sti-prefiks); verdien er hvorfor og hva som retter det.
# Et prefiks dekker alt under seg.
KJENTE_BRUDD = {
    ("/dokument", "/felter/felter"):
        "Åpent kart: nøkkelsettet følger dataene. Egen post i planen — "
        "hvert faktum skal få et typet hjem i profilen i stedet.",
    ("/dokument", "/felter/dokumentdato/type_kodet"):
        "Mangler helt når ingen dato finnes (tekstuttrekk.py:633). "
        "Rettes ved å emittere {kode: null, term: null} i tom-grenen.",
    ("/dokument", "/felter/dokumentdato/rolle_kodet"):
        "Samme brudd som type_kodet, samme sted.",
    ("/dokument", "/felter/datoer_detaljert"):
        "Elementet som utledes fra et fødselsnummer mangler "
        "«aar_antatt», som alle andre oppføringer har "
        "(tekstuttrekk.py:969). Det legges SIST, så den gamle vakten "
        "kunne aldri se det. Rettes ved å sette aar_antatt: False også "
        "i den grenen.",
    ("/dokument", "/felter/dokumentdato/periode"):
        "Nestet objekt som blir null i tom-grenen — tar med seg alle "
        "stiene under seg.",
    ("/dokument", "/struktur"):
        "Hele blokka er null når struktur ikke er bedt om, og bruker «» "
        "der profilen bruker null. Skal fjernes som parallellblokk.",
    ("/dokument/operasjoner", "/resultater"):
        "Elementformen varierer med operasjonstype og utfall (målt: 7 "
        "former). Skal bli én form med null der noe ikke gjelder.",
}


def _under(sti, prefiks):
    return sti == prefiks or sti.startswith(prefiks + "/")


def _unntatt(rute, sti, gjeld=None):
    """Er stien unntatt — enten som kart med datanøkler (permanent)
    eller som kjent brudd (midlertidig)?"""
    gjeld = KJENTE_BRUDD if gjeld is None else gjeld
    for (r, prefiks) in list(KART_MED_DATANOEKLER) + list(gjeld):
        if r == rute and _under(sti, prefiks):
            return True
    return False


# ------------------------------------------------------------------ #
#  Stiuttrekk — ALLE listeelementer, ikke bare det første              #
# ------------------------------------------------------------------ #

def _objektstier(node, prefiks="", lister=None):
    """Stiene en robot leser direkte, og elementskjemaet for hver liste.

    Forskjellen fra den gamle vakten er `for element in node` i stedet
    for `node[0]`. Den avvikende oppføringen i `datoer_detaljert` legges
    SIST, så et førsteelement-søk kunne aldri sett den."""
    ut = set()
    if lister is None:
        lister = {}
    if isinstance(node, dict):
        for nokkel in node:
            ut.add(f"{prefiks}/{nokkel}")
            ut |= _objektstier(node[nokkel], f"{prefiks}/{nokkel}", lister)
    elif isinstance(node, list):
        for element in node:
            if isinstance(element, dict):
                lister.setdefault(prefiks, []).append(
                    frozenset(_objektstier(element, "", {})))
    return ut


# ------------------------------------------------------------------ #
#  Selve sjekkene — som funksjoner, så gjeldslista kan prøves mot dem  #
# ------------------------------------------------------------------ #

def _svarene(rute):
    lag = RUTER[rute]
    return {navn: lag(tekst) for navn, tekst in DOKUMENTER.items()}


def _problem_nokkelsett(rute, gjeld=None):
    """Har alle dokumenter samme objektnøkler?"""
    svar = _svarene(rute)
    fasit = {s for s in _objektstier(svar[FASIT])
             if not _unntatt(rute, s, gjeld)}
    problemer = []
    for navn, kropp in svar.items():
        naa = {s for s in _objektstier(kropp)
               if not _unntatt(rute, s, gjeld)}
        mangler, ekstra = sorted(fasit - naa), sorted(naa - fasit)
        if mangler or ekstra:
            problemer.append(
                f"«{navn}» har et ANNET nøkkelsett enn «{FASIT}»\n"
                f"    MANGLER: {mangler[:8]}{' …' if len(mangler) > 8 else ''}\n"
                f"    EKSTRA:  {ekstra[:8]}{' …' if len(ekstra) > 8 else ''}")
    return problemer


def _problem_lister(rute, gjeld=None):
    """Har alle elementer i hver liste samme nøkler — i samme svar OG
    mellom dokumenter?"""
    problemer, sett = [], {}
    for navn, kropp in _svarene(rute).items():
        lister = {}
        _objektstier(kropp, lister=lister)
        for sti, former in lister.items():
            if _unntatt(rute, sti, gjeld):
                continue
            ulike = set(former)
            if len(ulike) > 1:
                problemer.append(
                    f"«{navn}»: elementene i {sti} har ULIKE nøkkelsett "
                    f"i SAMME svar:\n"
                    + "\n".join(f"    {sorted(f)}" for f in ulike))
                continue
            form = next(iter(ulike))
            if sti in sett and sett[sti][1] != form:
                forrige, forrige_form = sett[sti]
                problemer.append(
                    f"{sti} har ulikt elementskjema mellom dokumenter:\n"
                    f"    «{forrige}»: {sorted(forrige_form)}\n"
                    f"    «{navn}»: {sorted(form)}")
            sett.setdefault(sti, (navn, form))
    return problemer


def _problem_nullobjekt(rute, gjeld=None):
    """Er et felt et objekt i ETT svar, må det være objekt i ALLE."""
    svar = _svarene(rute)

    def objektstier(node, prefiks=""):
        ut = set()
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, dict):
                    ut.add(f"{prefiks}/{k}")
                ut |= objektstier(v, f"{prefiks}/{k}")
        return ut

    objekter = {s for s in objektstier(svar[FASIT])
                if not _unntatt(rute, s, gjeld)}
    problemer = []
    for navn, kropp in svar.items():
        for sti in sorted(objekter):
            node = kropp
            for del_ in sti.strip("/").split("/"):
                node = node.get(del_) if isinstance(node, dict) else None
                if node is None:
                    break
            if node is None:
                problemer.append(
                    f"«{navn}»: {sti} er null, men er et objekt i "
                    f"«{FASIT}» — null tar med seg alle stiene under seg")
    return problemer


SJEKKER = (_problem_nokkelsett, _problem_lister, _problem_nullobjekt)


# ------------------------------------------------------------------ #
#  Testene                                                             #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("rute", sorted(RUTER))
def test_samme_objektnokler_i_hele_svaret(rute):
    """En robot leser `svar["felter"]["dokumentdato"]["type_kodet"]`
    uten å sjekke om stien finnes. Forsvinner en nøkkel fordi verdien
    mangler, krasjer den på dokument nummer to."""
    problemer = _problem_nokkelsett(rute)
    assert not problemer, f"{rute}:\n  " + "\n  ".join(problemer) + (
        "\nEr dette et kjent, akseptert brudd, hører det hjemme i "
        "KJENTE_BRUDD med en begrunnelse — ikke i stillhet.")


@pytest.mark.parametrize("rute", sorted(RUTER))
def test_alle_listeelementer_har_samme_skjema(rute):
    """Den gamle vakten så bare `node[0]`. Elementet som avviker i
    `datoer_detaljert` legges SIST, så den kunne aldri se det."""
    problemer = _problem_lister(rute)
    assert not problemer, f"{rute}:\n  " + "\n  ".join(problemer)


@pytest.mark.parametrize("rute", sorted(RUTER))
def test_ingen_nestede_objekter_blir_null(rute):
    """Er et felt et objekt i ETT svar, skal det være objekt i ALLE."""
    problemer = _problem_nullobjekt(rute)
    assert not problemer, f"{rute}:\n  " + "\n  ".join(problemer)


# ------------------------------------------------------------------ #
#  Gjeldslista skal krympe, ikke råtne                                 #
# ------------------------------------------------------------------ #

def test_hver_gjeldslinje_er_fortsatt_nodvendig():
    """Prøver hver linje ved å FJERNE den og se om noe blir rødt.

    En unntakslinje som ikke lenger trengs er verre enn ingen: den slår
    av vakten for en sti som er blitt riktig, og skjuler at et nytt
    brudd dukker opp der senere. Blir denne rød, er et punkt rettet —
    fjern linja, og vakten dekker stien igjen."""
    unodvendige = []
    for nokkel in KJENTE_BRUDD:
        rute, prefiks = nokkel
        if rute not in RUTER:
            unodvendige.append(f"{rute}{prefiks} — ruten drives ikke her")
            continue
        uten = {k: v for k, v in KJENTE_BRUDD.items() if k != nokkel}
        if not any(sjekk(rute, uten) for sjekk in SJEKKER):
            unodvendige.append(f"{rute}{prefiks}")
    assert not unodvendige, (
        "Disse linjene i KJENTE_BRUDD trengs ikke lenger — stien er "
        f"blitt stabil: {unodvendige}\nFjern dem, ellers vokter "
        "ingenting der.")


def test_gjeldslista_har_begrunnelse():
    """Et unntak uten grunn er et unntak ingen tør fjerne."""
    uten = [f"{r}{p}" for (r, p), grunn in
            list(KJENTE_BRUDD.items()) + list(KART_MED_DATANOEKLER.items())
            if not grunn or len(grunn) < 20]
    assert not uten, f"Unntak uten begrunnelse: {uten}"


def test_vakten_faktisk_fanger_et_innfort_brudd():
    """Speilet. En vakt som aldri blir rød er en påstand.

    Vi fjerner ett unntak vi VET dekker et ekte brudd, og krever at
    minst én sjekk melder fra."""
    nokkel = ("/dokument", "/felter/dokumentdato/type_kodet")
    assert nokkel in KJENTE_BRUDD, "prøven peker på feil linje"
    uten = {k: v for k, v in KJENTE_BRUDD.items() if k != nokkel}
    assert any(sjekk("/dokument", uten) for sjekk in SJEKKER), (
        "Vakten fanget ikke det manglende «type_kodet» — da vokter den "
        "ingenting.")

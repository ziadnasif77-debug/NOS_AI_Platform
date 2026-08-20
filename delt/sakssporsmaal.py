"""
Spørsmål om SAKEN, ikke om ett dokument (R250).

`POST /spor` svarer på spørsmål om ett dokument. Spør man i stedet «ble
vedtaket endret?» eller «hva manglet da kravet kom?», ligger svaret
spredt over flere filer — og §15 i kravspesifikasjonen sier hvorfor det
er vanskelig: man skal ikke svare fra det FØRSTE dokumentet som
inneholder ord som ligner spørsmålet.

TO VEIER, OG KODEN FÅR FØRSTE ORD
  1. KODEN SVARER når spørsmålet gjelder noe som allerede er BEVIST —
     hvem saken gjelder, hva som ble bestemt til slutt, om det ble
     klaget, hva som manglet, om noe motsier seg selv. Alt dette står
     alt i sakssammendraget (R249), utledet av mod11, datomodellen og
     forventningstabellen. Samme prinsipp som `bunkesporsmaal` (R229):
     modellen svarte feil på ALLE fire bunkespørsmålene den fikk, fordi
     den leser og ikke holder regnskap.
  2. MODELLEN SVARER på resten — men bare over dokumenter KODEN har
     valgt ut, og bare så mange som får plass. Kontekstvinduet er 3008
     tokens til prompt, dokument og spørsmål TIL SAMMEN; tolv dokumenter
     får aldri plass, uansett hvor god prompten er.

UTVALGET ER DET SOM GJØR SVARET ETTERRETTELIG
`bevisvalg` scorer sider innenfor ett dokument. Her scores DOKUMENTER,
med den samme ordmatchingen — og med et påslag for dokumenttypen
spørsmålet nevner. Spør noen om «klagevedtaket», skal klagevedtaket
vinne over en søknad som tilfeldigvis bruker de samme ordene.

Svaret bærer alltid HVILKE dokumenter det er bygget på, og hvilke som
ble utelatt. Et svar uten kilder er en påstand; et svar med kilder er et
spor et menneske kan gå etter.

DET SOM IKKE HAR TEKST, SIES DET OM
Saksmappa lagrer med vilje ikke dokumentteksten (R245) — den er den
tyngste persondataen systemet har. Et dokument kan derfor bare besvares
fra hvis teksten er med i kallet, eller ligger i en jobb det peker på.
De øvrige listes i `uten_tekst`. En sak besvart fra fire av ni
dokumenter er et annet svar enn en besvart fra ni, og forskjellen skal
ikke måtte gjettes (R24).
"""
from delt import bevisvalg
from delt.dokumentruting import SPORSMAALSORD
import re

# Hvor mange dokumenter modellen får se. Ikke et tall vi liker, men et
# tak: hvert dokument koster kontekst, og kontekst er 3008 tokens totalt.
MAKS_DOKUMENTER = 3

# Påslag når spørsmålet nevner dokumenttypen ved navn. Vekten er høy med
# vilje: «hva står i klagevedtaket?» skal treffe klagevedtaket, ikke det
# dokumentet som tilfeldigvis gjentar ordene flest ganger.
TYPETREFF_VEKT = 10.0


def _kode(dok: dict) -> str:
    type_ = (dok or {}).get("type")
    if isinstance(type_, dict):
        return type_.get("kode") or ""
    return type_ or ""


def _navn(dok: dict) -> str:
    return str((dok or {}).get("filnavn")
               or (dok or {}).get("tittel") or "dokument uten navn")


# ------------------------------------------------------------------ #
#  1) Det koden kan svare på selv                                     #
# ------------------------------------------------------------------ #
# Mønstrene er trange. Treffer ingen, går spørsmålet videre til
# modellen — en feilaktig deterministisk «treffer» er verre enn ingen,
# fordi den ser autoritativ ut.

_UTFALL = re.compile(
    r"(?i)\b(hva ble (det|utfallet|resultatet)|hvordan (endte|gikk) "
    r"(det|saken)|siste vedtak|endelig (vedtak|avgj[øo]relse)|"
    r"til slutt)\b")
_PART = re.compile(
    r"(?i)\b(hvem (gjelder|handler|er parten)|hvilken person|"
    r"hvem er saken om)\b")
_KLAGE = re.compile(r"(?i)\b(ble det klaget|er det (en )?klage|"
                    r"har (bruker|han|hun|parten) klaget)\b")
_MANGLER = re.compile(r"(?i)\b(hva mangl\w+|hvilke dokumenter mangl\w+|"
                      r"er noe ufullstendig)\b")
_MOTSIGELSE = re.compile(r"(?i)\b(motsier|motsigelse\w*|"
                         r"stemmer (ikke|alt)|er det (noe )?feil)\b")
_STATUS = re.compile(r"(?i)\b(hvor st[åa]r saken|status(en)? (i|p[åa]) "
                     r"saken|hva er status)\b")


def _kodesvar(sporsmal: str, sammendrag: dict):
    """(svar, kilder) fra sakssammendraget — eller None.

    Ingen av disse er en tolkning: de leser et felt som allerede er
    utledet av bevis. Kan feltet ikke fastslås, SIES det — «vet ikke» er
    et gyldig svar, og et bedre et enn en gjetning som ser sikker ut."""
    if not sammendrag:
        return None
    sp = sporsmal or ""

    if _UTFALL.search(sp):
        siste = sammendrag.get("siste_avgjorelse")
        status = sammendrag.get("status") or {}
        if not siste:
            return ("Ingen av dokumentene i saken avgjør noe. "
                    f"{status.get('begrunnelse', '')}".strip(), [])
        term = ((siste.get("type") or {}).get("term")
                if isinstance(siste.get("type"), dict) else None)
        return (f"{term or 'Avgjørelsen'} datert {siste['dato']} er den "
                f"som gjelder. Status: {status.get('term')} — "
                f"{status.get('begrunnelse')}", [siste.get("dokument")])

    if _PART.search(sp):
        part = sammendrag.get("part") or {}
        if part.get("fnr"):
            return (f"Saken gjelder personen med fødselsnummer "
                    f"{part['fnr']}. {part.get('grunnlag', '')}".strip(), [])
        return (f"Hvem saken gjelder kan ikke fastslås. "
                f"{part.get('grunnlag', '')}".strip(), [])

    if _KLAGE.search(sp):
        if sammendrag.get("klaget"):
            # Matcher KODEN, ikke termen: «Klagevedtak» inneholder
            # «Klage», og et delstrengsøk gjorde klagevedtakets dato til
            # en klagedato i svaret (målt live).
            klager = [h for h in (sammendrag.get("forlop") or [])
                      if h.get("type") == "klage"]
            naar = ", ".join(sorted({h["dato"] for h in klager}))
            return (f"Ja, det er klaget i saken ({naar}).",
                    [h["dokument"] for h in klager])
        return ("Nei, ingen klage finnes blant dokumentene i saken.", [])

    if _MANGLER.search(sp):
        mangler = sammendrag.get("mangler") or []
        if not mangler:
            return ("Ingen av dokumentene mangler noen av de feltene som "
                    "er MÅLT for typen sin. Det er ikke det samme som at "
                    "saken er komplett — bare målte felter kan mangle.", [])
        deler = [f"{m['dokument']} mangler {', '.join(m['mangler'])}"
                 for m in mangler]
        return ("; ".join(deler) + ".", [m["dokument"] for m in mangler])

    if _MOTSIGELSE.search(sp):
        antall = sammendrag.get("antall_motsigelser") or 0
        if not antall:
            return ("Ingen av de motsigelsene systemet kan bevise ble "
                    "funnet. Se «motsigelser.sjekket» for hva som "
                    "faktisk ble undersøkt.", [])
        return (f"Ja — {antall} motsigelse(r) ble funnet. Se "
                f"«motsigelser» for hver enkelt med begrunnelse.", [])

    if _STATUS.search(sp):
        status = sammendrag.get("status") or {}
        return (f"{status.get('term')} — {status.get('begrunnelse')}", [])
    return None


# ------------------------------------------------------------------ #
#  2) Utvalget når modellen skal svare                                #
# ------------------------------------------------------------------ #

def _typer_i_sporsmal(sporsmal: str) -> set:
    lav = (sporsmal or "").lower()
    return {t for t, monster in SPORSMAALSORD.items()
            if re.search(monster, lav)}


def velg_dokumenter(dokumenter: list, sporsmal: str,
                    maks: int = MAKS_DOKUMENTER) -> dict:
    """{valgte, utelatte, poeng} — hvilke dokumenter spørsmålet gjelder.

    Scoringen er `bevisvalg` sin, brukt på dokumenttekst i stedet for
    sider, pluss et kraftig påslag når spørsmålet NEVNER dokumenttypen.
    Uten påslaget vant det dokumentet som gjentok ordene flest ganger —
    og en søknad nevner «vedtak» den også."""
    nevnte = _typer_i_sporsmal(sporsmal)
    # Nøkkelordene regnes ÉN gang, som i `bevisvalg.velg_sider` — ikke
    # per dokument. Samme funksjon, samme stoppord, samme bøyningsmatch.
    nokkelord = bevisvalg._nokkelord(sporsmal)
    scoret = []
    for dok in dokumenter:
        tekst = dok.get("tekst") or ""
        poeng = (bevisvalg.poeng_for_side(tekst, nokkelord, sporsmal)
                 if tekst else 0.0)
        if _kode(dok) in nevnte:
            poeng += TYPETREFF_VEKT
        scoret.append((poeng, _navn(dok), dok))
    # Sortert på poeng, så navn: to like dokumenter skal ikke bytte
    # plass mellom to kall (R6).
    scoret.sort(key=lambda t: (-t[0], t[1]))
    valgte = [t for t in scoret if t[0] > 0][:maks]
    if not valgte:
        # Ingenting traff. Da er de ELDSTE dokumentene et ærligere valg
        # enn ingen: saken begynner der, og svaret sier uansett hvilke
        # det er bygget på.
        valgte = sorted(scoret, key=lambda t: t[1])[:maks]
    valgt_navn = {t[1] for t in valgte}
    return {
        "valgte": [t[2] for t in valgte],
        "utelatte": [t[1] for t in scoret if t[1] not in valgt_navn],
        "poeng": {t[1]: round(t[0], 2) for t in scoret},
    }


def bygg_utdrag(valgte: list) -> str:
    """Dokumentene satt sammen for modellen, hvert med sitt navn.

    Navnet står FORAN teksten så modellen kan vise til det, og så et
    menneske kan finne igjen kilden. Uten det ville svaret vært en
    påstand uten adresse."""
    deler = []
    for dok in valgte:
        deler.append(f"[Dokument: {_navn(dok)}]\n"
                     f"{(dok.get('tekst') or '').strip()}")
    return "\n\n".join(deler)

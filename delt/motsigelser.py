"""
Motsigelser MELLOM dokumenter i samme sak (R243).

Systemet hadde én motsigelsessjekk fra før, og den gikk på tvers av
KILDER i ett svar: `_uenighet_med_modellen` sammenligner det modellen
fylte ut med det uttrekket beviste, på tre felter. Ingenting sammenlignet
dokument mot dokument — og det er der en saksmappe motsier seg selv.

HVA SOM MELDES, OG HVA SOM IKKE GJØR DET
Bare det kode kan BEVISE. To slag:

  1. TO PERSONER I SAMME SAK. Sakens dokumenter bærer mer enn ett
     mod11-gyldig fødselsnummer. Enten gjelder saken flere parter, eller
     så er noe feilarkivert — begge deler må et menneske se på, og
     ingen av dem skal oppdages ved at svaret på «hvem gjelder saken?»
     tilfeldigvis ble hentet fra riktig side.

  2. UMULIG REKKEFØLGE. Et klagevedtak datert før klagen det svarer på
     kan ikke stemme: man avgjør ikke en klage som ikke finnes. Bare
     par der rekkefølgen er logisk umulig står i tabellen — ikke par
     som bare er uvanlige. En vakt som roper på det uvanlige blir slått
     av (R180).

DET SOM IKKE STÅR HER, ER IKKE FRIKJENT
Tom liste betyr «vi fant ingen av de motsigelsene vi kan bevise», ikke
«saken henger sammen». Derfor bærer svaret `sjekket` — hvilke sjekker som
faktisk ble kjørt — så et tomt funn aldri kan leses som en garanti det
ikke er (R128).

ULIKE BELØP MELDES IKKE
Det var fristende: to dokumenter i samme sak med ulik dagsats ser ut som
en motsigelse. Men et vedtak og et omgjøringsvedtak SKAL ha ulike beløp,
og en tabell med månedsbeløp har mange. Uten et målt korpus å skille på,
ville regelen ropt på friske saker. Den hører hjemme her når vi har
tallene, ikke før.
"""
from delt.sak import PERSONNOKKEL, _sakstype_av, _verdi, hendelsesdato

# Alvorsgrader — samme ord som resten av huset bruker om funn.
ALVOR_HOY = "hoy"

# Par der rekkefølgen er LOGISK UMULIG, ikke bare uvanlig:
# (må komme først, kan ikke komme før, forklaring).
UMULIG_REKKEFOLGE = (
    ("klage", "klagevedtak",
     "et klagevedtak avgjør en klage, og kan ikke være eldre enn den"),
    ("soknad", "vedtak",
     "et vedtak svarer på en søknad, og kan ikke være eldre enn den"),
    ("dokumentasjonskrav", "purring",
     "en purring følger opp et dokumentasjonskrav, og kan ikke være "
     "eldre enn det"),
)

# Navnene på sjekkene som kjøres — rapporteres alltid, se modulinnledningen.
SJEKKER = ("flere_personer", "umulig_rekkefolge")


def _dokumentnavn(dok: dict) -> str:
    return str((dok or {}).get("tittel")
               or (dok or {}).get("filnavn") or "dokument uten tittel")


def _tidligste(dokumenter: list, typekode: str):
    """(dato, dokument) for det ELDSTE dokumentet av typen — eller None.

    Eldste og ikke nyeste med vilje: finnes det tre klager, er det den
    første som avgjør om et klagevedtak kan ha kommet før noen klage i
    det hele tatt.

    Datoen hentes gjennom `sak.hendelsesdato`, samme kilde som
    tidslinjen bruker. En søknad bærer ofte bare «Mottatt», og spurte vi
    bare etter dokumentets egen dato, ville sjekken «vedtak før søknad»
    aldri slått ut på nettopp de søknadene det gjelder."""
    treff = []
    for d in dokumenter:
        if _sakstype_av(d) != typekode:
            continue
        dato, _kilde = hendelsesdato(d)
        if dato:
            treff.append((dato, _dokumentnavn(d), d))
    if not treff:
        return None
    treff.sort(key=lambda t: (t[0], t[1]))
    return treff[0][0], treff[0][2]


def _flere_personer(sak: dict) -> list:
    """Bærer sakens dokumenter mer enn ett fødselsnummer?"""
    per_fnr = {}
    for dok in sak.get("dokumenter") or []:
        fnr = _verdi(dok, PERSONNOKKEL)
        if fnr:
            per_fnr.setdefault(fnr, []).append(_dokumentnavn(dok))
    if len(per_fnr) < 2:
        return []
    # Sortert, så samme sak alltid gir samme rapport (R6). Fødselsnumrene
    # SELV står ikke i forklaringen — den skal kunne logges.
    deler = [f"{len(per_fnr[f])} dokument(er)" for f in sorted(per_fnr)]
    return [{
        "type": "flere_personer",
        "alvor": ALVOR_HOY,
        "forklaring": (
            f"Saken bærer {len(per_fnr)} ulike fødselsnummer "
            f"({', '.join(deler)}). Enten gjelder saken flere parter, "
            "eller så er noe feilarkivert — begge deler må vurderes av "
            "et menneske."),
        "dokumenter": sorted(n for navn in per_fnr.values() for n in navn),
    }]


def _umulig_rekkefolge(sak: dict) -> list:
    dokumenter = [d for d in (sak.get("dokumenter") or [])
                  if isinstance(d, dict)]
    funn = []
    for forst, senere, hvorfor in UMULIG_REKKEFOLGE:
        a = _tidligste(dokumenter, forst)
        b = _tidligste(dokumenter, senere)
        if not a or not b:
            continue          # begge må finnes for at rekkefølgen betyr noe
        if b[0] >= a[0]:
            continue          # rekkefølgen holder
        funn.append({
            "type": "umulig_rekkefolge",
            "alvor": ALVOR_HOY,
            "forklaring": (
                f"«{_dokumentnavn(b[1])}» er datert {b[0]}, før "
                f"«{_dokumentnavn(a[1])}» datert {a[0]} — {hvorfor}."),
            "dokumenter": sorted({_dokumentnavn(a[1]), _dokumentnavn(b[1])}),
        })
    return funn


def finn_motsigelser(sak: dict) -> dict:
    """{funn, sjekket} for ÉN sak.

    `sjekket` er alltid med, også når `funn` er tomt: uten den kunne et
    tomt resultat leses som «saken henger sammen», og det er en påstand
    denne modulen ikke kan gjøre (R128)."""
    sak = sak if isinstance(sak, dict) else {}
    funn = _flere_personer(sak) + _umulig_rekkefolge(sak)
    funn.sort(key=lambda f: (f["type"], f["forklaring"]))
    return {"funn": funn, "sjekket": list(SJEKKER)}

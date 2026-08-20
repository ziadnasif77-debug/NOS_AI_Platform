"""
Motsigelser MELLOM dokumenter i samme sak (R243).

Systemet hadde én motsigelsessjekk fra før, og den gikk på tvers av
KILDER i ett svar: `_uenighet_med_modellen` sammenligner det modellen
fylte ut med det uttrekket beviste, på tre felter. Ingenting sammenlignet
dokument mot dokument — og det er der en saksmappe motsier seg selv.

HVA SOM MELDES, OG HVA SOM IKKE GJØR DET
Bare det kode kan BEVISE. Tre slag:

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

ULIKE BELØP — OG HVORFOR REGELEN ER SÅ SMAL (R248)
Det var fristende å melde ethvert avvikende beløp. Men et vedtak og et
omgjøringsvedtak SKAL ha ulike beløp: klagen førte fram, og satsen ble
endret. En regel som bare ser «to ulike tall» ville ropt på den friskeste
saken i arkivet.

Skillet som holder, er om det ene kan gå FORAN det andre. Ulike datoer
er en HISTORIE — først dette, så det. Samme dato er to påstander om
samme øyeblikk, og da kan begge ikke stemme. Derfor sammenlignes bare
dokumenter datert samme dag, bare innenfor samme MERKEDE felt, og aldri
på tvers av felt: dagsats og månedsbeløp er ulike med matematisk
nødvendighet.

Regelen ble MÅLT før den ble kodet, mot `tester/korpus/belopsvarianter.json`
— seks legitime saker skrevet for å falsifisere den (omgjøring, ny
årssats, ulike felt, beregningstabell, samme verdi ulikt skrevet,
manglende dato) og to ekte motsigelser. Kjøres med
`skript/kjor_belopsmotsigelser.py`.
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

# De MERKEDE beløpsfeltene (R248). Bare disse sammenlignes — et beløp
# uten etikett blir aldri en dagsats (R71), så tallene i en
# beregningstabell kan aldri bli til et funn. Feltene er dessuten
# ARTSSKILTE: dagsats og månedsbeløp er ulike med matematisk
# nødvendighet, og sammenlignes derfor aldri med hverandre.
BELOPSFELT = ("dagsats", "manedsbelop", "utbetalt_belop",
              "tilbakebetalingsbelop")

# Navnene på sjekkene som kjøres — rapporteres alltid, se modulinnledningen.
SJEKKER = ("flere_personer", "umulig_rekkefolge", "ulikt_belop")


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


def _tall(raa):
    """Beløpet som tall, eller None.

    «1 240,00», «1240,00» og «1240» er SAMME beløp skrevet på tre måter.
    Sammenlignet som strenger ville de vært tre motsigelser — et funn
    som bare handler om skrivemåte er støy, og støy slår av vakten."""
    if raa is None:
        return None
    # Alt som ikke er siffer, komma, punktum eller minus kastes: det
    # dekker mellomrom, hardt mellomrom, «kr» og «kroner» i én regel.
    tett = "".join(c for c in str(raa)
                   if c.isdigit() or c in ",.-").replace(",", ".")
    try:
        return round(float(tett), 2)
    except ValueError:
        return None


def _ulikt_belop(sak: dict) -> list:
    """Samme merkede beløp, samme dato, ulik verdi (R248).

    HVORFOR SAMME DATO ER HELE REGELEN
    Et vedtak og et omgjøringsvedtak SKAL ha ulike beløp — klagen førte
    fram, og satsen ble endret. En regel som bare ser «to ulike tall»
    ville ropt på den friskeste saken i arkivet. Det som skiller en
    endring fra en motsigelse, er om det ene kan gå FORAN det andre:
    ulike datoer er en historie, samme dato er to påstander om samme
    øyeblikk — og da kan begge ikke stemme.

    Derfor sammenlignes bare dokumenter datert samme dag, og bare
    innenfor SAMME felt. Mangler datoen på det ene, sies ingenting:
    da kan ingen vite hva som går foran, og en gjetning der ville vært
    verre enn taushet."""
    per_nokkel = {}
    for dok in (sak.get("dokumenter") or []):
        if not isinstance(dok, dict):
            continue
        dato, _kilde = hendelsesdato(dok)
        if not dato:
            continue
        for felt in BELOPSFELT:
            verdi = _tall(dok.get(felt))
            if verdi is None:
                continue
            per_nokkel.setdefault((felt, dato), {}).setdefault(
                verdi, []).append(_dokumentnavn(dok))

    funn = []
    for (felt, dato), verdier in sorted(per_nokkel.items()):
        if len(verdier) < 2:
            continue
        dokumenter = sorted({n for navn in verdier.values() for n in navn})
        funn.append({
            "type": "ulikt_belop",
            "alvor": ALVOR_HOY,
            "forklaring": (
                f"«{felt}» er oppgitt med {len(verdier)} ulike verdier i "
                f"dokumenter datert {dato}. Dokumenter fra samme dag kan "
                "ikke gå foran hverandre, så begge kan ikke stemme — "
                "enten er mappa blandet, eller så er ett av dokumentene "
                "feil."),
            "dokumenter": dokumenter,
        })
    return funn


def finn_motsigelser(sak: dict) -> dict:
    """{funn, sjekket} for ÉN sak.

    `sjekket` er alltid med, også når `funn` er tomt: uten den kunne et
    tomt resultat leses som «saken henger sammen», og det er en påstand
    denne modulen ikke kan gjøre (R128)."""
    sak = sak if isinstance(sak, dict) else {}
    funn = (_flere_personer(sak) + _umulig_rekkefolge(sak)
            + _ulikt_belop(sak))
    funn.sort(key=lambda f: (f["type"], f["forklaring"]))
    return {"funn": funn, "sjekket": list(SJEKKER)}

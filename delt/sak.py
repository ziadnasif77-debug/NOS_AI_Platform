"""
Saken på tvers av filer — hvilke dokumenter hører sammen, og HVORFOR.

Systemet har til nå lest ett dokument om gangen. En bunke kunne deles i
flere dokumenter (`dokumentprofil.del_i_dokumenter`), men to opplastinger
hadde ingenting som bandt dem sammen: hver forespørsel var sin egen
verden. Et arkiv av saksdokumenter er ikke det — det er én sak fortalt av
tjue filer, og spørsmålene som betyr noe («ble vedtaket endret?», «hva
manglet da kravet kom?») kan bare besvares på tvers.

DET SOM BINDER, OG DET SOM BARE LIGNER
Denne modulen grupperer bare på det som kan BEVISES, og den skiller
skarpt mellom to slags bevis som er lette å blande:

  * SAKSNØKKEL (saksnummer, journalnummer) — beviser SAMME SAK.
    Et saksnummer er tildelt av etaten og står merket i dokumentet.
  * PERSONNØKKEL (fødselsnummer) — beviser SAMME PERSON, ikke samme
    sak. Én person kan ha sykepenger, dagpenger og en tilbakebetaling
    samtidig; tre saker, ett fødselsnummer.

Å slå sammen på fødselsnummer ville altså laget ÉN sak av tre, og
sammenblandingen ville sett riktig ut: alle dokumentene gjelder jo
samme person. Derfor melder modulen personsammenfall som en RELASJON
mellom saker, aldri som en sammenslåing.

NAVN BINDER INGENTING
Samme grunn som `bunkesporsmaal` teller personer på mod11 og ikke på
navn: «OLA NORDMANN», «Ola Nordmann» og «0la Nordrnann» er samme person
for et menneske og tre strenger for en maskin — og to ulike personer kan
hete det samme. Et navn er et hint, og hint grupperer ikke saksmapper.

DETERMINISME (R6)
Samme dokumenter i en annen rekkefølge SKAL gi samme saker. Grupperingen
er derfor en union-find over sorterte nøkler, og alle utlistinger er
sortert — ikke «i den rekkefølgen de kom».

HVA MODULEN IKKE GJØR
Den gjetter ikke. Et dokument uten en bevisbar saksnøkkel blir sin egen
sak med `grunn`-feltet utfylt, ikke tvunget inn i den nærmeste. Det er
det ærlige svaret: vi vet ikke om det hører hjemme der.
"""

# Nøkler som beviser SAMME SAK, sterkest først. Rekkefølgen bestemmer
# hvilken nøkkel saken navngis etter når et dokument bærer flere.
SAKSNOKLER = ("saksnummer", "journalnummer")

# Nøkkelen som beviser samme PERSON. Den grupperer aldri — se innledningen.
PERSONNOKKEL = "fnr"

# Grunner et dokument kan bli stående alene.
UTEN_SAKSNOKKEL = "ingen_bevist_saksnokkel"


def _verdi(dok: dict, felt: str):
    """Verdien av en nøkkel, normalisert — eller None.

    Saksnumre skrives med og uten mellomrom («44 17 820» / «4417820»),
    og et skille som bare finnes i skrivemåten skal ikke bli to saker.
    Bokstaver beholdes: «12/3456» er et ekte journalnummerformat."""
    raa = (dok or {}).get(felt)
    if not raa:
        return None
    tett = "".join(str(raa).split())
    return tett or None


def _sakstype_av(dok: dict) -> str:
    """Typekoden, uansett om feltet er en streng eller et {kode, term}."""
    type_ = (dok or {}).get("type")
    if isinstance(type_, dict):
        return type_.get("kode") or ""
    return type_ or ""


def _merkelapp(dok: dict) -> str:
    """Stabil, lesbar identifikator for ETT dokument — brukes til
    sortering, så to like dokumenter aldri bytter plass mellom kall."""
    return "|".join((
        str((dok or {}).get("filnavn") or ""),
        str((dok or {}).get("tittel") or ""),
        str((dok or {}).get("dato") or ""),
        _sakstype_av(dok),
    ))


def noklene_til(dok: dict) -> dict:
    """{felt: verdi} for saksnøklene dokumentet FAKTISK bærer.

    Tomt kart betyr at ingenting i dokumentet binder det til en sak —
    ikke at dokumentet er uinteressant."""
    funnet = {}
    for felt in SAKSNOKLER:
        verdi = _verdi(dok, felt)
        if verdi:
            funnet[felt] = verdi
    return funnet


def grupper_i_saker(dokumenter: list) -> list:
    """Dokumentene gruppert i saker, sortert og deterministisk.

    Hver sak er:
        {"nokkel": {"felt", "verdi"} | None,
         "grunnlag": tekst som sier HVORFOR de hører sammen,
         "grunn": None | «ingen_bevist_saksnokkel»,
         "dokumenter": [...]}

    To dokumenter havner i samme sak når de deler minst én saksnøkkel.
    Transitivt: deler A og B saksnummer, og B og C journalnummer, er alle
    tre samme sak — det er nettopp slik en sak henger sammen når
    dokumentene bærer ulike nøkler."""
    dokumenter = [d for d in (dokumenter or []) if isinstance(d, dict)]
    if not dokumenter:
        return []

    # Union-find over (felt, verdi). Sortert inngang gir determinisme:
    # hvilket dokument som «kom først» skal ikke kunne endre resultatet.
    rekkefolge = sorted(range(len(dokumenter)),
                        key=lambda i: (_merkelapp(dokumenter[i]), i))
    forelder = {}

    def finn(x):
        while forelder[x] != x:
            forelder[x] = forelder[forelder[x]]
            x = forelder[x]
        return x

    def foren(a, b):
        ra, rb = finn(a), finn(b)
        if ra != rb:
            # Minste rot vinner, så roten ikke avhenger av kallrekkefølgen
            if rb < ra:
                ra, rb = rb, ra
            forelder[rb] = ra

    for i in rekkefolge:
        merke = ("dok", i)
        forelder.setdefault(merke, merke)
        for felt, verdi in sorted(noklene_til(dokumenter[i]).items()):
            n = ("nokkel", felt, verdi)
            forelder.setdefault(n, n)
            foren(merke, n)

    # Samle dokumentene per rot
    grupper = {}
    for i in rekkefolge:
        grupper.setdefault(finn(("dok", i)), []).append(i)

    saker = []
    for rot in sorted(grupper, key=lambda r: _merkelapp(
            dokumenter[min(grupper[r])])):
        indekser = sorted(grupper[rot],
                          key=lambda i: (_merkelapp(dokumenter[i]), i))
        # Sakens navn: den STERKESTE nøkkelen noen av dokumentene bærer
        valgt = None
        for felt in SAKSNOKLER:
            verdier = sorted({v for i in indekser
                              for f, v in noklene_til(dokumenter[i]).items()
                              if f == felt})
            if verdier:
                valgt = {"felt": felt, "verdi": verdier[0]}
                break
        if valgt:
            baerer = sum(1 for i in indekser
                         if noklene_til(dokumenter[i]).get(valgt["felt"])
                         == valgt["verdi"])
            grunnlag = (f"{baerer} av {len(indekser)} dokumenter bærer "
                        f"{valgt['felt']} {valgt['verdi']}")
            if baerer < len(indekser):
                grunnlag += (" — de øvrige er bundet til saken gjennom en "
                             "annen nøkkel de deler")
            grunn = None
        else:
            grunnlag = ("Dokumentet bærer verken saksnummer eller "
                        "journalnummer, og er derfor ikke bevist å høre "
                        "sammen med noe annet")
            grunn = UTEN_SAKSNOKKEL
        saker.append({
            "nokkel": valgt,
            "grunnlag": grunnlag,
            "grunn": grunn,
            "dokumenter": [dokumenter[i] for i in indekser],
        })
    return saker


def personrelasjoner(saker: list) -> list:
    """Saker som deler et fødselsnummer — meldt som RELASJON, ikke slått
    sammen.

    Dette er skillet modulen finnes for: samme person er ikke samme sak.
    Én person kan ha sykepenger, dagpenger og en tilbakebetaling gående
    samtidig — tre saker, ett fødselsnummer. Slo vi dem sammen, ville
    «hva ble utfallet?» fått ett svar der det finnes tre.

    Returnerer [{fnr, saksindekser, forklaring}], sortert."""
    per_fnr = {}
    for nr, sak in enumerate(saker or []):
        for dok in sak.get("dokumenter") or []:
            fnr = _verdi(dok, PERSONNOKKEL)
            if fnr:
                per_fnr.setdefault(fnr, set()).add(nr)
    ut = []
    for fnr in sorted(per_fnr):
        indekser = sorted(per_fnr[fnr])
        if len(indekser) < 2:
            continue
        ut.append({
            "fnr": fnr,
            "saksindekser": indekser,
            "forklaring": (f"{len(indekser)} saker gjelder samme person. "
                           "Sakene er IKKE slått sammen: samme person er "
                           "ikke samme sak."),
        })
    return ut


def tidslinje(sak: dict) -> dict:
    """Sakens hendelser i tid — hver med dokumentet den kommer fra.

    {"hendelser": [{dato, hendelse, dokument, filnavn, sider}],
     "uten_dato": [...], "fra": …, "til": …}

    Dokumenter uten dato GJETTES IKKE inn i rekkefølgen. De listes for
    seg, for en tidslinje der noe er plassert på slump er verre enn en
    tidslinje med et hull: hullet ser man."""
    hendelser, uten_dato = [], []
    for dok in (sak or {}).get("dokumenter") or []:
        type_ = _sakstype_av(dok)
        term = ((dok.get("type") or {}).get("term")
                if isinstance(dok.get("type"), dict) else None)
        post = {
            "dato": dok.get("dato"),
            "hendelse": term or type_ or "Ukjent dokumenttype",
            "dokument": dok.get("tittel"),
            "filnavn": dok.get("filnavn"),
            "sider": dok.get("sider") or [],
        }
        (hendelser if dok.get("dato") else uten_dato).append(post)

    # Sortert på dato, så på merkelapp: to hendelser samme dag skal ha en
    # fast rekkefølge, ikke en tilfeldig (R6).
    hendelser.sort(key=lambda h: (h["dato"], str(h["filnavn"] or ""),
                                  str(h["dokument"] or "")))
    uten_dato.sort(key=lambda h: (str(h["filnavn"] or ""),
                                  str(h["dokument"] or "")))
    return {
        "hendelser": hendelser,
        "uten_dato": uten_dato,
        "fra": hendelser[0]["dato"] if hendelser else None,
        "til": hendelser[-1]["dato"] if hendelser else None,
    }

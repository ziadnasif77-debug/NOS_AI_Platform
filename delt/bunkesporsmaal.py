"""
Spørsmål om BUNKEN som helhet — koden teller, modellen gjetter (R229).

Fire spørsmål i korpuset handler ikke om hva som står i et dokument,
men om bunken som samling: hvor mange personer, om det er samme person
to steder, hvilke ytelser, hvor mange rader en tabell har. Modellen
svarte konsekvent feil på alle fire, og ikke ved å dikte:

    «Hvor mange ULIKE personer omtales i bunken?»
        → «Det omtales 1 ULIKE person i bunken.»   (det er to)
    «Er det samme person som har faatt vedtaket og som klager?»
        → «Ja … Ola Nordmann»                      (klagen er Marits)
    «Hvilke to ytelser er omtalt i bunken?»
        → «Arbeidsavkortning og sykepenger»        (ordet finnes ikke)
    «Hvor mange maaneder er med i beregningstabellen?»
        → «12 måneder»                             (det er seks)

DET ER TELLING, OG TELLING ER IKKE MODELLENS ARBEID
En språkmodell leser; den holder ikke regnskap. Å be en 4B-modell telle
distinkte personer i ti sider er å be den om noe den ikke er bygget
for — og svaret «1 person» på en bunke med to er ikke en unøyaktighet,
det er feil opplysning til en saksbehandler som skal se om saken gjelder
flere. CLAUDE.md §4: prompten styrer, koden garanterer. Dette er en
garanti.

GRUNNLAGET ER ALLEREDE VALIDERT
Personene telles på FØDSELSNUMMER med kontrollsiffer, ikke på navn:
samme person skrives «OLA NORDMANN», «Ola Nordmann Nor-Etternavn» og
«NOR-ETTERNAVN, OLA» i den samme bunken, og et navnesøk ville talt tre.
Dokumentgrensene kommer fra `del_i_dokumenter` (R226), ytelsene fra
`_ytelsestreff` (som nå også kjenner nynorsk), og tabellradene fra
`sidegeometri` (R219).

DEN SVARER IKKE NÅR DEN ER I TVIL
Hvert mønster er smalt, og treffer det ikke, går spørsmålet videre til
modellen som før. Særlig: et spørsmål som gjelder ETT dokument
(«hvilken ytelse gjelder klagen?») skal rutes dit av
`dokumentruting`, ikke besvares her med hele bunkens ytelser.
"""
import re

# «Hvor mange ulike personer …» — spørsmålet om bunkens omfang.
_PERSONER = re.compile(
    r"hvor\s+mange\s+(?:\w+\s+){0,2}?(personer|parter|personar)\b",
    re.IGNORECASE)

# «Er det samme person som …» — krever at spørsmålet peker på to
# dokumenter, ellers vet vi ikke hva som skal sammenlignes.
_SAMME_PERSON = re.compile(
    r"samme\s+person|same\s+person|samme\s+part\b", re.IGNORECASE)

# «Hvilke ytelser er omtalt i bunken?»
_YTELSER = re.compile(r"hvilke[nt]?\s+(?:\w+\s+){0,2}?ytels", re.IGNORECASE)

# Spørsmålet må si at det gjelder HELE samlingen. Uten dette fanget
# ytelsemønsteret «Hvilken ytelse gjelder tilbakebetalingskravet?» og
# svarte med bunkens to ytelser — som besto fasiten, fordi den er et
# delstrengsøk, men svarte på et annet spørsmål enn det som ble stilt.
# Et svar som er riktig av feil grunn, er en feil som venter.
_HELE_BUNKEN = re.compile(
    r"\bbunken?\b|\bbunka\b|\bfilen?\b|\bfila\b|\bdokumentene\b"
    r"|\bdokumenta\b|\bhele\s+dokumentet\b|\balle\s+sidene?\b",
    re.IGNORECASE)

# «Hvor mange X er med i tabellen» — STØRRELSEN på tabellen.
_TABELLSTORRELSE = re.compile(
    r"hvor\s+mange\s+(\w+)\s+(?:er\s+med|st(?:å|aa)r|finnes|inng(?:å|aa)r)\b",
    re.IGNORECASE)
# … men ikke når spørsmålet ber om en VERDI i tabellen. «Hvor mange
# dager er summen i beregningstabellen?» ser nesten likedan ut, og
# svaret er 129 — en celle, ikke et antall rader.
_VERDISPORSMAL = re.compile(r"\bsum|til\s+sammen|totalt\b", re.IGNORECASE)


def _fodselsnummer(tekst: str) -> list:
    from delt.tekstuttrekk import finn_alle_fodselsnummer
    return finn_alle_fodselsnummer(tekst or "")


def _dokumenter(tekst: str) -> list:
    from delt.dokumentprofil import del_i_dokumenter
    try:
        return del_i_dokumenter(tekst or "", None)
    except Exception:                                           # noqa: BLE001
        return []


def _type(dokument: dict) -> str:
    type_ = (dokument or {}).get("type")
    return (type_.get("kode") or "") if isinstance(type_, dict) else (type_ or "")


def _sidetekster(tekst: str) -> dict:
    """{sidenummer: tekst} fra sidemarkørene."""
    biter = re.split(r"\[Side (\d+) av \d+\]\n?", tekst or "")
    ut = {}
    for i in range(1, len(biter) - 1, 2):
        try:
            ut[int(biter[i])] = biter[i + 1]
        except ValueError:
            continue
    return ut


def _personer(sporsmal: str, tekst: str) -> dict:
    """Antall ULIKE personer i bunken, talt på fødselsnummer."""
    from delt import dokumentruting

    if dokumentruting.typer_i_sporsmal(sporsmal):
        # «Hvor mange personer står i klagen?» gjelder ETT dokument, og
        # skal rutes dit — ikke besvares med hele bunkens telling.
        return None
    numre = list(dict.fromkeys(_fodselsnummer(tekst)))
    if not numre:
        return None
    ord_ = "person" if len(numre) == 1 else "personer"
    return {"svar": f"{len(numre)} {ord_}",
            "tolket": (f"{len(numre)} ulike fødselsnummer med gyldig "
                       "kontrollsiffer funnet i bunken (deterministisk telling)"),
            "grunnlag": "fodselsnummer"}


def _samme_person(sporsmal: str, tekst: str) -> dict:
    """Er det samme person i de to dokumentene spørsmålet peker på?"""
    from delt import dokumentruting

    typer = dokumentruting.typer_i_sporsmal(sporsmal)
    if len(typer) != 2:
        return None                 # ikke to dokumenter å sammenligne
    dokumenter = _dokumenter(tekst)
    sider = _sidetekster(tekst)
    if len(dokumenter) < 2 or not sider:
        return None
    funn = {}
    for type_ in typer:
        traff = [d for d in dokumenter if _type(d) == type_]
        if len(traff) != 1:
            return None             # flertydig — da svarer vi ikke
        numre = set()
        for nr in traff[0].get("sider") or []:
            numre.update(_fodselsnummer(sider.get(nr, "")))
        if not numre:
            return None             # ett av dokumentene navngir ingen
        funn[type_] = numre
    a, b = (funn[t] for t in typer)
    lik = bool(a & b)
    navn = " og ".join(typer)
    return {"svar": ("Ja, det er samme person." if lik
                     else "Nei, det er to ulike personer."),
            "tolket": (f"fødselsnumrene i {navn}-dokumentene sammenlignet "
                       "deterministisk — "
                       + ("samme nummer" if lik else "ulike numre")),
            "grunnlag": "fodselsnummer"}


def _ytelser(sporsmal: str, tekst: str) -> dict:
    """Ytelsene bunken omtaler."""
    from delt import dokumentruting
    from delt.tekstuttrekk import YTELSE_TERM, _ytelsestreff

    if not _HELE_BUNKEN.search(sporsmal or ""):
        return None                 # spørsmålet gjelder ikke samlingen
    if dokumentruting.typer_i_sporsmal(sporsmal):
        # Spørsmålet peker på et bestemt dokument — da er det
        # dokumentets ytelse som spørres etter, ikke bunkens.
        return None
    funn = sorted({navn for _a, _b, navn in _ytelsestreff(tekst or "")})
    if not funn:
        return None
    termer = [YTELSE_TERM.get(n, n) for n in funn]
    return {"svar": " og ".join(termer) if len(termer) > 1 else termer[0],
            "tolket": (f"{len(termer)} ytelse(r) funnet i bunken ved "
                       "ordoppslag mot ytelseslista (deterministisk)"),
            "grunnlag": "ytelsesliste"}


# Radene slik `sidegeometri` skrev dem: «Maaned: Juli 2026 | Dager: 23 …».
# Teksten LESES tilbake i den formen den ble skrevet i — den er
# kontrakten mellom de to modulene, ikke en ny tolkning av PDF-en (R111).
_TABELLCELLE = re.compile(r"(?:^|\|\s*)([^:|]{1,40}?):\s*([^|]*)")
_TABELLHODE = re.compile(r"^\[TABELL:\s*(.*?)\]\s*$")
_SUMRAD = ("sum", "totalt", "i alt", "til sammen", "sum totalt")


# Hvor mange linjer over tabellen som regnes som dens overskrift. Det
# er der en tabell får navnet sitt: «Vedlegg 1 - Beregning av
# sykepenger» står tre linjer over beregningstabellen.
_TABELLKONTEKST = 4


def _tabeller_i_tekst(tekst: str) -> list:
    """[(kontekst, [rad, …]), …] — én oppføring per tabell i teksten.

    `kontekst` er linjene rett over tabellen. De trengs fordi en bunke
    kan ha flere tabeller med samme kolonner, og det er der tabellen
    sier hva den er."""
    linjer = (tekst or "").splitlines()
    ut, naa = [], None
    for nr, linje in enumerate(linjer):
        if _TABELLHODE.match(linje.strip()):
            kontekst = " ".join(linjer[max(0, nr - _TABELLKONTEKST):nr])
            naa = []
            ut.append((kontekst, naa))
            continue
        celler = [(k.strip(), v.strip())
                  for k, v in _TABELLCELLE.findall(linje)]
        if naa is not None and len(celler) >= 2:
            naa.append(celler)
        elif len(celler) < 2:
            naa = None              # tabellen er slutt
    return [(k, r) for k, r in ut if r]


# «beregningstabellen» → forleddet «beregnings», som er tabellens navn.
_TABELLNAVN = re.compile(r"\b(\w{4,})tabell(?:en|a|ene)?\b", re.IGNORECASE)


def _med_tabellnavn(sporsmal: str, passer: list) -> list:
    """De tabellene som svarer til navnet spørsmålet bruker.

    Uten dette måtte telleren tie hver gang en bunke hadde to tabeller
    med samme kolonne — og det er den vanlige situasjonen, ikke
    unntaket. Med det kan den svare når spørsmålet HAR sagt hvilken det
    gjelder, og fortsatt tie når det ikke har det."""
    from delt.bevisvalg import _samme_ord

    treff = _TABELLNAVN.search(sporsmal or "")
    if not treff:
        return passer
    navn = treff.group(1).lower()
    valgt = [p for p in passer
             if any(_samme_ord(navn, o.lower())
                    for o in re.findall(r"[^\W\d_]{4,}", p[2]))]
    return valgt or passer


def _tabellstorrelse(sporsmal: str, tekst: str) -> dict:
    """Hvor mange rader har tabellen — ikke hva som står i den.

    NEKTER Å SVARE NÅR FLERE TABELLER PASSER. Bunken har to tabeller med
    kolonnen «Maaned» — beregningen på side 2 og inntekten på side 6 —
    og første utkast returnerte den første av dem. Svaret var riktig,
    men av flaks, og en teller som velger vilkårlig mellom to tabeller
    er verre enn ingen teller: den ser like sikker ut begge ganger."""
    if _VERDISPORSMAL.search(sporsmal or ""):
        return None                 # «hvor mange dager er SUMMEN» er en celle
    treff = _TABELLSTORRELSE.search(sporsmal or "")
    if not treff:
        return None
    from delt.bevisvalg import _samme_ord

    spurt = treff.group(1).lower()
    passer = []
    for kontekst, tabell in _tabeller_i_tekst(tekst):
        kolonne = None
        rader = 0
        for celler in tabell:
            if celler[0][1].strip().lower() in _SUMRAD:
                continue
            for navn, verdi in celler:
                if verdi and _samme_ord(spurt, navn.lower()):
                    kolonne = navn
                    rader += 1
                    break
        if kolonne and rader:
            passer.append((kolonne, rader, kontekst))
    if len(passer) > 1:
        # Flere tabeller har kolonnen. Da avgjør spørsmålets eget
        # navn på tabellen — «beregningstabellen» peker på den under
        # overskriften «Beregning av sykepenger», ikke på
        # inntektstabellen som også har en «Maaned»-kolonne.
        passer = _med_tabellnavn(sporsmal, passer)
    if len(passer) != 1:
        return None
    kolonne, rader, _kontekst = passer[0]
    return {"svar": f"{rader}",
            "tolket": (f"radene i tabellen telt deterministisk under "
                       f"kolonnen «{kolonne}» — sumraden er ikke talt med"),
            "grunnlag": "tabellrader"}


def svar(sporsmal: str, tekst: str) -> dict:
    """{svar, tolket, grunnlag} for et bunkespørsmål — ellers None.

    `tekst` er dokumentteksten med sidemarkørene intakt, slik
    `sidegeometri` bygget den."""
    if not (sporsmal or "").strip() or not (tekst or "").strip():
        return None
    if _PERSONER.search(sporsmal):
        return _personer(sporsmal, tekst)
    if _SAMME_PERSON.search(sporsmal):
        return _samme_person(sporsmal, tekst)
    if _YTELSER.search(sporsmal):
        return _ytelser(sporsmal, tekst)
    return _tabellstorrelse(sporsmal, tekst)

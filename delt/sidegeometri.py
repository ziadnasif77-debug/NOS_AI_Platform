"""
Bygger sideteksten opp igjen fra ordenes POSISJON (R219, R227).

`get_text()` gir en flat strøm av linjer. To slags informasjon går tapt
på veien, og begge finnes fortsatt i koordinatene:

  KOLONNENE i en tabell. Én celle per linje, og rekkefølgen er alt
  modellen har å gjette struktur ut av.

  ORDGRENSENE i utfylte felter. Håndskrift og skjemafelter kommer tegn
  for tegn — «Dr a mm e n», «1 8.0 6. 20 2 6» — fordi hvert tegn er sin
  egen tekstoperasjon i PDF-en. Modellen svarte «Dr a mm e n» på
  spørsmålet om hvor egenerklæringen var underskrevet, og leste
  «8. juni 2020» ut av mottatt-datoen 18.06.2026.

Begge løses av det samme: les ordene med koordinatene sine, og sett
teksten sammen igjen ut fra hvor de STÅR.

TABELLENE — KOLONNENE OVERLEVER

Målt på beregningstabellen i et sykepengevedtak. Modellen fikk fem
spørsmål om den, og bommet på alle fem — men ikke ved å dikte:

    «Hva er bruttobeløpet for juli 2026?»   svarte 31 717 (juli NETTO)
    «Hva er summen av bruttobeløpene?»      svarte 177 891 (sum NETTO)
    «Hvor mange dager er summen?»           svarte 177 891 (et beløp)

Hver verdi STÅR i tabellen. De står bare i feil kolonne, og grunnen er
at kolonnene ikke fantes lenger da modellen fikk teksten:

    Maaned / Dager / Dagsats / Bruttobeloep / Skattetrekk / Nettobeloep
    April 2026 / 21 / 1 970 / 41 370 / 12 411 / 28 959
    …

`get_text()` gir én celle per linje. Rader og kolonner er borte, og det
eneste som er igjen er rekkefølgen — som modellen må gjette strukturen
ut av. Den gjettet konsekvent feil.

SUM-RADEN VISER HVORFOR REKKEFØLGE IKKE HOLDER

    SUM / 129 / 254 130 / 76 239 / 177 891

Fem celler der de andre radene har seks: `Dagsats` er tom. Teller man
posisjoner, blir 254 130 til «Dagsats». Med x-koordinaten havner den i
`Bruttobeloep`, der den hører hjemme.

Derfor bygges tabellen fra GEOMETRIEN, ikke fra rekkefølgen. Det er
også derfor dette er kode og ikke en prompt (§4): en instruks om å lese
tabeller nøye gir modellen ikke tilbake informasjonen som er kastet.

VIRKER FOR BEGGE VEIENE
Funksjonene tar (x0, y0, x1, tekst) og bryr seg ikke om hvor de kommer
fra: `page.get_text("words")` for tekstlag, eller OCR-regionenes bokser
for skannede sider.
"""
import os
import re

# Hvordan en tabellrad skrives ut. Se `_radlinje` for de to formene og
# hva de koster. Verdien avgjøres av korpusmålingen, ikke av smak.
STIL = (os.environ.get("TABELLSTIL", "navngitt").strip().lower()
        or "navngitt")

# Vannrett avstand som skiller to CELLER. Under dette hører ordene
# sammen: «1» og «970» står 2 punkter fra hverandre og er ett tall,
# mens «970» og «41» står 51 fra hverandre og er to kolonner.
CELLEGAP = 12.0

# Under dette hører bitene til SAMME ORD, og settes sammen uten
# mellomrom. Målt på skjemaene i testbunken er de to avstandene skarpt
# atskilt: bitene i et håndskrevet felt står −1,4 til +0,5 punkter fra
# hverandre (de rører hverandre eller overlapper), mens et ekte
# ordmellomrom er 1,8 til 3,7.
#
# Terskelen er en ANDEL av tegnbredden på linja, ikke et fast tall:
# et fast tall er bundet til skriftstørrelsen, og en side med liten
# skrift ville fått vanlige ord limt sammen. Målt ga 0,35 nettopp det
# («Leggdennesida», «NAVSkanning» på returslippen), 0,25 slo sammen
# «I. Hansen» til «I.Hansen», og 0,20 traff hver eneste håndskriftlinje
# i bunken uten å røre en eneste trykt.
BITGAP_ANDEL = 0.20

# Loddrett slingring innenfor samme RAD. Tekstlinjer i en tabell ligger
# ikke på nøyaktig samme y — en brøkdel av et punkt er vanlig.
RADSLING = 3.0

# Hvor nær en celle må ligge en kolonnestart for å regnes som den.
KOLONNESLING = 12.0

# En tabell skal ha noe å være tabell av.
MINSTE_KOLONNER = 3
MINSTE_RADER = 3

_TALL = re.compile(r"^[\d\s.,%-]+$")


def _rader(ord_liste, sling=RADSLING):
    """Ord gruppert i rader etter y, hver rad sortert på x."""
    rader = {}
    for x0, y0, x1, tekst in ord_liste:
        if not (tekst or "").strip():
            continue
        naerme = [y for y in rader if abs(y - y0) <= sling]
        y = naerme[0] if naerme else y0
        rader.setdefault(y, []).append((x0, x1, tekst))
    return [(y, sorted(rader[y])) for y in sorted(rader)]


def _tegnbredde(rad) -> float:
    """Median bredde per tegn på linja — målestokken for avstandene."""
    bredder = sorted((x1 - x0) / max(1, len(t))
                     for x0, x1, t in rad if (t or "").strip())
    if not bredder:
        return 0.0
    midt = len(bredder) // 2
    return (bredder[midt] if len(bredder) % 2
            else (bredder[midt - 1] + bredder[midt]) / 2)


def _slaa_sammen_biter(rad):
    """Tegnbiter fra samme ord satt sammen igjen, uten mellomrom.

    Et utfylt skjemafelt er én tekstoperasjon per tegn i PDF-en, og
    `get_text("words")` leverer dem som separate «ord». Da blir stedet
    egenerklæringen er underskrevet, stående som «Dr a mm e n», og
    mottatt-datoen på returslippen som «1 8.0 6. 20 2 6» — som modellen
    leste som «8. juni 2020».

    Bitene røper seg på avstanden: de rører hverandre. Se `BITGAP_ANDEL`
    for hvorfor terskelen er en andel av tegnbredden og ikke et tall."""
    if len(rad) < 2:
        return list(rad)
    grense = BITGAP_ANDEL * _tegnbredde(rad)
    if grense <= 0:
        return list(rad)
    ut = [list(rad[0])]
    for x0, x1, tekst in rad[1:]:
        if x0 - ut[-1][1] < grense:
            ut[-1][1] = x1
            ut[-1][2] += tekst
        else:
            ut.append([x0, x1, tekst])
    return [tuple(c) for c in ut]


def _celler(rad, gap=CELLEGAP):
    """Ord slått sammen til celler. Returnerer [(x_start, tekst), …].

    To nivåer: først settes tegnbiter sammen til ORD (uten mellomrom),
    så settes ord sammen til CELLER (med mellomrom). Rekkefølgen er
    ikke likegyldig — slår man sammen til celler først, er bitene
    allerede limt med mellomrom mellom seg."""
    ut = []
    for x0, x1, tekst in _slaa_sammen_biter(rad):
        if ut and x0 - ut[-1][2] <= gap:
            ut[-1] = (ut[-1][0], ut[-1][1] + " " + tekst, x1)
        else:
            ut.append((x0, tekst, x1))
    return [(x, t) for x, t, _ in ut]


def _er_tall(tekst: str) -> bool:
    t = (tekst or "").strip()
    return bool(t) and bool(_TALL.match(t)) and any(c.isdigit() for c in t)


def _linjer(ord_liste) -> list:
    """Siden som linjer i leserekkefølge: [(y, [(x, tekst), …])]."""
    return [(y, _celler(rad)) for y, rad in _rader(ord_liste)]


def _blokker(linjer) -> list:
    """Tabellene som (medlemsindekser, kolonner) inn i `linjer`.

    Indeksene beholdes fordi teksten skal kunne bygges opp igjen med
    tabellen på PLASSEN sin. Uten dem vet vi hva tabellen inneholder,
    men ikke hvor den sto, og da kan den bare legges ved — som var
    nøyaktig det som kostet fire riktige svar: hvert tall to ganger,
    og datospørsmålene druknet i dobbelt så mange tall."""
    kandidater = [i for i, (_y, c) in enumerate(linjer)
                  if len(c) >= MINSTE_KOLONNER]
    ut, k = [], 0
    while k < len(kandidater):
        i = kandidater[k]
        kolonner = [x for x, _ in linjer[i][1]]
        med = [i]
        m = k + 1
        while m < len(kandidater):
            j = kandidater[m]
            # Deler raden kolonnestartene? Den TRENGER ikke ha alle —
            # SUM-raden mangler «Dagsats» — men de den har, skal treffe.
            if all(any(abs(x - kol) <= KOLONNESLING for kol in kolonner)
                   for x, _ in linjer[j][1]):
                med.append(j)
                for x, _ in linjer[j][1]:
                    if not any(abs(x - kol) <= KOLONNESLING
                               for kol in kolonner):
                        kolonner.append(x)
                m += 1
            else:
                break
        if len(med) >= MINSTE_RADER:
            ut.append((med, sorted(kolonner)))
            k = m
        else:
            k += 1
    return ut


def finn_tabeller(ord_liste) -> list:
    """Tabellene på en side. Hver: {overskrifter, rader, kolonner}.

    En tabell er tre eller flere rader på rad som deler de samme
    kolonnestartene. Overskriftsraden er den første av dem der ingen
    celle er et tall — står det tall i alle cellene, er det en datarad
    og tabellen har ingen overskrift vi kan navngi kolonnene med."""
    linjer = _linjer(ord_liste)
    return [_bygg([linjer[i] for i in med], kolonner)
            for med, kolonner in _blokker(linjer)]


def _bygg(blokk, kolonner) -> dict:
    """Radene lagt inn i kolonnene sine, med tomme der celler mangler."""
    def kolonne_for(x):
        beste, avstand = 0, None
        for nr, k in enumerate(kolonner):
            d = abs(x - k)
            if avstand is None or d < avstand:
                beste, avstand = nr, d
        return beste

    rader = []
    for _y, celler in blokk:
        rad = [""] * len(kolonner)
        for x, tekst in celler:
            nr = kolonne_for(x)
            rad[nr] = (rad[nr] + " " + tekst).strip() if rad[nr] else tekst
        rader.append(rad)

    overskrifter = None
    if rader and not any(_er_tall(c) for c in rader[0] if c):
        overskrifter = rader[0]
        rader = rader[1:]
    return {"overskrifter": overskrifter, "rader": rader,
            "kolonner": len(kolonner)}


def som_tekst(tabell: dict) -> str:
    """Tabellen som linjer modellen ikke kan misforstå.

    Hver celle bærer navnet på kolonnen sin. Da spiller rekkefølgen
    ingen rolle lenger, og en tom celle blir borte i stedet for å
    forskyve alt etter seg — som var hele feilen."""
    ut = []
    for rad in tabell["rader"]:
        if tabell["overskrifter"]:
            deler = [f"{o.strip()}: {v.strip()}"
                     for o, v in zip(tabell["overskrifter"], rad)
                     if v.strip() and o.strip()]
        else:
            deler = [v.strip() for v in rad if v.strip()]
        if deler:
            ut.append(" | ".join(deler))
    return "\n".join(ut)


def tabelltekst_for_side(ord_liste) -> str:
    """Alle tabellene på siden, klare til å legges ved dokumentteksten."""
    biter = []
    for nr, tab in enumerate(finn_tabeller(ord_liste), 1):
        tekst = som_tekst(tab)
        if not tekst:
            continue
        navn = (", ".join(o.strip() for o in tab["overskrifter"] if o.strip())
                if tab["overskrifter"] else f"tabell {nr}")
        biter.append(f"[TABELL: {navn}]\n{tekst}")
    return "\n\n".join(biter)


def sidetekst(ord_liste) -> str:
    """Hele siden som tekst, med tabellradene navngitt på plassen sin.

    ERSTATTER, LEGGER IKKE VED — og det er en målt beslutning.

    Første forsøk la den bygde tabellen ved siden av den flate teksten.
    Det fikset de fire spørsmålene om beregningstabellen og ØDELA fire
    andre som var riktige før: `klage_paaklaget_vedtak`,
    `saksbehandler_tittel`, `refusjon_fra`, `returslipp_mottatt`. Netto
    null. Alle fire hadde en side som vokste i konteksten sin, og tre av
    dem spør etter en DATO. Vedlegget doblet antall tall på side 2 og 6,
    og datospørsmålene druknet i dem.

    Derfor står hvert tall nå ÉN gang, med kolonnenavnet sitt. Ingen ord
    forsvinner: linjer utenfor en tabell gjengis ord for ord, og
    tabellinjene gjengis navngitt. Rekonstruksjonen bygger på ordene,
    ikke på å klippe i ferdig tekst — det er derfor den ikke kan miste
    noe uten at det synes."""
    linjer = _linjer(ord_liste)
    if not linjer:
        return ""
    blokker = _blokker(linjer)
    # indeks → (tabell, radnummer i tabellen)
    plass = {}
    for tab_nr, (med, kolonner) in enumerate(blokker):
        tab = _bygg([linjer[i] for i in med], kolonner)
        if not tab["overskrifter"]:
            # KAN VI IKKE NAVNGI KOLONNENE, SKAL VI IKKE RØRE TEKSTEN.
            # Målt på en ekte kontoutskrift: alle tretten tabellene der
            # er uten overskrift, fordi beløpene er HØYREJUSTERT — deres
            # venstrekant flytter seg med tallets bredde, mens
            # overskriften står fast, så de to radene deler ingen
            # kolonnestart. Resultatet var rader som «Varekjøp | 107,00
            # | 07.04.26»: skillene sier at beløpet er en egen celle,
            # men ikke om det er «Ut av konto» eller «Inn på konto» —
            # nettopp spørsmålet modulen finnes for.
            #
            # Da er det ærligere å la teksten stå. R220 målte hva en
            # kontekstendring uten gevinst koster: fire riktige svar.
            continue
        # `_bygg` tar overskriftsraden ut av `rader`; her trengs den
        # tilbake på linja si, ellers forsvinner den fra teksten.
        rader = ([tab["overskrifter"]] if tab["overskrifter"] else []) \
            + tab["rader"]
        for radnr, indeks in enumerate(med):
            if radnr < len(rader):
                plass[indeks] = (tab, tab_nr, rader[radnr],
                                 radnr == 0 and bool(tab["overskrifter"]))

    ut = []
    for i, (_y, celler) in enumerate(linjer):
        if i in plass:
            tab, _tab_nr, rad, er_overskrift = plass[i]
            ut.append(_radlinje(tab, rad, er_overskrift))
        else:
            ut.append(" ".join(t for _x, t in celler))
    return "\n".join(ut)


def _radlinje(tab: dict, rad: list, er_overskrift: bool) -> str:
    """Én tabellrad som tekst, i den valgte stilen.

    To stiler, fordi de bytter presisjon mot lengde og bare en måling
    kan si hva som lønner seg:

    `navngitt` — hver celle bærer kolonnenavnet sitt. Modellen trenger
    ikke telle noe som helst, og en tom celle kan ikke forskyve resten.
    Koster ~500 tegn på beregningstabellen.

    `kolonner` — én overskriftsrad, så bare verdier. Kortere, men
    kolonnen må telles fram, og da må den tomme cellen merkes eksplisitt
    («-») for at SUM-raden ikke skal forskyve seg — nettopp feilen hele
    modulen finnes for."""
    if er_overskrift:
        navn = ", ".join(o.strip() for o in tab["overskrifter"] if o.strip())
        if STIL == "kolonner":
            return ("[TABELL] "
                    + " | ".join(o.strip() for o in tab["overskrifter"]))
        return f"[TABELL: {navn}]"
    if not tab["overskrifter"]:
        return " | ".join(v.strip() for v in rad if v.strip())
    if STIL == "kolonner":
        return " | ".join(v.strip() if v.strip() else "-" for v in rad)
    deler = [f"{o.strip()}: {v.strip()}"
             for o, v in zip(tab["overskrifter"], rad)
             if v.strip() and o.strip()]
    return " | ".join(deler)


def _navngivbar_tabell(ord_liste) -> bool:
    """Finnes det en tabell vi kan sette NAVN på kolonnene i?

    En tabell uten overskrift gir ingenting å vinne — se `sidetekst`."""
    linjer = _linjer(ord_liste)
    for med, kolonner in _blokker(linjer):
        if _bygg([linjer[i] for i in med], kolonner)["overskrifter"]:
            return True
    return False


def _har_biter(ord_liste) -> bool:
    """Finnes det tegnbiter på siden som hører til samme ord?"""
    for _y, rad in _rader(ord_liste):
        if len(_slaa_sammen_biter(rad)) < len(rad):
            return True
    return False


def bygg_om(side, tekst: str) -> str:
    """Sideteksten bygget opp igjen fra ordenes posisjon.

    `side` er et PyMuPDF-sideobjekt. Teksten byttes bare ut når siden
    har noe å vinne på det — en tabell, eller ord som er delt i
    tegnbiter. Har den ingen av delene, leveres `get_text()` urørt; vi
    skriver ikke om sider som ikke trenger det.

    Feiler ordhentingen, leveres teksten også urørt: en side vi ikke
    klarte å bygge om, skal ikke koste dokumentet."""
    try:
        ord_ = [(o[0], o[1], o[2], o[4]) for o in side.get_text("words")]
    except Exception:                                           # noqa: BLE001
        return tekst
    if not ord_:
        return tekst
    try:
        if not _navngivbar_tabell(ord_) and not _har_biter(ord_):
            return tekst
        ny = sidetekst(ord_)
    except Exception:                                           # noqa: BLE001
        return tekst
    # Sikkerhetsnett: blir den nye teksten vesentlig kortere enn den
    # gamle, har rekonstruksjonen mistet noe, og da beholder vi
    # originalen. Vi bytter bare når vi vinner struktur uten å tape ord.
    if len(ny.strip()) < 0.8 * len(tekst.strip()):
        return tekst
    return ny

"""
Sakssammendrag (R249) — saken fortalt som ÉN sak, ikke som en bunke
dokumentsammendrag.

Systemet kunne oppsummere ett dokument. Spør man i stedet «hva skjedde i
denne saken?», er svaret ikke elleve sammendrag etter hverandre: det er
hvem saken gjelder, hva den handler om, hva som skjedde, hva som manglet,
hva som ble bestemt — og hva som ble bestemt TIL SLUTT.

HVORFOR DETTE ER KODE OG IKKE EN PROMPT
Fristelsen er å gi dokumentene til språkmodellen og be om et sammendrag.
Målingen i R229 sier hvorfor det ikke går: modellen ble spurt om hvor
mange personer en bunke omtaler, om det var samme person som klaget som
fikk vedtaket, og hvilke ytelser som var nevnt — og svarte feil på alle.
Den leser; den holder ikke regnskap. Et sakssammendrag ER regnskap.
Dessuten: kontekstvinduet tar 3008 tokens til prompt, dokument og
spørsmål til sammen. Tolv dokumenter får ikke plass, uansett prompt.

Derfor utledes alt her av felt som ALLEREDE er bevist: parten av et
mod11-validert fødselsnummer under en eierEtikett, datoene av
datomodellen, manglene av forventningstabellen (R247), motsigelsene av
R243/R248. Sammendraget legger ingenting til — det ORDNER.

SISTE AVGJØRELSE ER IKKE SISTE DOKUMENT
Spørsmålet «hva ble det til slutt?» besvares ikke av det nyeste
dokumentet i mappa: et journalnotat skrevet etter klagevedtaket er
nyere, men avgjør ingenting. Bare avgjørende dokumenttyper teller, og
blant dem går klageinstansens vedtak foran førsteinstansens uansett
dato — det er hele poenget med en klageinstans.

STATUS ER EN SLUTNING, OG SIES Å VÆRE DET
`status` er utledet av hvilke dokumenttyper som finnes og i hvilken
rekkefølge. Det er en regel anvendt på bevis, ikke et bevis — og
opphavskartet merker den `regel`, ikke `etikett`. Finnes ikke grunnlag,
er svaret `ukjent`, ikke en gjetning.
"""
from delt.sak import _sakstype_av, _verdi, hendelsesdato

# Dokumenttypene som AVGJØR noe. Et notat er ikke en avgjørelse, uansett
# hvor sent det er skrevet.
AVGJORENDE = ("vedtak", "klagevedtak")

# Typene som utgjør sakens gang — det en saksbehandler vil se i ett blikk.
# Rekkefølgen her er ingen tidslinje; den kommer av datoene.
FORLOPSTYPER = ("soknad", "vedtak", "klage", "klagevedtak",
                "dokumentasjonskrav", "purring")

# Lukket statusvokabular. En verdi utenfor dette er en feil, ikke en ny
# kategori — samme regel som METODER i `opphav`.
STATUSER = {
    "avgjort_etter_klage": "Avgjort etter klage",
    "avgjort": "Avgjort",
    "venter_paa_dokumentasjon": "Venter på dokumentasjon",
    "under_behandling": "Under behandling",
    "ukjent": "Ukjent",
}


def _navn(dok: dict) -> str:
    return str((dok or {}).get("filnavn")
               or (dok or {}).get("tittel") or "dokument uten navn")


def _datert(dokumenter: list, typer) -> list:
    """(dato, dokument) for dokumentene av de gitte typene som HAR en
    dato, eldst først. Udaterte utelates: de kan ikke ordnes i tid, og
    en gjetning her ville vært verre enn et hull."""
    ut = []
    for dok in dokumenter:
        if _sakstype_av(dok) not in typer:
            continue
        dato, _kilde = hendelsesdato(dok)
        if dato:
            ut.append((dato, dok))
    ut.sort(key=lambda t: (t[0], _navn(t[1])))
    return ut


def _part(dokumenter: list) -> dict:
    """Hvem saken gjelder — bevist, eller ærlig `null`.

    Fødselsnummeret er alt mod11-validert og hentet under en eier-
    etikett; her telles det bare opp. Er det flere, sies det, og ingen
    av dem velges: å plukke ett ville vært å gjette hvem saken gjelder
    (samme grunn som `finn_dokument_eier` nekter)."""
    per_fnr = {}
    for dok in dokumenter:
        fnr = _verdi(dok, "fnr")
        if fnr:
            per_fnr.setdefault(fnr, []).append(_navn(dok))
    if not per_fnr:
        return {"fnr": None, "antall_personer": 0,
                "grunnlag": "Ingen av dokumentene bærer et fødselsnummer "
                            "under en etikett som viser hvem saken gjelder."}
    if len(per_fnr) > 1:
        return {"fnr": None, "antall_personer": len(per_fnr),
                "grunnlag": f"Saken bærer {len(per_fnr)} ulike "
                            "fødselsnummer — hvem den gjelder kan ikke "
                            "avgjøres. Se «motsigelser»."}
    fnr = next(iter(per_fnr))
    return {"fnr": fnr, "antall_personer": 1,
            "grunnlag": f"Fastslått av {len(per_fnr[fnr])} dokument(er) "
                        "med samme fødselsnummer."}


def _ytelse(dokumenter: list) -> dict:
    """Ytelsen saken handler om — bare når dokumentene er ENIGE.

    To ulike ytelser i samme mappe betyr som regel at mappa er blandet,
    og da er «den første vi fant» et tilfeldig svar."""
    funnet = {}
    for dok in dokumenter:
        ytelse = dok.get("ytelse")
        kode = ytelse.get("kode") if isinstance(ytelse, dict) else ytelse
        if kode:
            funnet.setdefault(kode, ytelse if isinstance(ytelse, dict)
                              else {"kode": kode, "term": kode})
    if len(funnet) == 1:
        return next(iter(funnet.values()))
    return {"kode": None, "term": None}


def _siste_avgjorelse(dokumenter: list):
    """Avgjørelsen som gjelder — ikke det nyeste dokumentet.

    Klageinstansens vedtak går foran førsteinstansens uansett dato: det
    er hele poenget med en klageinstans. Blant like går det seneste
    foran (et omgjøringsvedtak)."""
    for typer in (("klagevedtak",), ("vedtak",)):
        treff = _datert(dokumenter, typer)
        if treff:
            dato, dok = treff[-1]
            return {"dato": dato, "type": dok.get("type"),
                    "dokument": _navn(dok)}
    return None


def _status(dokumenter: list, siste) -> dict:
    """Hvor saken står. En SLUTNING av hvilke typer som finnes og i
    hvilken rekkefølge — ikke et felt noen har skrevet i et dokument."""
    def sist(typer):
        treff = _datert(dokumenter, typer)
        return treff[-1][0] if treff else None

    if siste and _sakstype_av({"type": siste["type"]}) == "klagevedtak":
        return {"kode": "avgjort_etter_klage",
                "begrunnelse": "Klageinstansen har avgjort saken "
                               f"({siste['dato']})."}
    etterspurt = sist(("dokumentasjonskrav", "purring"))
    if etterspurt and (not siste or siste["dato"] < etterspurt):
        return {"kode": "venter_paa_dokumentasjon",
                "begrunnelse": f"Dokumentasjon ble etterspurt {etterspurt}, "
                               "og ingen avgjørelse er datert etter det."}
    if siste:
        return {"kode": "avgjort",
                "begrunnelse": f"Vedtak datert {siste['dato']}, og ingen "
                               "klage er avgjort etter det."}
    if _datert(dokumenter, ("soknad",)):
        return {"kode": "under_behandling",
                "begrunnelse": "Søknad finnes, men ingen avgjørelse."}
    return {"kode": "ukjent",
            "begrunnelse": "Ingen av dokumentene avgjør noe, og ingen "
                           "søknad er datert. Saken kan ikke plasseres."}


def _mangler(dokumenter: list) -> list:
    """Hva dokumentene MANGLER, samlet (R247). Bare de målte
    forventningene — et felt som ikke er målt, kan ikke mangle."""
    ut = []
    for dok in dokumenter:
        savnet = dok.get("mangler")
        if savnet:
            ut.append({"dokument": _navn(dok),
                       "type": _sakstype_av(dok) or None,
                       "mangler": list(savnet)})
    ut.sort(key=lambda m: str(m["dokument"]))
    return ut


def bygg_sammendrag(sak: dict, motsigelser: dict = None) -> dict:
    """Saken fortalt som én sak.

    Alt er utledet av felt som allerede er bevist; ingenting legges til.
    Feltene som er SLUTNINGER (`status`) sier det selv, og
    `saksopphav`-kartet merker dem `regel`."""
    dokumenter = [d for d in ((sak or {}).get("dokumenter") or [])
                  if isinstance(d, dict)]
    # `type` er med i tillegg til `hendelse`: termen er for et menneske,
    # koden for en maskin. Uten koden må en klient matche på tekst — og
    # «Klagevedtak» INNEHOLDER «Klage», så et delstrengsøk teller
    # klagevedtaket som en klage. Målt: svaret på «ble det klaget?» ga
    # både klagedatoen og klagevedtakets dato (R250).
    forlop = [{"dato": dato,
               "type": _sakstype_av(dok),
               "hendelse": (
                   (dok.get("type") or {}).get("term")
                   if isinstance(dok.get("type"), dict) else None)
                   or _sakstype_av(dok),
               "dokument": _navn(dok)}
              for dato, dok in _datert(dokumenter, FORLOPSTYPER)]
    siste = _siste_avgjorelse(dokumenter)
    status = _status(dokumenter, siste)
    funn = ((motsigelser or {}).get("funn") or [])
    return {
        "part": _part(dokumenter),
        "ytelse": _ytelse(dokumenter),
        "antall_dokumenter": len(dokumenter),
        # Sakens gang — bare typene som flytter saken. Notater og brev
        # er med i tidslinjen, ikke her: et sammendrag som gjentar alt
        # er ikke et sammendrag.
        "forlop": forlop,
        "klaget": bool(_datert(dokumenter, ("klage",))),
        "siste_avgjorelse": siste,
        "status": {"kode": status["kode"],
                   "term": STATUSER[status["kode"]],
                   "begrunnelse": status["begrunnelse"]},
        "mangler": _mangler(dokumenter),
        "antall_motsigelser": len(funn),
        "forklaring": (
            "Utledet av felt som allerede er bevist — ingen språkmodell "
            "er involvert. «status» er en SLUTNING av hvilke dokumenttyper "
            "som finnes og i hvilken rekkefølge; «siste_avgjorelse» er "
            "ikke nødvendigvis det nyeste dokumentet, for et notat "
            "avgjør ingenting."),
    }

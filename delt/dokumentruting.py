"""
Spørsmålet nevner ett dokument — da skal svaret komme derfra (R226).

En bunke er ikke ett dokument. Den syntetiske testbunken er sju:
vedtak (side 1–2), faktura (3), egenerklæring (4), legeerklæring (5),
inntektsmelding (6–8), klage (9) og returslipp (10). Modellen så alle
sammen som én lang tekst, og hentet svar fra feil dokument:

    «Hvilken paragraf i folketrygdlova viser KLAGEN til?»
        → paragraf 22-15   (fakturaens hjemmel, side 3 — klagens er 11-5)
    «Hvem er saksbehandler for KLAGEN?»
        → Kari Saksbehandler   (vedtakets saksbehandler, side 1)
    «Hvilken tittel har den som undertegnet VEDTAKET?»
        → Kari Saksbehandler   (navnet, ikke tittelen — med klagen i
                                konteksten som konkurrerende signatur)

Ingen av dem er oppdiktet. Alle er ekte verdier fra feil dokument, og
det er en feil en saksbehandler ikke kan se: svaret ser riktig ut.

SAMMENSATTE ORD ER IKKE DOKUMENTET
Rutingen utløses bare av ordet som står ALENE, med bøyning:
«klagen», «klagens», «klager». Ikke «klagefristen», ikke
«klageadgangen» — de to spør om et avsnitt i VEDTAKET, ikke om
klagebrevet, og begge var riktige før. En regel som bare lette etter
«klage» ville rutet dem til side 9 og gjort to riktige svar gale.

TRE VILKÅR, ELLERS SKJER INGENTING
  1. bunken har flere enn ett dokument
  2. spørsmålet nevner NØYAKTIG én dokumenttype — nevner det to
     («vedtaket som det klages på»), vet vi ikke hvilket det gjelder
  3. bunken har NØYAKTIG ett dokument av den typen — har den to
     fakturaer, er «fakturaen» flertydig, og en gjetning her ville vært
     den samme feilen vi retter

DATOENE TRENGS IKKE HER
`del_i_dokumenter` bruker to signaler: dokumentdato og tittel. Denne
modulen kaller den uten datoer, og det er med vilje — datoen skiller to
dokumenter av SAMME slag, og vilkår 3 nekter uansett å velge mellom to
av samme slag. Tittelen er signalet som svarer på «hvilken slags», og
det er det eneste rutingen spør om. Samme funksjon, ikke en kopi (R111).
"""
import re

# Ordformene som betyr DOKUMENTET, ikke et begrep i et annet dokument.
# Endelsene er bokmål og nynorsk: «klagen»/«klaga», «inntektsmeldingen»/
# «inntektsmeldinga». Ingen av mønstrene får treffe inn i et sammensatt
# ord — se modulens innledning for hva det kostet å prøve.
SPORSMAALSORD = {
    "vedtak": r"\bvedtak(?:et|ets)?\b",
    "faktura": r"\bfaktura(?:en|ens)?\b|\bregning(?:a|en|ens)?\b",
    "klage": r"\bklage(?:n|ns|a|as|r|rs|s)?\b",
    "egenerklaring": r"\begenerkl(?:æ|ae|a)ring(?:a|as|en|ens)?\b",
    "legeerklaring": r"\blegeerkl(?:æ|ae|a)ring(?:a|as|en|ens)?\b",
    "inntektsmelding": r"\binntektsmelding(?:a|as|en|ens)?\b",
    "returslipp": r"\breturslipp(?:en|ens)?\b",
    "sykmelding": r"\bsy[kj]kmelding(?:a|as|en|ens)?\b",
    "meldekort": r"\bmeldekort(?:et|ets)?\b",
    "soknad": r"\bs(?:ø|oe|o)knad(?:a|as|en|ens)?\b",
    "kvittering": r"\bkvittering(?:a|as|en|ens)?\b",
    "attest": r"\battest(?:a|en|ens)?\b",
}


def typer_i_sporsmal(sporsmal: str) -> list:
    """Dokumenttypene spørsmålet nevner som DOKUMENT."""
    lav = (sporsmal or "").lower()
    return [type_ for type_, monster in SPORSMAALSORD.items()
            if re.search(monster, lav)]


def _kode(dokument: dict) -> str:
    """Typekoden, uansett om feltet er en streng eller et kodeverkspar."""
    type_ = (dokument or {}).get("type")
    if isinstance(type_, dict):
        return type_.get("kode") or ""
    return type_ or ""


def rut(sporsmal: str, tekst: str) -> dict:
    """{type, sider, tittel} for dokumentet spørsmålet gjelder — ellers None.

    `tekst` er dokumentteksten med sidemarkørene («[Side i av n]») intakt;
    det er dem `del_i_dokumenter` deler på."""
    from delt.dokumentprofil import del_i_dokumenter

    typer = typer_i_sporsmal(sporsmal)
    if len(typer) != 1:
        return None
    try:
        dokumenter = del_i_dokumenter(tekst or "", None)
    except Exception:                                           # noqa: BLE001
        # Rutingen er en forbedring, ikke en forutsetning. Klarer vi
        # ikke å dele bunken, svarer vi som før — på hele.
        return None
    if len(dokumenter) < 2:
        return None
    treff = [d for d in dokumenter if _kode(d) == typer[0] and d.get("sider")]
    if len(treff) != 1:
        return None
    sider = sorted(treff[0]["sider"])
    if len(sider) >= sum(len(d.get("sider") or []) for d in dokumenter):
        return None                 # ingen innsnevring — ikke verdt å si fra
    return {"type": typer[0], "sider": sider,
            "tittel": treff[0].get("tittel")}

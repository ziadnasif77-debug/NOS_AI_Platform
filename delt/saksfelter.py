"""Saks-, økonomi- og arbeidsfelter fra NAV-dokumenter.

Alle uttrekkene her krever en EKSPLISITT etikett i dokumentet. Et tall
uten etikett blir aldri et vedtaksnummer, og et beløp uten etikett blir
aldri en dagsats — vi henter det som står merket, ikke det som kunne
passet. Finnes ikke etiketten, er svaret None, og en klient som ser
None vet at opplysningen ikke sto der.

Modulen ligger utenfor tekstuttrekk.py med vilje: den fila er allerede
stor nok til at det å finne noe i den er et arbeid i seg selv.
"""
import re

from delt.tekstuttrekk import _BELOP_TALL, _normaliser_belop, finn_dato

# Æøå skrives på tre måter i praksis: tegnet selv, ae/oe/aa (eldre
# systemer og norske tastaturløse skjemaer), og ren a/o (OCR som mister
# ringen og streken). Etikettene må kjenne igjen alle tre, ellers faller
# feltet stille bort på et dokument som ser helt normalt ut.
AA = r"(?:å|aa|a)"
OE = r"(?:ø|oe|o)"


# Etiketten må slutte der ordet slutter — men norsk bøyer i bestemt form
# og flertall, og dokumentene bruker begge deler: «Dagsatsen», «beløpet»,
# «satsene». Derfor godtas endelsene, men ikke noe annet: «stilling» får
# fortsatt IKKE treffe inne i «Stillingsprosent» (der ble
# stillingstittelen «sprosent: 80 %»).
_ORDSLUTT = r"(?:en|et|er|ene|ne|a|n)?(?![A-Za-zÆØÅæøå])"

# «Dagsatsen ER kr 1 234» og «beløpet UTGJØR 500» skriver seg naturlig
# på norsk. Uten et lite rom for bindeordet finner vi bare den knappe
# skjemaformen «Dagsats: 1 234», og mister den halve dokumentmengden
# som er skrevet i setninger.
_BINDEORD = r"(?:\s+(?:er|var|p" + AA + r"|utgj" + OE + r"r|blir|settes\s+til|"
_BINDEORD += r"med|lyder\s+p" + AA + r"))?"


def _merket(tekst: str, etiketter: str, verdi: str, flagg=re.IGNORECASE):
    """Verdien som står rett etter en av etikettene.

    Skilletegnet mellom etikett og verdi varierer mellom dokumenter
    (kolon, mellomrom, «nr.»), så det holdes løst — men etiketten selv
    må stå der, og den må stå HEL.

    Er ordet nevnt flere steder, vinner den forekomsten som ER en
    feltetikett: den som STARTER sin linje. Et skjema skriver
    «Inntektsmelding fra arbeidsgiver» som overskrift og «Arbeidsgiver»
    som feltnavn lenger nede — uten denne regelen tok vi overskriften
    og fikk linja under den som arbeidsgiver («Innsendt via Altinn
    28.04.2026 kl. 09:14»)."""
    monster = re.compile(
        r"(?:" + etiketter + r")" + _ORDSLUTT + _BINDEORD
        + r"\s*(?:nr\.?|nummer)?\s*[:.\-]?\s*(" + verdi + r")",
        flagg)
    tekst = tekst or ""
    reserve = None
    for treff in monster.finditer(tekst):
        linje_start = tekst.rfind("\n", 0, treff.start()) + 1
        if not tekst[linje_start:treff.start()].strip():
            return treff.group(1).strip()      # etiketten starter linja
        if reserve is None:
            reserve = treff.group(1).strip()
    return reserve


# Et tall etterfulgt av «prosent» eller «%» er en ANDEL, ikke et beløp.
# «du får utbetalt 100 prosent av dette» ga ellers utbetalt_belop = 100.
#
# «\b» bak markøren duger ikke: en ordgrense krever et ordtegn på den ene
# siden, og etter «%» kommer det som regel et mellomrom. «100 prosent av»
# ble derfor riktig avvist mens «100 % av» slapp gjennom som et beløp —
# halve fiksen virket. Nå kreves bare at markøren ikke fortsetter i et
# ord, slik at både «%», «prosent» og «pst.» stopper tallet.
_ANDEL_ETTER = re.compile(r"\s*(?:%|prosent|pst\.?)(?![a-zæøåA-ZÆØÅ0-9])",
                          re.IGNORECASE)


def _merket_belop(tekst: str, etiketter: str):
    """Beløpet som står rett etter en etikett, som tall. «Dagsats: kr
    1 234,00» og «dagsats 1234,-» skal gi det samme.

    Et tall som viser seg å være en PROSENTANDEL forkastes: en andel og
    en sum er ikke samme slags tall, og 100 kroner er ikke 100 prosent."""
    monster = re.compile(
        r"(?:" + etiketter + r")" + _ORDSLUTT
        + _BINDEORD + r"\s*[:.\-]?\s*(?:kr\.?|NOK)?\s*(" + _BELOP_TALL + r")",
        re.IGNORECASE)
    for treff in monster.finditer(tekst or ""):
        if _ANDEL_ETTER.match(tekst, treff.end()):
            continue
        return _normaliser_belop(treff.group(1))
    return None


def _merket_dato(tekst: str, etiketter: str):
    """Datoen som står rett etter en etikett, normalisert til
    dd.mm.åååå av den vanlige datoparseren."""
    treff = re.search(
        r"(?:" + etiketter + r")" + _ORDSLUTT + _BINDEORD
        + r"\s*[:.\-]?\s*([0-9]{1,2}[.\-/ ][0-9]{1,2}"
        r"[.\-/ ][0-9]{2,4}|[0-9]{1,2}\.?\s+\w+\s+[0-9]{4})",
        tekst or "", re.IGNORECASE)
    return finn_dato(treff.group(1)) if treff else None


# ------------------------------------------------------------------ #
#  Sak                                                                 #
# ------------------------------------------------------------------ #

_SAKSNUMMERFORM = r"[0-9]{2,4}/[0-9]{3,6}|[0-9]{4,12}"


def finn_journalnummer(tekst: str):
    """«Journalnummer: 2026001234», «Jnr 12/3456», «Journalpost 998877»."""
    return _merket(tekst, r"journalnummer|journalnr\.?|journalpost|\bjnr\b",
                   _SAKSNUMMERFORM)


def finn_vedtaksnummer(tekst: str):
    """Vedtakets eget nummer — ikke saksnummeret. Et vedtak kan være ett
    av flere i samme sak, og de to forveksles lett."""
    return _merket(tekst, r"vedtaksnummer|vedtaksnr\.?|vedtak\s+nr\.?",
                   _SAKSNUMMERFORM)


def finn_dokumentnummer(tekst: str):
    return _merket(tekst, r"dokumentnummer|dokumentnr\.?|dok\.?nr\.?",
                   _SAKSNUMMERFORM)


def finn_referanse(tekst: str):
    """«Vår referanse», «Deres ref», «Referanse». Vår/deres skilles ikke
    her — den som trenger forskjellen, ser på dokumentet."""
    return _merket(
        tekst,
        r"v" + AA + r"r\s+referanse|v" + AA + r"r\s+ref\.?|deres\s+referanse|"
        r"deres\s+ref\.?|referansenummer|\breferanse\b",
        r"[A-Za-z0-9][A-Za-z0-9/\-]{2,30}")


def sak_felter(tekst: str) -> dict:
    return {
        "journalnummer": finn_journalnummer(tekst),
        "vedtaksnummer": finn_vedtaksnummer(tekst),
        "dokumentnummer": finn_dokumentnummer(tekst),
        "referanse": finn_referanse(tekst),
    }


# ------------------------------------------------------------------ #
#  Økonomi                                                             #
# ------------------------------------------------------------------ #

def finn_dagsats(tekst: str):
    return _merket_belop(tekst, r"dagsats|dagsatsen|sats\s+per\s+dag|bel"
                                + OE + r"p\s+per\s+dag")


def finn_manedsbelop(tekst: str):
    return _merket_belop(
        tekst,
        r"m" + AA + r"nedsbel" + OE + r"p"
        + r"|m" + AA + r"nedlig\s+bel" + OE + r"p"
        + r"|bel" + OE + r"p\s+per\s+m" + AA + r"ned"
        + r"|per\s+m" + AA + r"ned"
        + r"|m" + AA + r"nedlig\s+utbetaling"
        + r"|m" + AA + r"nedss?ats")


def finn_utbetalt_belop(tekst: str):
    return _merket_belop(
        tekst,
        r"utbetalt\s+bel" + OE + r"p"
        + r"|utbetalingsbel" + OE + r"p"
        + r"|til\s+utbetaling"
        + r"|utbetalt|utbetales")


def finn_tilbakebetaling(tekst: str):
    """Krav den andre veien. Blandes dette med utbetalt beløp, snur
    fortegnet på hele saken."""
    return _merket_belop(
        tekst, r"tilbakebetaling|tilbakebetalings?bel" + OE + r"p|"
               r"krever\s+tilbake|skyldig\s+bel" + OE + r"p|restbel" + OE + r"p")


def okonomi_felter(tekst: str) -> dict:
    return {
        "dagsats": finn_dagsats(tekst),
        "manedsbelop": finn_manedsbelop(tekst),
        "utbetalt_belop": finn_utbetalt_belop(tekst),
        "tilbakebetalingsbelop": finn_tilbakebetaling(tekst),
        "utbetalingsdato": _merket_dato(
            tekst, r"utbetalingsdato|utbetales\s+den|utbetalt\s+den"),
    }


# ------------------------------------------------------------------ #
#  Arbeid og inntekt                                                   #
# ------------------------------------------------------------------ #

# Et virksomhetsnavn: ord med stor forbokstav, eventuelt med
# selskapsform bak. Stopper ved komma, linjeskift eller «Org».
_VIRKSOMHET = r"[A-ZÆØÅ0-9][^\n,;]{1,58}?(?=\s*(?:,|\n|$|[Oo]rg\.?\s?nr))"


def finn_arbeidsgiver(tekst: str):
    return _merket(tekst, r"arbeidsgiver|arbeidsgivers?\s+navn|"
                          r"virksomhet|bedrift|foretak", _VIRKSOMHET)


def finn_stilling(tekst: str):
    return _merket(tekst, r"stilling|stillingstittel|\byrke\b|"
                          r"stillingsbetegnelse", r"[A-Za-zÆØÅæøå][^\n,;]{1,48}")


def finn_stillingsprosent(tekst: str):
    """«Stillingsprosent: 80 %», «80% stilling», «stillingsandel 60»."""
    treff = re.search(
        r"(?:stillingsprosent|stillingsandel|stillingsst" + OE + r"rrelse)"
        r"\s*[:.\-]?\s*(\d{1,3})\s*%?",
        tekst or "", re.IGNORECASE)
    if treff:
        prosent = int(treff.group(1))
        return prosent if 0 < prosent <= 100 else None
    treff = re.search(r"\b(\d{1,3})\s*%\s*stilling\b", tekst or "",
                      re.IGNORECASE)
    if treff:
        prosent = int(treff.group(1))
        return prosent if 0 < prosent <= 100 else None
    return None


def finn_inntekt(tekst: str) -> dict:
    """Årsinntekt og månedslønn hver for seg. Å slå dem sammen til ett
    «inntekt»-felt gjør en årslønn og en månedslønn til samme tall."""
    return {
        "arsinntekt": _merket_belop(
            tekst,
            AA + r"rsinntekt"
            + r"|" + AA + r"rsl" + OE + r"nn"
            + r"|inntekt\s+per\s+" + AA + r"r"
            + r"|brutto\s+" + AA + r"rsinntekt"),
        "manedslonn": _merket_belop(
            tekst,
            r"m" + AA + r"nedsl" + OE + r"nn"
            + r"|l" + OE + r"nn\s+per\s+m" + AA + r"ned"
            + r"|brutto\s+m" + AA + r"nedsl" + OE + r"nn"),
    }


def arbeid_felter(tekst: str) -> dict:
    inntekt = finn_inntekt(tekst)
    return {
        "arbeidsgiver": finn_arbeidsgiver(tekst),
        "stilling": finn_stilling(tekst),
        "stillingsprosent": finn_stillingsprosent(tekst),
        "startdato": _merket_dato(
            tekst, r"startdato|ansatt\s+fra|tiltr" + AA + r"dt|ansettelsesdato|"
                   r"arbeidsforhold\s+fra"),
        "sluttdato": _merket_dato(
            tekst, r"sluttdato|fratr" + AA + r"dt|siste\s+arbeidsdag|"
                   r"arbeidsforhold\s+til|opph" + OE + r"rsdato"),
        "arsinntekt": inntekt["arsinntekt"],
        "manedslonn": inntekt["manedslonn"],
    }

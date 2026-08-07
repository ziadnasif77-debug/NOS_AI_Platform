"""
Deterministisk feltuttrekk fra OCR-tekst — ingen modeller, kun mønstre
og sjekksummer. For strukturerte felter (fødselsnummer, kontonummer,
datoer, telefon) er dette MER presist enn NER: mod11 er matematikk,
ikke gjetning.

Brukes av NLPWorker som et lag OVER modell-uttrekket:
    entiteter = utvid_entiteter(tekst, ner_entiteter)
Deterministiske treff vinner for strukturerte felter; modellene vinner
for navn (fritekst uten fast mønster).
"""
import bisect
import os
import re
import threading
from datetime import date, datetime

from delt.konstanter import (NAV_TEMA, NORSKE_FYLKER, NORSKE_YTELSER,
                             YTELSE_TEMA, YTELSE_TERM)

# Versjon av det deterministiske regelverket. Bumpes når mønstre/vakter
# endres, så hvert svar kan spores til reglene som produserte det (§4).
# u2: R61 — beløp med internasjonalt punktum-desimalformat («6380.00»)
# u3: R62 — finn_belop fanger beløp der etikett og tall står på hver sin
#     linje («Total Kr:\n486,00»), likt finn_alle_belop
# u4: nytt felt «totalbelop» — beløpet på en Total-/Sum-/Å betale-linje.
#     Additivt: «belop» (første beløp) er URØRT, fordi hvilket beløp som
#     er riktig avhenger av dokumentet. Klienten velger.
# u5: «organisasjonsnummer» og «kid» eksponeres som felter/plassholdere.
#     Begge var mod11-validerte fra før, men manglet i felter_flatt — en
#     mal måtte derfor be MODELLEN om noe koden kunne BEVISE.
# u6: målt på en 10-siders syntetisk NAV-bunke (vedtak+faktura+skjema+
#     legeerklæring+inntektsmelding+klage): merket saksnummer vinner over
#     NAV-skjemakode; Postboks-nummer er ikke postnummer; telefon fanger
#     3-2-3-mobilform og avviser fakturanummer-etikett; merket kontonummer
#     vinner over fnr-presedens når begge sjekksummer stemmer; totalbelop
#     «beløp å betale» + tabellrad faller ikke videre til neste linje;
#     nytt felt forfallsdato.
UTTREKK_REGEL_VERSJON = "u6"

# Versjon av den deterministiske malfletteren (flett_mal). Skilt fra
# uttrekksreglene fordi flettingen kan endres uavhengig av hvordan de
# enkelte feltene finnes. f1: første utgave — {feltnavn}-plassholdere
# fylt fra felter_flatt, uten modell.
FLETT_REGEL_VERSJON = "f1"

# ------------------------------------------------------------------ #
#  Sjekksummer (mod11)                                                 #
# ------------------------------------------------------------------ #

_FNR_VEKTER1 = [3, 7, 6, 1, 8, 9, 4, 5, 2]
_FNR_VEKTER2 = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
_KONTO_VEKTER = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]


def _mod11_kontroll(sifre: str, vekter: list) -> int:
    s = sum(int(sifre[i]) * v for i, v in enumerate(vekter))
    r = 11 - (s % 11)
    return 0 if r == 11 else r


def er_gyldig_fnr(fnr: str) -> bool:
    """Norsk fødselsnummer: 11 sifre med to mod11-kontrollsifre."""
    if not fnr or not fnr.isdigit() or len(fnr) != 11:
        return False
    k1 = _mod11_kontroll(fnr, _FNR_VEKTER1)
    k2 = _mod11_kontroll(fnr, _FNR_VEKTER2)
    if k1 == 10 or k2 == 10:
        return False
    return k1 == int(fnr[9]) and k2 == int(fnr[10])


def er_gyldig_kontonummer(konto: str) -> bool:
    """Norsk bankkontonummer: 11 sifre med ett mod11-kontrollsiffer."""
    if not konto or not konto.isdigit() or len(konto) != 11:
        return False
    k = _mod11_kontroll(konto, _KONTO_VEKTER)
    return k != 10 and k == int(konto[10])


# ------------------------------------------------------------------ #
#  Enkeltfelt-uttrekk                                                  #
# ------------------------------------------------------------------ #

def finn_fodselsnummer(tekst: str):
    """11 sifre (ev. med mellomrom etter posisjon 6) som består mod11.

    ETIKETTEN foran avgjør når tallet består BEGGE sjekksummene — samme
    regel som flertallsvarianten bruker. Uten den rapporterte denne
    funksjonen refusjonskontoen som fødselsnummer, mens
    `struktur.identifikatorer` sa kontonummer om nøyaktig samme tall i
    samme svar. Verdien gikk dessuten videre inn i skjemautfyllingen via
    `felter_flatt`, der `{fodselsnummer}` da ble fylt med et kontonummer."""
    for treff in re.finditer(r"\b(\d{6})[ ]?(\d{5})\b", tekst):
        kandidat = treff.group(1) + treff.group(2)
        if _ellevesiffer_type(tekst, treff.start(), kandidat) == "fodselsnummer":
            return kandidat
    return None


def finn_kontonummer(tekst: str):
    """11 sifre, ev. formatert dddd.dd.ddddd, som består konto-mod11.

    Samme etikettregel som over: et dobbeltgyldig tall under
    «Kontonummer:» ER et kontonummer. Før dette hoppet funksjonen over
    ALLE fnr-gyldige tall, så en merket refusjonskonto forsvant helt."""
    for treff in re.finditer(r"\b(\d{4})[. ]?(\d{2})[. ]?(\d{5})\b", tekst):
        kandidat = "".join(treff.groups())
        if _ellevesiffer_type(tekst, treff.start(), kandidat) == "kontonummer":
            return kandidat
    return None


_MAANEDER = {
    "januar": 1, "februar": 2, "mars": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "desember": 12,
}

# Engelske månedsnavn — dokumenter i arkivet er ikke alltid norske.
# (april/august/september/november staves likt på begge språk.)
_MAANEDER_EN = {
    "january": 1, "february": 2, "march": 3, "may": 5, "june": 6,
    "july": 7, "october": 10, "december": 12,
}
_ALLE_MAANEDER = {**_MAANEDER, **_MAANEDER_EN}


def iso(d: int, m: int, y: int) -> str:
    """Den ENE normaliserte datoformen i hele prosjektet: ISO 8601.

    Alle datoverdier bygges her. Grunnen til at det er ett sted: så
    lenge formen ble skrevet ut med f-streng på fem steder, kunne et
    nytt uttrekk nummer seks lett få en annen form uten at noe sa fra.

    ISO og ikke dd.mm.åååå av tre grunner som alle er målbare, ikke
    smakssaker:
      1) Den sorterer riktig som REN TEKST. `sorted()` på dd.mm.åååå
         sorterer på dagen først, altså på ingenting.
      2) `date.fromisoformat` leser den; dd.mm.åååå krever egen parser
         i hver klient.
      3) Den er entydig. 03.04.2026 er 3. april for en nordmann og
         4. mars for en amerikaner — og klientene her er roboter som
         ikke vet hvilken de leser.

    Presentasjon er en ANNEN sak: `til_norsk()` renderer for menneske-
    øyne der det trengs (utfylte skjemaer). Det er en renderer på
    kanten, ikke et tvillingfelt i svaret (R110)."""
    return f"{y:04d}-{m:02d}-{d:02d}"


def til_norsk(dato_iso):
    """«2026-03-04» → «04.03.2026». For PRESENTASJON — aldri for et
    felt i API-svaret.

    Eneste lovlige bruk er der utdataet leses av et menneske eller
    skrives inn i et norsk skjemafelt som selv sier «dd.mm.åååå». Dukker
    denne opp i en svarbygger, er det en R110-tvilling."""
    try:
        aar, maaned, dag = (int(x) for x in str(dato_iso).split("-"))
        return f"{dag:02d}.{maaned:02d}.{aar:04d}"
    except (ValueError, TypeError, AttributeError):
        return None


def finn_dato(tekst: str):
    """Første gyldige dato — numeriske formater og «12. januar 2020».
    Normaliseres til ISO 8601 (se `iso`)."""
    for treff in re.finditer(
            r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)", tekst):
        d, m, y = int(treff.group(1)), int(treff.group(2)), int(treff.group(3))
        if _gyldig_dato(d, m, y):
            return iso(d, m, y)
    for treff in re.finditer(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", tekst):
        y, m, d = int(treff.group(1)), int(treff.group(2)), int(treff.group(3))
        if _gyldig_dato(d, m, y):
            return iso(d, m, y)
    maaneder = "|".join(_MAANEDER)
    for treff in re.finditer(
        rf"(?<!\d)(\d{{1,2}})[.\s]+({maaneder})[.\s]+(\d{{4}})(?!\d)",
        tekst, re.IGNORECASE
    ):
        d = int(treff.group(1))
        m = _MAANEDER[treff.group(2).lower()]
        y = int(treff.group(3))
        if _gyldig_dato(d, m, y):
            return iso(d, m, y)
    return None


def _antatt_aar(yy: int) -> int:
    """Tosifret år → firesifret med dokumentert pivot: til og med
    inneværende års to siste sifre tolkes som 20xx, ellers 19xx."""
    pivot = datetime.utcnow().year % 100
    return 2000 + yy if yy <= pivot else 1900 + yy


def _alle_datotreff(tekst: str) -> list:
    """ÉN generell datodetektor for alle vanlige formater: numerisk med
    to- eller firesifret år, ISO, og norske/engelske månedsnavn.

    Returnerer sortert liste av
    (start, slutt, raatekst, normalisert ISO 8601, aar_antatt) der
    aar_antatt=True betyr at århundret er antatt (tosifret år) — en
    deklarert antagelse, ikke et faktum."""
    funn = []

    def _legg_til(treff, d, m, y, aar_antatt=False):
        if _gyldig_dato(d, m, y):
            funn.append((treff.start(), treff.end(), treff.group(0),
                         iso(d, m, y), aar_antatt))

    # Numerisk, firesifret år: 12.03.2024, 12/3/2024 — og OCR-varianter
    # med mellomrom rundt skilletegnene («21.04 . 1994»).
    # R61: ytre (?<!\d)/(?!\d) i stedet for \b. På kvitteringer limer OCR
    # ofte datoen til nabotekst («12.06.2026kr», «DATO12.06.2026»,
    # «12.06.2026KL14:46»); \b fant ingen ordgrense mellom to bokstaver/
    # sifre og forkastet en fullt lesbar dato i det stille. Lookarounds
    # forbyr bare SIFFER-naboer (så «2026» aldri plukkes ut av «20261234»),
    # men tillater bokstav-naboer.
    for treff in re.finditer(
        r"(?<!\d)(\d{1,2})[ ]*[./][ ]*(\d{1,2})[ ]*[./][ ]*(\d{4})(?!\d)", tekst
    ):
        _legg_til(treff, int(treff.group(1)), int(treff.group(2)),
                  int(treff.group(3)))
    # Numerisk, tosifret år: 01.06.94 (århundre antas, flagges)
    for treff in re.finditer(
        r"(?<!\d)(\d{1,2})[ ]*[./][ ]*(\d{1,2})[ ]*[./][ ]*(\d{2})(?!\d)", tekst
    ):
        _legg_til(treff, int(treff.group(1)), int(treff.group(2)),
                  _antatt_aar(int(treff.group(3))), aar_antatt=True)
    # ISO: 2024-03-12
    for treff in re.finditer(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", tekst):
        _legg_til(treff, int(treff.group(3)), int(treff.group(2)),
                  int(treff.group(1)))
    # Månedsnavn, norsk/engelsk: «12. mars 2024» / «March 12, 2024».
    # R61: [.\s]+ i stedet for \s+ rundt måneden, så «08.juni 2026» og
    # «8.juni.2026» (OCR mister mellomrommet) også fanges — månedsnavnet
    # er selv et sterkt anker, så falske treff er usannsynlige.
    maaneder = "|".join(_ALLE_MAANEDER)
    for treff in re.finditer(
        rf"(?<!\d)(\d{{1,2}})[.\s]+({maaneder})[.\s]+(\d{{4}})(?!\d)",
        tekst, re.IGNORECASE
    ):
        _legg_til(treff, int(treff.group(1)),
                  _ALLE_MAANEDER[treff.group(2).lower()], int(treff.group(3)))
    for treff in re.finditer(
        rf"\b({maaneder})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", tekst, re.IGNORECASE
    ):
        _legg_til(treff, int(treff.group(2)),
                  _ALLE_MAANEDER[treff.group(1).lower()], int(treff.group(3)))

    funn.sort(key=lambda t: t[0])
    return funn


def finn_alle_datoer(tekst: str, maks: int = 100) -> list:
    """ALLE gyldige datoer i teksten — normalisert til ISO 8601, i
    tekstrekkefølge, uten duplikater. Forstår numeriske formater, ISO,
    norske OG engelske månedsnavn («12 March 2024», «March 12, 2024»).
    Deterministisk og rask nok for dokumenter på hundrevis av sider."""
    ut, sett = [], set()
    for _, _, _, dato, _ in _alle_datotreff(tekst):
        if dato not in sett:
            sett.add(dato)
            ut.append(dato)
        if len(ut) >= maks:
            break
    return ut


# Etiketter som forteller hva en dato ER — mest spesifikke først.
# Generisk «dato» står sist så den bare treffer når intet annet passer.
# [øo]-varianter fordi OCR ofte leser ø som o
_DATO_ETIKETTER = [
    (r"f[øo]ds?elsdato|f[øo]dt", "fodselsdato"),
    (r"frist|innen|senest", "frist"),
    (r"vedtaksdato|vedtak\s+av", "vedtaksdato"),
    (r"s[øo]knadsdato|s[øo]knad\s+datert", "soknadsdato"),
    (r"mottatt", "mottatt"),
    (r"sendt", "sendt"),
    (r"utstedt|utstedelsesdato", "utstedt"),
    # eksplisitt merking av DOKUMENTETS egen dato («Brevet er datert ...»).
    # Står etter søknadsdato, så «søknad datert» fortsatt blir søknadsdato.
    (r"dokumentdato|brevdato|datert", "dokumentdato"),
    (r"gyldig\s+til|utl[øo]per|utl[øo]psdato", "utlop"),
    (r"gyldig\s+fra", "gyldig_fra"),
    (r"avreise", "avreise"),
    (r"ankomst", "ankomst"),
    (r"signert|underskrift|signatur", "signaturdato"),
    (r"betalingsdato|utbetalt|utbetaling|betalt", "utbetalingsdato"),
    (r"arkivert|journalf[øo]rt", "arkivert"),
    (r"periode|fra\s+og\s+med|f\.o\.m", "periode_start"),
    (r"til\s+og\s+med|t\.o\.m", "periode_slutt"),
    (r"dato", "merket_dato"),
]


# ------------------------------------------------------------------ #
#  Dokumentets EGEN dato kontra datoer i innholdet
# ------------------------------------------------------------------ #
# Et dokument har én dato som er DOKUMENTETS (da det ble skrevet, fattet,
# signert, utstedt). Alle andre datoer er noe dokumentet HANDLER OM: en
# frist, en periode, en fødselsdato. Blandes de sammen, svarer systemet
# «01.07.2026» på «når er brevet fra?» fordi det var fristen som sto der.
# Derfor får hver dato en ROLLE, og dokumentdatoen velges deterministisk
# etter en rangstige — aldri av modellen.
ROLLE_DOKUMENT = "dokument"      # dokumentets egen dato
ROLLE_INNHOLD = "innhold"        # noe dokumentet handler om
ROLLE_BEHANDLING = "behandling"  # håndteringen AV dokumentet (mottatt/arkivert)
ROLLE_UKJENT = "ukjent"

_ROLLER = {
    # dokumentets egen dato
    "dokumentdato": ROLLE_DOKUMENT,
    "vedtaksdato": ROLLE_DOKUMENT,
    "utstedt": ROLLE_DOKUMENT,
    "signaturdato": ROLLE_DOKUMENT,
    "soknadsdato": ROLLE_DOKUMENT,
    "brevdato_sannsynlig": ROLLE_DOKUMENT,
    "signaturdato_sannsynlig": ROLLE_DOKUMENT,
    "sendt": ROLLE_DOKUMENT,
    "merket_dato": ROLLE_DOKUMENT,
    "pdf_opprettet": ROLLE_DOKUMENT,
    "pdf_endret": ROLLE_DOKUMENT,
    # håndtering: sier når NOEN GJORDE noe med dokumentet, ikke når det ble til
    "mottatt": ROLLE_BEHANDLING,
    "arkivert": ROLLE_BEHANDLING,
    # innhold: noe dokumentet forteller om
    "fodselsdato": ROLLE_INNHOLD,
    "fodselsdato_fra_fnr": ROLLE_INNHOLD,
    "frist": ROLLE_INNHOLD,
    "utlop": ROLLE_INNHOLD,
    "gyldig_fra": ROLLE_INNHOLD,
    "avreise": ROLLE_INNHOLD,
    "ankomst": ROLLE_INNHOLD,
    "periode_start": ROLLE_INNHOLD,
    "periode_slutt": ROLLE_INNHOLD,
    "utbetalingsdato": ROLLE_INNHOLD,
    "i_lopende_tekst": ROLLE_INNHOLD,
    "ukjent": ROLLE_UKJENT,
}

# Rangstige for dokumentdatoen: lavere tall vinner. En EKSPLISITT etikett
# («Vedtaksdato:») slår alltid en posisjonsgjetning, som igjen slår
# PDF-metadata — metadata er filens dato, ikke nødvendigvis dokumentets.
_DOKUMENTDATO_RANG = {
    "dokumentdato": (1, "etikett"),
    "vedtaksdato": (1, "etikett"),
    "utstedt": (1, "etikett"),
    "signaturdato": (1, "etikett"),
    "soknadsdato": (1, "etikett"),
    "sendt": (2, "etikett"),
    "brevdato_sannsynlig": (2, "posisjon"),
    "signaturdato_sannsynlig": (2, "posisjon"),
    "merket_dato": (3, "etikett"),
    "pdf_opprettet": (4, "pdf_metadata"),
    "pdf_endret": (5, "pdf_metadata"),
}

# Ord som røper en SIGNATURBLOKK. De står typisk RUNDT eller ETTER datoen
# («Oslo, 12.06.2026 … Ola Nordmann (sign.)»), og fanges derfor ikke av
# etikettsøket, som bare ser 35 tegn FORAN datoen.
_SIGNATUR_ORD = re.compile(
    r"\(?\bsign\b\.?\)?|signatur|underskrift|underskrevet|underteg|"
    r"med\s+vennlig\s+hilsen|\bmvh\b|vennlig\s+hilsen|"
    r"sted\s*[/og]{1,2}\s*dato|dato\s*[/og]{1,2}\s*sted",
    re.IGNORECASE)

# «Oslo, 12.06.2026» — norsk konvensjon i både brevhode og signaturblokk.
# Stedsnavnet rett før datoen er i seg selv et sterkt signal om at datoen
# gjelder DOKUMENTET, ikke noe det handler om.
_STED_FORAN_DATO = re.compile(r"[A-ZÆØÅ][a-zæøåA-ZÆØÅ\- ]{1,25},\s*$")
_RANG_KONFIDENS = {1: "hoy", 2: "middels", 3: "middels", 4: "lav", 5: "lav"}


# Lesbare beskrivelser (term) for hver datotype og rolle. Ideen fra NAVs
# AAREG-API: en kategoriverdi er et PAR {kode, term} — koden er stabil og
# maskinlesbar, termen er for et menneske. En klient kan forgrene på
# «vedtaksdato» uten å hardkode en norsk streng, og samtidig vise en
# forklaring i et grensesnitt uten å bygge sin egen oversettelsestabell.
_TYPE_TERM = {
    "dokumentdato": "Dokumentets dato",
    "vedtaksdato": "Vedtaksdato",
    "utstedt": "Utstedelsesdato",
    "signaturdato": "Signaturdato",
    "signaturdato_sannsynlig": "Sannsynlig signaturdato (ved underskrift)",
    "soknadsdato": "Søknadsdato",
    "brevdato_sannsynlig": "Sannsynlig brevdato (øverst i dokumentet)",
    "sendt": "Sendt-dato",
    "mottatt": "Mottatt-dato",
    "arkivert": "Arkivert-dato",
    "merket_dato": "Dato merket «dato»",
    "frist": "Frist",
    "utlop": "Utløpsdato",
    "gyldig_fra": "Gyldig fra",
    "avreise": "Avreisedato",
    "ankomst": "Ankomstdato",
    "periode_start": "Periodestart",
    "periode_slutt": "Periodeslutt",
    "utbetalingsdato": "Utbetalingsdato",
    "fodselsdato": "Fødselsdato",
    "fodselsdato_fra_fnr": "Fødselsdato (avledet fra fødselsnummer)",
    "i_lopende_tekst": "Dato i løpende tekst",
    "pdf_opprettet": "PDF opprettet (metadata)",
    "pdf_endret": "PDF endret (metadata)",
    "ukjent": "Ukjent",
}
_ROLLE_TERM = {
    ROLLE_DOKUMENT: "Dokumentets egen dato",
    ROLLE_INNHOLD: "Dato i innholdet (noe dokumentet handler om)",
    ROLLE_BEHANDLING: "Dato for håndtering av dokumentet",
    ROLLE_UKJENT: "Ukjent rolle",
}


def kodeverk(kode, tabell) -> dict:
    """{kode, term}-par for en kategoriverdi (AAREG-stil). Ukjent kode gir
    kode som term, så en ny type aldri mangler en lesbar verdi.

    Uten kode returneres PARET med to null-verdier — ikke None. Det er
    ikke pedanteri: klientene er RPA-roboter som mapper felt blindt og
    leser `dokument.type.kode` direkte. Er `type` null, finnes stien
    ikke, og roboten krasjer på dokument nummer to. Et par med
    `kode: null` betyr «typen er ikke fastslått», og det står i
    dokumentasjonen (R118)."""
    if kode is None:
        return {"kode": None, "term": None}
    return {"kode": kode, "term": tabell.get(kode, str(kode))}


def ytelse_kodet(navn) -> dict:
    """{kode, term} for en ytelse, der KODEN er NAVs offisielle temakode.

    Ute i svaret skal det stå `{"kode": "SYK", "term": "Sykepenger"}` —
    ikke vår interne streng «sykepenger». Temakoden er det andre
    NAV-systemer snakker; en RPA-robot som ruter dokumenter videre kan
    slå den opp i sitt eget kodeverk, mens et norsk substantiv fra vår
    tekstgjenkjenning bare er vårt.

    Det norske ordet forsvinner IKKE av den grunn — det brukes fortsatt
    internt til kapitteloppslaget i `lover.py` (`sok_ytelse("SYK")` ville
    truffet både kapittel 8 og 9 og vært flertydig) og til å finne siden
    ordet står på i `opphav`. Koden går ut, ordet blir igjen.

    `term` beskriver ALLTID `kode` — aldri noe annet (R134). Tidligere
    betydde feltet to ting avhengig av dataene: temaets navn når det
    fantes en kode, og den SPESIFIKKE ytelsens navn når det ikke gjorde
    det. Et felt hvis betydning varierer med innholdet kan en klient
    ikke lese uten å kjenne innholdet først.

    Hvilken ytelse dokumentet faktisk navngir, står i `betegnelse()` —
    et eget felt, fordi det er en egen opplysning. Temakoden er BEVISST
    mange-til-én (`uforepensjon` og `uforetrygd` er begge UFO), så
    temanavnet kan umulig også bære den."""
    if not navn:
        return {"kode": None, "term": None}
    tema = YTELSE_TEMA.get(navn)
    if not tema:
        # Kjent ytelse uten temakode ennå: NAVs liste er levert
        # stykkevis. `betegnelse` er fylt, koden tom — og de to sammen
        # skiller «forsto ytelsen, mangler koden» fra «fant ingen
        # ytelse» uten å måtte lyve om hva `term` beskriver (R127).
        return {"kode": None, "term": None}
    return {"kode": tema, "term": NAV_TEMA.get(tema, tema)}


def ytelse_betegnelse(navn):
    """Ytelsen slik den heter — ikke temaet den rutes under.

    Målt: 16 av våre 25 ytelser deler tema med en annen, og fikk derfor
    en annen betegnelse enn dokumentets egen. To av dem var direkte
    gale, ikke bare upresise:

      · `uforepensjon` (1966-loven) ble meldt som «Uføretrygd» — en
        ytelse som ikke fantes før 1997 — SAMTIDIG som svaret sa
        `gjeldende_lov: ftrl-1966`. Svaret motsa seg selv.
      · `etterlattepensjon` ble meldt som «Omstillingsstønad», som kom
        i 2024. Et dokument fra 1970-tallet fikk altså navnet på en
        ytelse som ennå ikke er femti år yngre enn det selv.

    De tre kapittel 9-ytelsene delte betegnelsen «Omsorgspenger,
    pleiepenger og opplæringspenger», så et vedtak om pleiepenger ikke
    kunne skilles fra ett om opplæringspenger — ulike vilkår, ulike
    paragrafer.

    Betegnelsen bærer de historiske merkene fra `YTELSE_TERM`
    («(1966-loven; i dag uføretrygd)»), som er nettopp det en
    saksbehandler trenger for ikke å lese et gammelt vedtak som om det
    gjaldt dagens regelverk."""
    if not navn:
        return None
    return YTELSE_TERM.get(navn, str(navn))


def rolle_for_type(dtype) -> str:
    """Rollen til en datotype. Ukjente typer (egne etiketter uten oppgitt
    rolle) regnes som INNHOLD — en ny etikett navngir nesten alltid noe
    dokumentet handler om, og å gjette «dokumentdato» ville vært å la en
    tilfeldig etikett kuppe selve dokumentdatoen."""
    if not dtype:
        return ROLLE_UKJENT
    return _ROLLER.get(dtype, _egne_roller().get(dtype, ROLLE_INNHOLD))


def sett_dato_roller(datoer: list) -> list:
    """Merker hver klassifiserte dato med «rolle», og med de kodede
    parene «type_kodet»/«rolle_kodet» {kode, term} (AAREG-stil). De rå
    strengfeltene «type» og «rolle» beholdes uendret, så ingen klient
    brytes — de kodede feltene kommer i tillegg. Muterer og returnerer
    lista (praktisk i kjeder)."""
    for d in datoer:
        if isinstance(d, dict):
            rolle = rolle_for_type(d.get("type"))
            d["rolle"] = rolle
            d["type_kodet"] = kodeverk(d.get("type"), _TYPE_TERM)
            d["rolle_kodet"] = kodeverk(rolle, _ROLLE_TERM)
    return datoer


def _til_dato(dato_str):
    """ISO 8601 → date, eller None hvis den ikke lar seg lese.

    Med VILJE streng: den godtar ikke dd.mm.åååå «for sikkerhets
    skyld». Slapp den begge former gjennom, ville en gjenglemt norsk
    verdi et sted i koden fortsatt regne riktig her — og feilen ville
    først dukke opp ute i svaret, der den er dyrest å finne."""
    try:
        a, m, d = (int(x) for x in str(dato_str).split("-"))
        return date(a, m, d)
    except (ValueError, TypeError, AttributeError):
        return None


def fodselsdato_av_fnr(fnr: str):
    """(dag, måned, år) fra et fødselsnummer — eller None.

    Århundret ligger i INDIVIDSIFRENE, ikke i årstallet alene, og
    dokumentprofilen hadde en egen kopi som hardkodet `1900 + år`. Den
    ga altså feil århundre for ALLE født etter 1999 — en gjetning
    presentert som et faktum. Én regel, ett sted.

    Månedstillegg håndteres også: +80 er syntetiske testnumre (Tenor),
    og dag +40 er D-nummer."""
    if not fnr or len(fnr) != 11 or not fnr.isdigit():
        return None
    dag, maaned, aa = int(fnr[0:2]), int(fnr[2:4]), int(fnr[4:6])
    individ = int(fnr[6:9])
    if maaned > 80:
        maaned -= 80            # syntetisk testnummer
    if dag > 40:
        dag -= 40               # D-nummer
    if not (1 <= dag <= 31 and 1 <= maaned <= 12):
        return None
    # Individsifrene bestemmer århundret (forenklet, men langt riktigere
    # enn å anta 1900 for alle)
    if individ >= 500 and aa <= 39:
        aar = 2000 + aa
    elif individ >= 500 and aa >= 54:
        aar = 1800 + aa
    else:
        aar = 1900 + aa
    return dag, maaned, aar


def gjelder_periode(datoer: list):
    """Perioden dokumentet GJELDER FOR («for perioden 01.01. til 31.12.»).

    Tre datobegreper må holdes fra hverandre, og dette er det andre:
      1) dokumentets egen dato   — finn_dokumentdato()
      2) perioden det gjelder for — DENNE
      3) datospennet i en bunke  — dokumentets_periode()

    Skjemautfyllingen brukte tidligere (3) under navnet «periode_start»
    mens dokumentprofilen brukte (2) under samme navn. Samme svar kunne
    da si 2026-04-02 i profilen og 01.08.2019 i «{periode_start}». Begge
    henter nå fra denne funksjonen.

    Paret bygges av en periodestart etterfulgt av en periodeslutt —
    står de ikke i par, er det ingen periode."""
    venter = None
    for d in datoer or []:
        if not isinstance(d, dict):
            continue
        if d.get("type") == "periode_start":
            venter = d
        elif d.get("type") == "periode_slutt" and venter:
            return {"fra": venter.get("dato"), "til": d.get("dato")}
    return None


def dokumentets_periode(datoer: list) -> dict:
    """FRA og TIL for dokumentets EGNE datoer — dokumentets datospenn.

    Et enkelt brev har én dato: da er fra == til. En flersidig fil er
    ofte en BUNKE selvstendige dokumenter (saksmappe, vedleggssamling)
    med hver sin dato — da forteller fra/til hvilken periode filen som
    helhet dekker. Datoene i innholdet (frister, perioder, fødselsdatoer)
    holdes utenfor: dette er dokumentenes egne datoer.

    Returnerer {fra, til, antall, per_side, flere_dokumenter} — eller
    None når ingen dato kan knyttes til dokumentet selv."""
    egne = []
    for d in datoer or []:
        if not isinstance(d, dict) or not d.get("dato"):
            continue
        if rolle_for_type(d.get("type")) != ROLLE_DOKUMENT:
            continue
        parset = _til_dato(d["dato"])
        if parset:
            egne.append((parset, d))
    if not egne:
        # Fast skjelett, ikke None. Et nestet objekt som blir null tar
        # med seg ALLE stiene under seg (R118): en robot som leser
        # `periode.fra` krasjer på første dokument uten dokumentdato.
        return {"fra": None, "til": None, "antall": 0,
                "per_side": [], "flere_dokumenter": False}

    egne.sort(key=lambda p: p[0])
    fra, til = egne[0][1]["dato"], egne[-1][1]["dato"]
    # én oppføring per side: den FØRSTE dokumentdatoen på siden. Flere
    # datoer på samme side er som regel brevhode + signatur i samme brev.
    per_side, sett_sider = [], set()
    for parset, d in egne:
        side = d.get("side")
        if side in sett_sider:
            continue
        sett_sider.add(side)
        per_side.append({"side": side, "dato": d["dato"], "type": d.get("type")})
    per_side.sort(key=lambda p: (p["side"] if p["side"] else 0))

    ulike_datoer = {p[1]["dato"] for p in egne}
    ulike_sider = {p[1].get("side") for p in egne if p[1].get("side")}
    return {
        "fra": fra,
        "til": til,
        "antall": len(ulike_datoer),
        "per_side": per_side,
        # flere daterte dokumenter i samme fil: ulike datoer på ulike
        # sider. Da er «dokumentets dato» egentlig et SPENN, ikke ett punkt.
        "flere_dokumenter": len(ulike_datoer) > 1 and len(ulike_sider) > 1,
    }


def dokumentets_alder(dato_str, i_dag=None) -> dict:
    """Hvor GAMMELT dokumentet er, regnet fra dokumentdatoen.

    Returnerer ALLTID {dager, aar, tekst, fremtidig}; uten lesbar dato
    er alle fire null. Formen er fast fordi klientene er RPA-roboter som
    leser `alder.dager` blindt (R118). «fremtidig» settes når dokumentdatoen
    ligger fram i tid: da er enten datoen feillest, eller dokumentet
    forhåndsdatert — begge deler skal fram, ikke skjules bak et
    negativt tall."""
    dokdato = _til_dato(dato_str)
    if dokdato is None:
        return {"dager": None, "aar": None, "tekst": None,
                "fremtidig": None}
    i_dag = i_dag or date.today()
    dager = (i_dag - dokdato).days

    absolutt = abs(dager)
    aar, rest = divmod(absolutt, 365)
    maaneder = rest // 30
    if absolutt == 0:
        tekst = "datert i dag"
    elif aar and maaneder:
        tekst = f"{aar} år og {maaneder} måned{'er' if maaneder > 1 else ''}"
    elif aar:
        tekst = f"{aar} år"
    elif maaneder:
        tekst = f"{maaneder} måned{'er' if maaneder > 1 else ''}"
    else:
        tekst = f"{absolutt} dag{'er' if absolutt > 1 else ''}"

    if dager < 0:
        tekst = f"datert {tekst} FRAM I TID"
    elif absolutt > 0:
        tekst += " gammelt"
    return {
        "dager": dager,
        "aar": round(dager / 365.25, 2),
        "tekst": tekst,
        "fremtidig": dager < 0,
    }


def finn_dokumentdato(datoer: list, ocr_brukt: bool = False) -> dict:
    """Velger DOKUMENTETS EGEN dato blant de klassifiserte datoene.

    Deterministisk, aldri modellbasert: bare datoer med rolle «dokument»
    er kandidater, og de rangeres etter hvor sterkt beviset er. Finnes
    ingen slik dato, sies det ÆRLIG (dato=None) i stedet for å plukke en
    tilfeldig dato fra innholdet.

    Returnerer {dato, type, kilde, konfidens, begrunnelse, side,
    alternativer, advarsel}."""
    kandidater = []
    for i, d in enumerate(datoer or []):
        if not isinstance(d, dict) or not d.get("dato"):
            continue
        if rolle_for_type(d.get("type")) != ROLLE_DOKUMENT:
            continue
        rang, kilde = _DOKUMENTDATO_RANG.get(d["type"], (6, "etikett"))
        # side 1 foretrekkes ved lik rang: brevhodet står på første side
        kandidater.append((rang, 0 if (d.get("side") or 1) == 1 else 1, i,
                           kilde, d))
    if not kandidater:
        # NØYAKTIG samme nøkler som funn-grenen under (R118). Grenen
        # manglet «type_kodet» og «rolle_kodet» — ikke som null, men
        # BORTE: 12 nøkler ble 10. En robot som leser
        # `felter.dokumentdato.type_kodet.kode` virket på hvert datert
        # dokument og krasjet på det første udaterte.
        return {
            "dato": None, "raatekst": None,
            "type": None,
            "type_kodet": kodeverk(None, _TYPE_TERM),
            "rolle_kodet": kodeverk(None, _ROLLE_TERM),
            "kilde": None, "konfidens": "ingen",
            "begrunnelse": ("Fant ingen dato som kan knyttes til dokumentet "
                            "selv — verken etikett (vedtaksdato/utstedt/"
                            "signert), dato øverst på side 1, dato ved en "
                            "signaturblokk nederst eller PDF-metadata. "
                            "Datoene i dokumentet hører til innholdet."),
            "side": None, "alternativer": [], "advarsel": None,
            "periode": dokumentets_periode([]),
        }

    kandidater.sort(key=lambda k: (k[0], k[1], k[2]))
    rang, _, _, kilde, beste = kandidater[0]
    konfidens = _RANG_KONFIDENS.get(rang, "lav")
    begrunnelse = beste.get("begrunnelse") or ""
    advarsler = []

    # PDF-metadata på et SKANNET dokument er skannedatoen, ikke dokumentets
    if kilde == "pdf_metadata" and ocr_brukt:
        konfidens = "lav"
        advarsler.append(
            "Dokumentet er skannet, og datoen kommer fra PDF-filens "
            "metadata — det er trolig SKANNEDATOEN, ikke dokumentets dato")
    # håndskrevet dato er mindre pålitelig lest enn trykt
    if beste.get("skrevet_for_hand"):
        konfidens = "middels" if konfidens == "hoy" else "lav"
        advarsler.append("datoen er håndskrevet — kontroller lesingen")
    if beste.get("aar_antatt"):
        advarsler.append("tosifret årstall i kilden — århundret er antatt")

    alder = dokumentets_alder(beste["dato"])
    if alder and alder["fremtidig"]:
        advarsler.append(
            "dokumentdatoen ligger FRAM I TID — enten er datoen feillest, "
            "eller dokumentet er forhåndsdatert")

    # Datospennet: ett brev gir fra == til, en bunke gir en periode
    periode = dokumentets_periode(datoer)
    if periode and periode["flere_dokumenter"]:
        advarsler.append(
            f"filen inneholder flere daterte dokumenter ({periode['fra']}–"
            f"{periode['til']}) — «dokumentets dato» er her et SPENN, og "
            f"{beste['dato']} er dokumentet på side {beste.get('side') or 1}")

    # Uenighet på SAMME rang er et ekte varsel: to like sterke bevis som
    # peker på ulike datoer skal et menneske se på, ikke skjules. I en
    # BUNKE er uenigheten derimot forventet — hvert dokument har sin egen
    # dato — og forklares allerede av spenn-advarselen over.
    samme_rang = {k[4]["dato"] for k in kandidater if k[0] == rang}
    if len(samme_rang) > 1 and not (periode and periode["flere_dokumenter"]):
        advarsler.append(
            "flere like sterke kandidater med ULIKE datoer ("
            + ", ".join(sorted(samme_rang)) + ") — kontroller mot dokumentet")

    return {
        "dato": beste["dato"],
        # Slik datoen STO i dokumentet, ordrett. Den normaliserte formen
        # er den man regner med; originalen er den man kontrollerer mot
        # når OCR er tvilsom.
        "raatekst": beste.get("raatekst"),
        "type": beste.get("type"),
        # kodet par {kode, term} i tillegg til den rå «type»-strengen
        "type_kodet": kodeverk(beste.get("type"), _TYPE_TERM),
        "rolle_kodet": kodeverk(ROLLE_DOKUMENT, _ROLLE_TERM),
        "kilde": kilde,
        "konfidens": konfidens,
        "begrunnelse": begrunnelse,
        "side": beste.get("side"),
        # dokumentets datospenn: fra–til. Ett brev gir fra == til; en
        # flersidig bunke gir perioden filen som helhet dekker.
        "periode": periode,
        "alternativer": [
            {"dato": k[4]["dato"], "type": k[4].get("type"),
             "type_kodet": kodeverk(k[4].get("type"), _TYPE_TERM),
             "konfidens": _RANG_KONFIDENS.get(k[0], "lav")}
            for k in kandidater[1:6]],
        "advarsel": "; ".join(advarsler) if advarsler else None,
    }


# Brukerdefinerte etiketter fra regler/egne_etiketter.txt:
# «ord = type» per linje — eller «ord = type = rolle» når etiketten er
# dokumentets EGEN dato (rolle: dokument/innhold/behandling). Nye
# dokumenttyper med nye ord krever dermed ALDRI kodeendring — én linje i
# en tekstfil, uten omstart.
from delt.prompter import regelfil as _regelfil

_EGNE_ETIKETTER_STI = _regelfil("egne_etiketter.txt")
_egne_etiketter_cache = {"mtime": None, "liste": [], "roller": {}}
_GYLDIGE_ROLLER = (ROLLE_DOKUMENT, ROLLE_INNHOLD, ROLLE_BEHANDLING)


def _les_egne_etiketter() -> None:
    """Leser egne_etiketter.txt på nytt hvis fila er endret."""
    try:
        mtime = os.path.getmtime(_EGNE_ETIKETTER_STI)
    except OSError:
        _egne_etiketter_cache.update(mtime=None, liste=[], roller={})
        return
    if _egne_etiketter_cache["mtime"] == mtime:
        return
    liste, roller = [], {}
    try:
        # utf-8-sig: en fil lagret fra Notepad får BOM, og uten -sig
        # havner den usynlig først på linje én — da slipper en
        # kommentarlinje forbi «startswith('#')»-filteret
        with open(_EGNE_ETIKETTER_STI, encoding="utf-8-sig") as f:
            for linje in f:
                linje = linje.strip()
                if not linje or linje.startswith("#") or "=" not in linje:
                    continue
                deler = [d.strip() for d in linje.split("=")]
                ordet, typen = deler[0], deler[1] if len(deler) > 1 else ""
                if not (ordet and typen):
                    continue
                typen = re.sub(r"[^\wæøå]", "_", typen.lower())
                liste.append((re.escape(ordet), typen))
                # valgfri tredje del: rollen. Ugyldig rolle ignoreres i
                # stillhet — da gjelder standarden (innhold), som er trygt
                if len(deler) > 2 and deler[2].strip().lower() in _GYLDIGE_ROLLER:
                    roller[typen] = deler[2].strip().lower()
    except OSError:
        return          # behold forrige (gyldige) innhold
    _egne_etiketter_cache.update(mtime=mtime, liste=liste, roller=roller)


def _egne_dato_etiketter() -> list:
    _les_egne_etiketter()
    return _egne_etiketter_cache["liste"]


def _egne_roller() -> dict:
    _les_egne_etiketter()
    return _egne_etiketter_cache["roller"]


def klassifiser_datoer(tekst: str, maks: int = 200) -> list:
    """Klassifiserer HVER dato i teksten: hva den er og hvorfor.

    Deterministisk (ingen modell): etiketter i konteksten, posisjon i
    dokumentet, fra–til-intervaller og fødselsnummer-avledning. Datoer
    uten noe signal klassifiseres ærlig som «ukjent» med kontekst
    vedlagt — de skal vurderes av et menneske, ikke gjettes på.

    Returnerer liste av {dato, raatekst, type, etikett, begrunnelse,
    side, kontekst, i_lopende_tekst}, i tekstrekkefølge."""
    treff = _alle_datotreff(tekst)

    # Sidegrenser fra [Side i av n]-merkene (satt av API-et)
    sidemerker = [(m.start(), int(m.group(1)))
                  for m in re.finditer(r"\[Side (\d+) av \d+\]", tekst)]

    def _side_for(pos: int) -> int:
        side = 1
        for merkepos, nr in sidemerker:
            if pos >= merkepos:
                side = nr
            else:
                break
        return side

    # Linjenummer via forhåndsberegnede linjeskift: å telle «\n» på nytt
    # per dato ville blitt O(tekst × datoer) på et hundresiders dokument.
    nylinjer = [m.start() for m in re.finditer("\n", tekst)]

    def _linjenr(pos: int) -> int:
        return bisect.bisect_left(nylinjer, pos)

    # «Øverst» og «nederst» måles PER SIDE, ikke for hele filen. En
    # flersidig fil er ofte en bunke selvstendige dokumenter: brevhodet på
    # side 4 er øverst på SIN side, og signaturen på side 2 er nederst på
    # sin — målt mot hele filen ville ingen av dem blitt funnet.
    _sidestart = [m.start() for m in re.finditer(r"\[Side \d+ av \d+\]", tekst)]
    if not _sidestart or _sidestart[0] != 0:
        _sidestart = [0] + _sidestart

    def _sideomraade(pos: int):
        i = bisect.bisect_right(_sidestart, pos) - 1
        start = _sidestart[max(i, 0)]
        slutt = _sidestart[i + 1] if i + 1 < len(_sidestart) else len(tekst)
        return start, slutt

    def _linjenr_i_side(pos: int) -> int:
        start, _ = _sideomraade(pos)
        return _linjenr(pos) - _linjenr(start)

    def _naer_slutten(pos: int) -> bool:
        """Nederste del av SIN side: siste 20 % eller siste 600 tegn (det
        romsligste), men aldri mer enn siste halvdel — ellers ville midten
        av en kort side regnes som signaturblokk. Sider under 200 tegn har
        ingen slutt-sone; da gjelder brevhode-regelen alene."""
        start, slutt = _sideomraade(pos)
        lengde = slutt - start
        if lengde < 200:
            return False
        grense = max(slutt - max(600, int(lengde * 0.20)),
                     start + int(lengde * 0.5))
        return pos >= grense

    resultater = []
    for i, (start, slutt, raatekst, dato, aar_antatt) in enumerate(treff[:maks]):
        linje_start = tekst.rfind("\n", 0, start) + 1
        linje_slutt = tekst.find("\n", slutt)
        if linje_slutt == -1:
            linje_slutt = len(tekst)
        linje = tekst[linje_start:linje_slutt]
        kontekst = " ".join(
            tekst[max(0, start - 45):min(len(tekst), slutt + 30)].split())

        dtype, etikett, begrunnelse = None, None, None

        # 1) Fra–til-intervall: to datoer med kort bindetekst mellom
        if i + 1 < len(treff):
            mellom = tekst[slutt:treff[i + 1][0]]
            if len(mellom) <= 8 and re.search(r"[-–—]|til", mellom, re.IGNORECASE):
                dtype = "periode_start"
                begrunnelse = "første dato i et fra–til-intervall"
        if dtype is None and i > 0:
            mellom = tekst[treff[i - 1][1]:start]
            if len(mellom) <= 8 and re.search(r"[-–—]|til", mellom, re.IGNORECASE):
                dtype = "periode_slutt"
                begrunnelse = "andre dato i et fra–til-intervall"

        # 2) Etikett rett før datoen (på samme linje) — brukerens egne
        #    etiketter sjekkes FØRST og kan dermed overstyre de innebygde
        if dtype is None:
            etikett_sok = tekst[max(linje_start, start - 35):start]

            def naermeste(etiketter):
                """Etiketten som SLUTTER nærmest datoen — og ved likt
                sluttpunkt den LENGSTE.

                To hensyn måtte forenes. «Dagpenger for perioden
                01.01.2023 til og med 31.12.2023»: foran sluttdatoen
                står både «periode» (langt til venstre) og «til og med»
                (rett foran). Vinner den første i listerekkefølge, blir
                sluttdatoen en periodeSTART og perioden forsvinner.
                «Søknad datert 12.03.2024»: her slutter både «søknad
                datert» og «datert» på samme sted, og da er den lengste
                den presise — ellers ble søknadsdatoen til dokumentdato.
                Nærmest slutt, deretter lengst, gir begge deler."""
                beste = beste_rang = None
                for monster, kandidat in etiketter:
                    for m in re.finditer(monster, etikett_sok, re.IGNORECASE):
                        rang = (m.end(), len(m.group(0)))
                        if beste_rang is None or rang > beste_rang:
                            beste, beste_rang = (m, kandidat), rang
                return beste

            # brukerens egne etiketter har fortsatt forrang som gruppe
            traff = naermeste(_egne_dato_etiketter()) \
                or naermeste(_DATO_ETIKETTER)
            if traff:
                m, dtype = traff
                etikett = m.group(0)
                begrunnelse = f"etiketten «{etikett}» står rett før datoen"

        # 2b) «Oslo, 12.06.2026» — stedsnavn rett foran datoen. Norsk
        #     konvensjon i brevhoder og signaturblokker, og et sterkt
        #     signal om at datoen gjelder DOKUMENTET. Slår an uansett
        #     hvor i dokumentet den står (brevhode øverst, signatur nederst).
        if dtype is None and _STED_FORAN_DATO.search(
                tekst[linje_start:start]) and len(linje.strip()) <= 60:
            dtype = ("signaturdato_sannsynlig" if _naer_slutten(start)
                     else "brevdato_sannsynlig")
            begrunnelse = ("stedsnavn rett foran datoen («Sted, dato») — "
                           "norsk konvensjon for dokumentets egen dato")

        # 3a) Signaturblokk: dato nederst i dokumentet, på kort linje, med
        #     signaturord i nærheten. Her står dokumentets dato i skjemaer
        #     og erklæringer — den signerte datoen ER dokumentets dato.
        if dtype is None and _naer_slutten(start) and len(linje.strip()) <= 60 \
                and _SIGNATUR_ORD.search(
                    tekst[max(0, start - 120):min(len(tekst), slutt + 200)]):
            dtype = "signaturdato_sannsynlig"
            begrunnelse = ("nederst i dokumentet ved signaturord "
                           "(sign./underskrift/hilsen) — typisk signaturdato")

        # 3b) Brevdato: øverst i dokumentet på egen kort linje. Måles i
        #     LINJER, ikke tegn: et brevhode med avsender- og mottakerblokk
        #     skyver lett datoen forbi en tegngrense, og da forsvant den.
        #     Gjelder øverst på HVER side (en bunke har flere brevhoder).
        #     «not _naer_slutten» er nødvendig på KORTE sider, der de
        #     første 14 linjene også er de siste: uten den fikk en dato ved
        #     underskriften begrunnelsen «øverst i dokumentet».
        if dtype is None and not _naer_slutten(start) \
                and _linjenr_i_side(start) < 14 and len(linje.strip()) <= 40:
            dtype = "brevdato_sannsynlig"
            side_ord = ("øverst i dokumentet" if _side_for(start) == 1
                        else f"øverst på side {_side_for(start)}")
            begrunnelse = (f"{side_ord} på egen kort linje — "
                           "typisk brev-/utstedelsesdato")

        # 3c) Datoen ALENE på sin egen linje nederst, uten signaturord.
        #     Svakere signal, men i praksis dateringen ved underskriften.
        #     Kravet om at linja ikke inneholder ANNET enn datoen holder
        #     tabeller og datolister ute.
        if dtype is None and _naer_slutten(start) and re.fullmatch(
                r"[\s.,;:\-–—]*" + re.escape(raatekst) + r"[\s.,;:\-–—]*",
                linje):
            dtype = "signaturdato_sannsynlig"
            begrunnelse = ("alene på egen linje nederst i dokumentet — "
                           "typisk dateringen ved underskriften")

        # 4) Løpende tekst eller ærlig ukjent
        i_lopende = len(linje.strip()) > 60
        if dtype is None:
            if i_lopende:
                dtype = "i_lopende_tekst"
                begrunnelse = "står inne i en setning, uten etikett"
            else:
                dtype = "ukjent"
                begrunnelse = ("ingen etikett eller posisjonssignal — "
                               "bør vurderes av et menneske")

        if aar_antatt:
            begrunnelse += "; tosifret år i kilden — århundret er antatt"

        resultater.append({
            "dato": dato,
            "raatekst": raatekst,
            "type": dtype,
            "etikett": etikett,
            "begrunnelse": begrunnelse,
            "side": _side_for(start),
            "kontekst": kontekst,
            "i_lopende_tekst": i_lopende,
            "aar_antatt": aar_antatt,
        })

    # 5) Fødselsdato avledet fra gyldig fødselsnummer
    fnr = finn_fodselsnummer(tekst)
    if fnr:
        d, m, aar = fodselsdato_av_fnr(fnr) or (None, None, None)
        if d and _gyldig_dato(d, m, aar):
            resultater.append({
                "dato": iso(d, m, aar),
                "raatekst": fnr[:6] + "*****",
                "type": "fodselsdato_fra_fnr",
                "etikett": None,
                "begrunnelse": ("avledet fra de seks første sifrene i et "
                                "mod11-gyldig fødselsnummer "
                                "(forenklet århundreregel)"),
                "side": None,
                "kontekst": "fødselsnummer i dokumentet (maskert)",
                "i_lopende_tekst": False,
                # Samme nøkler som hver andre oppføring (R119). Denne
                # manglet «aar_antatt» — og den legges SIST, så en vakt
                # som bare inspiserte listas FØRSTE element kunne aldri
                # se det. Århundret er utledet av fødselsnummerets egen
                # regel, ikke antatt av oss, så verdien er False.
                "aar_antatt": False,
            })
    return resultater


def _gyldig_dato(d: int, m: int, y: int) -> bool:
    if not (1900 <= y <= datetime.utcnow().year + 1):
        return False
    try:
        datetime(y, m, d)
        return True
    except ValueError:
        return False


# Telefongrupperinger som faktisk brukes i Norge: parvis «22 33 44 55»
# OG mobilformen 3-2-3 «412 88 903». Målt på den syntetiske testbunken:
# kun parvis ble fanget før, så personens mobil (+47 412 88 903) ble
# aldri funnet — mens fakturanummeret 90114882 (åtte sifre i strekk)
# BLE «telefon». Én delt skanner for finn_telefon, finn_alle_telefoner
# og sladdingen, så de aldri kan være uenige.
_TELEFON_MONSTER = re.compile(
    r"(?:\+47|0047)?[ ]?(?:"
    r"(\d{2})[ ]?(\d{2})[ ]?(\d{2})[ ]?(\d{2})"      # 2-2-2-2 / 8 i strekk
    r"|(\d{3})[ ]?(\d{2})[ ]?(\d{3})"                # 3-2-3 (mobilform)
    r")\b")

# Etikett rett foran som betyr at tallet IKKE er en telefon.
_IKKE_TELEFON_ETIKETT = re.compile(
    r"(?:faktura(?:nummer|nr)?|kunde(?:nummer|nr)?|ordre(?:nummer|nr)?"
    r"|saksnr\.?|saksnummer)[.:\s]*$", re.IGNORECASE)


def _telefon_treff(tekst: str):
    """Yielder (start, slutt, nummer) for hver telefonkandidat, med alle
    vaktene: ikke halen av et lengre tall, ikke et tall etiketten foran
    sier er noe annet, og norske abonnentnumre starter ikke på 0/1."""
    for treff in _TELEFON_MONSTER.finditer(tekst):
        start = treff.start()
        if start > 0 and tekst[start - 1].isdigit():
            continue
        nummer = "".join(g for g in treff.groups() if g)
        if len(nummer) != 8 or nummer[0] in "01":
            continue
        if _IKKE_TELEFON_ETIKETT.search(tekst[max(0, start - 24):start]):
            continue
        # Uten +47-prefiks sluker [ ]? naboens mellomrom — trim
        if tekst[start] == " ":
            start += 1
        yield start, treff.end(), nummer


def finn_telefon(tekst: str):
    """Norsk telefonnummer: 8 sifre, ev. +47/0047-prefiks og gruppering
    (parvis eller 3-2-3)."""
    for _, _, nummer in _telefon_treff(tekst):
        return nummer
    return None


def finn_epost(tekst: str):
    treff = re.search(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b", tekst)
    return treff.group(0) if treff else None


def finn_postnummer_sted(tekst: str):
    """«0181 Oslo» → (postnummer, poststed). Flerords-steder med «i»
    («8610 Mo i Rana») fanges også — uten å sluke neste setningsord.

    «Postboks 6600 Etterstad» er IKKE et postnummer: 6600 er
    postboksnummeret, og Etterstad navnet på postboksanlegget. Målt på
    testbunken kom den fella FØRST i teksten (NAVs egen adresselinje) og
    stjal feltet fra det ekte postnummeret på samme linje (0607 OSLO).

    «Rema 1000 AS» er heller ikke et postnummer. Den vakten fantes bare i
    `finn_adresser`, så de to adressefinnerne svarte ULIKT på samme
    dokument: `struktur.adresser` sa Storgata 14 B / 3044 DRAMMEN mens
    `felter.postnummer/poststed` sa 1000 / AS — og det er den siste som
    mater `{postnummer}` i skjemautfyllingen."""
    for treff in re.finditer(
        r"\b(\d{4})[ \t]+([A-ZÆØÅ][a-zæøåA-ZÆØÅ]+"
        r"(?:[ \t][iI][ \t][A-ZÆØÅ][a-zæøåA-ZÆØÅ]+)?)\b",
        tekst,
    ):
        forfelt = tekst[max(0, treff.start() - 12):treff.start()]
        if re.search(r"(?i)postboks\s*$", forfelt):
            continue
        if treff.group(2).upper() in _SELSKAPSFORM:
            continue
        return treff.group(1), treff.group(2)
    return None, None


# R53: tusenskille er ALLTID grupper på nøyaktig tre sifre («46 300»,
# «1 234 567»). Mønsteret tillot tidligere hvilken som helst blanding av
# sifre, mellomrom og punktum, og slo dem sammen til ett tall. På en
# kvittering der OCR hadde mistet desimalkommaet ble «NOK 463 00»
# (altså 463,00) lest som 46300 — hundre ganger for mye, i et felt som
# skal tåle å bli lest av et saksbehandlingssystem.
#
# Med kravet om tregrupper stopper mønsteret etter «463», som er riktig
# krone-verdi, i stedet for å sluke de to ørene som om de var tusener.
#
# R60: tusengruppene godtar også bokstaven O. På håndskrift og
# matriseskrift leser OCR jevnlig null som O — «kr 15 000 per måned» ble
# «kr 15 OOO», og parseren stoppet på 15. TUSEN ganger for lite, i et
# beløpsfelt. Funnet av regresjonskorpuset (skript/kjor_korpus.py).
#
# Hvorfor dette er trygt: O godtas BARE inne i en gruppe på nøyaktig tre
# tegn som følger rett etter et tall og et skilletegn. «kr 15 OSLO»
# treffer ikke (OSL er ikke tre O/sifre etterfulgt av gruppeslutt), og
# løpende tekst kan ikke bli til et beløp. Gruppen normaliseres til
# sifre før tallet tolkes.
# Desimaldelen godtar BÅDE komma (norsk «463,00») OG punktum
# (internasjonalt «6380.00», som er vanlig på hotell-/utenlandskvitteringer).
# R61: uten punktum-varianten ga «6380.00 NOK» INGEN beløp — det falt
# mellom stolene fordi «.00» hverken er en tregruppe (tusenskille krever
# tre sifre) eller et komma. Funnet på en ekte Thon-kvittering der belop
# ble 0.0 mens totalen sto to ganger som «6380.00 NOK».
_BELOP_TALL = r"\d+(?:[ .][\dOo]{3})*(?:[.,]\d{2}|,-)?"

# Beløp der valutaordet står ETTER tallet: «12 500 kroner», «15 000 kr»,
# «500 NOK». Dette er den vanligste skrivemåten i norske vedtaksbrev, og
# den falt mellom alle mønstrene: uten valutaord FORAN og uten desimaler
# traff verken prefiks-regelen eller tusenskille-med-desimaler-regelen.
# Målt før fiksen: «Du får utbetalt 12 500 kroner» ga INGEN beløp — og
# skjemautfyllingen mistet dermed grunnlaget sitt på nettopp de beløpene
# som betyr mest. Valutaordet er ankeret, akkurat som i prefiks-regelen,
# så årstall, saksnummer og telefonnumre fortsatt ikke kan bli beløp.
_BELOP_ETTER = r"\b(" + _BELOP_TALL + r")\s?(?:kr\.?|kroner|NOK)\b"


def _o_til_null(tall: str) -> str:
    """Gjør OCR-ens bokstav-O om til sifferet 0 i et beløp som allerede
    er gjenkjent som tall. Kalles aldri på fri tekst."""
    return tall.replace("O", "0").replace("o", "0")


def _normaliser_belop(raa: str):
    """Rå beløpsstreng → float, med RIKTIG tolkning av skilletegn.

    Punktum er tvetydig: i norsk er det tusenskille («46.300» = 46300),
    internasjonalt er det desimaltegn («6380.00» = 6380). Regelen som
    løser det: et punktum (eller komma) med NØYAKTIG to sifre etter, helt
    til slutt, er DESIMAL — alt annet er tusenskille. En tusengruppe er
    alltid tre sifre, så «.00» kan aldri være tusener. Uten dette ble
    «6380.00» normalisert til «638000» (punktum fjernet) og feiltolket."""
    s = raa.replace(" ", "").replace(",-", "")
    if "," in s:
        # komma = desimal (norsk); punktum er da tusenskille
        return _til_float(s.replace(".", "").replace(",", "."))
    if "." in s:
        heltall, siste = s.rsplit(".", 1)
        if len(siste) == 2:                    # «.00» = desimal
            return _til_float(heltall.replace(".", "") + "." + siste)
        return _til_float(s.replace(".", ""))  # «.300» = tusenskille
    return _til_float(s)


def _til_float(s: str):
    try:
        return float(s)
    except ValueError:
        return None


def finn_belop(tekst: str):
    """Kronebeløp: «kr 12 345,50», «NOK 5000», «12.345,-», «463,00».

    Siste alternativ (rent øre-desimaltall uten valutaord i nærheten)
    dekker kvitteringer der etikett og tall står på hver sin linje —
    «Total Kr:\\n486,00» — slik at hverken prefiks- eller
    suffiks-regelen når over linjeskiftet til tallet. finn_alle_belop
    hadde alt dette alternativet; finn_belop manglet det, så
    strukturert felt-uttrekk («felter.belop») mistet beløpet stille på
    denne kvitteringslayouten selv om selve teksten inneholdt det."""
    treff = re.search(
        r"(?:kr\.?|NOK)\s?(" + _BELOP_TALL + r")|"
        r"\b([\d]{1,3}(?:[ .]\d{3})+(?:,\d{2}|,-))|"
        r"\b(\d{1,6},\d{2})\b|"
        + _BELOP_ETTER,
        tekst, re.IGNORECASE,
    )
    if not treff:
        return None
    raa = _o_til_null(
        (treff.group(1) or treff.group(2) or treff.group(3)
         or treff.group(4)).strip())
    return _normaliser_belop(raa)


# Etiketter som peker på dokumentets TOTALBELØP. «Total Km» kan aldri bli
# et beløp — både fordi km ikke har valutaord og fordi beløpsmønsteret
# krever to desimaler («15,8» er ikke et beløp).
# «Beløp å betale» er fakturaformen: linja starter med «beløp», ikke med
# total/sum, og falt derfor utenfor — kravbeløpet (kr 4 812,00) manglet.
_TOTAL_ETIKETT = re.compile(
    r"^\W*(?:total(?:sum|t|beløp|belop)?|sum|å\s*betale|aa\s*betale"
    r"|til\s*betaling|bel(?:ø|oe?)p\s+(?:å|aa)\s+betale)\b", re.IGNORECASE)


def finn_totalbelop(tekst: str):
    """Beløpet på en linje merket «Total», «Sum», «Å betale» e.l.
    None hvis dokumentet ikke har en slik etikett.

    SKILT fra finn_belop, som gir FØRSTE beløp i teksten. På en kvittering
    er de forskjellige: «Pris Kr: 463,00 … Total Kr: 486,00». Hvilket som
    er «riktig» avhenger av dokumentet — et vedtak kan si «12 500 kroner
    per måned» først og en årssum etterpå, der FØRSTE beløp er det man vil
    ha i skjemaet og summen ville vært feil. Derfor gjetter API-et ikke:
    det leverer begge deterministisk, og klienten velger.

    Beløpet godtas både på SAMME linje («Sum: 486,00») og på den NESTE
    («Total Kr:\\n486,00») — sistnevnte er vanlig kvitteringsoppsett der
    etikett og tall står i hver sin kolonne, som OCR leser som to linjer.
    """
    linjer = (tekst or "").splitlines()
    for i, linje in enumerate(linjer):
        if not _TOTAL_ETIKETT.match(linje.strip()):
            continue
        verdi = finn_belop(linje)
        if verdi is not None:
            return verdi
        # Neste linje KUN når etikettlinja selv er uten sifre («Total
        # Kr:»-oppsettet). En tabellrad («SUM 128 100 8 550 …») har sifre
        # som bare ikke lot seg tolke som beløp — å falle videre derfra
        # gjorde NESTE linjes tall («Beregnet maanedsinntekt: kr 47 400»)
        # til «totalbeløp» på testbunken. Raden svarer selv; den svarer
        # bare ikke med et beløp.
        if any(c.isdigit() for c in linje):
            continue
        for kandidat in linjer[i + 1:i + 2]:
            verdi = finn_belop(kandidat)
            if verdi is not None:
                return verdi
    return None


def finn_forfallsdato(tekst: str):
    """Datoen et krav MÅ betales: «Forfallsdato 24.06.2026»,
    «Betalingsfrist: 01.07.2026».

    Skilt fra dokumentdato med vilje: på en faktura er forfallsdatoen
    handlingsdatoen — den viktigste enkeltdatoen i dokumentet — mens
    fakturadatoen bare sier når kravet ble skrevet. Testbunken hadde
    beløpet og forfallet som det eneste utførbare i hele bunken, og
    ingen av dem kom ut som felt."""
    treff = re.search(r"(?:forfalls?dato|forfall|betalingsfrist)\b[:\s]*",
                      tekst, re.IGNORECASE)
    if not treff:
        return None
    return finn_dato(tekst[treff.end():treff.end() + 24])


def finn_saksnummer(tekst: str):
    """Saksreferanser: «saksnr 21/12345», «Saksnummer: 4417820»,
    «Sakstilvising: 5590114» (nynorsk) — og NAV-skjemakoder som
    «NAV 04-01.03» som SISTE utvei.

    Rekkefølgen er poenget (målt på testbunken): et merket, rent
    saksnummer («Saksnummer: 4417820», gjentatt på fire sider) tapte
    før mot skjemakoden «NAV 08-07.04» — skjemakoden identifiserer
    BLANKETTEN, ikke saken, og er det svakeste beviset her."""
    treff = re.search(
        r"(?:saksnr\.?|saksnummer|ref\.?|referanse)[:\s]+([0-9]{2,4}/[0-9]{3,6})",
        tekst, re.IGNORECASE,
    )
    if treff:
        return treff.group(1)
    treff = re.search(
        r"(?:saksnr\.?|saksnummer|sakstilvising)[:\s]+(\d{5,9})\b",
        tekst, re.IGNORECASE,
    )
    if treff:
        return treff.group(1)
    treff = re.search(r"\bNAV\s?(\d{2}-\d{2}\.\d{2})\b", tekst)
    if treff:
        return f"NAV {treff.group(1)}"
    return None


def finn_kontornavn(tekst: str):
    """NAV-kontor: «NAV Grünerløkka», «NAV Bergen vest»."""
    # Andre ord krever ≥3 tegn — ellers sluker mønsteret småord («i», «og»)
    treff = re.search(
        r"\bNAV\s+([A-ZÆØÅ][\w-]+(?:\s+[a-zæøå][\w-]{2,})?)", tekst
    )
    if not treff:
        return None
    kandidat = treff.group(1).strip()
    # Skjemakoder («NAV 04-…») og ytelsesord er ikke kontornavn
    if kandidat.lower() in NORSKE_YTELSER:
        return None
    return f"NAV {kandidat}"


def _uten_saertegn(tekst: str) -> str:
    """æøå (og ae/oe/aa) skrevet ned til a/o, så de tre skrivemåtene av
    samme ord kan sammenlignes."""
    lav = (tekst or "").lower()
    for fra, til in (("æ", "a"), ("ø", "o"), ("å", "a"),
                     ("ae", "a"), ("oe", "o"), ("aa", "a")):
        lav = lav.replace(fra, til)
    return lav


def finn_ytelse(tekst: str):
    """Nøkkelordssøk mot den kanoniske ytelseslisten — sikrere enn å
    gjette at enhver ORG-entitet er en ytelse.

    BEGGE sider normaliseres for æøå. Lista er skrevet uten særtegn, og
    dokumentene skriver «uføretrygd»: uten normaliseringen fant vi
    ALDRI uføretrygd, uførepensjon, overgangsstønad eller kontantstøtte
    — fire av de viktigste ytelsene, og de falt stille bort som «ingen
    ytelse nevnt».

    Lengste treff vinner, så «uførepensjon» ikke blir til «pensjon» og
    «arbeidsavklaringspenger» ikke til «penger»."""
    flat = _uten_saertegn(tekst)
    treff = [y for y in NORSKE_YTELSER if _uten_saertegn(y) in flat]
    return max(treff, key=len) if treff else None


def finn_alle_ytelser(tekst: str) -> list:
    """ALLE ytelsene dokumentet nevner, i den rekkefølgen de står.

    `finn_ytelse` gir bare ÉN — den lengste. Det er riktig når to navn
    overlapper, men det taper informasjon når dokumentet nevner to ULIKE
    ytelser: et AAP-vedtak viser nesten alltid til sykepengeperioden som
    tok slutt, og et etterbetalingsbrev kan gjelde to ordninger. Da sa
    profilen «arbeidsavklaringspenger» og tidde om resten.

    Rekkefølgen er FØRSTE FOREKOMST, ikke lengde. Den er stabil for
    samme tekst, og «hva står øverst» er det en leser ser først.
    """
    flat = _uten_saertegn(tekst)
    med_posisjon = []
    for ytelse in NORSKE_YTELSER:
        i = flat.find(_uten_saertegn(ytelse))
        if i >= 0:
            med_posisjon.append((i, ytelse))
    # posisjon først, så navn: to ytelser kan ikke starte på samme
    # indeks, men sorteringen skal være total uansett input
    return [y for _, y in sorted(med_posisjon)]


# Paragraf- og kapittelhenvisninger i løpende tekst. «§ 8-2», «§§ 8-2 og
# 8-3», «kapittel 11», «kap. 4». Lovnavnet står ofte foran, men ikke
# alltid — derfor fanges det separat og kan mangle.
# Rekkefølgen betyr noe: den TODELTE formen prøves først, ellers ville
# «§ 8-2» blitt lest som den udelte «§ 8» og leddet forsvunnet stille.
_PARAGRAF_REF = re.compile(
    r"§{1,2}\s*(\d{1,2})\s*[-–]\s*(\d{1,2}[a-zA-Z]?)"
    r"|§{1,2}\s*(\d{1,2}[a-zA-Z]?)(?!\s*[-–]\s*\d)"
    r"|\bkap(?:\.|ittel)?\s*(\d{1,2})\s*([A-Z])?\b")

# Loven henvisningen gjelder, når den er navngitt rett foran.
_LOVNAVN_FORAN = re.compile(
    r"(?i)\b(folketrygdloven|folketrygdlova|ftrl|lov\s+om\s+folketrygd)"
    r"[^.\n]{0,40}$")


def finn_lovhenvisninger(tekst: str) -> list:
    """Paragraf- og kapittelhenvisninger slik de STÅR i dokumentet.

    Dette er noe annet enn `hjemmel`, som sier hvilken lov som GJALDT da
    dokumentet ble skrevet. Et vedtak kan vise til flere paragrafer, og
    et klagebrev siterer gjerne både bestemmelsen det klages på og
    saksbehandlingsregelen. Én hjemmel kan ikke bære det.

    Returnerer `{referanse, kapittel, lov_nevnt, posisjon}` per treff,
    uten å slå opp noe — oppslaget krever dokumentdatoen og hører hjemme
    i profilen. Duplikater fjernes; samme paragraf nevnt fem ganger er
    én henvisning.
    """
    funn, sett = [], set()
    for m in _PARAGRAF_REF.finditer(tekst or ""):
        kap_p, ledd, alene, kap_k, bokstav = m.groups()
        if kap_p:
            referanse = f"§ {kap_p}-{ledd}"
            kapittel = kap_p
        elif alene:
            # Folketrygdloven nummererer «kapittel-ledd» (§ 8-2). En
            # UDELT paragraf tilhører derfor en ANNEN lov —
            # forvaltningsloven § 29 er den vanligste i NAV-brev. Vi
            # kjenner ikke den loven, så kapittelet står tomt i stedet
            # for å bli gjettet til «kapittel 29» i folketrygdloven,
            # som ikke finnes.
            referanse = f"§ {alene}"
            kapittel = None
        else:
            kapittel = f"{kap_k}{bokstav or ''}"
            referanse = f"kapittel {kapittel}"
        if referanse in sett:
            continue
        sett.add(referanse)
        foran = tekst[max(0, m.start() - 60):m.start()]
        navn = _LOVNAVN_FORAN.search(foran)
        funn.append({
            "referanse": referanse,
            "kapittel": kapittel,
            # Står lovnavnet rett foran, er henvisningen ikke flertydig
            # selv uten dokumentdato. Står det ikke, sier vi det —
            # ikke gjetter.
            "lov_nevnt": bool(navn),
            "posisjon": m.start(),
        })
    return funn


def finn_fylke(tekst: str):
    # Lengste navn først → «Troms og Finnmark» matches før «Troms», og
    # resultatet blir deterministisk (NORSKE_FYLKER er et set/uordnet).
    for fylke in sorted(NORSKE_FYLKER, key=len, reverse=True):
        if re.search(rf"\b{re.escape(fylke)}\b", tekst):
            return fylke
    return None


# ------------------------------------------------------------------ #
#  Strukturert totaluttrekk — komplett, generelt skjema               #
# ------------------------------------------------------------------ #
# Prinsipper (bransjebeste praksis for dokumentekstraksjon):
#   * ALLE nøkler er alltid til stede — tomt er "" eller []
#   * beløp er tall, datoer er normaliserte
#   * alt med sjekksum valideres matematisk (fnr, konto, orgnr, KID)
#   * generelt: sifferkandidater finnes uansett gruppering
#     (mellomrom/punktum) — skjemaer og OCR grupperer vilkårlig
#   * deterministisk: samme dokument gir alltid samme resultat

_ORGNR_VEKTER = [3, 2, 7, 6, 5, 4, 3, 2]


def er_gyldig_orgnr(nr: str) -> bool:
    """Norsk organisasjonsnummer: 9 sifre med mod11-kontrollsiffer."""
    if not nr or not nr.isdigit() or len(nr) != 9:
        return False
    k = _mod11_kontroll(nr, _ORGNR_VEKTER)
    return k != 10 and k == int(nr[8])


def _luhn_gyldig(sifre: str) -> bool:
    total = 0
    for i, tegn in enumerate(reversed(sifre)):
        v = int(tegn)
        if i % 2 == 1:
            v = v * 2
            if v > 9:
                v -= 9
        total += v
    return total % 10 == 0


def _kid_mod11_gyldig(sifre: str) -> bool:
    vekter = [2, 3, 4, 5, 6, 7]
    total = sum(int(t) * vekter[i % 6]
                for i, t in enumerate(reversed(sifre[:-1])))
    k = 11 - (total % 11)
    if k == 11:
        k = 0
    return k != 10 and k == int(sifre[-1])


def er_gyldig_kid(nr: str) -> bool:
    """Norsk KID: 3–25 sifre der siste er kontrollsiffer etter mod10
    (Luhn) ELLER mod11 — betalingsmottakere bruker begge."""
    if not nr or not nr.isdigit() or not (3 <= len(nr) <= 25):
        return False
    return _luhn_gyldig(nr) or _kid_mod11_gyldig(nr)


def _unike(verdier) -> list:
    ut, sett = [], set()
    for v in verdier:
        if v not in sett:
            sett.add(v)
            ut.append(v)
    return ut


# TRÅDLOKAL: serveren er en ThreadingHTTPServer, og denne bufferen
# styrer hvilke sifferkandidater som blir fødselsnummer og hvilke som
# blir kontonummer. Som én delt global — skrevet med update() og lest
# tilbake i neste setning — kunne tråd A returnere tråd B sine områder,
# og da påvirker ett dokument uttrekket i et annet. Én bøtte per tråd
# fjerner både kappløpet og behovet for en lås.
_opptatt_lokal = threading.local()


def _opptatte_omraader(tekst: str) -> tuple:
    """Tegnområder som ALLEREDE er tolket som noe annet enn en
    identifikator: datoer og kronebeløp. Brukes til å hindre at
    sifferskanningen limer nabotall sammen over en slik grense.

    Enkelt-nivås buffer: strukturert_uttrekk kaller fire
    identifikatorfunksjoner på samme tekst, og alle trenger det samme."""
    nokkel = (len(tekst), hash(tekst))
    if getattr(_opptatt_lokal, "nokkel", None) == nokkel:
        return _opptatt_lokal.omraader
    omraader = [(s, sl) for s, sl, *_ in _alle_datotreff(tekst)]
    for m in re.finditer(
            r"(?:kr\.?|NOK)\s?(?:" + _BELOP_TALL + r")|"
            r"\b[\d]{1,3}(?:[ .]\d{3})+(?:,\d{2}|,-)|"
            + _BELOP_ETTER, tekst, re.IGNORECASE):
        omraader.append((m.start(), m.end()))
    omraader = tuple(omraader)
    _opptatt_lokal.nokkel = nokkel
    _opptatt_lokal.omraader = omraader
    # returner den LOKALE verdien, ikke et oppslag i bufferen: da kan
    # svaret ikke bli et annet dokuments områder uansett hva som skjer
    # mellom skriving og lesing
    return omraader


def _tallkandidater(tekst: str, lengde: int):
    """Alle sifferstrenger av gitt lengde uansett gruppering — «123456
    789 10», «1234.56.78910» og «12345678910» er samme kandidat.

    VAKT: kandidaten forkastes hvis den overlapper en DATO eller et
    BELØP. Mønsteret tillater et skilletegn mellom hvert sifferpar og
    skilte derfor ikke mellom sifre i SAMME tall og to NABOTALL:
    «Vedtak datert 01.01.2024 114 kroner» ble limt til «12345678910»,
    som består mod11 — og ble rapportert som et gyldig FØDSELSNUMMER.
    Det oppdiktede nummeret gikk videre inn i prompten merket
    «KONTROLLERT av kode (sjekksum/format)» og havnet i fnr-feltet i
    skjemautfyllingen, der nettopp den merkingen desarmerer den
    menneskelige kontrollen. Tilsvarende ble «kr 103 456 789» til et
    «organisasjonsnummer». Entallsvarianten finn_fodselsnummer har alltid
    hatt det stramme mønsteret (6+5) og fant ingen av delene — dette var
    en inkonsistens, ikke et bevisst design."""
    for kompakt, _, _ in _tallkandidater_med_posisjon(tekst, lengde):
        yield kompakt


def _opptattindeks(tekst: str):
    """(startpunkter, løpende maks sluttpunkt) for de opptatte områdene.

    Sortert på start, med et prefiksmaksimum over sluttpunktene — da kan
    «overlapper denne kandidaten noe?» besvares med ett binærsøk i
    stedet for en gjennomgang av hele lista. Bufres trådlokalt sammen
    med områdene selv."""
    nokkel = (len(tekst), hash(tekst))
    if getattr(_opptatt_lokal, "indeksnokkel", None) == nokkel:
        return _opptatt_lokal.starter, _opptatt_lokal.maks_slutt
    omraader = sorted(_opptatte_omraader(tekst))
    starter, maks_slutt, hittil = [], [], 0
    for start, slutt in omraader:
        hittil = max(hittil, slutt)
        starter.append(start)
        maks_slutt.append(hittil)
    _opptatt_lokal.indeksnokkel = nokkel
    _opptatt_lokal.starter = starter
    _opptatt_lokal.maks_slutt = maks_slutt
    return starter, maks_slutt


def _tallkandidater_med_posisjon(tekst: str, lengde: int):
    """Som _tallkandidater, men yielder (kompakt, start, slutt) — samme
    mønster og samme dato-/beløpsvakt, slik at sladding og feltuttrekk
    aldri kan være uenige om hva som er en identifikator."""
    # Overlappsjekken var lineær PER KANDIDAT, og både kandidatene og
    # de opptatte områdene vokser med teksten — altså O(n²). Målt vekst
    # per dobling av teksten: 4,08× (2,0× er lineært). En bunke på
    # 117 000 tegn brukte 248 ms bare her.
    #
    # Områdene sorteres én gang og slås opp med binærsøk: finn siste
    # område som STARTER før kandidaten slutter, og sjekk om det (eller
    # det maksimale sluttpunktet så langt) rekker forbi kandidatens
    # start. Samme svar, O(log n) per kandidat.
    starter, maks_slutt = _opptattindeks(tekst)
    for treff in re.finditer(r"(?<!\d)\d(?:[ .]?\d)+(?!\d)", tekst):
        i = bisect.bisect_left(starter, treff.end())
        if i and maks_slutt[i - 1] > treff.start():
            continue
        kompakt = re.sub(r"[ .]", "", treff.group(0))
        if len(kompakt) == lengde:
            yield kompakt, treff.start(), treff.end()


# Etiketter som avgjør hva et 11-sifret tall ER når BEGGE sjekksummene
# stemmer. Reelt tilfelle fra testbunken: refusjonskontoen 12345678910
# består OGSÅ fnr-kontrollen (gyldig som D-nummer), så fnr-presedensen
# «stjal» den — den ble rapportert som fødselsnummer og MANGLET i
# kontonummerlista. Etiketten («kontonummer:») foran står i dokumentet
# og er beviset; uten etikett gjelder fnr-presedensen som før.
_KONTO_ETIKETT = re.compile(r"konto(?:nummer|nr)?[.:\s]*$", re.IGNORECASE)
_FNR_ETIKETT = re.compile(
    r"(?:f(?:ø|oe?)dselsnummer|fnr|personnummer|d-?nummer)[.:\s]*$",
    re.IGNORECASE)


def _ellevesiffer_type(tekst: str, start: int, kompakt: str):
    """«fodselsnummer», «kontonummer» eller None for en 11-sifret
    kandidat — etiketten foran vinner når begge sjekksummene stemmer."""
    fnr_ok = er_gyldig_fnr(kompakt)
    konto_ok = er_gyldig_kontonummer(kompakt)
    if fnr_ok and konto_ok:
        forfelt = tekst[max(0, start - 28):start]
        if _KONTO_ETIKETT.search(forfelt):
            return "kontonummer"
        return "fodselsnummer"
    if fnr_ok:
        return "fodselsnummer"
    if konto_ok:
        return "kontonummer"
    return None


def finn_alle_fodselsnummer(tekst: str) -> list:
    return _unike(
        k for k, start, _ in _tallkandidater_med_posisjon(tekst, 11)
        if _ellevesiffer_type(tekst, start, k) == "fodselsnummer")


def finn_alle_kontonummer(tekst: str) -> list:
    return _unike(
        k for k, start, _ in _tallkandidater_med_posisjon(tekst, 11)
        if _ellevesiffer_type(tekst, start, k) == "kontonummer")


def finn_alle_organisasjonsnummer(tekst: str) -> list:
    return _unike(k for k in _tallkandidater(tekst, 9) if er_gyldig_orgnr(k))


# «KID», «KID-nummer», «KIDnummer», «KID nr.» — alle formene som står på
# norske fakturaer. Uten «nummer/nr»-varianten fant vi bare KID-en på
# fakturaer som TILFELDIGVIS også har en bar «KID:»-linje (målt på
# testbunken: «KID-nummer 1002345678911» ga ingen treff alene).
_KID_ETIKETT = r"(?i)\bkid[\s-]*(?:nummer|nr\.?)?[.:\s-]*"


def finn_alle_kid(tekst: str) -> list:
    """KID krever etikett i konteksten — et rent tall uten «KID» ved
    siden av er for tvetydig til å påstås å være KID."""
    ut = []
    for treff in re.finditer(_KID_ETIKETT + r"((?:\d[ .]?){2,30}\d)", tekst):
        kompakt = re.sub(r"[ .]", "", treff.group(1))
        if er_gyldig_kid(kompakt):
            ut.append(kompakt)
    return _unike(ut)


def finn_alle_telefoner(tekst: str) -> list:
    """Alle norske telefonnumre (8 sifre, ev. +47, parvis eller 3-2-3).
    Deler skanner (og dermed vakter) med finn_telefon og sladdingen."""
    return _unike(nummer for _, _, nummer in _telefon_treff(tekst))


def finn_alle_eposter(tekst: str) -> list:
    return _unike(re.findall(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b", tekst))


# ------------------------------------------------------------------ #
#  Sladding — kun det som kan BEVISES                                  #
# ------------------------------------------------------------------ #

# Typene sladderen kan fjerne. Alle er sjekksum-/formatvaliderte — navn
# og adresser er BEVISST utelatt: de kan ikke bevises deterministisk
# (NER er fjernet), og en gjettet sladding som ser fullført ut er
# farligere enn ingen sladding.
SLADD_TYPER = ("fodselsnummer", "kontonummer", "organisasjonsnummer",
               "kid", "telefon", "epost")


# Etikett + tallet som følger. Brukes til å finne kandidater som er
# TYDELIG merket, men som ikke består kontrollsifferet — og derfor blir
# stående usladdet.
_MERKEDE_KANDIDATER = (
    ("kontonummer", r"(?i)\bkonto(?:nummer|nr\.?)?[.:\s]*"),
    ("fodselsnummer",
     r"(?i)\b(?:f(?:ø|oe?)dselsnummer|fnr|personnummer|d-?nummer)[.:\s]*"),
    ("organisasjonsnummer",
     r"(?i)\b(?:organisasjonsnummer|orgnr\.?|org\.?\s*nr\.?)[.:\s]*"),
    ("kid", _KID_ETIKETT),
)


def finn_mistenkt_usladdet(tekst: str, omraader=None) -> list:
    """Identifikatorer som er TYDELIG merket, men ikke ble sladdet.

    Dette er hullet i sladdingen, gjort maskinlesbart. `sladd_tekst`
    fjerner bare det den kan BEVISE — mod11 for fødselsnummer, konto og
    orgnr, mod10/11 for KID. Består ikke kontrollsifferet, emitteres
    ingen område, og etiketten ved siden av blir aldri konsultert.

    Målt: et dokument med fem merkede identifikatorer der fire feilet
    sjekksummen ga `ok: true`, `advarsler: []` og et `funn` som bare
    listet de to som FAKTISK ble fjernet. Hvert maskinlesbart felt så
    like friskt ut som på et rent dokument — den eneste måten å oppdage
    lekkasjen på var å lese teksten selv, altså å gjøre sladdingen om
    igjen.

    Et treff her betyr ikke at nummeret er ekte: det kan være en
    skrivefeil, et utenlandsk format, eller en OCR-feillesning. Men det
    betyr at noe som SER ut som en identifikator står igjen — og det er
    klienten som må avgjøre hva den gjør med det.

    `omraader` er sladdeområdene som alt er funnet; treff som ligger
    inne i dem er allerede fjernet og tas ikke med."""
    sladdet = [(s, e) for s, e, _ in (omraader or [])]

    def er_sladdet(start, slutt):
        return any(s <= start and slutt <= e for s, e in sladdet)

    ut = []
    for type_, etikett in _MERKEDE_KANDIDATER:
        for treff in re.finditer(etikett + r"((?:\d[ .-]?){4,30}\d)", tekst):
            start, slutt = treff.start(1), treff.end(1)
            if er_sladdet(start, slutt):
                continue
            kompakt = re.sub(r"[ .-]", "", treff.group(1))
            gyldig = {
                "kontonummer": er_gyldig_kontonummer,
                "fodselsnummer": er_gyldig_fnr,
                "organisasjonsnummer": er_gyldig_orgnr,
                "kid": er_gyldig_kid,
            }[type_]
            if gyldig(kompakt):
                continue          # gyldig og usladdet ⇒ typen var valgt bort
            ut.append({
                "type": type_,
                "etikett": treff.group(0)[:len(treff.group(0))
                                          - len(treff.group(1))].strip(),
                "posisjon": start,
                "lengde": len(kompakt),
                "grunn": ("feil_lengde" if len(kompakt) not in (9, 11)
                          and type_ != "kid" else "kontrollsiffer_feilet"),
            })
    ut.sort(key=lambda p: p["posisjon"])
    return ut


def finn_sladdeomraader(tekst: str, typer=None) -> list:
    """Tegnområder som skal sladdes: [(start, slutt, type), …], sortert
    og uten overlapp.

    Gjenbruker NØYAKTIG samme mønstre og vakter som finnerne — spesielt
    dato-/beløpsvakten fra _tallkandidater, så «01.01.2024 114 kroner»
    aldri kan sladdes som et «fødselsnummer». En falsk positiv i
    sladding FJERNER lovlig innhold, så vaktene er like viktige her som
    i uttrekket.

    Ved overlapp (et KID-nummer som også består kontonummer-kontrollen)
    beholdes området som starter først; ved samme start det lengste.
    Typemerkingen kan da variere, men sladdet blir det uansett."""
    valgte = set(typer or SLADD_TYPER)
    funn = []
    if {"fodselsnummer", "kontonummer"} & valgte:
        for kompakt, start, slutt in _tallkandidater_med_posisjon(tekst, 11):
            type_ = _ellevesiffer_type(tekst, start, kompakt)
            if type_ in valgte:
                funn.append((start, slutt, type_))
    if "organisasjonsnummer" in valgte:
        for kompakt, start, slutt in _tallkandidater_med_posisjon(tekst, 9):
            if er_gyldig_orgnr(kompakt):
                funn.append((start, slutt, "organisasjonsnummer"))
    if "kid" in valgte:
        # Kun selve nummeret sladdes — «KID»-etiketten står igjen, så
        # leseren ser at det STO et KID der. Samme etikettmønster som
        # finn_alle_kid, så de aldri kan være uenige.
        for treff in re.finditer(_KID_ETIKETT + r"((?:\d[ .]?){2,30}\d)",
                                 tekst):
            if er_gyldig_kid(re.sub(r"[ .]", "", treff.group(1))):
                funn.append((treff.start(1), treff.end(1), "kid"))
    if "telefon" in valgte:
        # NØYAKTIG samme skanner som finn_telefon/finn_alle_telefoner
        for start, slutt, _ in _telefon_treff(tekst):
            funn.append((start, slutt, "telefon"))
    if "epost" in valgte:
        for treff in re.finditer(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b", tekst):
            funn.append((treff.start(), treff.end(), "epost"))

    # Fjern overlapp: først i teksten vinner; ved samme start den lengste
    funn.sort(key=lambda o: (o[0], -(o[1] - o[0])))
    rene, siste_slutt = [], -1
    for start, slutt, type_ in funn:
        if start >= siste_slutt:
            rene.append((start, slutt, type_))
            siste_slutt = slutt
    return rene


def sladd_tekst(tekst: str, typer=None):
    """Sladder alle beviste identifikatorer i teksten.

    Returnerer (sladdet_tekst, antall_per_type). Hvert funn erstattes
    med «[SLADDET type]» — synlig sladd, ikke stille fjerning: leseren
    skal SE at noe er tatt bort, og hva slags noe det var."""
    omraader = finn_sladdeomraader(tekst or "", typer)
    ut = tekst or ""
    antall: dict = {}
    # Bakfra, så posisjonene foran ikke forskyves av erstatningene
    for start, slutt, type_ in reversed(omraader):
        ut = ut[:start] + "[SLADDET " + type_ + "]" + ut[slutt:]
        antall[type_] = antall.get(type_, 0) + 1
    return ut, antall


def finn_alle_belop(tekst: str, maks: int = 100) -> list:
    """Alle kronebeløp med kontekst — verdier som tall (float)."""
    ut = []
    for treff in re.finditer(
        r"(?:kr\.?|NOK)\s?(" + _BELOP_TALL + r")|"
        r"\b([\d]{1,3}(?:[ .]\d{3})+(?:,\d{2}|,-))|"
        r"\b(\d{1,6},\d{2})\b|"
        + _BELOP_ETTER,
        tekst, re.IGNORECASE,
    ):
        raa = _o_til_null(
            (treff.group(1) or treff.group(2) or treff.group(3)
             or treff.group(4)).strip())
        verdi = _normaliser_belop(raa)
        if verdi is None:
            continue
        kontekst = " ".join(
            tekst[max(0, treff.start() - 35):treff.end() + 15].split())
        ut.append({"verdi": verdi, "raatekst": treff.group(0).strip(),
                   "kontekst": kontekst})
        if len(ut) >= maks:
            break
    return ut


def finn_koder_med_kontekst(tekst: str, maks: int = 25) -> list:
    """Frittstående tall (4–10 sifre) og alfanumeriske koder, hver med
    sin kontekst — generelt grunnlag for å plassere identifikatorer i
    riktige felter (produktnummer vs aktiveringskode vs ordrenummer)."""
    ut, sett = [], set()
    for monster in (r"(?<!\d)\d{4,10}(?!\d)",
                    r"\b(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]{6,12}\b"):
        for treff in re.finditer(monster, tekst):
            verdi = treff.group(0)
            if verdi in sett:
                continue
            sett.add(verdi)
            kontekst = " ".join(
                tekst[max(0, treff.start() - 35):treff.end() + 20].split())
            ut.append({"verdi": verdi, "kontekst": kontekst})
            if len(ut) >= maks:
                return ut
    return ut


# Selskapsformer som følger et FIRMANAVN, ikke et postnummer. Uten dem
# ble «Rema 1000 AS» lest som postnummer 1000 i poststedet AS.
_SELSKAPSFORM = {"AS", "ASA", "ANS", "DA", "BA", "SA", "NUF", "AB", "KS"}

# En gateadresse: ord, så husnummer til slutt («Storgata 12», «Storgata
# 12B», «Postboks 123»). Kolon utelukker den — «Fnr: 12345678910» og
# «Telefon: 22 22 22 22» er merkede felter, ikke adresser.
_GATEADRESSE = re.compile(
    r"^[A-ZÆØÅa-zæøå][A-Za-zÆØÅæøå.'\- ]{2,40}\s\d{1,4}\s?[A-Za-z]?$")


def finn_adresser(tekst: str) -> list:
    """Alle postnummer/poststed-forekomster, med gateadresse fra linjen
    over når den FAKTISK ligner en gate.

    To feller styres unna, begge sett i ekte NAV-brev:

    1) «Rema 1000 AS» er ikke postnummer 1000 i poststed AS. Et norsk
       postnummer står først på linja eller etter komma — aldri klistret
       inntil et ord — og et poststed er ikke en selskapsform.
    2) Linja over postnummeret er ikke automatisk en gate. Uten en
       formsjekk ble «Fnr: 12345678910» gateadressen til mottakeren,
       og en klient som fylte et adressefelt fikk et fødselsnummer."""
    ut, sett = [], set()
    for treff in re.finditer(
        r"(?:(?<=^)|(?<=[,\-–]\s)|(?<=[,\-–]))[ \t]*"
        r"\b(\d{4})[ \t]+([A-ZÆØÅ][a-zæøåA-ZÆØÅ]+"
        r"(?:[ \t][iI][ \t][A-ZÆØÅ][a-zæøåA-ZÆØÅ]+)?)\b",
        tekst, re.MULTILINE
    ):
        postnummer, poststed = treff.group(1), treff.group(2)
        if poststed.upper() in _SELSKAPSFORM:
            continue
        linje_start = tekst.rfind("\n", 0, treff.start()) + 1
        gate = ""
        # gata kan stå PÅ samme linje, foran postnummeret («Storgata 12,
        # 0181 OSLO») eller på linja over
        foran = tekst[linje_start:treff.start()].strip().rstrip(",-–").strip()
        # «Adresse: Storgata 12, 0181 OSLO» — etiketten foran er ikke en
        # del av gata, men gata er fortsatt en gate
        foran = re.sub(r"^[A-Za-zÆØÅæøå ]{0,25}:\s*", "", foran)
        if _GATEADRESSE.match(foran):
            gate = foran
        elif linje_start > 1:
            forrige_start = tekst.rfind("\n", 0, linje_start - 1) + 1
            forrige = tekst[forrige_start:linje_start - 1].strip()
            if _GATEADRESSE.match(forrige):
                gate = forrige
        nokkel = (gate, postnummer, poststed)
        if nokkel not in sett:
            sett.add(nokkel)
            # Tom streng er IKKE «ingen gate» — den ser ut som en verdi.
            # R118: tomt er null. Målt på en ekte bunke ga «Postboks 6600
            # Etterstad, 0607 OSLO» adressen {"gate": "", …}, og en
            # RPA-robot som skrev gata inn i et felt fikk en tom rubrikk
            # i stedet for et hull den kunne oppdage.
            ut.append({"gate": gate or None, "postnummer": postnummer,
                       "poststed": poststed})
    return ut


# Dokumenttyper med kjennetegn — poengsum avgjør, "" hvis intet treffer
_DOKUMENTTYPER = [
    ("faktura", r"faktura|forfallsdato|\bkid\b"),
    ("kvittering", r"kvittering|betaling mottatt|kj[øo]pskvittering"),
    ("vedtak", r"\bvedtak"),
    ("soknad", r"s[øo]knad"),
    # sentrale NAV-dokumenttyper: uten dem ble en legeerklæring og en
    # inntektsmelding stående som «vedtak» fordi ordet vedtak fantes et
    # sted i teksten
    ("legeerklaring", r"legeerkl(?:æ|ae|a)ring"),
    ("inntektsmelding", r"inntektsmelding"),
    ("sykmelding", r"sykmelding|sjukmelding"),
    ("klage", r"\bklage[nr]?\b|\bklagar\b|klage p(?:å|aa|a)"),
    ("egenerklaring", r"egenerkl(?:æ|ae|a)ring"),
    ("meldekort", r"meldekort"),
    ("pensjonsbrev", r"pensjonsbrev"),
    ("attest", r"\battest"),
    ("kontrakt", r"kontrakt|l[æa]rekontrakt|avtale"),
    ("boardingkort", r"boardingkort|boarding"),
    ("brev", r"med vennlig hilsen|kj[æa]re"),
]

# Lesbart navn per dokumenttype. Samme mønster som _TYPE_TERM for datoer:
# koden er stabil (en klient forgrener på «legeerklaring» uten å hardkode
# en norsk streng), termen er for et menneske. Kodene er uten æøå fordi
# de matches mot OCR-tekst; termen har dem.
#
# Hver kode i _DOKUMENTTYPER SKAL ha en term her — en vakttest feiler
# ellers, så en ny type ikke stille faller tilbake til koden.
DOKUMENTTYPE_TERM = {
    "faktura": "Faktura",
    "kvittering": "Kvittering",
    "vedtak": "Vedtak",
    "soknad": "Søknad",
    "legeerklaring": "Legeerklæring",
    "inntektsmelding": "Inntektsmelding",
    "sykmelding": "Sykmelding",
    "klage": "Klage",
    "egenerklaring": "Egenerklæring",
    "meldekort": "Meldekort",
    "pensjonsbrev": "Pensjonsbrev",
    "attest": "Attest",
    "kontrakt": "Kontrakt",
    "boardingkort": "Boardingkort",
    "brev": "Brev",
}


# Tittelen veier tyngre enn brødteksten: den sier hva dokumentet ER.
# «Vedtak om dagpenger» med et beløp og en forfallsdato lenger nede ble
# ellers klassifisert som FAKTURA, fordi to svake treff i teksten slo
# ett sterkt treff i overskriften.
_TITTELVEKT = 5
_TITTELLINJER = 2

# «Forfallsdato: 24.06.2026» er et FELT, ikke en tittel. Uten denne
# utelukkelsen havnet feltlinjene i tittelen, og et vedtaksbrev ble
# klassifisert som faktura fordi «forfallsdato» sto der.
_FELTLINJE = re.compile(r"^[\w æøåÆØÅ./-]{2,30}:\s*\S")


def _tittelen(tekst: str) -> str:
    """De første linjene med et TITTEL-preg: ikke tomme, ikke
    sidemarkører, ikke merkede felter."""
    linjer = []
    for linje in (tekst or "").splitlines():
        linje = linje.strip()
        if (not linje
                or re.match(r"^\[Side \d+ av \d+\]$", linje)
                or _FELTLINJE.match(linje)):
            continue
        linjer.append(linje)
        if len(linjer) >= _TITTELLINJER:
            break
    return "\n".join(linjer)


def gjett_dokumenttype(tekst: str) -> str:
    """Dokumentets type, avgjort av TITTELEN når den sier noe.

    Rekkefølgen i tittelen avgjør: «Klage på vedtak om …» er en KLAGE,
    ikke et vedtak — dokumentets egen art står først, og det den handler
    OM kommer etter. Teller vi i stedet forekomster, vinner «vedtak»,
    fordi en klage nevner vedtaket den klager på mange ganger."""
    tittel = _tittelen(tekst)
    i_tittel = []
    for navn, monster in _DOKUMENTTYPER:
        treff = re.search(monster, tittel, re.IGNORECASE)
        if treff:
            i_tittel.append((treff.start(), -len(treff.group(0)), navn))
    if i_tittel:
        return min(i_tittel)[2]

    # Ingen type i tittelen: da får brødteksten bestemme, som før
    beste, beste_poeng = "", 0
    for navn, monster in _DOKUMENTTYPER:
        poeng = len(re.findall(monster, tekst, re.IGNORECASE))
        if poeng > beste_poeng:
            beste, beste_poeng = navn, poeng
    return beste


def gjett_sprak(tekst: str) -> str:
    lav = f" {tekst.lower()} "
    norsk = sum(lav.count(f" {ord} ")
                for ord in ("og", "i", "på", "det", "som", "til", "er", "av"))
    engelsk = sum(lav.count(f" {ord} ")
                  for ord in ("the", "and", "of", "to", "is", "for"))
    if norsk >= 2 and norsk > engelsk:
        return "norsk"
    if engelsk >= 2 and engelsk > norsk:
        return "engelsk"
    return ""


def strukturert_uttrekk(tekst: str, datoer=None) -> dict:
    """Komplett strukturert uttrekk av ALT som kan finnes i tekst fra
    NAV-dokumenter. Alle nøkler er alltid til stede — tomt er "" / [].

    `datoer` lar en kaller som ALLEREDE har klassifisert datoene levere
    dem inn. Målt gikk `klassifiser_datoer` tre ganger over samme tekst
    i én forespørsel: her, i `dokumentdato_av`, og i konteksten som
    eier begge. På en 200-siders bunke er hver runde ~38 ms.

    Argumentet er valgfritt med uendret oppførsel når det utelates —
    de andre kallstedene (sjekk_miljo, testene) skal ikke trenge å vite
    om denne optimaliseringen."""
    tekst = tekst or ""
    datoer = klassifiser_datoer(tekst) if datoer is None else datoer

    perioder = []
    venter = None
    for d in datoer:
        if d["type"] == "periode_start":
            venter = d["dato"]
        elif d["type"] == "periode_slutt" and venter:
            perioder.append({"fra": venter, "til": d["dato"]})
            venter = None

    forste_linje = next(
        (l.strip() for l in tekst.splitlines()
         if l.strip() and not re.match(r"\[Side \d+ av \d+\]", l.strip())),
        "")

    # TOMT ER null, IKKE «». Blokka brukte tom streng der profilen
    # bruker null — for NØYAKTIG samme faktum, i samme svar:
    #
    #     struktur.dokument.ytelse     ""
    #     dokumentprofil.ytelse.navn.kode   null
    #
    # To konvensjoner for «finnes ikke» i én JSON-kropp. R126 sier det
    # rett ut: en tom streng SER ut som en verdi. En klient som tester
    # `if (ytelse)` får falsk for begge, men `!= null` i C#/.NET er sant
    # for «» — og da tror roboten den fant en ytelse.
    return {
        "dokument": {
            "tittel": forste_linje[:100] or None,
            "dokumenttype": gjett_dokumenttype(tekst) or None,
            "sprak": gjett_sprak(tekst) or None,
            "kontornavn": finn_kontornavn(tekst) or None,
            "fylke": finn_fylke(tekst) or None,
            "ytelse": finn_ytelse(tekst) or None,
        },
        "identifikatorer": {
            "fodselsnummer": finn_alle_fodselsnummer(tekst),
            "kontonummer": finn_alle_kontonummer(tekst),
            "organisasjonsnummer": finn_alle_organisasjonsnummer(tekst),
            "kid": finn_alle_kid(tekst),
            "saksnummer": finn_saksnummer(tekst) or None,
        },
        "kontakt": {
            "telefoner": finn_alle_telefoner(tekst),
            "eposter": finn_alle_eposter(tekst),
        },
        "adresser": finn_adresser(tekst),
        "datoer": datoer,
        "perioder": perioder,
        "belop": finn_alle_belop(tekst),
    }


# ------------------------------------------------------------------ #
#  Sammenslåing med modell-uttrekk                                     #
# ------------------------------------------------------------------ #

def utvid_entiteter(tekst: str, entiteter: dict) -> dict:
    """
    Beriker modell-entiteter med alle deterministiske felter.
    Presedens: sjekksum-/mønsterfelter overstyrer modellen (matematikk
    slår gjetning); navn beholdes fra modellen (fritekst).
    """
    resultat = dict(entiteter or {})

    deterministiske = {
        "fodselsnummer": finn_fodselsnummer(tekst),
        "kontonummer":   finn_kontonummer(tekst),
        # Orgnr og KID er sjekksumvaliderte (mod11) på lik linje med fnr og
        # kontonummer, men manglet her — så en mal med {organisasjonsnummer}
        # fikk null fra «felter»-motoren og måtte overlates til modellen,
        # enda koden kunne BEVISE nummeret. KID krever i tillegg en
        # «KID»-etikett i teksten, så et løst tall kan aldri bli KID.
        "organisasjonsnummer": (finn_alle_organisasjonsnummer(tekst)
                                or [None])[0],
        "kid":           (finn_alle_kid(tekst) or [None])[0],
        "dato":          finn_dato(tekst),
        "forfallsdato":  finn_forfallsdato(tekst),
        "telefon":       finn_telefon(tekst),
        "epost":         finn_epost(tekst),
        "belop":         finn_belop(tekst),
        "totalbelop":    finn_totalbelop(tekst),
        "saksnummer":    finn_saksnummer(tekst),
        "kontornavn":    finn_kontornavn(tekst),
    }
    for felt, verdi in deterministiske.items():
        if verdi is not None:
            resultat[felt] = verdi

    postnummer, poststed = finn_postnummer_sted(tekst)
    if postnummer:
        resultat["postnummer"] = postnummer
        resultat["poststed"] = poststed

    # Anti-hallusinasjon: modellverdier for sjekksumfelter må bestå samme
    # matematikk som de deterministiske — ellers forkastes de. (De
    # deterministiske treffene over er allerede validert, så dette rammer
    # kun ukontrollerte modellverdier.)
    fnr_verdi = re.sub(r"\D", "", str(resultat.get("fodselsnummer") or ""))
    if resultat.get("fodselsnummer") and not er_gyldig_fnr(fnr_verdi):
        resultat.pop("fodselsnummer")
    konto_verdi = re.sub(r"\D", "", str(resultat.get("kontonummer") or ""))
    if resultat.get("kontonummer") and not er_gyldig_kontonummer(konto_verdi):
        resultat.pop("kontonummer")
    orgnr_verdi = re.sub(r"\D", "",
                         str(resultat.get("organisasjonsnummer") or ""))
    if (resultat.get("organisasjonsnummer")
            and not er_gyldig_orgnr(orgnr_verdi)):
        resultat.pop("organisasjonsnummer")
    kid_verdi = re.sub(r"\D", "", str(resultat.get("kid") or ""))
    if resultat.get("kid") and not er_gyldig_kid(kid_verdi):
        resultat.pop("kid")

    # F3-2: mønsterfelter der deterministisk søk ikke fant noe, men modellen
    # likevel leverte en verdi — verifiser modellverdien mot samme format,
    # ellers forkast (hindrer hallusinert telefon/epost/dato/beløp/saksnr).
    _mønster_validatorer = {
        "telefon":    lambda v: bool(re.fullmatch(r"\+?\d[\d ]{6,14}", v.strip())),
        "epost":      lambda v: bool(re.fullmatch(r"[\w.+-]+@[\w-]+\.[\w.]{2,}", v.strip())),
        "dato":       lambda v: finn_dato(v) is not None,
        "forfallsdato": lambda v: finn_dato(v) is not None,
        "saksnummer": lambda v: finn_saksnummer(f"saksnr {v}") is not None
                                or bool(re.search(r"\d", v)),
    }
    for felt, gyldig in _mønster_validatorer.items():
        verdi = resultat.get(felt)
        # deterministisk treff (allerede satt over) er alltid gyldig; kun
        # felter som IKKE ble satt deterministisk kan komme fra modellen
        if verdi is not None and deterministiske.get(felt) is None:
            try:
                if not gyldig(str(verdi)):
                    resultat.pop(felt)
            except Exception:
                resultat.pop(felt)
    # beløp: modellverdi må være tallbar
    for beløpsfelt in ("belop", "totalbelop"):
        if (resultat.get(beløpsfelt) is not None
                and deterministiske.get(beløpsfelt) is None):
            try:
                float(str(resultat[beløpsfelt])
                      .replace(",", ".").replace(" ", ""))
            except (ValueError, TypeError):
                resultat.pop(beløpsfelt)

    # kontornavn betyr NAV-kontor — alt annet er en organisasjon, ikke kontor
    if resultat.get("kontornavn") and not str(resultat["kontornavn"]).upper().startswith("NAV"):
        resultat.pop("kontornavn")

    # Whitelist-baserte felter: gyldig modellverdi beholdes; ugyldig
    # erstattes av deterministisk treff fra teksten, eller forkastes helt.
    if str(resultat.get("ytelse", "")).lower() not in NORSKE_YTELSER:
        ytelse = finn_ytelse(tekst)
        if ytelse:
            resultat["ytelse"] = ytelse
        else:
            resultat.pop("ytelse", None)

    # fylke må både være et ekte fylke OG faktisk stå i teksten —
    # et fylke modellen ikke kan kildeføre er gjetning.
    fylke = finn_fylke(tekst)
    if fylke:
        resultat["fylke"] = fylke
    elif "fylke" in resultat:
        resultat.pop("fylke")

    return resultat


# ------------------------------------------------------------------ #
#  Deterministisk malfletting — {feltnavn} fylt UTEN modell           #
# ------------------------------------------------------------------ #
#  Hver klient sender sitt EGET JSON-format der verdiene er            #
#  plassholdere som «{telefon}». flett_mal bytter dem mot de           #
#  deterministisk funnede verdiene. Ingen modell, ingen venting: like  #
#  raskt som felter, men klienten bestemmer selv feltnavn og oppsett.  #


def felter_flatt(tekst: str, ocr_brukt: bool = False) -> dict:
    """Flat oppslagstabell {feltnavn: verdi} over ALLE deterministiske
    felter, til bruk i malfletting. Verdiene beholder sin egen type: et
    tall forblir tall, et felt som mangler blir None (→ null i JSON).

    Dette er kilden plassholderne i en mal fylles fra. Navnene her er
    kontrakten klienten skriver mot — hold dem stabile."""
    ent = utvid_entiteter(tekst, {})
    klassifiserte = klassifiser_datoer(tekst)
    dd = finn_dokumentdato(klassifiserte, ocr_brukt=ocr_brukt)
    # «periode_start» betydde her BUNKESPENNET (dd["periode"]) mens
    # dokumentprofilen brukte samme navn om perioden dokumentet GJELDER
    # FOR. Samme svar kunne si 2026-04-02 i profilen og 01.08.2019 i
    # «{periode_start}». Begge henter nå fra gjelder_periode; spennet har
    # fått sine egne navn så ingenting går tapt.
    periode = gjelder_periode(klassifiserte) or {}
    spenn = dd.get("periode") or {}
    alder = dokumentets_alder(dd.get("dato")) if dd.get("dato") else None

    flat = {
        # personopplysninger / kontakt
        "telefon": ent.get("telefon"),
        "epost": ent.get("epost"),
        "fodselsnummer": ent.get("fodselsnummer"),
        "kontonummer": ent.get("kontonummer"),
        "organisasjonsnummer": ent.get("organisasjonsnummer"),
        "kid": ent.get("kid"),
        # adresse
        "postnummer": ent.get("postnummer"),
        "poststed": ent.get("poststed"),
        "fylke": ent.get("fylke"),
        # sak / ytelse / kontor
        "saksnummer": ent.get("saksnummer"),
        "ytelse": ent.get("ytelse"),
        "kontornavn": ent.get("kontornavn"),
        # beløp — «belop» er FØRSTE beløp i teksten, «totalbelop» det på
        # en Total-/Sum-linje. På en kvittering er de forskjellige (pris
        # vs. sum); klienten velger hvilket malen skal fylles med.
        "belop": ent.get("belop"),
        "totalbelop": ent.get("totalbelop"),
        # datoer
        "dato": ent.get("dato"),
        "forfallsdato": ent.get("forfallsdato"),
        "dokumentdato": dd.get("dato"),
        "dokumentdato_type": dd.get("type"),
        "dokumentdato_kilde": dd.get("kilde"),
        "dokumentdato_konfidens": dd.get("konfidens"),
        "periode_start": periode.get("fra"),
        "periode_slutt": periode.get("til"),
        # datospennet i en BUNKE — et annet begrep, egne navn
        "dokumentspenn_fra": spenn.get("fra"),
        "dokumentspenn_til": spenn.get("til"),
        "alder_dager": alder.get("dager") if alder else None,
    }
    return flat


# «{telefon}» eller «{ telefon }» — ett feltnavn i krøllparenteser
_PLASSHOLDER = re.compile(r"\{\s*([a-zA-Z_æøåÆØÅ][\w æøåÆØÅ]*?)\s*\}")


def _flett_streng(verdi: str, flat: dict, ukjente: list):
    """Fyller plassholdere i én malverdi.

    Er verdien NØYAKTIG én plassholder («{telefon}»), returneres den rå
    verdien med sin egen type (tall/None bevart). Er plassholderen vevd
    inn i tekst («Tlf: {telefon}»), gjøres tekstlig innsetting der None
    blir tom streng. En verdi uten plassholder er en konstant klienten
    vil ha uendret, og returneres som den er."""
    full = _PLASSHOLDER.fullmatch(verdi.strip())
    if full:
        navn = full.group(1).strip()
        if navn not in flat:
            ukjente.append(navn)
            return None
        return flat[navn]

    def _bytt(m):
        navn = m.group(1).strip()
        if navn not in flat:
            ukjente.append(navn)
            return ""
        v = flat[navn]
        return "" if v is None else str(v)

    return _PLASSHOLDER.sub(_bytt, verdi)


def refererte_felt(mal) -> list:
    """Alle feltnavn en mal peker på via {feltnavn} — også de som er
    vevd inn i tekst («Ring {telefon}»). Brukes av den hybride motoren
    til å se HVILKE felter malen faktisk trenger, så bare de manglende
    sendes videre til modellen."""
    navn: set = set()

    def _gaa(node):
        if isinstance(node, dict):
            for v in node.values():
                _gaa(v)
        elif isinstance(node, list):
            for v in node:
                _gaa(v)
        elif isinstance(node, str):
            for m in _PLASSHOLDER.finditer(node):
                navn.add(m.group(1).strip())

    _gaa(mal)
    return sorted(navn)


# Hvilke ord i en mal som ber om hvilken identifikatortype.
#
# To lister per type, og skillet er ikke pirk: norsk setter sammen ord.
# «kontonummer» er konto+nummer, men «kontornavn» er kontor+navn — og
# begge inneholder delstrengen «konto». Matchet vi «konto» som
# delstreng, ville en mal som spør om KONTORETS navn fått
# kontonumrene til personen servert til modellen.
#
#   delstreng  entydige, sammensatte ord — trygge hvor som helst
#   helord     korte ord som ER andre ords begynnelse — må stå alene
_IDENTIFIKATORORD = {
    "fodselsnummer": {
        "delstreng": ("fodselsnummer", "fodselsnr", "personnummer",
                      "personnr", "fnummer"),
        "helord": ("fnr", "pnr", "dnr", "dnummer", "id")},
    "kontonummer": {
        "delstreng": ("kontonummer", "kontonr", "bankkonto", "iban"),
        "helord": ("konto",)},
    "organisasjonsnummer": {
        "delstreng": ("organisasjonsnummer", "organisasjonsnr",
                      "orgnummer", "foretaksnummer", "bedriftsnummer"),
        "helord": ("orgnr", "org")},
    "telefonnummer": {
        "delstreng": ("telefonnummer", "telefonnr", "telefon",
                      "mobilnummer", "mobilnr"),
        "helord": ("tlf", "mobil")},
    "epost": {
        "delstreng": ("epost", "email", "eposadresse"),
        "helord": ("mail",)},
}


def _malord(mal) -> tuple:
    """(hele navn, enkeltord) fra en mal — nøkler, tekstverdier og
    plassholdere. Alt normalisert uten æøå og særtegn."""
    hele, ord = set(), set()

    def _ta(raa):
        flat = _uten_saertegn(str(raa)).lower()
        reint = re.sub(r"[^a-z0-9]+", " ", flat).strip()
        if not reint:
            return
        hele.add(reint.replace(" ", ""))
        ord.update(reint.split())

    def _gaa(node):
        if isinstance(node, dict):
            for nokkel, verdi in node.items():
                _ta(nokkel)
                _gaa(verdi)
        elif isinstance(node, list):
            for verdi in node:
                _gaa(verdi)
        elif isinstance(node, str):
            _ta(node)
            for m in _PLASSHOLDER.finditer(node):
                _ta(m.group(1))

    _gaa(mal)
    return hele, ord


def identifikatortyper_i_mal(mal) -> set:
    """Hvilke identifikatortyper malen faktisk spør om.

    Uten dette fikk modellen HVER type servert — også fødselsnummer og
    kontonummer i en mal som bare ba om et beløp. Det er persondata
    sendt til språkmodellen uten at noen ba om dem, og det spiser av
    promptbudsjettet som ellers går til dokumentteksten.

    Ingen treff gir tom mengde: da nevnes ingen identifikatorer i
    prompten i det hele tatt."""
    hele, ord = _malord(mal)
    typer = set()
    for type_, m in _IDENTIFIKATORORD.items():
        if any(n in navn for navn in hele for n in m["delstreng"]):
            typer.add(type_)
        elif ord & set(m["helord"]):
            typer.add(type_)
    return typer


def flett_mal(mal, tekst: str = None, ocr_brukt: bool = False, flat: dict = None):
    """Fyller en klients JSON-mal deterministisk fra dokumentteksten.

    «mal» kan være et objekt eller en liste (vilkårlig nøstet). Hver
    strengverdi tolkes av _flett_streng: «{feltnavn}» byttes mot den
    deterministiske verdien. Andre typer (tall, bool, null) beholdes.

    «flat» kan gis ferdig (f.eks. beriket av den hybride motoren med
    modellfunnede felter); ellers bygges den fra teksten. Returnerer
    (utfylt, rapport) der rapport har «ukjente_felter» (navn i malen som
    ikke finnes) og «tilgjengelige_felter» (alle gyldige navn), så
    klienten raskt ser hva som kan flettes."""
    if flat is None:
        flat = felter_flatt(tekst, ocr_brukt=ocr_brukt)
    ukjente: list = []

    def _gaa(node):
        if isinstance(node, dict):
            return {k: _gaa(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_gaa(v) for v in node]
        if isinstance(node, str):
            return _flett_streng(node, flat, ukjente)
        return node

    utfylt = _gaa(mal)
    rapport = {
        "ukjente_felter": sorted(set(ukjente)),
        "tilgjengelige_felter": sorted(flat.keys()),
    }
    return utfylt, rapport

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
import os
import re
from datetime import datetime

from delt.konstanter import NORSKE_FYLKER, NORSKE_YTELSER

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
    """11 sifre (ev. med mellomrom etter posisjon 6) som består mod11."""
    for treff in re.finditer(r"\b(\d{6})[ ]?(\d{5})\b", tekst):
        kandidat = treff.group(1) + treff.group(2)
        if er_gyldig_fnr(kandidat):
            return kandidat
    return None


def finn_kontonummer(tekst: str):
    """11 sifre, ev. formatert dddd.dd.ddddd, som består konto-mod11.
    Gyldige fødselsnummer hoppes over (kan kollidere i ren sifferform)."""
    for treff in re.finditer(r"\b(\d{4})[. ]?(\d{2})[. ]?(\d{5})\b", tekst):
        kandidat = "".join(treff.groups())
        if er_gyldig_fnr(kandidat):
            continue
        if er_gyldig_kontonummer(kandidat):
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


def finn_dato(tekst: str):
    """Første gyldige dato — numeriske formater og «12. januar 2020».
    Normaliseres til dd.mm.yyyy."""
    for treff in re.finditer(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b", tekst):
        d, m, y = int(treff.group(1)), int(treff.group(2)), int(treff.group(3))
        if _gyldig_dato(d, m, y):
            return f"{d:02d}.{m:02d}.{y}"
    for treff in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", tekst):
        y, m, d = int(treff.group(1)), int(treff.group(2)), int(treff.group(3))
        if _gyldig_dato(d, m, y):
            return f"{d:02d}.{m:02d}.{y}"
    maaneder = "|".join(_MAANEDER)
    for treff in re.finditer(
        rf"\b(\d{{1,2}})\.?\s+({maaneder})\s+(\d{{4}})\b", tekst, re.IGNORECASE
    ):
        d = int(treff.group(1))
        m = _MAANEDER[treff.group(2).lower()]
        y = int(treff.group(3))
        if _gyldig_dato(d, m, y):
            return f"{d:02d}.{m:02d}.{y}"
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
    (start, slutt, raatekst, normalisert dd.mm.yyyy, aar_antatt) der
    aar_antatt=True betyr at århundret er antatt (tosifret år) — en
    deklarert antagelse, ikke et faktum."""
    funn = []

    def _legg_til(treff, d, m, y, aar_antatt=False):
        if _gyldig_dato(d, m, y):
            funn.append((treff.start(), treff.end(), treff.group(0),
                         f"{d:02d}.{m:02d}.{y}", aar_antatt))

    # Numerisk, firesifret år: 12.03.2024, 12/3/2024 — og OCR-varianter
    # med mellomrom rundt skilletegnene («21.04 . 1994»)
    for treff in re.finditer(
        r"\b(\d{1,2})[ ]*[./][ ]*(\d{1,2})[ ]*[./][ ]*(\d{4})\b", tekst
    ):
        _legg_til(treff, int(treff.group(1)), int(treff.group(2)),
                  int(treff.group(3)))
    # Numerisk, tosifret år: 01.06.94 (århundre antas, flagges)
    for treff in re.finditer(
        r"\b(\d{1,2})[ ]*[./][ ]*(\d{1,2})[ ]*[./][ ]*(\d{2})(?!\d)", tekst
    ):
        _legg_til(treff, int(treff.group(1)), int(treff.group(2)),
                  _antatt_aar(int(treff.group(3))), aar_antatt=True)
    # ISO: 2024-03-12
    for treff in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", tekst):
        _legg_til(treff, int(treff.group(3)), int(treff.group(2)),
                  int(treff.group(1)))
    # Månedsnavn, norsk/engelsk: «12. mars 2024» / «March 12, 2024»
    maaneder = "|".join(_ALLE_MAANEDER)
    for treff in re.finditer(
        rf"\b(\d{{1,2}})\.?\s+({maaneder})\s+(\d{{4}})\b", tekst, re.IGNORECASE
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
    """ALLE gyldige datoer i teksten — normalisert til dd.mm.yyyy, i
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


# Brukerdefinerte etiketter fra egne_etiketter.txt i prosjektroten:
# «ord = type» per linje. Nye dokumenttyper med nye ord krever dermed
# ALDRI kodeendring — én linje i en tekstfil, uten omstart.
_EGNE_ETIKETTER_STI = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "egne_etiketter.txt")
_egne_etiketter_cache = {"mtime": None, "liste": []}


def _egne_dato_etiketter() -> list:
    try:
        mtime = os.path.getmtime(_EGNE_ETIKETTER_STI)
    except OSError:
        return []
    if _egne_etiketter_cache["mtime"] != mtime:
        liste = []
        try:
            with open(_EGNE_ETIKETTER_STI, encoding="utf-8") as f:
                for linje in f:
                    linje = linje.strip()
                    if not linje or linje.startswith("#") or "=" not in linje:
                        continue
                    ordet, typen = (d.strip() for d in linje.split("=", 1))
                    if ordet and typen:
                        liste.append((re.escape(ordet),
                                      re.sub(r"[^\wæøå]", "_", typen.lower())))
        except OSError:
            return _egne_etiketter_cache["liste"]
        _egne_etiketter_cache.update(mtime=mtime, liste=liste)
    return _egne_etiketter_cache["liste"]


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
            for monster, kandidat in _egne_dato_etiketter() + _DATO_ETIKETTER:
                m = re.search(monster, etikett_sok, re.IGNORECASE)
                if m:
                    dtype, etikett = kandidat, m.group(0)
                    begrunnelse = f"etiketten «{etikett}» står rett før datoen"
                    break

        # 3) Brev-/utstedelsesdato: øverst i dokumentet på egen kort linje
        if dtype is None and _side_for(start) == 1 and start < 300 \
                and len(linje.strip()) <= 40:
            dtype = "brevdato_sannsynlig"
            begrunnelse = ("øverst i dokumentet på egen kort linje — "
                           "typisk brev-/utstedelsesdato")

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

    # 5) Fødselsdato avledet fra gyldig fødselsnummer (forenklet
    #    århundreregel via individnummer)
    fnr = finn_fodselsnummer(tekst)
    if fnr:
        d, m, yy = int(fnr[0:2]), int(fnr[2:4]), int(fnr[4:6])
        individ = int(fnr[6:9])
        aar = 2000 + yy if (individ >= 500 and yy <= 39) else 1900 + yy
        if _gyldig_dato(d, m, aar):
            resultater.append({
                "dato": f"{d:02d}.{m:02d}.{aar}",
                "raatekst": fnr[:6] + "*****",
                "type": "fodselsdato_fra_fnr",
                "etikett": None,
                "begrunnelse": ("avledet fra de seks første sifrene i et "
                                "mod11-gyldig fødselsnummer "
                                "(forenklet århundreregel)"),
                "side": None,
                "kontekst": "fødselsnummer i dokumentet (maskert)",
                "i_lopende_tekst": False,
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


def finn_telefon(tekst: str):
    """Norsk telefonnummer: 8 sifre, ev. +47/0047-prefiks og gruppering."""
    for treff in re.finditer(
        r"(?:\+47|0047)?[ ]?(\d{2})[ ]?(\d{2})[ ]?(\d{2})[ ]?(\d{2})\b", tekst
    ):
        # Hopp over kandidater som er halen av et lengre tall (fnr/konto)
        start = treff.start()
        if start > 0 and tekst[start - 1].isdigit():
            continue
        return "".join(treff.groups())
    return None


def finn_epost(tekst: str):
    treff = re.search(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b", tekst)
    return treff.group(0) if treff else None


def finn_postnummer_sted(tekst: str):
    """«0181 Oslo» → (postnummer, poststed). Flerords-steder med «i»
    («8610 Mo i Rana») fanges også — uten å sluke neste setningsord."""
    treff = re.search(
        r"\b(\d{4})[ \t]+([A-ZÆØÅ][a-zæøåA-ZÆØÅ]+"
        r"(?:[ \t][iI][ \t][A-ZÆØÅ][a-zæøåA-ZÆØÅ]+)?)\b",
        tekst,
    )
    if treff:
        return treff.group(1), treff.group(2)
    return None, None


def finn_belop(tekst: str):
    """Kronebeløp: «kr 12 345,50», «NOK 5000», «12.345,-»."""
    treff = re.search(
        r"(?:kr\.?|NOK)\s?([\d][\d .]*(?:,\d{2}|,-)?)|"
        r"\b([\d]{1,3}(?:[ .]\d{3})+(?:,\d{2}|,-))",
        tekst, re.IGNORECASE,
    )
    if not treff:
        return None
    raa = (treff.group(1) or treff.group(2)).strip()
    normalisert = raa.replace(" ", "").replace(".", "").replace(",-", "").replace(",", ".")
    try:
        return float(normalisert)
    except ValueError:
        return None


def finn_saksnummer(tekst: str):
    """Saksreferanser: «saksnr 21/12345», «ref.: 2020/0456» og
    NAV-skjemakoder som «NAV 04-01.03»."""
    treff = re.search(
        r"(?:saksnr\.?|saksnummer|ref\.?|referanse)[:\s]+([0-9]{2,4}/[0-9]{3,6})",
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


def finn_ytelse(tekst: str):
    """Nøkkelordssøk mot den kanoniske ytelseslisten — sikrere enn å
    gjette at enhver ORG-entitet er en ytelse."""
    tekst_lav = tekst.lower()
    for ytelse in NORSKE_YTELSER:
        if ytelse in tekst_lav:
            return ytelse
    return None


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


def _tallkandidater(tekst: str, lengde: int):
    """Alle sifferstrenger av gitt lengde uansett gruppering — «180527
    422 30», «1805.27.44230» og «18052744230» er samme kandidat."""
    for treff in re.finditer(r"(?<!\d)\d(?:[ .]?\d)+(?!\d)", tekst):
        kompakt = re.sub(r"[ .]", "", treff.group(0))
        if len(kompakt) == lengde:
            yield kompakt


def finn_alle_fodselsnummer(tekst: str) -> list:
    return _unike(k for k in _tallkandidater(tekst, 11) if er_gyldig_fnr(k))


def finn_alle_kontonummer(tekst: str) -> list:
    return _unike(k for k in _tallkandidater(tekst, 11)
                  if er_gyldig_kontonummer(k) and not er_gyldig_fnr(k))


def finn_alle_organisasjonsnummer(tekst: str) -> list:
    return _unike(k for k in _tallkandidater(tekst, 9) if er_gyldig_orgnr(k))


def finn_alle_kid(tekst: str) -> list:
    """KID krever etikett i konteksten — et rent tall uten «KID» ved
    siden av er for tvetydig til å påstås å være KID."""
    ut = []
    for treff in re.finditer(r"(?i)\bkid[.:\s-]*((?:\d[ .]?){2,30}\d)", tekst):
        kompakt = re.sub(r"[ .]", "", treff.group(1))
        if er_gyldig_kid(kompakt):
            ut.append(kompakt)
    return _unike(ut)


def finn_alle_telefoner(tekst: str) -> list:
    """Alle norske telefonnumre (8 sifre, ev. +47 og gruppering).
    Kandidater som er del av lengre tall utelukkes."""
    ut = []
    for treff in re.finditer(
        r"(?:\+47|0047)?[ ]?(\d{2})[ ]?(\d{2})[ ]?(\d{2})[ ]?(\d{2})\b", tekst
    ):
        if treff.start() > 0 and tekst[treff.start() - 1].isdigit():
            continue
        nummer = "".join(treff.groups())
        # Norske abonnentnumre starter ikke på 0 eller 1
        if nummer[0] not in "01":
            ut.append(nummer)
    return _unike(ut)


def finn_alle_eposter(tekst: str) -> list:
    return _unike(re.findall(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b", tekst))


def finn_alle_belop(tekst: str, maks: int = 100) -> list:
    """Alle kronebeløp med kontekst — verdier som tall (float)."""
    ut = []
    for treff in re.finditer(
        r"(?:kr\.?|NOK)\s?([\d][\d .]*(?:,\d{2}|,-)?)|"
        r"\b([\d]{1,3}(?:[ .]\d{3})+(?:,\d{2}|,-))|"
        r"\b(\d{1,6},\d{2})\b",
        tekst, re.IGNORECASE,
    ):
        raa = (treff.group(1) or treff.group(2) or treff.group(3)).strip()
        normalisert = (raa.replace(" ", "").replace(".", "")
                       .replace(",-", "").replace(",", "."))
        try:
            verdi = float(normalisert)
        except ValueError:
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


def finn_adresser(tekst: str) -> list:
    """Alle postnummer/poststed-forekomster, med gateadresse fra linjen
    over når den ligner en gate (bokstaver + husnummer)."""
    ut, sett = [], set()
    for treff in re.finditer(
        r"\b(\d{4})[ \t]+([A-ZÆØÅ][a-zæøåA-ZÆØÅ]+"
        r"(?:[ \t][iI][ \t][A-ZÆØÅ][a-zæøåA-ZÆØÅ]+)?)\b", tekst
    ):
        postnummer, poststed = treff.group(1), treff.group(2)
        linje_start = tekst.rfind("\n", 0, treff.start()) + 1
        forrige_slutt = linje_start - 1
        gate = ""
        if forrige_slutt > 0:
            forrige_start = tekst.rfind("\n", 0, forrige_slutt) + 1
            forrige = tekst[forrige_start:forrige_slutt].strip()
            if (len(forrige) <= 60
                    and re.search(r"[A-Za-zÆØÅæøå]{3,}.*\d", forrige)):
                gate = forrige
        nokkel = (gate, postnummer, poststed)
        if nokkel not in sett:
            sett.add(nokkel)
            ut.append({"gate": gate, "postnummer": postnummer,
                       "poststed": poststed})
    return ut


# Dokumenttyper med kjennetegn — poengsum avgjør, "" hvis intet treffer
_DOKUMENTTYPER = [
    ("faktura", r"faktura|forfallsdato|\bkid\b"),
    ("kvittering", r"kvittering|betaling mottatt|kj[øo]pskvittering"),
    ("vedtak", r"\bvedtak"),
    ("soknad", r"s[øo]knad"),
    ("pensjonsbrev", r"pensjonsbrev"),
    ("attest", r"\battest"),
    ("kontrakt", r"kontrakt|l[æa]rekontrakt|avtale"),
    ("boardingkort", r"boardingkort|boarding"),
    ("brev", r"med vennlig hilsen|kj[æa]re"),
]


def gjett_dokumenttype(tekst: str) -> str:
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


def strukturert_uttrekk(tekst: str) -> dict:
    """Komplett strukturert uttrekk av ALT som kan finnes i tekst fra
    NAV-dokumenter. Alle nøkler er alltid til stede — tomt er "" / []."""
    tekst = tekst or ""
    datoer = klassifiser_datoer(tekst)

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

    return {
        "dokument": {
            "tittel": forste_linje[:100],
            "dokumenttype": gjett_dokumenttype(tekst),
            "sprak": gjett_sprak(tekst),
            "kontornavn": finn_kontornavn(tekst) or "",
            "fylke": finn_fylke(tekst) or "",
            "ytelse": finn_ytelse(tekst) or "",
        },
        "identifikatorer": {
            "fodselsnummer": finn_alle_fodselsnummer(tekst),
            "kontonummer": finn_alle_kontonummer(tekst),
            "organisasjonsnummer": finn_alle_organisasjonsnummer(tekst),
            "kid": finn_alle_kid(tekst),
            "saksnummer": finn_saksnummer(tekst) or "",
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
        "dato":          finn_dato(tekst),
        "telefon":       finn_telefon(tekst),
        "epost":         finn_epost(tekst),
        "belop":         finn_belop(tekst),
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

    # F3-2: mønsterfelter der deterministisk søk ikke fant noe, men modellen
    # likevel leverte en verdi — verifiser modellverdien mot samme format,
    # ellers forkast (hindrer hallusinert telefon/epost/dato/beløp/saksnr).
    _mønster_validatorer = {
        "telefon":    lambda v: bool(re.fullmatch(r"\+?\d[\d ]{6,14}", v.strip())),
        "epost":      lambda v: bool(re.fullmatch(r"[\w.+-]+@[\w-]+\.[\w.]{2,}", v.strip())),
        "dato":       lambda v: finn_dato(v) is not None,
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
    if resultat.get("belop") is not None and deterministiske.get("belop") is None:
        try:
            float(str(resultat["belop"]).replace(",", ".").replace(" ", ""))
        except (ValueError, TypeError):
            resultat.pop("belop")

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

"""Dokumentprofilen — de obligatoriske metadataene i svaret fra
`POST /dokument`.

Profilen følger med HVER GANG, uansett hva klienten spurte om. Grunnen
er at et dokument har egenskaper som gjelder uavhengig av spørsmålet:
hvor mange sider det har, når det er datert, hvem det gjelder. Måtte
klienten be om dem enkeltvis, ville de bli glemt — og et svar uten dem
er et halvt svar.

Alt her er DETERMINISTISK. Ingen språkmodell er involvert, og ingenting
gjettes: kan ikke et felt fastslås, står det `null` sammen med en
begrunnelse for hvorfor. Et felt med `null` og en forklaring er til å
stole på; et felt med en tilfeldig dato er ikke det.
"""
import re

from delt.tekstuttrekk import (ROLLE_BEHANDLING, dokumentets_alder,
                               finn_alle_fodselsnummer, rolle_for_type)

# ------------------------------------------------------------------ #
#  Datoer: norsk form ut og inn, ISO i profilen                       #
# ------------------------------------------------------------------ #


def til_iso(dato_norsk):
    """«17.05.2024» → «2024-05-17». None når datoen ikke lar seg lese.

    Profilen svarer i ISO fordi den leses av andre systemer; resten av
    API-et beholder den norske formen, og begge følger med."""
    try:
        dag, maaned, aar = (int(x) for x in str(dato_norsk).split("."))
        return f"{aar:04d}-{maaned:02d}-{dag:02d}"
    except (ValueError, TypeError, AttributeError):
        return None


# ------------------------------------------------------------------ #
#  QR-koder og strekkoder: hvilken SIDE står de på                    #
# ------------------------------------------------------------------ #

# pyzbar melder typen; alt som ikke er QR-aktig regnes som strekkode
_QR_TYPER = ("QRCODE", "QR_CODE", "MICROQR", "DATAMATRIX", "AZTEC", "PDF417")


def _er_qr(type_navn) -> bool:
    return str(type_navn or "").upper().replace("-", "").replace(" ", "") \
        in _QR_TYPER


def koder_med_sider(strekkoder, lest: bool = True) -> dict:
    """Deler de dekodede kodene i QR og strekkode, med sidetall.

    `lest=False` betyr at skanningen ALDRI ble kjørt (klienten slo den
    av). Da er svaret «vet ikke», ikke «ingen koder» — forskjellen er
    hele poenget: et dokument uten skanning har ikke bevist at det
    mangler QR-kode."""
    if not lest:
        return {"lest": False, "qr": [], "strekkode": [],
                "qr_kode_side": None, "strekkode_side": None,
                "merknad": ("Strekkode-/QR-skanning var slått av for dette "
                            "kallet — feltene sier ikke at koder mangler, "
                            "bare at det ikke ble sett etter dem")}
    qr, strek = [], []
    for kode in strekkoder or []:
        if not isinstance(kode, dict):
            continue
        post = {"side": kode.get("side"), "verdi": kode.get("verdi"),
                "type": kode.get("type")}
        (qr if _er_qr(kode.get("type")) else strek).append(post)

    def forste_side(liste):
        sider = sorted(p["side"] for p in liste if p.get("side"))
        return sider[0] if sider else None

    return {"lest": True, "qr": qr, "strekkode": strek,
            "qr_kode_side": forste_side(qr),
            "strekkode_side": forste_side(strek),
            "merknad": None}


# ------------------------------------------------------------------ #
#  Periode: hva dokumentet GJELDER FOR                                #
# ------------------------------------------------------------------ #

def gjelder_periode(datoer) -> dict | None:
    """Perioden dokumentet gjelder for («for perioden 01.01. til 31.12.»).

    Dette er IKKE det samme som dokumentets egen dato, og heller ikke
    det samme som datospennet i en bunke: et vedtak datert i mai kan
    gjelde for hele året. Paret bygges av en periodestart etterfulgt av
    en periodeslutt — står de ikke i par, er det ingen periode."""
    venter = None
    for d in datoer or []:
        if not isinstance(d, dict):
            continue
        if d.get("type") == "periode_start":
            venter = d
        elif d.get("type") == "periode_slutt" and venter:
            return {"fra": venter.get("dato"), "til": d.get("dato")}
    return None


# ------------------------------------------------------------------ #
#  Stempeldatoer                                                      #
# ------------------------------------------------------------------ #

# Ord som viser at datoen står i et stempel eller en påtegning, ikke i
# dokumentets egen datolinje
_STEMPELORD = re.compile(
    r"(?i)\b(stempel|stemplet|mottatt|innkommet|registrert|journalf[øo]rt|"
    r"arkivert|ekspedert|skannet|innlest|postmottak|dokumentsenter)\b")

# Datotyper som ALLTID hører til håndteringen av dokumentet
_STEMPELTYPER = ("mottatt", "arkivert")


def _stempelord_foran(tekst: str, dato: str) -> bool:
    """Står et stempelord rett foran datoen, på SAMME linje? Brukes for
    påtegninger som ikke har en egen datotype («Stempel: 20.05.2024»)."""
    for treff in re.finditer(re.escape(dato), tekst or ""):
        linje_start = (tekst.rfind("\n", 0, treff.start()) + 1)
        foran = tekst[max(linje_start, treff.start() - 40):treff.start()]
        if _STEMPELORD.search(foran):
            return True
    return False


def stempeldatoer(tekst: str, datoer) -> list:
    """Datoer som står i et stempel eller en påtegning.

    Et stempel forteller når NOEN GJORDE noe med dokumentet — mottok
    det, arkiverte det — ikke når dokumentet ble til. Blandes de
    sammen, blir et brev fra mai «datert» den dagen postmottaket
    stemplet det. Derfor holdes de i sitt eget felt, og de blir aldri
    dokumentdato av seg selv."""
    funn = []
    for d in datoer or []:
        if not isinstance(d, dict) or not d.get("dato"):
            continue
        type_ = d.get("type")
        # Rollen «behandling» ER stempelsemantikken: den er satt nettopp
        # for datoer som sier når NOEN GJORDE noe med dokumentet.
        i_stempel = (type_ in _STEMPELTYPER
                     or rolle_for_type(type_) == ROLLE_BEHANDLING)
        if not i_stempel:
            # Ellers: står et stempelord RETT FORAN datoen? «kontekst»
            # duger ikke — den spenner over linjeskift, så et stempelord
            # på neste linje ville gjort dokumentdatoen til et stempel.
            i_stempel = _stempelord_foran(tekst, d["dato"])
        if not i_stempel:
            continue
        iso = til_iso(d["dato"])
        if not iso:
            continue
        funn.append({"dato": iso, "dato_norsk": d["dato"],
                     "type": type_, "side": d.get("side"),
                     "rolle": rolle_for_type(type_)})
    # samme stempeldato flere steder er ett stempel, ikke flere
    sett, unike = set(), []
    for f in funn:
        if f["dato"] in sett:
            continue
        sett.add(f["dato"])
        unike.append(f)
    return unike


# ------------------------------------------------------------------ #
#  Dokumentets eier — personen dokumentet GJELDER                     #
# ------------------------------------------------------------------ #

# Etiketter som peker på dokumentets hovedperson
_EIERETIKETT = re.compile(
    r"(?i)(dokumentet\s+gjelder|saken\s+gjelder|gjelder\s+person|"
    r"vedr[øo]rende|ang[åa]ende|personopplysninger|"
    r"\bnavn\b|\bs[øo]ker\b|s[øo]kers?\s+navn|\bbruker\b|brukers?\s+navn|"
    r"den\s+sykmeldte|sykmeldt\b|arbeidstaker|\bmedlem\b|\bpasient\b|"
    r"\belev\b|\bdeltaker\b|\bklient\b|sakens\s+part|"
    r"personen\s+dette\s+gjelder|opplysninger\s+om)")

# Etiketter som peker på ALLE ANDRE. Et fødselsnummer under en av disse
# er aldri dokumentets fødselsnummer.
_ANNENETIKETT = re.compile(
    r"(?i)(saksbehandler|behandlende\s+lege|\blege\b|tannlege|psykolog|"
    r"fysioterapeut|\bbehandler\b|kontaktperson|arbeidsgiver|"
    r"n[æa]rmeste\s+leder|\bkopi\b|kopimottaker|\bmottaker\b|\bavsender\b|"
    r"utsteder|utstedt\s+av|signert\s+av|underskrevet\s+av|attestert\s+av|"
    r"\bveileder\b|konsulent|\bvitne\b|\bverge\b|fullmektig|p[åa]r[øo]rende|"
    r"ektefelle|samboer|\bforelder\b|\bvergem[åa]l\b|revisor|regnskapsf[øo]rer)")

# Et navn: to eller flere ord med stor forbokstav PÅ SAMME LINJE.
# «\s+» ville sluppet linjeskift gjennom, og da ble «Ola Nordmann» til
# «Ola Nordmann Fnr» fordi etiketten på neste linje også har stor
# forbokstav.
_NAVN = re.compile(
    r"\b([A-ZÆØÅ][a-zæøåé\-']{1,20}(?:[ \t]+[A-ZÆØÅ][a-zæøåé\-']{1,20}){1,3})\b")

# Ord som ser ut som navn, men er etiketter eller organisasjoner
_IKKE_NAVN = re.compile(
    r"(?i)^(fnr|f[øo]dselsnummer|personnummer|navn|dato|side|nav|"
    r"saksnummer|adresse|telefon|postnummer|org)\b")

# Hvor langt bak fødselsnummeret vi leter etter etiketten som styrer det
_ETIKETTVINDU = 250


def _posisjoner(tekst: str, fnr: str) -> list:
    """Hvor i teksten fødselsnummeret står — også når det er skrevet med
    skilletegn («010190 12345», «0101.90.12345»)."""
    monster = re.compile(r"(?<![0-9])" + r"[ .\-]?".join(fnr) + r"(?![0-9])")
    return [m.start() for m in monster.finditer(tekst)]


def _navn_ved(tekst: str, etikett_slutt: int, fnr_start: int):
    """Navnet som hører til etiketten: det første navnelignende ordparet
    mellom etiketten og fødselsnummeret. Står det ingen der, ser vi på
    linja over nummeret."""
    def foerste_navn(bit: str):
        for treff in _NAVN.finditer(bit):
            navn = treff.group(1).strip()
            if not _IKKE_NAVN.match(navn):
                return navn
        return None

    navn = foerste_navn(tekst[etikett_slutt:fnr_start])
    if navn:
        return navn
    linjer = [l.strip() for l in tekst[:fnr_start].splitlines() if l.strip()]
    for linje in reversed(linjer[-3:]):
        navn = foerste_navn(linje)
        if navn:
            return navn
    return None


def _rolle_for_forekomst(tekst: str, start: int) -> tuple:
    """Etiketten som STYRER dette fødselsnummeret: den siste rolle-
    etiketten foran nummeret. «Siste» fordi et dokument leses ovenfra og
    ned — står «Saksbehandler:» rett over nummeret, er det
    saksbehandlerens, selv om «Dokumentet gjelder» sto lenger opp."""
    vindu_start = max(0, start - _ETIKETTVINDU)
    vindu = tekst[vindu_start:start]
    eier = list(_EIERETIKETT.finditer(vindu))
    annen = list(_ANNENETIKETT.finditer(vindu))
    siste_eier = eier[-1] if eier else None
    siste_annen = annen[-1] if annen else None
    if siste_eier and (not siste_annen or siste_eier.start() > siste_annen.start()):
        return "eier", vindu_start + siste_eier.end(), siste_eier.group(0)
    if siste_annen:
        return "annen", vindu_start + siste_annen.end(), siste_annen.group(0)
    return "umerket", start, None


def finn_dokument_eier(tekst: str) -> dict:
    """Fødselsnummeret til personen dokumentet GJELDER.

    Et NAV-dokument nevner ofte flere personer med fødselsnummer: den
    saken gjelder, saksbehandleren, legen, arbeidsgiverens kontakt. Å
    plukke det første nummeret i teksten gir feil person i det øyeblikket
    dokumentet har mer enn én. Derfor kobles hvert nummer til etiketten
    som står foran det, og bare et POSITIVT eiersignal kvalifiserer.

    Uten et slikt signal er svaret `null` — ikke det eneste nummeret vi
    fant. «Det står bare ett fødselsnummer her» er en gjetning, og en
    gjetning om hvem et vedtak gjelder er verre enn ingen verdi.

    Returnerer {navn, fnr, sikkerhet, begrunnelse, kandidater}."""
    tekst = tekst or ""
    kandidater = []
    for fnr in finn_alle_fodselsnummer(tekst):
        for start in _posisjoner(tekst, fnr):
            rolle, etikett_slutt, etikett = _rolle_for_forekomst(tekst, start)
            kandidater.append({
                "fnr": fnr,
                "rolle": rolle,
                "etikett": (etikett or "").strip() or None,
                "navn": _navn_ved(tekst, etikett_slutt, start),
            })

    def svar(navn, fnr, sikkerhet, begrunnelse):
        return {"navn": navn, "fnr": fnr, "sikkerhet": sikkerhet,
                "begrunnelse": begrunnelse, "kandidater": kandidater}

    if not kandidater:
        return svar(None, None, "ingen",
                    "Dokumentet inneholder ingen fødselsnummer som består "
                    "kontrollsifferet (mod11).")

    eiere = [k for k in kandidater if k["rolle"] == "eier"]
    unike_eiere = {k["fnr"] for k in eiere}
    if len(unike_eiere) == 1:
        beste = eiere[0]
        return svar(beste["navn"], beste["fnr"], "merket",
                    f"Fødselsnummeret står under «{beste['etikett']}», som "
                    f"peker på personen dokumentet gjelder.")
    if len(unike_eiere) > 1:
        return svar(None, None, "flertydig",
                    "Flere ULIKE fødselsnummer står under eier-etiketter ("
                    + ", ".join(f"{k['etikett']}" for k in eiere[:4])
                    + ") — hvem dokumentet gjelder kan ikke avgjøres, og et "
                      "valg mellom dem ville vært en gjetning.")

    andre = [k for k in kandidater if k["rolle"] == "annen"]
    if andre and len(andre) == len(kandidater):
        return svar(None, None, "bare_andre_roller",
                    "Fødselsnumrene i dokumentet hører til andre roller ("
                    + ", ".join(sorted({k["etikett"] or "?" for k in andre}))
                    + ") — ingen av dem er personen dokumentet gjelder.")

    return svar(None, None, "umerket",
                f"Fant {len({k['fnr'] for k in kandidater})} fødselsnummer, "
                "men ingen av dem står under en etikett som viser hvem "
                "dokumentet gjelder. Et nummer hentes ikke bare fordi det "
                "finnes i teksten.")


# ------------------------------------------------------------------ #
#  Selve profilen                                                     #
# ------------------------------------------------------------------ #

def bygg_profil(tekst, *, antall_sider=None, strekkoder=None,
                strekkoder_lest=True, datoer_detaljert=None,
                dokumentdato=None) -> dict:
    """Setter sammen de obligatoriske metadataene.

    Alle argumenter er allerede utregnet av kalleren (DokumentKontekst
    cacher dem), så profilen koster ingen ny lesing av dokumentet."""
    dokumentdato = dokumentdato or {}
    datoer = datoer_detaljert or []

    dato_norsk = dokumentdato.get("dato")
    dato_iso = til_iso(dato_norsk)
    periode = gjelder_periode(datoer)
    # Datospennet i en BUNKE er noe annet enn perioden dokumentet gjelder
    # for — begge kan finnes samtidig, og de skal ikke forveksles
    spenn = dokumentdato.get("periode")

    profil = {
        "antall_sider": antall_sider,
        "koder": koder_med_sider(strekkoder, strekkoder_lest),

        "dokumentdato": dato_iso,
        "dokumentdato_norsk": dato_norsk,
        "dokumentdato_kilde": dokumentdato.get("kilde"),
        "dokumentdato_konfidens": dokumentdato.get("konfidens") or "ingen",
        "dokumentdato_begrunnelse": dokumentdato.get("begrunnelse"),
        "dokumentdato_side": dokumentdato.get("side"),

        # perioden dokumentet GJELDER FOR (null når det ikke er en periode)
        "dokumentdato_fra": til_iso(periode["fra"]) if periode else None,
        "dokumentdato_til": til_iso(periode["til"]) if periode else None,

        # datospennet når filen er en BUNKE av flere daterte dokumenter
        "dokumentspenn_fra": til_iso(spenn["fra"]) if spenn else None,
        "dokumentspenn_til": til_iso(spenn["til"]) if spenn else None,
        "flere_dokumenter": bool(spenn and spenn.get("flere_dokumenter")),

        "dokument_ar": int(dato_iso[:4]) if dato_iso else None,
        # dokumentets alder regnes fra dokumentdatoen — «fremtidig» settes
        # når datoen ligger fram i tid, og da er noe galt som skal fram
        "dokument_alder": dokumentets_alder(dato_norsk) if dato_norsk else None,

        "stempel_datoer": stempeldatoer(tekst, datoer),

        "dokument_eier": finn_dokument_eier(tekst),

        # Reglene for ytelse kommer senere. Feltet er med fra første dag
        # så kontrakten ikke må endres når de gjør det — en klient som
        # leser det nå, får null og vet at det ikke er fastslått.
        "ytelse": None,
        "ytelse_status": "ikke_implementert",
    }
    return profil

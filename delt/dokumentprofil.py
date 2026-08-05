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

from delt.saksfelter import arbeid_felter, okonomi_felter, sak_felter
from delt.tekstuttrekk import (ROLLE_BEHANDLING, ROLLE_DOKUMENT,
                               dokumentets_alder, finn_alle_fodselsnummer,
                               rolle_for_type)

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
        rolle = rolle_for_type(type_)
        # En dato som er sterk nok til å bli klassifisert som DOKUMENTETS
        # egen (vedtaksdato, «datert …», dokumentdato) er per definisjon
        # ikke et stempel. Uten denne sperren havnet dokumentdatoen i
        # stempellista på et skannet dokument: OCR flater ut layouten, så
        # teksten i et stempelmerke og datolinja kan havne på SAMME
        # linje — og da slo stempelord-fallbacken til på feil dato.
        if rolle == ROLLE_DOKUMENT:
            continue
        # Rollen «behandling» ER stempelsemantikken: den er satt nettopp
        # for datoer som sier når NOEN GJORDE noe med dokumentet.
        i_stempel = type_ in _STEMPELTYPER or rolle == ROLLE_BEHANDLING
        if not i_stempel:
            # Ellers: står et stempelord RETT FORAN datoen? «kontekst»
            # duger ikke — den spenner over linjeskift, så et stempelord
            # på neste linje ville gjort en vilkårlig dato til et stempel.
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
# Et navneord: stor forbokstav, og dobbeltnavn med bindestrek regnes som
# ETT ord. «Nor-Etternavn» ble ellers klippet til «Nor-», fordi den
# store E-en etter bindestreken falt utenfor.
_NAVNEORD = r"[A-ZÆØÅ][a-zæøåé']{1,20}(?:-[A-ZÆØÅa-zæøåé']{1,20})?"
_NAVN = re.compile(r"\b(" + _NAVNEORD + r"(?:[ \t]+" + _NAVNEORD + r"){1,3})\b")

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


# Skjemaer merker navnefeltet selv. Står etiketten der, er linja under
# navnet — uansett hvordan det er skrevet. Dette er sikrere enn å kjenne
# igjen FORMEN på et navn, og det er den eneste veien til navn skrevet
# med blokkbokstaver («NOR-ETTERNAVN, OLA»), som norske skjemaer ber om.
_NAVNEETIKETT = re.compile(
    r"(?im)^\s*(?:etternavn,?\s*fornavn|fornavn,?\s*etternavn|"
    r"navn\s*p[åa]\s*\w+|etternavn|fornavn|\bnavn\b)\s*:?\s*$")


def _navn_under_etikett(bit: str):
    """Linja under en navne-etikett. None hvis etiketten ikke står der,
    eller hvis linja under er tom."""
    treff = None
    for treff in _NAVNEETIKETT.finditer(bit):
        pass                       # den siste = nærmest fødselsnummeret
    if not treff:
        return None
    for linje in bit[treff.end():].splitlines():
        linje = linje.strip()
        if linje:
            return linje if not _IKKE_NAVN.match(linje) else None
    return None


def _navn_ved(tekst: str, etikett_slutt: int, fnr_start: int):
    """Navnet som hører til etiketten.

    Først etter en navne-etikett («Etternavn, fornavn»), som er den
    sikre veien og den eneste som fanger blokkbokstaver. Ellers det
    første navnelignende ordparet, og til sist linja over nummeret."""
    mellom_rom = tekst[etikett_slutt:fnr_start]
    fra_etikett = _navn_under_etikett(mellom_rom)
    if fra_etikett:
        return fra_etikett

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

    De ØVRIGE fødselsnumrene kastes ikke — de er ekte opplysninger i
    dokumentet, og en klient kan trenge dem. Men de holdes STRENGT
    atskilt, i «andre_fodselsnummer», slik at ingen kan forveksle
    legens eller saksbehandlerens nummer med dokumentets eget.

    Returnerer {navn, fnr, sikkerhet, begrunnelse, andre_fodselsnummer}."""
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
        # Alt som IKKE er eierens nummer havner her — én oppføring per
        # unikt nummer, aldri sammenblandet med eierens.
        andre, sett = [], set()
        for k in kandidater:
            if k["fnr"] == fnr or k["fnr"] in sett:
                continue
            sett.add(k["fnr"])
            andre.append(k)
        return {"navn": navn, "fnr": fnr, "sikkerhet": sikkerhet,
                "begrunnelse": begrunnelse, "andre_fodselsnummer": andre}

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

def blanke_sider(tekst: str) -> list | None:
    """Sidene uten lesbart innhold.

    Sidemarkørene «[Side i av n]» er KODE-genererte (R36), så det som
    står mellom to markører er alt som ble lest på den siden. Er det
    tomt, kom det ingenting ut av siden — enten fordi den er blank,
    eller fordi lesingen mislyktes. Begge deler skal fram: en bunke der
    side 7 er tom, er noe en saksbehandler må vite om.

    None når teksten ikke har sidemarkører — da VET vi ikke, og «ingen
    blanke sider» ville vært en påstand vi ikke kan stå for."""
    if not tekst or not re.search(r"\[Side \d+ av \d+\]", tekst):
        return None
    biter = re.split(r"\[Side (\d+) av \d+\]", tekst)
    tomme = []
    # split gir [før, nr, innhold, nr, innhold, …]
    for i in range(1, len(biter) - 1, 2):
        if not biter[i + 1].strip():
            tomme.append(int(biter[i]))
    return tomme


def _fodselsdato_av_fnr(fnr):
    """Fødselsdatoen ligger i de seks første sifrene av et gyldig
    fødselsnummer. Bare for BEVISTE numre — å regne den ut av et nummer
    vi ikke har verifisert, ville vært å gjette to ganger."""
    if not fnr or len(fnr) != 11:
        return None
    dag, maaned, aar = int(fnr[:2]), int(fnr[2:4]), int(fnr[4:6])
    # syntetiske serier: måned +80 (Tenor) eller +40 (D-nummer på dag)
    if maaned > 80:
        maaned -= 80
    elif maaned > 40:
        maaned -= 40
    if dag > 40:
        dag -= 40                      # D-nummer
    if not (1 <= dag <= 31 and 1 <= maaned <= 12):
        return None
    # århundret er ikke entydig av fnr alene; individsifrene avgjør, og
    # den regelen hører ikke hjemme her. 1900-tallet som utgangspunkt.
    return f"{1900 + aar:04d}-{maaned:02d}-{dag:02d}"


def _sider(tekst: str) -> list:
    """[(sidenummer, sidetekst)] fra de KODE-genererte sidemarkørene
    (R36). Tom liste når teksten ikke har markører."""
    biter = re.split(r"\[Side (\d+) av \d+\]", tekst or "")
    return [(int(biter[i]), biter[i + 1])
            for i in range(1, len(biter) - 1, 2)]


def del_i_dokumenter(tekst: str, datoer, filens_type=None) -> list:
    """Deler en BUNKE i dokumentene den består av.

    En skannet fil er ofte ikke ett dokument, men en saksmappe: vedtak,
    inntektsmelding, legeerklæring, klage — hver med sin dato, sin type
    og noen ganger sin person. Ett `eier`-felt og én `dokumentdato` for
    hele filen er da misvisende, uansett hvor riktig hver enkelt verdi
    er isolert sett.

    Delingen følger dokumentDATOENE: en side som bærer en ny dato med
    rolle «dokument», starter et nytt dokument; sider uten egen dato
    hører til det foregående. Det er et deterministisk skille som kan
    forklares — ikke en gjetning om hvor et dokument «føles» ferdig.

    Returnerer alltid minst én oppføring: en fil uten sidemarkører er
    ett dokument."""
    from delt.tekstuttrekk import gjett_dokumenttype

    sider = _sider(tekst)
    if not sider:
        sider = [(None, tekst or "")]

    dato_per_side = {}
    for d in datoer or []:
        if (isinstance(d, dict) and d.get("side") and d.get("dato")
                and rolle_for_type(d.get("type")) == ROLLE_DOKUMENT):
            dato_per_side.setdefault(d["side"], d["dato"])

    grupper = []
    for nr, sidetekst in sider:
        dato = dato_per_side.get(nr)
        ny = (not grupper
              or (dato and grupper[-1]["dato"] and dato != grupper[-1]["dato"])
              or (dato and not grupper[-1]["dato"]))
        if ny:
            grupper.append({"sider": [nr] if nr else [],
                            "dato": dato, "tekst": sidetekst})
        else:
            if nr:
                grupper[-1]["sider"].append(nr)
            grupper[-1]["tekst"] += "\n" + sidetekst

    ut = []
    for g in grupper:
        eier = finn_dokument_eier(g["tekst"])
        forste = next((l.strip() for l in g["tekst"].splitlines()
                       if l.strip()), "")
        ut.append({
            "sider": g["sider"],
            "dato": til_iso(g["dato"]),
            "dato_norsk": g["dato"],
            # ingen arv fra filens type: et dokument vi ikke kjenner
            # igjen, skal si «vet ikke» — ikke låne naboens etikett
            "type": gjett_dokumenttype(g["tekst"]) or None,
            "tittel": forste[:100] or None,
            "eier_navn": eier["navn"],
            "eier_fnr": eier["fnr"],
            "eier_sikkerhet": eier["sikkerhet"],
        })
    return ut


def _sammendrag(profil: dict, antall_dokumenter: int) -> dict:
    """De få feltene de fleste er ute etter, øverst.

    Profilen er komplett og derfor lang. Et sammendrag gjør at den som
    bare skal vite «hvem og når» slipper å lete — uten at noe fjernes
    for den som trenger resten. «sikkerhet» er det SVAKESTE leddet, ikke
    et gjennomsnitt: er eieren usikker, hjelper det ikke at datoen er
    sikker."""
    eier, dok = profil["eier"], profil["dokument"]
    ledd = [eier["sikkerhet"] == "merket",
            dok["dato_sikkerhet"] == "hoy",
            antall_dokumenter <= 1]
    if all(ledd):
        sikkerhet = "hoy"
    elif eier["fnr"] and dok["dato"]:
        sikkerhet = "middels"
    else:
        sikkerhet = "usikker"
    return {
        "navn": eier["navn"],
        "fnr": eier["fnr"],
        "dokumentdato": dok["dato"],
        "dokumenttype": dok["type"],
        "ytelse": profil["ytelse"]["navn"],
        "saksnummer": profil["sak"]["saksnummer"],
        "antall_sider": profil["fil"]["antall_sider"],
        "antall_dokumenter": antall_dokumenter,
        "sikkerhet": sikkerhet,
    }


SKJEMAVERSJON = "1.1"


def bygg_profil(tekst, *, filnavn=None, antall_sider=None, strekkoder=None,
                strekkoder_lest=True, datoer_detaljert=None,
                dokumentdato=None, struktur=None, handskrift=None) -> dict:
    """Setter sammen dokumentprofilen — den kanoniske formen (R66).

    Seksjonene er faste og alltid til stede. Alle argumenter er
    allerede utregnet av kalleren (DokumentKontekst cacher dem), så
    profilen koster ingen ny lesing av dokumentet."""
    dokumentdato = dokumentdato or {}
    datoer = datoer_detaljert or []
    struktur = struktur or {}
    s_dok = struktur.get("dokument") or {}
    s_ident = struktur.get("identifikatorer") or {}
    s_kontakt = struktur.get("kontakt") or {}

    dato_norsk = dokumentdato.get("dato")
    dato_iso = til_iso(dato_norsk)
    periode = gjelder_periode(datoer)
    # Datospennet i en BUNKE er noe annet enn perioden dokumentet gjelder
    # for — begge kan finnes samtidig, og de skal ikke forveksles
    spenn = dokumentdato.get("periode")
    eier = finn_dokument_eier(tekst)
    stempler = stempeldatoer(tekst, datoer)

    profil = {
        "skjemaversjon": SKJEMAVERSJON,

        "fil": {
            "filnavn": filnavn,
            "antall_sider": antall_sider,
            "blanke_sider": blanke_sider(tekst),
            # krever OCR-konfidens per side; finnes ikke ennå, og «[]»
            # ville påstått at vi har sjekket
            "uleselige_sider": None,
        },

        "eier": {
            "navn": eier["navn"],
            "fnr": eier["fnr"],
            "fodselsdato": _fodselsdato_av_fnr(eier["fnr"]),
            "sikkerhet": eier["sikkerhet"],
            "begrunnelse": eier["begrunnelse"],
        },

        # ALDRI sammenblandet med eier — se R69
        "andre_personer": eier["andre_fodselsnummer"],

        "dokument": {
            "type": s_dok.get("dokumenttype") or None,
            "tittel": s_dok.get("tittel") or None,
            "sprak": s_dok.get("sprak") or None,
            "kontornavn": s_dok.get("kontornavn") or None,
            "fylke": s_dok.get("fylke") or None,

            "dato": dato_iso,
            "dato_norsk": dato_norsk,
            "ar": int(dato_iso[:4]) if dato_iso else None,
            "alder": dokumentets_alder(dato_norsk) if dato_norsk else None,
            "dato_kilde": dokumentdato.get("kilde"),
            "dato_sikkerhet": dokumentdato.get("konfidens") or "ingen",
            "dato_begrunnelse": dokumentdato.get("begrunnelse"),
            "dato_side": dokumentdato.get("side"),

            # perioden dokumentet GJELDER FOR (null når det ikke er en periode)
            "periode_start": til_iso(periode["fra"]) if periode else None,
            "periode_slutt": til_iso(periode["til"]) if periode else None,

            # datospennet når filen er en BUNKE av flere daterte dokumenter
            "spenn_fra": til_iso(spenn["fra"]) if spenn else None,
            "spenn_til": til_iso(spenn["til"]) if spenn else None,
            "flere_dokumenter": bool(spenn and spenn.get("flere_dokumenter")),
        },

        "sak": {
            "saksnummer": s_ident.get("saksnummer") or None,
            **sak_felter(tekst),
            # sakstype hører til samme regelverk som ytelse — kommer
            # sammen med det, ikke gjettet i mellomtiden
            "sakstype": None,
        },

        # Ytelsesreglene kommer senere. Navnet hentes fra den ENE
        # detektoren som finnes (struktur), så profilen og /uttrekk ikke
        # kan si hver sin ting; resten står tomt til reglene er på plass.
        "ytelse": {
            "navn": s_dok.get("ytelse") or None,
            "type": None,
            "utfall": None,
            "gyldig_fra": None,
            "gyldig_til": None,
            "status": "delvis_implementert" if s_dok.get("ytelse")
                      else "ikke_implementert",
        },

        "okonomi": {
            **okonomi_felter(tekst),
            "valuta": "NOK",
            "kontonummer": s_ident.get("kontonummer") or [],
            "kid": s_ident.get("kid") or [],
        },

        "arbeid": {
            **arbeid_felter(tekst),
            "organisasjonsnummer": s_ident.get("organisasjonsnummer") or [],
        },

        "kontakt": {
            "telefoner": s_kontakt.get("telefoner") or [],
            "eposter": s_kontakt.get("eposter") or [],
            "adresser": struktur.get("adresser") or [],
        },

        "koder": koder_med_sider(strekkoder, strekkoder_lest),

        "visuelt": {
            "stempel_datoer": stempler,
            "stempel_sider": sorted({s["side"] for s in stempler if s["side"]}),
            # krever bildeanalyse av signaturfelt; ikke bygget ennå, og
            # «[]» ville påstått at vi har sett etter
            "signatur_sider": None,
            "handskrift_funnet": bool(handskrift),
        },
    }

    # Bunkedeling: en fil er ofte en saksmappe, ikke ett dokument. Lista
    # har alltid minst én oppføring, så en klient kan gå gjennom den
    # uten først å sjekke om filen «var» en bunke.
    profil["dokumenter"] = del_i_dokumenter(
        tekst, datoer, filens_type=profil["dokument"]["type"])
    profil["sammendrag"] = _sammendrag(profil, len(profil["dokumenter"]))
    return profil

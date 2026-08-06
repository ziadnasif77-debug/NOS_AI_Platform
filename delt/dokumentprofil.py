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
from delt.konstanter import YTELSE_TERM
from delt.tekstuttrekk import (DOKUMENTTYPE_TERM, ROLLE_BEHANDLING,
                               ROLLE_DOKUMENT, dokumentets_alder,
                               finn_alle_fodselsnummer, finn_alle_ytelser,
                               finn_lovhenvisninger, fodselsdato_av_fnr,
                               gjelder_periode as _gjelder_periode,
                               kodeverk, rolle_for_type, ytelse_kodet)

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

# Bor nå i tekstuttrekk, sammen med den øvrige datoklassifiseringen, så
# skjemautfyllingen kan bruke NØYAKTIG samme begrep. Navnet beholdes her
# fordi profilen og testene importerer det herfra.
gjelder_periode = _gjelder_periode


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
        funn.append({"dato": iso, "dato_original": d.get("raatekst"),
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
                # Posisjonen der beviset FAKTISK står. Uten den måtte
                # «opphav» lete opp nummeret på nytt — og fant da første
                # forekomst, som gjerne er et umerket treff på en helt
                # annen side enn etiketten begrunnelsen viser til.
                # Målt på en ekte bunke: begrunnelsen sa «under
                # Opplysninger om» (side 4), opphav sa side 1.
                "posisjon": start,
            })

    def svar(navn, fnr, sikkerhet, begrunnelse, posisjon=None):
        # Alt som IKKE er eierens nummer havner her — én oppføring per
        # unikt nummer, aldri sammenblandet med eierens.
        andre, sett = [], set()
        for k in kandidater:
            if k["fnr"] == fnr or k["fnr"] in sett:
                continue
            sett.add(k["fnr"])
            andre.append(k)
        return {"navn": navn, "fnr": fnr, "sikkerhet": sikkerhet,
                "begrunnelse": begrunnelse, "andre_fodselsnummer": andre,
                "posisjon": posisjon}

    if not kandidater:
        return svar(None, None, "ingen",
                    "Dokumentet inneholder ingen fødselsnummer som består "
                    "kontrollsifferet (mod11).")

    eiere = [k for k in kandidater if k["rolle"] == "eier"]
    unike_eiere = {k["fnr"] for k in eiere}
    if len(unike_eiere) == 1:
        beste = eiere[0]
        # Samme nummer kan være merket som eier FLERE steder, og bare
        # noen av dem har et navn ved siden av. Målt på en ekte bunke:
        # tre eier-treff på side 4, 5 og 6 — det første («Opplysninger
        # om») hadde INTET navn, de to andre hadde «Ola Nordmann».
        # Å ta navnet fra den første ga part.navn = null på et dokument
        # der navnet står seks steder.
        med_navn = next((k for k in eiere if k["navn"]), None)
        navn = med_navn["navn"] if med_navn else None
        return svar(navn, beste["fnr"], "merket",
                    f"Fødselsnummeret står under «{beste['etikett']}», som "
                    f"peker på personen dokumentet gjelder.",
                    beste["posisjon"])
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
    """Fødselsdatoen fra et BEVIST fødselsnummer, i ISO.

    Regnestykket — inkludert århundret, som ligger i individsifrene —
    bor i `tekstuttrekk.fodselsdato_av_fnr`. Denne fila hadde tidligere
    sin egen kopi som hardkodet `1900 + år`, og ga derfor feil århundre
    for alle født etter 1999. To kopier av samme regel, og profilen
    hadde den gale."""
    deler = fodselsdato_av_fnr(fnr)
    if not deler:
        return None
    dag, maaned, aar = deler
    return f"{aar:04d}-{maaned:02d}-{dag:02d}"


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
            # ingen arv fra filens type: et dokument vi ikke kjenner
            # igjen, skal si «vet ikke» — ikke låne naboens etikett.
            # SAMME form som «dokument.type»: feltet var en bar streng
            # her og et {kode, term}-par der — samme begrep i to
            # representasjoner, som R111 forbyr. En klient måtte da
            # skrive to kodeveier for det samme.
            "type": kodeverk(gjett_dokumenttype(g["tekst"]) or None,
                             DOKUMENTTYPE_TERM),
            "tittel": forste[:100] or None,
            # UTTRUKKET av DETTE dokumentets tekst, ikke arvet fra
            # filens hovedpart. En skannet bunke kan inneholde
            # dokumenter om ULIKE personer, og arv ville skjult det.
            # Står det null her mens «part» er fylt, betyr det at
            # nettopp dette dokumentet ikke navngir noen — ikke at
            # opplysningen mangler i filen.
            "eier_navn": eier["navn"],
            "eier_fnr": eier["fnr"],
            "eier_grunnlag": _GRUNNLAG.get(eier["sikkerhet"],
                                           eier["sikkerhet"]),
        })
    return ut


def _hjemler(tekst, dato_iso, lov_id) -> list:
    """Bestemmelsene dokumentet SELV viser til, slått opp i riktig lov.

    Skilt fra `hjemmel` med vilje: den sier hvilken lov som GJALDT da
    dokumentet ble skrevet, dette sier hva dokumentet HENVISER til. Et
    vedtak kan vise til flere paragrafer, og et klagebrev siterer gjerne
    både bestemmelsen det klages på og saksbehandlingsregelen.

    Uten kjent lov (ingen dokumentdato) slås ingenting opp — det samme
    paragrafnummeret betyr ULIKE ting i 1966- og 1997-loven, og å velge
    én av dem uten grunnlag ville gitt et svar som ser riktig ut. Da står
    henvisningen der med `kapittel_tittel: null` og `flertydig: true`.
    """
    funn = finn_lovhenvisninger(tekst)
    if not funn:
        return []
    try:
        from delt import lover as _lover
    except Exception:
        _lover = None

    ut = []
    for ref in funn:
        # En UDELT paragraf (§ 29) kan ikke være folketrygdloven — den
        # nummererer kapittel-ledd (§ 8-2). Å skrive «ftrl-1997» på den
        # ville vært en påstand vi VET er feil; den vanligste er
        # forvaltningsloven, som ikke er registrert her.
        annen_lov = ref["kapittel"] is None
        post = {"referanse": ref["referanse"], "kapittel": ref["kapittel"],
                "lov": None if annen_lov else lov_id,
                "kapittel_tittel": None,
                "flertydig": lov_id is None and not annen_lov,
                "lov_nevnt_i_teksten": ref["lov_nevnt"],
                "merknad": ("Udelt paragrafnummer — hører til en ANNEN lov "
                            "enn folketrygdloven (ofte forvaltningsloven). "
                            "Den loven er ikke registrert, så henvisningen "
                            "slås ikke opp." if annen_lov else None)}
        if _lover and lov_id and ref["kapittel"]:
            try:
                # kapitler() gir {nummer: tittel} — tittelen ER verdien
                post["kapittel_tittel"] = \
                    _lover.kapitler(lov_id).get(ref["kapittel"])
            except Exception:
                pass
        ut.append(post)
    return ut


def _hjemmel(dato_iso, ytelse_navn=None) -> dict:
    """Hvilken lov som gjaldt DA DOKUMENTET BLE TIL.

    Et vedtak fra 1994 skal leses mot folketrygdloven av 1966, ikke mot
    dagens. Den gamle loven er ikke historikk vi kan se bort fra: den er
    hjemmelen for vedtak som fortsatt har virkning, og paragrafnumrene
    peker på helt andre ytelser enn i den nye.

    Finner vi ytelsen i dokumentet, slås den også opp i RIKTIG lov, så
    «uførepensjon» i et gammelt vedtak havner i 1966-lovens kapittel 8
    og ikke i 1997-lovens kapittel 12."""
    tomt = {"lov": None, "lov_tittel": None, "status": None,
            "begrunnelse": None, "ytelse_kapittel": None,
            "ytelse_kapittel_tittel": None}
    try:
        from delt import lover as _lover
    except Exception as exc:                      # registeret mangler
        return {**tomt, "begrunnelse": f"Lovregisteret er utilgjengelig: {exc}"}

    try:
        valg = _lover.lov_for_dato(dato_iso)
    except Exception as exc:
        return {**tomt, "begrunnelse": f"Lovvalget feilet: {exc}"}

    svar = {**tomt, "begrunnelse": valg["begrunnelse"]}
    if not valg["lov"]:
        return svar
    try:
        meta = _lover.lov(valg["lov"])
    except KeyError:
        return svar
    svar.update(lov=valg["lov"], lov_tittel=meta.get("tittel"),
                status=meta.get("status"))

    if ytelse_navn:
        # søk BARE i den loven som gjaldt — et treff i feil lov er verre
        # enn ingen treff, fordi det ser like riktig ut
        try:
            treff = _lover.sok_ytelse(ytelse_navn, lov_id=valg["lov"])
        except Exception:
            treff = []
        if treff:
            svar["ytelse_kapittel"] = treff[0]["kapittel"]
            svar["ytelse_kapittel_tittel"] = treff[0]["kapittel_tittel"]
    return svar


def _sammendrag(profil: dict, antall_dokumenter: int) -> dict:
    """De få feltene de fleste er ute etter, øverst.

    Profilen er komplett og derfor lang. Et sammendrag gjør at den som
    bare skal vite «hvem og når» slipper å lete — uten at noe fjernes
    for den som trenger resten. «sikkerhet» er det SVAKESTE leddet, ikke
    et gjennomsnitt: er PARTEN usikker, hjelper det ikke at datoen er
    sikker."""
    part, dok = profil["part"], profil["dokument"]
    # «etikett» er den ENESTE grunnlagsverdien som er et positivt funn;
    # resten forteller hvorfor vi ikke har et nummer.
    ledd = [part["grunnlag"] == "etikett",
            dok["dato_sikkerhet"] == "hoy",
            antall_dokumenter <= 1]
    if all(ledd):
        sikkerhet = "hoy"
    elif part["fnr"] and dok["dato"]:
        sikkerhet = "middels"
    else:
        sikkerhet = "usikker"
    return {
        "navn": part["navn"],
        "fnr": part["fnr"],
        "dokumentdato": dok["dato"],
        # Projeksjon: bare koden. Hele {kode, term}-paret hører
        # hjemme i seksjonen, ikke i et sammendrag man skummer.
        "dokumenttype": (dok["type"] or {}).get("kode"),
        "ytelse": (profil["ytelse"]["navn"] or {}).get("kode"),
        "saksnummer": profil["sak"]["saksnummer"],
        "antall_sider": profil["fil"]["antall_sider"],
        "antall_dokumenter": antall_dokumenter,
        # «sikkerhet» betyr fire ulike ting i dette API-et — security i
        # /hjelp, konfidens her, beviskategori i parten, og en annen
        # skala i dato_sikkerhet («usikker» mot «lav» for samme akse).
        # «konfidens» er navnet, med ÉN skala overalt.
        "konfidens": _EN_SKALA.get(sikkerhet, sikkerhet),
    }


# Én ordnet konfidensskala for hele API-et. «usikker» var et fjerde ord
# for det «lav» allerede het, så en klient som filtrerte på «lav» aldri
# traff sammendraget.
_EN_SKALA = {"usikker": "lav"}

# Beviskategoriene i eier-oppslaget er IKKE en gradert skala —
# «flertydig» betyr at vi fant MER bevis, ikke mindre, og kan ikke
# rangeres mot «umerket». De hører til en egen akse: grunnlaget.
_GRUNNLAG = {
    "merket": "etikett",
    "flertydig": "flertydig",
    "bare_andre_roller": "bare_andre_roller",
    "umerket": "umerket",
    "ingen": "ingen",
}


def _part(eier: dict) -> dict:
    """Personen dokumentet gjelder (R69).

    «grunnlag» er en BEVISKATEGORI, ikke en grad: «flertydig» betyr at
    vi fant MER bevis, ikke mindre, og kan ikke rangeres mot «umerket».
    «fastslatt» svarer på det spørsmålet de fleste faktisk stiller —
    fant dere personen? — så nye bevistilstander kan legges til i
    «grunnlag» uten å brekke noen som matcher på enum."""
    return {
        "navn": eier["navn"],
        "fnr": eier["fnr"],
        "fodselsdato": _fodselsdato_av_fnr(eier["fnr"]),
        "fastslatt": eier["fnr"] is not None,
        "grunnlag": _GRUNNLAG.get(eier["sikkerhet"], eier["sikkerhet"]),
        "begrunnelse": eier["begrunnelse"],
        # Understrek = INTERN. Ikke en del av kontrakten; «opphav» leser
        # den for å oppgi den siden beviset FAKTISK står på, og fjerner
        # den fra svaret. Uten den lette opphav opp nummeret på nytt og
        # fant første forekomst — en helt annen side enn etiketten.
        "_posisjon": eier.get("posisjon"),
    }


def sidedekning(tekst: str, antall_sider) -> dict:
    """Hvor mye av dokumentet uttrekket FAKTISK så.

    Dette er den farligste tause avkortingen i hele API-et. Et skannet
    dokument på 500 sider får som standard OCR på 10 av dem — to
    prosent — og resten av profilen svarer likevel som om den hadde
    lest hele: `part.fnr: null` med begrunnelsen «Dokumentet inneholder
    ingen fødselsnummer». Den setningen er ikke sann. Vi så ikke etter
    i 98 % av dokumentet.

    Advarselen sto i `varsler`, men ved millioner av dokumenter leser
    ingen `varsler` — de leser feltet og handler på det. Derfor er
    dekningen et FELT, ikke en tekst.

    Målt på sidemerkene `[Side N av M]`, som OCR-/tekstlaget setter for
    hver side den faktisk leverte tekst fra."""
    totalt = antall_sider if isinstance(antall_sider, int) else None
    lest = len({int(n) for n in re.findall(r"\[Side (\d+) av \d+\]",
                                           tekst or "")})
    if not totalt:
        # Uten sideantall vet vi ikke hva vi sammenligner mot. Da er
        # svaret «vet ikke» — ikke «alt er lest».
        return {"grad": "ukjent", "lest": lest or None, "totalt": None}
    if not lest:
        # Ingen sidemerker: enten ett-sides dokument eller ren tekst
        # sendt inn direkte. Begge deler er full dekning.
        return {"grad": "full", "lest": totalt, "totalt": totalt}
    if lest >= totalt:
        return {"grad": "full", "lest": totalt, "totalt": totalt}
    return {"grad": "delvis", "lest": lest, "totalt": totalt}


# Setningen som gjør enhver «vi fant ingenting»-begrunnelse ærlig når
# bare deler av dokumentet ble lest.
def _med_forbehold(begrunnelse, dekning) -> str:
    if not begrunnelse or (dekning or {}).get("grad") != "delvis":
        return begrunnelse
    return (f"{begrunnelse} MERK: bare {dekning['lest']} av "
            f"{dekning['totalt']} sider ble lest, så dette gjelder de "
            f"leste sidene — ikke hele dokumentet.")


def _iso_datoer(felter: dict, navn) -> dict:
    """Gjør de navngitte datofeltene om til ISO.

    Profilen erklærer ISO («leses av andre systemer»), men feltene fra
    saksfelter.py kom gjennom `finn_dato` og var norske. Resultatet var
    `arbeid.startdato: "01.08.2019"` i samme objekt som
    `dokument.dato: "2026-05-28"` — en klient kunne ikke vite hvilket
    format et datofelt hadde uten en tabell.

    Den norske formen fulgte en stund med som `_norsk`-tvilling. Den er
    borte: målt gir «28. mai 2026», «28/05/2026», «2026-05-28» og
    «28.5.26» ALLE samme tvilling «28.05.2026» — den var altså en andre
    RENDERING av den normaliserte verdien, ikke det som sto i
    dokumentet. En klient som har ISO kan formatere selv.

    Det som er verdt å ta vare på er den EKTE originalen, og den ligger
    i `dokument.dato_original`."""
    ut = dict(felter)
    for n in navn:
        ut[n] = til_iso(ut.get(n))
    return ut


# Valutamarkører slik de faktisk står i norske dokumenter
_VALUTA = re.compile(r"(?i)\b(NOK|SEK|DKK|EUR|USD|GBP|CHF|ISK)\b|(?<![A-Za-z])kr\.?(?![A-Za-z])")


def _valuta(tekst: str) -> dict:
    """Valutaen dokumentet faktisk oppgir.

    Feltet var hardkodet `"NOK"` og ble aldri lest fra dokumentet — en
    påstand om en måling som ikke var gjort. Er dokumentet i SEK eller
    EUR, svarte API-et likevel NOK. Nå: finnes en markør, brukes den;
    finnes ingen, sier vi det i stedet for å gjette."""
    treff = _VALUTA.search(tekst or "")
    if not treff:
        return {"valuta": None,
                "valuta_merknad": "Ingen valutamarkør funnet i dokumentet"}
    kode = (treff.group(1) or "NOK").upper()   # bar «kr» ⇒ norske kroner
    return {"valuta": kode, "valuta_merknad": None}


# Første utgivelse — se API_VERSJON i dokument_api.py for hvorfor det
# ikke er 2.0.
SKJEMAVERSJON = "1.0"


def bygg_profil(tekst, *, filnavn=None, antall_sider=None, strekkoder=None,
                strekkoder_lest=True, datoer_detaljert=None,
                dokumentdato=None, struktur=None, handskrift=None) -> dict:
    """Setter sammen dokumentprofilen — den kanoniske formen (R79).

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

        # «part» er forvaltningslovens term (§ 2 e: «den en avgjørelse
        # retter seg mot») og nøyaktig det deteksjonen matcher på.
        # «eier» er juridisk feil, og feil i en FARLIG retning: i
        # dokumentforvaltning betyr «dokumenteier» arkiveier eller
        # ansvarlig saksbehandler — altså nettopp personen R69 finnes
        # for å utelukke. En integrasjon som mapper «eier» mot sitt
        # arkivsystems eierfelt treffer feil person.
        "part": _part(eier),


        # ALDRI sammenblandet med parten — se R69. Feltet er nøklet på
        # fødselsnummer og deduplisert på det, så en person nevnt bare
        # ved navn kommer ikke med. Navnet «andre_personer» lovet mer
        # enn feltet kan holde, og ble derfor forkastet.
        "andre_fodselsnummer": eier["andre_fodselsnummer"],


        "dokument": {
            # ETT felt, ikke to. «type» og «type_kodet» bar alltid
            # samme kode — en speiltest håndhevet det — så paret var en
            # kopi av seg selv. Nå ER verdien paret: koden er stabil og
            # maskinlesbar, termen er for et menneske. Kodene er skrevet
            # uten æøå fordi de matches mot OCR-tekst; termen har dem.
            "type": kodeverk(s_dok.get("dokumenttype") or None,
                             DOKUMENTTYPE_TERM),
            "tittel": s_dok.get("tittel") or None,
            "sprak": s_dok.get("sprak") or None,
            "kontornavn": s_dok.get("kontornavn") or None,
            "fylke": s_dok.get("fylke") or None,

            "dato": dato_iso,
            # ordrett slik det sto i dokumentet — «28. mai 2026»,
            # «28/05/2026». Den normaliserte formen er «dato».
            "dato_original": (dokumentdato or {}).get("raatekst"),
            # «aarstall», ikke «ar»: den sto rett ved siden av
            # «alder.aar» — to skrivemåter av samme bokstav, to
            # betydninger (årstallet kontra hvor gammelt dokumentet er).
            "aarstall": int(dato_iso[:4]) if dato_iso else None,
            "alder": dokumentets_alder(dato_norsk),
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
            # sammen med det, ikke gjettet i mellomtiden. Det KODEDE
            # feltet er med allerede, så formen ikke endres senere:
            # en klient som leser sakstype_kodet i dag får null, ikke en
            # manglende nøkkel.
            # Formen er fast selv om reglene ikke er bygget: en
            # RPA-robot som leser sakstype.kode skal ikke krasje den
            # dagen feltet fylles (R118). «dekning.sakstype» sier at vi
            # ikke leter etter det ennå.
            "sakstype": {"kode": None, "term": None},
        },

        # Ytelsesreglene kommer senere. Navnet hentes fra den ENE
        # detektoren som finnes (struktur), så profilen og /uttrekk ikke
        # kan si hver sin ting; resten står tomt til reglene er på plass.
        # «status» her publiserte VÅR byggeframdrift som domenetilstand:
        # {"navn": "sykepenger", "status": "delvis_implementert"} leses
        # naturlig som at sykepengesaken er delvis behandlet. Verre —
        # navnet var opptatt av et verdirom det ikke kan vokse inn i,
        # for når ytelsesreglene lander er de riktige verdiene
        # «innvilget»/«lopende»/«opphort». Modenheten bor nå i
        # «dekning»; «status» er frigjort til å bety ytelsens status.
        "ytelse": {
            # KODEN er NAVs offisielle temakode («SYK»), ikke vårt
            # interne norske ord — det er den andre NAV-systemer og en
            # RPA-robot kan rute på (R127).
            "navn": ytelse_kodet(s_dok.get("ytelse") or None),
            # Det norske ordet, internt. Understrek = ute av svaret
            # (_profilform fjerner det), men «opphav» trenger det for å
            # finne siden ordet FAKTISK står på: et søk etter «SYK»
            # ville enten bommet eller truffet inne i «sykemelding».
            "_ord": s_dok.get("ytelse") or None,
            "type": None,
            "utfall": None,
            "gyldig_fra": None,
            "gyldig_til": None,
            "status": None,
        },

        "okonomi": {
            **_iso_datoer(okonomi_felter(tekst), ("utbetalingsdato",)),
            **_valuta(tekst),
            "kontonummer": s_ident.get("kontonummer") or [],
            "kid": s_ident.get("kid") or [],
        },

        "arbeid": {
            **_iso_datoer(arbeid_felter(tekst), ("startdato", "sluttdato")),
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

    # Hjemmelen følger DOKUMENTETS alder, ikke dagens dato. En bunke kan
    # spenne over lovskiftet i 1997, og da har dokumentene i den ulik
    # hjemmel — derfor avgjøres den per dokument, ikke bare for filen.
    # «gjeldende_lov», ikke «hjemmel»: den er AVLEDET av dokumentets
    # dato og sier hvilken lov som gjaldt da — den er ikke noe
    # dokumentet påberoper seg. Det dokumentet FAKTISK viser til ligger
    # i «hjemler». To navn som lignet på hverandre skjulte at det var
    # to ulike spørsmål.
    # Det NORSKE ordet inn i lovoppslaget, ikke temakoden: kapitlene i
    # folketrygdloven heter «Sykepenger», og `sok_ytelse("SYK")` ville
    # truffet både kapittel 8 og 9 — flertydig der ordet er entydig.
    profil["gjeldende_lov"] = _hjemmel(
        profil["dokument"]["dato"], profil["ytelse"]["_ord"])
    for dok in profil["dokumenter"]:
        egen = _hjemmel(dok["dato"])
        dok["lov"] = egen["lov"]
        dok["lov_status"] = egen["status"]

    # ÉN ytelse taper informasjon: et AAP-vedtak viser nesten alltid til
    # sykepengeperioden som tok slutt, og profilen sa da bare
    # «arbeidsavklaringspenger». Lista har alle, i den rekkefølgen de
    # står; «ytelse» over er fortsatt den mest spesifikke og ligger
    # ALLTID i lista (vokterprøve).
    dekning_sider = sidedekning(tekst, antall_sider)

    # Enhver «vi fant ingenting»-begrunnelse må si fra når den bare
    # gjelder de leste sidene. Uten dette lyver den: «Dokumentet
    # inneholder ingen fødselsnummer» på et dokument vi så 2 % av.
    for _sti in (("part", "begrunnelse"),
                 ("dokument", "dato_begrunnelse")):
        _seksjon = profil.get(_sti[0]) or {}
        if _seksjon.get(_sti[1]):
            _seksjon[_sti[1]] = _med_forbehold(_seksjon[_sti[1]],
                                               dekning_sider)

    # Temakodene er BEVISST mange-til-én (uføretrygd og uførepensjon er
    # begge UFO; de tre kapittel 9-ytelsene er alle OMS). Uten avduping
    # ville et brev som nevner både pleiepenger og omsorgspenger fått
    # OMS to ganger i lista — samme tema listet opp som om det var to.
    # Rekkefølgen (første forekomst) beholdes.
    profil["ytelser"] = []
    _sett = set()
    for _navn in finn_alle_ytelser(tekst):
        _par = ytelse_kodet(_navn)
        _nokkel = (_par["kode"], _par["term"])
        if _nokkel not in _sett:
            _sett.add(_nokkel)
            profil["ytelser"].append(_par)

    # «hjemmel» sier hvilken lov som GJALDT. «hjemler» sier hvilke
    # bestemmelser dokumentet SELV viser til — to ulike spørsmål. Et
    # klagebrev siterer gjerne både bestemmelsen det klages på og
    # saksbehandlingsregelen, og én hjemmel kan ikke bære det.
    profil["hjemler"] = _hjemler(tekst, profil["dokument"]["dato"],
                                 profil["gjeldende_lov"]["lov"])

    # Hva systemet FAKTISK er i stand til å fastslå ennå. Profilen hadde
    # fire «ikke bygget ennå»-nuller spredt rundt, hver med sin egen
    # kommentar i koden og ingen markør i JSON-en — en klient kunne ikke
    # skille «vi så etter og fant ingenting» fra «vi så aldri etter».
    profil["dekning"] = {
        # FØRST, fordi den overstyrer alt annet: er bare 10 av 500
        # sider lest, sier ingen andre felt noe om hele dokumentet.
        "sider_lest": dekning_sider["grad"],
        "sider": {"lest": dekning_sider["lest"],
                  "totalt": dekning_sider["totalt"]},
        # NB: «navn» er nå ALLTID et par (R118), så en sannhetstest på
        # selve objektet er alltid sann. Og det er ORDET, ikke temakoden,
        # som avgjør om ytelsen ble funnet: NAVs temakodeliste er levert
        # stykkevis, og en ytelse som venter på koden sin ville meldt
        # «ikke_evaluert» — altså at vi aldri lette — om noe vi tydelig
        # leste i teksten. Alle 25 har kode i dag; veien står åpen for
        # den neste som ikke gjør det.
        "ytelse": ("delvis" if profil["ytelse"]["_ord"]
                   else "ikke_evaluert"),
        "sakstype": "ikke_evaluert",
        "signatur_sider": "ikke_evaluert",
        "uleselige_sider": "ikke_evaluert",
        "forklaring": ("«ikke_evaluert» betyr at systemet ikke leter "
                       "etter feltet ennå — det sier INGENTING om "
                       "dokumentet, og en klient skal ikke melde avvik. "
                       "Feltet het «ingen», som i et API leses som «finnes "
                       "ikke» — to helt ulike ting under ett ord. "
                       "«delvis» betyr at noe fastslås, men ikke alt; "
                       "«full» at et null-svar er en påstand om "
                       "dokumentet. «sider_lest: delvis» overstyrer "
                       "resten: da gjelder INGEN av feltene hele "
                       "dokumentet, bare de leste sidene."),
    }
    profil["sammendrag"] = _sammendrag(profil, len(profil["dokumenter"]))

    # Konfidensen er det SVAKESTE leddet (R74), og å ha lest 10 av 500
    # sider ER et svakt ledd. «hoy» på det grunnlaget er feil uansett
    # hvor sikre de leste feltene er hver for seg.
    if (dekning_sider["grad"] == "delvis"
            and profil["sammendrag"]["konfidens"] == "hoy"):
        profil["sammendrag"]["konfidens"] = "middels"
    return profil

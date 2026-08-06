"""Opphav — ÉN proveniensmodell for hele svaret fra `POST /dokument`.

Bakgrunn (revisjonen, §5): API-et forklarte hvor et funn kom fra på fem
uavhengige måter — `dato_kilde`, `dato_sikkerhet`, `part.grunnlag`,
`kilde_per_felt` og `kilde` — med hvert sitt ordforråd. En klient som
ville vite «hvor sikkert er dette, og hvorfor?» måtte lære alle fem, og
to av dem brukte samme ord om ulike ting.

`opphav` er ett oppslag: JSON Pointer (RFC 6901) inn, opphavet ut. Samme
pekersyntaks som `problem.errors[].pointer` allerede bruker, så en klient
som håndterer valideringsfeil kan gjenbruke koden sin.

To LUKKEDE ordforråd, aldri gjenbrukt til noe annet:

  metode    sjekksum · etikett · posisjon · metadata · strekkode ·
            regel · modell · avledet · ingen
  konfidens hoy · middels · lav · ingen        (samme skala overalt)

VIKTIG: kartet er en PROJEKSJON. Verdiene leses ut av de feltene
profilen allerede har fylt — de regnes ikke ut på nytt. Ellers ville
`opphav` blitt en sjette uavhengig mening, altså akkurat problemet det
skal løse. De gamle feltene står urørt ved siden av; ingen klient
brekker.
"""
import re

# Lukkede ordforråd. En verdi utenfor disse er en feil i kartet, ikke en
# ny kategori — testene håndhever det.
METODER = ("sjekksum", "etikett", "posisjon", "metadata", "strekkode",
           "regel", "modell", "avledet", "ingen")
KONFIDENSNIVAA = ("hoy", "middels", "lav", "ingen")

# «viktige» er standard: pekerne de fleste klientene faktisk handler på.
# Alt er tilgjengelig med opphav=alle, men et kart over hvert eneste felt
# gjør svaret større uten å gjøre det klarere for den vanlige bruken.
VIKTIGE = ("/dokumentprofil/part/fnr", "/dokumentprofil/dokument/dato")

NIVAAER = ("ingen", "viktige", "alle")

# Dokumentdatoens «kilde» bruker allerede tre av ordene våre. «pdf_metadata»
# er det ene som må oversettes — kartet her er oversettelsen, ikke en ny
# vurdering.
_DATOMETODE = {"etikett": "etikett", "posisjon": "posisjon",
               "pdf_metadata": "metadata"}

# Partens «grunnlag» er en beviskategori med FEM verdier (se _GRUNNLAG i
# dokumentprofil.py). Bare «etikett» er et positivt funn; «flertydig»,
# «bare_andre_roller», «umerket» og «ingen» forteller alle HVORFOR vi
# ikke har et nummer — og da er metoden «ingen», ikke en svakere metode.
_PARTMETODE = {"etikett": "etikett"}

# … og hvor sikkert funnet er. Nøklene er GRUNNLAG-verdier: «sikkerhet»
# var det gamle navnet på samme akse og finnes ikke lenger.
_PARTKONFIDENS = {"etikett": "hoy", "flertydig": "lav",
                  "bare_andre_roller": "ingen", "umerket": "lav",
                  "ingen": "ingen"}


def _sidekart(tekst: str):
    """(posisjon, sidetall) for hvert `[Side N av M]`-merke, sortert.

    Bygges ÉN gang per dokument. Uten det ville hvert oppslag skannet
    hele teksten på nytt — og på en bunke med hundre felter og hundre
    sider blir det målbart."""
    return [(m.start(), int(m.group(1)))
            for m in re.finditer(r"\[Side (\d+) av \d+\]", tekst or "")]


def _bare_tegn(tekst: str):
    """(strippet tekst, indekskart tilbake til originalen).

    Uttrukne verdier er NORMALISERTE: kontonummeret «1234.56.78903» blir
    lagret uten punktumene, og beløpet «kr 1 234,00» blir tallet 1234.0. Et
    tekstsøk finner dem derfor ikke, og siden ble stående null på nettopp
    de feltene en saksbehandler oftest må kontrollere.

    Her fjernes alt som ikke er bokstav eller siffer, og hver beholdt
    posisjon husker hvor den kom fra — så treffet kan oversettes tilbake
    til en posisjon i originalteksten."""
    biter, kart = [], []
    for i, tegn in enumerate(tekst or ""):
        if tegn.isalnum():
            biter.append(tegn.lower())
            kart.append(i)
    return "".join(biter), kart


def side_for_verdi(tekst: str, verdi, sidekart=None, strippet=None):
    """Hvilken SIDE en uttrukket verdi står på — eller None.

    Klientene henter dokumenter fra flere systemer og trenger å vite
    hvor i bunken et funn kom fra: et saksnummer på side 2 og et på side
    40 er ikke det samme saksnummeret, og en saksbehandler som skal
    kontrollere må vite hvor hen skal se.

    Søker først ORDRETT, deretter på strippet form (se `_bare_tegn`), så
    normaliserte identifikatorer og beløp også får en side. Et beløp
    prøves både som `1234.0` og som «1234,00», siden dokumentet skriver
    det siste.

    FØRSTE forekomst vinner. Står samme verdi på flere sider, er det
    den første som meldes — en bevisst forenkling; en liste ville brutt
    formstabiliteten for et felt som er ett tall.

    Returnerer None når verdien ikke finnes i teksten i det hele tatt.
    Det er riktig for AVLEDEDE verdier: fødselsdatoen er regnet ut av
    fødselsnummeret, og lovvalget av dokumentdatoen — de står ikke på
    noen side."""
    if verdi in (None, "", [], {}):
        return None
    naal = str(verdi)
    if not naal.strip():
        return None
    i = (tekst or "").find(naal)
    if i < 0:
        # normalisert form: strippet for alt annet enn bokstav/siffer
        flat, kart = _bare_tegn(tekst) if strippet is None else strippet
        kandidater = [naal]
        if isinstance(verdi, float):
            # 1234.0 skrives «1 234,00» i dokumentet
            kandidater.append(f"{verdi:.2f}")
        for k in kandidater:
            n, _ = _bare_tegn(k)
            if not n:
                continue
            j = flat.find(n)
            if j >= 0:
                i = kart[j]
                break
        else:
            return None
    merker = _sidekart(tekst) if sidekart is None else sidekart
    if not merker:
        # ingen sidemerker = ett-sides dokument eller ren tekst
        return 1
    side = merker[0][1] if i >= merker[0][0] else None
    for pos, nr in merker:
        if i >= pos:
            side = nr
        else:
            break
    return side


def _side_for_posisjon(pos, merker):
    """Sidetallet for en KJENT tegnposisjon. Brukes når uttrekket alt
    vet hvor beviset står — da skal ingen lete etter det på nytt."""
    if pos is None:
        return None
    if not merker:
        return 1
    side = merker[0][1] if pos >= merker[0][0] else None
    for merkepos, nr in merker:
        if pos >= merkepos:
            side = nr
        else:
            break
    return side


def _post(metode, konfidens, begrunnelse=None, side=None) -> dict:
    """Én oppføring. Feltene er alltid til stede, tomt er `null` — samme
    regel som resten av profilen."""
    return {"metode": metode, "konfidens": konfidens,
            "begrunnelse": begrunnelse or None, "side": side}


def bygg_opphav(profil: dict, nivaa: str = "viktige",
                tekst: str = None) -> dict:
    """Proveniensen for feltene i profilen, som JSON Pointer → opphav.

    `nivaa`:
      ingen    tomt kart (klienten vil ikke ha det)
      viktige  parten og dokumentdatoen — det de fleste handler på
      alle     alt vi kan tilskrive et opphav

    Et felt uten verdi får ikke en oppføring med `metode: "ingen"` — det
    ville fylt kartet med støy. Unntaket er de to viktige pekerne, der
    «vi fant ingenting, og her er hvorfor» ER svaret klienten trenger.
    """
    if nivaa == "ingen":
        return {}

    # Sidemerkene leses ÉN gang; hvert felt slår opp mot den ferdige
    # lista i stedet for å skanne teksten på nytt.
    merker = _sidekart(tekst) if tekst else []
    # Strippingen gjøres ÉN gang for hele dokumentet, ikke per felt.
    strippet = _bare_tegn(tekst) if tekst else None

    def side(verdi):
        return (side_for_verdi(tekst, verdi, merker, strippet)
                if tekst else None)

    kart = {}
    part = profil.get("part") or {}
    dokument = profil.get("dokument") or {}

    # --- parten (R69) -------------------------------------------------
    grunnlag = part.get("grunnlag")
    # Siden der BEVISET står — ikke der nummeret først dukker opp.
    # Målt på en ekte bunke sa begrunnelsen «under Opplysninger om»
    # (side 4) mens opphav sa side 1, der det samme nummeret sto
    # UMERKET. En saksbehandler som slo opp side 1 fant ingen etikett,
    # og da er hele feltet verdiløst.
    kart["/dokumentprofil/part/fnr"] = _post(
        _PARTMETODE.get(grunnlag, "ingen"),
        _PARTKONFIDENS.get(grunnlag, "ingen"),
        part.get("begrunnelse"),
        _side_for_posisjon(part.get("_posisjon"), merker)
        if part.get("_posisjon") is not None else side(part.get("fnr")))

    # --- dokumentets egen dato (R80) ----------------------------------
    kart["/dokumentprofil/dokument/dato"] = _post(
        _DATOMETODE.get(dokument.get("dato_kilde"), "ingen"),
        dokument.get("dato_sikkerhet") or "ingen",
        dokument.get("dato_begrunnelse"), dokument.get("dato_side"))

    if nivaa != "alle":
        return kart

    # --- fødselsdatoen er REGNET UT av fødselsnummeret ------------------
    # «avledet» finnes nettopp for dette: verdien står ikke i dokumentet,
    # den følger av en annen verdi som gjør det. Uten skillet ser den ut
    # som et selvstendig funn.
    if part.get("navn"):
        kart["/dokumentprofil/part/navn"] = _post(
            _PARTMETODE.get(grunnlag, "ingen"),
            _PARTKONFIDENS.get(grunnlag, "ingen"),
            "Navnet står ved siden av det beviste fødselsnummeret",
            side(part.get("navn")))

    if part.get("fodselsdato"):
        kart["/dokumentprofil/part/fodselsdato"] = _post(
            "avledet", _PARTKONFIDENS.get(grunnlag, "ingen"),
            "Regnet ut av fødselsnummerets seks første siffer — står ikke "
            "nødvendigvis skrevet i dokumentet")

    # --- hjemmelen følger dokumentDATOEN (R77) -------------------------
    # Feltet het «hjemmel» og ble døpt om til «gjeldende_lov» for å si at
    # det er AVLEDET. Denne linja fulgte ikke med, så pekeren ble aldri
    # laget — en stille mangel, for et kart uten en oppføring ser ikke
    # galt ut.
    hjemmel = profil.get("gjeldende_lov") or {}
    if hjemmel.get("lov"):
        # Arver datoens konfidens: er datoen usikker, er lovvalget det
        # også — det er den datoen valget hviler på.
        kart["/dokumentprofil/gjeldende_lov/lov"] = _post(
            "avledet", dokument.get("dato_sikkerhet") or "ingen",
            hjemmel.get("begrunnelse"))

    # --- identifikatorer med sjekksum ----------------------------------
    # mod11/mod10 er matematisk bevis, ikke et mønstertreff: konfidensen
    # er «hoy» uten forbehold.
    okonomi = profil.get("okonomi") or {}
    for i, v in enumerate(okonomi.get("kontonummer") or []):
        kart[f"/dokumentprofil/okonomi/kontonummer/{i}"] = _post(
            "sjekksum", "hoy", "Elleve siffer som består mod11", side(v))
    for i, v in enumerate(okonomi.get("kid") or []):
        kart[f"/dokumentprofil/okonomi/kid/{i}"] = _post(
            "sjekksum", "hoy", "KID-nummer som består mod10/mod11", side(v))
    arbeid = profil.get("arbeid") or {}
    for i, v in enumerate(arbeid.get("organisasjonsnummer") or []):
        kart[f"/dokumentprofil/arbeid/organisasjonsnummer/{i}"] = _post(
            "sjekksum", "hoy", "Ni siffer som består mod11", side(v))

    # --- etikettbundne felter (R71) ------------------------------------
    # De hentes BARE når ordet står i dokumentet, så metoden er alltid
    # «etikett» når verdien finnes.
    for seksjon, felt in (("sak", "saksnummer"), ("sak", "journalnummer"),
                          ("sak", "vedtaksnummer"), ("sak", "dokumentnummer"),
                          ("okonomi", "dagsats"), ("okonomi", "manedsbelop"),
                          ("okonomi", "utbetalt_belop"),
                          ("arbeid", "arbeidsgiver"), ("arbeid", "stilling"),
                          ("arbeid", "stillingsprosent")):
        verdi = (profil.get(seksjon) or {}).get(felt)
        if verdi is not None:
            kart[f"/dokumentprofil/{seksjon}/{felt}"] = _post(
                "etikett", "hoy",
                "Hentet fordi etiketten står i dokumentet (R71)",
                side(verdi))

    # --- kontakt: står ofte i et brevhode på FØRSTE side, men i en
    # bunke kan hvert dokument ha sitt eget -------------------------------
    kontakt = profil.get("kontakt") or {}
    for navn in ("telefoner", "eposter"):
        for i, v in enumerate(kontakt.get(navn) or []):
            kart[f"/dokumentprofil/kontakt/{navn}/{i}"] = _post(
                "regel", "hoy", "Formvalidert (lengde/mønster)", side(v))
    for i, adr in enumerate(kontakt.get("adresser") or []):
        if isinstance(adr, dict):
            kart[f"/dokumentprofil/kontakt/adresser/{i}"] = _post(
                "etikett", "middels",
                "Gate + postnummer + poststed sto sammen",
                side(adr.get("gate")))

    # --- koder lest av dekoderen ---------------------------------------
    koder = profil.get("koder") or {}
    for navn in ("qr", "strekkode"):
        for i, k in enumerate(koder.get(navn) or []):
            # dekoderen oppgir siden selv — mer presist enn tekstsøk
            kart[f"/dokumentprofil/koder/{navn}/{i}"] = _post(
                "strekkode", "hoy", "Dekodet av pyzbar, ikke lest som tekst",
                (k or {}).get("side") if isinstance(k, dict) else None)

    # --- ytelse og dokumenttype: mønsterregler --------------------------
    # Søket må gå på det NORSKE ORDET vi faktisk fant i teksten, ikke på
    # temakoden: «SYK» står ingen steder i dokumentet, og et normalisert
    # søk etter tre bokstaver ville i verste fall truffet inne i
    # «sykemelding» og pekt på feil side.
    ytelse_ord = (profil.get("ytelse") or {}).get("_ord")
    if ytelse_ord:
        kart["/dokumentprofil/ytelse/navn"] = _post(
            "regel", "middels", "Kjent ytelsesnavn funnet i teksten",
            side(ytelse_ord))
    if (dokument.get("type") or {}).get("kode"):
        # typen avgjøres av TITTELEN, som per definisjon står først
        kart["/dokumentprofil/dokument/type"] = _post(
            "regel", "middels", "Klassifisert av tittel- og ordmønstre",
            1 if merker or tekst else None)

    return kart


def uten_utelatte(kart: dict, profil: dict) -> dict:
    """Fjerner pekere som viser til seksjoner `profil=sammendrag` tok bort.

    To grunner, og begge er reelle. En peker til et felt som ikke er i
    svaret er verre enn ingen peker: klienten slår opp, får ingenting og
    vet ikke om feltet mangler eller om pekeren er feil. Og oppføringen
    lekker det bryteren skulle skjule — `/dokumentprofil/part/fnr` med
    `metode: "etikett"` sier at det FINNES en part og hvordan vi fant
    hen, i et svar klienten uttrykkelig ba om uten persondata.
    """
    utelatt = (profil or {}).get("utelatt")
    if not utelatt:
        return kart
    stengt = tuple(f"/dokumentprofil/{navn}/" for navn in utelatt)
    return {peker: post for peker, post in kart.items()
            if not peker.startswith(stengt)}


def opphav_for_skjema(kilde_per_felt: dict) -> dict:
    """Oversetter `skjema.kilde_per_felt` til samme kart.

    `auto`-motoren svarer allerede per felt med «deterministisk» eller
    «modell». Det er den samme opplysningen i et sjette ordforråd —
    her blir den den samme som resten."""
    kart = {}
    for felt, kilde in (kilde_per_felt or {}).items():
        if kilde == "modell":
            kart[f"/skjema/skjema/{felt}"] = _post(
                "modell", "lav", "Fylt av språkmodellen — ikke bevist i "
                                 "dokumentet")
        else:
            kart[f"/skjema/skjema/{felt}"] = _post(
                "regel", "hoy", "Bevist deterministisk av uttrekket")
    return kart

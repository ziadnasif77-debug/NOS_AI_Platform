"""Opphav — ÉN proveniensmodell for hele svaret fra `POST /dokument`.

Bakgrunn (revisjonen, §5): API-et forklarte hvor et funn kom fra på fem
uavhengige måter — `dato_kilde`, `dato_sikkerhet`, `eier.sikkerhet`,
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

# … og hvor sikkert det er. Skalaen er den ene felles, ikke en fjerde.
_PARTKONFIDENS = {"merket": "hoy", "flertydig": "lav",
                  "bare_andre_roller": "ingen", "umerket": "lav",
                  "ingen": "ingen"}


def _post(metode, konfidens, begrunnelse=None, side=None) -> dict:
    """Én oppføring. Feltene er alltid til stede, tomt er `null` — samme
    regel som resten av profilen."""
    return {"metode": metode, "konfidens": konfidens,
            "begrunnelse": begrunnelse or None, "side": side}


def bygg_opphav(profil: dict, nivaa: str = "viktige") -> dict:
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

    kart = {}
    part = profil.get("part") or profil.get("eier") or {}
    dokument = profil.get("dokument") or {}

    # --- parten (R69) -------------------------------------------------
    grunnlag = part.get("grunnlag")
    kart["/dokumentprofil/part/fnr"] = _post(
        _PARTMETODE.get(grunnlag, "ingen"),
        _PARTKONFIDENS.get(part.get("sikkerhet"), "ingen"),
        part.get("begrunnelse"))

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
    if part.get("fodselsdato"):
        kart["/dokumentprofil/part/fodselsdato"] = _post(
            "avledet", _PARTKONFIDENS.get(part.get("sikkerhet"), "ingen"),
            "Regnet ut av fødselsnummerets seks første siffer — står ikke "
            "nødvendigvis skrevet i dokumentet")

    # --- hjemmelen følger dokumentDATOEN (R77) -------------------------
    hjemmel = profil.get("hjemmel") or {}
    if hjemmel.get("lov"):
        # Arver datoens konfidens: er datoen usikker, er lovvalget det
        # også — det er den datoen valget hviler på.
        kart["/dokumentprofil/hjemmel/lov"] = _post(
            "avledet", dokument.get("dato_sikkerhet") or "ingen",
            hjemmel.get("begrunnelse"))

    # --- identifikatorer med sjekksum ----------------------------------
    # mod11/mod10 er matematisk bevis, ikke et mønstertreff: konfidensen
    # er «hoy» uten forbehold.
    okonomi = profil.get("okonomi") or {}
    for i, _ in enumerate(okonomi.get("kontonummer") or []):
        kart[f"/dokumentprofil/okonomi/kontonummer/{i}"] = _post(
            "sjekksum", "hoy", "Elleve siffer som består mod11")
    for i, _ in enumerate(okonomi.get("kid") or []):
        kart[f"/dokumentprofil/okonomi/kid/{i}"] = _post(
            "sjekksum", "hoy", "KID-nummer som består mod10/mod11")
    arbeid = profil.get("arbeid") or {}
    for i, _ in enumerate(arbeid.get("organisasjonsnummer") or []):
        kart[f"/dokumentprofil/arbeid/organisasjonsnummer/{i}"] = _post(
            "sjekksum", "hoy", "Ni siffer som består mod11")

    # --- etikettbundne felter (R71) ------------------------------------
    # De hentes BARE når ordet står i dokumentet, så metoden er alltid
    # «etikett» når verdien finnes.
    for seksjon, felt in (("sak", "saksnummer"), ("sak", "journalnummer"),
                          ("sak", "vedtaksnummer"), ("sak", "dokumentnummer"),
                          ("okonomi", "dagsats"), ("okonomi", "manedsbelop"),
                          ("okonomi", "utbetalt_belop"),
                          ("arbeid", "arbeidsgiver"), ("arbeid", "stilling"),
                          ("arbeid", "stillingsprosent")):
        if (profil.get(seksjon) or {}).get(felt) is not None:
            kart[f"/dokumentprofil/{seksjon}/{felt}"] = _post(
                "etikett", "hoy",
                "Hentet fordi etiketten står i dokumentet (R71)")

    # --- koder lest av dekoderen ---------------------------------------
    koder = profil.get("koder") or {}
    for navn in ("qr", "strekkode"):
        for i, _ in enumerate(koder.get(navn) or []):
            kart[f"/dokumentprofil/koder/{navn}/{i}"] = _post(
                "strekkode", "hoy", "Dekodet av pyzbar, ikke lest som tekst")

    # --- ytelse og dokumenttype: mønsterregler --------------------------
    if (profil.get("ytelse") or {}).get("navn"):
        kart["/dokumentprofil/ytelse/navn"] = _post(
            "regel", "middels", "Kjent ytelsesnavn funnet i teksten")
    if dokument.get("type"):
        kart["/dokumentprofil/dokument/type"] = _post(
            "regel", "middels", "Klassifisert av tittel- og ordmønstre")

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

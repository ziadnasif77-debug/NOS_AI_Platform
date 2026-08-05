"""Klientidentitet — navngitte API-nøkler.

Revisjonen kalte dette forutsetningen for hele fase 4: «Uten klient-
identitet kan ingen felter noensinne fjernes.» Med ÉN delt nøkkel er
hver forespørsel anonym, og spørsmålet «bruker noen fortsatt dette?»
har ikke noe svar — så et utgått felt må stå for alltid, for sikkerhets
skyld.

Med navngitte nøkler blir spørsmålet besvarbart: tilgangsloggen får en
`klient_id`, og før noe fjernes kan man se hvem som faktisk kalte hva.

HVA DETTE SVARER PÅ, OG HVA DET IKKE GJØR
    Loggen ser FORESPØRSELEN: hvem kalte, hvilket endepunkt, hvilke
    brytere. Den ser ikke hvilke felter klienten LESER i svaret. At
    ingen sender `struktur=ja` er et bevis; at ingen bruker `eier` i
    stedet for `part` kan loggen ikke vise, for begge står i samme svar.
    Utgåtte SVARfelter må derfor fortsatt varsles i `varsler[]` og
    fjernes etter et annonsert løp — ikke fordi loggen sier de er
    ubrukte, for det kan den ikke.

SIKKERHET
    Sammenligningen går over ALLE nøklene uten tidlig utgang og med
    `compare_digest`. Stopper man ved første treff, røper svartiden både
    hvilken nøkkel som traff og omtrent hvor i lista den lå.

    Nøkkelen logges ALDRI — bare navnet. Et navn i en logg er nyttig; en
    nøkkel i en logg er en lekkasje som overlever i sikkerhetskopier.
"""
import hmac

# Navnet forespørsler får når serveren kjører uten nøkkel. Da er alle
# anonyme, og loggen skal si det rett ut i stedet for å la feltet stå
# tomt — «ukjent» og «ikke påkrevd» er ikke det samme.
AAPEN = "aapen"

# Navnet den ENE gamle nøkkelen (API_NOKKEL) beholder. Den fortsetter å
# virke uendret; uten den ville hver eksisterende integrasjon brekt i det
# øyeblikket navngitte nøkler ble skrudd på.
ELDRE = "eldre-nokkel"

# Kortere enn dette er ikke en nøkkel, det er et passord. Vi avviser den
# ikke — en kjørende server skal ikke stoppe fordi noen valgte dårlig —
# men oppstarten sier fra.
MINSTE_LENGDE = 24


def les_nokler(raa: str) -> dict:
    """Tolker `API_NOKLER` — «navn:nøkkel,navn:nøkkel» — til {navn: nøkkel}.

    Navnet er klientens ID i loggen, så det skal si hvem det er:
    «uipath-fakturamottak», ikke «nokkel1». Kolon skiller; alt etter
    FØRSTE kolon er nøkkelen, så en nøkkel kan selv inneholde kolon.
    """
    nokler = {}
    for bit in (raa or "").split(","):
        bit = bit.strip()
        if not bit or ":" not in bit:
            continue
        navn, nokkel = bit.split(":", 1)
        navn, nokkel = navn.strip(), nokkel.strip()
        if navn and nokkel:
            nokler[navn] = nokkel
    return nokler


def svake_nokler(nokler: dict) -> list:
    """Navnene på nøkler som er for korte til å være noe forsvar."""
    return sorted(navn for navn, n in (nokler or {}).items()
                  if len(n) < MINSTE_LENGDE)


def gjenbrukte_nokler(nokler: dict) -> list:
    """Navn som DELER nøkkelverdi.

    To klienter med samme nøkkel er én klient med to navn — og da lyver
    `klient_id` i loggen, som er det eneste feltet dette bygger på."""
    sett = {}
    for navn, nokkel in (nokler or {}).items():
        sett.setdefault(nokkel, []).append(navn)
    return sorted(sorted(navn) for navn in sett.values() if len(navn) > 1)


def finn_klient(gitt: str, nokler: dict, eldre_nokkel: str = "") -> str:
    """Navnet på klienten som eier `gitt`, eller None.

    Går gjennom ALLE nøklene uten tidlig utgang: svartiden skal ikke
    røpe hvilken nøkkel som traff, eller hvor langt ut i lista den lå.
    """
    gitt = gitt or ""
    treff = None
    if eldre_nokkel and hmac.compare_digest(gitt, eldre_nokkel):
        treff = ELDRE
    for navn, nokkel in sorted((nokler or {}).items()):
        if hmac.compare_digest(gitt, nokkel):
            # ingen `break` — se doc-strengen
            treff = treff or navn
    return treff

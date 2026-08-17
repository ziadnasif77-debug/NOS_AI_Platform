"""
Svarer vi om RIKTIG person? — en kodegaranti, ikke en prompt (R213).

Målt på den syntetiske bunken, der Marit står på side 9 og Ola på 1–6:

    «Hva er e-postadressen til Marit Testperson?»
        → ola.testperson@eksempel.no      (Olas, fra side 4)
    «Hvilken diagnose har Marit Testperson?»
        → L86 Ryggsmerter                 (Olas)
    «Hvem er arbeidsgiveren til Marit Testperson?»
        → Nordbygg Entreprenoer AS        (Olas)

Ingen av dem er hallusinasjon. Verdiene STÅR i dokumentet — de tilhører
bare en annen person. Og i det første tilfellet svarte ikke modellen i
det hele tatt: den deterministiske felteruttrekkeren fant bunkens ENESTE
e-post og leverte den.

DET ER DERFOR DETTE ER KODE OG IKKE EN PROMPT
CLAUDE.md §4: «prompten styrer, koden garanterer». En instruks om å
passe på hvem det spørres om, ville ikke hjulpet feltuttrekkeren i det
hele tatt — den leser ikke prompter. Og for en saksbehandler er Olas
diagnose merket med Marits navn verre enn «ikke oppgitt»: det første er
en feil ingen oppdager, det andre er et spørsmål man stiller på nytt.

HVA GARANTIEN ER — OG HVOR SMAL DEN ER
Slår bare til når ALLE fire holder:

  1. spørsmålet nevner ETT navn som dokumentet faktisk inneholder
     (nevner det to, vet vi ikke hvem svaret gjaldt — da holder vi oss unna)
  2. dokumentet har flere sider, og navnet står på noen av dem
  3. svaret inneholder minst én konkret VERDI (tall, e-post, beløp)
  4. INGEN av verdiene står på en eneste side som nevner personen

Da — og bare da — byttes svaret mot «Ikke oppgitt».

Er verdien på personens side, skjer ingenting. «Hva er Olas diagnose?»
er derfor helt urørt, og det er hele poenget: garantien skal ikke koste
et eneste riktig svar.

DEN LØSER IKKE ROTPROBLEMET
Rotproblemet er at en bunke med to personer gir ÉN flat feltmengde:
ett fødselsnummer, én e-post, ett beløp. Det er dokumentdelingen som må
rettes, og den venter på ekte dokumenter. Dette er en sikkerhetsgaranti
i mellomtiden — den hindrer det farlige svaret, den lager ikke det
riktige.
"""
import re

# Ord som ser ut som navn i en norsk setning fordi de står med stor
# forbokstav først i spørsmålet, men ikke er det.
IKKE_NAVN = {
    "hva", "hvem", "hvilken", "hvilke", "hvilket", "hvor", "hvorfor",
    "når", "naar", "er", "har", "kan", "skal", "ble", "blir", "står",
    "staar", "finnes", "gjelder", "den", "det", "de", "denne", "dette",
    "disse", "en", "et", "og", "eller", "som", "til", "for", "fra",
    "med", "om", "på", "paa", "i", "av", "ved", "mye", "mange", "stort",
    "nav", "dokumentet", "vedtaket", "fakturaen", "brevet", "saken",
}

# En verdi er noe man kan ta feil av: et tall, et beløp, en e-post, en
# dato. Fri tekst er ikke en verdi — et sammendrag «tilhører» ingen
# enkeltside, og en garanti som slår til på sammendrag ville tatt
# riktige svar med seg.
_VERDI = re.compile(
    r"[\w.\-]+@[\w.\-]+"                       # e-post
    r"|\d{1,3}(?:[ .]\d{3})+(?:,\d+)?"         # 512 400 / 4 812,00
    r"|\d{4,}"                                 # fødselsnummer, saksnr, kid
    r"|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}")       # dato


def _navnefraser(tekst: str) -> list:
    """«Marit Testperson» er ETT navn, ikke to.

    Ord med stor forbokstav som står inntil hverandre, hører sammen.
    Uten det ville et fullt navn telt som to personer, og garantien —
    som krever nøyaktig ett navn — ville aldri slått til på nettopp de
    spørsmålene den ble laget for."""
    fraser, naa = [], []
    for ord_ in re.findall(r"[A-ZÆØÅa-zæøå\-]+|[^A-ZÆØÅa-zæøå\-]+", tekst):
        stor = (ord_[:1].isupper() and len(ord_) > 2
                and ord_.lower() not in IKKE_NAVN)
        if stor:
            naa.append(ord_)
        elif ord_.strip() and not ord_.isspace():
            if naa:
                fraser.append(" ".join(naa))
            naa = []
        elif ord_ != " ":
            if naa:
                fraser.append(" ".join(naa))
            naa = []
    if naa:
        fraser.append(" ".join(naa))
    return fraser


def navn_i_sporsmal(sporsmal: str, sider: dict) -> list:
    """Navn spørsmålet nevner OG dokumentet inneholder.

    Begge deler kreves. Et navn som bare står i spørsmålet, kan vi ikke
    si noe om — kanskje er personen ikke i dokumentet i det hele tatt,
    og da er «ikke oppgitt» allerede riktig svar uten vår hjelp.

    Står ikke hele frasen i dokumentet, prøves FØRSTE ledd: spørsmålet
    kan si «Marit Testperson» der dokumentet bare skriver «Marit»."""
    # SMÅ BOKSTAVER PÅ BEGGE SIDER. Adressefeltet i et NAV-brev står i
    # blokkbokstaver — «OLA NORDMANN» på side 1 — mens spørsmålet
    # skriver «Ola Nordmann». Med et versalfølsomt søk fant garantien
    # bare side 6, trodde side 1 tilhørte en annen, og slo til på et
    # helt riktig svar.
    alt = "\n".join(sider.values()).lower()
    ut = []
    for frase in dict.fromkeys(_navnefraser(sporsmal)):
        if frase.lower() in alt:
            ut.append(frase)
        else:
            forste = frase.split()[0]
            if len(forste) > 2 and forste.lower() in alt:
                ut.append(forste)
    return list(dict.fromkeys(ut))


def sider_for_navn(navn: str, sider: dict) -> set:
    """Versaluavhengig — se begrunnelsen i `navn_i_sporsmal`."""
    lav = navn.lower()
    return {nr for nr, tekst in sider.items() if lav in tekst.lower()}


# Et KORT svar er også en verdi, når det står ordrett i dokumentet.
# Grensen skiller et oppslag fra et sammendrag: «Nordbygg Entreprenoer
# AS» er hentet fra én bestemt side, mens en oppsummering av bunken
# ikke tilhører noen side og aldri skal dømmes av denne garantien.
KORT_SVAR_TEGN = 60

# Nedre grense. Et for kort svar er ikke en verdi man kan spore til en
# side: «Ja» og «Nei» står overalt eller ingen steder, og å dømme dem
# ville byttet ut riktige svar med «Ikke oppgitt».
MINSTE_ORDRETT_TEGN = 8

# Svar som allerede sier at noe ikke står der. Da er det ingenting å
# bytte ut, og å lete etter dem ordrett i dokumentet ville vært meningsløst.
_ALLEREDE_AVKREFTET = ("ikke oppgitt", "finnes ikke", "står ikke",
                       "staar ikke", "vet ikke", "ingen ")


def _verdier(svar: str) -> list:
    return [v for v in _VERDI.findall(svar or "") if len(v) >= 4]


def _ordrett_verdi(svar: str) -> str:
    """Svaret som ÉN verdi, når det er kort nok til å være et oppslag.

    HVORFOR DETTE MÅTTE UTVIDES
    Garantien regnet bare tall, e-post og datoer som verdier. Den fanget
    derfor Marits fødselsnummer og kontonummer — og slapp gjennom:

        «Hvilken diagnose har Marit Testperson?»
            → L86 Ryggsmerter med utstråling   (Olas, fra side 5)
        «Hvem er arbeidsgiveren til Marit Testperson?»
            → Nordbygg Entreprenoer AS         (Olas, fra side 6)

    Begge er nøyaktig samme feil som fødselsnummeret: en ekte verdi fra
    feil persons side. At den ene er skrevet med tall og den andre med
    bokstaver, er uten betydning for saksbehandleren som stoler på den.

    Begrunnelsen for å holde fri tekst utenfor står fortsatt — men den
    gjaldt SAMMENDRAG, ikke korte oppslag. Skillet er om svaret lar seg
    finne igjen ORDRETT på en side: kan det ikke det, tilhører det ingen
    enkeltside, og garantien holder seg unna."""
    t = " ".join((svar or "").split())
    if len(t) > KORT_SVAR_TEGN or len(_uten_luft(t)) < MINSTE_ORDRETT_TEGN:
        return ""
    lav = t.lower()
    if any(f in lav for f in _ALLEREDE_AVKREFTET):
        return ""
    return t


def _uten_luft(tekst: str) -> str:
    """Teksten uten mellomrom og linjeskift, i små bokstaver.

    HÅNDSKRIFTFELTER KOMMER I BITER. Diagnosen på side 5 i bunken ligger
    i tekstlaget som «L», «8», «6 R», «y», … — ett tegn om gangen, slik
    utfylte felter gjør både i denne PDF-en og i ekte OCR. Modellen
    setter dem sammen og svarer «L86 Ryggsmerter med utstråling», men et
    ordrett søk finner den strengen ingen steder.

    Sammenligner vi uten luft, finner vi den — og garantien virker på
    nettopp de feltene som oftest er feilkilden."""
    return "".join((tekst or "").split()).lower()


def doem(sporsmal: str, svar: str, sider: dict) -> dict:
    """→ {gjelder, navn, personsider, verdier, funnet_paa}.

    `gjelder=True` betyr: svaret bygger på verdier som IKKE står på en
    eneste av personens sider. Kalleren bestemmer hva som skjer da —
    modulen tar ingen beslutning på egen hånd, den svarer på et
    spørsmål."""
    ut = {"gjelder": False, "navn": None, "personsider": [],
          "verdier": [], "funnet_paa": []}
    if not sider or len(sider) < 2:
        return ut                       # ett dokument — ingen forveksling
    navn = navn_i_sporsmal(sporsmal, sider)
    if len(navn) != 1:
        # Null navn: spørsmålet gjelder dokumentet, ikke en person.
        # To eller flere: vi vet ikke hvem svaret gjaldt, og en gjetning
        # her ville vært nøyaktig den feilen vi prøver å hindre.
        return ut
    ut["navn"] = navn[0]
    personsider = sider_for_navn(navn[0], sider)
    ut["personsider"] = sorted(personsider)
    if not personsider:
        return ut
    verdier = _verdier(svar)
    ordrett = ""
    if not verdier:
        # Ingen tall i svaret. Er det likevel kort nok til å være et
        # oppslag, prøves hele svaret ordrett — se `_ordrett_verdi`.
        ordrett = _ordrett_verdi(svar)
        if ordrett:
            verdier = [ordrett]
    ut["verdier"] = verdier
    if not verdier:
        return ut                       # sammendrag — ingen verdi å ta feil av
    funnet = set()
    naken = _uten_luft(ordrett) if ordrett else ""
    for verdi in verdier:
        for nr, tekst in sider.items():
            if verdi in tekst:
                funnet.add(nr)
            elif naken and verdi is ordrett and naken in _uten_luft(tekst):
                funnet.add(nr)
    ut["funnet_paa"] = sorted(funnet)
    if not funnet:
        return ut                       # verdien står ingen steder — en
                                        # annen vakt (tallvakten) sitt bord
    ut["gjelder"] = not (funnet & personsider)
    return ut

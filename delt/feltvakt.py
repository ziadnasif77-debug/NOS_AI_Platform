"""
Er verdien i svaret svar på det spørsmålet FAKTISK spurte om? (R232)

Tre korpusspørsmål feilet på samme måte, og ingen av dem ved å dikte:

    «Hvor stort gebyr er lagt paa fakturaen?»  → kr 4 812,00
    «Hvor mye skylder parten i renter?»        → kr 4 812,00
    «Hva er pensjonsgrunnlaget til Ola?»       → kr 512 400

Alle tre tallene STÅR i dokumentet. 4 812,00 er beløpet som skal
betales, 512 400 er sykepengegrunnlaget. Ingen av dem er et gebyr,
renter eller et pensjonsgrunnlag — de finnes ikke i bunken.

For en saksbehandler er dette den farligste feilklassen som finnes:
tallet er ekte, det står i dokumentet, og ingenting i svaret røper at
det hører til et annet felt. `ikke_oppdiktet_belop` ligger i korpuset
nettopp som en kontroll mot dette.

TO VILKÅR, OG BEGGE MÅ HOLDE

  1. Verdien bærer ingen etikett spørsmålet nevner. Et beløp i et
     NAV-dokument står nesten alltid ved siden av hva det ER —
     «Beloep aa betale», «Sykepengegrunnlaget er fastsatt til»,
     «Refusjonskrav fra:». Deler nabolaget rundt verdien ikke ett
     eneste ord med spørsmålet, hører verdien til et annet felt.

  2. Spørsmålet navngir noe dokumentet ALDRI nevner. «gebyr» og
     «pensjonsgrunnlaget» finnes ikke i bunken i det hele tatt.

Hvert vilkår ALENE tar riktige svar med seg. Målt på korpuset: vilkår 1
alene flagget «Hvor mye hadde parten i frilansinntekt?», fordi beløpet
står under «Frilansoppdrag» og de to ordene bare deler forstavelse.
Sammen flagget de null riktige svar.

ORDSAMMENLIGNINGEN ER MED VILJE ROMSLIG
Her skal vi AVVISE, og til det trengs fravær av enhver forbindelse —
ikke et presist treff. «postnummer» og «Postboks» deler fire tegn, og
det er nok til å la svaret stå. Bevisvalgets terskel på 70 % (R224) er
riktig når man skal VELGE mellom sider, og gal her: den ville gjort
«frilansinntekt» og «Frilansoppdrag» til fremmede.

HVORFOR IKKE EN PROMPT (§4)
En instruks om å svare på riktig felt ble målt og forkastet (R225):
den rettet ett spørsmål og ødela fire — deriblant nettopp kontrollen
mot oppdiktede beløp. Instruksen får modellen til å binde seg til en
verdi i stedet for å nekte, og den effekten skiller ikke mellom når en
verdi finnes og når den ikke gjør det. Koden skiller.
"""
import re

# MENGDER: beloep og datoer. Det er der «feil felt» baade er vanlig og
# farlig — et beloep uten etikett ser like riktig ut som et med.
#
# BARE SIFRE HOLDER IKKE, og det er maalt. Foerste versjon regnet ogsaa
# ethvert firesifret tall som en verdi. Da fanget vakten «Hvilken
# gateadresse har mottakeren?»: modellen svarte «Storgata 14 B, 3044
# DRAMMEN», POSTNUMMERET ble verdien, og «gateadresse» finnes ikke i
# bunken som ord — saa begge vilkaar holdt, og et riktig svar ble byttet
# mot «Ikke oppgitt». Et postnummer i en adresseblokk er ikke en
# stoerrelse noen ber om ved navn.
#
# Identifikatorer (foedselsnummer, kontonummer, KID) er utenfor med
# vilje: de er sjekksumvaliderte og svares deterministisk lenge foer
# modellen ser dem, og personbindingen (R213) vokter hvem de tilhoerer.
VERDI = re.compile(
    r"\d{1,3}(?:[ . ]\d{3})+(?:,\d+)?"        # 4 812,00 / 512 400
    r"|\d{1,2}[./]\d{1,2}[./]\d{2,4}"              # 24.06.2026
    r"|\d+,\d{2}"                                # 812,00
    r"|\d{4}-\d{2}-\d{2}")                         # 2026-06-24

# Hvor mange linjer over verdien som regnes som etiketten dens. Én er
# nok, og målt: «Beloep aa betale» står på linja over «kr 4 812,00»,
# mens «Refusjonskrav fra:» står på samme linje som datoen.
NABOLINJER = 1

# Korteste felles forstavelse for at to ord skal regnes som beslektet.
# Fire, ikke fem — se modulens innledning.
FELLES = 4

# Kortere spørsmålsord bærer for lite til at fraværet betyr noe.
MINSTE_FRAVAERENDE = 5

_ALLEREDE_AVKREFTET = ("ikke oppgitt", "finnes ikke", "står ikke",
                       "staar ikke", "vet ikke", "ingen ")


def _flat(tekst: str) -> str:
    """Mellomrom MELLOM sifre bort — «4 812,00» og «4812,00» er ett tall."""
    return re.sub(r"(?<=\d)[ . ](?=\d)", "", tekst or "")


def _beslektet(a: str, b: str) -> bool:
    from delt.bevisvalg import _norsk

    a, b = _norsk(a.lower()), _norsk(b.lower())
    if a == b or a.startswith(b) or b.startswith(a):
        return True
    delt = 0
    for x, y in zip(a, b):
        if x != y:
            break
        delt += 1
    return delt >= FELLES


def _ord(tekst: str) -> list:
    from delt.bevisvalg import _ORD

    return [o.lower() for o in _ORD.findall(tekst or "")]


def _sporsmalsord(sporsmal: str) -> list:
    from delt.bevisvalg import _STOPPORD

    return [o for o in _ord(sporsmal) if o not in _STOPPORD]


def verdier_i(svar: str) -> list:
    return [v.strip() for v in VERDI.findall(svar or "") if len(v.strip()) >= 4]


def uten_etikett(sporsmal: str, verdi: str, linjer: list) -> bool:
    """Står verdien noe sted der spørsmålet har et ord i nærheten?

    Returnerer False også når verdien ikke står i dokumentet i det hele
    tatt — da er det tallvaktens bord (R147), ikke vår."""
    spm = _sporsmalsord(sporsmal)
    if not spm:
        return False
    monster = re.compile(r"(?<!\d)" + re.escape(_flat(verdi)) + r"(?!\d)")
    sett = False
    for nr, linje in enumerate(linjer):
        if not monster.search(_flat(linje)):
            continue
        sett = True
        start = max(0, nr - NABOLINJER)
        for naboord in _ord(" ".join(linjer[start:nr + 1])):
            if any(_beslektet(s, naboord) for s in spm):
                return False
    return sett


def fravaerende_ord(sporsmal: str, alle_ord: set) -> list:
    """Ordene i spørsmålet som dokumentet aldri nevner."""
    return [s for s in _sporsmalsord(sporsmal)
            if len(s) >= MINSTE_FRAVAERENDE
            and not any(_beslektet(s, o) for o in alle_ord)]


def doem(sporsmal: str, svar: str, tekst: str) -> dict:
    """→ {gjelder, verdier, fravaerende}.

    `gjelder=True` betyr: svaret hviler på en verdi som hører til et
    annet felt, og spørsmålet ber om noe dokumentet ikke har. Kalleren
    bestemmer hva som skjer da — modulen tar ingen beslutning på egen
    hånd, den svarer på et spørsmål."""
    ut = {"gjelder": False, "verdier": [], "fravaerende": []}
    if not (svar or "").strip() or not (tekst or "").strip():
        return ut
    if any(f in svar.lower() for f in _ALLEREDE_AVKREFTET):
        return ut                   # svaret nekter allerede
    verdier = verdier_i(svar)
    ut["verdier"] = verdier
    if not verdier:
        return ut                   # fri tekst — ikke vårt bord
    linjer = (tekst or "").splitlines()
    if not all(uten_etikett(sporsmal, v, linjer) for v in verdier):
        return ut                   # minst én verdi hører hjemme her
    ut["fravaerende"] = fravaerende_ord(sporsmal, set(_ord(tekst)))
    ut["gjelder"] = bool(ut["fravaerende"])
    return ut

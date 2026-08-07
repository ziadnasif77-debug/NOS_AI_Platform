"""Bygger gyldige norske identifikatorer PÅ KJØRETID, så ingen av dem
står som tall i kildekoden.

Hvorfor: et ellevesifret tall i en fil ser ut som et fødselsnummer,
uansett hvor syntetisk det er ment å være — og en fil på GitHub leses av
folk som ikke kjenner opprinnelsen. Her ligger bare regnestykket;
tallene finnes først når testen kjører, og forsvinner med den.

Sjekksummene regnes ut HER, uavhengig av koden som testes. Ellers ville
en feil i implementasjonen kunne bekrefte seg selv gjennom testdataene.
"""

# mod11-vektene for fødselsnummer (kontrollsiffer 1 og 2)
_VEKT_FNR_1 = (3, 7, 6, 1, 8, 9, 4, 5, 2)
_VEKT_FNR_2 = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
# mod11-vekten for kontonummer (ett kontrollsiffer over de ti første)
_VEKT_KONTO = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def _kontrollsiffer(sifre: str, vekter) -> int | None:
    """Kontrollsifferet, eller None når mod11 gir 10 (da finnes det
    ikke et gyldig siffer, og kandidaten må forkastes)."""
    rest = sum(int(s) * v for s, v in zip(sifre, vekter)) % 11
    siffer = 11 - rest
    if siffer == 11:
        return 0
    return None if siffer == 10 else siffer


def _fnr_fra(ni_sifre: str) -> str | None:
    k1 = _kontrollsiffer(ni_sifre, _VEKT_FNR_1)
    if k1 is None:
        return None
    k2 = _kontrollsiffer(ni_sifre + str(k1), _VEKT_FNR_2)
    return None if k2 is None else f"{ni_sifre}{k1}{k2}"


def lag_fnr(nummer: int = 0) -> str:
    """Et gyldig fødselsnummer. `nummer` velger blant flere ULIKE — en
    bunke kan gjelde to personer, og da må testen kunne skille dem."""
    funnet = []
    for individ in range(100, 1000):
        fnr = _fnr_fra(f"010190{individ:03d}")
        if fnr:
            funnet.append(fnr)
            if len(funnet) > nummer:
                return funnet[nummer]
    raise AssertionError(f"fant ikke gyldig test-fnr nr. {nummer}")


def lag_fnr_fodt(dag: int, maaned: int, aar: int, nummer: int = 0,
                 intervall: str = "lav") -> str:
    """Et gyldig fødselsnummer med en BESTEMT fødselsdato.

    `lag_fnr` hardkoder 01.01.1990, så alle numrene derfra har SAMME
    fødselsdato. Det holder til å skille to personer, men ikke til å
    vise hvem en avledet fødselsdato tilhører — da ser riktig og galt
    svar likt ut, og testen beviser ingenting (R139).

    Århundret velges av INDIVIDSIFRENE, ikke av årstallet. Regelen
    speiles her — ikke importeres fra koden som testes — av samme grunn
    som sjekksummene regnes ut i denne fila: ellers kunne en feil i
    implementasjonen bekrefte seg selv gjennom testdataene.

    `intervall` velger HVILKET individnummerintervall som brukes når
    flere er lovlige for samme år. 1940-1999 dekkes av BÅDE 000-499 og
    900-999, og det siste ble aldri generert her — så den verste feilen
    i århundreregelen var strukturelt umulig å skrive en test for:
    generatoren kunne ikke lage nummeret som utløste den (R154)."""
    if 2000 <= aar <= 2039:
        omraade = range(500, 1000)
    elif 1940 <= aar <= 1999 and intervall == "hoy":
        omraade = range(900, 1000)      # også lovlig for disse årene
    elif 1900 <= aar <= 1999:
        omraade = range(100, 500)
    elif 1854 <= aar <= 1899:
        omraade = range(500, 750)
    else:
        raise AssertionError(
            f"året {aar} dekkes ikke av århundreregelen (1854-2039)")
    aa = aar % 100
    funnet = []
    for individ in omraade:
        fnr = _fnr_fra(f"{dag:02d}{maaned:02d}{aa:02d}{individ:03d}")
        if fnr:
            funnet.append(fnr)
            if len(funnet) > nummer:
                return funnet[nummer]
    raise AssertionError(
        f"fant ikke gyldig test-fnr født {dag:02d}.{maaned:02d}.{aar}")


def lag_kontonummer(nummer: int = 0) -> str:
    """Et gyldig kontonummer (11 siffer, mod11 på siste siffer) som IKKE
    også består fødselsnummerkontrollen — ellers ville testen ikke kunne
    skille de to typene fra hverandre."""
    funnet = []
    for teller in range(1000):
        # ti sifre, bygd av en kort basis — heller ikke tallene i denne
        # fila skal ha elleve siffer
        ti = f"2000000{teller:03d}"
        k = _kontrollsiffer(ti, _VEKT_KONTO)
        if k is None:
            continue
        konto = ti + str(k)
        if _fnr_fra(konto[:9]) == konto:      # dobbeltgyldig — hopp over
            continue
        funnet.append(konto)
        if len(funnet) > nummer:
            return funnet[nummer]
    raise AssertionError(f"fant ikke gyldig test-kontonummer nr. {nummer}")


def lag_dobbeltgyldig() -> str:
    """Et tall som består BEGGE kontrollene — gyldig både som
    kontonummer og som fødselsnummer (D-nummer).

    Slike finnes i virkeligheten, og de er grunnen til at etiketten
    foran tallet må avgjøre hva det ER: en refusjonskonto ble ellers
    rapportert som fødselsnummer og manglet helt i kontonummerlista."""
    for individ in range(100, 1000):
        fnr = _fnr_fra(f"601110{individ:03d}")
        if not fnr:
            continue
        if _kontrollsiffer(fnr[:10], _VEKT_KONTO) == int(fnr[10]):
            return fnr
    raise AssertionError("fant ikke et dobbeltgyldig testnummer")

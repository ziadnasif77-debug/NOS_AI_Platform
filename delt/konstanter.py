# Statuser brukt av alle tjenester
KJORER = "kjorer"
FERDIG = "ferdig"
FEIL = "feil"
VENTER = "venter"

# Dokumenttyper
HANDSKRIFT = "handskrift"
TRYKT = "trykt"
TABELL = "tabell"
BLANDET = "blandet"

# Konfidens-terskel
STANDARD_TERSKEL = 0.85

# Mappenavn
INNTAK = "inntak"
BEHANDLET = "behandlet"
RAA = "raw"
RENSET = "renset"
GJENNOMGANG = "gjennomgang"
FINJUSTERING = "finjustering"

# V2.1 — State machine og køer
DLQ_KOOER = {
    "preprocess": "dlq:preprocess",
    "ocr":        "dlq:ocr",
    "nlp":        "dlq:nlp",
    "validation": "dlq:validation",
}

REDIS_KOOER = {
    "preprocess": "queue:preprocess",
    "ocr":        "queue:ocr",
    "nlp":        "queue:nlp",
    "validation": "queue:validation",
    "routing":    "queue:routing",
}

STATE_OVERGANGER = {
    "UPLOADED":       "QUEUED",
    "QUEUED":         "PREPROCESSING",
    "PREPROCESSING":  "OCR_PROCESSING",
    "OCR_PROCESSING": "NLP_PROCESSING",
    "NLP_PROCESSING": "VALIDATION",
    "VALIDATION":     "ROUTING",
    "ROUTING":        "DONE",
}

LOVLIGE_OVERGANGER = set(STATE_OVERGANGER.items()) | {
    ("PREPROCESSING",  "FAILED"),
    ("OCR_PROCESSING", "FAILED"),
    ("NLP_PROCESSING", "FAILED"),
    ("VALIDATION",     "FAILED"),
    ("ROUTING",        "FAILED"),
    # Self-transitions: worker re-claimer jobb som allerede er i running_state
    ("PREPROCESSING",  "PREPROCESSING"),
    ("OCR_PROCESSING", "OCR_PROCESSING"),
    ("NLP_PROCESSING", "NLP_PROCESSING"),
    ("ROUTING",        "ROUTING"),
    # NLP gjør validering inline → hopper over VALIDATION-state
    ("NLP_PROCESSING", "ROUTING"),
}

TERMINAL_TILSTANDER = {"DONE", "FAILED"}

# ─── Kanoniske domenelister (én kilde — brukes av NLP, søk og uttrekk) ──────

NORSKE_FYLKER = {
    "Oslo", "Viken", "Innlandet", "Vestfold og Telemark",
    "Agder", "Rogaland", "Vestland", "Møre og Romsdal",
    "Trøndelag", "Nordland", "Troms og Finnmark",
    "Troms", "Finnmark",
}

# Ytelsene folketrygdloven gir. Skrives HER uten æøå med vilje: både
# lista og dokumentteksten normaliseres før de sammenlignes (se
# finn_ytelse), slik at «uføretrygd», «uforetrygd» og «ufoeretrygd» er
# samme ord. Uten den normaliseringen fant systemet ALDRI uføretrygd,
# uførepensjon, overgangsstønad eller kontantstøtte — fire av de
# viktigste ytelsene, og de falt stille bort.
#
# Kapittelnavnene i regler/lover.md er kilden: hver ytelse her har sin
# hjemmel i et kapittel i én av de to folketrygdlovene.
NORSKE_YTELSER = {
    # 1997-loven (gjeldende)
    "dagpenger",                 # kap. 4
    "grunnstonad", "hjelpestonad",   # kap. 6
    "gravferdsstonad",           # kap. 7
    "sykepenger",                # kap. 8
    "omsorgspenger", "pleiepenger", "opplaeringspenger",   # kap. 9
    "arbeidsavklaringspenger",   # kap. 11
    "tilleggsstonad",            # kap. 11 A
    "uforetrygd",                # kap. 12
    "yrkesskadeerstatning",      # kap. 13
    "foreldrepenger", "svangerskapspenger", "engangsstonad",   # kap. 14
    "overgangsstonad",           # kap. 15
    "gjenlevendepensjon",        # kap. 17
    "barnepensjon",              # kap. 18
    "alderspensjon",             # kap. 19/20
    # 1966-loven (opphevet) — egne navn på det som i dag heter noe annet
    "uforepensjon",              # kap. 8 (i dag: uføretrygd)
    "etterlattepensjon",         # kap. 10
    "attforingspenger",          # kap. 5B (i dag: arbeidsavklaringspenger)
    "rehabiliteringspenger",     # kap. 5A (i dag: arbeidsavklaringspenger)
    # ytelser utenfor folketrygdloven, men i samme dokumentflyt
    "barnetrygd", "kontantstotte",
}

# Lesbart navn for hver ytelseskode (AAREG-mønsteret: koden er stabil og
# maskinlesbar, termen er for et menneske). Kodene er skrevet UTEN æøå
# fordi de sammenlignes mot OCR-tekst som kan skrive «uforetrygd»,
# «uføretrygd» eller «ufoeretrygd» — men et grensesnitt skal vise den
# norske formen, ikke koden.
#
# Hver kode i NORSKE_YTELSER SKAL ha en term her; en vakttest feiler
# ellers. Uten den ville en ny ytelse stille falt tilbake til koden, og
# en bruker fått «opplaeringspenger» i skjermbildet.
YTELSE_TERM = {
    "dagpenger": "Dagpenger",
    "grunnstonad": "Grunnstønad",
    "hjelpestonad": "Hjelpestønad",
    "gravferdsstonad": "Gravferdsstønad",
    "sykepenger": "Sykepenger",
    "omsorgspenger": "Omsorgspenger",
    "pleiepenger": "Pleiepenger",
    "opplaeringspenger": "Opplæringspenger",
    "arbeidsavklaringspenger": "Arbeidsavklaringspenger",
    "tilleggsstonad": "Tilleggsstønad",
    "uforetrygd": "Uføretrygd",
    "yrkesskadeerstatning": "Yrkesskadeerstatning",
    "foreldrepenger": "Foreldrepenger",
    "svangerskapspenger": "Svangerskapspenger",
    "engangsstonad": "Engangsstønad",
    "overgangsstonad": "Overgangsstønad",
    "gjenlevendepensjon": "Gjenlevendepensjon",
    "barnepensjon": "Barnepensjon",
    "alderspensjon": "Alderspensjon",
    # 1966-loven. Termen sier at ytelsen er historisk OG hva den heter i
    # dag — et vedtak fra 1994 om «uførepensjon» skal ikke leses som om
    # det gjaldt dagens uføretrygd, som har andre vilkår.
    "uforepensjon": "Uførepensjon (1966-loven; i dag uføretrygd)",
    "etterlattepensjon": "Etterlattepensjon (1966-loven)",
    "attforingspenger": "Attføringspenger (1966-loven; i dag AAP)",
    "rehabiliteringspenger": "Rehabiliteringspenger (1966-loven; i dag AAP)",
    # utenfor folketrygdloven
    "barnetrygd": "Barnetrygd",
    "kontantstotte": "Kontantstøtte",
}

# NAVs offisielle TEMAKODER (Joark/Gosys). Dette er språket andre
# NAV-systemer snakker: en robot som ruter et dokument videre trenger
# «SYK», ikke vår interne streng «sykepenger».
#
# Lista er UFULLSTENDIG — den er levert stykkevis, og flere koder
# kommer. Derfor er «ingen kode ennå» en normal, dokumentert tilstand
# her, ikke en feil: da står `kode: null` med `term` fylt (R127).
#
# Merk at NAV blander tre ting i samme kodeverk: ytelser (SYK, DAG),
# prosess/hendelse (MOT Skanning, KTR Kontroll) og rent administrative
# temaer (GEN Generell, OVR Øvrig). Bare de vi faktisk kan kjenne igjen
# fra en ytelse i teksten er kartlagt i YTELSE_TEMA nedenfor; resten
# ligger her for at en term skal finnes den dagen koden kommer inn en
# annen vei.
NAV_TEMA = {
    "AAR": "Aa-registeret",
    "AGR": "Ajourhold - grunnopplysninger",
    "AKT": "Aktivitetsplan med dialoger",
    "ARP": "Arbeidsrådgivning - psykologtester",
    "ARS": "Arbeidsrådgivning - skjermet",
    "BAR": "Barnetrygd",
    "BID": "Bidrag",
    "BII": "Bidrag innkreving",
    "BIL": "Bil",
    "DAG": "Dagpenger",
    "ENF": "Enslig mor eller far",
    "ERS": "Erstatning",
    "EYB": "Barnepensjon",
    "EYO": "Omstillingsstønad",
    "FEI": "Feilutbetaling",
    "FIP": "Fiskerpensjon",
    "FOR": "Foreldre- og svangerskapspenger",
    "FOS": "Forsikring",
    "FRI": "Kompensasjon selvstendig næringsdrivende/frilansere",
    "FUL": "Fullmakt",
    "GEN": "Generell",
    "GRA": "Gravferdsstønad",
    "GRU": "Grunn- og hjelpestønad",
    "HEL": "Helsetjenester og ort. hjelpemidler",
    "HJE": "Hjelpemidler",
    "IAR": "Inkluderende Arbeidsliv",
    "IND": "Tiltakspenger",
    "KLL": "Klage - lønnsgaranti",
    "KNA": "Kontakt NAV",
    "KOM": "Kommunale tjenester",
    "KON": "Kontantstøtte",
    "KTA": "Kontroll - anmeldelse",
    "KTR": "Kontroll",
    "LGA": "Lønnsgaranti",
    "MED": "Medlemskap",
    "MOB": "Mobilitetsfremmende stønad",
    "MOT": "Skanning",
    "OKO": "Økonomi",
    "OLJ": "Oljepionerene",
    "OMS": "Omsorgspenger, pleiepenger og opplæringspenger",
    "OPA": "Oppfølging - arbeidsgiver",
    "OPP": "Oppfølging",
    "OVR": "Øvrig",
    "PAI": "Innsyn",
    "PEN": "Pensjon",
    "PER": "Permittering og masseoppsigelser",
    "POI": "Innsyn etter personopplysningsloven",
    "REH": "Rehabiliteringspenger",
    "REK": "Rekruttering",
    "RPO": "Retting av personopplysninger",
    "RVE": "Rettferdsvederlag",
    "SAA": "Sanksjon - Arbeidsgiver",
    "SAK": "Sakskostnader",
    "SAP": "Sanksjon - person",
    "SER": "Serviceklager",
    "SIK": "Sikkerhetstiltak",
    "SUP": "Supplerende stønad",
    "SYK": "Sykepenger",
    "SYM": "Sykemeldinger",
    "TIL": "Tiltak",
    "TRY": "Trygdeavgift",
    "TSO": "Tilleggsstønad",
    "TSR": "Tilleggsstønad - arbeidssøkere",
    "UFM": "Unntak fra medlemskap",
    "UFO": "Uføretrygd",
    "UNG": "Ungdomsprogramytelsen",
    "VEN": "Ventelønn",
    "YRA": "Yrkesrettet attføring",
    "YRK": "Yrkesskade og menerstatning",
}

# Fra vårt interne ytelsesnavn til NAVs temakode.
#
# Kartet er BEVISST mange-til-én der NAV selv slår sammen: «uføretrygd»
# og «uførepensjon» er begge UFO, og de tre kapittel 9-ytelsene er alle
# OMS. Det taper ikke informasjon vi trenger — hvilken LOV som gjaldt
# avgjøres av dokumentDATOEN (R77), ikke av ytelsesnavnet, så et
# 1994-vedtak om uførepensjon får fortsatt ftrl-1966 som hjemmel.
#
# `None` betyr «vi kjenner ytelsen, men har ikke fått den offisielle
# koden ennå». Det er en helt annen tilstand enn «fant ingen ytelse», og
# skillet er synlig i svaret: den første gir `{kode: null, term: fylt}`,
# den andre `{kode: null, term: null}`.
YTELSE_TEMA = {
    "dagpenger": "DAG",
    "grunnstonad": "GRU",
    "hjelpestonad": "GRU",
    "gravferdsstonad": "GRA",
    "sykepenger": "SYK",
    "omsorgspenger": "OMS",
    "pleiepenger": "OMS",
    "opplaeringspenger": "OMS",
    # Arbeidsavklaringspenger står IKKE i lista vi har fått. Ytelsen
    # finnes åpenbart (den er kapittel 11 og ligger i klagen på side 9 i
    # testbunken) — koden mangler bare her ennå.
    "arbeidsavklaringspenger": None,
    "tilleggsstonad": "TSO",
    "uforetrygd": "UFO",
    "yrkesskadeerstatning": "YRK",
    "foreldrepenger": "FOR",
    "svangerskapspenger": "FOR",
    "engangsstonad": "FOR",
    "overgangsstonad": "ENF",
    "gjenlevendepensjon": "EYO",
    "barnepensjon": "EYB",
    "alderspensjon": "PEN",
    # 1966-loven
    "uforepensjon": "UFO",
    "etterlattepensjon": "EYO",
    "attforingspenger": "YRA",
    "rehabiliteringspenger": "REH",
    # utenfor folketrygdloven
    "barnetrygd": "BAR",
    "kontantstotte": "KON",
}

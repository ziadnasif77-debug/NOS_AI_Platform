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

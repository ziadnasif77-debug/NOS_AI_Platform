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
}

TERMINAL_TILSTANDER = {"DONE", "FAILED"}

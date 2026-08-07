"""
Generelt dokument-API — kjører lokalt på din maskin, uten Docker.

Tar imot selve FILEN (multipart/form-data) slik ENHVER klient sender
den — GUI-er, UiPath, Power Automate, curl, egne skript. Ingenting i
API-et er knyttet til én bestemt klient eller én bestemt dokumenttype.

Flyt:
    UiPath  --(HTTP POST, fil vedlagt)-->  /dokument
                                              |
                              leser PDF-tekstlaget (PyMuPDF)
                                              |
                        deterministisk uttrekk (mod11, anti-hallusinering)
                                              |
    UiPath  <--(JSON: felter + trenger_ocr)--

For tekst-PDF-er svarer det med felter med en gang. For skannede
bilde-PDF-er (uten tekstlag) kjøres EasyOCR automatisk (GPU, med
CPU-fallback) før uttrekk/spørsmål — finner heller ikke OCR-en tekst,
sier svaret det ærlig (strekkoder er ikke tekst).

I tillegg: POST /spor tar imot FIL + SPØRSMÅL (multipart-felter «fil» og
«sporsmal») og svarer med fritt svar fra Borealis (norsk LLM, 4-bit på
GPU). Modellen lastes i bakgrunnen ved oppstart; /spor svarer 503 med
forklaring til den er klar.

Start:
    python skript/dokument_api.py
Enhver HTTP-klient: POST http://localhost:8600/dokument med filen som
multipart-felt «fil». Se GET /hjelp for alle endepunkter.
"""
import gzip
import hashlib
import io
import json
import os
import queue
import re
import sys
import tempfile
import logging
import logging.handlers
import socket
import threading
import time
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Norske tegn (æøå) på et Windows-konsoll krever UTF-8 på stdout.
# R53: gjøres BARE når fila kjøres som program. Å bytte ut global stdout
# ved import er en bivirkning som rammer alle som importerer modulen —
# blant annet testene, der pytests egen fangst da får en lukket buffer.
if __name__ == "__main__" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)


def _last_env_fil(sti: str = None) -> list:
    """Leser .env i prosjektroten inn i miljøet.

    SIKKERHETSFIKS: fila fantes og hadde API_NOKKEL satt, men INGEN kode
    leste den — så serveren kjørte helt åpen mens operatøren trodde
    nøkkel var påkrevd. Med tunnelen oppe betyr det at et dokument-API
    med personopplysninger sto fritt tilgjengelig på internett.

    Ekte miljøvariabler VINNER over fila, så en launcher eller
    `set API_NOKKEL=` fortsatt kan overstyre. Returnerer navnene som
    faktisk ble satt herfra, så oppstarten kan si det høyt."""
    sti = sti or os.path.join(ROT, ".env")
    satt = []
    try:
        with open(sti, encoding="utf-8", errors="replace") as f:
            for linje in f:
                linje = linje.strip()
                if not linje or linje.startswith("#") or "=" not in linje:
                    continue
                navn, verdi = linje.split("=", 1)
                navn, verdi = navn.strip(), verdi.strip().strip('"').strip("'")
                # tomme verdier skal ikke overskrive noe, og et ekte
                # miljø (launcher/tjeneste) har alltid forrang
                if navn and verdi and not os.environ.get(navn):
                    os.environ[navn] = verdi
                    satt.append(navn)
    except OSError:
        pass
    return satt


# Bare når fila kjøres SOM SERVER. Å laste .env ved import ville vært en
# bivirkning som rammer alle som importerer modulen — testene kjørte
# plutselig med Label Studio-token og skrudde på auto-gjennomgang av seg
# selv. Samme forbehold som stdout-innpakningen over. Dette må stå FØR
# konstantene under, som leses fra miljøet.
_ENV_SATT = _last_env_fil() if __name__ == "__main__" else []

from delt.tekstuttrekk import (er_gyldig_fnr, er_gyldig_orgnr, finn_adresser,
                               finn_alle_belop, finn_alle_datoer,
                               finn_alle_eposter, finn_alle_fodselsnummer,
                               finn_alle_kid, finn_alle_kontonummer,
                               finn_alle_organisasjonsnummer,
                               finn_alle_telefoner, finn_dato,
                               finn_dokumentdato, finn_koder_med_kontekst,
                               finn_mistenkt_usladdet, finn_sladdeomraader,
                               felter_flatt, flett_mal,
                               identifikatortyper_i_mal, klassifiser_datoer,
                               refererte_felt, sett_dato_roller,
                               sladd_tekst, strukturert_uttrekk,
                               utvid_entiteter, FLETT_REGEL_VERSJON,
                               SLADD_TYPER, UTTREKK_REGEL_VERSJON)
# All prompttekst bor i regler/prompter.md — ett sted å lese, ett sted
# å endre. Se delt/prompter.py for hvorfor.
from delt import prompter
from delt.dokumentprofil import bygg_profil
from delt.klienter import (AAPEN, MINSTE_LENGDE as MINSTE_NOKKELLENGDE,
                           finn_klient, gjenbrukte_nokler, les_nokler,
                           svake_nokler)
from delt.opphav import (NIVAAER, bygg_opphav, opphav_for_skjema,
                         uten_utelatte)

# UTF-8-trygg utskrift: norsk (æøå) skal ikke krasje når stdout er en fil/
# pipe med ikke-UTF-8-kodesett (cp1256) — f.eks. når tjeneste-wrapperen
# omdirigerer til data/logger/dokument_api.ut.log.
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PORT = int(os.environ.get("DOKUMENT_API_PORT",
                          os.environ.get("UIPATH_API_PORT", "8600")))
MAKS_BYTES = int(os.environ.get("MAKS_OPPLASTING_MB", "200")) * 1024 * 1024
# Hvor mange tegn av dokumentet LLM-en leser direkte. Større dokumenter
# suppleres med deterministisk uttrekk fra HELE teksten + advarsel.
MAKS_LLM_TEGN = int(os.environ.get("MAKS_LLM_TEGN", "12000"))
# OCR er ekte GPU-arbeid per side — standardgrense, kan økes per
# forespørsel med multipart-feltet maks_sider (tak: OCR_TAK_SIDER).
# Kuttes det, sier svaret det ALLTID eksplisitt i 'advarsel'.
OCR_MAKS_SIDER = int(os.environ.get("OCR_MAKS_SIDER", "10"))
OCR_TAK_SIDER = int(os.environ.get("OCR_TAK_SIDER", "50"))
# Sikkerhet: settes API_NOKKEL, kreves headeren X-API-Key på alle
# endepunkter unntatt GET /hjelp. Tom = åpen (kun for lokal testing).
API_NOKKEL = os.environ.get("API_NOKKEL", "").strip()
# NAVNGITTE nøkler: «navn:nøkkel,navn:nøkkel». Uten klientidentitet er
# hver forespørsel anonym, og spørsmålet «bruker noen fortsatt dette?»
# har ikke noe svar — så et utgått felt må stå for alltid. Med navn får
# tilgangsloggen en «klient_id», og fjerning kan gjøres med kunnskap.
# API_NOKKEL virker uendret ved siden av; ingen integrasjon brekker.
API_NOKLER = les_nokler(os.environ.get("API_NOKLER", ""))
# Stiene som svarer i v2-form. En EKSPLISITT mengde, ikke et
# prefikssjekk: «startswith» ville gjort /api/v2noeannet til en
# v2-rute, og prefikset alene ser dessuten ut som en rute for
# vakttesten som krever at hver rute er dokumentert.
# Prefiksene _sti() normaliserer bort. Navngitt fordi de er PREFIKSER,
# ikke ruter: skrevet som strengliteraler rett i startswith() ble de
# lest som endepunkter av vakttesten som krever at hver rute er
# dokumentert — og «/api/» er ingen rute.
API_PREFIKS = "/api"
V1_PREFIKS = API_PREFIKS + "/v1"
_VERSJONSLEDD = re.compile(re.escape(API_PREFIKS) + r"/v\d+(?:/|$)")
# CORS: tom = INGEN CORS-header (mest restriktivt) — de faktiske
# klientene (tkinter-GUI, UiPath, curl) er ikke nettlesere og trenger
# ingen CORS. Var hardkodet «*» (enhver nettside kunne kalle API-et fra
# en brukers nettleser). Sett en kommaseparert liste av tillatte opphav,
# eller «*» bevisst, hvis en nettleserklient trenger det.
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "").strip()
# Rate-limiting: maks forespørsler per klient per minutt (dybdeforsvar mot
# skraping/misbruk på et eksponert endepunkt). 0 = av. Bak en tunnel/gateway
# er socket-IP-en localhost, så den videresendte klient-IP-en brukes.
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "120"))

# --- Samtidighetsvakt -------------------------------------------------
# OCR og språkmodellen deler ETT skjermkort og serialiseres uansett på
# GPU-låsen. Flere enn noen få tunge forespørsler samtidig gir derfor
# ingen gjennomstrømning — bare kostnader. Målt med 10 samtidige skannede
# sider mot 1 om gangen: samme 10 dokumenter, men 78 tråder, 8,5 GB RSS og
# 76 s vegg-tid (median 42 s per klient) mot 7,6 s per dokument alene.
# Resultatene var korrekte hele veien; problemet er ressursbruk og at en
# klient kan bli stående uten å vite at den står i kø.
#
# To vakter, begge med ÆRLIG 503 + Retry-After i stedet for taus venting:
#   1) hvor mange tunge forespørsler som behandles samtidig
#   2) hvor mange opplastede byte som ligger i minnet samtidig — hele
#      kroppen leses inn før parsing, så N × MAKS_BYTES er det virkelige
#      minnetaket uten denne
# Grensen er MÅLT, ikke fast: serveren skal ta imot flere klienter av seg
# selv når den får flere kort, mer minne og flere kjerner — uten at noe
# stilles om. Måles på nytt med jevne mellomrom, så en oppgradering (eller
# et annet program som slipper minne) slår inn mens serveren kjører.
# MAKS_SAMTIDIGE_TUNGE overstyrer manuelt hvis den settes.
# Køfristen MÅ være kortere enn socketfristen (120 s). Var den
# lengre, kunne klienten stå og vente forbi serverens egen frist
# på tilkoblingen og få verken svar eller 503 — bare stillhet.
KOE_VENT_S = float(os.environ.get("KOE_VENT_S", "90"))
MAKS_SAMTIDIGE_MB = int(os.environ.get("MAKS_SAMTIDIGE_MB", "400"))
# Hvor mange som får stå inne per kort. OCR serialiseres uansett per kort,
# så poenget er å holde kortet mettet — ikke å kjøre alt samtidig.
SAMTIDIGE_PER_GPU = int(os.environ.get("SAMTIDIGE_PER_GPU", "4"))
SAMTIDIGE_UTEN_GPU = int(os.environ.get("SAMTIDIGE_UTEN_GPU", "2"))
# Minne en forespørsel legger beslag på mens den behandles. Målt: 10
# samtidige skannede sider løftet serveren fra 7,0 til 8,1 GB ≈ 110 MB
# hver; 300 gir romslig margin for større dokumenter.
RAM_PER_JOBB_MB = int(os.environ.get("RAM_PER_JOBB_MB", "300"))
VRAM_PER_JOBB_MB = int(os.environ.get("VRAM_PER_JOBB_MB", "700"))
MIN_SAMTIDIGE = int(os.environ.get("MIN_SAMTIDIGE", "2"))
MAKS_SAMTIDIGE_TAK = int(os.environ.get("MAKS_SAMTIDIGE_TAK", "64"))
KAPASITET_MAAL_S = float(os.environ.get("KAPASITET_MAAL_S", "30"))
_i_flukt_bytes = {"n": 0}
_i_flukt_las = threading.Lock()


def _gpu_ressurser() -> tuple:
    """(antall kort, samlet ledig VRAM i MiB). (0, 0) uten CUDA."""
    try:
        import torch
        if not torch.cuda.is_available():
            return 0, 0.0
        antall = torch.cuda.device_count()
        ledig = 0.0
        for i in range(antall):
            try:
                ledig += torch.cuda.mem_get_info(i)[0] / (1024 * 1024)
            except Exception:
                continue
        return antall, ledig
    except Exception:
        return 0, 0.0


def _ledig_ram_mb() -> float:
    """Ledig systemminne i MiB. psutil hvis den finnes, ellers Windows-API."""
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 * 1024)
    except Exception:
        pass
    try:
        import ctypes

        class _MINNE(ctypes.Structure):
            _fields_ = [("lengde", ctypes.c_uint32),
                        ("minne_last", ctypes.c_uint32),
                        ("total_fys", ctypes.c_uint64),
                        ("ledig_fys", ctypes.c_uint64),
                        ("total_side", ctypes.c_uint64),
                        ("ledig_side", ctypes.c_uint64),
                        ("total_virt", ctypes.c_uint64),
                        ("ledig_virt", ctypes.c_uint64),
                        ("ledig_utvidet", ctypes.c_uint64)]

        m = _MINNE()
        m.lengde = ctypes.sizeof(_MINNE)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return m.ledig_fys / (1024 * 1024)
    except Exception:
        pass
    return 4096.0        # ukjent maskin: anta beskjedent, aldri ubegrenset


def mal_kapasitet() -> dict:
    """Måler maskinen og regner ut hvor mange tunge forespørsler den tåler
    SAMTIDIG akkurat nå. Den knappeste ressursen bestemmer — å slippe inn
    flere enn den tåler gir ikke gjennomstrømning, bare minnepress og
    lengre kø for alle.

    Returnerer måling, grense og hvilken ressurs som binder, så tallet
    kan begrunnes i /hjelp i stedet for å være magisk."""
    manuell = os.environ.get("MAKS_SAMTIDIGE_TUNGE", "").strip()
    kjerner = os.cpu_count() or 4
    gpuer, vram_mb = _gpu_ressurser()
    ram_mb = _ledig_ram_mb()

    if gpuer:
        # per kort: en fast kvote for å holde kortet mettet, men aldri
        # flere enn det ledige VRAM-et faktisk bærer
        fra_gpu = min(gpuer * SAMTIDIGE_PER_GPU,
                      max(1, int(vram_mb // VRAM_PER_JOBB_MB)))
    else:
        fra_gpu = SAMTIDIGE_UTEN_GPU * max(1, kjerner // 4)
    fra_cpu = max(1, kjerner // 2)
    fra_ram = max(1, int(ram_mb // RAM_PER_JOBB_MB))

    kilder = {"gpu": fra_gpu, "cpu": fra_cpu, "ram": fra_ram}
    raa = min(kilder.values())
    grense = max(MIN_SAMTIDIGE, min(raa, MAKS_SAMTIDIGE_TAK))
    binder = min(kilder, key=kilder.get)

    if manuell.isdigit() and int(manuell) > 0:
        grense, binder = int(manuell), "manuell (MAKS_SAMTIDIGE_TUNGE)"

    return {
        "grense": grense,
        "binder": binder,
        "maalt": {
            "gpu_kort": gpuer,
            "gpu_ledig_mb": round(vram_mb),
            "cpu_kjerner": kjerner,
            "ram_ledig_mb": round(ram_mb),
        },
        "fra": kilder,
    }


class _Kapasitetsport:
    """Slipper inn så mange samtidige tunge forespørsler som maskinen
    faktisk bærer NÅ. Grensen måles på nytt hvert KAPASITET_MAAL_S, så en
    server som får flere kort, mer minne eller flere kjerner tar imot
    flere klienter av seg selv — uten omstart og uten at noe stilles om.

    En vanlig Semaphore duger ikke: den låser antallet ved oppstart."""

    def __init__(self):
        self._las = threading.Condition()
        self._inne = 0
        self._kapasitet = None
        self._maalt_ved = 0.0

    def _gjeldende(self) -> dict:
        """Kalles med _las holdt."""
        naa = time.monotonic()
        if (self._kapasitet is None
                or naa - self._maalt_ved >= KAPASITET_MAAL_S):
            self._maalt_ved = naa
            self._kapasitet = mal_kapasitet()
        return self._kapasitet

    def status(self) -> dict:
        with self._las:
            kap = dict(self._gjeldende())
            kap["i_arbeid"] = self._inne
            return kap

    def ta(self, frist: float) -> bool:
        slutt = time.monotonic() + frist
        with self._las:
            while True:
                if self._inne < self._gjeldende()["grense"]:
                    self._inne += 1
                    return True
                igjen = slutt - time.monotonic()
                if igjen <= 0:
                    return False
                # maks 1 s om gangen: da fanges en NY måling opp med en
                # gang kapasiteten vokser, uten at noen står og venter
                self._las.wait(min(igjen, 1.0))

    def slipp(self) -> None:
        with self._las:
            self._inne = max(0, self._inne - 1)
            self._las.notify()


_kapasitet_port = _Kapasitetsport()
# Endepunkter som gjør tungt arbeid SYNKRONT. /jobb er utelatt med vilje:
# den svarer 202 med en gang og har allerede én arbeidstråd som grense.
# /innsyn svarer også med en gang (arbeidet skjer i egen tråd).
# Rutene som gjør ekte OCR-/modellarbeid og derfor må ta en køplass.
# De nye dokumentrutene gjør NØYAKTIG samme arbeid som /dokument —
# uten dem her ville v2 og operasjonsressursen gått utenom
# kapasitetsporten, og serveren kunne overlastes gjennom en dør mens
# den andre var stengt.
_TUNGE_STIER = ("/spor", "/dokument", "/dokument/operasjoner", "/sladd")
_rate_lock = threading.Lock()
_rate_teller = {}   # klient-ip -> [vindu_minutt, antall]


def _rate_tillatt(ip: str) -> bool:
    """Kjerne-rate-limit (teller per klient per minutt). Modulnivå så den
    kan enhetstestes uten en HTTP-handler. True = innenfor grensen."""
    if RATE_LIMIT_PER_MIN <= 0:
        return True
    vindu = int(time.time() // 60)
    with _rate_lock:
        rad = _rate_teller.get(ip)
        if rad is None or rad[0] != vindu:
            if len(_rate_teller) > 10000:   # unngå ubegrenset vekst
                _rate_teller.clear()
            _rate_teller[ip] = [vindu, 1]
            return True
        rad[1] += 1
        return rad[1] <= RATE_LIMIT_PER_MIN


# Tilgangslogg: én JSON-linje per forespørsel med METADATA — aldri kroppen
# (som kan inneholde PII). Tom sti = av. Svarer §3.3-kravet om at
# revisjonssporet viser hvem/hva som traff hvert endepunkt.
TILGANGSLOGG_STI = os.environ.get("TILGANGSLOGG", "data/logger/tilgang.log").strip()
# Loggen roterte IKKE — den vokste fritt, og med klient_id på hver rad
# vokser den litt raskere. Et revisjonsspor som fyller disken slutter å
# være et revisjonsspor. Vinduet er bevisst romslig: klientrapporten
# spør typisk 30–365 dager tilbake, og en fil som roterer bort før
# spørsmålet stilles er verdiløs. 10 MB × 12 ≈ et halvt år med normal
# last, og filene ligger under nav/ som alt annet (CLAUDE.md §1).
TILGANGSLOGG_MAKS_MB = int(os.environ.get("TILGANGSLOGG_MAKS_MB", "10"))
TILGANGSLOGG_ARKIV = int(os.environ.get("TILGANGSLOGG_ARKIV", "12"))
_tilgang_logger = None
_tilgang_init_lock = threading.Lock()


def _tilgangslogger():
    """Lazy, tråd-trygg logger med ÉN vedvarende filhåndtak — unngår å
    åpne fila + ta en global lås under I/O på HVER forespørsel (som ville
    serialisere alle tråder ved høy last). Opprettes én gang."""
    global _tilgang_logger
    if _tilgang_logger is not None:
        return _tilgang_logger
    with _tilgang_init_lock:
        if _tilgang_logger is None:
            lg = logging.getLogger("nav.tilgang")
            lg.setLevel(logging.INFO)
            lg.propagate = False
            if not lg.handlers:
                try:
                    mappe = os.path.dirname(TILGANGSLOGG_STI)
                    if mappe:
                        os.makedirs(mappe, exist_ok=True)
                    # Roterende, ikke voksende: se TILGANGSLOGG_MAKS_MB.
                    # delay=False (standard) åpner fila nå, så en
                    # rettighetsfeil oppdages ved oppstart og ikke ved
                    # første forespørsel.
                    h = logging.handlers.RotatingFileHandler(
                        TILGANGSLOGG_STI, encoding="utf-8",
                        maxBytes=TILGANGSLOGG_MAKS_MB * 1024 * 1024,
                        backupCount=TILGANGSLOGG_ARKIV)
                    h.setFormatter(logging.Formatter("%(message)s"))
                    lg.addHandler(h)
                except Exception:
                    lg.addHandler(logging.NullHandler())
            _tilgang_logger = lg
    return _tilgang_logger


def _skriv_tilgang(handler, code) -> None:
    """Én JSON-linje til tilgangsloggen. Best-effort, aldri fatal. Logger
    kun ip, metode, sti (uten query), status, om X-API-Key var med, og
    responstid — ALDRI forespørselskroppen (kan inneholde PII)."""
    if not TILGANGSLOGG_STI:
        return
    try:
        ms = round((time.time() - getattr(handler, "_t0_req", time.time())) * 1000)
        rad = json.dumps({
            "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
            # samme ID som klienten fikk i X-Correlation-ID-svarhodet, så
            # en feilmelding hos brukeren kan slås rett opp i denne raden
            "korrelasjon": getattr(handler, "_korr_id", None),
            "ip": handler._klient_ip(),
            "metode": getattr(handler, "command", "?"),
            "sti": handler.path.split("?", 1)[0],
            "kode": code.value if hasattr(code, "value") else code,
            "nokkel": bool(handler.headers.get("X-API-Key")),
            # Hvem kalte. ALDRI selve nøkkelen — et navn i en logg er
            # nyttig, en nøkkel i en logg er en lekkasje som overlever i
            # sikkerhetskopier. None = nøkkelen traff ingen klient.
            "klient_id": getattr(handler, "_klient_id", None),
            "ms": ms,
        }, ensure_ascii=False)
        _tilgangslogger().info(rad)
    except Exception:
        pass


# Auto-gjennomgang: leser vi et dokument dårlig (lav OCR-konfidens eller
# håndskrift), sendes det automatisk til Label Studio for menneskelig
# korreksjon — som igjen mater treningsløkken (finjuster). AV som
# standard: aktiveres kun når både URL og API-nøkkel er satt, så
# «lagrer ingenting»-oppførselen bevares for dem som ikke vil ha det.
LABEL_STUDIO_URL = os.environ.get("LABEL_STUDIO_URL", "").strip()
LABEL_STUDIO_API_KEY = os.environ.get("LABEL_STUDIO_API_KEY", "").strip()
LS_KONFIDENS_TERSKEL = float(os.environ.get("LS_KONFIDENS_TERSKEL", "0.85"))
AUTO_GJENNOMGANG = bool(LABEL_STUDIO_URL and LABEL_STUDIO_API_KEY)
# Versjonsstempling — følger med hvert /spor-svar så resultater kan
# spores tilbake til nøyaktig API- og prompt-versjon (R39)
# Hvor mange datoer som LISTES for modellen. Dokumentdatoen velges av
# hele lista uansett — grensen gjelder bare plassen i prompten.
MAKS_DATOER_I_PROMPT = 30

# gzip: under denne grensen koster komprimeringen mer enn den sparer
# (og en TCP-pakke er uansett ~1,4 kB). Nivå 6 er standardbalansen —
# målt gevinst på et vanlig svar er 80,8 %, og nivå 9 gir under ett
# prosentpoeng mer for merkbart mer CPU.
GZIP_MINSTE_BYTE = 1024
GZIP_NIVAA = 6

# Budsjett for ÉN forespørsel til operasjonsmotoren. Uten det kunne 20
# svar-operasjoner utløse 100 genereringer (0,3–2,8 s hver, serialisert
# bak GPU-låsen) — 30–280 s i ett kall, mot en socketfrist på 120 s.
# Fristen er satt godt under socketfristen så klienten får et SVAR.
MAKS_MODELLOPERASJONER = 8
OPERASJON_FRIST_S = 75.0

# FØRSTE utgivelse. Tallene 1.3.0 -> 1.6.0 -> 2.0.0 var utvikling ingen
# utenfor maskinen så: API-et har aldri vært i drift. «2.0.0» ville
# påstått at det fantes en 1.x som ble brutt, og et versjonsnummer som
# lyver er verre enn ingen (R108).
API_VERSJON = "1.0.0"
# Promptversjonen står i regler/prompter.md, sammen med ordlyden den
# beskriver — så den ikke kan bli glemt når en regel endres. Den slås
# opp PER SVAR (prompter.versjon()), ikke ved oppstart: reglene kan
# endres mens serveren kjører, og da ville en versjon frosset ved
# oppstart pekt på en ordlyd som ikke lenger er den som svarte (R39).

# RFC 9457 Problem Details — samme standard som NAV Oppgave-APIet bruker.
# Basis-URI-en for «type» kan overstyres (settes til tjenestens egen
# adresse i produksjon); ellers en nøytral placeholder.
PROBLEM_BASIS = os.environ.get(
    "PROBLEM_BASIS_URI", "https://nav-dokument-api/problems").rstrip("/")
# Kort, stabil tittel per statuskode — det maskinlesbare «hva», mens
# «detail» er den menneskelige forklaringen fra selve feilstedet.
_PROBLEM_TITLER = {
    400: ("ugyldig-input", "Ugyldig input"),
    401: ("unauthorized", "Unauthorized"),
    404: ("ikke-funnet", "Ikke funnet"),
    409: ("konflikt", "Konflikt"),
    413: ("for-stor", "For stor forespørsel"),
    429: ("for-mange-kall", "For mange kall"),
    503: ("utilgjengelig", "Tjenesten er opptatt"),
    500: ("intern-feil", "Intern feil"),
}


def _problem_detaljer(kode, detalj, korrelasjon, sti=None, felter_feil=None):
    """Bygger et RFC 9457-objekt {type, title, status, detail, traceId,
    (errors)}. traceId = korrelasjons-ID-en, så ett oppslag kobler
    problemet til logglinjen. `felter_feil` er en valgfri liste
    {pointer, message, (value)} som forteller HVILKET felt som er galt —
    slik NAV Oppgave-APIet gjør, i stedet for bare «ugyldig input»."""
    kode = kode.value if hasattr(kode, "value") else kode
    slug, tittel = _PROBLEM_TITLER.get(kode, ("feil", "Feil"))
    problem = {
        "type": f"{PROBLEM_BASIS}/{slug}",
        "title": tittel,
        "status": kode,
        "detail": detalj or tittel,
        "traceId": korrelasjon,
    }
    if sti:
        problem["instance"] = sti
    if felter_feil:
        problem["errors"] = felter_feil
    return problem


_NORHAND_VERSJON = None


def _norhand_versjon() -> str:
    """Versjonsstempel for den aktive norhand-modellen, skrevet av
    kvalitetsporten ved promotering (modeller/norhand/nav_versjon.txt).
    Cachet fordi den kjørende modellen ikke byttes uten omstart. «ukjent»
    hvis modellen aldri er promotert gjennom porten."""
    global _NORHAND_VERSJON
    if _NORHAND_VERSJON is None:
        try:
            sti = os.path.join(os.environ.get("MODELLER_STI", "./modeller"),
                               "norhand", "nav_versjon.txt")
            with open(sti, encoding="utf-8") as f:
                _NORHAND_VERSJON = f.read().strip() or "ukjent"
        except Exception:
            _NORHAND_VERSJON = "ukjent"
    return _NORHAND_VERSJON


def _versjon_stempel() -> dict:
    """R39/§4: full proveniens per svar — modell-, regel- og terskelversjon
    så hvert result kan spores til nøyaktig det som produserte det."""
    return {
        "api": API_VERSJON,
        "prompt": prompter.versjon(),
        "uttrekk_regler": UTTREKK_REGEL_VERSJON,
        "ocr_konfidens_terskel": LS_KONFIDENS_TERSKEL,
        "norhand": _norhand_versjon(),
    }
# Maks lengde på generert svar. Taket er en RESSURSGRENSE, ikke en
# stilregel: korte svar stopper naturlig ved EOS uansett. Treffer et
# svar taket, flagges det ALLTID eksplisitt (svar_avkortet + advarsel).
MAKS_SVAR_TOKENS = int(os.environ.get("MAKS_SVAR_TOKENS", "1024"))


# ------------------------------------------------------------------ #
#  Multipart-parsing (kun stdlib) — henter fil OG tekstfelter         #
# ------------------------------------------------------------------ #

def _cd_parameter(hoder: bytes, parameter: str):
    """Henter en Content-Disposition-parameter («name» / «filename») ENTEN
    klienten siterer verdien eller ikke. None hvis parameteren mangler.

    R63: RFC 7578 sier verdien BØR siteres, men .NET-baserte klienter —
    og dermed UiPath — sender et enkelt token USITERT:
        Content-Disposition: form-data; name=sporsmal
    Parseren krevde `name="` med anførselstegn og droppet da ALLE
    tekstfeltene i stillhet. Fila kom likevel fram, fordi et filnavn med
    mellomrom («Taxi fra.pdf») MÅ siteres — derfor så det ut som om bare
    tekstfeltene «forsvant» hos klienten. Det er denne fella som gjorde at
    skjema_mal/skjema_motor/sporsmal aldri nådde serveren fra UiPath.

    Foranstilt `(?:^|[;\\s])` er nødvendig: uten den ville «name» også
    treffe inni «filename=»."""
    tekst = hoder.decode("utf-8", "replace")
    treff = re.search(
        r'(?:^|[;\s])' + re.escape(parameter) + r'\s*=\s*(?:"([^"]*)"|([^;\r\n]*))',
        tekst, re.IGNORECASE)
    if not treff:
        return None
    if treff.group(1) is not None:
        return treff.group(1)
    return (treff.group(2) or "").strip()


def _rfc5987_verdi(raa: str):
    """Dekoder «UTF-8''taxi%20fr%C3%A5.pdf» → «taxi frå.pdf».

    RFC 5987/6266-formen brukes av .NET og andre klienter så snart et
    filnavn har tegn utenfor ASCII — altså for ethvert norsk filnavn med
    æøå. Uten dette ville et slikt navn ikke bli gjenkjent som filnavn i
    det hele tatt, og filparten ville blitt tolket som et TEKSTFELT."""
    from urllib.parse import unquote
    deler = raa.split("'", 2)
    if len(deler) != 3:
        return None
    tegnsett, _sprak, kodet = deler
    try:
        return unquote(kodet, encoding=tegnsett or "utf-8", errors="replace")
    except (LookupError, ValueError):
        return unquote(kodet, encoding="utf-8", errors="replace")


def _cd_filnavn(hoder: bytes):
    """Filnavnet fra Content-Disposition, uansett hvilken av de to
    formene klienten bruker. «filename*» (RFC 5987) vinner når begge
    finnes — det er den som bærer æøå korrekt."""
    utvidet = _cd_parameter(hoder, "filename*")
    if utvidet:
        dekodet = _rfc5987_verdi(utvidet)
        if dekodet:
            return dekodet
    return _cd_parameter(hoder, "filename")


def _parse_multipart(body: bytes, content_type: str):
    """Returnerer (filnavn, filbytes, tekstfelter) fra en
    multipart/form-data-body. Filnavn/filbytes er None hvis ingen fil;
    tekstfelter er dict av vanlige skjemafelter (f.eks. 'sporsmal').

    Parseren er bevisst tolerant mot klientvariasjon (R63): feltnavn med
    og uten anførselstegn, CRLF og bare LF, filnavn i begge RFC-former,
    og en boundary som står sammen med andre parametre. Alle disse har
    samme feilmodus — delen faller stille ut og API-et svarer 200 som om
    klienten aldri sendte feltet."""
    tekstfelter = {}
    # Boundary hentes med samme parameterleser som resten: den takler
    # både «boundary=abc» og «boundary="abc"», og stopper ved neste «;».
    # Naiv split på «boundary=» tok med etterfølgende parametre — en
    # Content-Type som «...; boundary=abc; charset=utf-8» ga da en
    # boundary som aldri fantes i kroppen, og ALT ble borte.
    boundary = _cd_parameter(content_type.encode("utf-8", "replace"),
                             "boundary")
    if not boundary:
        return None, None, tekstfelter
    skille = ("--" + boundary).encode()
    filnavn, filbytes = None, None
    for del_ in body.split(skille):
        # Hoder skilles fra innhold av en TOM LINJE. RFC krever CRLF, men
        # enkelte klienter sender bare LF — godtar vi ikke begge, hoppes
        # hele delen over.
        tomlinje = re.search(b"\r?\n\r?\n", del_)
        if not tomlinje:
            continue
        hoder = del_[:tomlinje.start()]
        # fjern etterfølgende linjeskift før neste boundary
        innhold = del_[tomlinje.end():].rstrip(b"\r\n")
        funnet_filnavn = _cd_filnavn(hoder)
        funnet_feltnavn = _cd_parameter(hoder, "name")
        if funnet_filnavn is not None:
            if filbytes is None:      # første fil vinner
                filnavn = funnet_filnavn or "opplastet.pdf"
                filbytes = innhold
        elif funnet_feltnavn:
            # Tekstdelen kan oppgi sitt eget tegnsett. Uten dette ville
            # æøå fra en klient som ikke bruker UTF-8 bli til krøll.
            tegnsett = _cd_parameter(hoder, "charset") or "utf-8"
            try:
                tekst = innhold.decode(tegnsett, "replace")
            except LookupError:
                tekst = innhold.decode("utf-8", "replace")
            tekstfelter[funnet_feltnavn] = tekst.strip()
    return filnavn, filbytes, tekstfelter


# ------------------------------------------------------------------ #
#  Filtype-normalisering — alt blir PDF-bytes eller ren tekst         #
# ------------------------------------------------------------------ #

BILDE_TYPER = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
# Maks tekstlinjer fra regneark/CSV — beskytter mot gigantiske JSON-svar
MAKS_TABELL_LINJER = 1000


def normaliser_fil(filnavn: str, data: bytes):
    """Gjør enhver støttet filtype om til noe resten av API-et forstår.

    Returnerer (slag, innhold):
      ("pdf", pdf_bytes)   — PDF-er som de er; bilder konverteres til PDF
                             slik at OCR/strekkoder/alt virker uendret
      ("tekst", str)       — DOCX/TXT: teksten hentes direkte (ingen OCR)
      (None, feilmelding)  — filtype som ikke støttes
    """
    lav = filnavn.lower()
    if lav.endswith(".pdf"):
        return "pdf", data
    if lav.endswith(BILDE_TYPER):
        import fitz
        bilde_doc = fitz.open(stream=data, filetype=lav.rsplit(".", 1)[1])
        pdf = bilde_doc.convert_to_pdf()
        bilde_doc.close()
        return "pdf", pdf
    if lav.endswith(".txt"):
        return "tekst", data.decode("utf-8", "replace")
    if lav.endswith(".docx"):
        import io as _io
        from docx import Document
        dok = Document(_io.BytesIO(data))
        deler = [avsnitt.text for avsnitt in dok.paragraphs]
        for tabell in dok.tables:
            for rad in tabell.rows:
                deler.append(" | ".join(c.text for c in rad.cells))
        return "tekst", "\n".join(d for d in deler if d.strip())
    if lav.endswith(".csv"):
        import csv as _csv
        import io as _io
        try:
            raa = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            # Norske CSV-er fra eldre systemer er ofte cp1252 (æøå)
            raa = data.decode("cp1252", "replace")
        try:
            dialekt = _csv.Sniffer().sniff(raa[:2000], delimiters=",;\t")
        except _csv.Error:
            dialekt = _csv.excel
        linjer = []
        for rad in _csv.reader(_io.StringIO(raa), dialekt):
            celler = [felt.strip() for felt in rad if felt.strip()]
            if celler:
                linjer.append(" | ".join(celler))
            if len(linjer) >= MAKS_TABELL_LINJER:
                linjer.append("[Avkortet: filen har flere rader]")
                break
        return "tekst", "\n".join(linjer)
    if lav.endswith((".xlsx", ".xlsm")):
        import io as _io
        from openpyxl import load_workbook
        bok = load_workbook(_io.BytesIO(data), read_only=True, data_only=True)
        linjer = []
        for ark in bok.worksheets:
            linjer.append(f"[Ark: {ark.title}]")
            for rad in ark.iter_rows(values_only=True):
                celler = [str(c).strip() for c in rad if c is not None and str(c).strip()]
                if celler:
                    linjer.append(" | ".join(celler))
                if len(linjer) >= MAKS_TABELL_LINJER:
                    break
            if len(linjer) >= MAKS_TABELL_LINJER:
                linjer.append("[Avkortet: arbeidsboken har flere rader]")
                break
        bok.close()
        return "tekst", "\n".join(linjer)
    return None, ("Filtypen støttes ikke. Støttet: PDF, "
                  "bilder (JPG/PNG/TIFF/BMP/WEBP), DOCX, XLSX/XLSM, CSV, TXT")


# ------------------------------------------------------------------ #
#  OCR-fallback — regionbasert ruting (EasyOCR + norhand)             #
# ------------------------------------------------------------------ #

OCR_DPI = int(os.environ.get("OCR_DPI", "200"))


def _ocr_status() -> dict:
    """OCR-motorenes enhetsvalg — for GET /hjelp."""
    try:
        from delt.region_ocr import motorstatus
        return motorstatus()
    except Exception as exc:
        return {"feil": f"kunne ikke lese motorstatus: {exc}"}


def naturlig_dpi(doc, side):
    """Bildesidens EGEN oppløsning i dpi — eller None for en ren tekst-/
    vektorside (som kan rendres vilkårlig fint).

    Trukket ut av ocr_skala slik at forhåndssjekken og OCR-veien bruker
    NØYAKTIG samme regnestykke: én piksel innebygd bilde per PDF-punkt
    tilsvarer 72 dpi."""
    try:
        bilder = side.get_images(full=True)
        if len(bilder) == 1 and side.rect.width > 0:
            bredde_px = doc.extract_image(bilder[0][0]).get("width", 0)
            if bredde_px:
                return (bredde_px / side.rect.width) * 72.0
    except Exception:
        pass   # klarer vi ikke å lese bildeinfo, oppgi ingen dpi
    return None


def ocr_skala(doc, side):
    """Renderoppløsning for OCR av én side.

    R51: en ekte tekst-PDF (A4 = 595 punkter bred) skal rendres ved
    OCR_DPI. Men et OPPLASTET BILDE blir en PDF-side der ett punkt
    tilsvarer én piksel — da ganger 200 dpi opp bildet 2,8× uten å
    tilføre én eneste ny detalj. Det koster dobbelt tid OG gir dårligere
    lesing (målt: «NAV Vedtak» ble til «NAV = Vedtak» etter oppskalering).
    Derfor: aldri rendre finere enn bildets egen oppløsning.
    """
    import fitz

    standard = OCR_DPI / 72
    dpi = naturlig_dpi(doc, side)
    if dpi is not None:
        standard = min(standard, max(dpi / 72.0, 1.0))
    return fitz.Matrix(standard, standard)


# --- forhåndssjekk: billig kvalitetsdom FØR GPU-en brukes -----------
# Sidetak: forhåndssjekken skal være rask og GPU-fri, og et 300-siders
# dokument trenger ikke 300 målinger for en dom — de første sidene er
# representative for skannerens innstillinger.
FORHANDSSJEKK_MAKS_SIDER = int(os.environ.get("FORHANDSSJEKK_MAKS_SIDER", "10"))
# «Avvis»-tersklene er strengere enn advarsel-tersklene i
# delt/forbehandling.py: en advarsel betyr «antakelig dårlig lesing»,
# avvis betyr «OCR er så godt som garantert søppel — ikke bruk GPU-en».
#
# MERK: dømming skjer på RENDREDE PIKSLER, ikke på nominell dpi. Målt i
# kalibreringen: et knivskarpt 1700×2200-bilde lastet opp som PNG får
# nominell dpi 96 (formatets standardantakelse, ikke en egenskap ved
# bildet) — en dpi-terskel ville avvist hvert eneste mobilfoto uansett
# hvor godt det var. Pikslene er det OCR faktisk ser; dpi rapporteres
# som informasjon, uten dom.
FORHANDSSJEKK_AVVIS_PIKSLER = int(
    os.environ.get("FORHANDSSJEKK_AVVIS_PIKSLER", "300"))
FORHANDSSJEKK_AVVIS_SKARPHET = float(
    os.environ.get("FORHANDSSJEKK_AVVIS_SKARPHET", "30"))


def doem_forhandssjekk(sider: list) -> tuple:
    """Samlet dom over sidevurderingene: (dom, anbefaling).

    Reglene, i prioritert rekkefølge:
      «avvis»   — alle sider er tomme, ELLER alle sider med innhold er
                  uleselige (dpi/skarphet under avvis-terskelen).
      «tvilsom» — minst én side har en advarsel. Dokumentet kan leses,
                  men resultatet bør gjennom et menneske.
      «god»     — ingen advarsler.

    Én tom side blant innholdssider gir IKKE avvis: tosidig skanning
    legger rutinemessig inn blanke baksider, og de er ikke en feil."""
    tomme = [s for s in sider if s["tom"]]
    med_innhold = [s for s in sider if not s["tom"]]
    if not med_innhold:
        return ("avvis",
                f"Alle {len(sider)} vurderte sider er tomme — skann "
                "dokumentet på nytt (riktig side opp, dokumentet i "
                "skanneren).")
    uleselige = [s for s in med_innhold if s["uleselig"]]
    if len(uleselige) == len(med_innhold):
        return ("avvis",
                "Alle sider med innhold er uleselige (for lav oppløsning "
                "eller sterkt uskarpe) — OCR vil gi søppel. Skann på nytt "
                "med høyere oppløsning (minst 200 dpi) og godt fokus.")
    if any(s["advarsler"] for s in sider) or tomme:
        return ("tvilsom",
                "Dokumentet kan leses, men har kvalitetsadvarsler — "
                "resultatet bør kontrolleres av et menneske. Se "
                "advarslene per side.")
    return ("god", "Skannkvaliteten ser god ut — send dokumentet til "
                   "POST /dokument.")


def ocr_pdf_bytes(data: bytes, maks_sider: int = None) -> dict:
    """Renderer PDF-sider til bilder (200 dpi) og OCR-er dem med
    regionbasert modellruting (delt/region_ocr): EasyOCR leser alt,
    usikre regioner leses i tillegg av norhand (norsk håndskrift),
    beste motor vinner per region, alt flettes i leserekkefølge.
    Synkron variant med sidegrense — store dokumenter hører hjemme i
    POST /jobb. Rapporterer alltid sider_lest/sider_totalt ærlig."""
    import fitz
    import numpy as np
    from delt.forbehandling import forbehandle_side
    from delt.region_ocr import ocr_side

    if maks_sider is None:
        maks_sider = OCR_MAKS_SIDER
    doc = fitz.open(stream=data, filetype="pdf")
    sider_totalt = doc.page_count
    tekster = []
    motorer = {}
    handskrift = []
    # R55: sidebildene tas vare på og returneres, så strekkodelesingen
    # kan bruke de samme i stedet for å rendre hele dokumentet på nytt.
    rendrede = []
    # Samlet lesekonfidens: lengdevektet snitt av regionscorene. Gir et
    # ærlig «hvor godt leste vi dette»-signal (fantes ikke lokalt før —
    # det bodde i det distribuerte systemet). Brukes til å avgjøre om
    # dokumentet bør til Label Studio for korreksjon.
    konf_sum = 0.0
    konf_vekt = 0.0
    # Side 1-regionene (bokser + skriftslag) beholdes for auto-
    # gjennomgangen: Label Studio-oppgaven får dem som forhåndsmerkede
    # områder, så den ansatte ser hvor maskinen fant tekst.
    side1_regioner = []
    side1_dim = None
    forbehandling_rapport = None
    # Slanke regioner ({boks, tekst}) for ALLE leste sider — grunnlaget
    # for koordinater per funn. Før ble side 2+ sine bokser regnet ut og
    # KASTET etter konfidensstatistikken; å beholde dem koster ~kB per
    # side, mens å regne dem ut på nytt koster en full OCR-kjøring på
    # GPU. Derfor beholdes de alltid (ikke bak et flagg à la R55: flagget
    # ville splittet cachen og utløst re-OCR når klienten ombestemmer seg).
    sider_regioner = []
    # Sider hoppet over av tomside-vakten (1-basert) — rapporteres ærlig
    tomme_sider = []
    for i, side in enumerate(doc):
        if i >= maks_sider:
            break
        pix = side.get_pixmap(matrix=ocr_skala(doc, side))
        bilde = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:      # RGBA → RGB
            bilde = bilde[:, :, :3]
        # Forbehandling FØR OCR: perspektiv/skygge/skjevhet rettes og
        # kvaliteten måles ærlig. Boksene og LS-bildet bygges av det
        # FORBEHANDLEDE bildet, så alt forblir samstemt.
        from delt import innsyn_hendelser
        if i == 0 and innsyn_hendelser.aktiv():
            b64, vb, vh, fb, fh = _bilde_til_b64(bilde)
            innsyn_hendelser.send("side_bilde", stadie="original", bilde=b64,
                                  vist_bredde=vb, vist_hoyde=vh,
                                  full_bredde=fb, full_hoyde=fh)
        bilde, side_rapport = forbehandle_side(bilde)
        if i == 0 and innsyn_hendelser.aktiv():
            b64, vb, vh, fb, fh = _bilde_til_b64(bilde)
            innsyn_hendelser.send("side_bilde", stadie="forbehandlet",
                                  bilde=b64, vist_bredde=vb, vist_hoyde=vh,
                                  full_bredde=fb, full_hoyde=fh,
                                  rapport=side_rapport)
        rendrede.append(bilde)
        # Tomside-vakt FØR OCR: på en (nesten) blank side leser motorene
        # støy og finner på tekst. Målt på en ekte skannet bunke: side 7
        # hadde blekkandel 0,00064 (gjennomslag fra arket bak) og OCR
        # «leste» to linjer som ikke finnes på siden — mens laveste
        # innholdsside lå på 0,015. Terskelen (0,002) skiller med god
        # margin. Siden rapporteres som tom i stedet — ærlig stillhet
        # slår oppdiktet tekst.
        from delt.forbehandling import TOM_SIDE_BLEKK, andel_blekk
        if andel_blekk(bilde) < TOM_SIDE_BLEKK:
            tomme_sider.append(i + 1)
            tekster.append("")
            sider_regioner.append({"side": i + 1, "bredde": bilde.shape[1],
                                   "hoyde": bilde.shape[0], "regioner": []})
            if i == 0:
                side1_dim = (bilde.shape[1], bilde.shape[0])
                forbehandling_rapport = side_rapport
            continue
        resultat = ocr_side(bilde)
        if i == 0:
            side1_regioner = resultat["regioner"]
            # forbehandlet størrelse — perspektivretting kan endre den
            side1_dim = (bilde.shape[1], bilde.shape[0])
            forbehandling_rapport = side_rapport
        tekster.append(resultat["tekst"])
        sider_regioner.append({
            "side": i + 1,
            "bredde": bilde.shape[1], "hoyde": bilde.shape[0],
            "regioner": [{"boks": r["boks"], "tekst": r["tekst"]}
                         for r in resultat["regioner"]
                         if (r.get("tekst") or "").strip()],
        })
        for r in resultat["regioner"]:
            motorer[r["motor"]] = motorer.get(r["motor"], 0) + 1
            vekt = max(len((r.get("tekst") or "").strip()), 1)
            konf_sum += float(r.get("konfidens", 0.0)) * vekt
            konf_vekt += vekt
            # Visuelt klassifisert som håndskrift (eller lest av norhand)
            if r.get("skrift") == "handskrift" and r["tekst"]:
                handskrift.append(r["tekst"])
    doc.close()
    if sider_totalt > 1:
        samlet = "\n".join(f"[Side {i + 1} av {sider_totalt}]\n{t}"
                           for i, t in enumerate(tekster))
    else:
        samlet = "\n".join(tekster)
    konfidens = round(konf_sum / konf_vekt, 4) if konf_vekt else 1.0
    return {"tekst": samlet, "motorer": motorer,
            "handskrift": handskrift, "konfidens": konfidens,
            "sider_lest": min(sider_totalt, maks_sider),
            "sider_totalt": sider_totalt,
            # Understrek = internt felt, aldri med i et JSON-svar (samme
            # konvensjon som jobb["_data"]). Dette er numpy-arrayer.
            "_sidebilder": rendrede,
            "_side1_regioner": side1_regioner,
            "_side1_dim": side1_dim,
            "_sider_regioner": sider_regioner,
            "tomme_sider": tomme_sider,
            "forbehandling": forbehandling_rapport}


# ------------------------------------------------------------------ #
#  Auto-gjennomgang: dårlig lest dokument → Label Studio → trening    #
# ------------------------------------------------------------------ #

def _kanskje_send_til_gjennomgang(filnavn: str, innhold: bytes,
                                  ocr_res: dict, felter: dict) -> dict | None:
    """Leste vi dokumentet dårlig, send det til Label Studio for
    menneskelig korreksjon (som mater treningsløkken). Kjøres i en
    bakgrunnstråd så svaret til klienten aldri forsinkes, og er
    best-effort — feiler Label Studio, logges det og forespørselen går
    videre. Returnerer {grunn, konfidens} hvis den utløste en sending,
    ellers None.

    AV med mindre LABEL_STUDIO_URL + _API_KEY er satt (AUTO_GJENNOMGANG).
    """
    if not AUTO_GJENNOMGANG or not ocr_res:
        return None
    konfidens = float(ocr_res.get("konfidens", 1.0))
    handskrift = bool(ocr_res.get("handskrift"))
    raa_tekst = ocr_res.get("tekst", "")
    tomt = len(raa_tekst.strip()) < 20        # OCR fant nesten ingen tekst
    lav_konfidens = konfidens < LS_KONFIDENS_TERSKEL
    if not (tomt or lav_konfidens or handskrift):
        return None                      # lest godt nok — ingen grunn
    grunn = ("tomt_resultat" if tomt else
             "lav_ocr_konfidens" if lav_konfidens else "handskrift")

    def arbeider():
        png_sti = None
        try:
            # Bruk det FORBEHANDLEDE side 1-bildet fra OCR-en (allerede
            # rendret): (1) regionboksene ble beregnet på nøyaktig dette
            # bildet, så forhåndsmerkingen i Label Studio treffer riktig,
            # (2) annotatøren ser det rettede bildet, (3) ingen dobbel
            # rendring. Stabil id fra PIKSLENE, ikke PDF-bytene: klienten
            # lager ny PDF (nytt tidsstempel) ved hver opplasting.
            side1 = (ocr_res.get("_sidebilder") or [None])[0]
            if side1 is not None:
                from PIL import Image
                fil_id = hashlib.sha256(
                    f"{side1.shape[1]}x{side1.shape[0]}".encode()
                    + side1.tobytes()).hexdigest()[:16]
                png_sti = os.path.join(_gjennomgang_temp(),
                                       f"gjennomgang_{fil_id}.png")
                Image.fromarray(side1).save(png_sti)
            else:
                # reserve: rendrer selv (eldre kall uten _sidebilder)
                import fitz
                doc = fitz.open(stream=innhold, filetype="pdf")
                pix = doc[0].get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72))
                fil_id = hashlib.sha256(
                    f"{pix.width}x{pix.height}".encode() + bytes(pix.samples)
                ).hexdigest()[:16]
                png_sti = os.path.join(_gjennomgang_temp(),
                                       f"gjennomgang_{fil_id}.png")
                pix.save(png_sti)
                doc.close()
            from send_til_label_studio import send_til_gjennomgang
            ok = send_til_gjennomgang(
                fil_id=fil_id, bilde_sti=png_sti, raa_tekst=raa_tekst,
                konfidens=konfidens,
                metadata={k: felter.get(k, "") for k in
                          ("navn", "dato", "ytelse", "fylke")},
                regioner=ocr_res.get("_side1_regioner") or [],
                bilde_dim=ocr_res.get("_side1_dim"))
            print(f"  [gjennomgang] {filnavn} ({grunn}, konf={konfidens}) "
                  f"→ Label Studio: {'sendt' if ok else 'feilet'}",
                  file=sys.stderr)
        except Exception as exc:
            print(f"  [gjennomgang] hoppet over ({type(exc).__name__}: {exc})",
                  file=sys.stderr)
        finally:
            if png_sti is not None:
                try:
                    os.remove(png_sti)
                except OSError:
                    pass

    threading.Thread(target=arbeider, daemon=True).start()
    return {"grunn": grunn, "konfidens": konfidens}


# ------------------------------------------------------------------ #
#  Strekkoder og QR-koder (pyzbar)                                    #
# ------------------------------------------------------------------ #

# Sidetak for strekkodeskanning. Var 5 — med den grensen ble
# arkivstrekkoden på side 10 i en 10-siders bunke ALDRI lest, uten et
# ord om det i svaret. Returslipp/arkivkoder står nettopp bakerst, så
# taket rammet systematisk den viktigste koden i skanneløypa. Nå følger
# det OCR-taket, og trunkering MELDES.
STREKKODE_MAKS_SIDER = int(os.environ.get("STREKKODE_MAKS_SIDER",
                                          str(OCR_TAK_SIDER)))


def les_strekkoder_bytes(data: bytes, maks_sider: int = None, sider=None,
                         rapport: dict = None):
    """Dekoder strekkoder (Code128, EAN m.fl.) og QR-koder fra ALLE
    PDF-sidene. Returnerer liste av {type, verdi, side} — tom liste
    hvis ingen finnes eller pyzbar mangler.

    Flere koder på samme side gir flere oppføringer; rekkefølgen følger
    sidene. Duplikater (samme type+verdi+side) fjernes — pyzbar melder
    av og til samme kode to ganger på et støyete skann.

    «rapport» fylles med {sider_skannet, sider_totalt, avkortet} når den
    gis, slik at kalleren kan si ærlig fra om ikke alle sider ble sett.

    R55: `sider` er ferdig rendrede sidebilder (numpy RGB). Kjører OCR
    på det samme dokumentet, har sidene allerede blitt rendret én gang,
    og å rendre dem om igjen her var rent dobbeltarbeid (målt 0,19 s på
    en A4-side). Uten `sider` rendres de som før — det er tilfellet når
    dokumentet har tekstlag og OCR aldri kjøres.
    """
    if maks_sider is None:
        maks_sider = STREKKODE_MAKS_SIDER
    try:
        from PIL import Image
        from pyzbar.pyzbar import decode
    except ImportError:
        return []
    koder = []
    try:
        if sider is not None:
            sider_totalt = len(sider)
            bilder = [Image.fromarray(s) for s in sider[:maks_sider]]
        else:
            import fitz
            doc = fitz.open(stream=data, filetype="pdf")
            sider_totalt = doc.page_count
            bilder = []
            for i, side in enumerate(doc):
                if i >= maks_sider:
                    break
                # En side helt uten bilder OG uten vektortegninger kan
                # ikke inneholde en strekkode — en kode må være tegnet
                # på en av de to måtene. Rendringen er det dyre steget
                # (~90 ms per side), så en tom side hoppes over uten at
                # noe kan gå tapt.
                #
                # MERK at dette er den ENESTE trygge innsnevringen her.
                # Å filtrere på get_images() alene — som er det
                # nærliggende — ville mistet BEGGE kodene i testbunken:
                # de står på side 3 og 10, og begge sidene har null
                # innebygde bilder. Kodene er vektortegnet (36 og 63
                # tegneoperasjoner). Å senke oppløsningen er heller
                # ikke trygt: målt fant 1.5x begge kodene, men 1.0x
                # fant INGEN — marginen er for liten til å gamble på.
                if not (side.get_images(full=True) or side.get_drawings()):
                    bilder.append(None)          # plassholder: side uten innhold
                    continue
                # R51: samme oppskaleringsfelle som i OCR — strekkoder
                # blir ikke lettere å lese av å blåse opp bildet
                pix = side.get_pixmap(matrix=ocr_skala(doc, side))
                bilder.append(
                    Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
            doc.close()
        sett = set()
        for i, bilde in enumerate(bilder):
            if bilde is None:            # side uten bilder eller tegninger
                continue
            for kode in decode(bilde):
                verdi = kode.data.decode("utf-8", "replace")
                nokkel = (kode.type, verdi, i + 1)
                if nokkel in sett:
                    continue
                sett.add(nokkel)
                koder.append({"type": kode.type, "verdi": verdi,
                              "side": i + 1})
        if rapport is not None:
            rapport.update(sider_skannet=len(bilder),
                           sider_totalt=sider_totalt,
                           avkortet=len(bilder) < sider_totalt)
    except Exception:
        pass
    return koder


# ------------------------------------------------------------------ #
#  Analysecache — samme fil skal aldri OCR-es to ganger               #
# ------------------------------------------------------------------ #
# Nøkkel er SHA-256 av filinnholdet (+ sidegrense): spørsmål nr. 2, 3,
# 10 på samme dokument gjenbruker hele analysen øyeblikkelig.

_analyse_cache = OrderedDict()
_analyse_cache_las = threading.Lock()

# R58: er OCR-oppvarmingen (R54) i gang, holder den motorlåsen mens den
# laster modellene. En forespørsel som kom inn i det vinduet ble stående
# og vente — målt 28,5 sekunder, uten at klienten fikk vite hvorfor.
# Da er et ærlig «prøv igjen om litt» langt bedre enn en taus henging,
# og det er samme mønster som Borealis alt bruker mens den laster.
_oppvarming = {"pagaar": False}
ANALYSE_CACHE_MAKS = int(os.environ.get("ANALYSE_CACHE_MAKS", "32"))


def analyser_med_cache(filnavn: str, data: bytes, ocr_maks_sider=None,
                       les_strekkoder: bool = True) -> dict:
    # R55: strekkodevalget er DEL AV nøkkelen. Ellers ville en
    # forespørsel som hoppet over strekkoder kunne servere sitt tomme
    # resultat videre til en som faktisk ba om dem.
    nokkel = (hashlib.sha256(data).hexdigest()
              + f":{ocr_maks_sider}:{int(les_strekkoder)}")
    with _analyse_cache_las:
        if nokkel in _analyse_cache:
            _analyse_cache.move_to_end(nokkel)
            return {**_analyse_cache[nokkel],
                    "filnavn": filnavn, "fra_cache": True}
    resultat = analyser_bytes(filnavn, data, ocr_maks_sider, les_strekkoder)
    if resultat.get("ok"):
        with _analyse_cache_las:
            _analyse_cache[nokkel] = resultat
            while len(_analyse_cache) > ANALYSE_CACHE_MAKS:
                _analyse_cache.popitem(last=False)
    return {**resultat, "fra_cache": False}


def dokumentdato_av(tekst: str, ocr_brukt: bool = False) -> dict:
    """Dokumentets egen dato utledet fra ren tekst (uten PDF-metadata).
    Brukes der vi bare har teksten: DOCX/TXT og /dokument-stien."""
    return finn_dokumentdato(
        sett_dato_roller(klassifiser_datoer(tekst or "")), ocr_brukt=ocr_brukt)


def _pdf_metadata_datoer(meta: dict) -> list:
    """Datoer fra PDF-filens egne metadata (opprettet/endret) — usynlige
    i dokumentteksten, men ofte selve «utstedelsesdatoen» teknisk sett."""
    ut = []
    for nokkel, dtype in (("creationDate", "pdf_opprettet"),
                          ("modDate", "pdf_endret")):
        verdi = (meta or {}).get(nokkel) or ""
        m = re.match(r"D:(\d{4})(\d{2})(\d{2})", verdi)
        if not m:
            continue
        y, mnd, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= mnd <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100):
            continue
        ut.append({
            "dato": f"{d:02d}.{mnd:02d}.{y}",
            "raatekst": verdi[:18],
            "type": dtype,
            "etikett": None,
            "begrunnelse": "fra PDF-filens metadata (ikke synlig i dokumentteksten)",
            "side": None,
            "kontekst": "PDF-metadata",
            "i_lopende_tekst": False,
        })
    return ut


# ------------------------------------------------------------------ #
#  Analyse                                                            #
# ------------------------------------------------------------------ #

def analyser_bytes(filnavn: str, data: bytes, ocr_maks_sider: int = None,
                   les_strekkoder: bool = True) -> dict:
    """Analyserer PDF-bytes (normaliser_fil har alt konvertert bilder).

    les_strekkoder=False hopper over strekkode-/QR-skanningen. Den koster
    ~0,2 s per side og er bortkastet på dokumenter som ikke har koder;
    styres per forespørsel med multipart-feltet strekkoder=nei.
    """
    if not data:
        return {"ok": False, "feil": "Tom fil"}
    try:
        import fitz
    except ImportError:
        return {"ok": False, "feil": "PyMuPDF (fitz) ikke installert"}
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        return {"ok": False, "feil": f"Ugyldig/korrupt PDF: {exc}"}

    pdf_meta = doc.metadata or {}
    sider = []
    tekster = []
    total_tekst = 0
    for i, side in enumerate(doc):
        tekst = side.get_text() or ""
        tekster.append(tekst)
        total_tekst += len(tekst.strip())
        sider.append({"side_nummer": i, "tegn": len(tekst),
                      "felter": utvid_entiteter(tekst, {})})
    doc.close()
    if len(tekster) > 1:
        full_tekst = "\n".join(f"[Side {i + 1} av {len(tekster)}]\n{t}"
                               for i, t in enumerate(tekster)).strip()
    else:
        full_tekst = "\n".join(tekster).strip()

    # Aggreger på tvers av sider (første ikke-tomme verdi per felt)
    felter = {}
    for s in sider:
        for k, v in s["felter"].items():
            if k not in felter and v not in (None, ""):
                felter[k] = v

    # Skannet bilde uten tekstlag → kjør OCR automatisk.
    # R55: OCR kjøres FØR strekkodelesingen, slik at den kan gjenbruke
    # sidebildene OCR allerede har rendret. Før dette rendret de to
    # stegene hver sin kopi av de samme sidene (målt 0,19 s per A4-side
    # i ren dobbeltjobb).
    ocr_res = None
    if total_tekst < 20:
        try:
            ocr_res = ocr_pdf_bytes(data, ocr_maks_sider)
        except Exception as exc:
            return {"ok": False, "feil": f"OCR feilet: {exc}"}

    strekkode_rapport = {}
    strekkoder = les_strekkoder_bytes(
        data, sider=ocr_res["_sidebilder"] if ocr_res else None,
        rapport=strekkode_rapport
    ) if les_strekkoder else []
    # Ble ikke alle sidene skannet, skal det SIES. Går OCR-veien, er
    # sidetallet fra rendrede sider — det ekte totalen er dokumentets.
    if ocr_res is not None and strekkode_rapport:
        strekkode_rapport["sider_totalt"] = ocr_res.get(
            "sider_totalt", strekkode_rapport.get("sider_totalt", 0))
        strekkode_rapport["avkortet"] = (
            strekkode_rapport.get("sider_skannet", 0)
            < strekkode_rapport["sider_totalt"])
    strekkode_advarsel = None
    if strekkode_rapport.get("avkortet"):
        strekkode_advarsel = (
            f"strekkoder: kun {strekkode_rapport['sider_skannet']} av "
            f"{strekkode_rapport['sider_totalt']} sider ble skannet — "
            "koder på de siste sidene (typisk arkiv-/returslipp) kan "
            "mangle")

    if ocr_res is not None:
        ocr_tekst = ocr_res["tekst"]
        ocr_advarsel = None
        if ocr_res.get("tomme_sider"):
            hvilke = ", ".join(str(s) for s in ocr_res["tomme_sider"])
            ocr_advarsel = (f"side {hvilke}: (nesten) tom — OCR hoppet "
                            "over for å ikke lese støy som tekst")
        if ocr_res["sider_lest"] < ocr_res["sider_totalt"]:
            grense_tekst = (
                f"OCR leste {ocr_res['sider_lest']} av {ocr_res['sider_totalt']} sider "
                f"(synkron grense — øk med felt maks_sider inntil {OCR_TAK_SIDER}, "
                "eller bruk POST /jobb for hele dokumentet)")
            ocr_advarsel = (f"{ocr_advarsel} — {grense_tekst}"
                            if ocr_advarsel else grense_tekst)
        # Ærlig bildekvalitet: uskarpt/mørkt/utbrent/lite bilde sies RETT UT
        # («ta et nytt bilde») i stedet for å levere stille søppel-OCR.
        kvalitet = (ocr_res.get("forbehandling") or {}).get("kvalitet") or {}
        if kvalitet.get("advarsler"):
            kv_tekst = "bildekvalitet: " + "; ".join(kvalitet["advarsler"])
            ocr_advarsel = (f"{ocr_advarsel} — {kv_tekst}"
                            if ocr_advarsel else kv_tekst)
        if strekkode_advarsel:
            ocr_advarsel = (f"{ocr_advarsel} — {strekkode_advarsel}"
                            if ocr_advarsel else strekkode_advarsel)
        if len(ocr_tekst.strip()) < 5:
            melding = ("Fant ingen lesbar tekst i dokumentet — selv med OCR. "
                       "Men fant strekkoder/QR-koder (se 'strekkoder')."
                       if strekkoder else
                       "Fant ingen lesbar tekst i dokumentet — selv med OCR. "
                       "(Rene bilder uten skrift gir ingen tekst.)")
            # Klarte nesten ikke å lese noe → send til korreksjon
            sendt = _kanskje_send_til_gjennomgang(filnavn, data, ocr_res, {})
            return {
                "ok": True,
                "filnavn": filnavn,
                "antall_sider": len(sider),
                "trenger_ocr": True,
                "ocr_brukt": True,
                "felter": {},
                "strekkoder": strekkoder,
                "melding": melding,
                "tekst": ocr_tekst.strip(),
                "antall_tegn": len(ocr_tekst.strip()),
                "ocr_motorer": ocr_res["motorer"],
                "ocr_sider_lest": ocr_res["sider_lest"],
                "ocr_sider_totalt": ocr_res["sider_totalt"],
                "ocr_konfidens": ocr_res.get("konfidens"),
                "bildekvalitet": ocr_res.get("forbehandling"),
                "sendt_til_gjennomgang": sendt,
                "advarsel": ocr_advarsel,
            }
        # Datoklassifisering + kryssjekk mot håndskrevne regioner
        datoer_detaljert = (klassifiser_datoer(ocr_tekst)
                            + _pdf_metadata_datoer(pdf_meta))
        for dd in datoer_detaljert:
            if any(dd["raatekst"] in h for h in ocr_res["handskrift"]):
                dd["skrevet_for_hand"] = True
                dd["begrunnelse"] += "; står i en håndskrevet region"
        # Rolle på hver dato + dokumentets EGEN dato. ocr_brukt=True her,
        # så PDF-metadata nedgraderes: på et skannet dokument er
        # opprettelsesdatoen skannedatoen, ikke dokumentets dato.
        sett_dato_roller(datoer_detaljert)
        dokumentdato = finn_dokumentdato(datoer_detaljert, ocr_brukt=True)
        felter_ut = utvid_entiteter(ocr_tekst, {})
        # Leste vi dette dårlig? → automatisk til Label Studio (bakgrunn)
        sendt = _kanskje_send_til_gjennomgang(filnavn, data, ocr_res, felter_ut)
        return {
            "ok": True,
            "filnavn": filnavn,
            "antall_sider": len(sider),
            "trenger_ocr": False,
            "ocr_brukt": True,
            "kilde": "regionocr+deterministisk",
            # Internt (understrek-konvensjonen): grunnlaget for
            # koordinater per funn. Slanke {boks, tekst} per side —
            # JSON-vennlig, men skal ikke ut i svar uten at klienten ba
            # om koordinater.
            "_sider_regioner": ocr_res.get("_sider_regioner") or [],
            "felter": felter_ut,
            "datoer": finn_alle_datoer(ocr_tekst),
            "datoer_detaljert": datoer_detaljert,
            "dokumentdato": dokumentdato,
            "strekkoder": strekkoder,
            "tekst": ocr_tekst.strip(),
            "antall_tegn": len(ocr_tekst.strip()),
            "ocr_motorer": ocr_res["motorer"],
            "handskrift": ocr_res["handskrift"],
            "ocr_sider_lest": ocr_res["sider_lest"],
            "ocr_sider_totalt": ocr_res["sider_totalt"],
            "ocr_konfidens": ocr_res.get("konfidens"),
            "bildekvalitet": ocr_res.get("forbehandling"),
            "sendt_til_gjennomgang": sendt,
            "advarsel": ocr_advarsel,
        }

    tekstlag_datoer = sett_dato_roller(
        klassifiser_datoer(full_tekst) + _pdf_metadata_datoer(pdf_meta))
    return {
        "ok": True,
        "filnavn": filnavn,
        "antall_sider": len(sider),
        "trenger_ocr": False,
        "ocr_brukt": False,
        "kilde": "deterministisk_tekstlag",
        "felter": felter,
        "datoer": finn_alle_datoer(full_tekst),
        "datoer_detaljert": tekstlag_datoer,
        # Tekstlag = digitalt født dokument: da er PDF-metadata filens
        # ekte opprettelsesdato, ikke en skannedato (ocr_brukt=False)
        "dokumentdato": finn_dokumentdato(tekstlag_datoer, ocr_brukt=False),
        "strekkoder": strekkoder,
        "advarsel": strekkode_advarsel,
        "per_side": sider,
        "tekst": full_tekst,
        "antall_tegn": len(full_tekst),
    }


# ------------------------------------------------------------------ #
#  Borealis (fritt spørsmål/svar) — lastes i bakgrunnen ved oppstart  #
# ------------------------------------------------------------------ #

BOREALIS_STI = os.path.join(ROT, "modeller", "borealis")
BOREALIS_GGUF_MAPPE = os.path.join(ROT, "modeller", "borealis-gguf")
# R51: kontekstvinduet bestemmer hvor stor KV-hurtigbuffer llama.cpp
# reserverer på GPU-en — og den reservasjonen er permanent, ikke etter
# behov. Målt: 12288 la beslag på ~2,5 GiB og etterlot 746 MiB ledig på
# et 8 GB-kort, som gjorde at OCR ikke fikk plass og falt til CPU (17 s
# per side). 8192 frigjør ~1 GiB uten å koste noe: dokumentteksten som
# faktisk sendes inn er uansett kappet på MAKS_LLM_TEGN (12000 tegn ≈
# 4000 tokens), så budsjettet er mer enn dobbelt så stort som behovet.
# 8192 KREVER for mye VRAM sammen med OCR på et 8 GB-kort: llama.cpp
# segfaulter under KV-cache-allokering (full-size SWA-cache). 4096 er
# verifisert trygt her (og romslig — LLM-input er uansett kappet på
# MAKS_LLM_TEGN). Øk bare hvis du frigjør GPU (færre GPU-lag / mindre OCR).
BOREALIS_KONTEKST = int(os.environ.get("BOREALIS_KONTEKST", "4096"))


def _finn_gguf() -> str:
    """Modellbytte skal være «legg filen i mappen og restart»: bruk
    BOREALIS_GGUF-miljøvariabelen hvis satt, ellers den nyeste
    .gguf-filen i modeller/borealis-gguf (mmproj-filer er
    synsprojektorer, ikke språkmodeller — hoppes over)."""
    valgt = os.environ.get("BOREALIS_GGUF", "").strip()
    if valgt:
        return valgt if os.path.isabs(valgt) else os.path.join(
            BOREALIS_GGUF_MAPPE, valgt)
    try:
        kandidater = [os.path.join(BOREALIS_GGUF_MAPPE, n)
                      for n in os.listdir(BOREALIS_GGUF_MAPPE)
                      if n.lower().endswith(".gguf")
                      and not n.lower().startswith("mmproj")]
    except OSError:
        return ""
    return max(kandidater, key=os.path.getmtime) if kandidater else ""


BOREALIS_GGUF_STI = _finn_gguf()
_borealis = {"status": "ikke_startet", "motor": "", "modellfil": "",
             "llama": None, "tok": None, "model": None, "feil": None}
_borealis_las = threading.Lock()   # GPU-en tar én generering om gangen

# R51: OCR-motorene og språkmodellen deler ett fysisk kort. Kjører de
# samtidig, konkurrerer de om VRAM og BEGGE blir tregere (målt: modellen
# alene 3,3 s → 18,5 s parallelt med OCR). Denne låsen eies av
# delt.region_ocr og tas her rundt generering, slik at GPU-arbeid
# serialiseres på tvers av de to. Ligger OCR på CPU, tar OCR-siden den
# aldri — og da kan modellen svare parallelt uten å vente.
try:
    from delt.region_ocr import GPU_LAS as _gpu_las
except Exception:                      # region_ocr utilgjengelig
    _gpu_las = threading.RLock()


def _last_borealis_bakgrunn():
    """Laster Borealis i en bakgrunnstråd. GGUF Q8 via llama.cpp
    foretrekkes (målt: ~3 s lasting og ~34 tok/s mot ~90 s og ~12
    tok/s med transformers+bitsandbytes — og Q8 er mer presis enn
    nf4). transformers beholdes som generell fallback."""
    try:
        _borealis["status"] = "laster"
        gguf_sti = _finn_gguf()
        if gguf_sti and os.path.isfile(gguf_sti):
            try:
                # llama.dll trenger CUDA-DLL-ene som følger med torch
                import torch as _torch
                os.add_dll_directory(
                    os.path.join(os.path.dirname(_torch.__file__), "lib"))
                from llama_cpp import Llama
                # n_gpu_layers=-1 legger alt på GPU hvis det er plass;
                # BOREALIS_GPU_LAG lar deg dele en STØRRE modell (12B/27B)
                # mellom GPU og RAM på et mindre kort (f.eks. 40)
                gpu_lag = int(os.environ.get("BOREALIS_GPU_LAG", "-1"))
                llm = Llama(model_path=gguf_sti, n_gpu_layers=gpu_lag,
                            n_ctx=BOREALIS_KONTEKST, verbose=False)
                navn = os.path.basename(gguf_sti)
                _borealis.update(llama=llm, status="klar",
                                 motor="llama_cpp", modellfil=navn)
                print(f"  Borealis ({navn}, llama.cpp/CUDA) klar — POST /spor er klar.")
                return
            except Exception as exc:
                print(f"  GGUF-backend feilet ({exc}) — prøver transformers.")
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
        tok = AutoTokenizer.from_pretrained(BOREALIS_STI)
        kvant = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
        # sdpa er 10-30 % raskere prefill enn eager (målt i bransjen);
        # eager beholdes som fallback for eldre transformers/modeller
        try:
            model = AutoModelForCausalLM.from_pretrained(
                BOREALIS_STI,
                quantization_config=kvant,
                device_map="cuda:0",
                attn_implementation="sdpa",
            )
        except Exception:
            model = AutoModelForCausalLM.from_pretrained(
                BOREALIS_STI,
                quantization_config=kvant,
                device_map="cuda:0",
                attn_implementation="eager",
            )
        model.eval()
        _borealis.update(tok=tok, model=model, status="klar",
                         motor="transformers_nf4")
        print("  Borealis lastet (transformers) — POST /spor er klar.")
    except Exception as exc:
        _borealis.update(status="feil", feil=str(exc))
        print(f"  Borealis kunne ikke lastes: {exc}")


# Ankerpar som avgrenser den KLIPPBARE dokumentdelen i promptene våre
_PROMPT_ANKRE = [("\nDokument:\n", "\n\nSpørsmål:"),
                 ("\nDokument:\n", "\n\nJSON-mal:"),
                 ("OCR-tekst:\n", "\n\nKorrigert tekst:")]


def _tilpass_kontekst(llm, prompt: str, maks_tokens: int) -> str:
    """Klipper dokumentdelen av prompten så den FAKTISK får plass i
    kontekstvinduet — målt i tokens, ikke tegn (OCR-tekst og tallrike
    dokumenter tokeniserer 2–3× tettere enn normaltekst, så tegnbaserte
    grenser er upålitelige). Binærsøk på dokumentlengden; kuttet
    merkes eksplisitt i prompten."""
    # Minst 256 tokens til dokumentet uansett, så en feilkonfigurert
    # MAKS_SVAR_TOKENS ikke gir et negativt budsjett (og en prompt som
    # likevel sprenger vinduet)
    budsjett = max(BOREALIS_KONTEKST - maks_tokens - 64, 256)

    def antall(p: str) -> int:
        return len(llm.tokenize(p.encode("utf-8"), add_bos=True, special=True))

    if antall(prompt) <= budsjett:
        return prompt
    for hode_anker, hale_anker in _PROMPT_ANKRE:
        i = prompt.find(hode_anker)
        j = prompt.rfind(hale_anker)
        if i == -1 or j <= i:
            continue
        hode = prompt[:i + len(hode_anker)]
        dok = prompt[i + len(hode_anker):j]
        hale = prompt[j:]
        merke = "\n[DOKUMENTET ER AVKORTET HER pga. kontekstvinduet]"
        lav, hoy = 0, len(dok)
        while lav < hoy:
            midt = (lav + hoy + 1) // 2
            if antall(hode + dok[:midt] + merke + hale) <= budsjett:
                lav = midt
            else:
                hoy = midt - 1
        return hode + dok[:lav] + merke + hale
    # Ukjent promptstruktur: klipp bakfra, men behold slutten (spørsmålet)
    return prompt[:len(prompt) // 2] + "\n[AVKORTET]\n" + prompt[-800:]


def _borealis_generer(prompt: str, maks_tokens: int = 256) -> tuple:
    """Én deterministisk generering med Borealis (GPU-lås rundt kallet).
    Returnerer (tekst, avkortet) — avkortet=True betyr at svaret traff
    tokentaket og KAN være ufullstendig. Det skal aldri skjules."""
    if _borealis["motor"].startswith("llama_cpp"):
        llm = _borealis["llama"]
        prompt = _tilpass_kontekst(llm, prompt, maks_tokens)
        with _borealis_las, _gpu_las:
            ut = llm.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=maks_tokens, temperature=0.0)
        valg = ut["choices"][0]
        return ((valg["message"]["content"] or "").strip(),
                valg.get("finish_reason") == "length")
    import torch
    tok, model = _borealis["tok"], _borealis["model"]
    meldinger = [{"role": "user", "content": prompt}]
    inn = tok.apply_chat_template(
        meldinger, add_generation_prompt=True,
        return_tensors="pt", return_dict=True,
    ).to("cuda:0")
    with _borealis_las, _gpu_las, torch.no_grad():
        ut = model.generate(
            **inn, max_new_tokens=maks_tokens, do_sample=False,
            pad_token_id=tok.eos_token_id,
        )
    ut_tokens = ut[0][inn["input_ids"].shape[-1]:]
    tekst = tok.decode(ut_tokens, skip_special_tokens=True).strip()
    return tekst, len(ut_tokens) >= maks_tokens


EGNE_REGLER_STI = prompter.regelfil("egne_regler.txt")

# R8.1: regelfilen er en fritekstkanal inn i prompten — uten vern er
# den en injeksjonsvei. Linjer som prøver å overstyre kjerneregler
# eller tallbehandling AVVISES av kode (ikke prompt).
_REGEL_AVVIS = re.compile(
    r"(?i)\b(ignorer|glem|se bort|overstyr|opphev|omgå|"
    r"regn(e|et)?|summ?er(e|te)?|beregn(e)?|adder(e)?|"
    r"tallvakt(en)?|gjett(e)?|dikt(e)?|finn på|hallusiner)\b"
    r"|regel\s*r?\d|forrang|systeminstruks")
_MAKS_EGNE_REGLER = 20
_MAKS_REGEL_LENGDE = 200


def _egne_regler() -> str:
    """R8: brukerens egne stil-/formatregler — leses PER forespørsel,
    endringer virker uten omstart. # = kommentar.

    R8.1-vern (kode, ikke løfte): linjer som matcher overstyrings-/
    regnemønstre avvises og logges; maks 20 regler à 200 tegn; og
    reglene plasseres FØR kjernereglene i prompten slik at kjerne-
    reglene alltid får siste ord. Dette er skadebegrensning — den
    harde garantien mot talljuks er fortsatt tallvakten (R3, kode)."""
    try:
        # utf-8-sig: Notepad lagrer med BOM, og uten -sig ble BOM-en
        # hengende foran «#» på linje én — kommentarfilteret slapp den
        # forbi, og en rad likhetstegn havnet i prompten som en «regel»
        with open(EGNE_REGLER_STI, encoding="utf-8-sig") as f:
            linjer = [l.strip() for l in f
                      if l.strip() and not l.strip().startswith("#")]
    except (FileNotFoundError, OSError):
        return ""
    godkjente = []
    for linje in linjer[:_MAKS_EGNE_REGLER]:
        if len(linje) > _MAKS_REGEL_LENGDE or _REGEL_AVVIS.search(linje):
            print(f"  egne_regler: AVVIST (R8.1): {linje[:70]!r}")
            continue
        godkjente.append(linje)
    if not godkjente:
        return ""
    return (prompter.avsnitt("spor.egne_regler_innledning")
            + "\n".join(f"- {l}" for l in godkjente) + "\n")


def spor_borealis(tekst: str, sporsmal: str, fra_ocr: bool = False) -> str:
    """Stiller ett spørsmål om dokumentteksten (dokumentet er DATA,
    ikke instruksjoner). Med fra_ocr=True får modellen lov til å tolke
    åpenbare OCR-lesefeil ut fra sammenhengen — men ikke dikte."""
    # R8.1: brukerens preferanser plasseres FØR kjernereglene — for
    # språkmodeller vinner senere instruksjoner, så kjernereglene får
    # alltid siste ord uansett hva regelfilen inneholder. Rekkefølgen
    # ligger i selve blokka; se regler/prompter.md.
    prompt = prompter.hent(
        "spor.dokumentsporsmal",
        egne_regler=_egne_regler(),
        ocr_merknad=prompter.avsnitt("spor.ocr_merknad") if fra_ocr else "",
        dokument=tekst[:MAKS_LLM_TEGN + 2000],
        sporsmal=sporsmal)
    svar, avkortet = _borealis_generer(prompt, MAKS_SVAR_TOKENS)
    # Modellen gjentar av og til ledeteksten «Svar:» — fjern den
    if svar.lower().startswith("svar:"):
        svar = svar[5:].strip()
    return svar, avkortet


def dato_tokens(kilde: str) -> set:
    """Kompaktformen av hver dato den deterministiske parseren finner i
    kilden.

    R53: tallvakten krever EKSAKT token-treff (med vilje — «1777» skal
    ikke slippe gjennom som delstreng av «11777»). En normalisert dato
    er derimot ikke et nytt tall: «12.06.2026» er den samme datoen som
    «12 06 2026» i dokumentet, bare skrevet på standardform. Uten dette
    ble en korrekt lest dato avvist som «tall som ikke står i
    dokumentet» — to sikkerhetsmekanismer som slo hverandre i hjel.
    """
    try:
        return {re.sub(r"[ ., \xa0]", "", d) for d in finn_alle_datoer(kilde)}
    except Exception:
        return set()


def uverifiserte_tall(svar: str, kilde: str, ekstra_tokens: set = None) -> list:
    """Tallvakt: finner tall i svaret som IKKE står ordrett i kilden.

    Modellen har regler mot å regne selv, men språkmodeller kan likevel
    finne på å summere («SUM 268,00» + mva → «296,71»). Hvert tall på
    3+ sifre i svaret må finnes igjen i kildeteksten (sammenlignet uten
    mellomrom/punktum, så «41 28 89 03» matcher «41288903»). Returnerer
    listen av tall som mangler — tom liste = alt verifisert."""
    # VIKTIG token-vakt: (1) eksakt token-match, ikke delstreng - ellers
    # ville "1777" passert som delstreng av "11777"; (2) monsteret tar
    # med komma-desimaler sa "268,00" ikke splittes til "268"+"00" og
    # slipper endrede orebelop gjennom. Gruppering ("41 28 89 03") og
    # NBSP fjernes symmetrisk i bade svar og kilde.
    monster = r"\d[\d . ]*\d(?:,\d+)?|\d(?:,\d+)?"
    rens = lambda t: re.sub(r"[ ., ]", "", t)
    kilde_tokens = {rens(t) for t in re.findall(monster, kilde)}
    if ekstra_tokens:
        kilde_tokens |= ekstra_tokens
    mangler = []
    for tall in re.findall(monster, svar):
        raa = tall.strip()
        kompakt = rens(raa)
        if len(kompakt) < 3 or kompakt in kilde_tokens:
            continue
        # R56: «23,00» og «23» er nøyaktig samme beløp. På matriseskrift
        # mister OCR ofte ørene — «+FORHÅND NOK 23,00» ble lest «#FORHAND
        # NOK 23 Q» — og da falt en korrekt lest verdi på at kilden bare
        # inneholdt heltallet. Vakten var dessuten inkonsekvent: «23»
        # alene slipper uansett gjennom (under tresifergrensen), mens
        # «23,00» ble avvist.
        # Gjelder KUN når ørene er null. «23,50» må fortsatt stå ordrett
        # i kilden — ellers ville et endret ørebeløp sluppet forbi.
        uten_ore = re.sub(r"[,.](?:00|-)$", "", raa)
        if uten_ore != raa and rens(uten_ore) in kilde_tokens:
            continue
        mangler.append(raa)
    return mangler


# R48: eksklusjoner i spørsmålet («uten adresse») håndheves av kode —
# små modeller er notorisk svake på negasjoner, så vi SJEKKER svaret
# med de deterministiske detektorene i stedet for å stole på modellen
_EKSKLUSJONS_DETEKTORER = {
    "adresse": lambda s: bool(re.search(r"\b\d{4}\s+[A-ZÆØÅ][a-zæøå]", s))
                          or bool(finn_adresser(s)),
    "telefon": lambda s: bool(finn_alle_telefoner(s)),
    "epost": lambda s: bool(finn_alle_eposter(s)),
    "dato": lambda s: bool(finn_alle_datoer(s)),
    "fødselsnummer": lambda s: bool(finn_alle_fodselsnummer(s)),
    "tall": lambda s: bool(re.search(r"\d", s)),
}


def eksklusjoner_brutt(sporsmal: str, svar: str) -> list:
    """Hvilke «uten X»-begrensninger i spørsmålet bryter svaret?
    Generell: matcher uten/ikke med/foruten + kjente entitetstyper
    som vi kan detektere deterministisk."""
    brutt = []
    for treff in re.finditer(
            r"(?i)\b(?:uten|ikke\s+med|foruten)\s+([a-zæøåA-ZÆØÅ]+)",
            sporsmal):
        ordet = treff.group(1).lower()
        for nokkel, detektor in _EKSKLUSJONS_DETEKTORER.items():
            stamme = min(len(nokkel), len(ordet), 4)
            if nokkel[:stamme] == ordet[:stamme] and detektor(svar) \
                    and nokkel not in brutt:
                brutt.append(nokkel)
    return brutt


def _parse_json_svar(tekst: str):
    """Henter JSON-objektet ut av et modellsvar (tåler ```-gjerder og
    tekst rundt). None hvis ingen gyldig JSON finnes."""
    tekst = re.sub(r"```(?:json)?", "", tekst)
    start, slutt = tekst.find("{"), tekst.rfind("}")
    if start == -1 or slutt <= start:
        return None
    try:
        return json.loads(tekst[start:slutt + 1])
    except json.JSONDecodeError:
        return None


def rens_skjemasvar(mal, svar, dok_tekst: str):
    """Tvinger modellens utfylling inn i malens struktur og validerer
    hvert felt med KODE (skjemautfylling er der modeller oftest setter
    riktige verdier i feil felt):
      * struktur-lås: kun malens nøkler beholdes, manglende → ""
      * tallvakt per felt: tall som ikke står i dokumentet → tømmes
      * navnedrevne typesjekker (generelle, styrt av feltnavnet):
        beløp/pris/sum/grunnlag avviser prosentsatser;
        organisasjonsnummer må bestå mod11; telefon må ha 8 sifre
    Returnerer (renset_skjema, liste_med_avvik)."""
    avvik = []
    # Beregnes én gang for hele skjemaet, ikke per felt — parsingen går
    # over hele dokumentteksten og ville ellers kjørt for hvert felt.
    kjente_datoer = dato_tokens(dok_tekst)

    def _rekurs(m, s, sti):
        if isinstance(m, dict):
            return {k: _rekurs(v, s.get(k) if isinstance(s, dict) else None,
                               f"{sti}.{k}" if sti else k)
                    for k, v in m.items()}
        if isinstance(m, list):
            kilde = s if isinstance(s, list) else []
            malelement = m[0] if m else ""
            return [_rekurs(malelement, e, f"{sti}[{i}]")
                    for i, e in enumerate(kilde)]
        verdi = "" if s is None or isinstance(s, (dict, list)) else str(s).strip()
        if not verdi:
            return ""
        mangler = uverifiserte_tall(verdi, dok_tekst, kjente_datoer)
        if mangler:
            avvik.append(f"{sti}: «{verdi}» inneholder tall som ikke står "
                         "i dokumentet — feltet er tømt")
            return ""
        navn = sti.lower()
        if re.search(r"bel[øo]p|pris|sum|grunnlag", navn):
            if "%" in verdi:
                avvik.append(f"{sti}: prosentsats («{verdi}») hører ikke "
                             "hjemme i et beløpsfelt — feltet er tømt")
                return ""
            if not re.search(r"\d", verdi):
                avvik.append(f"{sti}: «{verdi}» inneholder ingen tall og kan "
                             "ikke være en pris/et beløp — feltet er tømt")
                return ""
        if "rabatt" in navn and "%" in verdi:
            avvik.append(f"{sti}: «{verdi}» er en prosentsats i rabattfeltet "
                         "— kontroller om dette egentlig er mva-satsen")
        if "organisasjonsnummer" in navn:
            sifre = re.sub(r"\D", "", verdi)
            if len(sifre) < 9 or not er_gyldig_orgnr(sifre[:9]):
                avvik.append(f"{sti}: «{verdi}» består ikke mod11-kontrollen "
                             "for organisasjonsnummer — feltet er tømt")
                return ""
        if "telefon" in navn:
            sifre = re.sub(r"\D", "", verdi)
            if sifre.startswith("47") and len(sifre) == 10:
                sifre = sifre[2:]
            if len(sifre) != 8:
                avvik.append(f"{sti}: «{verdi}» er ikke et gyldig norsk "
                             "telefonnummer — feltet er tømt")
                return ""
        # R53: fødselsnummer var IKKE validert, selv om orgnr og telefon
        # var det og er_gyldig_fnr fantes i delt/tekstuttrekk. På en
        # taxikvittering havnet løyvenummeret «N02272» i fnr-feltet og
        # kom uimotsagt gjennom — i et NAV-system er nettopp fnr det
        # feltet som minst av alt skal kunne fylles med noe tilfeldig.
        if re.search(r"f[øo]dselsnummer|fnr\b|personnummer", navn):
            sifre = re.sub(r"\D", "", verdi)
            if not er_gyldig_fnr(sifre):
                avvik.append(f"{sti}: «{verdi}» er ikke et gyldig norsk "
                             "fødselsnummer (11 sifre med mod11-kontroll) "
                             "— feltet er tømt")
                return ""
            verdi = sifre
        # R53: datofelter var heller ikke validert. Feilleste datoer som
        # «1970 12 06 2026» (OCR leste «DATO» som «1970») ble stående som
        # om de var en dato.
        if re.search(r"\bdato\b|dato$|_dato|dato_", navn):
            normalisert = finn_dato(verdi)
            if normalisert is None:
                avvik.append(f"{sti}: «{verdi}» er ikke en gjenkjennelig "
                             "dato — feltet er tømt")
                return ""
            if normalisert != verdi:
                avvik.append(f"{sti}: «{verdi}» ble normalisert til "
                             f"«{normalisert}»")
            verdi = normalisert
        return verdi

    renset = _rekurs(mal, svar, "")

    # Aritmetisk konsistens (generell, feltnavndrevet): der en gruppe
    # har enhetspris/antall/sum, må regnestykket gå opp — ellers er en
    # verdi sannsynligvis plassert i feil felt
    def _tall(v):
        # Strip ASCII space, NBSP (\xa0) og smal NBSP ( ) — norske
        # belop bruker ofte disse som tusenskille; ellers slo den
        # aritmetiske vakten seg av nettopp pa store belop.
        try:
            return float(re.sub(r"[ \xa0 .]", "", str(v))
                         .replace(",", "."))
        except (ValueError, AttributeError):
            return None

    def _rabatt_er_null(v) -> bool:
        # Kun en FRAVÆRENDE eller eksplisitt null rabatt teller som null.
        # En uparselig rabatt (f.eks. «10 %») er IKKE null — da skal vi
        # ikke auto-rette, for premisset «rabatt=0» ville vært falskt.
        if v is None or str(v).strip() == "":
            return True
        t = _tall(v)
        return t is not None and t == 0.0

    def _konsistens(node, sti):
        if not isinstance(node, dict):
            return
        lav = {k.lower(): v for k, v in node.items()}
        e, a, s = (_tall(lav.get("enhetspris")), _tall(lav.get("antall")),
                   _tall(lav.get("sum")))
        if e is not None and a is not None and s is not None and s > 0:
            rabatt = _tall(lav.get("rabatt"))
            rabatt_null = _rabatt_er_null(lav.get("rabatt"))
            toleranse = max(0.01 * s, 0.5)
            if abs(e * a - (rabatt or 0.0) - s) > toleranse:
                if a == 1 and rabatt_null:
                    # Matematisk entydig: ved antall 1 uten rabatt ER
                    # enhetsprisen lik summen — rettes av kode, deklarert
                    e_nokkel = next((k for k in node
                                     if k.lower() == "enhetspris"), None)
                    s_nokkel = next((k for k in node
                                     if k.lower() == "sum"), None)
                    if e_nokkel and s_nokkel:
                        gammel = node[e_nokkel]
                        node[e_nokkel] = node[s_nokkel]
                        e = s
                        avvik.append(
                            f"{sti}: enhetspris «{gammel}» RETTET AV KODE "
                            f"til «{node[s_nokkel]}» (antall=1, rabatt=0 → "
                            "enhetspris er per definisjon lik sum)")
                else:
                    avvik.append(
                        f"{sti}: enhetspris×antall−rabatt ({e}×{a}−{rabatt}) "
                        f"stemmer ikke med sum ({s}) — en verdi står "
                        "sannsynligvis i feil felt, kontroller mot dokumentet")
            # Uparselig rabatt (f.eks. prosentsats) mens regnestykket går
            # opp UTEN rabatt → rabatten er per definisjon null
            r_nokkel = next((k for k in node if k.lower() == "rabatt"), None)
            if (r_nokkel is not None and rabatt is None
                    and str(node.get(r_nokkel, "")).strip()
                    and abs(e * a - s) <= toleranse):
                gammel = node[r_nokkel]
                node[r_nokkel] = "0,00"
                avvik.append(
                    f"{sti}: rabatt «{gammel}» RETTET AV KODE til «0,00» "
                    "(enhetspris×antall stemmer med sum uten rabatt)")
        for k, v in node.items():
            _konsistens(v, f"{sti}.{k}" if sti else k)

    _konsistens(renset, "")
    return renset, avvik


def _reparer_ocr_artefakter(tekst: str) -> str:
    """Deterministiske reparasjoner av linje-gjennom-bokstav-artefakter.
    «#» og «ł» finnes ikke i norsk tekst — de oppstår når en rutelinje
    skjærer gjennom en bokstav i samme høyde som bokstavens tverrstrek
    (H → «#», tt → «#», t → «ł»). Mekanisk feil → mekanisk fiks; språk-
    modellen (som nekter å røre dem) trengs ikke til dette."""
    tekst = re.sub(r"ł", "t", tekst)
    tekst = re.sub(r"(?<=[a-zæøåA-ZÆØÅ])#(?=[a-zæøå])", "t", tekst)
    tekst = re.sub(r"(?:^|(?<=[\s(«\"']))#(?=[a-zæøå]{2})", "H", tekst,
                   flags=re.MULTILINE)
    return tekst


def korriger_borealis(ocr_tekst: str, regioner: list | None = None) -> str:
    """Retter OCR-feil ut fra SETNINGSSAMMENHENGEN, i TO pass:
    1) korreksjon — med kjente OCR-artefaktmønstre og (når vi har dem)
       regionene som ble lest med lav konfidens, så modellen vet nøyaktig
       HVOR den skal våge seg og hvor den skal ligge unna,
    2) selvkontroll — kandidaten sammenlignes med originalen setning for
       setning: oversette tegnfeil rettes, tillegg/omformuleringer rulles
       tilbake, sifferverdier må være identiske.
    Rå OCR-tekst beholdes alltid ved siden av; dette er et lag OVER."""
    # Pass 0 — deterministisk: mekaniske artefakter («#», «ł») fikses før
    # språkmodellen ser teksten (den nekter å røre dem selv med instruks).
    ocr_tekst = _reparer_ocr_artefakter(ocr_tekst)
    usikre = [f"- «{(r.get('tekst') or '')[:60]}» (konfidens "
              f"{float(r.get('konfidens', 0)):.2f})"
              for r in (regioner or [])
              if float(r.get("konfidens", 1.0)) < 0.75
              and (r.get("tekst") or "").strip()]
    usikre_blokk = ""
    if usikre:
        usikre_blokk = (prompter.avsnitt("korriger.usikre_overskrift")
                        + "\n".join(usikre[:12]) + "\n")
    prompt = prompter.hent("korriger.forste_pass",
                           usikre_blokk=usikre_blokk,
                           ocr_tekst=ocr_tekst[:3000])
    forste, avkortet = _borealis_generer(prompt, MAKS_SVAR_TOKENS)
    if avkortet:
        return forste + "\n[AVKORTET: nådde maksimal svarlengde]"
    if forste.strip() == ocr_tekst.strip():
        # Pass 1 fant ingenting å rette — da finnes det heller ingenting å
        # selvkontrollere. Sparer et helt modellkall (flere sekunder) i
        # normaltilfellet der OCR-teksten alt er ren.
        return forste.strip()

    # Pass 2 — selvkontroll («sjekk flere ganger»): fanger både tegnfeil
    # første pass overså og eventuelle påfunn den la til.
    kontroll = prompter.hent("korriger.selvkontroll",
                             original=ocr_tekst[:3000],
                             kandidat=forste[:3000])
    andre, avkortet2 = _borealis_generer(kontroll, MAKS_SVAR_TOKENS)
    if avkortet2 or len(andre.strip()) < len(forste.strip()) // 2:
        andre = forste         # kontrollpasset sporet av → behold første
    return _linjevakt(ocr_tekst, andre)


_FUNKSJONSORD = {"er", "det", "og", "i", "på", "å", "en", "et", "som",
                 "for", "med", "til", "av", "har", "vi", "de", "den",
                 "seg", "ikke", "at", "om", "så", "kan", "må", "skal"}


def _linjevakt(raa: str, korrigert: str) -> str:
    """Pass 3 — deterministisk LINJEVAKT mot omskriving: korrigeringen
    skal fikse TEGN, ikke dikte innhold. Ord-Jaccard duger ikke (en
    tegnfiks endrer ordets identitet og straffes urettferdig) — i stedet
    kreves BEGGE bevis på omskriving samtidig: minst ett OPPFUNNET
    innholdsord (finnes ikke i originalen, heller ikke som tegnfiks/
    fuzzy-treff) OG minst ett MISTET innholdsord. Da beholdes original-
    linjen (målt: «trene på maren» ble diktet om til «trene på å forstå»
    — mens «#er → Her»-fikser passerer uberørt)."""
    import difflib

    raa_linjer = raa.strip().splitlines()
    kor_linjer = korrigert.strip().splitlines()
    if len(raa_linjer) != len(kor_linjer):
        return korrigert       # ulik struktur → kan ikke pares trygt

    def innholdsord(linje):
        return [w for w in re.findall(r"[\wæøåÆØÅ]+", linje.lower())
                if len(w) >= 3 and w not in _FUNKSJONSORD]

    ut = []
    for raa_l, kor_l in zip(raa_linjer, kor_linjer):
        ra, ka = innholdsord(raa_l), innholdsord(kor_l)
        oppfunnet = [w for w in ka
                     if not difflib.get_close_matches(w, ra, 1, 0.65)]
        mistet = [w for w in ra
                  if not difflib.get_close_matches(w, ka, 1, 0.65)]
        ut.append(raa_l if (oppfunnet and mistet) else kor_l)
    return "\n".join(ut)


# ------------------------------------------------------------------ #
#  Jobbsystem — asynkron OCR av STORE skannede dokumenter             #
# ------------------------------------------------------------------ #
# 500-1000 skannede sider tar titalls minutter på GPU-en og kan ikke
# skje inne i én HTTP-forespørsel (tunnelen kutter ved ~100 s). Flyt:
#   POST /jobb (fil)        → jobb_id med en gang
#   GET  /jobb/<id>         → status + fremdrift side for side
#   GET  /jobb/<id>/tekst   → hele den utlestne teksten (når ferdig)
#   POST /jobb/<id>/avbryt  → stopp en kø/pågående jobb
#   POST /spor  (jobb_id + sporsmal) → svar øyeblikkelig fra lagret
#                             tekst — ingen ny OCR per spørsmål.

JOBB_STI = os.path.join(ROT, "data", "jobber")

# Hvor lenge en ferdig jobb ligger på disk. Filen inneholder HELE
# dokumentteksten, altså persondata fra et ekte NAV-dokument — den skal
# ikke ligge lenger enn den er til nytte. Samme frist som
# gjennomgangsmappa bruker (rydd_gjennomgang.py), så systemet har ÉN
# oppbevaringsregel og ikke to.
JOBB_OPPBEVARING_DAGER = int(os.environ.get("JOBB_OPPBEVARING_DAGER", "30"))


def _gjennomgang_temp() -> str:
    """Midlertidig mappe for side-1-bildet som sendes til gjennomgang.

    Lå tidligere i OS-ens temp — altså UTENFOR nav/ (CLAUDE.md §1), på
    en maskin der bildet er første side av et ekte NAV-dokument. Filen
    slettes i en `finally`, men et prosesskrasj etterlot den der.
    Nå ligger den under nav/data, som følger mappa og ryddes med den."""
    sti = os.path.join(ROT, "data", "midlertidig")
    os.makedirs(sti, exist_ok=True)
    return sti
_jobber = {}
_jobb_ko = queue.Queue()
_jobb_las = threading.Lock()   # beskytter jobb-mutasjon mot samtidig lesing
# Idempotency-Key → jobb_id. Sender en klient samme nøkkel om igjen (typisk
# automatisk retry etter et nettbrudd), får den DEN OPPRINNELIGE jobben i
# stedet for en ny — så et avbrutt opplastingsforsøk aldri gir to jobber
# for samme dokument. NAV Oppgave-APIet bruker samme mekanisme.
_idempotens = {}


def _jobb_status(jobb: dict, ny_status: str, **felter) -> None:
    """Setter status og øker versjon — grunnlaget for optimistisk låsing.
    Hver endring løfter versjon med 1, så en klient som avbryter med en
    utdatert versjon oppdager at noen (typisk arbeidstråden) har rukket å
    endre jobben i mellomtiden, og får 409 i stedet for en stille no-op."""
    jobb["status"] = ny_status
    jobb["versjon"] = jobb.get("versjon", 1) + 1
    for k, v in felter.items():
        jobb[k] = v


def _jobb_lagre(jobb: dict) -> None:
    os.makedirs(JOBB_STI, exist_ok=True)
    with _jobb_las:
        lagres = {k: v for k, v in jobb.items() if not k.startswith("_")}
    with open(os.path.join(JOBB_STI, jobb["jobb_id"] + ".json"), "w",
              encoding="utf-8") as f:
        json.dump(lagres, f, ensure_ascii=False)


def rydd_jobber(maks_alder_dager: int = None, naa: float = None) -> dict:
    """Sletter jobber som er eldre enn oppbevaringsfristen.

    En jobbfil inneholder HELE dokumentteksten. Uten rydding lå
    persondata fra hvert eneste store dokument på disk for alltid — og
    `skript/rydd_gjennomgang.py` påsto samtidig at gjennomgangsmappa var
    «det ENESTE stedet systemet bevarer data». Det stemte ikke, og en
    oppbevaringspolicy som ikke stemmer med virkeligheten er verre enn
    ingen policy.

    Kjøres ved oppstart og etter hver fullførte jobb. Returnerer
    {slettet, beholdt, frigjort_byte}."""
    frist = (maks_alder_dager if maks_alder_dager is not None
             else JOBB_OPPBEVARING_DAGER)
    naa = naa if naa is not None else time.time()
    grense = naa - frist * 86400
    slettet, beholdt, byte = 0, 0, 0
    try:
        filer = os.listdir(JOBB_STI)
    except FileNotFoundError:
        return {"slettet": 0, "beholdt": 0, "frigjort_byte": 0}
    for navn in filer:
        if not navn.endswith(".json"):
            continue
        sti = os.path.join(JOBB_STI, navn)
        try:
            if os.path.getmtime(sti) >= grense:
                beholdt += 1
                continue
            byte += os.path.getsize(sti)
            os.remove(sti)
            _jobber.pop(navn[:-5], None)
            slettet += 1
        except OSError:
            continue
    if slettet:
        print(f"  Ryddet {slettet} jobb(er) eldre enn {frist} dager "
              f"({byte // 1024} kB frigjort)")
    return {"slettet": slettet, "beholdt": beholdt, "frigjort_byte": byte}


def _jobb_last_fra_disk() -> None:
    """Laster ferdige jobber fra disk ved oppstart. Jobber som var
    underveis da serveren stoppet, merkes ærlig som feilet.

    Rydder FØRST: gamle jobber skal ikke lastes tilbake i minnet bare
    for å bli slettet senere."""
    rydd_jobber()
    try:
        for navn in os.listdir(JOBB_STI):
            if not navn.endswith(".json"):
                continue
            with open(os.path.join(JOBB_STI, navn), encoding="utf-8") as f:
                jobb = json.load(f)
            if jobb.get("status") in ("kø", "pågår"):
                jobb["status"] = "feil"
                jobb["feil"] = "Serveren ble restartet før jobben ble ferdig — last opp på nytt."
            _jobber[jobb["jobb_id"]] = jobb
    except FileNotFoundError:
        pass


def _jobb_arbeider() -> None:
    """Én arbeidstråd — GPU-en tar uansett én OCR-side om gangen.
    Renderer hver side ÉN gang og kjører både region-OCR og
    strekkode-dekoding på samme bilde."""
    while True:
        jobb_id = _jobb_ko.get()
        jobb = _jobber.get(jobb_id)
        if jobb is None or jobb.get("avbrutt"):
            if jobb is not None:
                _jobb_status(jobb, "avbrutt")
                with _jobb_las:
                    jobb.pop("_data", None)   # frigjør filbytene
                try:
                    _jobb_lagre(jobb)
                except Exception:
                    pass
            continue
        try:
            # Importene ligger INNE i jobb-try-en med vilje: 2026-07-24
            # døde tråden stille ved oppstart fordi et import feilet
            # (halvskrevet fil på disk i utrullingsøyeblikket) — og ALLE
            # køede jobber ble stående «i kø» for evig. Nå feiler bare
            # den ene jobben; tråden lever og neste jobb prøver på nytt.
            # (Vellykkede importer er gratis — Python cacher moduler.)
            import fitz
            import numpy as np
            from delt.region_ocr import ocr_side
            try:
                from PIL import Image
                from pyzbar.pyzbar import decode as _dekode
            except ImportError:
                _dekode = None

            _jobb_status(jobb, "pågår")
            with _jobb_las:
                data = jobb.pop("_data", None)
            doc = fitz.open(stream=data, filetype="pdf")
            jobb["sider_totalt"] = doc.page_count

            # Snarvei: har PDF-en tekstlag, trengs ingen OCR i det hele tatt
            sider_tekst = [(s.get_text() or "") for s in doc]
            tekstlag = "\n".join(sider_tekst)
            if len(tekstlag.strip()) >= 20:
                doc.close()
                if len(sider_tekst) > 1:
                    t = "\n".join(f"[Side {i + 1} av {len(sider_tekst)}]\n{s}"
                                  for i, s in enumerate(sider_tekst)).strip()
                else:
                    t = tekstlag.strip()
                jobb.update(
                    status="ferdig", versjon=jobb.get("versjon", 1) + 1,
                    tekst=t, antall_tegn=len(t),
                    felter=utvid_entiteter(t, {}), datoer=finn_alle_datoer(t),
                    # tekstlag = digitalt født, ingen OCR (ocr_brukt=False)
                    dokumentdato=dokumentdato_av(t, ocr_brukt=False),
                    strekkoder=les_strekkoder_bytes(data), handskrift=[],
                    ocr_motorer={}, sider_ferdig=jobb["sider_totalt"],
                )
                _jobb_lagre(jobb)
                continue

            tekster, handskrift, strekkoder = [], [], []
            motorer = {}
            start = time.time()
            for i, side in enumerate(doc):
                if jobb.get("avbrutt"):
                    _jobb_status(jobb, "avbrutt")
                    break
                pix = side.get_pixmap(matrix=ocr_skala(doc, side))
                bilde = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                    pix.height, pix.width, pix.n)
                if pix.n == 4:
                    bilde = bilde[:, :, :3]
                res = ocr_side(bilde)
                tekster.append(res["tekst"])
                for r in res["regioner"]:
                    motorer[r["motor"]] = motorer.get(r["motor"], 0) + 1
                    if r.get("skrift") == "handskrift" and r["tekst"]:
                        handskrift.append(r["tekst"])
                if _dekode is not None:
                    try:
                        for kode in _dekode(Image.fromarray(bilde)):
                            strekkoder.append({
                                "type": kode.type,
                                "verdi": kode.data.decode("utf-8", "replace"),
                                "side": i + 1,
                            })
                    except Exception:
                        pass
                jobb["sider_ferdig"] = i + 1
                brukt = time.time() - start
                jobb["sekunder_brukt"] = round(brukt)
                gjenstaar = jobb["sider_totalt"] - (i + 1)
                if gjenstaar > 0:
                    jobb["sekunder_igjen_estimat"] = round(brukt / (i + 1) * gjenstaar)
                if (i + 1) % 25 == 0:
                    _jobb_lagre(jobb)
            doc.close()

            if jobb.get("status") != "avbrutt":
                if len(tekster) > 1:
                    tekst = "\n".join(
                        f"[Side {i + 1} av {jobb['sider_totalt']}]\n{t}"
                        for i, t in enumerate(tekster)).strip()
                else:
                    tekst = "\n".join(tekster).strip()
                jobb["sekunder_igjen_estimat"] = None
                jobb.update(
                    status="ferdig", versjon=jobb.get("versjon", 1) + 1,
                    tekst=tekst, antall_tegn=len(tekst),
                    felter=utvid_entiteter(tekst, {}),
                    datoer=finn_alle_datoer(tekst),
                    # Store skannede bunker går HIT, ikke gjennom /analyser
                    # — og det er nettopp her datospennet per side betyr
                    # mest. Sidemerkene over gjør per-side-logikken riktig.
                    dokumentdato=dokumentdato_av(tekst, ocr_brukt=True),
                    strekkoder=strekkoder, handskrift=handskrift,
                    ocr_motorer=motorer,
                )
            _jobb_lagre(jobb)
        except Exception as exc:
            _jobb_status(jobb, "feil", feil=str(exc))
            try:
                _jobb_lagre(jobb)
            except Exception:
                pass
        finally:
            # Rydd etter hver jobb, ikke bare ved oppstart: en server som
            # står i månedsvis ville ellers samlet opp dokumenttekst helt
            # til neste omstart.
            try:
                rydd_jobber()
            except Exception:
                pass


# ------------------------------------------------------------------ #
#  OpenAPI-spesifikasjon + Swagger UI (GET /openapi.json, /dokumentasjon)
# ------------------------------------------------------------------ #

def _skjemaer() -> dict:
    """Svarmodellene, slik Swagger UI kan vise dem under «Schemas».

    Formene her er hentet fra FAKTISKE svar fra en kjørende server, ikke
    skrevet ut fra hukommelsen. Poenget er at en integrator skal kunne
    lese seg til feltnavn og typer uten å måtte kalle API-et først —
    særlig de stedene der typen overrasker: «belop» er et TALL i
    felter-delen, men en LISTE av objekter med kontekst i struktur-delen.

    Merk at API-et er en «tolerant reader»-kontrakt: vi UTVIDER svar med
    nye felter uten å regne det som en brytende endring. Modellene under
    er derfor ikke uttømmende låser, men en beskrivelse av det du kan
    regne med finnes."""
    s = lambda **kw: {"type": "string", **kw}          # noqa: E731
    b = lambda **kw: {"type": "boolean", **kw}         # noqa: E731
    ref = lambda navn: {"$ref": f"#/components/schemas/{navn}"}  # noqa: E731

    # ÉN konfidensskala i hele svaret. Ordet «usikker» var et fjerde navn
    # på det «lav» allerede het, så en klient som filtrerte på «lav»
    # aldri traff sammendraget.
    KONFIDENS = ["hoy", "middels", "lav", "ingen"]
    # Hvor langt SYSTEMET er kommet — ikke hvor sikkert et funn er.
    # «ingen» sto her og betydde «vi leter ikke etter feltet» — mens
    # «ingen» i konfidensskalaen betyr «vi lette og fant ingenting».
    # Samme ord, motsatt betydning: en klient som leste dekning-«ingen»
    # som «dokumentet mangler signatur» bygget en beslutning på en løgn.
    DEKNINGSGRAD = ["full", "delvis", "ikke_evaluert"]

    return {
        "Part": {
            "type": "object",
            "description": (
                "R69: personen dokumentet GJELDER — ikke saksbehandler, "
                "lege, arbeidsgiver eller kopimottaker. «Part» er "
                "forvaltningslovens ord (§ 2 e); «dokumenteier» betyr i "
                "dokumenthåndtering arkivets eier, altså akkurat den "
                "personen regelen skal holde UTENFOR. Uten et positivt "
                "partssignal er fnr null, og «sikkerhet» sier hvorfor."),
            "properties": {
                "navn": s(nullable=True, example="Ola Nordmann"),
                "fnr": s(nullable=True),
                "fodselsdato": s(nullable=True,
                                 description="Avledet av et BEVIST "
                                             "fødselsnummer"),
                "fastslatt": b(description="Har vi en part eller ikke — som "
                                           "ÉN verdi, så en klient slipper å "
                                           "vite hvilke av fem "
                                           "«sikkerhet»-ord som betyr ja"),
                "grunnlag": s(example="etikett",
                              enum=["etikett", "flertydig",
                                    "bare_andre_roller", "umerket", "ingen"],
                              description="Hva funnet BYGGER PÅ. En "
                                          "kategori, ikke et trinn på en "
                                          "skala — ikke sammenlign med </>"),
                "begrunnelse": s()}},
        "Opphav": {
            "type": "object",
            "description": (
                "Hvor ETT felt kommer fra. To LUKKEDE ordforråd, aldri "
                "gjenbrukt til noe annet — API-et forklarte tidligere "
                "proveniens på fem uavhengige måter med hvert sitt "
                "ordforråd, og to av dem brukte samme ord om ulike ting."),
            "properties": {
                "metode": s(example="etikett",
                            enum=["sjekksum", "etikett", "posisjon",
                                  "metadata", "strekkode", "regel", "modell",
                                  "avledet", "ingen"],
                            description="«sjekksum» er matematisk bevis "
                                        "(mod11/mod10); «avledet» betyr at "
                                        "verdien FØLGER av en annen verdi og "
                                        "ikke står i dokumentet; «modell» "
                                        "betyr gjettet av språkmodellen"),
                "konfidens": s(example="hoy", enum=KONFIDENS,
                               description="Samme skala som overalt ellers"),
                "begrunnelse": s(nullable=True),
                "side": {"type": "integer", "nullable": True}}},
        "Hjemmel": {
            "type": "object",
            "description": (
                "Én lovhenvisning fra dokumentteksten, slått opp i den "
                "loven som gjaldt DA DOKUMENTET BLE SKREVET. Samme "
                "kapittelnummer betyr ULIKE ting i de to "
                "folketrygdlovene — «kapittel 8» er sykepenger i "
                "1997-loven og uførepensjon i 1966-loven — så oppslaget "
                "uten dokumentdato ville vært en gjetning (R77)."),
            "properties": {
                "referanse": s(example="§ 11-5",
                               description="Slik den STÅR i dokumentet"),
                "kapittel": s(nullable=True, example="11"),
                "lov": s(nullable=True, example="ftrl-1997"),
                "kapittel_tittel": s(nullable=True,
                                     example="Arbeidsavklaringspenger"),
                "flertydig": b(description="Ingen dokumentdato ⇒ vi vet "
                                           "ikke hvilken lov, og gjetter "
                                           "ikke"),
                "lov_nevnt_i_teksten": b(
                    description="Sto lovnavnet rett foran henvisningen"),
                "merknad": s(nullable=True,
                             description="Satt når henvisningen IKKE kan "
                                         "slås opp — f.eks. et udelt "
                                         "paragrafnummer (§ 29), som "
                                         "hører til en annen lov enn "
                                         "folketrygdloven")}},
        "Varsel": {
            "type": "object",
            "description": (
                "En advarsel du kan programmere mot. De samme advarslene "
                "lå før bare som fri tekst i «kvalitet.advarsler», der en "
                "klient måtte lete etter delstrenger for å reagere. "
                "«kode» er stabil; «detalj» er den opprinnelige teksten."),
            "properties": {
                "type": s(example="ocr"),
                "kode": s(example="ukjent_felt"),
                "alvor": s(example="advarsel",
                           enum=["info", "advarsel", "feil"]),
                "detalj": s()}},
        "Kodet": {
            "type": "object",
            "description": "Maskinkode + menneskelig term. Bruk «kode» i "
                           "logikk, «term» i grensesnitt.",
            "properties": {"kode": s(example="brevdato_sannsynlig"),
                           "term": s(example="Sannsynlig brevdato "
                                             "(øverst i dokumentet)")}},
        "Datospenn": {
            "type": "object",
            "description": "Datospennet i dokumentet. «flere_dokumenter» "
                           "varsler at fila trolig inneholder mer enn ett "
                           "dokument — da er én dokumentdato misvisende.",
            "properties": {
                "fra": s(format="dd.MM.yyyy", example="12.06.2026"),
                "til": s(format="dd.MM.yyyy", example="12.06.2026"),
                "antall": {"type": "integer", "example": 1},
                "per_side": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"side": {"type": "integer"},
                                   "dato": s(), "type": s()}}},
                "flere_dokumenter": b(example=False)}},
        "Dokumentdato": {
            "type": "object",
            "description": "Dokumentets EGEN dato, valgt blant alle datoene "
                           "i teksten og begrunnet. Skilt fra datoene "
                           "dokumentet HANDLER om. Alltid deterministisk.",
            "properties": {
                "dato": s(format="dd.MM.yyyy", example="12.06.2026"),
                "type": s(example="brevdato_sannsynlig"),
                "type_kodet": ref("Kodet"),
                "rolle_kodet": ref("Kodet"),
                "kilde": s(description="Hva valget bygger på: «etikett» "
                                       "(merket i teksten), «posisjon» "
                                       "(plassering), «pdf_metadata»",
                           example="posisjon"),
                "konfidens": s(enum=["hoy", "middels", "lav"],
                               example="middels"),
                "begrunnelse": s(description="Hvorfor nettopp denne datoen "
                                             "ble valgt — les den når "
                                             "konfidens ikke er «hoy»"),
                "side": {"type": "integer", "example": 1},
                "periode": ref("Datospenn"),
                "alternativer": {"type": "array", "items": ref("Kodet"),
                                 "description": "Datoer som også var "
                                                "kandidater"},
                "advarsel": s(nullable=True)}},
        "DatoDetaljert": {
            "type": "object",
            "description": "Én dato med klassifisering og kontekst.",
            "properties": {
                "dato": s(example="12.06.2026"),
                "raatekst": s(description="Slik datoen sto i dokumentet"),
                "type": s(example="brevdato_sannsynlig"),
                "etikett": s(nullable=True,
                             description="Teksten som merket datoen, f.eks. "
                                         "«Frist:»"),
                "begrunnelse": s(),
                "side": {"type": "integer"},
                "kontekst": s(description="Tekstutdrag rundt treffet"),
                "i_lopende_tekst": b(),
                "aar_antatt": b(description="Årstallet manglet og ble utledet"),
                "rolle": s(example="dokument"),
                "type_kodet": ref("Kodet"),
                "rolle_kodet": ref("Kodet")}},
        "Belop": {
            "type": "object",
            "description": "Ett kronebeløp med konteksten det ble lest i. "
                           "Konteksten er ofte avgjørende: «Pris», «MVA» og "
                           "«Total» ser like ut som tall.",
            "properties": {
                "verdi": {"type": "number", "format": "double",
                          "example": 463.0},
                "raatekst": s(example="463,00"),
                "kontekst": s(example="… Pris Kr: 463,00 + Utlegg Kr: …")}},
        "DeterministiskeFelter": {
            "type": "object",
            "description": "Felter funnet med mønstre og sjekksummer — "
                           "ALDRI modellgjetning. Identifikatorer er "
                           "mod11-validert; består de ikke matematikken, "
                           "utelates de helt. Et felt som ikke ble funnet "
                           "MANGLER (nøkkelen er ikke null).",
            "properties": {
                "dato": s(example="12.06.2026"),
                "belop": {"type": "number", "example": 463.0,
                          "description": "FØRSTE beløp i teksten"},
                "totalbelop": {"type": "number", "example": 486.0,
                               "description": "Beløpet på en Total-/Sum-/"
                                              "Å betale-linje. Ofte et ANNET "
                                              "tall enn «belop»."},
                "fodselsnummer": s(description="mod11-validert"),
                "kontonummer": s(description="mod11-validert"),
                "organisasjonsnummer": s(description="mod11-validert",
                                         example="889000007"),
                "kid": s(description="Krever «KID»-etikett i teksten"),
                "telefon": s(), "epost": s(),
                "postnummer": s(), "poststed": s(), "fylke": s(),
                "saksnummer": s(), "ytelse": s(), "kontornavn": s()}},
        "FelterDel": {
            "type": "object",
            "description": "Svaret på «felter=ja».",
            "properties": {
                "felter": ref("DeterministiskeFelter"),
                "datoer": {"type": "array", "items": s(),
                           "description": "Alle datoer, bare som tekst"},
                "datoer_detaljert": {"type": "array",
                                     "items": ref("DatoDetaljert")},
                "dokumentdato": ref("Dokumentdato")}},
        "StrukturDel": {
            "type": "object",
            "description": "Svaret på «struktur=ja» — samme innhold som "
                           "POST /uttrekk. Alle nøkler alltid til stede; "
                           "tomt er \"\" eller [].",
            "properties": {
                "dokument": {"type": "object", "properties": {
                    "tittel": s(), "dokumenttype": s(example="kvittering"),
                    "sprak": s(), "kontornavn": s(), "fylke": s(),
                    "ytelse": s()}},
                "identifikatorer": {"type": "object", "properties": {
                    "fodselsnummer": {"type": "array", "items": s()},
                    "kontonummer": {"type": "array", "items": s()},
                    "organisasjonsnummer": {"type": "array", "items": s()},
                    "kid": {"type": "array", "items": s()},
                    "saksnummer": s()}},
                "kontakt": {"type": "object", "properties": {
                    "telefoner": {"type": "array", "items": s()},
                    "eposter": {"type": "array", "items": s()}}},
                "adresser": {"type": "array", "items": s()},
                "datoer": {"type": "array", "items": ref("DatoDetaljert")},
                "perioder": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"fra": s(), "til": s()}}},
                "belop": {"type": "array", "items": ref("Belop"),
                          "description": "MERK: liste av objekter — ikke ett "
                                         "tall som i felter-delen"}}},
        "SvarDel": {
            "type": "object",
            "description": "Svaret på «sporsmal». Dette er den ENE delen som "
                           "alltid går via modellen.",
            "properties": {
                "ok": b(),
                "sporsmal": s(),
                "svar": s(example="486,00"),
                "tall_verifisert": b(
                    description="Hvert tall i svaret står ORDRETT i "
                                "dokumentet. false ⇒ modellen kan ha "
                                "funnet på et tall — ikke stol på svaret."),
                "tolket_sporsmal": s(nullable=True,
                                     description="Satt hvis et uklart "
                                                 "spørsmål måtte tolkes om"),
                "svar_avkortet": b()}},
        "SkjemaDel": {
            "type": "object",
            "description": "Svaret på «skjema_mal» — din egen mal utfylt.",
            "properties": {
                "ok": b(),
                "motor": s(enum=["felter", "auto", "modell"]),
                "skjema": {"type": "object",
                           "description": "Malen din, utfylt. Samme struktur "
                                          "som du sendte inn."},
                "kilde_per_felt": {
                    "type": "object",
                    "additionalProperties": s(enum=["deterministisk",
                                                    "modell"]),
                    "description": "Kun «auto»: hvilke felter som er BEVIST "
                                   "og hvilke som er gjettet"},
                "modell_brukt": b(description="Kun «auto»: om modellen "
                                              "faktisk ble kalt"),
                "avvik": {"type": "array", "items": s(),
                          "description": "Hva kodevalideringen grep inn i"},
                "ukjente_felter": {"type": "array", "items": s(),
                                   "description": "Plassholdere i malen din "
                                                  "som ikke finnes"},
                "tilgjengelige_felter": {"type": "array", "items": s(),
                                         "description": "Alle gyldige "
                                                        "plassholdernavn"}}},
        "Valg": {
            "type": "object",
            "description": "Hva serveren FAKTISK utførte. Sammenlign med det "
                           "du ba om — avviker den, ble et felt ikke forstått.",
            "properties": {"tekst": b(), "felter": b(), "struktur": b(),
                           "svar": b(), "skjema": b(), "korriger": b()}},
        "Kvalitet": {
            "type": "object",
            "properties": {
                "ocr_brukt": b(),
                "ocr_motorer": {"type": "object"},
                "advarsler": {"type": "array", "items": s(),
                              "description": "Bl.a. ukjente feltnavn som ble "
                                             "ignorert. LES DENNE."}}},
        "Versjon": {
            "type": "object",
            "description": "Hva som svarte. «uttrekk_regler» endres når de "
                           "deterministiske mønstrene endres, så et svar kan "
                           "spores til reglene som produserte det.",
            "properties": {
                "api": s(example="1.3.0"), "prompt": s(example="p10"),
                "uttrekk_regler": s(example="u5"),
                "ocr_konfidens_terskel": {"type": "number", "example": 0.85},
                "norhand": s(), "modell": s()}},
        "Dokumentprofil": {
            "type": "object",
            "description": (
                "R79: obligatoriske metadata om dokumentet SELV. Følger "
                "ALLTID med i svaret fra POST /dokument — i begge "
                "kontraktene, uansett hva klienten ba om. Seksjonene og "
                "feltene er FASTE: tomt er null eller [], aldri en "
                "manglende nøkkel. Alt er deterministisk (ingen modell); "
                "et felt som ikke kan fastslås er null med en begrunnelse "
                "ved siden av, aldri en gjetning. Se "
                "docs/dokumentprofil_skjema.md."),
            "properties": {
                "skjemaversjon": s(
                    example="1.3",
                    description="Profilens EGEN versjon. Endres formen, går "
                                "dette tallet opp — en klient skal se det på "
                                "tallet, ikke når noe brekker"),
                "sammendrag": {
                    "type": "object",
                    "description": (
                        "R74: START HER. De få feltene de fleste er ute "
                        "etter, hentet opp fra seksjonene under. "
                        "«konfidens» er det SVAKESTE leddet, ikke et "
                        "gjennomsnitt — er parten usikker, hjelper det "
                        "ikke at datoen er sikker"),
                    "properties": {
                        "navn": s(nullable=True, example="Ola Nordmann"),
                        "fnr": s(nullable=True),
                        "dokumentdato": s(nullable=True,
                                          example="2026-05-12"),
                        "dokumenttype": s(nullable=True, example="vedtak"),
                        "ytelse": s(nullable=True),
                        "saksnummer": s(nullable=True),
                        "antall_sider": {"type": "integer",
                                         "nullable": True},
                        "antall_dokumenter": {"type": "integer"},
                        "konfidens": s(example="middels", enum=KONFIDENS,
                                       description="ÉN skala for hele "
                                                   "API-et: hoy/middels/"
                                                   "lav/ingen")}},
                "dokumenter": {
                    "type": "array", "items": {"type": "object"},
                    "description": (
                        "R74: en FIL er ikke nødvendigvis ETT dokument. "
                        "En skannet saksmappe kan inneholde vedtak, "
                        "inntektsmelding og klage — hver med sin dato og "
                        "noen ganger sin person. Er antall_dokumenter > "
                        "1, LES DENNE i stedet for toppnivåfeltene")},
                "fil": {
                    "type": "object",
                    "description": "Filen som ble lest. antall_sider er "
                                   "FILENS sider, ikke sidene med tekst. "
                                   "blanke_sider/uleselige_sider er null når "
                                   "vi ikke har grunnlag for å svare — ikke "
                                   "det samme som «ingen»",
                    "properties": {
                        "filnavn": s(nullable=True),
                        "antall_sider": {"type": "integer", "nullable": True,
                                         "example": 12},
                        "blanke_sider": {"type": "array", "nullable": True,
                                         "items": {"type": "integer"}},
                        "uleselige_sider": {"type": "array", "nullable": True,
                                            "items": {"type": "integer"}}}},
                "part": ref("Part"),
                "andre_fodselsnummer": {
                    "type": "array", "items": {"type": "object"},
                    "description": "Alle ANDRE fødselsnummer i dokumentet, "
                                   "med rolle og etikett. Partens gjentas "
                                   "aldri her"},

                "dokument": {
                    "type": "object",
                    "description": (
                        "R80: «dato» er dokumentets EGEN dato — aldri en "
                        "dato som bare nevnes i teksten. «periode_start/"
                        "slutt» er hva dokumentet GJELDER FOR; «spenn_fra/"
                        "til» er datospennet når filen er en BUNKE. De tre "
                        "er ulike ting"),
                    "properties": {
                        "type": {**ref("Kodet"), "nullable": True,
                                 "description": "Koden er stabil og "
                                                "maskinlesbar, termen er "
                                                "for et menneske. HELE "
                                                "paret er null når typen "
                                                "ikke ble fastslått — "
                                                "{kode: null} ville sagt at "
                                                "det finnes en type som "
                                                "bare mangler navn"},
                        "tittel": s(nullable=True),
                        "sprak": s(nullable=True),
                        "kontornavn": s(nullable=True),
                        "fylke": s(nullable=True),
                        "dato": s(nullable=True, example="2026-05-08"),
                        "dato_original": s(
                            nullable=True, example="8. mai 2026",
                            description="Ordrett slik datoen STO i "
                                        "dokumentet. «dato» er den "
                                        "normaliserte formen. Feltet het "
                                        "«dato_norsk» og var da en andre "
                                        "RENDERING av den normaliserte "
                                        "verdien — fem ulike skrivemåter ga "
                                        "alle samme streng. Dette er "
                                        "originalen, og det eneste man kan "
                                        "kontrollere OCR mot"),
                        "aarstall": {"type": "integer", "nullable": True,
                                     "example": 2026},
                        "alder": {"type": "object", "nullable": True},
                        "dato_kilde": s(nullable=True),
                        "dato_sikkerhet": s(example="hoy"),
                        "dato_begrunnelse": s(nullable=True),
                        "dato_side": {"type": "integer", "nullable": True},
                        "periode_start": s(nullable=True,
                                           example="2025-01-01"),
                        "periode_slutt": s(nullable=True,
                                           example="2025-12-31"),
                        "spenn_fra": s(nullable=True),
                        "spenn_til": s(nullable=True),
                        "flere_dokumenter": b()}},
                "sak": {
                    "type": "object",
                    "description": "R71: hentes bare når etiketten står i "
                                   "dokumentet",
                    "properties": {
                        "saksnummer": s(nullable=True),
                        "journalnummer": s(nullable=True),
                        "vedtaksnummer": s(nullable=True),
                        "dokumentnummer": s(nullable=True),
                        "referanse": s(nullable=True),
                        "sakstype": {**ref("Kodet"), "nullable": True,
                                     "description": "Kommer sammen med "
                                                    "ytelsesreglene"}}},
                "ytelse": {
                    "type": "object",
                    "description": "Ytelsesreglene kommer senere. «navn» "
                                   "hentes av den ene detektoren som "
                                   "finnes",
                    "properties": {
                        "navn": {**ref("Kodet"), "nullable": True,
                                 "example": {"kode": "SYK",
                                             "term": "Sykepenger"},
                                 "description":
                                     "«kode» er NAVs offisielle TEMAKODE — "
                                     "den andre NAV-systemer ruter på. "
                                     "Kartet er mange-til-én der NAV selv "
                                     "slår sammen (uføretrygd og "
                                     "uførepensjon er begge «UFO»); hvilken "
                                     "LOV som gjaldt avgjøres likevel av "
                                     "dokumentdatoen, ikke av koden, så et "
                                     "1994-vedtak får fortsatt ftrl-1966. "
                                     "Temakodelista er levert stykkevis: "
                                     "«kode: null» MED fylt «term» betyr "
                                     "at ytelsen ble funnet, men at vi ikke "
                                     "har koden ennå — noe helt annet enn "
                                     "at begge er null, som betyr at ingen "
                                     "ytelse ble funnet"},
                        "type": s(nullable=True),
                        "utfall": s(nullable=True,
                                    description="innvilget/avslatt/endret/"
                                                "stanset — ikke implementert"),
                        "gyldig_fra": s(nullable=True),
                        "gyldig_til": s(nullable=True),
                        "status": s(nullable=True,
                                    enum=["innvilget", "lopende",
                                          "opphort"],
                                    description="YTELSENS egen status. "
                                                "Sto tidligere for hvor "
                                                "langt SYSTEMET var "
                                                "kommet — to ulike ting "
                                                "under ett navn. Det "
                                                "andre ligger nå i "
                                                "«dekning»"),
                        "navn_kodet": {**ref("Kodet"), "nullable": True}}},
                "ytelser": {
                    "type": "array", "items": ref("Kodet"),
                    "description": (
                        "ALLE ytelsene dokumentet nevner, i den "
                        "rekkefølgen de står. «ytelse» over er den mest "
                        "SPESIFIKKE (lengste treff) og ligger alltid i "
                        "denne lista — men den er ikke nødvendigvis den "
                        "første. Ett navn tapte informasjon: et "
                        "AAP-vedtak viser nesten alltid til "
                        "sykepengeperioden som tok slutt. Lista er "
                        "avdupet på TEMAKODE: pleiepenger og "
                        "omsorgspenger er begge «OMS» og står én gang")},
                "hjemler": {
                    "type": "array", "items": ref("Hjemmel"),
                    "description": (
                        "Bestemmelsene dokumentet SELV viser til. Dette "
                        "er noe annet enn «hjemmel», som sier hvilken lov "
                        "som GJALDT da dokumentet ble skrevet: et vedtak "
                        "kan vise til flere paragrafer, og et klagebrev "
                        "siterer gjerne både bestemmelsen det klages på "
                        "og saksbehandlingsregelen")},
                "dekning": {
                    "type": "object",
                    "description": (
                        "Hva systemet LETER ETTER ennå. Et null-felt kan "
                        "bety to ting: dokumentet mangler opplysningen, "
                        "eller lesingen er ikke bygget. «ingen» ⇒ null "
                        "sier ingenting om DOKUMENTET, og en klient skal "
                        "ikke melde avvik. «ikke_evaluert» er IKKE det "
                        "samme som konfidens-«ingen», som betyr at vi lette "
                        "og ikke fant"),
                    "properties": {
                        "sider_lest": s(
                            example="delvis",
                            enum=["full", "delvis", "ukjent"],
                            description="OVERSTYRER resten. «delvis» ⇒ "
                                        "INGEN av feltene i svaret gjelder "
                                        "hele dokumentet, bare de leste "
                                        "sidene. Et skannet dokument på 500 "
                                        "sider får som standard OCR på 10 av "
                                        "dem; øk med «maks_sider» eller bruk "
                                        "POST /jobb for hele"),
                        "sider": {
                            "type": "object",
                            "description": "Hvor mange sider som faktisk ble "
                                           "lest, av hvor mange filen har",
                            "properties": {
                                "lest": {"type": "integer", "nullable": True,
                                         "example": 10},
                                "totalt": {"type": "integer",
                                           "nullable": True, "example": 500}}},
                        "ytelse": s(enum=DEKNINGSGRAD),
                        "sakstype": s(enum=DEKNINGSGRAD),
                        "signatur_sider": s(enum=DEKNINGSGRAD),
                        "uleselige_sider": s(enum=DEKNINGSGRAD),
                        "forklaring": s()}},
                "gjeldende_lov": {
                    "type": "object",
                    "description": (
                        "R77/R78: hvilken folketrygdlov som gjaldt DA "
                        "dokumentet ble skrevet. AVLEDET av "
                        "dokumentets dato — ikke noe dokumentet "
                        "påberoper seg; det ligger i «hjemler». "
                        "dokumentet ble skrevet. Det finnes to — 1966 og "
                        "1997 — og de samme kapittelnumrene betyr ULIKE "
                        "ting i dem. Valget følger dokumentdatoen (skillet "
                        "går 1997-05-01), ikke dagens dato, og "
                        "«begrunnelse» sier hvorfor. Uten dokumentdato er "
                        "«lov» null: å gjette lov er verre enn å la være."),
                    "properties": {
                        "lov": s(nullable=True, example="ftrl-1997",
                                 enum=["ftrl-1997", "ftrl-1966", None]),
                        "lov_tittel": s(nullable=True),
                        "status": s(nullable=True, example="gjeldende",
                                    enum=["gjeldende", "opphevet", None]),
                        "begrunnelse": s(nullable=True),
                        "ytelse_kapittel": s(nullable=True, example="8"),
                        "ytelse_kapittel_tittel": s(nullable=True)}},
                "okonomi": {
                    "type": "object",
                    "description": "R71: beløp uten etikett blir aldri en "
                                   "dagsats",
                    "properties": {
                        "dagsats": {"type": "number", "nullable": True},
                        "manedsbelop": {"type": "number", "nullable": True},
                        "utbetalt_belop": {"type": "number", "nullable": True},
                        "tilbakebetalingsbelop": {"type": "number",
                                                  "nullable": True},
                        "utbetalingsdato": s(nullable=True),
                        "valuta": s(example="NOK"),
                        "kontonummer": {"type": "array", "items": s()},
                        "kid": {"type": "array", "items": s()}}},
                "arbeid": {
                    "type": "object",
                    "properties": {
                        "arbeidsgiver": s(nullable=True),
                        "stilling": s(nullable=True),
                        "stillingsprosent": {"type": "integer",
                                             "nullable": True, "example": 80},
                        "startdato": s(nullable=True),
                        "sluttdato": s(nullable=True),
                        "arsinntekt": {"type": "number", "nullable": True},
                        "manedslonn": {"type": "number", "nullable": True},
                        "organisasjonsnummer": {"type": "array",
                                                "items": s()}}},
                "kontakt": {
                    "type": "object",
                    "properties": {
                        "telefoner": {"type": "array", "items": s()},
                        "eposter": {"type": "array", "items": s()},
                        "adresser": {"type": "array",
                                     "items": {"type": "object"}}}},
                "koder": {
                    "type": "object",
                    "description": "QR-koder og strekkoder med sidetall. "
                                   "lest=false ⇒ skanningen var AV, og null "
                                   "betyr «ikke sett etter», ikke «finnes "
                                   "ikke»",
                    "properties": {
                        "lest": b(),
                        "qr": {"type": "array", "items": {"type": "object"}},
                        "strekkode": {"type": "array",
                                      "items": {"type": "object"}},
                        "qr_kode_side": {"type": "integer", "nullable": True,
                                         "example": 1},
                        "strekkode_side": {"type": "integer", "nullable": True,
                                           "example": 3},
                        "merknad": s(nullable=True)}},
                "visuelt": {
                    "type": "object",
                    "description": "R68: stempeldatoer blir ALDRI "
                                   "dokumentdato av seg selv. signatur_sider "
                                   "er null fordi analysen ikke er bygget "
                                   "ennå — ikke fordi det mangler signatur",
                    "properties": {
                        "stempel_datoer": {"type": "array",
                                           "items": {"type": "object"}},
                        "stempel_sider": {"type": "array",
                                          "items": {"type": "integer"}},
                        "signatur_sider": {"type": "array", "nullable": True,
                                           "items": {"type": "integer"}},
                        "handskrift_funnet": b()}}}},
        "DokumentSvar": {
            "type": "object",
            "description": "Svaret fra POST /dokument. Deler du ikke ba om "
                           "er null. «dokumentprofil» følger alltid med (R79).",
            "properties": {
                "ok": b(description="Gikk forespørselen igjennom. Den er "
                                    "true OGSÅ når OCR-en ga opp på tre "
                                    "sider — se «status» for det"),
                "status": s(example="ok", enum=["ok", "delvis", "feil"],
                            description="Ett ord for hele svaret. «delvis» ⇒ "
                                        "noe manglet eller ble hoppet over; "
                                        "les «varsler»"),
                "filnavn": s(),
                "valg": ref("Valg"),
                "dokumentprofil": ref("Dokumentprofil"),
                "opphav": {
                    "type": "object",
                    "additionalProperties": ref("Opphav"),
                    "description": (
                        "Proveniens for feltene i svaret, som JSON Pointer "
                        "(RFC 6901) → opphav. Samme pekersyntaks som "
                        "problem.errors[].pointer. Erstatter INGENTING: "
                        "dato_kilde, dato_sikkerhet, part.sikkerhet og "
                        "kilde_per_felt står urørt ved siden av — kartet "
                        "er en projeksjon av dem, ikke en sjette uavhengig "
                        "mening. Nivå styres med bryteren «opphav»")},
                "tekst": s(nullable=True),
                "antall_tegn": {"type": "integer"},
                "antall_sider": {"type": "integer", "nullable": True,
                                 "description": "Filens FAKTISKE sideantall — "
                                                "ikke antall sider med tekst"},
                "felter": {**ref("FelterDel"), "nullable": True},
                "struktur": {**ref("StrukturDel"), "nullable": True},
                "svar": {**ref("SvarDel"), "nullable": True},
                "skjema": {**ref("SkjemaDel"), "nullable": True},
                "korriger": {"type": "object", "nullable": True},
                "korrigert_tekst": s(nullable=True),
                "koordinater": {**ref("KoordinatDel"), "nullable": True},
                "strekkoder": {"type": "array", "items": s()},
                "handskrift": {"type": "array", "items": s()},
                "kvalitet": ref("Kvalitet"),
                "varsler": {"type": "array", "items": ref("Varsel"),
                            "description": "Advarslene i «kvalitet.advarsler» "
                                           "som TYPEDE objekter. Fritekst"
                                           "lista blir stående ved siden av"},
                "fra_cache": b(description="Teksten kom fra cache — samme fil "
                                           "er analysert før"),
                "tid_sekunder": {"type": "number", "example": 0.6},
                "kilde": s(
                    example="borealis+deterministisk",
                    description="Inneholder «borealis» ⇒ modellen bidro til "
                                "svaret. Ellers rent deterministisk (regex + "
                                "mod11). Raskeste toppnivåsjekk en robot kan "
                                "gjøre for å avgjøre om et menneske bør se "
                                "på svaret."),
                "versjon": ref("Versjon")}},
        "SideVurdering": {
            "type": "object",
            "description": "Kvalitetsmåling av ÉN side, uten OCR.",
            "properties": {
                "side": {"type": "integer", "example": 1},
                "dpi": {"type": "number", "nullable": True,
                        "description": "Nominell oppløsning — KUN "
                                       "informasjon, aldri dømt på: for et "
                                       "opplastet bilde er den formatets "
                                       "antakelse (PNG=96), ikke en "
                                       "egenskap ved bildet. null for "
                                       "tekst-/vektorsider."},
                "piksler": {"type": "array", "items": {"type": "integer"},
                            "description": "[bredde, høyde] slik OCR ville "
                                           "sett siden — dette dømmes det "
                                           "på"},
                "skarphet": {"type": "number",
                             "description": "Laplacian-varians — høyere er "
                                            "skarpere"},
                "lys": {"type": "number",
                        "description": "Gjennomsnittlig lysnivå 0–255"},
                "blekk_andel": {"type": "number",
                                "description": "Andel mørke piksler. Nær 0 "
                                               "= tom side."},
                "tom": b(),
                "uleselig": b(description="Under AVVIS-terskelen (under 300 "
                                          "piksler eller sterkt uskarp) — "
                                          "OCR vil gi søppel"),
                "advarsler": {"type": "array", "items": s()}}},
        "ForhandssjekkSvar": {
            "type": "object",
            "description": "Kvalitetsdom FØR prosessering — aldri OCR, "
                           "aldri modell. Bruk «dom» som port: god → send "
                           "til /dokument; tvilsom → send, men flagg for "
                           "menneskelig kontroll; avvis → be om nytt skann "
                           "i stedet for å brenne GPU-tid.",
            "properties": {
                "ok": b(),
                "filnavn": s(),
                "dom": s(enum=["god", "tvilsom", "avvis"]),
                "tekstlag": b(description="Dokumentet har tekstlag — OCR "
                                          "kjøres aldri, skannkvalitet er "
                                          "irrelevant"),
                "trenger_ocr": b(),
                "antall_sider": {"type": "integer", "nullable": True},
                "sider_vurdert": {"type": "integer"},
                "sider": {"type": "array",
                          "items": ref("SideVurdering")},
                "advarsler": {"type": "array", "items": s()},
                "anbefaling": s(description="Menneskelig lesbar anbefaling "
                                            "på norsk"),
                "tid_sekunder": {"type": "number"},
                "versjon": {"type": "object"}}},
        "KoordinatFunn": {
            "type": "object",
            "description": "Ett bevist funn med posisjon på siden.",
            "properties": {
                "type": s(example="organisasjonsnummer"),
                "tekst": s(description="Tegnene slik de står i dokumentet "
                                       "(gruppering beholdt)",
                           example="889 000 007"),
                "bokser": {"type": "array",
                           "items": {"type": "array",
                                     "items": {"type": "number"}},
                           "description": "[x0, y0, x1, y1] per boks. "
                                          "Flere når OCR delte et gruppert "
                                          "nummer i flere bokser."}}},
        "KoordinatDel": {
            "type": "object",
            "description": "Svaret på «koordinater=ja»: beviste funn "
                           "(samme finnere som /sladd — mod11/sjekksum/"
                           "format, aldri modell) med bokser per side.",
            "properties": {
                "koordinatrom": s(
                    enum=["forbehandlet_bilde_piksler", "pdf_punkter"],
                    description="Rommet boksene lever i. OCR-dokumenter: "
                                "piksler i det FORBEHANDLEDE sidebildet "
                                "(perspektiv-/skjevhetsrettet). "
                                "Tekstlags-PDF: PDF-punkter (72 per "
                                "tomme). Uten dette kan ikke en utheving "
                                "skaleres riktig."),
                "sider": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "side": {"type": "integer", "example": 1},
                        "bredde": {"type": "number"},
                        "hoyde": {"type": "number"},
                        "funn": {"type": "array",
                                 "items": ref("KoordinatFunn")}}}},
                "antall_funn": {"type": "integer"}}},
        "SladdSvar": {
            "type": "object",
            "description": "Sladdet tekst — KUN beviste identifikatorer "
                           "(mod11/sjekksum/format). Les «ikke_dekket» og "
                           "«advarsel» FØR dokumentet deles videre: navn "
                           "og adresser sladdes ikke.",
            "properties": {
                "ok": b(),
                "filnavn": s(),
                "sladdet_tekst": s(description="Teksten med hvert funn "
                                               "erstattet av «[SLADDET "
                                               "type]» — synlig sladd, "
                                               "ikke stille fjerning"),
                "antall_tegn": {"type": "integer"},
                "funn": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"type": s(example="fodselsnummer"),
                                   "antall": {"type": "integer"}}}},
                "antall_sladdet": {"type": "integer"},
                "typer_valgt": {"type": "array", "items": s()},
                "ikke_dekket": {"type": "array", "items": s(),
                                "description": "Det sladdingen IKKE "
                                               "dekker — alltid navn og "
                                               "adresser"},
                "advarsel": s(description="Fast: sladdingen er ikke alene "
                                          "tilstrekkelig for "
                                          "offentliggjøring"),
                "advarsler": {"type": "array", "items": s(),
                              "description": "Bl.a. OCR-forbeholdet: et "
                                             "feillest siffer kan la et "
                                             "nummer stå usladdet"},
                "fra_cache": b(),
                "tid_sekunder": {"type": "number"},
                "kilde": s(example="deterministisk"),
                "versjon": {"type": "object"}}},
        "EkkoSvar": {
            "type": "object",
            "description": "Diagnose: nøyaktig hva serveren mottok. "
                           "Sammenlign «raa_deler» (slik det FAKTISK kom) "
                           "med «parser_ser» (hva parseren fikk ut).",
            "properties": {
                "ok": b(),
                "melding": s(),
                "content_type": s(),
                "body_lengde": {"type": "integer"},
                "antall_deler": {"type": "integer"},
                "parser_ser": {"type": "object", "properties": {
                    "fil": s(nullable=True),
                    "fil_bytes": {"type": "integer"},
                    "tekstfelt_navn": {"type": "array", "items": s(),
                                       "description": "Feltnavnene serveren "
                                                      "faktisk fant. Mangler "
                                                      "et felt du sendte, "
                                                      "ligger feilen hos "
                                                      "klienten."},
                    "tekstfelter": {"type": "object"}}},
                "raa_deler": {"type": "array", "items": {
                    "type": "object", "properties": {
                        "content_disposition": s(),
                        "innhold_lengde": {"type": "integer"},
                        "innhold_start": s()}}}}},
        "ProblemDetails": {
            "type": "object",
            "description": "RFC 9457 Problem Details — samme standard som "
                           "NAV Oppgave-APIet.",
            "properties": {
                "type": s(example="https://nav-dokument-api/problems/"
                                  "ugyldig-input"),
                "title": s(example="Ugyldig input"),
                "status": {"type": "integer", "format": "int32",
                           "example": 400},
                "detail": s(),
                "traceId": s(),
                "errors": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"pointer": s(example="/skjema_motor"),
                                   "message": s()}}}}},
        "Feilsvar": {
            "type": "object",
            "description": "Feil bærer BÅDE de enkle feltene og et "
                           "RFC 9457-objekt. Bruk det du trenger.",
            "properties": {
                "ok": b(example=False),
                "feil": s(),
                "uuid": s(description="Korrelasjons-ID for support"),
                "felter_feil": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"pointer": s(), "message": s()}}},
                "problem": ref("ProblemDetails")}},
    }


def _openapi() -> dict:
    fil_felt = {"type": "string", "format": "binary",
                "description": "Dokumentet: PDF, bilde (JPG/PNG/TIFF/BMP/WEBP), DOCX, XLSX/XLSM, CSV eller TXT"}
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "NAV dokument-API (generelt)",
            "version": API_VERSJON,
            "description": (
                "Generelt dokument-API: deterministisk uttrekk, regionbasert OCR "
                "(trykt + norsk håndskrift), strekkoder/QR, fritt spørsmål/svar med "
                "Borealis, skjemautfylling med kodevalidering og bakgrunnsjobber "
                "for store dokumenter.\n\n"
                "**Kontrakt:** fil UTEN spørsmål → hele den utleste teksten ordrett "
                "(deterministisk). Fil MED tekst → bestillingen utføres. Alle svar "
                "deklarerer ærlig hva som skjedde (advarsel/avvik/tall_verifisert).\n\n"
                "**Sti:** endepunktene svarer både på «/spor» og «/api/v1/spor» "
                "(NAV-konvensjon) — samme endepunkt.\n\n"
                "**Sporing:** send gjerne X-Correlation-ID; den ekkoes i svaret og "
                "logges, så én sak kan følges på tvers av tjenester. Mangler den, "
                "lager serveren en.\n\n"
                "**Feilformat:** feilsvar har både de enkle feltene {ok:false, feil, "
                "uuid} OG et RFC 9457-objekt «problem» {type, title, status, detail, "
                "traceId, (errors med pointer per felt)} — samme standard som NAV "
                "Oppgave-APIet. Bruk det du trenger.\n\n"
                "**Tolerant reader:** les kun feltene du bruker og ignorer resten. "
                "Vi UTVIDER svar med nye felter uten å regne det som en brytende "
                "endring; brytende endringer kommer under et nytt versjonsprefiks "
                "(/api/v2). Da er integrasjonen din robust mot videre utvikling.\n\n"
                "**Store dokumenter (POST /jobb):** send Idempotency-Key (UUID) for "
                "retry-trygghet — samme nøkkel gir samme jobb, aldri en dublett. "
                "Avbryt med optimistisk låsing: ?versjon=N (eller X-Versjon) gir 409 "
                "hvis noen andre har endret jobben i mellomtiden."),
        },
        "components": {
            "schemas": _skjemaer(),
            "securitySchemes": {"ApiKeyAuth": {
                "type": "apiKey", "in": "header", "name": "X-API-Key",
                "description": "Kreves når serveren er startet med API_NOKKEL og/eller API_NOKLER. Med navngitte nøkler (API_NOKLER=navn:nøkkel,…) får tilgangsloggen en klient_id, slik at man kan se hvem som bruker hvilke endepunkter før noe pensjoneres (R91). Nøkkelen selv logges aldri."}},
            "parameters": {"KorrelasjonsID": {
                "name": "X-Correlation-ID", "in": "header", "required": False,
                "schema": {"type": "string", "maxLength": 64},
                "description": "UUID for sporing på tvers av tjenester. "
                               "Ekkoes i svaret; genereres hvis utelatt."}},
            "responses": {"Feil": {
                "description": "Feil — {ok:false, feil, uuid}",
                "content": {"application/json": {"schema": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"},
                                   "feil": {"type": "string"},
                                   "uuid": {"type": "string",
                                            "description": "korrelasjons-ID for support"}}}}}}},
        },
        "paths": {
            "/hjelp": {"get": {"summary": "Tjenestestatus og oversikt",
                               "responses": {"200": {"description": "Status, endepunkter, grenser, Borealis-motor"}}}},
            "/dokument": {"post": {
                "summary": "Samlet endepunkt: ETT kall, brytere for hva som skal gjøres",
                "description": (
                    "Dokumentet leses ÉN gang (delt cache), deretter kjøres bare delene som er PÅ:\n"
                    "- felter=ja (STANDARD PÅ): deterministiske felter + datoer — raskt\n"
                    "- struktur=ja: komplett strukturert uttrekk (som /uttrekk) — raskt\n"
                    "- svar=ja + sporsmal: Borealis-svar med alle vaktene (som /spor)\n"
                    "- skjema=ja + skjema_mal: JSON-malen din utfylt. skjema_motor=modell "
                    "(standard): Borealis fyller med kodevalidering (som /fyll_skjema). "
                    "skjema_motor=felter: deterministisk fletting av {feltnavn}-plassholdere "
                    "i malen — raskt, uten modell, virker når Borealis er nede. "
                    "skjema_motor=auto: HYBRID — regelen fyller alt den kan BEVISE "
                    "(sjekksum/mønster/kontekst), og bare feltene den ikke fant (navn o.l. "
                    "uten fast form) sendes til modellen med tallvakt. kilde_per_felt viser "
                    "for hvert felt om verdien kom fra 'deterministisk' eller 'modell'\n"
                    "- korriger=ja: LLM-korrigert OCR-tekst\n"
                    "- tekst=nei: utelat fullteksten fra svaret\n"
                    "Modelldelene (svar/skjema/korriger) er AV som standard og feiler uavhengig — "
                    "én del med problem stopper aldri de andre; hver del har sitt eget "
                    "{ok, feil}-objekt, og feilene gjentas i kvalitet.advarsler.\n"
                    "Sender du sporsmal/skjema_mal uten bryter, slås delen på automatisk. "
                    "Brytere tar ja/nei (også 1/0, true/false, på/av) — en UKJENT verdi gir 400, "
                    "aldri en stille avslått del. Er BARE modelldeler bedt om mens Borealis er "
                    "nede, svares 503 (retry-signal) i stedet for 200.\n"
                    "ALTERNATIVT KONTRAKT: sender du feltet 'operasjoner' (en JSON-liste av "
                    "{type, …}), kjøres dokumentet gjennom operasjonsmotoren og svaret blir "
                    "{ok, resultater:[{type, ok, …}]}. Samme motor, uniform og utvidbar form; "
                    "bryterne over er den korte veien for de vanligste tilfellene."),
                "requestBody": {"content": {"multipart/form-data": {"schema": {
                    "type": "object", "required": ["fil"],
                    "properties": {"fil": fil_felt,
                                   "felter": {"type": "string", "enum": ["ja", "nei"]},
                                   "struktur": {"type": "string", "enum": ["ja", "nei"]},
                                   "svar": {"type": "string", "enum": ["ja", "nei"]},
                                   "sporsmal": {"type": "string"},
                                   "skjema": {"type": "string", "enum": ["ja", "nei"]},
                                   "skjema_mal": {"type": "string",
                                                  "description": "Din JSON-mal (kreves når skjema=ja)"},
                                   "skjema_motor": {"type": "string",
                                                    "enum": ["modell", "felter", "auto"],
                                                    "description": "modell=Borealis fyller alt (standard); felter=deterministisk fletting av {feltnavn}-plassholdere (rask, uten modell); auto=hybrid: deterministisk der regelen kan bevise, modell for resten (navn o.l.) med tallvakt"},
                                   "korriger": {"type": "string", "enum": ["ja", "nei"]},
                                   "tekst": {"type": "string", "enum": ["ja", "nei"]},
                                   "koordinater": {"type": "string",
                                                   "enum": ["ja", "nei"],
                                                   "description": "ja → beviste funn (fnr/konto/orgnr/KID/telefon/epost) med bokser per side, i «koordinater». Standard nei (bokser kan mangedoble svaret)"},
                                   "operasjoner": {"type": "string",
                                                   "description": "ALTERNATIV til bryterne: en JSON-liste av operasjoner, f.eks. [{\"type\":\"felter\"},{\"type\":\"skjema\",\"motor\":\"auto\",\"mal\":{...}}]. Gyldige typer: tekst, felter, struktur, svar (+sporsmal), skjema (+mal, +motor felter/modell/auto), korriger. Svar: {ok, resultater:[{type, ok, ...}]}. Maks 20 per kall"},
                                   "strekkoder": {"type": "string",
                                                  "enum": ["ja", "nei"],
                                                  "description": "nei → hopper over strekkode-/QR-skanningen. Da betyr et tomt «strekkoder» at det ikke ble sett etter koder, IKKE at dokumentet mangler dem — «dokumentprofil.koder.lest» sier hvilket. Standard ja"},
                                   "opphav": {"type": "string",
                                              "enum": ["ingen", "viktige", "alle"],
                                              "description": "Nivå på proveniens-sidekartet «opphav»: JSON Pointer (RFC 6901) → {metode, konfidens, begrunnelse, side}. viktige (standard) = parten og dokumentdatoen; alle = hvert felt vi kan tilskrive et opphav; ingen = tomt kart"},
                                   "datoer_detaljert": {"type": "string",
                                                        "enum": ["ja", "nei"],
                                                        "description": "nei → dropper «datoer»-lista fra svaret (typisk ~40 % av responsen på et flersidig dokument). dokumentprofil beholder alle daterte felter uansett. Standard ja"},
                                   "profil": {"type": "string",
                                              "enum": ["full", "sammendrag"],
                                              "description": "sammendrag → dokumentprofil uten person- og kontaktseksjoner (personvern: spør du bare om en dato, trenger svaret ikke fødselsnummer og adresse). «utelatt» navngir hva som ble tatt bort. Standard full"},
                                   "maks_sider": {"type": "integer"}}}}}},
                "responses": {
                    "200": {"description":
                        "Delene du ba om. Deler du ikke ba om er null.",
                        "content": {"application/json": {"schema": {
                            "$ref": "#/components/schemas/DokumentSvar"}}}},
                    "400": {"description": "Ukjent bryterverdi, manglende sporsmal/skjema_mal, "
                                           "ugyldig JSON-mal, eller JSON-mal sendt i 'skjema' "
                                           "(bruk 'skjema_mal')",
                            "content": {"application/json": {"schema": {
                                "$ref": "#/components/schemas/Feilsvar"}}}},
                    "503": {"description": "Bare modelldeler bedt om mens Borealis er nede",
                            "content": {"application/json": {"schema": {
                                "$ref": "#/components/schemas/Feilsvar"}}}}}}},
            "/dokument/operasjoner": {"post": {
                "summary": "Operasjonslista som EGEN ressurs",
                "description": (
                    "Samme motor som feltet «operasjoner» på POST /dokument, men som "
                    "egen sti. Grunnen: på /dokument overstyrer feltet bryterne i "
                    "STILLHET — sender en klient «felter=ja» sammen med «operasjoner», "
                    "skjer det ingenting med bryteren, og svaret ser ut som om begge "
                    "deler ble utført. En egen URL gjør valget synlig.\n\n"
                    "«operasjoner» er PÅKREVD her; uten feltet får du 400 i stedet for "
                    "et svar som stilltiende ble noe annet. Feltveien på /dokument "
                    "beholdes uendret."),
                "tags": ["dokument"],
                "requestBody": {"content": {"multipart/form-data": {"schema": {
                    "type": "object", "required": ["fil", "operasjoner"],
                    "properties": {
                        "fil": fil_felt,
                        "operasjoner": {"type": "string",
                                        "description": "JSON-liste av {type, …}. Maks 20."},
                        "profil": {"type": "string", "enum": ["full", "sammendrag"]},
                        "opphav": {"type": "string",
                                   "enum": ["ingen", "viktige", "alle"]},
                        "strekkoder": {"type": "string", "enum": ["ja", "nei"]},
                        "maks_sider": {"type": "integer"}}}}}},
                "responses": {
                    "200": {"description": "{ok, resultater:[{type, ok, …}], dokumentprofil, …}",
                            "content": {"application/json": {"schema": {
                                "type": "object"}}}},
                    "400": {"description": "«operasjoner» mangler eller er ugyldig JSON",
                            "content": {"application/json": {"schema": {
                                "$ref": "#/components/schemas/Feilsvar"}}}}}}},
            "/spor": {"post": {
                "summary": "Spørsmål/innhold fra dokument — eller rent spørsmål",
                "description": (
                    "1) fil uten sporsmal → HELE den utleste teksten ordrett (deterministisk)\n"
                    "2) fil + sporsmal → svar fra Borealis med tallvakt og vern\n"
                    "3) fil + sporsmal som er en JSON-mal → skjemautfylling med kodevalidering\n"
                    "4) sporsmal uten fil → generelt svar fra modellen (merkes uten_dokument)\n"
                    "Valgfritt: korriger=ja (LLM-korrigert OCR-tekst), jobb_id (spør mot ferdig jobb), "
                    "maks_sider (OCR-sidegrense)"),
                "requestBody": {"content": {"multipart/form-data": {"schema": {
                    "type": "object",
                    "properties": {"fil": fil_felt,
                                   "sporsmal": {"type": "string"},
                                   "jobb_id": {"type": "string"},
                                   "korriger": {"type": "string", "enum": ["ja"]},
                                   "maks_sider": {"type": "integer"}}}}}},
                "responses": {"200": {"description":
                    "svar, tall_verifisert, tolket_sporsmal, svar_avkortet, handskrift, strekkoder, "
                    "ocr_motorer, advarsel, fra_cache, tid_sekunder, kilde, versjon"}}}},
            "/jobb": {"post": {
                "summary": "Asynkron OCR av store dokumenter (ubegrenset antall sider)",
                "parameters": [{"name": "Idempotency-Key", "in": "header", "required": False,
                                "schema": {"type": "string", "format": "uuid"},
                                "description": "Retry-trygghet: samme nøkkel gir samme jobb "
                                               "(200 med idempotent_gjenbruk=true), aldri en dublett"}],
                "requestBody": {"content": {"multipart/form-data": {"schema": {
                    "type": "object", "required": ["fil"],
                    "properties": {"fil": fil_felt}}}}},
                "responses": {"202": {"description": "jobb_id + versjon — følg med på GET /jobb/{id}"}}}},
            "/jobb/{id}": {"get": {"summary": "Jobbstatus og fremdrift",
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description":
                    "status, versjon (for optimistisk låsing), sider_ferdig/sider_totalt, "
                    "tidsestimat, felter, datoer og dokumentdato (med «periode»: datospennet "
                    "fra–til og dato per side — særlig nyttig her, siden store skannede bunker "
                    "går via bakgrunnsjobber)"}}}},
            "/jobb/{id}/tekst": {"get": {"summary": "Hele den utleste teksten fra en ferdig jobb",
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "tekst, antall_tegn"}}}},
            "/jobb/{id}/avbryt": {"post": {"summary": "Avbryt en kø/pågående jobb",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
                    {"name": "versjon", "in": "query", "required": False,
                     "schema": {"type": "integer"},
                     "description": "Optimistisk låsing: 409 hvis jobben er endret siden denne versjonen"}],
                "responses": {"200": {"description": "status avbrytes + versjon"},
                              "409": {"description": "Versjonskonflikt eller jobben er i en sluttilstand"}}}},
            # /innsyn og /ekko manglet i spekken selv om de er fullverdige
            # ruter. For /ekko var det verst: det er DIAGNOSE-endepunktet
            # man trenger nettopp når noe ikke kommer fram — og det var
            # usynlig i Swagger, så ingen fant det uten å lese koden.
            "/innsyn": {"post": {
                "summary": "Direktevisning: strømmer lesingen hendelse for hendelse",
                "description":
                    "Starter en inspeksjonsøkt. Dokumentet behandles i en "
                    "bakgrunnstråd som strømmer hendelser (side rendret, "
                    "forbehandlet, hver region lest, andrepasset ...). "
                    "Poll GET /innsyn/{id}?fra=N. Sender ALDRI til Label "
                    "Studio — ren inspeksjon.",
                "requestBody": {"content": {"multipart/form-data": {"schema": {
                    "type": "object", "required": ["fil"],
                    "properties": {"fil": fil_felt}}}}},
                "responses": {"200": {"description": "innsyn_id"}}}},
            "/innsyn/{id}": {"get": {
                "summary": "Hendelsesstrømmen for en innsynsøkt",
                "parameters": [
                    {"name": "id", "in": "path", "required": True,
                     "schema": {"type": "string"}},
                    {"name": "fra", "in": "query", "required": False,
                     "schema": {"type": "integer"},
                     "description": "Indeks å hente fra — bruk «neste» fra "
                                    "forrige svar, så får du bare det nye"}],
                "responses": {"200": {"description":
                    "status, hendelser, neste, resultat, feil"}}}},
            "/forhandssjekk": {"post": {
                "summary": "Kvalitetsdom FØR prosessering — avvis dårlige skann uten å bruke GPU",
                "description":
                    "Rendrer sidene ved samme oppløsning som OCR ville "
                    "brukt og måler skarphet, lys, oppløsning (dpi) og "
                    "tomme sider — men kjører ALDRI OCR og rører aldri "
                    "modellen. Svarer på ~sekundet.\n\n"
                    "Bruk «dom» som port i roboten: god → POST /dokument; "
                    "tvilsom → prosesser, men flagg for menneskelig "
                    "kontroll; avvis → be om nytt skann.\n\n"
                    "Dokumenter MED tekstlag får alltid dommen «god» uten "
                    "sidevurderinger: OCR kjøres aldri på dem, så "
                    "skannkvalitet er irrelevant.",
                "requestBody": {"content": {"multipart/form-data": {"schema": {
                    "type": "object", "required": ["fil"],
                    "properties": {
                        "fil": fil_felt,
                        "maks_sider": {"type": "integer",
                                       "description": "Hvor mange sider som "
                                                      "vurderes (tak 10)"}}}}}},
                "responses": {
                    "200": {"description": "Kvalitetsdom",
                            "content": {"application/json": {"schema": {
                                "$ref": "#/components/schemas/"
                                        "ForhandssjekkSvar"}}}},
                    "400": {"description": "Manglende fil eller korrupt PDF",
                            "content": {"application/json": {"schema": {
                                "$ref": "#/components/schemas/Feilsvar"}}}}}}},
            "/sladd": {"post": {
                "summary": "Sladd beviste identifikatorer — fnr, konto, orgnr, KID, telefon, epost",
                "description":
                    "Sladder KUN det som kan BEVISES: fødselsnummer, "
                    "kontonummer og organisasjonsnummer er mod11-validert, "
                    "KID sjekksumvalidert (med etikettkrav), telefon og "
                    "epost formatvalidert. Matematikk, aldri modell. Hvert "
                    "funn erstattes synlig med «[SLADDET type]».\n\n"
                    "**Grensen sies i hvert svar:** navn og adresser "
                    "sladdes IKKE — de kan ikke bevises deterministisk, og "
                    "en gjettet sladding som ser fullført ut er farligere "
                    "enn ingen. Sladdingen er derfor ikke alene "
                    "tilstrekkelig for offentliggjøring (offentleglova); "
                    "manuell gjennomgang er påkrevd.\n\n"
                    "For skannede dokumenter kjøres OCR først. Merk "
                    "OCR-forbeholdet i «advarsler»: et feillest siffer gjør "
                    "at sjekksummen ikke slår til, og nummeret blir stående "
                    "usladdet.",
                "requestBody": {"content": {"multipart/form-data": {"schema": {
                    "type": "object", "required": ["fil"],
                    "properties": {
                        "fil": fil_felt,
                        "typer": {"type": "string",
                                  "description": "Kommaseparert utvalg, "
                                                 "f.eks. «fodselsnummer,"
                                                 "telefon». Standard: alle. "
                                                 "Gyldige: fodselsnummer, "
                                                 "kontonummer, "
                                                 "organisasjonsnummer, kid, "
                                                 "telefon, epost"},
                        "maks_sider": {"type": "integer"}}}}}},
                "responses": {
                    "200": {"description": "Sladdet tekst + funn",
                            "content": {"application/json": {"schema": {
                                "$ref": "#/components/schemas/SladdSvar"}}}},
                    "400": {"description": "Manglende fil eller ukjent type i 'typer'",
                            "content": {"application/json": {"schema": {
                                "$ref": "#/components/schemas/Feilsvar"}}}}}}},
            "/ekko": {"post": {
                "summary": "Diagnose: svarer med NØYAKTIG hva serveren mottok fra deg",
                "description":
                    "Behandler ikke dokumentet. «raa_deler» viser hver "
                    "multipart-dels Content-Disposition slik den FAKTISK "
                    "kom, og «parser_ser» hva parseren fikk ut av den. "
                    "Bruk denne FØR du gjetter på klientoppsettet: kommer "
                    "et tekstfelt ikke fram, ser du her om det ble sendt i "
                    "det hele tatt, og med hvilket feltnavn.",
                "requestBody": {"content": {"multipart/form-data": {"schema": {
                    "type": "object",
                    "properties": {"fil": fil_felt}}}}},
                "responses": {"200": {
                    "description": "Nøyaktig hva serveren mottok",
                    "content": {"application/json": {"schema": {
                        "$ref": "#/components/schemas/EkkoSvar"}}}}}}},
        },
    }


# Endepunktguiden som vises UNDER endepunktlista på /dokumentasjon.
#
# Hvorfor under og ikke i info.description: Swagger UI plasserer
# beskrivelsen ØVERST, før lista. Den som blar gjennom endepunktene og
# lurer på «hvilket av disse skal jeg bruke, og hvorfor» er da ferdig med
# å lese før spørsmålet melder seg. Guiden hører hjemme der spørsmålet
# faktisk oppstår — rett under lista.
#
# Ren HTML med innebygde stiler, ingen markdown-bibliotek: prosjektet
# skal kunne kopieres og kjøre uten nedlastinger (CLAUDE.md §1).
_ENDEPUNKTGUIDE_HTML = """
<div class="veiledning">
<section>
<h2>Hvilket endepunkt skal jeg bruke?</h2>
<table>
<tr><th>Vil du …</th><th>Bruk</th></tr>
<tr><td>Ha ETT kall som gjør alt du trenger</td><td><code>POST /dokument</code> <span class="anbefalt">← anbefalt</span></td></tr>
<tr><td>Bare lese teksten ordrett</td><td>POST /spor (uten <code>sporsmal</code>)</td></tr>
<tr><td>Ha komplett strukturert JSON med faste nøkler</td><td>POST /uttrekk</td></tr>
<tr><td>Fylle din egen JSON-mal</td><td>POST /dokument med <code>skjema_mal</code></td></tr>
<tr><td>Behandle et STORT skannet dokument</td><td>POST /jobb → GET /jobb/{id}</td></tr>
<tr><td>Se lesingen skje LIVE</td><td>POST /innsyn</td></tr>
<tr><td>Finne ut hva serveren FAKTISK mottok fra deg</td><td><b>POST /ekko</b></td></tr>
</table>

<p><b>POST /dokument er hovedveien.</b> De andre dokumentendepunktene er
eldre og beholdes bevisst for ikke å bryte eksisterende integrasjoner.
De gir stort sett SAMME fakta, men i ULIKE JSON-former.</p>

<p class="advarsel">Endepunktene deler bare <code>ok</code>,
<code>tekst</code> og <code>strekkoder</code> på toppnivå. Bytter du
endepunkt, brekker klientens JSON-stier. Velg ett og bli der.</p>
</section>

<section>
<h2>Endepunktene — hva, hvordan og hvorfor</h2>

<h3>POST /dokument — samlet endepunkt</h3>
<p><b>Hva:</b> Ett kall med brytere. Dokumentet leses <b>én gang</b>
uansett hvor mange deler du ber om.</p>
<pre>fil=@dokument.pdf
felter=ja                              # standard: på
struktur=ja                            # alt /uttrekk gir, under «struktur»
sporsmal=Hva er totalbeløpet?          # slår på «svar» av seg selv
skjema_mal={"total":"{totalbelop}"}    # slår på «skjema» av seg selv
skjema_motor=auto                      # felter | auto | modell</pre>
<p><b>Hvorfor:</b> Modelldelene er AV som standard, så det raske forblir
raskt. Du slipper å velge mellom endepunkter, og JSON-stiene dine flytter
seg ikke når du senere trenger mer.</p>

<h3>POST /uttrekk — fast, komplett skjema</h3>
<p><b>Hva:</b> Alle nøkler ALLTID til stede; tomt er <code>""</code> /
<code>[]</code>. Aldri modell.</p>
<p><b>Hvorfor:</b> Når klienten din ikke tåler at en nøkkel mangler.</p>
<p><b>Merk formen:</b> <code>belop</code> er en LISTE av objekter med
kontekst, ikke ett tall:
<code>[{"verdi": 463.0, "raatekst": "463,00", "kontekst": "…"}]</code>.
Dokumentets EGEN dato ligger i <code>dokument.dokumentdato</code> — i
<code>datoer</code> ligger datoene dokumentet HANDLER om.</p>

<h3>POST /analyser — deterministisk analyse</h3>
<p><b>Hva:</b> Felter, alle datoer klassifisert med begrunnelse,
strekkoder, håndskrift, full tekst. Aldri modell.</p>
<p><b>Hvorfor:</b> <code>trenger_ocr</code> finnes ikke noe annet sted.</p>

<h3>POST /spor — den eldste veien</h3>
<table>
<tr><th>Du sender</th><th>Du får</th><th>Modell?</th></tr>
<tr><td><code>fil</code> alene</td><td>HELE teksten ordrett</td><td><b>nei</b> (R47)</td></tr>
<tr><td><code>fil</code> + <code>sporsmal</code></td><td>Svar fra Borealis med tallvakt</td><td>ja</td></tr>
<tr><td><code>fil</code> + JSON-mal i <code>sporsmal</code></td><td>Rutes til skjemautfylling</td><td>ja</td></tr>
<tr><td><code>sporsmal</code> alene</td><td>Generelt svar, merket <code>uten_dokument</code></td><td>ja</td></tr>
<tr><td><code>jobb_id</code> + <code>sporsmal</code></td><td>Svar mot en ferdig jobb</td><td>ja</td></tr>
</table>
<p><b>Hvorfor:</b> Fil uten spørsmål er korteste vei til ren tekst.
Trenger du både svar OG felter i samme kall, bruk /dokument.</p>

<h3>POST /fyll_skjema — fyll din egen mal</h3>
<p class="advarsel">Feltet heter <code>skjema</code> her — ikke
<code>skjema_mal</code>. Motorfeltet heter <code>skjema_motor</code> på
begge endepunktene. Dette er den vanligste fella.</p>
<p><b>De tre motorene (gjelder også /dokument):</b></p>
<table>
<tr><th>Motor</th><th>Modell?</th><th>Hva den gjør</th></tr>
<tr><td><code>felter</code></td><td>nei</td><td>Fletter <code>{feltnavn}</code> deterministisk. Virker selv om Borealis er nede.</td></tr>
<tr><td><code>auto</code></td><td>delvis</td><td>Regel der den kan BEVISE, modell for resten. Gir <code>kilde_per_felt</code>.</td></tr>
<tr><td><code>modell</code></td><td>ja</td><td>Borealis fyller, koden validerer. Standard.</td></tr>
</table>
<p><b>Hvorfor <code>auto</code> som regel:</b> du får bevis der bevis
finnes, og <code>kilde_per_felt</code> sier nøyaktig hvilke felter som er
gjettet.</p>

<h3>POST /jobb → GET /jobb/{id} — store dokumenter</h3>
<p><b>Hva:</b> OCR av hele dokumentet i bakgrunnen. <code>jobb_id</code>
med en gang, fremdrift og tidsestimat underveis, og <code>felter</code>
/ <code>datoer</code> / <code>dokumentdato</code> når den er ferdig.</p>
<p><b>Hvordan:</b> POST /jobb → poll GET /jobb/{id} → POST /spor med
<code>jobb_id</code> for å spørre uten å sende fila på nytt.</p>
<p><b>Hvorfor:</b> Når dokumentet er for stort til å vente på i ett kall.
Send <code>Idempotency-Key</code> for retry-trygghet: samme nøkkel gir
samme jobb, aldri en dublett.</p>

<h3>POST /innsyn — direktevisning</h3>
<p><b>Hva:</b> Strømmer lesingen hendelse for hendelse (side rendret,
forbehandlet, hver region lest, andrepasset …).</p>
<p><b>Hvordan:</b> POST /innsyn → poll GET /innsyn/{id}?fra=N. Bruk
<code>neste</code> fra forrige svar som <code>fra</code>, så får du bare
det nye.</p>
<p><b>Hvorfor:</b> Laget for GUI-et, som tegner prosessen live. Sender
ALDRI til Label Studio — ren inspeksjon.</p>

<h3>POST /ekko — diagnose</h3>
<p><b>Hva:</b> Svarer med NØYAKTIG hva serveren mottok. Behandler ikke
dokumentet.</p>
<p><b>Hvorfor:</b> Kommer et felt ikke fram, viser <code>raa_deler</code>
den rå Content-Disposition slik den FAKTISK kom, og
<code>parser_ser</code> hva parseren fikk ut. <b>Bruk denne før du gjetter
på klientoppsettet</b> — det er forskjellen på å se problemet og å gjette
på det.</p>
</section>

<section>
<h2>Er svaret BEVIST eller GJETTET?</h2>
<table>
<tr><th>Felt</th><th>Betyr</th></tr>
<tr><td><code>kilde</code></td><td>Inneholder «borealis» ⇒ modellen bidro. Ellers rent deterministisk.</td></tr>
<tr><td><code>kilde_per_felt</code></td><td>(<code>auto</code>) Hvilke felter som er bevist, hvilke som er gjettet</td></tr>
<tr><td><code>tall_verifisert</code></td><td>Hvert tall i svaret står ORDRETT i dokumentet</td></tr>
<tr><td><code>avvik</code></td><td>Hva kodevalideringen måtte gripe inn i</td></tr>
<tr><td><code>advarsler</code></td><td>Bl.a. ukjente felt som ble ignorert</td></tr>
<tr><td><code>versjon.uttrekk_regler</code></td><td>Hvilken regelversjon som svarte</td></tr>
</table>
<p>Raskeste sjekk en robot kan gjøre: <code>kilde</code> inneholder
«borealis» ⇒ la et menneske se på det. <code>kilde</code> er
«deterministisk» ⇒ regex + mod11, ingen gjetning.</p>
</section>

<section>
<h2>Klientfeller (UiPath / .NET)</h2>
<p><b>Argumentrekkefølge — BEGGE tar verdien først, navnet sist:</b></p>
<pre>New FileFormDataPart(filsti, "fil")
New TextFormDataPart("auto", "skjema_motor")</pre>
<p>Snur du det, kaster UiPath «The format of value '{…}' is invalid» FØR
requesten sendes — andre argument er NAVNET og må være et gyldig token.
Slipper en verdi likevel gjennom som feltnavn, svarer API-et 400 med
presis retting.</p>
<p><b>Ukjent feltnavn</b> gir aldri stille tap: du får en linje i
<code>advarsler</code> (eller <code>kvalitet.advarsler</code>) som sier
hva som ble ignorert og hvilke felt endepunktet kjenner.</p>
</section>
</div>
"""

_SWAGGER_HTML = """<!DOCTYPE html>
<html lang="no"><head><meta charset="utf-8">
<title>NAV dokument-API — dokumentasjon</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
<style>
/* Følger Swagger UI sitt formspråk: samme bredde (.wrapper = 1460px),
   samme skriftstakk, samme kortflate med kant og skygge som
   .opblock-tag-section, og samme tekstfarge (#3b4151). Guiden skal se
   ut som en del av siden, ikke som noe limt på etterpå. */
.veiledning{max-width:1460px;margin:0 auto;padding:0 20px 60px;
  box-sizing:border-box;
  font-family:"Open Sans","Helvetica Neue",Helvetica,Arial,sans-serif;
  color:#3b4151;line-height:1.6;font-size:14px}
.veiledning section{background:#fff;border:1px solid rgba(59,65,81,.3);
  border-radius:4px;box-shadow:0 1px 2px rgba(0,0,0,.15);
  padding:14px 20px 20px;margin:20px 0}
.veiledning h2{font-family:"Titillium Web","Open Sans",sans-serif;
  font-size:24px;font-weight:700;color:#3b4151;margin:0 0 12px}
.veiledning h3{font-family:"Titillium Web","Open Sans",sans-serif;
  font-size:17px;font-weight:600;color:#3b4151;
  margin:22px 0 6px;padding-bottom:5px;border-bottom:1px solid #ebebeb}
.veiledning table{border-collapse:collapse;width:100%;margin:10px 0 16px}
.veiledning th,.veiledning td{border-bottom:1px solid #ebebeb;
  padding:8px 10px;text-align:left;vertical-align:top}
.veiledning th{font-family:"Titillium Web","Open Sans",sans-serif;
  font-weight:700;color:#3b4151;border-bottom:2px solid #ebebeb}
.veiledning tr:last-child td{border-bottom:none}
.veiledning code{background:rgba(0,0,0,.05);padding:1px 5px;
  border-radius:3px;font-family:"Source Code Pro",monospace;font-size:12px;
  color:#9012fe}
.veiledning pre{background:#41444e;color:#fff;padding:12px 14px;
  border-radius:4px;overflow-x:auto;font-size:12px;line-height:1.6;
  font-family:"Source Code Pro",monospace}
.veiledning p{margin:8px 0}
.veiledning .advarsel{border-left:4px solid #fca130;background:#fcf3e6;
  padding:10px 14px;margin:12px 0;border-radius:0 4px 4px 0}
.veiledning .anbefalt{color:#49cc90;font-weight:700}
@media (prefers-color-scheme:dark){
  .veiledning{color:#d7dade}
  .veiledning section{background:#1f2226;border-color:#3a3f44;
    box-shadow:none}
  .veiledning h2,.veiledning h3,.veiledning th{color:#e8eaed}
  .veiledning h3,.veiledning th,.veiledning td{border-color:#3a3f44}
  .veiledning code{background:rgba(255,255,255,.08);color:#c792ea}
  .veiledning .advarsel{background:#332a1c;border-left-color:#fca130}
}
</style>
</head><body>
<div id="swagger-ui"></div>
__VEILEDNING__
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
// defaultModelsExpandDepth: 0 viser «Schemas»-seksjonen under endepunkt-
// lista med hver modell sammenslått. -1 (som før) skjuler den helt — da
// fantes svarmodellene bare i koden, og en integrator måtte kalle API-et
// for å se hva feltene het.
SwaggerUIBundle({url: "/openapi.json", dom_id: "#swagger-ui",
                 docExpansion: "list", defaultModelsExpandDepth: 0,
                 onComplete: function () {
                   // Seksjonen rendres sammenslått, så modellnavnene er
                   // usynlige til man vet at man skal klikke. Åpne den én
                   // gang ved lasting: lista over navn er hele poenget.
                   var k = document.querySelector(".models-control");
                   if (k && k.getAttribute("aria-expanded") === "false") {
                     k.click();
                   }
                 }});
</script>
</body></html>""".replace("__VEILEDNING__", _ENDEPUNKTGUIDE_HTML)


# ------------------------------------------------------------------ #
#  HTTP                                                               #
# ------------------------------------------------------------------ #

class Handler(BaseHTTPRequestHandler):
    # Frist på selve socketen. socketserver kaller connection.settimeout()
    # BARE når dette attributtet ikke er None — og standarden er None, så
    # rfile.read() blokkerte i det uendelige.
    #
    # Det gjorde samtidighetsvakten om til en angrepsflate: køplassen tas
    # før kroppen leses, så en klient som sender «Content-Length:
    # 200000000» og deretter ingenting, holdt plassen for alltid. Med den
    # målte grensen (gulvet 2 på et fullt 8 GB-kort) var TO slike nok til
    # å låse /analyser, /spor, /uttrekk, /fyll_skjema og /dokument
    # permanent — do_POST sin finally-blokk nås jo aldri. Det skjer også
    # utilsiktet: et mobilnett som dropper midt i en stor opplasting.
    # Nå avbrytes lesingen, unntaket propagerer, og plassen frigjøres.
    timeout = float(os.environ.get("SOCKET_TIDSAVBRUDD_S", "120"))

    def handle_one_request(self):
        """Som standard, men en socket-frist skal gi en ryddig avslutning
        av tilkoblingen — ikke en traceback i loggen for hver klient som
        mister nettet."""
        try:
            return super().handle_one_request()
        except (TimeoutError, socket.timeout):
            self.close_connection = True

    def _autorisert(self) -> bool:
        """R38: er en nøkkel satt, kreves matchende X-API-Key-header.
        Ingen nøkler = åpen modus (kun for lokal testing uten sensitive
        data).

        Sideeffekt: setter `self._klient_id` til navnet på klienten, som
        tilgangsloggen bruker. Sammenligningen går over ALLE nøklene uten
        tidlig utgang — se delt/klienter.py."""
        if not API_NOKKEL and not API_NOKLER:
            self._klient_id = AAPEN
            return True
        navn = finn_klient(self.headers.get("X-API-Key", ""),
                           API_NOKLER, API_NOKKEL)
        self._klient_id = navn
        return navn is not None

    def _klient_ip(self) -> str:
        """Klient-IP for rate-limiting. Bak en tunnel/gateway er socket-IP-en
        localhost, så vi foretrekker den videresendte IP-en (kun til
        rate-limit, ALDRI som sikkerhetsgrense — den kan forfalskes)."""
        for h in ("CF-Connecting-IP", "X-Forwarded-For"):
            v = self.headers.get(h, "").split(",")[0].strip()
            if v:
                return v
        try:
            return self.client_address[0]
        except Exception:
            return "?"

    def _rate_ok(self) -> bool:
        """True hvis innenfor grensen. Skriver 429 og returnerer False hvis
        ikke."""
        if _rate_tillatt(self._klient_ip()):
            return True
        self._svar(429, {"ok": False,
                         "feil": f"For mange forespørsler (grense "
                                 f"{RATE_LIMIT_PER_MIN}/min per klient). "
                                 "Vent litt og prøv igjen."})
        return False

    def _cors_origin(self):
        """Hvilket Access-Control-Allow-Origin skal svaret ha? None =
        ingen header (restriktivt). Ekko av forespørselens Origin kun når
        det står på den konfigurerte whitelisten (aldri blindt «*»)."""
        if not CORS_ORIGINS:
            return None
        if CORS_ORIGINS == "*":
            return "*"
        origin = self.headers.get("Origin", "")
        tillatte = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
        return origin if origin in tillatte else None

    def _serverfeil(self, exc):
        """En uventet feil skal LOGGES i sin helhet på serveren, men bare
        gi klienten en generisk melding. Den fulle exceptionen (type,
        melding, stakksporing) kunne lekke interne stier, spørringer og
        biblioteksdetaljer til enhver som treffer et endepunkt."""
        import traceback
        korr = self._korrelasjonsid()
        # Skriv korrelasjons-ID-en SAMMEN med stakksporet, så en bruker som
        # oppgir uuid-en fører deg rett til akkurat denne feilen i loggen.
        print(f"!!! Uventet serverfeil (korrelasjon={korr}):", file=sys.stderr)
        traceback.print_exc()
        try:
            return self._svar(500, {
                "ok": False,
                "feil": "Uventet serverfeil — detaljene står i serverloggen.",
            })
        except Exception:
            pass

    def _tar_gzip(self) -> bool:
        """Sa klienten at den tåler gzip?

        Bare `gzip` godtas — ikke `*`. En klient som sender `*` har ikke
        sagt noe om gzip spesifikt, og her er kostnaden ved å ta feil
        (et uleselig svar hos en RPA-robot) større enn gevinsten."""
        felt = (self.headers.get("Accept-Encoding") or "").lower()
        for ledd in felt.split(","):
            navn, _, resten = ledd.strip().partition(";")
            if navn.strip() != "gzip":
                continue
            # «gzip;q=0» betyr uttrykkelig NEI
            if "q=0" in resten.replace(" ", "") and "q=0." not in resten.replace(" ", ""):
                return False
            return True
        return False

    def _svar(self, kode, data, hoder: dict = None):
        # R39/§4: berik versjon-blokken med full proveniens (modell/regel/
        # terskel) i ÉTT punkt. Additivt — eksisterende nøkler (api, prompt,
        # modell) beholdes, så ingen klient brytes.
        korr = self._korrelasjonsid()
        if isinstance(data, dict):
            if isinstance(data.get("versjon"), dict):
                data["versjon"] = {**_versjon_stempel(), **data["versjon"]}
            # Feilsvar får ALLTID en uuid = korrelasjons-ID-en (NAV-
            # konvensjon: {uuid, feilmelding}). Brukeren oppgir den til
            # support, som slår den opp i loggen — i stedet for å lete
            # etter «noe som skjedde rundt det tidspunktet». Legges bare på
            # feil (ok=False), så vellykkede svar beholder formen sin.
            if data.get("ok") is False:
                if "uuid" not in data:
                    data["uuid"] = korr
                # RFC 9457 Problem Details: ett STANDARDISERT feilobjekt
                # (som NAV Oppgave-APIet), bygget ÉN gang her — de gamle
                # feltene (ok/feil/uuid) beholdes, så ingen klient brytes,
                # men en klient som forstår standarden får {type, title,
                # status, detail, traceId} også.
                if "problem" not in data:
                    data["problem"] = _problem_detaljer(
                        kode, data.get("feil"), korr, self._sti(),
                        data.pop("felter_feil", None))
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        # gzip når klienten sier den tåler det. Målt på et vanlig
        # /dokument-svar: 33 424 → 6 422 byte (−80,8 %). Innrykket alene
        # er 20,9 % av svaret, og over en tunnel er dette den klart
        # største enkeltgevinsten — uten å endre en eneste nøkkel.
        # Ligger bak Accept-Encoding, så en klient som ikke ber om det
        # (UiPath med egen HTTP-aktivitet) merker ingen forskjell.
        komprimert = None
        if len(payload) >= GZIP_MINSTE_BYTE and self._tar_gzip():
            komprimert = gzip.compress(payload, GZIP_NIVAA)
            # bare bruk den hvis den faktisk ble mindre
            if len(komprimert) < len(payload):
                payload = komprimert
            else:
                komprimert = None
        self.send_response(kode)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if komprimert is not None:
            self.send_header("Content-Encoding", "gzip")
            # svaret varierer med Accept-Encoding — mellomlagre må vite det
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(payload)))
        # Ekko korrelasjons-ID-en så klienten kan logge den sin side og
        # koble sitt kall til vår logglinje.
        self.send_header("X-Correlation-ID", korr)
        for navn, verdi in (hoder or {}).items():
            self.send_header(navn, str(verdi))
        opphav = self._cors_origin()
        if opphav:
            self.send_header("Access-Control-Allow-Origin", opphav)
        self.end_headers()
        # HEAD/204 og lignende har ingen kropp; men alle våre svar er JSON.
        self.wfile.write(payload)

    def _tapp_kropp(self, lengde: int) -> None:
        """Les og forkast kroppen i biter. Uten dette blir en AVVIST
        forespørsels kropp liggende i socket-bufferet og tolkes som starten
        på neste forespørsel på samme (keep-alive) tilkobling."""
        igjen = max(0, lengde)
        while igjen > 0:
            bit = self.rfile.read(min(65536, igjen))
            if not bit:
                break
            igjen -= len(bit)

    def _html(self, innhold: str):
        payload = innhold.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self._t0_req = time.time()
        # CORS-preflight for nettleserklienter — svarer kun med tillatelse
        # når opphavet er på whitelisten (se _cors_origin / CORS_ORIGINS).
        self.send_response(204)
        opphav = self._cors_origin()
        if opphav:
            self.send_header("Access-Control-Allow-Origin", opphav)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key")
        self.end_headers()

    def _sti(self) -> str:
        """Stien uten query-streng og uten etterfølgende skråstrek —
        så «/spor?x=1» og «/spor/» rutes som «/spor».

        Kanonisk prefiks «/api/v1» strippes (NAV-konvensjon):
        /api/v1/spor og /spor er SAMME endepunkt. De gamle stiene består
        som alias, så ingen eksisterende klient brekker — og en fremtidig
        v2 med brytende endringer kan leve side om side med v1."""
        sti = self.path.split("?", 1)[0].rstrip("/")
        if sti in (API_PREFIKS, V1_PREFIKS):
            return "/hjelp"
        if sti.startswith(V1_PREFIKS + "/"):
            return sti[len(V1_PREFIKS):]
        # «/api/…» strippes ellers også — MEN ikke når neste ledd er et
        # versjonsnummer. Uten unntaket ble /api/v2/dokument til
        # /v2/dokument, og v2-ruten svarte 404. Docstringen over lovet
        # nettopp at en framtidig v2 skulle kunne leve side om side med
        # v1; den generelle strippingen tok livet av sitt eget løfte.
        if sti.startswith(API_PREFIKS + "/") and not _VERSJONSLEDD.match(sti):
            return sti[len(API_PREFIKS):]
        return sti

    def _korrelasjonsid(self) -> str:
        """X-Correlation-ID for sporing PÅ TVERS av tjenester (NAV-
        konvensjon). Kommer den fra klienten, beholdes den — da kan én
        sak følges gjennom Oppgave → Dokarkiv → oss i én samlet logg.
        Mangler den, lager vi en, så svaret og loggen ALLTID har en å
        oppgi. Bufres per forespørsel så svar og logg får samme verdi.

        Verdien er klientstyrt og havner i et svar-hode og i loggen, så
        den saneres: bare trygge tegn, maks 64. Ellers kunne en injisert
        CR/LF splittet svar-hoder eller forfalsket en loggrad."""
        if getattr(self, "_korr_id", None) is None:
            raa = (self.headers.get("X-Correlation-ID")
                   or self.headers.get("X-Correlation-Id") or "")
            # bare tegn som er trygge i et HTTP-hode og en JSON-loggrad:
            # bokstaver, tall, bindestrek, punktum, understrek. CR/LF og
            # kolon fjernes helt, så ingen kan splitte hoder eller
            # forfalske en loggrad via denne klientstyrte verdien.
            trygg = re.sub(r"[^A-Za-z0-9._-]", "", raa)[:64]
            self._korr_id = trygg or uuid.uuid4().hex
        return self._korr_id

    def _forventet_versjon(self):
        """Klientens forventede jobb-versjon for optimistisk låsing, fra
        ?versjon=N eller X-Versjon-headeren. None hvis ikke oppgitt (da
        gjelder ingen låsing). Ugyldig verdi behandles som None."""
        from urllib.parse import parse_qs, urlparse
        raa = (parse_qs(urlparse(self.path).query).get("versjon", [None])[0]
               or self.headers.get("X-Versjon"))
        try:
            return int(raa) if raa is not None else None
        except (ValueError, TypeError):
            return None

    def do_GET(self):
        self._t0_req = time.time()
        # Samme sikkerhetsnett som do_POST: uventet feil → ærlig JSON-500,
        # aldri en taus lukket forbindelse (som blir 502 i en tunnel)
        try:
            return self._do_get_intern()
        except Exception as exc:
            return self._serverfeil(exc)

    def _do_get_intern(self):
        sti = self._sti()
        if sti not in ("", "/hjelp") and not self._rate_ok():
            return
        if sti == "/openapi.json":
            return self._svar(200, _openapi())
        if sti.startswith("/innsyn/"):
            # Direktevisnings-poll: hendelser fra og med ?fra=N + resultat.
            # SAMME nøkkelkrav som GET /jobb/<id>: svaret inneholder hele
            # den utleste teksten OG base64-sidebilder av dokumentet.
            # Uten denne vakten kunne en 48-bits id — som havner i
            # tilgangslogg, proxy og nettleserhistorikk — hentes ut av
            # hvem som helst. Målt før fiksen: 246 KB dokumentinnhold
            # uten en eneste header.
            if not self._autorisert():
                return self._svar(401, {
                    "ok": False,
                    "feil": "Ugyldig eller manglende X-API-Key"})
            okt = _innsyn_okter.get(sti.split("/")[2])
            if okt is None:
                return self._svar(404, {"ok": False, "feil": "Ukjent innsyn_id"})
            try:
                from urllib.parse import parse_qs, urlparse
                fra = int(parse_qs(urlparse(self.path).query)
                          .get("fra", ["0"])[0])
            except (ValueError, IndexError):
                fra = 0
            hendelser = okt["hendelser"]
            return self._svar(200, {
                "ok": True, "status": okt["status"],
                "hendelser": hendelser[fra:], "neste": len(hendelser),
                "resultat": okt["resultat"] if okt["status"] == "ferdig" else None,
                "feil": okt.get("feil")})
        if sti in ("/dokumentasjon", "/docs"):
            return self._html(_SWAGGER_HTML)
        if sti in ("", "/hjelp"):
            return self._svar(200, {
                "tjeneste": "NAV dokument-API (generelt)",
                "dokumentasjon": "GET /dokumentasjon (Swagger UI) · GET /openapi.json (OpenAPI 3)",
                "endepunkter": {
                    "POST /dokument": ("ETT kall med brytere: felter=ja/nei (standard ja), "
                                       "struktur=ja/nei, svar=ja/nei (+sporsmal), skjema=ja/nei "
                                       "(+skjema_mal, +skjema_motor felter/modell/auto), "
                                       "korriger=ja/nei, tekst=ja/nei — dokumentet "
                                       "leses ÉN gang; modelldelene er AV som standard, så det "
                                       "raske forblir raskt. ALTERNATIVT: felt 'operasjoner' "
                                       "(JSON-liste av {type,…}) → {ok, resultater:[…]} via "
                                       "operasjonsmotoren (uniform, utvidbar form)"),
                    "POST /analyser": "multipart/form-data, felt 'fil' → deterministiske felter + trenger_ocr",
                    "POST /spor": ("felter 'fil' + 'sporsmal' (eller 'jobb_id' + 'sporsmal') → svar fra Borealis; "
                                   "fil UTEN 'sporsmal' → hele den utleste teksten ordrett (deterministisk); "
                                   "valgfritt korriger=ja → LLM-korrigert OCR-tekst"),
                    "POST /uttrekk": ("felt 'fil' → KOMPLETT strukturert JSON: alle identifikatorer "
                                      "(sjekksumvalidert), kontakt, adresser, datoer, perioder, beløp, "
                                      "strekkoder, håndskrift, kvalitet — alle nøkler alltid til stede"),
                    "POST /fyll_skjema": ("felter 'fil' + 'skjema' (din egen JSON-mal) → malen utfylt "
                                          "fra dokumentet, kodevalidert felt for felt (avvik rapporteres)"),
                    "POST /jobb": "felt 'fil' → jobb_id med en gang; OCR av HELE dokumentet kjører i bakgrunnen",
                    "POST /innsyn": ("felt 'fil' → innsyn_id; direktevisning av lesingen — "
                                     "poll GET /innsyn/<id>?fra=N for hendelsesstrømmen"),
                    "GET /jobb/<id>": ("status + fremdrift (sider_ferdig/sider_totalt, "
                                       "tidsestimat); når jobben er ferdig også felter, "
                                       "datoer og dokumentdato med datospenn per side"),
                    "GET /jobb/<id>/tekst": "hele den utlestne teksten når jobben er ferdig",
                    "POST /jobb/<id>/avbryt": "stopp en kø/pågående jobb",
                },
                "datoer": ("dokumentets EGEN dato (dokumentdato) skilles fra datoene i "
                           "innholdet: hver dato får en «rolle» (dokument/innhold/behandling/"
                           "ukjent), og dokumentdatoen velges deterministisk etter styrken på "
                           "beviset — etikett (vedtaksdato/utstedt/datert) > dato øverst på "
                           "en side eller ved en signaturblokk > PDF-metadata. dokumentdato."
                           "periode gir datospennet FRA–TIL med dato per side: én dato for et "
                           "enkelt brev, en periode når filen er en bunke daterte dokumenter. "
                           "Kategorifeltene har både rå streng («type», «rolle») OG et kodet "
                           "par «type_kodet»/«rolle_kodet» {kode, term} (AAREG-stil): kode er "
                           "stabil/maskinlesbar, term er for et menneske. "
                           "Finnes ingen, sies det ærlig i stedet for å gjette. Egne "
                           "etiketter: regler/egne_etiketter.txt («ord = type = rolle»)"),
                "filtyper": "PDF, bilder (JPG/PNG/TIFF/BMP/WEBP — OCR-es), DOCX, XLSX/XLSM, CSV, TXT",
                "ocr": ("regionbasert ruting når PDF-en mangler tekstlag: EasyOCR (trykt) + "
                        "norhand (norsk håndskrift) per region, flettet i leserekkefølge"),
                "grenser": {
                    "opplasting_mb": MAKS_BYTES // 1024 // 1024,
                    "ocr_sider_synkront": f"{OCR_MAKS_SIDER} (øk per forespørsel med maks_sider, tak {OCR_TAK_SIDER})",
                    "ocr_sider_jobb": "ubegrenset — bruk POST /jobb for store skannede dokumenter",
                    "llm_tegn_direkte": f"{MAKS_LLM_TEGN} + deterministisk uttrekk fra hele dokumentet",
                },
                "strekkoder": "Code128/EAN/QR m.fl. dekodes automatisk (pyzbar) og legges ved svaret",
                "kapasitet": {
                    **_kapasitet_port.status(),
                    "koe_vent_s": KOE_VENT_S,
                    "opplasting_i_minnet_mb": MAKS_SAMTIDIGE_MB,
                    "forklaring": (
                        "Grensen er MÅLT på denne maskinen, ikke fast: flere kort, "
                        "mer ledig minne eller flere kjerner gir automatisk plass til "
                        "flere samtidige klienter (måles på nytt hvert "
                        f"{int(KAPASITET_MAAL_S)}. sekund, uten omstart). «binder» "
                        "sier hvilken ressurs som holder tallet nede. Overstyr med "
                        "MAKS_SAMTIDIGE_TUNGE. MERK: OCR kjører fortsatt én side om "
                        "gangen per kort — flere kort hever grensen og lar "
                        "språkmodellen og OCR jobbe side om side, men full "
                        "parallell OCR krever én modellinstans per kort."),
                },
                "sporing": ("Send X-Correlation-ID for å følge en sak på tvers av "
                            "tjenester — den ekkoes i svaret og logges. Feilsvar har "
                            "{ok:false, feil, uuid} der uuid er korrelasjons-ID-en. "
                            "Stiene svarer også med /api/v1-prefiks."),
                "sikkerhet": ("X-API-Key kreves på alle endepunkter" if API_NOKKEL else
                              "ÅPEN — sett miljøvariabelen API_NOKKEL for å kreve X-API-Key"),
                "versjon": {"api": API_VERSJON, "prompt": prompter.versjon()},
                "borealis": _borealis["status"],
                "borealis_motor": _borealis["motor"],
                "borealis_modell": _borealis["modellfil"],
                # R51: hvilken enhet OCR faktisk endte på. En stille
                # CPU-fallback (fullt kort) er 20× tregere — den skal
                # være synlig her, ikke noe man må måle seg fram til.
                "ocr": _ocr_status(),
                "klient_eksempel": ("Enhver HTTP-klient (GUI, UiPath, curl, egne skript): "
                                    "POST med filen som multipart-felt 'fil'"),
            })
        if sti.startswith("/jobb/"):
            if not self._autorisert():
                return self._svar(401, {"ok": False, "feil": "Ugyldig eller manglende X-API-Key"})
            deler = [d for d in sti.split("/") if d]
            jobb = _jobber.get(deler[1]) if len(deler) >= 2 else None
            if jobb is None:
                return self._svar(404, {"ok": False, "feil": "Ukjent jobb_id"})
            # Arbeidstråden muterer det samme jobb-objektet — ta et
            # atomisk øyeblikksbilde under lås (uten _data-bytene) så en
            # samtidig statuspoll ikke krasjer på «dict changed size»
            with _jobb_las:
                jobb = {k: v for k, v in jobb.items() if not k.startswith("_")}
            if len(deler) == 3 and deler[2] == "tekst":
                if jobb.get("status") != "ferdig":
                    return self._svar(409, {"ok": False, "status": jobb.get("status"),
                                            "feil": "Jobben er ikke ferdig ennå"})
                return self._svar(200, {"ok": True, "jobb_id": jobb["jobb_id"],
                                        "tekst": jobb.get("tekst", ""),
                                        "antall_tegn": jobb.get("antall_tegn", 0)})
            vis = {k: v for k, v in jobb.items()
                   if not k.startswith("_") and k != "tekst"}
            vis["ok"] = True
            vis["tekst_tilgjengelig"] = jobb.get("status") == "ferdig"
            return self._svar(200, vis)
        return self._svar(404, {"ok": False, "feil": "Se GET /hjelp for endepunkter"})

    def _fyll_skjema_flyt(self, filnavn, slag, innhold, maks_ocr, mal,
                          via_spor=False, les_strekkoder=True,
                          skjema_motor="modell", ekstra_advarsler=None):
        """Fyller brukerens egen JSON-mal fra dokumentet. Tre motorer, som
        på /dokument: «modell» (Borealis fyller, KODEN validerer via
        rens_skjemasvar), «felter» (deterministisk fletting av
        {feltnavn}-plassholdere — rask, uten modell) og «auto» (hybrid:
        regel der den kan bevise, modell for resten, med tallvakt)."""
        t0 = time.time()
        # KUN modell-motoren MÅ ha Borealis. felter er ren kode, og auto
        # degraderer til deterministisk når modellen er nede.
        if skjema_motor == "modell" and _borealis["status"] != "klar":
            return self._svar(503, {"ok": False,
                                    "feil": f"Borealis er ikke klar ({_borealis['status']})",
                                    "borealis": _borealis["status"]})
        fra_cache, ocr_brukt = False, False
        if slag == "tekst":
            dok = innhold
        else:
            a = analyser_med_cache(filnavn, innhold, maks_ocr, les_strekkoder)
            if not a.get("ok"):
                return self._svar(400, a)
            dok = a.get("tekst", "")
            fra_cache = a.get("fra_cache", False)
            ocr_brukt = a.get("ocr_brukt", False)

        # «advarsler» ligger i grunnlaget slik at ALLE tre motorene svarer
        # med samme nøkkel — ellers ville et ukjent felt bli meldt på én
        # motor og forsvinne på en annen.
        grunn = {"ok": True, "filnavn": filnavn, "fra_cache": fra_cache,
                 "advarsler": list(ekstra_advarsler or []),
                 "versjon": {"api": API_VERSJON, "prompt": prompter.versjon(),
                             "modell": _borealis["modellfil"] or _borealis["motor"] or None}}

        # --- deterministisk fletting (ingen modell) ---
        if skjema_motor == "felter":
            utfylt, rapport = flett_mal(mal, dok, ocr_brukt)
            svar = {**grunn, "motor": "felter", "skjema": utfylt, "avvik": [],
                    "ukjente_felter": rapport["ukjente_felter"],
                    "tilgjengelige_felter": rapport["tilgjengelige_felter"],
                    "tid_sekunder": round(time.time() - t0, 1),
                    "kilde": "deterministisk"}
            if via_spor:
                svar["svar"] = json.dumps(utfylt, ensure_ascii=False, indent=2)
            return self._svar(200, svar)

        # --- hybrid: deterministisk der mulig, modell for resten ---
        if skjema_motor == "auto":
            res = flett_mal_hybrid(dok, mal, ocr_brukt,
                                   _borealis["status"] == "klar")
            svar = {**grunn, "motor": "auto", "skjema": res["skjema"],
                    "kilde_per_felt": res["kilde_per_felt"],
                    "modell_brukt": res["modell_brukt"],
                    "avvik": res["avvik"],
                    "ukjente_felter": res["ukjente_felter"],
                    "tilgjengelige_felter": res["tilgjengelige_felter"],
                    "tid_sekunder": round(time.time() - t0, 1),
                    "kilde": ("borealis+deterministisk" if res["modell_brukt"]
                              else "deterministisk")}
            if via_spor:
                svar["svar"] = json.dumps(res["skjema"], ensure_ascii=False,
                                          indent=2)
            return self._svar(200, svar)

        # --- modell: Borealis fyller, koden validerer ---
        kjerne = fyll_skjema_kjerne(dok, mal)
        if not kjerne.get("ok"):
            # Også feilsvaret skal bære advarselen — ellers mister den som
            # trenger den mest (noe gikk galt) hintet om at et felt ble
            # ignorert.
            return self._svar(200, {**kjerne,
                                    "advarsler": list(ekstra_advarsler or [])})
        renset, avvik = kjerne["skjema"], kjerne["avvik"]
        svar = {**grunn, "motor": "modell",
                "skjema": renset,
                "avvik": avvik,
                "tid_sekunder": round(time.time() - t0, 1),
                "kilde": "borealis_" + (_borealis["motor"] or "ukjent") + "+kodevalidering"}
        if via_spor:
            svar["melding"] = ("JSON-mal oppdaget i spørsmålet — behandlet "
                               "som skjemautfylling med full kodevalidering")
            # Du ba om JSON → 'svar' er NØYAKTIG den utfylte malen, ren og
            # parsebar. Eventuelle kodeinngrep ligger separat i 'avvik' —
            # ingenting limes på JSON-en (det ville brutt den).
            svar["svar"] = json.dumps(renset, ensure_ascii=False, indent=2)
        return self._svar(200, svar)


    def _innsyn(self, filnavn, slag, innhold, maks_ocr):
        """POST /innsyn — starter en DIREKTEVISNINGS-økt: dokumentet
        behandles i en bakgrunnstråd som strømmer hendelser (side rendret,
        forbehandlet, hver region lest, andrepasset ...) til økta.
        GUI-et poller GET /innsyn/<id>?fra=N og tegner prosessen LIVE.
        Sender ALDRI til Label Studio (ren inspeksjon)."""
        if innhold is None:
            return self._svar(400, {"ok": False,
                                    "feil": "Ingen fil funnet (felt 'fil')"})
        # Kapasitetsplassen tas HER og slippes av arbeidstråden — ikke av
        # forespørselen, som returnerer med en gang. /innsyn sto utenfor
        # _TUNGE_STIER og kunne derfor starte vilkårlig mange samtidige
        # OCR-tråder som alle kjempet om det ene skjermkortet, hver med
        # hele dokumentet i minne. Å legge stien i _TUNGE_STIER ville
        # ikke hjulpet: den plassen frigjøres når POST-en svarer, og da
        # har arbeidet så vidt begynt.
        if not _kapasitet_port.ta(KOE_VENT_S):
            kap = _kapasitet_port.status()
            return self._svar(503, {
                "ok": False,
                "feil": (f"Serveren er opptatt: {kap['grense']} samtidige "
                         "lesinger er taket på denne maskinen. Prøv igjen "
                         "om litt."),
                "opptatt": True, "kapasitet": kap,
            }, hoder={"Retry-After": "30"})
        okt_id = uuid.uuid4().hex[:12]
        okt = {"status": "pågår", "hendelser": [], "resultat": None,
               "start": time.time()}
        with _innsyn_las:
            _innsyn_okter[okt_id] = okt
            while len(_innsyn_okter) > 6:      # eldste økter ryddes
                _innsyn_okter.pop(next(iter(_innsyn_okter)))

        def _arbeid_med_plass():
            try:
                _innsyn_arbeider(okt, filnavn, slag, innhold, maks_ocr)
            finally:
                _kapasitet_port.slipp()

        threading.Thread(target=_arbeid_med_plass, daemon=True).start()
        return self._svar(200, {"ok": True, "innsyn_id": okt_id})

    def _ekko(self, body, ct):
        """POST /ekko — diagnose: svarer med NØYAKTIG hva klienten sendte.
        «raa_deler» viser hver multipart-dels Content-Disposition slik den
        FAKTISK kom, og «parser_ser» hva parseren fikk ut. Slik ser vi om en
        klient (f.eks. UiPath) faktisk sender tekstfeltene, og med hvilket
        feltnavn — uten å gjette."""
        filnavn, filbytes, tekstfelter = None, None, {}
        if "multipart/form-data" in ct:
            filnavn, filbytes, tekstfelter = _parse_multipart(body, ct)
        deler = []
        if "boundary=" in ct:
            boundary = ct.split("boundary=", 1)[1].strip().strip('"')
            skille = ("--" + boundary).encode()
            for d in body.split(skille):
                if b"\r\n\r\n" not in d:
                    continue
                hoder, _, innhold = d.partition(b"\r\n\r\n")
                innhold = innhold.rstrip(b"\r\n")
                deler.append({
                    "content_disposition":
                        hoder.decode("utf-8", "replace").strip()[:300],
                    "innhold_lengde": len(innhold),
                    "innhold_start": innhold[:80].decode("utf-8", "replace"),
                })
        return self._svar(200, {
            "ok": True,
            "melding": "Ekko: dette er hva serveren MOTTOK fra deg.",
            "content_type": ct,
            "body_lengde": len(body),
            "antall_deler": len(deler),
            "parser_ser": {
                "fil": filnavn,
                "fil_bytes": len(filbytes) if filbytes else 0,
                "tekstfelt_navn": sorted(tekstfelter.keys()),
                "tekstfelter": {k: v[:200] for k, v in tekstfelter.items()},
            },
            "raa_deler": deler,
        })

    def _forhandssjekk(self, filnavn, slag, innhold, tekstfelter):
        """POST /forhandssjekk — billig kvalitetsdom FØR GPU-en brukes.

        Rendrer sidene (samme oppløsning som OCR ville brukt) og måler
        skarphet/lys/oppløsning/tomhet med vurder_kvalitet og
        andel_blekk fra delt/forbehandling — men kjører ALDRI OCR og
        rører aldri modellen. Et dårlig skann avvises på ~sekundet i
        stedet for å koste 30 s GPU og gi søppeltekst.

        Har dokumentet TEKSTLAG, er skannkvalitet irrelevant (OCR kjøres
        aldri) — da er dommen «god» uten sidevurderinger."""
        t0 = time.time()
        milde, omvendte = _sjekk_feltnavn(tekstfelter,
                                          _KJENTE_FELT_FORHANDSSJEKK)
        if omvendte:
            return self._svar(400, _omvendt_felt_feil(
                omvendte, _KJENTE_FELT_FORHANDSSJEKK))
        advarsler = _ukjent_felt_advarsel(milde, _KJENTE_FELT_FORHANDSSJEKK)
        grunn = {"ok": True, "filnavn": filnavn,
                 "versjon": {"api": API_VERSJON,
                             "uttrekk_regler": UTTREKK_REGEL_VERSJON}}

        # DOCX/TXT/regneark: det finnes ikke noe skann å vurdere
        if slag == "tekst":
            return self._svar(200, {
                **grunn, "dom": "god", "tekstlag": True,
                "trenger_ocr": False, "antall_sider": None,
                "sider_vurdert": 0, "sider": [],
                "advarsler": advarsler,
                "anbefaling": "Tekstdokument — det finnes ikke noe skann "
                              "å vurdere. Send det rett til POST /dokument.",
                "tid_sekunder": round(time.time() - t0, 1)})

        import fitz
        try:
            doc = fitz.open(stream=innhold, filetype="pdf")
        except Exception as exc:
            return self._svar(400, {"ok": False,
                                    "feil": f"Ugyldig/korrupt PDF: {exc}"})
        try:
            antall = len(doc)
            if antall == 0:
                return self._svar(400, {"ok": False,
                                        "feil": "PDF-en har ingen sider"})

            # Tekstlag → OCR kjøres aldri → skannkvalitet er irrelevant.
            # Samme terskel (20 tegn) som analyser_bytes bruker for å
            # avgjøre om OCR trengs — de to skal aldri være uenige.
            total_tekst = sum(len((s.get_text() or "").strip())
                              for s in doc)
            if total_tekst >= 20:
                return self._svar(200, {
                    **grunn, "dom": "god", "tekstlag": True,
                    "trenger_ocr": False, "antall_sider": antall,
                    "sider_vurdert": 0, "sider": [],
                    "advarsler": advarsler,
                    "anbefaling": "Dokumentet har tekstlag — OCR trengs "
                                  "ikke, og skannkvalitet er irrelevant. "
                                  "Send det rett til POST /dokument.",
                    "tid_sekunder": round(time.time() - t0, 1)})

            import numpy as np

            from delt.forbehandling import (TOM_SIDE_BLEKK, andel_blekk,
                                            vurder_kvalitet)
            # Klientens maks_sider respekteres, men aldri over taket —
            # et kjent felt som ignoreres i stillhet er nettopp fella
            # resten av API-et nå vokter mot.
            try:
                onsket = int(tekstfelter.get("maks_sider", "0") or 0)
            except ValueError:
                onsket = 0
            tak = FORHANDSSJEKK_MAKS_SIDER
            grense = min(onsket, tak) if onsket > 0 else tak
            grense = min(grense, antall)
            sider = []
            for i in range(grense):
                side = doc[i]
                dpi = naturlig_dpi(doc, side)
                pix = side.get_pixmap(matrix=ocr_skala(doc, side))
                bilde = np.frombuffer(pix.samples, dtype=np.uint8) \
                    .reshape(pix.height, pix.width, pix.n)
                if pix.n == 4:      # RGBA → RGB
                    bilde = bilde[:, :, :3]
                kvalitet = vurder_kvalitet(bilde)
                blekk = andel_blekk(bilde)
                tom = blekk < TOM_SIDE_BLEKK
                side_advarsler = list(kvalitet["advarsler"])
                if tom:
                    side_advarsler.append(
                        "tom side — ingen synlig tekst eller innhold")
                # «uleselig» = under avvis-terskelen, ikke bare under
                # advarsel-terskelen. Dømmes på det OCR faktisk får se:
                # rendrede piksler og skarphet — IKKE nominell dpi (se
                # kommentaren ved tersklene).
                min_px = min(bilde.shape[0], bilde.shape[1])
                uleselig = (min_px < FORHANDSSJEKK_AVVIS_PIKSLER
                            or kvalitet["skarphet"]
                            < FORHANDSSJEKK_AVVIS_SKARPHET)
                if not tom and min_px < FORHANDSSJEKK_AVVIS_PIKSLER:
                    side_advarsler.append(
                        f"altfor få piksler ({min_px} — under "
                        f"{FORHANDSSJEKK_AVVIS_PIKSLER}): teksten kan "
                        "ikke leses")
                sider.append({
                    "side": i + 1,
                    "dpi": round(dpi, 1) if dpi is not None else None,
                    "piksler": [bilde.shape[1], bilde.shape[0]],
                    "skarphet": kvalitet["skarphet"],
                    "lys": kvalitet["lys"],
                    "blekk_andel": round(blekk, 4),
                    "tom": tom,
                    "uleselig": bool(uleselig and not tom),
                    "advarsler": side_advarsler,
                })
            if grense < antall:
                advarsler.append(
                    f"Kun de første {grense} av {antall} sider er vurdert "
                    f"(feltet maks_sider, tak {tak})")
            dom, anbefaling = doem_forhandssjekk(sider)
            return self._svar(200, {
                **grunn, "dom": dom, "tekstlag": False,
                "trenger_ocr": True, "antall_sider": antall,
                "sider_vurdert": grense, "sider": sider,
                "advarsler": advarsler, "anbefaling": anbefaling,
                "tid_sekunder": round(time.time() - t0, 1)})
        finally:
            doc.close()

    # Fast tekst i HVERT /sladd-svar — ikke bare i dokumentasjonen: den
    # som tror sladdingen alene er nok for offentliggjøring, skal møte
    # grensen i selve svaret, før dokumentet forlater huset.
    SLADD_ADVARSEL = (
        "Navn og adresser sladdes IKKE — de kan ikke bevises "
        "deterministisk. Denne sladdingen er derfor IKKE alene "
        "tilstrekkelig for offentliggjøring (offentleglova); manuell "
        "gjennomgang er påkrevd.")

    def _sladd(self, filnavn, slag, innhold, maks_ocr, tekstfelter):
        """POST /sladd — sladder KUN det som kan BEVISES.

        Fødselsnummer, kontonummer og organisasjonsnummer er
        mod11-validert, KID sjekksumvalidert med etikettkrav, telefon og
        epost formatvalidert — matematikk og format, aldri modell.
        Hvert funn erstattes synlig med «[SLADDET type]».

        Grensen sies høyt i hvert svar (SLADD_ADVARSEL): navn og
        adresser dekkes ikke, for de kan ikke bevises — og en gjettet
        sladding som SER fullført ut er farligere enn ingen."""
        t0 = time.time()
        milde, omvendte = _sjekk_feltnavn(tekstfelter, _KJENTE_FELT_SLADD)
        if omvendte:
            return self._svar(400, _omvendt_felt_feil(omvendte,
                                                      _KJENTE_FELT_SLADD))
        advarsler = _ukjent_felt_advarsel(milde, _KJENTE_FELT_SLADD)

        # Valgfritt utvalg av typer (kommaseparert). Ukjent type er 400 —
        # en klient som ber om «personnummer» og får 200 ville trodd det
        # ble sladdet.
        typer = None
        typer_raa = tekstfelter.get("typer", "").strip()
        if typer_raa:
            typer = [t.strip().lower() for t in typer_raa.split(",")
                     if t.strip()]
            ukjente_typer = [t for t in typer if t not in SLADD_TYPER]
            if ukjente_typer:
                return self._svar(400, {
                    "ok": False,
                    "feil": (f"Ukjente sladdetyper: {', '.join(ukjente_typer)}. "
                             f"Gyldige: {', '.join(SLADD_TYPER)}"),
                    "felter_feil": [{"pointer": "/typer",
                                     "message": "Ukjent type"}]})

        # Strekkoder er irrelevante for sladding — spar skanningen
        ktx, les_advarsler, feil = self._les_dokument(
            filnavn, slag, innhold, maks_ocr, les_strekkoder=False)
        if feil:
            return self._svar(*feil)
        advarsler.extend(les_advarsler)

        sladdet, antall_per_type = sladd_tekst(ktx.tekst, typer)
        if ktx.ocr_brukt:
            # Ærlig grense nr. 2: mod11 er en tveegget vakt på OCR-tekst.
            # Ett feillest siffer → kontrollen slår ikke til → nummeret
            # blir stående USLADDET.
            advarsler.append(
                "Teksten kommer fra OCR: et feillest siffer gjør at "
                "sjekksumkontrollen ikke slår til, og et nummer kan bli "
                "stående usladdet. Kontroller resultatet manuelt.")

        # HULLET, GJORT MASKINLESBART.
        #
        # Målt: et dokument med fem MERKEDE identifikatorer der fire
        # feilet sjekksummen ga `ok: true`, `advarsler: []` og et `funn`
        # som bare listet de to som faktisk ble fjernet. Hvert
        # maskinlesbart felt så like friskt ut som på et rent dokument.
        # Eneste måte å oppdage lekkasjen på var å lese teksten selv —
        # altså gjøre sladdingen om igjen for å kontrollere sladdingen.
        #
        # Advarselen om dette fantes, men lå bak `if ktx.ocr_brukt:`. På
        # et tekstlags-PDF er ikke OCR årsaken — en skrivefeil eller et
        # utenlandsk format er nok — og da kom det ingen advarsel i det
        # hele tatt.
        mistenkt = finn_mistenkt_usladdet(
            ktx.tekst, finn_sladdeomraader(ktx.tekst, typer))
        fullstendig = not mistenkt and not ktx.ocr_brukt
        if mistenkt:
            advarsler.append(
                f"{len(mistenkt)} identifikator(er) står MERKET i "
                f"dokumentet, men besto ikke kontrollsifferet og ble "
                f"derfor IKKE sladdet — se «mistenkt_usladdet».")

        return self._svar(200, {
            "ok": True, "filnavn": filnavn,
            "sladdet_tekst": sladdet,
            "antall_tegn": len(sladdet),
            "funn": [{"type": t, "antall": antall_per_type[t]}
                     for t in SLADD_TYPER if t in antall_per_type],
            "antall_sladdet": sum(antall_per_type.values()),
            # «funn» teller hva som BLE FJERNET. Det sier ingenting om
            # hva som ble MISSET — og forskjellen er hele poenget med
            # de to feltene under.
            "mistenkt_usladdet": mistenkt,
            # Den ene boolen en robot kan rute på: false betyr «send
            # dette til manuell kontroll». Den er false både når noe
            # merket sto igjen, og når teksten kom fra OCR — der ett
            # feillest siffer er nok til at kontrollen ikke slår til.
            "sladding_fullstendig": fullstendig,
            "typer_valgt": typer or list(SLADD_TYPER),
            # Den FULLE lista over hva sladdingen ikke fjerner. Sto
            # tidligere bare «navn, adresser», og en klient som
            # stolte på feltet ville tro et sladdet dokument var
            # tryggere enn det er.
            "ikke_dekket": ["navn", "adresser", "arbeidsgiver",
                            "inntekt", "belop",
                            "helseopplysninger", "saksnummer",
                            "datoer"],
            "advarsel": self.SLADD_ADVARSEL,
            "advarsler": advarsler,
            "kvalitet": {"ocr_brukt": ktx.ocr_brukt,
                         "ocr_motorer": ktx.ocr_motorer or {}},
            "fra_cache": ktx.fra_cache,
            "tid_sekunder": round(time.time() - t0, 1),
            "kilde": "deterministisk",
            "versjon": {"api": API_VERSJON,
                        "uttrekk_regler": UTTREKK_REGEL_VERSJON},
        })

    def _bygg_koordinater(self, ktx, slag, innhold, maks_ocr, advarsler):
        """Koordinatdelen for /dokument (bryteren koordinater=ja).

        To kilder, samme svarform (delt/koordinater):
          * OCR kjørte → regionene per side, bokser i FORBEHANDLEDE
            bildepiksler.
          * Tekstlags-PDF → ordregister fra PyMuPDF, bokser i PDF-punkter.
        Ren tekstopplasting har ingen sider — det sies ærlig i stedet
        for å returnere et tomt objekt som ser ut som «ingen funn»."""
        from delt.koordinater import (koordinater_for_sider,
                                      ord_regioner_fra_pdfside)
        if ktx.sider_regioner:
            return koordinater_for_sider(ktx.sider_regioner,
                                         "forbehandlet_bilde_piksler")
        if slag == "pdf" and not ktx.ocr_brukt:
            import fitz
            try:
                doc = fitz.open(stream=innhold, filetype="pdf")
            except Exception:
                advarsler.append("koordinater: klarte ikke å åpne PDF-en "
                                 "på nytt for ordposisjoner")
                return None
            try:
                tak = maks_ocr or OCR_MAKS_SIDER
                sider = [{"side": i + 1,
                          "bredde": round(side.rect.width, 1),
                          "hoyde": round(side.rect.height, 1),
                          "regioner": ord_regioner_fra_pdfside(side)}
                         for i, side in enumerate(doc) if i < tak]
                if len(doc) > tak:
                    advarsler.append(
                        f"koordinater: kun de første {tak} av {len(doc)} "
                        "sider (samme grense som maks_sider)")
            finally:
                doc.close()
            return koordinater_for_sider(sider, "pdf_punkter")
        advarsler.append("koordinater: ren tekstopplasting har ingen "
                         "sider — koordinater finnes ikke")
        return None

    def _les_dokument(self, filnavn, slag, innhold, maks_ocr, les_strekkoder):
        """Leser dokumentet ÉN gang og pakker det i en DokumentKontekst —
        delt av bryter-veien OG operasjoner-veien, så begge leser likt.
        Returnerer (ktx, advarsler, feil): feil er None ved suksess, ellers
        et (status, kropp)-par kalleren svarer med."""
        advarsler = []
        # Sidegrensen ble kappet mot taket — sagt her, én gang, for
        # begge svarveiene.
        if getattr(self, "_kappet_advarsel", None):
            advarsler.append(self._kappet_advarsel)
        ocr_brukt, ocr_motorer, fra_cache = False, None, False
        handskrift, strekkoder, sider_regioner = [], [], []
        antall_sider = None
        ferdig = {}          # deler analysen ALLEREDE har regnet ut
        if slag == "tekst":
            raa_tekst = (innhold or "").strip()
            # Ren tekst har ingen sider. Er teksten derimot lest ut av et
            # flersidig dokument tidligere, står sidemarkørene der (R36)
            # og forteller hvor mange det var.
            markorer = re.findall(r"\[Side \d+ av (\d+)\]", raa_tekst)
            antall_sider = max(int(m) for m in markorer) if markorer else None
        else:
            a = analyser_med_cache(filnavn, innhold, maks_ocr, les_strekkoder)
            if not a.get("ok"):
                return None, advarsler, (400, a)
            raa_tekst = a.get("tekst", "")
            strekkoder = a.get("strekkoder", [])
            handskrift = a.get("handskrift") or []
            ocr_motorer = a.get("ocr_motorer")
            ocr_brukt = a.get("ocr_brukt", False)
            fra_cache = a.get("fra_cache", False)
            sider_regioner = a.get("_sider_regioner") or []
            antall_sider = a.get("antall_sider")
            # Analysen har allerede klassifisert datoene og funnet
            # dokumentdatoen — MED PDF-metadata og håndskriftmerking som
            # konteksten ikke har tilgang til. Kastet vi dem, regnet vi
            # ikke bare det samme om igjen: vi fikk et ANNET svar, så
            # /analyser og /dokument kunne melde ulik dokumentdato for
            # samme fil, og advarselen «datoen er håndskrevet» kunne
            # aldri utløses i dokumentprofilen.
            for nokkel in ("felter", "datoer", "datoer_detaljert",
                           "dokumentdato"):
                if a.get(nokkel) is not None:
                    ferdig[nokkel] = a[nokkel]
            if a.get("advarsel"):
                advarsler.append(a["advarsel"])
            if a.get("melding"):
                advarsler.append(a["melding"])
        # «lest» betyr at dekoderen FAKTISK kjørte — ikke at klienten lot
        # være å slå den av. På tekstveien (.txt/.docx/.csv/regneark)
        # finnes det ingen bilder å skanne, og dekoderen kalles aldri.
        # Likevel sto `lest: true` med to tomme lister, altså påstanden
        # «vi skannet og fant ingen koder» om et dokument som aldri ble
        # skannet. Feltet som finnes for å hindre nettopp den løgnen,
        # fortalte den.
        skanning_kjorte = bool(les_strekkoder) and slag != "tekst"
        ktx = DokumentKontekst(raa_tekst, ocr_brukt=ocr_brukt,
                               handskrift=handskrift, strekkoder=strekkoder,
                               ocr_motorer=ocr_motorer, fra_cache=fra_cache,
                               sider_regioner=sider_regioner,
                               antall_sider=antall_sider,
                               strekkoder_lest=skanning_kjorte,
                               filnavn=filnavn,
                               ferdig=ferdig)
        return ktx, advarsler, None

    # Vern mot misbruk: en enkelt forespørsel kan ikke be om et ubegrenset
    # antall operasjoner.
    MAKS_OPERASJONER = 20

    def _dokument_operasjoner(self, filnavn, slag, innhold, maks_ocr,
                              les_strekkoder, operasjoner_raa, tekstfelter=None):
        """POST /dokument med feltet 'operasjoner' — det nye, uniforme
        kontraktet: en JSON-liste av {type, …}. Dokumentet leses ÉN gang,
        og motoren kjører hver operasjon mot samme kontekst. Svar:
        {ok, resultater:[...]}. Bryter-veien er urørt; dette er et tillegg."""
        t0 = time.time()
        if innhold is None:
            return self._svar(400, {"ok": False,
                                    "feil": "Ingen fil funnet (felt 'fil')"})
        milde, omvendte = _sjekk_feltnavn(tekstfelter or {},
                                          _KJENTE_FELT_OPERASJONER)
        if omvendte:
            return self._svar(400, _omvendt_felt_feil(omvendte,
                                                      _KJENTE_FELT_OPERASJONER))
        # Samme grunn som på /fyll_skjema: advarselen ble regnet ut og
        # kastet. Her er fallhøyden ekstra stor, for operasjoner-veien
        # IGNORERER bryterne — sender klienten «felter=ja» sammen med
        # «operasjoner», skjer det ingenting, og uten melding ser svaret
        # ut som om begge deler ble utført.
        operasjon_advarsler = _ukjent_felt_advarsel(milde,
                                                    _KJENTE_FELT_OPERASJONER)
        try:
            spec = json.loads(operasjoner_raa)
        except json.JSONDecodeError as exc:
            return self._svar(400, {
                "ok": False, "feil": f"Ugyldig JSON i 'operasjoner': {exc}",
                "felter_feil": [{"pointer": "/operasjoner",
                                 "message": "Ikke gyldig JSON"}]})
        # Godta både {"operasjoner":[...]} og en ren [...]
        if isinstance(spec, dict) and "operasjoner" in spec:
            spec = spec["operasjoner"]
        if not isinstance(spec, list) or not spec:
            return self._svar(400, {
                "ok": False,
                "feil": "'operasjoner' må være en ikke-tom liste av operasjoner",
                "felter_feil": [{"pointer": "/operasjoner",
                                 "message": "Må være en ikke-tom liste"}]})
        if len(spec) > self.MAKS_OPERASJONER:
            return self._svar(400, {
                "ok": False,
                "feil": f"For mange operasjoner ({len(spec)}) — maks "
                        f"{self.MAKS_OPERASJONER} per forespørsel"})
        try:
            ops = [bygg_operasjon(o) for o in spec]
        except ValueError as exc:
            return self._svar(400, {"ok": False, "feil": str(exc),
                                    "felter_feil": [{"pointer": "/operasjoner",
                                                     "message": str(exc)}]})

        # 503-port som ellers på /dokument: er ALLE operasjonene modelldeler
        # og Borealis er nede, er 503 (retry) ærligere enn 200 med bare
        # feilobjekter. Er minst én rask del med, svarer vi 200.
        if (all(op._krever_borealis() for op in ops)
                and _borealis["status"] != "klar"):
            return self._svar(503, {
                "ok": False,
                "feil": f"Borealis er ikke tilgjengelig ({_borealis['status']}) — prøv igjen senere",
                "borealis": _borealis["status"]})

        ktx, advarsler, feil = self._les_dokument(
            filnavn, slag, innhold, maks_ocr, les_strekkoder)
        if feil:
            return self._svar(*feil)
        advarsler = operasjon_advarsler + advarsler

        resultater = Operasjonsmotor().kjor(ktx, ops, advarsler)
        # Feil i en del skal også være synlig for den som bare leser
        # advarslene — samme løfte som bryter-veien gir.
        for r in resultater:
            if r.get("ok") is False:
                advarsler.append(f"{r.get('type')}: {r.get('feil')}")

        # R79: profilen følger med her OGSÅ. De to kontraktene på
        # /dokument skal svare likt på det som gjelder dokumentet selv —
        # ellers ville en klient miste metadataene ved å bytte kontrakt.
        profilform = ((tekstfelter or {}).get("profil", "").strip().lower()
                      or "full")
        if profilform not in ("full", "sammendrag"):
            return self._svar(400, {"ok": False, "feil": (
                f"Ukjent 'profil': {profilform!r}. Bruk 'full' (standard) "
                "eller 'sammendrag'."),
                "felter_feil": [{"pointer": "/profil",
                                 "message": "Bruk 'full' eller 'sammendrag'"}]})
        opphavsnivaa = ((tekstfelter or {}).get("opphav", "").strip().lower()
                        or "viktige")
        if opphavsnivaa not in NIVAAER:
            return self._svar(400, {"ok": False, "feil": (
                f"Ukjent 'opphav': {opphavsnivaa!r}. Bruk "
                + ", ".join(f"'{n}'" for n in NIVAAER) + "."),
                "felter_feil": [{"pointer": "/opphav",
                                 "message": "Bruk " + "/".join(NIVAAER)}]})
        try:
            profil = _profilform(ktx.profil, profilform)
            opphav = uten_utelatte(bygg_opphav(ktx.profil, opphavsnivaa,
                                                   ktx.tekst),
                                   profil)
        except Exception as exc:
            profil = {"ok": False,
                      "feil": f"Profilen feilet ({type(exc).__name__}): {exc}"[:300]}
            opphav = {}

        # Samme ærlighetsregel som bryter-veien: en operasjon som feilet
        # skal ikke telles som «modellen kjørte». Resultatene er en liste
        # av {type, …}, så de mappes til samme form regelen forventer.
        modell_kjorte = _modellen_kjorte(
            {r.get("type"): r for r in resultater if isinstance(r, dict)})

        svar = {
            "ok": True, "filnavn": filnavn,
            "dokumentprofil": profil,
            "opphav": opphav,
            "modell_brukt": modell_kjorte,
            "resultater": resultater,
            "antall_tegn": len(ktx.tekst),
            "antall_sider": ktx.antall_sider,
            # null når skanningen aldri kjørte — samme regel som
            # `koder.qr`/`koder.strekkode` i profilen (R128). Sto de
            # ulikt, ville to felt om samme faktum sagt hver sin ting i
            # samme svar.
            "strekkoder": ktx.strekkoder if ktx.strekkoder_lest else None,
            "handskrift": ktx.handskrift if ktx.ocr_brukt else None,
            "varsler": _varsler(advarsler),
            "status": _samlet_status(
                {r.get("type", f"op{i}"): r
                 for i, r in enumerate(resultater) if isinstance(r, dict)},
                advarsler),
            "kvalitet": {"ocr_brukt": ktx.ocr_brukt,
                         "ocr_motorer": ktx.ocr_motorer or {},
                         "advarsler": advarsler},
            "fra_cache": ktx.fra_cache,
            "tid_sekunder": round(time.time() - t0, 1),
            # «motor» sa hvilken VEI som ble brukt, ikke om modellen kjørte
            # — og dokumentasjonen lover at «borealis» i kilde betyr at
            # den gjorde det. Nå følger begge veier samme regel.
            "kilde": ("motor+borealis" if modell_kjorte else "motor"),
            "versjon": {"api": API_VERSJON, "prompt": prompter.versjon(),
                        "modell": _borealis["modellfil"] or _borealis["motor"] or None},
        }
        # Samme personvernbryter som på bryterveien (R90: den skal virke
        # i BEGGE kontraktene). Her bærer «resultater» de samme feltene
        # bryterveien har i «felter».
        if profilform == "sammendrag":
            svar = _sammendragsform(_sammendragsform_operasjoner(svar))
        return self._svar(200, svar)

    def _dokument_samlet(self, filnavn, slag, innhold, maks_ocr,
                         tekstfelter, les_strekkoder):
        """POST /dokument — ETT kall med brytere for hva som skal gjøres.
        Dokumentet leses ÉN gang (delt cache med /analyser//spor//uttrekk);
        deretter kjøres BARE delene som er slått på. De raske
        deterministiske delene er PÅ som standard; delene som koster
        modellkall (svar/skjema/korriger) er AV til de bes om — så det
        raske forblir raskt. Delene feiler uavhengig: én del med problem
        stopper aldri de andre."""
        # Nytt, uniformt kontrakt: sendes feltet 'operasjoner' (en JSON-
        # liste), ruter vi til motoren og svarer {ok, resultater:[...]}.
        # Uten feltet er alt NØYAKTIG som før — bryterne under styrer.
        operasjoner_raa = tekstfelter.get("operasjoner", "").strip()
        if operasjoner_raa:
            return self._dokument_operasjoner(
                filnavn, slag, innhold, maks_ocr, les_strekkoder,
                operasjoner_raa, tekstfelter)

        t0 = time.time()
        advarsler = []

        # Feilnavngitte felt (UiPath-fella): en VERDI brukt som feltnavn er
        # en klar feil — stopp med 400 i stedet for et misvisende 200 der
        # skjema_mal/skjema_motor stilltiende falt bort.
        milde, omvendte = _sjekk_feltnavn(tekstfelter, _KJENTE_FELT_DOKUMENT)
        if omvendte:
            return self._svar(400, _omvendt_felt_feil(omvendte,
                                                      _KJENTE_FELT_DOKUMENT))
        advarsler.extend(_ukjent_felt_advarsel(milde, _KJENTE_FELT_DOKUMENT))

        # Bryterne tar både norsk og engelsk ja/nei. En UKJENT verdi
        # avvises (400) i stedet for å bli tolket som «nei» — ellers ville
        # «felter=yes» stille slått AV en standard-PÅ-del, og klienten
        # fått 200 med tomt innhold uten et eneste feilsignal.
        JA, NEI = BRYTER_JA, BRYTER_NEI
        ukjente = []

        def gitt(navn):
            """Er bryteren EKSPLISITT satt? En TOM verdi teller ikke:
            skjemaposteringer (HTML-skjema, UiPath) sender gjerne alle
            felter — også de tomme — og «svar=» skal ikke blokkere
            autoaktiveringen under."""
            return bool(tekstfelter.get(navn, "").strip())

        def paa(navn, standard):
            v = tekstfelter.get(navn, "").strip().lower()
            if not v:
                return standard
            if v in JA:
                return True
            if v in NEI:
                return False
            ukjente.append(f"{navn}={tekstfelter.get(navn, '')[:40]}")
            return standard

        # Kollisjonsvern: på /fyll_skjema er «skjema» selve JSON-malen,
        # her er det en bryter. En klient som migrerer med det gamle
        # feltnavnet skal få en TYDELIG feil — ikke en stille tapt mal.
        skjema_bryter = tekstfelter.get("skjema", "").strip()
        if skjema_bryter.startswith(("{", "[")):
            return self._svar(400, {"ok": False, "feil": (
                "På /dokument er 'skjema' en bryter (ja/nei) — legg selve "
                "JSON-malen i feltet 'skjema_mal'")})

        valg = {
            "tekst": paa("tekst", True),
            "felter": paa("felter", True),
            "struktur": paa("struktur", False),
            "svar": paa("svar", False),
            "skjema": paa("skjema", False),
            "korriger": paa("korriger", False),
        }
        # Koordinater er ikke en del av valg-kontrakten (den er urørt for
        # eksisterende klienter) — egen bryter, standard AV: bokser per
        # funn kan mangedoble svaret, og de fleste kall trenger dem ikke.
        vil_ha_koordinater = paa("koordinater", False)
        # «datoer_detaljert» er den enkeltdelen som veier mest i svaret:
        # målt 12 949 av 33 424 byte (39 %) på en 10-siders bunke —
        # større enn dokumentteksten selv. Standard er fortsatt PÅ, så
        # ingen klient mister noe; men den som ikke bruker den kan nå si
        # fra. (Standard flyttes til AV først i v2.)
        vil_ha_datodetaljer = paa("datoer_detaljert", True)
        # profil=sammendrag lar en klient la være å motta persondata den
        # ikke skal ha. Personvernfunnet var at et kall med bare
        # «sporsmal» likevel fikk fnr, fødselsdato, adresse, telefon,
        # e-post, arbeidsgiver, årsinntekt, kontonummer og KID.
        profilform = (tekstfelter.get("profil", "").strip().lower()
                      or "full")
        if profilform not in ("full", "sammendrag"):
            return self._svar(400, {"ok": False, "feil": (
                f"Ukjent 'profil': {profilform!r}. Bruk 'full' (standard) "
                "eller 'sammendrag'."),
                "felter_feil": [{"pointer": "/profil",
                                 "message": "Bruk 'full' eller 'sammendrag'"}]})
        # «opphav» samler de fem måtene API-et forklarte proveniens på i
        # ETT oppslag: JSON Pointer inn, {metode, konfidens, begrunnelse,
        # side} ut. Standard «viktige» = parten og dokumentdatoen, altså
        # det de fleste faktisk handler på; «alle» tar med resten.
        opphavsnivaa = (tekstfelter.get("opphav", "").strip().lower()
                        or "viktige")
        if opphavsnivaa not in NIVAAER:
            return self._svar(400, {"ok": False, "feil": (
                f"Ukjent 'opphav': {opphavsnivaa!r}. Bruk "
                + ", ".join(f"'{n}'" for n in NIVAAER) + "."),
                "felter_feil": [{"pointer": "/opphav",
                                 "message": "Bruk " + "/".join(NIVAAER)}]})
        if ukjente:
            return self._svar(400, {"ok": False, "feil": (
                "Ukjent bryterverdi: " + ", ".join(ukjente)
                + ". Bruk ja/nei (eller 1/0, true/false)."),
                "felter_feil": [{"pointer": f"/{u.split('=')[0]}",
                                 "message": "Ukjent bryterverdi (bruk ja/nei)"}
                                for u in ukjente]})

        sporsmal = tekstfelter.get("sporsmal", "").strip()
        mal_raa = tekstfelter.get("skjema_mal", "").strip()
        # Motor for skjemautfylling: «modell» (Borealis fyller — mest
        # fleksibelt, men koster tid) eller «felter» (deterministisk
        # fletting av {feltnavn}-plassholdere — like raskt som felter, og
        # klienten bestemmer selv navn/oppsett). Standard er modell for å
        # ikke endre eksisterende oppførsel stille.
        skjema_motor = tekstfelter.get("skjema_motor", "").strip().lower() \
            or "modell"
        # Vennlighet: sender du sporsmal/skjema_mal uten å sette bryteren,
        # er hensikten åpenbar — bryteren slås på av seg selv
        if sporsmal and not gitt("svar"):
            valg["svar"] = True
        if mal_raa and not gitt("skjema"):
            valg["skjema"] = True

        if innhold is None:
            return self._svar(400, {"ok": False,
                                    "feil": "Ingen fil funnet (felt 'fil')"})
        if valg["svar"] and not sporsmal:
            return self._svar(400, {
                "ok": False, "feil": "svar=ja krever feltet 'sporsmal'",
                "felter_feil": [{"pointer": "/sporsmal",
                                 "message": "Påkrevd når svar=ja"}]})
        # JSON-mal limt i sporsmal-feltet: /spor ruter slikt automatisk til
        # skjemautfylling. Her finnes et eget felt for det — si fra, ellers
        # ville malen blitt sendt som et vanlig SPØRSMÅL til modellen.
        if valg["svar"] and sporsmal.startswith(("{", "[")):
            if isinstance(_parse_json_svar(sporsmal), (dict, list)):
                advarsler.append(
                    "'sporsmal' ser ut som en JSON-mal — den behandles her "
                    "som et vanlig spørsmål. Vil du ha den UTFYLT med "
                    "kodevalidering, send den i 'skjema_mal' i stedet.")
        mal = None
        if valg["skjema"]:
            if not mal_raa:
                return self._svar(400, {
                    "ok": False,
                    "feil": "skjema=ja krever feltet 'skjema_mal' (din JSON-mal)",
                    "felter_feil": [{"pointer": "/skjema_mal",
                                     "message": "Påkrevd når skjema=ja"}]})
            try:
                mal = json.loads(mal_raa)
            except json.JSONDecodeError as exc:
                return self._svar(400, {
                    "ok": False, "feil": f"Ugyldig JSON i 'skjema_mal': {exc}",
                    "felter_feil": [{"pointer": "/skjema_mal",
                                     "message": "Ikke gyldig JSON"}]})
            # Lister godtas (rens_skjemasvar håndterer dem rekursivt) —
            # samme kontrakt som /fyll_skjema, slik dokumentasjonen lover
            if not isinstance(mal, (dict, list)) or not mal:
                return self._svar(400, {
                    "ok": False,
                    "feil": "'skjema_mal' må være et JSON-objekt (eller en liste) med felter",
                    "felter_feil": [{"pointer": "/skjema_mal",
                                     "message": "Må være et ikke-tomt objekt eller liste"}]})
            if skjema_motor not in ("modell", "felter", "auto"):
                return self._svar(400, {
                    "ok": False,
                    "feil": ("Ukjent 'skjema_motor': "
                             f"{skjema_motor!r}. Bruk 'modell' (Borealis "
                             "fyller alt), 'felter' (deterministisk "
                             "fletting av {feltnavn}-plassholdere) eller "
                             "'auto' (deterministisk der det går, modell "
                             "for resten)."),
                    "felter_feil": [{"pointer": "/skjema_motor",
                                     "message": "Bruk 'modell', 'felter' eller 'auto'"}]})

        # Bare «modell»-motoren MÅ ha Borealis. «felter» er ren kode, og
        # «auto» faller elegant tilbake til deterministisk hvis modellen er
        # nede — begge teller derfor som RASKE deler i porten under.
        skjema_med_modell = valg["skjema"] and skjema_motor == "modell"

        # Konsistens med /spor og /fyll_skjema: er BARE modelldeler bedt om
        # og modellen er nede, er 503 med retry-signal riktigere enn 200
        # der alt innholdet er feilobjekter. Er en rask del også bedt om,
        # gjelder «delene feiler uavhengig» og vi svarer 200.
        rask_del = (valg["tekst"] or valg["felter"] or valg["struktur"]
                    or (valg["skjema"] and skjema_motor in ("felter", "auto"))
                    or (valg["svar"] and kan_svares_uten_modell(sporsmal)))
        bare_modell = not rask_del
        vil_ha_modell = valg["svar"] or skjema_med_modell or valg["korriger"]
        if bare_modell and vil_ha_modell and _borealis["status"] != "klar":
            return self._svar(503, {
                "ok": False,
                "feil": f"Borealis er ikke tilgjengelig ({_borealis['status']}) — prøv igjen senere",
                "borealis": _borealis["status"]})

        # --- les dokumentet ÉN gang (delt _les_dokument med operasjoner-
        # veien, så begge leser og cacher likt) ---
        ktx, les_advarsler, feil = self._les_dokument(
            filnavn, slag, innhold, maks_ocr, les_strekkoder)
        if feil:
            return self._svar(*feil)
        advarsler.extend(les_advarsler)
        raa_tekst = ktx.tekst
        ocr_brukt = ktx.ocr_brukt
        ocr_motorer = ktx.ocr_motorer
        fra_cache = ktx.fra_cache
        handskrift = ktx.handskrift
        strekkoder = ktx.strekkoder

        borealis_klar = _borealis["status"] == "klar"
        borealis_feil = f"Borealis er ikke klar ({_borealis['status']}) — prøv igjen senere"
        # Blankt ark: modelldelene skal IKKE kjøre. Uten dette vernet kan
        # korriger_borealis("") få modellen til å DIKTE «korrigert» tekst
        # fra ingenting — linjevakta slipper det gjennom fordi 0 linjer mot
        # N linjer ikke lar seg pare (samme grunn gjelder skjemautfylling).
        tomt_dokument = len(raa_tekst.strip()) < 5 and not strekkoder
        tom_feil = "Fant ingen lesbar tekst i dokumentet"
        deler = {}

        # --- koordinater per bevist funn (egen bryter, standard av) ---
        koordinater = None
        if vil_ha_koordinater:
            koordinater = self._bygg_koordinater(ktx, slag, innhold,
                                                 maks_ocr, advarsler)

        def trygt(fn):
            """Kjør én del uten at en uventet feil river med seg resten —
            kontrakten er at delene feiler UAVHENGIG. Det realistiske
            tilfellet er CUDA-OOM på det delte 8 GB-kortet: før dette
            vernet ble hele kallet 500, og de allerede ferdige
            deterministiske delene gikk tapt sammen med det."""
            try:
                return fn()
            except Exception as exc:
                return {"ok": False,
                        "feil": f"Delen feilet ({type(exc).__name__}): {exc}"[:300]}

        # --- raske deterministiske deler ---
        # Bygges via motoren mot DEN SAMME konteksten (ktx), så den flate
        # bryter-responsen og operasjoner-veien deler nøyaktig samme
        # utregning. FelterOperasjon/StrukturOperasjon pakker svaret i
        # {type, ok, data}; her plukkes «data» ut for å beholde den flate
        # formen bryter-klientene alt får (uendret respons).
        if valg["felter"]:
            def _felter_del():
                data = FelterOperasjon().utfor(ktx)["data"]
                if not vil_ha_datodetaljer:
                    # nøkkelen blir stående (R44), men uten innholdet
                    data["datoer_detaljert"] = None
                return data
            deler["felter"] = trygt(_felter_del)
        if valg["struktur"]:
            deler["struktur"] = trygt(lambda: StrukturOperasjon().utfor(ktx)["data"])

        # --- modelldeler (kun på forespørsel) ---
        if valg["svar"]:
            # En ren sidelesing («les side 10») besvares deterministisk i
            # svar_paa_sporsmal — den skal virke selv når Borealis er nede
            if not borealis_klar and not kan_svares_uten_modell(sporsmal):
                deler["svar"] = {"ok": False, "feil": borealis_feil}
            elif tomt_dokument:
                deler["svar"] = {"ok": False, "feil": tom_feil}
            else:
                def _svar_del():
                    kjerne = svar_paa_sporsmal(raa_tekst, sporsmal, ocr_brukt,
                                               handskrift, strekkoder,
                                               les_strekkoder)
                    if kjerne["tom"]:
                        return {"ok": False, "feil": tom_feil}
                    advarsler.extend(kjerne["advarsler"])
                    return {"ok": True, "sporsmal": sporsmal,
                            "svar": kjerne["svar"],
                            "modell_brukt": kjerne.get("modell_brukt", True),
                            "tall_verifisert": kjerne["tall_verifisert"],
                            "tolket_sporsmal": kjerne["tolket_sporsmal"],
                            "svar_avkortet": kjerne["svar_avkortet"]}
                deler["svar"] = trygt(_svar_del)

        if valg["skjema"]:
            if skjema_motor == "felter":
                # Deterministisk: fyll {feltnavn}-plassholdere fra de
                # deterministisk funnede feltene. Ingen modell, ingen
                # venting — virker selv om Borealis er nede eller
                # dokumentet er «tomt» for modellens smak.
                def _flett_del():
                    utfylt, rapport = flett_mal(mal, raa_tekst, ocr_brukt)
                    return {"ok": True, "motor": "felter",
                            "skjema": utfylt,
                            "ukjente_felter": rapport["ukjente_felter"],
                            "tilgjengelige_felter":
                                rapport["tilgjengelige_felter"]}
                deler["skjema"] = trygt(_flett_del)
            elif skjema_motor == "auto":
                # Hybrid: deterministisk der regelen kan BEVISE, modell for
                # resten (navn o.l. uten fast form) — med tallvakt. Faller
                # tilbake til ren deterministisk hvis Borealis er nede.
                def _hybrid_del():
                    res = flett_mal_hybrid(raa_tekst, mal, ocr_brukt,
                                           borealis_klar and not tomt_dokument)
                    res["motor"] = "auto"
                    return res
                deler["skjema"] = trygt(_hybrid_del)
            elif not borealis_klar:
                deler["skjema"] = {"ok": False, "feil": borealis_feil}
            elif tomt_dokument:
                deler["skjema"] = {"ok": False, "feil": tom_feil}
            else:
                deler["skjema"] = trygt(lambda: fyll_skjema_kjerne(raa_tekst, mal))

        korrigert = None
        if valg["korriger"]:
            if not borealis_klar:
                deler["korriger"] = {"ok": False, "feil": borealis_feil}
            elif not ocr_brukt:
                deler["korriger"] = {"ok": False, "feil": (
                    "Dokumentet har tekstlag — ingen OCR-feil å korrigere")}
            elif tomt_dokument:
                deler["korriger"] = {"ok": False, "feil": tom_feil}
            else:
                deler["korriger"] = trygt(lambda: {
                    "ok": True, "tekst": korriger_borealis(raa_tekst)})
                korrigert = deler["korriger"].get("tekst")

        # «kilde» skal si hva som FAKTISK skjedde, ikke hva som ble bedt om.
        # auto-motoren kaller modellen bare for de feltene den ikke klarte å
        # bevise deterministisk, så svaret ligger i «modell_brukt» — ikke i
        # bryteren. Uten dette meldte /dokument «deterministisk» selv når
        # Borealis hadde fylt et felt, og klienten kunne ikke se forskjell
        # på et bevist og et gjettet svar. /fyll_skjema gjorde det allerede
        # riktig; dette retter opp forskjellen mellom de to veiene.
        # Samme ærlighet for svar-delen: en ren sidelesing besvares uten
        # modell (modell_brukt=False fra kjernen), og da skal kilden si
        # «deterministisk» selv om svar=ja var på.
        modell_kjorte = _modellen_kjorte(deler)

        # Feil i en del skal også være synlig for den som bare leser
        # advarslene (GUI-et, en enkel klient) — ikke bare i deltreet
        for navn in ("felter", "struktur", "svar", "skjema", "korriger"):
            del_ = deler.get(navn)
            if isinstance(del_, dict) and del_.get("ok") is False:
                advarsler.append(f"{navn}: {del_.get('feil')}")

        # R79: dokumentprofilen følger ALLTID med — den er ikke en del av
        # «valg». Sideantall, koder, dokumentdato og hvem dokumentet
        # gjelder er egenskaper ved dokumentet selv, ikke svar på et
        # spørsmål, og en klient skal ikke måtte be om dem for å få dem.
        profil = trygt(lambda: _profilform(ktx.profil, profilform))
        # Revisjonen fant at de tre veiene til samme faktum FAKTISK var
        # uenige i et ekte svar, og konkluderte med å beholde alle tre —
        # de har ulik garanti. Men uenigheten ble aldri MELDT, så en
        # klient måtte oppdage den selv. Nå sier vi fra.
        advarsler.extend(
            trygt(lambda: _uenighet_med_modellen(ktx.profil, deler)) or [])
        # Kartet er en PROJEKSJON av feltene profilen alt har fylt — ikke
        # en ny beregning. Ellers ville «opphav» blitt en sjette
        # uavhengig mening om det samme, altså problemet det løser.
        opphav = trygt(lambda: bygg_opphav(ktx.profil, opphavsnivaa,
                                           ktx.tekst)) or {}
        # profil=sammendrag tok seksjoner bort; da skal ingen peker vise
        # dit. En peker til et fjernet felt lekker nettopp det bryteren
        # skulle skjule, og gir klienten et oppslag som ikke går noe sted.
        opphav = uten_utelatte(opphav, profil if isinstance(profil, dict) else {})
        skjemadel = deler.get("skjema")
        if isinstance(skjemadel, dict) and skjemadel.get("kilde_per_felt"):
            opphav.update(opphav_for_skjema(skjemadel["kilde_per_felt"]))

        svar = {
            "ok": True, "filnavn": filnavn,
            "valg": valg,
            "dokumentprofil": profil,
            "opphav": opphav,
            "tekst": raa_tekst if valg["tekst"] else None,
            "antall_tegn": len(raa_tekst),
            "antall_sider": ktx.antall_sider,
            # Samme faktum som «kilde», men som bool. «kilde» må
            # delstreng-søkes etter «borealis», og det er en kontrakt
            # klienter skriver feil.
            "modell_brukt": modell_kjorte,
            "felter": deler.get("felter"),
            "struktur": deler.get("struktur"),
            "svar": deler.get("svar"),
            "skjema": deler.get("skjema"),
            "korriger": deler.get("korriger"),
            "korrigert_tekst": korrigert,
            "koordinater": koordinater,
            # Se samme felt på operasjonsveien: null når målingen aldri
            # ble gjort, ikke en tom liste som påstår at vi så etter.
            "strekkoder": strekkoder if ktx.strekkoder_lest else None,
            "handskrift": handskrift if ktx.ocr_brukt else None,
            # Strukturerte varsler ved siden av de frie strengene, så en
            # klient kan skille «ukjent felt» fra «modellen er nede» uten
            # tekstsøk. Strengene beholdes uendret.
            "varsler": _varsler(advarsler),
            "status": _samlet_status(deler, advarsler),
            "kvalitet": {"ocr_brukt": ocr_brukt,
                         "ocr_motorer": ocr_motorer or {},
                         "advarsler": advarsler},
            "fra_cache": fra_cache,
            "tid_sekunder": round(time.time() - t0, 1),
            "kilde": ("borealis+deterministisk" if modell_kjorte
                      else "deterministisk"),
            "versjon": {"api": API_VERSJON, "prompt": prompter.versjon(),
                        "modell": _borealis["modellfil"] or _borealis["motor"] or None},
        }
        # Personvernbryteren gjelder HELE svaret. _profilform renset
        # dokumentprofilen; «tekst» og «felter» bygges utenom den, og
        # begge er PÅ som standard — så fødselsnummeret nådde fram
        # likevel. Se _sammendragsform.
        if profilform == "sammendrag":
            svar = _sammendragsform(svar)
        return self._svar(200, svar)

    def do_POST(self):
        self._t0_req = time.time()
        # Sikkerhetsnett: en uventet feil skal gi et ærlig JSON-svar
        # (500), aldri en taus lukket forbindelse som blir 502 i tunnelen
        try:
            return self._do_post_intern()
        except Exception as exc:
            return self._serverfeil(exc)
        finally:
            # slipp køplassen uansett hvordan forespørselen endte
            if getattr(self, "_har_koeplass", False):
                self._har_koeplass = False
                _kapasitet_port.slipp()

    def _ta_koeplass(self, sti: str) -> bool:
        """Sikrer en plass i den MÅLTE kapasiteten. Får vi ingen innen
        fristen, svarer vi ÆRLIG 503 med Retry-After — bedre enn å la
        klienten henge i minutter uten å vite hvorfor."""
        if sti not in _TUNGE_STIER:
            return True
        if _kapasitet_port.ta(KOE_VENT_S):
            self._har_koeplass = True
            return True
        kap = _kapasitet_port.status()
        self._svar(503, {
            "ok": False,
            "feil": (f"Serveren er opptatt: den bærer {kap['grense']} "
                     f"forespørsler samtidig på denne maskinen (begrenset av "
                     f"{kap['binder']}), og køen ble ikke ledig innen "
                     f"{int(KOE_VENT_S)} s. Prøv igjen, eller bruk POST /jobb "
                     "for store dokumenter (svarer med en gang og arbeider i "
                     "bakgrunnen)."),
            "opptatt": True,
            "kapasitet": kap,
        }, hoder={"Retry-After": "30"})
        return False

    def _do_post_intern(self):
        sti = self._sti()
        if not self._rate_ok():          # før auth: beskytt selve nøkkelsjekken
            return
        if not self._autorisert():
            return self._svar(401, {"ok": False, "feil": "Ugyldig eller manglende X-API-Key"})

        # Avbryt-endepunktet trenger ingen kropp
        if sti.startswith("/jobb/") and sti.endswith("/avbryt"):
            jid = sti.split("/")[2]
            jobb = _jobber.get(jid)
            if jobb is None:
                return self._svar(404, {"ok": False, "feil": "Ukjent jobb_id"})
            # Optimistisk låsing (NAV-konvensjon): sender klienten en
            # forventet versjon (?versjon=N eller X-Versjon-header) og den
            # ikke stemmer, har noen andre — typisk arbeidstråden — endret
            # jobben siden klienten sist så den. Da 409, med gjeldende
            # versjon så klienten kan hente på nytt og vurdere om avbrudd
            # fortsatt er ønskelig. Uten oppgitt versjon: uendret oppførsel.
            forventet = self._forventet_versjon()
            if forventet is not None and forventet != jobb.get("versjon"):
                return self._svar(409, {
                    "ok": False,
                    "feil": (f"Versjonskonflikt: du sendte versjon {forventet}, "
                             f"men jobben er nå versjon {jobb.get('versjon')} "
                             f"(status {jobb.get('status')}). Hent på nytt."),
                    "jobb_id": jid, "versjon": jobb.get("versjon"),
                    "status": jobb.get("status")})
            if jobb.get("status") in ("kø", "pågår"):
                jobb["avbrutt"] = True
                return self._svar(200, {"ok": True, "jobb_id": jid,
                                        "status": "avbrytes",
                                        "versjon": jobb.get("versjon")})
            return self._svar(409, {
                "ok": False,
                "feil": f"Jobben er allerede {jobb.get('status')}",
                "jobb_id": jid, "versjon": jobb.get("versjon"),
                "status": jobb.get("status")})

        if sti not in ("/spor", "/jobb", "/innsyn", "/dokument",
                       "/dokument/operasjoner", "/ekko",
                       "/forhandssjekk", "/sladd"):
            return self._svar(404, {"ok": False, "feil": "Bruk POST /dokument, /dokument/operasjoner, /spor, /innsyn, /jobb, /forhandssjekk, /sladd eller /ekko (se /hjelp)"})

        # Køplass tas FØR kroppen leses. Tas den etterpå, har hver ventende
        # tråd allerede hele opplastingen (og den normaliserte PDF-en) i
        # minnet mens den står i kø — målt: vakten alene endret hverken RAM
        # (8,1 GB) eller trådtall. Nå holdes dataene i klientens
        # socket-buffer i stedet, og bare de som faktisk arbeider bruker
        # minne. Ruting, rate-limit og auth over skjer uten køplass, så en
        # feilformet forespørsel aldri opptar en.
        if not self._ta_koeplass(sti):
            return
        try:
            lengde = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._svar(400, {"ok": False, "feil": "Ugyldig Content-Length"})
        # Negativ lengde ville ellers bli read(-1) = les til EOF og
        # omgå størrelsesgrensen — avvis eksplisitt
        if lengde < 0 or lengde > MAKS_BYTES:
            return self._svar(413, {"ok": False, "feil": f"Ugyldig eller for stor forespørsel (maks {MAKS_BYTES//1024//1024} MB)"})

        # Minnevakt FØR innlesing: hele kroppen leses inn i minnet, så uten
        # denne er taket N samtidige × MAKS_BYTES. Avvis ærlig i stedet.
        with _i_flukt_las:
            if (_i_flukt_bytes["n"] + lengde) > MAKS_SAMTIDIGE_MB * 1024 * 1024:
                for_mye = True
            else:
                _i_flukt_bytes["n"] += lengde
                for_mye = False
        if for_mye:
            self._tapp_kropp(lengde)      # tøm kroppen så tilkoblingen er ren
            return self._svar(503, {
                "ok": False,
                "feil": ("Serveren tar imot for mye data samtidig akkurat nå "
                         f"(grense {MAKS_SAMTIDIGE_MB} MB). Prøv igjen om litt, "
                         "eller bruk POST /jobb for store dokumenter."),
            }, hoder={"Retry-After": "20"})
        try:
            body = self.rfile.read(lengde) if lengde else b""
        finally:
            with _i_flukt_las:
                _i_flukt_bytes["n"] -= lengde
        ct = self.headers.get("Content-Type", "")

        # Diagnose: /ekko svarer med NØYAKTIG hva klienten sendte (rå
        # multipart-deler + hva parseren ser). Til feilsøking av klienter
        # (UiPath o.l.) der tekstfelter «forsvinner» — vi ser da om delene
        # faktisk kom, og med hvilket Content-Disposition-navn.
        if sti == "/ekko":
            return self._ekko(body, ct)

        tekstfelter = {}
        if "multipart/form-data" in ct:
            filnavn, data, tekstfelter = _parse_multipart(body, ct)
        else:
            # tillat òg rå PDF-bytes i body (Content-Type: application/pdf)
            filnavn, data = "opplastet.pdf", body

        # Omvendt feltnavn stoppes for ALLE ruter, ikke bare de fire som
        # hadde vakten fra før. Sjekken står her fordi det er det ene
        # stedet der både ruten og de parsede feltene er kjent — en ny
        # rute er dermed dekket i det den legges i _FELTSETT_PER_RUTE, i
        # stedet for å måtte huske et kall inne i hver håndterer.
        #
        # Rutene som allerede har sin egen sjekk beholder den: den bærer
        # også den MILDE advarselen inn i sitt eget svar, og den kan ikke
        # flyttes hit uten å kjenne svarformen. Her stoppes bare den
        # klare feilen.
        _kjente_felt = _FELTSETT_PER_RUTE.get(sti)
        if _kjente_felt is not None:
            _, _omvendte = _sjekk_feltnavn(tekstfelter, _kjente_felt)
            if _omvendte:
                return self._svar(400, _omvendt_felt_feil(_omvendte,
                                                          _kjente_felt))

        # /spor kan bruke jobb_id i stedet for fil — eller stå helt uten
        # fil (rent spørsmål → generelt modellsvar)
        jobb_ref = tekstfelter.get("jobb_id", "").strip() if sti == "/spor" else ""
        rent_sporsmal = bool(sti == "/spor" and data is None and not jobb_ref
                             and tekstfelter.get("sporsmal", "").strip())
        if data is None and not jobb_ref and not rent_sporsmal:
            return self._svar(400, {"ok": False, "feil": "Ingen fil funnet i multipart-body (felt 'fil')"})

        # Normaliser filtypen: PDF forblir PDF, bilder blir PDF,
        # DOCX/TXT gir teksten direkte
        slag, innhold = None, None
        if not jobb_ref and data is not None:
            # Korrupt/avkortet fil (bilde/DOCX/XLSX) skal gi et ryddig 400
            # som PDF-er gjør — ikke et 500 som lekker intern feiltype
            try:
                slag, innhold = normaliser_fil(filnavn, data)
            except Exception as exc:
                return self._svar(400, {"ok": False,
                                        "feil": f"Kunne ikke lese filen ({filnavn}): "
                                                f"korrupt eller ugyldig format ({type(exc).__name__})"})
            if slag is None:
                return self._svar(400, {"ok": False, "feil": innhold})

        # Forhåndssjekk: kvalitetsdom uten OCR og uten modell. Ruges så
        # tidlig fordi den ikke trenger noe av maskineriet under.
        if sti == "/forhandssjekk":
            if innhold is None:
                return self._svar(400, {
                    "ok": False, "feil": "Ingen fil funnet (felt 'fil')"})
            return self._forhandssjekk(filnavn, slag, innhold, tekstfelter)

        # Valgfri sidegrense for synkron OCR (felt maks_sider).
        # En UGYLDIG verdi ble stille ignorert: «maks_sider=abc» ga
        # ubegrenset lesing, uten 400 og uten advarsel. Klienten trodde
        # den hadde satt en grense. Det er samme feilmodus som
        # feltnavnvakten finnes for — et kjent felt som forsvinner i
        # stillhet — og maks_sider var unntatt fra begge.
        _raa_sider = (tekstfelter.get("maks_sider", "") or "").strip()
        _onsket_sider = 0
        if _raa_sider:
            try:
                _onsket_sider = int(_raa_sider)
            except ValueError:
                _onsket_sider = -1
            if _onsket_sider < 1:
                return self._svar(400, {
                    "ok": False,
                    "feil": (f"Ugyldig 'maks_sider': {_raa_sider!r}. "
                             f"Bruk et helt tall større enn 0, eller la "
                             f"feltet stå tomt for ingen grense."),
                    "felter_feil": [{"pointer": "/maks_sider",
                                     "message": "helt tall > 0"}]})
        maks_ocr = min(_onsket_sider, OCR_TAK_SIDER) if _onsket_sider > 0 else None
        # Kapping er ikke en feil, men den skal SIES: ba klienten om 999
        # sider og fikk 50, må den kunne se det. Advarselen legges på
        # forespørselen og plukkes opp av _les_dokument, som begge
        # svarveiene går gjennom.
        self._kappet_advarsel = (
            f"maks_sider={_onsket_sider} er kappet til taket "
            f"{OCR_TAK_SIDER} — bare de første {OCR_TAK_SIDER} sidene "
            f"ble lest"
            if _onsket_sider > OCR_TAK_SIDER else None)

        # R55: strekkodeskanning kan slås av per forespørsel
        # (strekkoder=nei). Den koster ~0,2 s per side, og de fleste
        # NAV-dokumenter har ingen koder å finne. Standard er PÅ, så
        # ingen eksisterende klient mister noe uten å be om det.
        les_strekkoder, _ukjent = bryterverdi(
            tekstfelter.get("strekkoder"), True)
        if _ukjent:
            # Tidligere: alt utenom den egne, ufullstendige NEI-lista ble
            # tolket som PÅ. «strekkoder=off» slo den derfor PÅ, mens
            # «struktur=off» slo AV — samme forespørsel, motsatt svar.
            # Og «strekkoder=tull» ga 200 der «struktur=tull» ga 400.
            return self._svar(400, {
                "ok": False,
                "feil": (f"Ukjent bryterverdi: strekkoder="
                         f"{tekstfelter.get('strekkoder', '')[:40]!r}. "
                         f"Bruk {'/'.join(BRYTER_JA[:4])} eller "
                         f"{'/'.join(BRYTER_NEI[:4])}."),
                "felter_feil": [{"pointer": "/strekkoder",
                                 "message": "ukjent bryterverdi"}]})

        # Sladding: leser dokumentet (med OCR ved behov) og sladder alt
        # som kan bevises. Rutes etter maks_ocr-parsingen fordi OCR kan
        # være del av jobben.
        if sti == "/sladd":
            if innhold is None:
                return self._svar(400, {
                    "ok": False, "feil": "Ingen fil funnet (felt 'fil')"})
            return self._sladd(filnavn, slag, innhold, maks_ocr, tekstfelter)

        # R58: kom forespørselen mens OCR-motorene lastes, ville den blitt
        # stående på motorlåsen i opptil et halvt minutt. Si fra med en
        # gang i stedet — klienten kan prøve igjen straks etterpå.
        if _oppvarming["pagaar"] and innhold is not None and slag == "pdf":
            return self._svar(503, {
                "ok": False,
                "feil": ("OCR-motorene varmer opp etter oppstart — prøv igjen "
                         "om cirka 15 sekunder"),
                "ocr": "varmer_opp",
            })

        if sti == "/innsyn":
            return self._innsyn(filnavn, slag, innhold, maks_ocr)

        if sti == "/dokument":
            return self._dokument_samlet(filnavn, slag, innhold, maks_ocr,
                                         tekstfelter, les_strekkoder)

        # Operasjonene som EGEN ressurs (planpunkt 36). På /dokument er
        # «operasjoner» et felt som overstyrer bryterne i stillhet —
        # sender en klient begge deler, skjer det ingenting med bryterne.
        # En egen sti gjør valget synlig i URL-en. Feltveien beholdes.
        if sti == "/dokument/operasjoner":
            raa = (tekstfelter.get("operasjoner") or "").strip()
            if not raa:
                return self._svar(400, {"ok": False, "feil": (
                    "Feltet 'operasjoner' er påkrevd på denne ressursen. "
                    "Send en JSON-liste, f.eks. [{\"type\":\"felter\"}]."),
                    "felter_feil": [{"pointer": "/operasjoner",
                                     "message": "Påkrevd her"}]})
            return self._dokument_operasjoner(
                filnavn, slag, innhold, maks_ocr, les_strekkoder, raa,
                tekstfelter)

        if sti == "/jobb":
            # Idempotens: samme Idempotency-Key → samme jobb (retry-trygt).
            idem = re.sub(r"[^A-Za-z0-9._-]", "",
                          self.headers.get("Idempotency-Key", ""))[:64]
            if idem:
                with _jobb_las:
                    tidligere = _idempotens.get(idem)
                if tidligere and tidligere in _jobber:
                    with _jobb_las:
                        vis = {k: v for k, v in _jobber[tidligere].items()
                               if not k.startswith("_")}
                    vis["ok"] = True
                    vis["idempotent_gjenbruk"] = True
                    return self._svar(200, vis)
            jobb_id = uuid.uuid4().hex[:12]
            # Alle feltene arbeidstråden senere fyller, forhåndsdeklareres
            # her — da endrer den bare VERDIER (aldri dict-størrelse), så
            # en samtidig statuspoll aldri krasjer under iterasjon.
            jobb = {"jobb_id": jobb_id, "filnavn": filnavn, "status": "kø",
                    "versjon": 1,
                    "sider_ferdig": 0, "sider_totalt": None,
                    "sekunder_brukt": 0, "sekunder_igjen_estimat": None,
                    "tekst": "", "antall_tegn": 0, "felter": {}, "datoer": [],
                    "dokumentdato": None,
                    "strekkoder": [], "handskrift": [], "ocr_motorer": {},
                    "opprettet": time.strftime("%Y-%m-%d %H:%M:%S")}
            if slag == "tekst":
                t = innhold.strip()
                jobb.update(status="ferdig", tekst=t, antall_tegn=len(t),
                            felter=utvid_entiteter(t, {}),
                            datoer=finn_alle_datoer(t),
                            dokumentdato=dokumentdato_av(t),
                            strekkoder=[],
                            handskrift=[], ocr_motorer={})
                _jobber[jobb_id] = jobb
                _jobb_lagre(jobb)
            else:
                jobb["_data"] = innhold
                _jobber[jobb_id] = jobb
                _jobb_ko.put(jobb_id)
            if idem:
                with _jobb_las:
                    _idempotens[idem] = jobb_id
                    while len(_idempotens) > 2000:   # eldste ryddes
                        _idempotens.pop(next(iter(_idempotens)))
            return self._svar(202, {
                "ok": True, "jobb_id": jobb_id, "status": jobb["status"],
                "fremdrift": f"GET /jobb/{jobb_id}",
                "sporsmal_senere": f"POST /spor med felter jobb_id={jobb_id} og sporsmal",
            })

        # ---- /spor: fil + spørsmål → svar fra Borealis ----
        # R47: fil UTEN spørsmål = hele den utleste teksten, ordrett og
        # deterministisk (aldri modell). Fil MED tekst = utfør bestillingen.
        sporsmal = tekstfelter.get("sporsmal", "").strip()
        tom_foresporsel = not sporsmal

        # Er «spørsmålet» en JSON-mal (limt inn i spørsmålsfeltet i en
        # GUI), rutes den automatisk til skjemautfylling MED
        # kodevalidering — brukeren skal ikke trenge å kjenne endepunkter
        if not jobb_ref and innhold is not None and "{" in sporsmal and "}" in sporsmal:
            mal_kandidat = _parse_json_svar(sporsmal)
            if isinstance(mal_kandidat, dict) and mal_kandidat:
                return self._fyll_skjema_flyt(filnavn, slag, innhold,
                                              maks_ocr, mal_kandidat,
                                              via_spor=True,
                                              les_strekkoder=les_strekkoder)
        # En ren sidelesing («les side 10») besvares deterministisk fra
        # sidemarkørene og trenger ikke modellen — slipp den forbi
        # Borealis-portene, ellers gir en nede-modell 503 på noe koden
        # kan svare på alene.
        deterministisk_svar = (innhold is not None
                               and kan_svares_uten_modell(sporsmal))
        if (not tom_foresporsel and not deterministisk_svar
                and _borealis["status"] == "laster"):
            return self._svar(503, {"ok": False, "feil": "Borealis laster fortsatt — prøv igjen om ett minutt", "borealis": "laster"})
        if (not tom_foresporsel and not deterministisk_svar
                and _borealis["status"] != "klar"):
            return self._svar(503, {"ok": False, "feil": f"Borealis er ikke tilgjengelig ({_borealis['status']}): {_borealis['feil']}", "borealis": _borealis["status"]})

        # Rent spørsmål uten dokument → generelt modellsvar, ærlig merket.
        # R50: modellen skal svare direkte — små modeller ber ellers om
        # «mer kontekst» på åpne oversiktsspørsmål i stedet for å svare.
        if rent_sporsmal:
            t0 = time.time()
            svar, avkortet = _borealis_generer(
                prompter.hent("spor.uten_dokument", sporsmal=sporsmal),
                MAKS_SVAR_TOKENS)
            return self._svar(200, _spor_svar(
                modus="uten_dokument",
                sporsmal=sporsmal, svar=svar,
                uten_dokument=True,
                melding=("Ingen fil vedlagt — svaret er generell "
                         "modellkunnskap, IKKE hentet fra noe dokument, "
                         "og tallvakten gjelder derfor ikke"),
                svar_avkortet=avkortet,
                tid_sekunder=round(time.time() - t0, 1),
                kilde="borealis_" + (_borealis["motor"] or "ukjent")
                      + "_uten_dokument",
            ))

        t0 = time.time()
        ocr_brukt = False
        ocr_motorer = None
        handskrift = []
        advarsler = []
        fra_cache = False
        if jobb_ref:
            # Svar fra en ferdig bakgrunnsjobb — ingen ny OCR
            jobb = _jobber.get(jobb_ref)
            if jobb is None:
                return self._svar(404, {"ok": False, "feil": "Ukjent jobb_id"})
            if jobb.get("status") != "ferdig":
                return self._svar(409, {
                    "ok": False, "status": jobb.get("status"),
                    "sider_ferdig": jobb.get("sider_ferdig", 0),
                    "sider_totalt": jobb.get("sider_totalt"),
                    "feil": f"Jobben er ikke ferdig ennå ({jobb.get('status')})",
                })
            filnavn = jobb["filnavn"]
            tekst = jobb.get("tekst", "")
            strekkoder = jobb.get("strekkoder", [])
            handskrift = list(jobb.get("handskrift", []))
            ocr_motorer = jobb.get("ocr_motorer") or None
            ocr_brukt = bool(ocr_motorer)
        elif slag == "tekst":
            # DOCX/TXT: teksten er allerede hentet — ingen OCR/strekkoder
            tekst = innhold
            strekkoder = []
        else:
            # Hele analysen (tekstlag/OCR/strekkoder) går gjennom cachen:
            # samme fil OCR-es aldri to ganger, og /spor deler nøyaktig
            # samme ekstraksjonslogikk som /analyser og /uttrekk
            a = analyser_med_cache(filnavn, innhold, maks_ocr, les_strekkoder)
            if not a.get("ok"):
                return self._svar(400, a)
            tekst = a.get("tekst", "")
            strekkoder = a.get("strekkoder", [])
            handskrift = a.get("handskrift") or []
            ocr_motorer = a.get("ocr_motorer")
            ocr_brukt = a.get("ocr_brukt", False)
            fra_cache = a.get("fra_cache", False)
            if a.get("advarsel"):
                advarsler.append(a["advarsel"])

        raa_tekst = tekst   # ren OCR/dokumenttekst — før merking og vedlegg

        # «korriger» godtok bare ("ja","1","true") her, mens den samme
        # bryteren på /dokument godtar tolv verdier. «korriger=på» var
        # altså SANN på én rute og USANN på en annen — samme ord, samme
        # API. Nå leser begge det felles verdirommet, og en ukjent verdi
        # avvises i stedet for å bli tolket som «nei».
        vil_korrigere, _ukjent_korr = bryterverdi(
            tekstfelter.get("korriger"), False)
        if _ukjent_korr:
            return self._svar(400, {
                "ok": False,
                "feil": (f"Ukjent bryterverdi: korriger="
                         f"{tekstfelter.get('korriger', '')[:40]!r}. "
                         f"Bruk {'/'.join(BRYTER_JA[:4])} eller "
                         f"{'/'.join(BRYTER_NEI[:4])}."),
                "felter_feil": [{"pointer": "/korriger",
                                 "message": "ukjent bryterverdi"}]})

        # Verbatim-svar besvares av KODEN, ikke modellen: en språkmodell
        # som skriver av kan hoppe over linjer — koden kan ikke.
        # Gjelder både eksplisitte «hele teksten»-forespørsler (R43) og
        # fil sendt UTEN spørsmål (R47).
        if tom_foresporsel or re.search(
                r"(?i)hele\s+(tekst|dokument|innhold)|all\s+tekst", sporsmal):
            return self._svar(200, _spor_svar(
                modus="fulltekst",
                filnavn=filnavn, sporsmal=sporsmal,
                melding=("Ingen spørsmål oppgitt — hele den utleste "
                         "teksten returneres ordrett, uten tillegg "
                         "eller utelatelser") if tom_foresporsel else None,
                svar=raa_tekst,
                ocr_brukt=ocr_brukt,
                strekkoder=strekkoder, ocr_motorer=ocr_motorer,
                handskrift=handskrift,
                korrigert_tekst=(korriger_borealis(raa_tekst)
                                 if ocr_brukt and vil_korrigere else None),
                tall_verifisert=True,
                svar_avkortet=False,
                fra_cache=fra_cache,
                tid_sekunder=round(time.time() - t0, 1),
                kilde="deterministisk_fulltekst",
            ))

        kjerne = svar_paa_sporsmal(raa_tekst, sporsmal, ocr_brukt,
                                   handskrift, strekkoder, les_strekkoder)
        if kjerne["tom"]:
            # Det TOMME dokumentet var verst: 8 nøkler, og uten
            # «versjon» — stikk i strid med R39. En bunke med én blank
            # side krasjet roboten på nettopp den siden.
            return self._svar(200, _spor_svar(
                modus="tomt_dokument",
                filnavn=filnavn, sporsmal=sporsmal,
                trenger_ocr=True,
                ocr_brukt=ocr_brukt, svar=None, strekkoder=strekkoder,
                ocr_motorer=ocr_motorer, handskrift=handskrift,
                fra_cache=fra_cache,
                tid_sekunder=round(time.time() - t0, 1),
                kilde="deterministisk_tom",
                melding=("Fant ingen lesbar tekst i dokumentet — selv med OCR. "
                         "(Rene bilder uten skrift gir ingen tekst.)"),
            ))
        advarsler.extend(kjerne["advarsler"])
        svar = kjerne["svar"]
        tall_verifisert = kjerne["tall_verifisert"]
        tolket_sporsmal = kjerne["tolket_sporsmal"]
        svar_avkortet = kjerne["svar_avkortet"]
        advarsel = "; ".join(advarsler) if advarsler else None

        # Valgfri OCR-korrigering (multipart-felt korriger=ja) — egen
        # generering, koster ekstra tid, derfor kun på forespørsel
        korrigert = None
        if ocr_brukt and vil_korrigere:
            korrigert = korriger_borealis(raa_tekst)

        return self._svar(200, _spor_svar(
            modus="dokumentsporsmal",
            filnavn=filnavn, sporsmal=sporsmal,
            svar=svar, ocr_brukt=ocr_brukt,
            strekkoder=strekkoder, ocr_motorer=ocr_motorer,
            handskrift=handskrift,
            korrigert_tekst=korrigert,
            tall_verifisert=tall_verifisert,
            tolket_sporsmal=tolket_sporsmal,
            svar_avkortet=svar_avkortet,
            advarsel=advarsel,
            fra_cache=fra_cache,
            tid_sekunder=round(time.time() - t0, 1),
            # Ærlig kilde: en ren sidelesing gikk aldri innom modellen
            kilde=(("deterministisk_sideutsnitt"
                    if kjerne.get("modell_brukt") is False
                    else "borealis_" + (_borealis["motor"] or "ukjent"))
                   + ("+regionocr" if ocr_brukt else "")),
        ))

    def log_request(self, code='-', size='-'):
        # Strukturert tilgangslogg + behold den ryddige stdout-linjen.
        _skriv_tilgang(self, code)
        super().log_request(code, size)

    def log_message(self, fmt, *args):
        # Én ryddig linje per forespørsel så du ser at UiPath treffer
        print(f"  [{self.command}] {self.path} → {args[1] if len(args) > 1 else ''}")


# ------------------------------------------------------------------ #
#  Direktevisning («røntgen» av lesingen) — /innsyn                    #
# ------------------------------------------------------------------ #
_innsyn_okter = {}
_innsyn_las = threading.Lock()


def _bilde_til_b64(bilde_np, maks_bredde: int = 900):
    """PNG-base64 av et sidebilde, nedskalert for rask overføring.
    Returnerer (b64, vist_bredde, vist_hoyde, full_bredde, full_hoyde) —
    GUI-et skalerer boksene med full/vist-forholdet."""
    import base64
    from io import BytesIO

    from PIL import Image
    full_h, full_b = bilde_np.shape[0], bilde_np.shape[1]
    img = Image.fromarray(bilde_np)
    if img.width > maks_bredde:
        img = img.resize((maks_bredde,
                          max(1, int(img.height * maks_bredde / img.width))))
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return (base64.b64encode(buffer.getvalue()).decode("ascii"),
            img.width, img.height, full_b, full_h)


def _innsyn_arbeider(okt, filnavn, slag, innhold, maks_ocr):
    """Bakgrunnstråden som faktisk behandler dokumentet for /innsyn —
    hendelsene strømmer via delt.innsyn_hendelser mens det skjer."""
    from delt import innsyn_hendelser
    innsyn_hendelser.aktiver(okt["hendelser"])
    try:
        t0 = okt["start"]
        if slag != "pdf":
            okt["resultat"] = {
                "ok": True, "filnavn": filnavn, "kilde": "tekstlag",
                "melding": "Ren tekst (DOCX/TXT) — ingen OCR å vise.",
                "tekst": innhold if isinstance(innhold, str) else "",
                "regioner": [], "tid_sekunder": round(time.time() - t0, 1)}
            okt["status"] = "ferdig"
            innsyn_hendelser.send("ferdig", kilde="tekstlag")
            return

        import fitz
        doc = fitz.open(stream=innhold, filetype="pdf")
        tekstlag = "".join((s.get_text() or "") for s in doc)
        if len(tekstlag.strip()) >= 20:
            import numpy as np
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72))
            bilde = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n)[:, :, :3]
            b64, vb, vh, fb, fh = _bilde_til_b64(np.ascontiguousarray(bilde))
            doc.close()
            innsyn_hendelser.send("side_bilde", stadie="original", bilde=b64,
                                  vist_bredde=vb, vist_hoyde=vh,
                                  full_bredde=fb, full_hoyde=fh)
            okt["resultat"] = {
                "ok": True, "filnavn": filnavn, "kilde": "tekstlag",
                "melding": ("PDF-en har innebygd tekstlag — teksten leses "
                            "direkte, ingen OCR kjøres."),
                "tekst": tekstlag.strip(), "regioner": [],
                "tid_sekunder": round(time.time() - t0, 1)}
            okt["status"] = "ferdig"
            innsyn_hendelser.send("ferdig", kilde="tekstlag")
            return
        doc.close()

        ocr_res = ocr_pdf_bytes(innhold, maks_ocr)
        regioner = [{
            "boks": r.get("boks"), "tekst": r.get("tekst", ""),
            "motor": r.get("motor", ""), "konfidens": r.get("konfidens", 0.0),
            "skrift": r.get("skrift", ""),
            "easyocr_tekst": r.get("easyocr_tekst"),
            "easyocr_konfidens": r.get("easyocr_konfidens"),
            "norhand_tekst": r.get("norhand_tekst"),
            "norhand_konfidens": r.get("norhand_konfidens"),
        } for r in (ocr_res.get("_side1_regioner") or [])]
        okt["resultat"] = {
            "ok": True, "filnavn": filnavn, "kilde": "regionocr",
            "regioner": regioner,
            "forbehandling": ocr_res.get("forbehandling"),
            "tekst": ocr_res.get("tekst", "").strip(),
            "ocr_konfidens": ocr_res.get("konfidens"),
            "ocr_motorer": ocr_res.get("motorer"),
            "sider_lest": ocr_res.get("sider_lest"),
            "sider_totalt": ocr_res.get("sider_totalt"),
            "tid_sekunder": round(time.time() - t0, 1)}
        okt["status"] = "ferdig"
        innsyn_hendelser.send("ferdig", kilde="regionocr",
                              konfidens=ocr_res.get("konfidens"))
    except Exception as exc:
        okt["status"] = "feil"
        # Bare unntakstypen ut til klienten — meldingen kan
        # inneholde tekstfragmenter og filstier fra dokumentet.
        # Full detalj går til serverloggen, som ellers i systemet.
        print(f"  /innsyn feilet: {type(exc).__name__}: {exc}")
        okt["feil"] = (f"Lesingen feilet ({type(exc).__name__}). "
                       "Se serverloggen for detaljer.")
        innsyn_hendelser.send("feil", melding=okt["feil"])
    finally:
        innsyn_hendelser.deaktiver()


def fyll_skjema_kjerne(dok: str, mal: dict) -> dict:
    """Felles kjerne for /fyll_skjema og /dokument: fyller brukerens
    JSON-mal fra dokumentteksten. Modellen fyller, KODEN validerer
    (rens_skjemasvar). Modellen grunnes med deterministisk funnede beløp
    MED kontekst — så verdier havner i riktige felter (kampanjepris vs
    produktpris osv.). Returnerer {"ok": True, "skjema": ..., "avvik":
    [...]} eller {"ok": False, "feil": ..., "raasvar": ...}."""
    # Deterministisk beløpsgrunnlag: hvert beløp med konteksten sin,
    # så modellen ser HVA hvert tall hører til før den plasserer det
    belop_del = ""
    belop_liste = finn_alle_belop(dok, maks=40)
    if belop_liste:
        belop_del = ("\n" + prompter.avsnitt("fyll_skjema.belop_overskrift")
                     + "\n".join(f"- {b['raatekst']}: «{b['kontekst']}»"
                                 for b in belop_liste) + "\n")
    koder_liste = finn_koder_med_kontekst(dok, maks=25)
    if koder_liste:
        belop_del += ("\n" + prompter.avsnitt("fyll_skjema.koder_overskrift")
                      + "\n".join(f"- {k['verdi']}: «{k['kontekst']}»"
                                  for k in koder_liste) + "\n")
    # R53: datoene manglet i grunnlaget, selv om beløp og koder var
    # med. På en kvittering der OCR hadde forvansket datolinjen fant
    # modellen ingen brukbar dato og fylte feltet med søppel, mens
    # den deterministiske parseren hadde lest «12.06.2026» riktig
    # hele tiden. Nå får modellen de faktiske datoene å velge blant.
    dato_liste = klassifiser_datoer(dok, maks=15)
    if dato_liste:
        belop_del += ("\n" + prompter.avsnitt("fyll_skjema.datoer_overskrift")
                      + "\n".join(
                          f"- {d['dato']} ({d.get('etikett') or d['type']}):"
                          f" «{d.get('kontekst', '')}»"
                          for d in dato_liste) + "\n")

    # R57: identifikatorene manglet også. På en taxikvittering står
    # både «TLF 07550» (kortnummer i toppteksten) og «TELEFON :
    # 41288903»; modellen plukket det første, og kodevalideringen
    # måtte tømme feltet. Den deterministiske parseren VET hvilket
    # av tallene som er et gyldig norsk telefonnummer — den
    # kunnskapen skal modellen få, ikke gjette seg til.
    #
    # …men BARE de typene malen faktisk spør om (S5). Lista ble tidligere
    # bygget uansett innhold, så en mal som bare ba om et beløp fikk
    # fødselsnummer og kontonummer servert til språkmodellen. Persondata
    # ingen hadde bedt om, og plass som ellers går til dokumentteksten.
    onsket = identifikatortyper_i_mal(mal)
    merket = []
    for nokkel, etikett, finn in (
        ("telefonnummer", "telefonnummer", finn_alle_telefoner),
        ("organisasjonsnummer", "organisasjonsnummer",
         finn_alle_organisasjonsnummer),
        ("fodselsnummer", "fødselsnummer", finn_alle_fodselsnummer),
        ("kontonummer", "kontonummer", finn_alle_kontonummer),
        ("epost", "e-postadresse", finn_alle_eposter),
    ):
        if nokkel not in onsket:
            continue
        for verdi in finn(dok)[:5]:
            merket.append(f"- {verdi} er et gyldig {etikett}")
    if merket:
        belop_del += ("\n"
                      + prompter.avsnitt("fyll_skjema.identifikatorer_overskrift")
                      + "\n".join(merket) + "\n")

    prompt = prompter.hent(
        "fyll_skjema.mal",
        dokument=dok[:MAKS_LLM_TEGN],
        grunnlag=belop_del,
        mal=json.dumps(mal, ensure_ascii=False, indent=1))
    svar_tekst, _ = _borealis_generer(prompt, MAKS_SVAR_TOKENS)
    utfylt = _parse_json_svar(svar_tekst)
    if utfylt is None:
        svar_tekst, _ = _borealis_generer(
            prompt + "\n" + prompter.hent("fyll_skjema.paaminnelse"),
            MAKS_SVAR_TOKENS)
        utfylt = _parse_json_svar(svar_tekst)
    if utfylt is None:
        return {"ok": False,
                "feil": "Modellen ga ikke gyldig JSON etter to forsøk",
                # Sladdet: dette er modellens RÅUTDATA, generert fra
                # dokumentteksten, og et feilsvar er nettopp det som
                # havner i en supportsak eller et feilsporingssystem.
                "raasvar": sladd_tekst(svar_tekst[:1500])[0]}
    renset, avvik = rens_skjemasvar(mal, utfylt, dok)
    return {"ok": True, "skjema": renset, "avvik": avvik}


def flett_mal_hybrid(dok: str, mal, ocr_brukt: bool = False,
                     borealis_klar: bool = True):
    """Hybrid malfletting: det HANDFASTE deterministisk, RESTEN med modell.

    Regelen fyller først alt den kan BEVISE (sjekksum, mønster, kontekst)
    — raskt og uten hallusinasjon. Bare feltene den IKKE fant (typisk
    fritekst uten fast form: navn, begrunnelse, arbeidsgiver) sendes til
    modellen, som grunnes med de deterministisk funnede tallene og
    kontrolleres av tallvakten (rens_skjemasvar). Modellen rører ALDRI et
    felt regelen alt har bevist — matematikk slår gjetning.

    Returnerer {"ok": True, "skjema": utfylt, "kilde_per_felt": {...},
    "modell_brukt": bool, "avvik": [...], "ukjente_felter": [...]}.
    «kilde_per_felt» sier for hvert feltnavn om verdien kom fra
    «deterministisk» eller «modell» — full sporbarhet."""
    flat = felter_flatt(dok, ocr_brukt=ocr_brukt)
    referert = refererte_felt(mal)
    kilde_per_felt = {f: "deterministisk"
                      for f in referert if flat.get(f) is not None}
    mangler = [f for f in referert if flat.get(f) is None]

    avvik: list = []
    modell_brukt = False
    if mangler and borealis_klar:
        # Bare de manglende feltene til modellen — malen holdes liten, og
        # feltnavnet (klientens eget, f.eks. «avsender_navn») er hintet
        # modellen fyller etter. Gjenbruker HELE grunningen + tallvakten.
        sub_mal = {f: "" for f in mangler}
        sub = fyll_skjema_kjerne(dok, sub_mal)
        if sub.get("ok"):
            modell_brukt = True
            avvik = sub.get("avvik", [])
            for f in mangler:
                v = sub["skjema"].get(f, "")
                if v not in ("", None):
                    flat[f] = v               # beriker flat-tabellen
                    kilde_per_felt[f] = "modell"

    utfylt, rapport = flett_mal(mal, flat=flat)
    return {
        "ok": True,
        "skjema": utfylt,
        "kilde_per_felt": kilde_per_felt,
        "modell_brukt": modell_brukt,
        "avvik": avvik,
        "ukjente_felter": rapport["ukjente_felter"],
        "tilgjengelige_felter": rapport["tilgjengelige_felter"],
    }


# «[Side i av n]»-markørene er KODE-genererte (analyser_bytes/OCR) og
# dermed pålitelige ankere for siderouting.
_SIDE_MARKOR = re.compile(r"^\[Side (\d+) av (\d+)\]$", re.MULTILINE)
# Sidehenvisning i et spørsmål: «side 10», «sida 3» (nynorsk), «s. 2»
_SIDEREF = re.compile(r"\bs(?:ide|ida|\.)\s*(\d{1,3})\b", re.IGNORECASE)
# En REN lesebestilling («les side 10», «vis sida 2», «side 4», «hva
# står på side 6») besvares ordrett av koden — aldri av modellen.
_REN_SIDELESING = re.compile(
    r"^\W*(?:(?:les|vis|hent|gi\s+meg|skriv(?:\s+ut)?)\s+)?(?:hele\s+)?"
    r"s(?:ide|ida)\s*\d{1,3}\W*$"
    r"|^\W*hva\s+st(?:å|aa)r\s+p(?:å|aa)\s+s(?:ide|ida)\s*\d{1,3}\W*\??\W*$",
    re.IGNORECASE)


def del_i_sider(tekst: str):
    """(antall_sider, {sidenr: sidetekst}) fra sidemarkørene. Tekst uten
    markører er ett-sidig: hele teksten er side 1."""
    treff = list(_SIDE_MARKOR.finditer(tekst or ""))
    if not treff:
        return 1, {1: (tekst or "").strip()}
    sider = {}
    for i, m in enumerate(treff):
        slutt = treff[i + 1].start() if i + 1 < len(treff) else len(tekst)
        sider[int(m.group(1))] = tekst[m.end():slutt].strip()
    antall = max(max(int(m.group(2)) for m in treff), max(sider))
    return antall, sider


def _sporsmalets_sideref(sporsmal: str):
    m = _SIDEREF.search(sporsmal or "")
    return int(m.group(1)) if m else None


def er_ren_sidelesing(sporsmal: str) -> bool:
    """Kan spørsmålet besvares HELT uten modell (ordrett sideutsnitt)?
    Brukes også av 503-portene: en ren sidelesing skal virke selv når
    Borealis er nede."""
    return bool(_REN_SIDELESING.match(sporsmal or ""))


# Spørsmål som ber om strekkode-/QR-VERDIEN. Verdien er DEKODET av en
# strekkodeleser (sjekksumsikret av selve symbologien) — det er
# matematikk, ikke gjetning, og skal aldri gå veien om modellen.
_STREKKODE_SPM = re.compile(
    r"^\W*(?:(?:hva|hvilken|hvilke)\s+(?:er|st(?:å|aa)r)?\s*)?"
    r"(?:(?:hent|vis|les|gi\s+meg|skriv(?:\s+ut)?)\s+)?"
    r"(?:ut\s+)?(?:strek[\s-]?kode\w*|bar[\s-]?kode\w*|barcode\w*"
    r"|qr[\s-]?kode\w*|qr\b|kode\w*)"
    r"(?:[^?]{0,40})?\W*\??\W*$", re.IGNORECASE)


def er_strekkodesporsmal(sporsmal: str) -> bool:
    """Ber spørsmålet om strekkode-/QR-verdien?

    Målt: «hva er strekkoden?» ga «Finnes ikke i dokumentet» selv om
    verdien lå ferdig dekodet i samme svar og var lagt inn i modellens
    kontekst. Samme feilmodus som sidetelling — vi ba en 4B-modell
    gjengi et tall den ikke trengte å tolke."""
    return bool(_STREKKODE_SPM.match(sporsmal or ""))


def _strekkodesvar(strekkoder: list, sideref=None, strekkoder_lest=True):
    """Deterministisk svar på et strekkodespørsmål, eller None hvis
    spørsmålet ikke kan besvares fra listen alene.

    «strekkoder_lest=False» (klienten sendte strekkoder=nei) gir None:
    en tom liste betyr da at vi ikke SÅ etter, ikke at det ikke finnes
    noe — og «ingen funnet» ville vært en løgn."""
    if not strekkoder_lest:
        return None
    aktuelle = strekkoder
    if sideref is not None:
        aktuelle = [k for k in strekkoder if k.get("side") == sideref]
    if not aktuelle:
        hvor = f" på side {sideref}" if sideref is not None else ""
        if strekkoder and sideref is not None:
            sider = ", ".join(str(k.get("side")) for k in strekkoder)
            return (f"Ingen strekkode{hvor}. Dokumentet har strekkode på "
                    f"side {sider}.")
        return f"Ingen strekkoder eller QR-koder funnet i dokumentet{hvor}."
    return "\n".join(
        f"{k.get('type', 'ukjent')} (side {k.get('side')}): {k.get('verdi')}"
        for k in aktuelle)


# Spørsmål som ber om en SJEKKSUMVALIDERT identifikator. Disse finnes
# allerede bevist i uttrekket (mod11/Luhn/format) — å la en 4B-modell
# gjengi sifrene er å bytte matematikk mot sannsynlighet. Modellen
# velger dessuten ÉN verdi; bunken har to fødselsnumre og to
# kontonumre, og koden svarer med begge.
_IDENT_ORD = [
    ("fodselsnummer", r"f(?:ø|oe?)dsels[\s-]?nummer\w*|fnr\b|"
                      r"person[\s-]?nummer\w*|d-?nummer\w*"),
    ("kontonummer", r"konto[\s-]?(?:nummer|nr)\w*|kontoen\b|konto\b"),
    ("organisasjonsnummer", r"organisasjons[\s-]?nummer\w*|org\.?[\s-]?nr\w*|"
                            r"orgnummer\w*"),
    ("kid", r"kid[\s-]?(?:nummer|nr)\w*|kid\b"),
    ("telefon", r"telefon\w*|tlf\b|mobil\w*"),
    ("epost", r"e-?post\w*|e-?mail\w*|epostadresse\w*"),
]
_IDENT_SPM = [
    (felt, re.compile(
        r"^\W*(?:(?:hva|hvilken|hvilke|hvor)\s+(?:er|st(?:å|aa)r)?\s*)?"
        r"(?:(?:hent|vis|les|finn|gi\s+meg|skriv(?:\s+ut)?)\s+)?"
        r"(?:ut\s+)?(?:\w+s\s+)?(?:" + monster + r")"
        r"(?:[^?]{0,40})?\W*\??\W*$", re.IGNORECASE))
    for felt, monster in _IDENT_ORD
]


def identsporsmalets_felt(sporsmal: str):
    """Hvilken sjekksumvalidert identifikator spør spørsmålet om?
    None hvis det ikke er et rent identifikatorspørsmål."""
    for felt, monster in _IDENT_SPM:
        if monster.match(sporsmal or ""):
            return felt
    return None


# Finnerne som svarer på hvert identifikatorspørsmål — de SAMME som
# /sladd og koordinatene bruker, så svarene aldri kan sprike.
_IDENT_FINNERE = {
    "fodselsnummer": (finn_alle_fodselsnummer, "fødselsnummer"),
    "kontonummer": (finn_alle_kontonummer, "kontonummer"),
    "organisasjonsnummer": (finn_alle_organisasjonsnummer,
                            "organisasjonsnummer"),
    "kid": (finn_alle_kid, "KID-nummer"),
    "telefon": (finn_alle_telefoner, "telefonnummer"),
    "epost": (finn_alle_eposter, "e-postadresse"),
}


def _identsvar(tekst: str, felt: str):
    """Deterministisk svar på et identifikatorspørsmål."""
    finner, navn = _IDENT_FINNERE[felt]
    funn = finner(tekst or "")
    if not funn:
        return (f"Fant ingen {navn} i dokumentet. (Et nummer som ikke "
                "består kontrollsifferet utelates med vilje — det er "
                "trolig feillest.)")
    if len(funn) == 1:
        return funn[0]
    return f"{len(funn)} {navn}: " + ", ".join(funn)


def kan_svares_uten_modell(sporsmal: str) -> bool:
    """Spørsmål koden kan besvare alene — de skal forbi Borealis-portene
    så en nede modell ikke feller noe vi kan svare på deterministisk."""
    return (er_ren_sidelesing(sporsmal) or er_strekkodesporsmal(sporsmal)
            or identsporsmalets_felt(sporsmal) is not None)


def svar_paa_sporsmal(raa_tekst: str, sporsmal: str, ocr_brukt: bool,
                      handskrift: list, strekkoder: list,
                      strekkoder_lest: bool = True) -> dict:
    """Felles kjerne for /spor og /dokument: beriker dokumentteksten
    (håndskriftmerking, strekkoder, stort-dokument-supplement,
    datoklassifisering), spør Borealis og kjører ALLE vaktene
    (tastefeilrunde, eksklusjonsvakt, tallvakt). Returnerer
    {"tom": True} når dokumentet mangler lesbar tekst, ellers
    {"tom": False, "svar", "tall_verifisert", "tolket_sporsmal",
     "svar_avkortet", "advarsler"}."""
    advarsler = []

    # --- deterministisk siderouting -----------------------------------
    # Målt: modellen fikk hele bunken (7 335 tegn — godt under grensen,
    # med «[Side 10 av 10]» i klartekst) og svarte likevel «Side 10
    # finnes ikke» på «les side 10». Sideindeksering er nettopp den
    # typen jobb en liten modell roter bort og koden gjør perfekt —
    # markørene er kodegenererte. Ren lesing besvares ordrett uten
    # modell; spørsmål OM en side gir modellen KUN den siden.
    sideref = _sporsmalets_sideref(sporsmal)

    # Strekkode-/QR-verdien er DEKODET av en leser, ikke lest av en
    # modell — svar rett fra listen. (Ligger før sideroutingen, så
    # «strekkoden på side 3» filtreres på side i stedet for å bli et
    # sideutsnitt.)
    if er_strekkodesporsmal(sporsmal):
        svar = _strekkodesvar(strekkoder or [], sideref,
                              strekkoder_lest)
        if svar is not None:
            return {"tom": False, "modell_brukt": False, "svar": svar,
                    "tall_verifisert": True,
                    "tolket_sporsmal": ("strekkodeverdien gjengitt fra "
                                        "dekoderen (deterministisk)"),
                    "svar_avkortet": False, "advarsler": advarsler}

    if sideref is not None and len((raa_tekst or "").strip()) >= 5:
        antall_sider, sider = del_i_sider(raa_tekst)
        if sideref not in sider:
            return {"tom": False, "modell_brukt": False,
                    "svar": (f"Dokumentet har {antall_sider} "
                             + ("side" if antall_sider == 1 else "sider")
                             + f" — side {sideref} finnes ikke."),
                    "tall_verifisert": True,
                    "tolket_sporsmal": ("sidetallet sjekket deterministisk "
                                        "mot sidemarkørene"),
                    "svar_avkortet": False, "advarsler": advarsler}
        if er_ren_sidelesing(sporsmal):
            return {"tom": False, "modell_brukt": False,
                    "svar": sider[sideref] or "(siden er tom)",
                    "tall_verifisert": True,
                    "tolket_sporsmal": (f"side {sideref} gjengitt ordrett "
                                        "(deterministisk, uten modell)"),
                    "svar_avkortet": False, "advarsler": advarsler}
        # Spørsmål OM en bestemt side → svaret hentes fra kun den siden
        raa_tekst = f"[Side {sideref} av {antall_sider}]\n{sider[sideref]}"
        advarsler.append(
            f"Spørsmålet peker på side {sideref} — svaret er hentet fra "
            "kun den siden (deterministisk utsnitt)")

    # Sjekksumvaliderte identifikatorer svares fra uttrekket, ikke av
    # modellen. Ligger ETTER sideroutingen, så «kontonummeret på side 2»
    # søker i riktig side. Finner koden ingenting, er det fordi
    # kontrollsifferet ikke stemmer — og da skal vi si det, ikke la
    # modellen gjette et tall som ser riktig ut.
    ident_felt = identsporsmalets_felt(sporsmal)
    if ident_felt and len((raa_tekst or "").strip()) >= 5:
        return {"tom": False, "modell_brukt": False,
                "svar": _identsvar(raa_tekst, ident_felt),
                "tall_verifisert": True,
                "tolket_sporsmal": (f"{ident_felt} hentet fra det "
                                    "sjekksumvaliderte uttrekket "
                                    "(deterministisk)"),
                "svar_avkortet": False, "advarsler": advarsler}

    tekst = raa_tekst
    # Merk håndskriftregioner så Borealis kan skille dem fra trykt
    # tekst («hvilket navn står med håndskrift?» blir svarbart)
    if handskrift:
        tekst += ("\n\nFølgende tekstbiter i dokumentet er HÅNDSKREVET "
                  "(alt annet er trykt):\n"
                  + "\n".join(f"- {t}" for t in handskrift))

    if len(tekst.strip()) < 5 and not strekkoder:
        return {"tom": True}

    # Strekkoder/QR legges inn i dokumentteksten så Borealis kan
    # svare på f.eks. «hva er dokumentnummeret?»
    if strekkoder:
        kodelinjer = "\n".join(
            f"- {k['type']} (side {k['side']}): {k['verdi']}" for k in strekkoder
        )
        tekst = ((tekst.strip() or "Dokumentet har ingen lesbar tekst.")
                 + "\n\nStrekkoder/QR-koder funnet i dokumentet:\n" + kodelinjer)

    # Store dokumenter: LLM-en leser bare begynnelsen — suppler med
    # deterministisk uttrekk fra HELE teksten, og si det ærlig i svaret
    if len(tekst) > MAKS_LLM_TEGN:
        datoer_hele = finn_alle_datoer(raa_tekst, maks=60)
        felter_hele = utvid_entiteter(raa_tekst, {})
        tekst = (
            tekst[:MAKS_LLM_TEGN]
            + f"\n\n[MERK: Dokumentet fortsetter — totalt {len(raa_tekst)} tegn. "
            + "Deterministisk uttrekk fra HELE dokumentet:\n"
            + "Alle datoer: "
            + (", ".join(datoer_hele) if datoer_hele else "ingen funnet")
            + "\nFelter: " + json.dumps(felter_hele, ensure_ascii=False) + "]"
        )
        advarsler.append(
            f"Stort dokument ({len(raa_tekst)} tegn): modellen leste de første "
            f"{MAKS_LLM_TEGN} tegnene direkte, pluss deterministisk uttrekk "
            "(alle datoer + felter) fra hele dokumentet."
        )
    # R40-klassifiseringen legges ALLTID ved som kontekst når
    # dokumentet inneholder datoer — generelt, uten skjøre
    # nøkkelordbetingelser (spørsmål kan inneholde skrivefeil)
    # Dokumentdatoen må regnes ut av HELE datolista, ikke av de 30 første.
    # Med maks=30 fikk modellen en annen dato enn dokumentprofilen meldte
    # — målt 01.02.2020 i prompten mot 28.05.2026 i profilen på samme
    # bunke, mens prompten under sier «besvares med NØYAKTIG denne
    # datoen». Grensen hører til hvor mange datoer som LISTES for
    # modellen, ikke til hvilken dato som ER dokumentets.
    klassifisert = sett_dato_roller(klassifiser_datoer(raa_tekst))
    if klassifisert:
        # DOKUMENTETS EGEN DATO skilles ut i sitt eget avsnitt. Uten dette
        # svarte modellen «01.07.2026» på «når er brevet fra?» fordi det
        # var fristen som tilfeldigvis sto nærmest — den kan ikke vite at
        # en frist er noe dokumentet HANDLER OM, ikke dokumentets dato.
        dd = finn_dokumentdato(klassifisert, ocr_brukt=ocr_brukt)
        if dd.get("dato"):
            tekst += (
                "\n\n[DOKUMENTETS EGEN DATO (da dokumentet ble skrevet/"
                f"utstedt/fattet): {dd['dato']}"
                + (f" — {dd['type']}, {dd['begrunnelse']}" if dd.get("type") else "")
                + f" (sikkerhet: {dd['konfidens']})."
                + (f" MERK: {dd['advarsel']}." if dd.get("advarsel") else "")
                + " Spørsmål om NÅR DOKUMENTET ER FRA — «datert», «skrevet»,"
                  " «utstedt», «hvilken dato er brevet» — besvares med"
                  " NØYAKTIG denne datoen.]")
        per = dd.get("periode")
        if per and per.get("flere_dokumenter"):
            # Bunke: «dokumentets dato» er et SPENN. Uten dette svarte
            # modellen med datoen på side 1 som om den gjaldt hele filen.
            sider = "; ".join(
                f"side {s['side']}: {s['dato']}" for s in per["per_side"])
            tekst += (
                f"\n\n[FILEN INNEHOLDER FLERE DATERTE DOKUMENTER. "
                f"DOKUMENTENES DATOSPENN: FRA {per['fra']} TIL {per['til']}. "
                f"Datert dokument per side — {sider}.\n"
                f"ALLE disse spørsmålene besvares med «fra {per['fra']} til "
                f"{per['til']}»: «fra hvilken dato til hvilken dato er "
                f"dokumentene», «hvilken periode dekker filen», «hvor gamle "
                f"er dokumentene», «hvilket tidsrom».\n"
                f"ADVARSEL: perioder som står i INNHOLDET (ytelsesperioder, "
                f"ansettelsesperioder, «for perioden … til …») er IKKE "
                f"dokumentenes datospenn — de hører til det dokumentene "
                f"HANDLER OM. Bruk KUN {per['fra']}–{per['til']} når "
                f"spørsmålet gjelder DOKUMENTENE eller FILEN.]")
        else:
            tekst += ("\n\n[DOKUMENTETS EGEN DATO: ikke funnet. Ingen av "
                      "datoene under kan knyttes til dokumentet selv — de "
                      "hører til innholdet. Spørres det om når dokumentet "
                      "er fra, SI at det ikke står i dokumentet; ikke velg "
                      "en dato fra listen under.]")

        # Selve LISTA holdes kort av hensyn til kontekstvinduet — men
        # dokumentdatoen over er regnet ut av HELE lista, ikke av utsnittet.
        # Det var sammenblandingen av de to som gjorde at modellen fikk en
        # annen dato enn profilen meldte.
        etter_rolle = {}
        for d in klassifisert[:MAKS_DATOER_I_PROMPT]:
            if d["dato"] == dd.get("dato") and d.get("rolle") == "dokument":
                continue          # allerede oppgitt som dokumentdato over
            etter_rolle.setdefault(d.get("rolle") or "ukjent", []).append(d)

        overskrifter = {
            "innhold": "Datoer i INNHOLDET (noe dokumentet handler om — "
                       "IKKE dokumentets egen dato)",
            "behandling": "Datoer om HÅNDTERINGEN av dokumentet (mottatt/"
                          "arkivert — ikke dokumentets egen dato)",
            "dokument": "Andre kandidater til dokumentdato (svakere bevis)",
            "ukjent": "Datoer uten tydelig rolle — vær forsiktig",
        }
        for rolle in ("innhold", "behandling", "dokument", "ukjent"):
            gruppe = etter_rolle.get(rolle)
            if not gruppe:
                continue
            linjer = "\n".join(
                f"- {d['dato']}"
                + (f" (side {d['side']})" if d["side"] else "")
                + f": {d['type']} — {d['begrunnelse']}"
                for d in gruppe)
            tekst += f"\n\n[{overskrifter[rolle]}:]\n" + linjer

    svar, svar_avkortet = spor_borealis(tekst, sporsmal, fra_ocr=ocr_brukt)

    # R41 (kode): «Finnes ikke»-svar kan skyldes skrivefeil i selve
    # SPØRSMÅLET. Da normaliseres spørsmålet til korrekt norsk og
    # prøves én gang til — og svaret deklarerer tolkningen ærlig.
    tolket_sporsmal = None
    if svar.strip().lower().startswith("finnes ikke") and len(sporsmal) <= 200:
        normalisert, _ = _borealis_generer(
            prompter.hent("spor.normaliser_sporsmal", sporsmal=sporsmal), 64)
        normalisert = normalisert.strip().strip('"«»')
        if normalisert and normalisert.lower() != sporsmal.strip().lower():
            svar2, avkortet2 = spor_borealis(tekst, normalisert, fra_ocr=ocr_brukt)
            if not svar2.strip().lower().startswith("finnes ikke"):
                svar, svar_avkortet = svar2, avkortet2
                tolket_sporsmal = normalisert

    # R48: «uten X»-begrensninger i spørsmålet håndheves — én streng
    # ny runde ved brudd, deretter ærlig varsling
    brutt = eksklusjoner_brutt(sporsmal, svar)
    if brutt:
        svar2, avkortet2 = spor_borealis(
            tekst,
            sporsmal + " (VIKTIG: svaret skal IKKE inneholde "
            + ", ".join(brutt) + " — utelat dette helt)",
            fra_ocr=ocr_brukt)
        if not eksklusjoner_brutt(sporsmal, svar2):
            svar, svar_avkortet, brutt = svar2, avkortet2, []
    if brutt:
        advarsler.append(
            "Spørsmålet ba om svar uten " + ", ".join(brutt)
            + ", men modellen tok det likevel med — kontroller svaret")

    # Tallvakt: inneholder svaret tall som ikke står i dokumentet,
    # prøves én streng ny runde — hjelper ikke det, flagges svaret
    mangler = uverifiserte_tall(svar, tekst)
    if mangler:
        svar2, avkortet2 = spor_borealis(
            tekst,
            sporsmal + " (VIKTIG: gjengi tallet NØYAKTIG slik det står "
                       "i dokumentet — ikke regn eller summer)",
            fra_ocr=ocr_brukt)
        if not uverifiserte_tall(svar2, tekst):
            svar, mangler, svar_avkortet = svar2, [], avkortet2
    tall_verifisert = not mangler
    if mangler:
        advarsler.append(
            "Svaret inneholder tall som ikke står ordrett i dokumentet ("
            + ", ".join(mangler)
            + ") — sannsynligvis utregnet av modellen. Kontroller mot kilden.")
    if svar_avkortet:
        advarsler.append(
            f"Svaret nådde maksimal lengde ({MAKS_SVAR_TOKENS} tokens) og "
            "kan være avkortet — hele dokumentteksten finnes alltid "
            "uavkortet i /analyser-feltet 'tekst'.")
    return {"tom": False, "modell_brukt": True,
            "svar": svar, "tall_verifisert": tall_verifisert,
            "tolket_sporsmal": tolket_sporsmal,
            "svar_avkortet": svar_avkortet, "advarsler": advarsler}


# ==================================================================== #
#  Operasjonsmotor — ETT dokument, mange operasjoner                    #
# ==================================================================== #
#  Dokumentet leses ÉN gang inn i en DokumentKontekst; deretter kjøres  #
#  operasjonene (felter/skjema/svar/…) mot samme kontekst. De           #
#  deterministiske avledningene beregnes dovent og caches, så to        #
#  operasjoner som begge trenger «felter» aldri regner dem to ganger.   #
#  Både /dokument-bryterne OG det nye operasjoner-kontraktet bygger på   #
#  denne motoren — én kjerne, flere fasader.                            #


class DokumentKontekst:
    """Dokumentet lest én gang. Avledede deler (felter, datoer, struktur)
    beregnes først når en operasjon ber om dem, og gjenbrukes så av
    resten — les-en-gang, regn-en-gang."""

    def __init__(self, tekst, ocr_brukt=False, handskrift=None,
                 strekkoder=None, ocr_motorer=None, fra_cache=False,
                 sider_regioner=None, antall_sider=None,
                 strekkoder_lest=True, filnavn=None, ferdig=None):
        self.tekst = tekst or ""
        self.filnavn = filnavn
        self.ocr_brukt = ocr_brukt
        self.handskrift = handskrift or []
        self.strekkoder = strekkoder or []
        self.ocr_motorer = ocr_motorer
        self.fra_cache = fra_cache
        # Det FAKTISKE sideantallet i fila — ikke antall sider med tekst.
        # En tom side er fortsatt en side, og en klient som teller sider
        # for å sjekke at hele bunken kom fram, trenger det tallet.
        self.antall_sider = antall_sider
        # Ble strekkode-/QR-skanningen faktisk kjørt? «Ingen koder funnet»
        # og «det ble ikke sett etter koder» er to ulike svar.
        self.strekkoder_lest = strekkoder_lest
        # OCR-regionene ({boks, tekst}) per side — koordinatgrunnlaget.
        # Tom for tekstlags-PDF-er (der bygges ordregister fra fitz i
        # stedet) og for rene tekstopplastinger (ingen sider finnes).
        self.sider_regioner = sider_regioner or []
        self._struktur = None
        self._profil = None
        # Deler analysen alt har regnet ut. De ER dovent-cachen, bare
        # fylt på forhånd — og de er BEDRE enn det konteksten selv kan
        # regne ut, fordi analysen så PDF-metadata og håndskriftmerking
        # som ikke overlever i ren tekst.
        ferdig = ferdig or {}
        self._felter = ferdig.get("felter")
        self._datoer = ferdig.get("datoer")
        self._datoer_detaljert = ferdig.get("datoer_detaljert")
        self._dokumentdato = ferdig.get("dokumentdato")

    # -- doven caching av de deterministiske delene --
    @property
    def felter(self):
        if self._felter is None:
            self._felter = utvid_entiteter(self.tekst, {})
        return self._felter

    @property
    def datoer(self):
        if self._datoer is None:
            self._datoer = finn_alle_datoer(self.tekst)
        return self._datoer

    @property
    def datoer_detaljert(self):
        if self._datoer_detaljert is None:
            self._datoer_detaljert = sett_dato_roller(
                klassifiser_datoer(self.tekst))
        return self._datoer_detaljert

    @property
    def dokumentdato(self):
        if self._dokumentdato is None:
            self._dokumentdato = dokumentdato_av(self.tekst, self.ocr_brukt)
        return self._dokumentdato

    @property
    def struktur(self):
        if self._struktur is None:
            self._struktur = strukturert_uttrekk(self.tekst)
        return self._struktur

    @property
    def profil(self):
        """De obligatoriske metadataene (R79). Bygges av allerede
        utregnede deler, så den koster ingen ny lesing av dokumentet."""
        if self._profil is None:
            self._profil = bygg_profil(
                self.tekst,
                filnavn=self.filnavn,
                antall_sider=self.antall_sider,
                strekkoder=self.strekkoder,
                strekkoder_lest=self.strekkoder_lest,
                datoer_detaljert=self.datoer_detaljert,
                dokumentdato=self.dokumentdato,
                struktur=self.struktur,
                handskrift=self.handskrift,
                # Håndskrift oppdages BARE på OCR-veien. Uten OCR er
                # svaret «vet ikke», ikke «ingen håndskrift».
                handskrift_lest=self.ocr_brukt)
        return self._profil

    def er_tom(self):
        """Blankt ark: modelldelene skal ikke kjøre mot ingenting."""
        return len(self.tekst.strip()) < 5 and not self.strekkoder


# Advarsler er i dag frie strenger som klienter må søke i tekst for å
# tolke. Her får de en maskinlesbar type ved siden av. Mønstrene er
# konservative: treffer ingen, blir typen «annet» — og strengen er
# uansett med, så ingenting går tapt.
_VARSELTYPER = (
    (re.compile(r"(?i)ukjent(e)? felt"), "ukjent-felt", "advarsel"),
    (re.compile(r"(?i)\(nesten\) tom|tom side"), "tom-side", "info"),
    (re.compile(r"(?i)borealis|modellen er ikke"), "modell-utilgjengelig", "feil"),
    (re.compile(r"(?i)avkortet|maksimal svarlengde"), "avkortet", "advarsel"),
    (re.compile(r"(?i)tall_verifisert|ikke finnes i dokumentet"), "tall-uverifisert", "advarsel"),
    (re.compile(r"(?i)h[åa]ndskrevet|bildekvalitet|utbrent"), "lesekvalitet", "advarsel"),
    (re.compile(r"(?i)hoppet over|utelatt|budsjettet"), "utelatt", "advarsel"),
    (re.compile(r"(?i)strekkode|qr"), "koder", "info"),
    (re.compile(r"(?i)uenige om"), "uenighet", "advarsel"),
)


def _uenighet_med_modellen(profil, deler) -> list:
    """Advarer når modellen og det DETERMINISTISKE uttrekket sier ulike
    ting om samme faktum.

    Revisjonen fant at de tre veiene til et fødselsnummer eller navn
    (`part`, `svar.svar`, `skjema.skjema`) faktisk VAR uenige i et ekte
    svar: «NOR-ETTERNAVN, OLA» mot «Ola Nordmann». Konklusjonen var å
    beholde alle tre — de har ulik garanti, og en sammenslåing ville
    slettet nettopp signalet.

    Men signalet ble aldri MELDT. En klient måtte sammenligne selv, og
    gjorde det ikke. Her er det deterministiske fasit: står det et
    bevist fødselsnummer i profilen og modellen skrev et annet, er det
    modellen som tar feil."""
    skjema = (deler or {}).get("skjema")
    if not isinstance(skjema, dict) or not isinstance(skjema.get("skjema"), dict):
        return []
    fylt = skjema["skjema"]
    kilde = skjema.get("kilde_per_felt") or {}
    part = (profil or {}).get("part") or {}

    ut = []
    for felt, bevist in (("fnr", part.get("fnr")),
                         ("fodselsnummer", part.get("fnr")),
                         ("navn", part.get("navn"))):
        modellens = fylt.get(felt)
        if not bevist or not modellens or kilde.get(felt) != "modell":
            continue
        if str(modellens).strip() != str(bevist).strip():
            # VERDIENE SITERES IKKE. Advarselen havner i «varsler» og i
            # «kvalitet.advarsler», og ingen av dem berøres av
            # personvernbryteren — så et fødselsnummer sitert her ville
            # nådd fram i et svar klienten uttrykkelig ba om UTEN
            # persondata. Klienten har begge verdiene i svaret alt
            # (`part.{felt}` og `skjema.skjema.{felt}`); den trenger å
            # vite AT de er uenige, ikke å få dem gjentatt.
            ut.append(
                f"Modellen og uttrekket er uenige om «{felt}». Sammenlign "
                f"dokumentprofil.part.{felt} mot skjema.skjema.{felt}. "
                f"Uttrekket er bevist (etikett/mod11); modellens verdi er "
                f"ikke, så uttrekket gjelder.")
    return ut


# Feltene i «felter.felter» som ER persondata. Under profil=sammendrag
# settes de til null — nøkkelen blir stående, så formen er uendret
# (R118), men verdien når ikke fram.
_PERSONFELT_I_FELTER = (
    "fodselsnummer", "navn", "telefon", "epost", "kontonummer", "kid",
    "organisasjonsnummer", "postnummer", "poststed", "adresse",
    "arbeidsgiver",
)


def _sammendragsform(svar: dict) -> dict:
    """Personvernbryteren for HELE svaret, ikke bare dokumentprofilen.

    `_profilform` renset `dokumentprofil` — og bare den. Målt på det
    ekte svaret nådde fødselsnummeret likevel fram to andre veier, begge
    PÅ som standard:

        /felter/felter/fodselsnummer   verdien, i klartekst
        /tekst                          hele dokumentet

    En klient som fulgte dokumentasjonen trodde den ikke mottok
    persondata, og gjorde det. Bryteren dekket en tredjedel av svaret.

    RÅTEKST FJERNES, DEN SLADDES IKKE. `sladd_tekst` dekker bare det den
    kan BEVISE — fødselsnummer, konto, KID, telefon, e-post — og sier
    selv at navn og adresser ikke dekkes. Å levere «sladdet» tekst som
    fortsatt bærer navn og adresse ville byttet ett falskt løfte mot et
    svakere. Feltene settes derfor til null, og navngis i «utelatt».

    Formen står stille: ingen nøkkel fjernes, bare verdier nulles."""
    if not isinstance(svar, dict):
        return svar
    fjernet = []

    if svar.get("tekst") is not None:
        svar["tekst"] = None
        fjernet.append("tekst")

    # «struktur» er en PARALLELL utvinning av de samme identifikatorene
    # — kontakt.telefoner, identifikatorer.fodselsnummer, adresser. Den
    # ble oppdaget som lekkasjekanal av testen som bygger hele svaret,
    # ikke av lesing: den er AV som standard, så den var lett å overse.
    # Hele blokka fjernes; den bærer ingenting profilen ikke har.
    if svar.get("struktur") is not None:
        svar["struktur"] = None
        fjernet.append("struktur")

    felter = svar.get("felter")
    if isinstance(felter, dict):
        flate = felter.get("felter")
        if isinstance(flate, dict):
            for navn in _PERSONFELT_I_FELTER:
                if flate.get(navn) is not None:
                    flate[navn] = None
                    fjernet.append(f"felter.felter.{navn}")

        datoer = felter.get("datoer_detaljert")
        if isinstance(datoer, list):
            # «kontekst» er et råtekstvindu rundt hver dato — målt til 84
            # tegn, og et fødselsnummer får plass i det. Det overlever
            # selv «tekst=nei», fordi det ligger i en annen blokk.
            for d in datoer:
                if isinstance(d, dict) and d.get("kontekst") is not None:
                    d["kontekst"] = None
                    if "felter.datoer_detaljert[].kontekst" not in fjernet:
                        fjernet.append("felter.datoer_detaljert[].kontekst")
            # Fødselsdatoen utledet av fødselsnummeret er persondata, og
            # oppføringen bekrefter i tillegg at et mod11-GYLDIG nummer
            # står i dokumentet. Samme klasse som opphav-pekerne R89
            # fjernet: den lekker eksistensen bryteren skulle skjule.
            for_e = len(datoer)
            felter["datoer_detaljert"] = [
                d for d in datoer
                if not (isinstance(d, dict)
                        and d.get("type") == "fodselsdato_fra_fnr")]
            if len(felter["datoer_detaljert"]) != for_e:
                fjernet.append("felter.datoer_detaljert[fodselsdato_fra_fnr]")

    # «utelatt» er løftet om at ingenting forsvinner i stillhet (R65).
    # Den bor i profilen, der _profilform alt har fylt seksjonsnavnene.
    profil = svar.get("dokumentprofil")
    if isinstance(profil, dict) and fjernet:
        profil["utelatt"] = sorted(set(profil.get("utelatt") or []) | set(fjernet))
    return svar


# Verdirommet for ALLE ja/nei-brytere. Sto tidligere som lokale
# variabler inne i _dokument_samlet, så to brytere utenfor den hadde
# hver sin ufullstendige liste — og tolket samme forespørsel motsatt:
#
#     struktur=off   → AV      (gikk gjennom paa())
#     strekkoder=off → PÅ      (egen liste uten «off»/«no»)
#     strekkoder=tull → PÅ, uten 400 — mens struktur=tull ga 400
#
# Én liste, ett sted, og alle brytere leser den.
BRYTER_JA = ("ja", "1", "true", "on", "yes", "pa", "på")
BRYTER_NEI = ("nei", "0", "false", "av", "off", "no")


def bryterverdi(raa, standard: bool):
    """Tolker én bryterverdi. Returnerer (verdi, ukjent).

    `ukjent` er True når klienten sendte noe vi ikke kjenner — da skal
    kalleren svare 400 i stedet for å tolke det som «nei». En bryter
    som stille faller tilbake til standarden er den feilmodusen R63 og
    feltnavnvakten ellers vokter mot: klienten tror den ba om noe."""
    v = (raa or "").strip().lower()
    if not v:
        return standard, False
    if v in BRYTER_JA:
        return True, False
    if v in BRYTER_NEI:
        return False, False
    return standard, True


def _spor_svar(**felt) -> dict:
    """Bygger ETT svar fra POST /spor, med samme nøkkelsett hver gang.

    Ruten hadde fire 200-veier med hvert sitt sett. Bare `ok` og `svar`
    var med i alle; 22 av 24 nøkler kom og gikk. Verst var det tomme
    dokumentet: 8 nøkler, uten `versjon` — og R39 sier uttrykkelig at
    HVERT /spor-svar bærer `versjon`.

    En robot leser `svar["tall_verifisert"]` uten å sjekke om stien
    finnes. Den virket på hvert dokument med lesbar tekst og krasjet på
    den første blanke siden i bunken.

    Skjelettet er fasit: alle nøkler, med null der noe ikke gjelder.
    Kalleren overstyrer bare det den faktisk vet.

    `modus` er ny og sier HVILKEN vei som svarte. Uten den måtte en
    klient gjette ut fra hvilke felt som var fylt — altså gjøre den
    formsniffingen kontrakten skal gjøre unødvendig."""
    skjelett = {
        "ok": True,
        "modus": None,
        "filnavn": None,
        "sporsmal": None,
        "svar": None,
        "melding": None,
        "uten_dokument": False,
        "trenger_ocr": False,
        "ocr_brukt": False,
        "ocr_motorer": None,
        "strekkoder": None,
        "handskrift": None,
        "korrigert_tekst": None,
        "tall_verifisert": None,
        "tolket_sporsmal": None,
        "svar_avkortet": None,
        "advarsel": None,
        "fra_cache": False,
        "tid_sekunder": None,
        "kilde": None,
        # ALLTID med, og alltid med samme undernøkler (R39). To av de
        # gamle veiene bygget den uten «modell».
        "versjon": {"api": API_VERSJON, "prompt": prompter.versjon(),
                    "modell": _borealis["modellfil"] or _borealis["motor"] or None},
    }
    ukjente = set(felt) - set(skjelett)
    if ukjente:                      # fanges av vakttesten, ikke i drift
        raise KeyError(f"_spor_svar fikk ukjente felt: {sorted(ukjente)}")
    skjelett.update(felt)
    return skjelett


def _sammendragsform_operasjoner(svar: dict) -> dict:
    """Samme rensing for operasjonsveien, der nyttelasten ligger i
    `resultater[].data` i stedet for i `felter`.

    R90 slo fast at personvernbryteren må virke i BEGGE kontraktene.
    Uten dette ville en klient som byttet fra brytere til «operasjoner»
    mistet vernet uten å bli fortalt det — og operasjonen `felter`
    leverer nøyaktig de samme identifikatorene."""
    if not isinstance(svar, dict):
        return svar
    for res in svar.get("resultater") or []:
        if not isinstance(res, dict):
            continue
        data = res.get("data")
        if res.get("type") == "tekst" and data:
            res["data"] = None
        elif isinstance(data, dict):
            # Operasjonen «felter» har samme form som blokka «felter» på
            # bryterveien, så den gjenbruker rensingen der.
            _sammendragsform({"felter": data})
    return svar


def _profilform(profil: dict, form: str) -> dict:
    """Full profil, eller bare sammendraget.

    `profil=sammendrag` finnes for personvern, ikke for størrelse: en
    klient som bare spør «hvilken dato er dette brevet fra» skal kunne
    la være å motta fødselsnummer, adresse, telefon, inntekt og
    kontonummer. Standard er `full` — R79 er urørt for alle som ikke ber
    om noe annet.

    `utelatt` navngir hva som er borte, så ingenting forsvinner i
    stillhet (samme løfte som R65 gir for ukjente feltnavn)."""
    # Interne arbeidsfelt (understrek) ut av svaret. De finnes for at
    # «opphav» skal slippe å lete opp noe uttrekket allerede vet — se
    # part._posisjon — og de er ikke en del av kontrakten. Fjernes i en
    # KOPI: originalen står igjen i DokumentKontekst, som «opphav»
    # leser etterpå. Muterte vi, ville sidetallet blitt borte igjen.
    def _uten_interne(node):
        if isinstance(node, dict):
            return {n: _uten_interne(v) for n, v in node.items()
                    if not n.startswith("_")}
        if isinstance(node, list):
            return [_uten_interne(v) for v in node]
        return node

    if not isinstance(profil, dict):
        return profil
    profil = _uten_interne(profil)
    if form != "sammendrag":
        return profil
    # Hva som beholdes — og hvorfor — står ved _PROFIL_SAMMENDRAG_BEHOLD.
    liten = {k: v for k, v in profil.items()
             if k in _PROFIL_SAMMENDRAG_BEHOLD}
    # sammendraget bærer navn og fnr — også de ut når formålet er å
    # slippe å motta persondata
    if isinstance(liten.get("sammendrag"), dict):
        liten["sammendrag"] = {k: v for k, v in liten["sammendrag"].items()
                               if k not in ("navn", "fnr")}
    liten["utelatt"] = sorted(set(profil) - set(_PROFIL_SAMMENDRAG_BEHOLD))
    return liten


def _varsler(advarsler) -> list:
    """Gjør advarselstrengene om til objekter med type og alvorsgrad.

    Strengene beholdes uendret i `kvalitet.advarsler` — dette kommer i
    tillegg, så en klient kan bytte over i sitt eget tempo. Uten det
    må den skille «ukjent felt» fra «tom side» fra «modellen er nede»
    med tekstsøk."""
    ut = []
    for melding in advarsler or []:
        melding = str(melding)
        slag, alvor = "annet", "advarsel"
        for monster, s, a in _VARSELTYPER:
            if monster.search(melding):
                slag, alvor = s, a
                break
        ut.append({"type": f"{PROBLEM_BASIS}/{slag}", "kode": slag,
                   "alvor": alvor, "detalj": melding})
    return ut


def _samlet_status(deler: dict, advarsler) -> str:
    """«ok» | «delvis» | «feil» for hele svaret.

    I dag er toppnivå-`ok` alltid true når forespørselen kom fram, selv
    om en del feilet — klienten må gå gjennom hele deltreet for å
    oppdage det. Dette svarer på spørsmålet direkte."""
    deler_med_svar = [d for d in deler.values() if isinstance(d, dict)]
    feilet = [d for d in deler_med_svar if d.get("ok") is False]
    if not feilet:
        return "ok"
    if len(feilet) == len(deler_med_svar):
        return "feil"
    return "delvis"


def _delen_brukte_modellen(del_) -> bool:
    """Kjørte modellen for DENNE delen?

    En del som FEILET er `{ok: False, feil: …}` og har ingen
    «modell_brukt». Den gamle regelen spurte `.get("modell_brukt") is
    False` — på en feilet del gir `.get()` None, og `None is False` er
    falskt, så delen ble talt som «modellen kjørte». Resultatet var at
    `/dokument` meldte `kilde: "borealis+deterministisk"` på et kall der
    Borealis var NEDE og aldri ble spurt. Nettopp det feltet er
    dokumentert som robotens raskeste ærlighetssjekk."""
    if not isinstance(del_, dict):
        return False
    if del_.get("ok") is False:
        return False            # delen feilet — ingen modell kjørte
    return del_.get("modell_brukt", True) is not False


def _modellen_kjorte(deler: dict) -> bool:
    """Om språkmodellen faktisk bidro til svaret.

    Én regel, brukt av BEGGE /dokument-kontraktene og av
    operasjonsmotoren, så de ikke kan gi hvert sitt svar på samme
    spørsmål. Operasjoner-veien hardkodet tidligere `kilde: "motor"`
    uansett — en robot som fulgte den dokumenterte regelen («inneholder
    borealis ⇒ modellen bidro») leste ethvert operasjonssvar som rent
    deterministisk og hoppet over menneskelig kontroll."""
    return any(_delen_brukte_modellen(deler.get(navn))
               for navn in ("svar", "skjema", "korriger"))


def _borealis_er_klar():
    return _borealis["status"] == "klar"


def _borealis_nede_feil():
    return f"Borealis er ikke klar ({_borealis['status']}) — prøv igjen senere"


_TOM_DOKUMENT_FEIL = "Fant ingen lesbar tekst i dokumentet"


# ------------------------------------------------------------------ #
#  Vakt mot feilnavngitte skjemafelter (UiPath-fella)                 #
# ------------------------------------------------------------------ #
#  UiPath: BEGGE delene tar VERDIEN først og NAVNET sist —            #
#      New FileFormDataPart(filsti, "fil")                            #
#      New TextFormDataPart("auto", "skjema_motor")                   #
#  Snur en klient tekstfeltene (navn først), havner navnet i verdi-   #
#  plassen og serveren får felter som HETER «auto», «ja» eller en hel #
#  JSON-streng. Før gikk de tapt i stillhet og svaret ble et          #
#  misvisende 200. En profesjonell API sier tydelig fra.              #
#                                                                     #
#  RETTET 2026-08-03: teksten her påsto tidligere det MOTSATTE (navn  #
#  først for Text). Det er feil, og feilmeldingen under sendte derfor #
#  brukeren rett i grøfta: legger man JSON-malen i andre argument,    #
#  kaster UiPath «The format of value '{…}' is invalid» FØR requesten #
#  sendes — nettopp fordi andre argument er NAVNET, som må være et    #
#  gyldig token. Bekreftet mot brukerens kjørende UiPath-oppsett.

# Ord/mønstre som røper at en VERDI er brukt som feltnavn.
_VERDI_ORD = {"ja", "nei", "auto", "felter", "modell", "1", "0", "true",
              "false", "på", "pa", "av", "yes", "no", "on", "off"}


def _ser_ut_som_verdi(navn: str) -> bool:
    """Ser feltNAVNET ut som en VERDI (→ omvendt TextFormDataPart)?"""
    n = (navn or "").strip()
    if n.lower() in _VERDI_ORD:
        return True
    if n.startswith(("{", "[")):                       # JSON-mal som navn
        return True
    if re.match(r"^[A-Za-z]:[\\/]", n) or "\\" in n:    # filsti som navn
        return True
    if n.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".txt", ".docx")):
        return True
    # Fritekst brukt som feltnavn. Den vanligste omvendte delen er ikke en
    # bryterverdi, men SPØRSMÅLET: «Hva er beløpet?» havner som navn, og
    # ordlista over fanget den ikke. Målt på den kjørende serveren ga det
    # 200 med hele dokumentteksten i stedet for svaret.
    #
    # Et ekte feltnavn i dette API-et er en kort identifikator — alle 16
    # kjente består av små bokstaver og understrek. Mellomrom,
    # spørsmålstegn eller mer enn 40 tegn er derfor aldri et feltnavn.
    # Vakten kjører kun på navn som ALLEREDE er ukjente, så en feiltolkning
    # her koster 400 i stedet for en mild advarsel — på et navn serveren
    # uansett ikke ville brukt til noe.
    if " " in n or "?" in n or len(n) > 40:
        return True
    return False


def _sjekk_feltnavn(tekstfelter: dict, kjente: set):
    """Deler mottatte feltnavn i (ukjente, omvendte). «omvendte» er de som
    tydelig er en verdi brukt som navn — en klar UiPath-feil vi stopper med
    400. «ukjente» ellers er bare ukjente navn vi advarer mildt om."""
    ukjente = [n for n in tekstfelter if n and n not in kjente]
    omvendte = [n for n in ukjente if _ser_ut_som_verdi(n)]
    milde = [n for n in ukjente if n not in omvendte]
    return milde, omvendte


# Feltnavn hvert endepunkt faktisk kjenner (fil-delen «fil» er egen, ikke
# et tekstfelt). Alt annet er ukjent — og en verdi-som-navn stoppes.
_KJENTE_FELT_DOKUMENT = {
    "felter", "struktur", "svar", "skjema", "korriger", "tekst", "sporsmal",
    "skjema_mal", "skjema_motor", "operasjoner", "maks_sider", "strekkoder",
    "koordinater", "datoer_detaljert", "profil", "opphav"}
_KJENTE_FELT_OPERASJONER = {"operasjoner", "maks_sider", "strekkoder",
                            "profil", "opphav"}
_KJENTE_FELT_FORHANDSSJEKK = {"maks_sider"}
_KJENTE_FELT_SLADD = {"typer", "maks_sider"}
_KJENTE_FELT_SPOR = {"sporsmal", "jobb_id", "korriger", "maks_sider",
                     "strekkoder"}
_KJENTE_FELT_JOBB = {"maks_sider", "sporsmal"}
_KJENTE_FELT_INNSYN = {"maks_sider"}

# Hvilket feltsett hver POST-rute kjenner. Fire ruter hadde vakten fra
# før; tre hadde den ikke, og målt var det NETTOPP der den manglet mest:
# på /spor gir et omvendt felt (UiPath sender verdi først, navn sist —
# R63) et helt vanlig 200. Spørsmålet havner som feltnavn, «sporsmal»
# blir tomt, R47 slår inn, og roboten får hele dokumentteksten tilbake
# med `ok: true` og ingen advarsel. Et vellykket svar som ikke er svaret.
#
# /ekko står MED VILJE utenfor: den finnes for å vise klienten nøyaktig
# hva serveren mottok. Avviste den en omvendt del med 400, ville den
# skjult akkurat det feilsøkeren kom for å se.
# Seksjonene «profil=sammendrag» BEHOLDER. Alt annet fjernes og
# navngis i «utelatt».
#
# Lista er en modulkonstant og ikke en lokal variabel fordi den ER
# kontrakt: en vakttest må kunne se den. Uten det sto «hjemmel» her i
# månedsvis etter at R113 hadde døpt seksjonen om til «gjeldende_lov» —
# det gamle navnet traff ingenting, det nye sto ikke i lista, og
# personvernbryteren fjernet dermed en seksjon som er avledet av
# dokumentDATOEN alene og ikke bærer én eneste personopplysning.
#
# «ytelser» og «hjemler» blir med av samme grunn: de sier hva dokumentet
# HANDLER om og hvilke bestemmelser det viser til. Utelot vi dem, ville
# «utelatt» påstå at de ble fjernet av personvernhensyn, og klienten
# mistet nettopp den saksinformasjonen den ba om.
_PROFIL_SAMMENDRAG_BEHOLD = (
    "skjemaversjon", "sammendrag", "fil", "dokument", "sak",
    "ytelse", "ytelser", "gjeldende_lov", "hjemler", "koder", "dekning")

_FELTSETT_PER_RUTE = {
    "/dokument": _KJENTE_FELT_DOKUMENT,
    "/dokument/operasjoner": _KJENTE_FELT_OPERASJONER,
    "/forhandssjekk": _KJENTE_FELT_FORHANDSSJEKK,
    "/sladd": _KJENTE_FELT_SLADD,
    "/spor": _KJENTE_FELT_SPOR,
    "/jobb": _KJENTE_FELT_JOBB,
    "/innsyn": _KJENTE_FELT_INNSYN,
}


def _ukjent_felt_advarsel(milde: list, kjente: set) -> list:
    """Advarselslinjene for felt serveren ikke kjenner. Tom liste når alt
    er kjent, så kalleren bare kan utvide advarselslista si.

    Et ukjent felt er ALLTID verdt å melde: klienten trodde den ba om noe,
    og fikk 200 som om den fikk det."""
    if not milde:
        return []
    return ["Ukjente felt ignorert: " + ", ".join(milde)
            + ". Kjente felt: " + ", ".join(sorted(kjente))]


def _omvendt_felt_feil(omvendte: list, kjente: set) -> dict:
    """Feilobjektet for 400 når feltnavn er en verdi (omvendt UiPath-orden)."""
    vis = ", ".join((n if len(n) <= 40 else n[:37] + "…") for n in omvendte)
    return {
        "ok": False,
        "feil": (f"Mottok felt som ser ut som VERDIER brukt som feltnavn: "
                 f"{vis}. I UiPath kommer VERDIEN først og NAVNET sist — "
                 "likt for begge delene: TextFormDataPart(verdi, navn) og "
                 "FileFormDataPart(sti, navn). Snu de tekstlige feltene, "
                 'f.eks. New TextFormDataPart("auto", "skjema_motor") og '
                 'New TextFormDataPart("{…}", "skjema_mal").'),
        "ukjente_felt": omvendte,
        "kjente_felt": sorted(kjente),
        "felter_feil": [{"pointer": f"/{n}",
                         "message": "Ser ut som en verdi brukt som feltnavn "
                                    "(snu rekkefølgen: navn først)"}
                        for n in omvendte],
    }


class Operasjon:
    """Basis for alt motoren kan gjøre. En operasjon leser fra konteksten
    og returnerer et selvstendig {type, ok, …}-resultat. Underklasser
    implementerer utfor(ktx)."""

    type = "operasjon"

    def utfor(self, ktx):
        raise NotImplementedError

    def _krever_borealis(self):
        """Trenger operasjonen modellen? Da gir motoren riktig 503-signal
        når den er BARE modelldeler og Borealis er nede."""
        return False


class TekstOperasjon(Operasjon):
    type = "tekst"

    def utfor(self, ktx):
        return {"type": "tekst", "ok": True, "data": ktx.tekst}


class FelterOperasjon(Operasjon):
    type = "felter"

    def utfor(self, ktx):
        return {"type": "felter", "ok": True, "data": {
            "felter": ktx.felter,
            "datoer": ktx.datoer,
            "datoer_detaljert": ktx.datoer_detaljert,
            "dokumentdato": ktx.dokumentdato,
        }}


class StrukturOperasjon(Operasjon):
    type = "struktur"

    def utfor(self, ktx):
        return {"type": "struktur", "ok": True, "data": ktx.struktur}


class SvarOperasjon(Operasjon):
    type = "svar"

    def __init__(self, sporsmal):
        self.sporsmal = sporsmal

    def _krever_borealis(self):
        # En ren sidelesing besvares deterministisk fra sidemarkørene —
        # den skal ikke telle som modelloperasjon i 503-porten
        return not kan_svares_uten_modell(self.sporsmal)

    def utfor(self, ktx):
        if self._krever_borealis() and not _borealis_er_klar():
            return {"type": "svar", "ok": False, "feil": _borealis_nede_feil()}
        if ktx.er_tom():
            return {"type": "svar", "ok": False, "feil": _TOM_DOKUMENT_FEIL}
        kjerne = svar_paa_sporsmal(ktx.tekst, self.sporsmal, ktx.ocr_brukt,
                                   ktx.handskrift, ktx.strekkoder)
        if kjerne["tom"]:
            return {"type": "svar", "ok": False, "feil": _TOM_DOKUMENT_FEIL}
        return {"type": "svar", "ok": True, "sporsmal": self.sporsmal,
                "svar": kjerne["svar"],
                "modell_brukt": kjerne.get("modell_brukt", True),
                "tall_verifisert": kjerne["tall_verifisert"],
                "tolket_sporsmal": kjerne["tolket_sporsmal"],
                "svar_avkortet": kjerne["svar_avkortet"],
                "advarsler": kjerne["advarsler"]}


class SkjemaOperasjon(Operasjon):
    type = "skjema"

    # Gyldige motorer — samme tre som skjema_motor-bryteren.
    MOTORER = ("felter", "modell", "auto")

    def __init__(self, mal, motor="modell"):
        self.mal = mal
        self.motor = motor

    def _krever_borealis(self):
        # Bare ren modell-motor MÅ ha Borealis; felter er kode, og auto
        # degraderer til deterministisk når modellen er nede.
        return self.motor == "modell"

    def utfor(self, ktx):
        if self.motor == "felter":
            utfylt, rapport = flett_mal(self.mal, ktx.tekst, ktx.ocr_brukt)
            return {"type": "skjema", "ok": True, "motor": "felter",
                    "data": utfylt,
                    "ukjente_felter": rapport["ukjente_felter"],
                    "tilgjengelige_felter": rapport["tilgjengelige_felter"]}
        if self.motor == "auto":
            res = flett_mal_hybrid(ktx.tekst, self.mal, ktx.ocr_brukt,
                                   _borealis_er_klar() and not ktx.er_tom())
            return {"type": "skjema", "ok": True, "motor": "auto",
                    "data": res["skjema"],
                    "kilde_per_felt": res["kilde_per_felt"],
                    "modell_brukt": res["modell_brukt"],
                    "avvik": res["avvik"],
                    "ukjente_felter": res["ukjente_felter"],
                    "tilgjengelige_felter": res["tilgjengelige_felter"]}
        # motor == "modell"
        if not _borealis_er_klar():
            return {"type": "skjema", "ok": False, "feil": _borealis_nede_feil()}
        if ktx.er_tom():
            return {"type": "skjema", "ok": False, "feil": _TOM_DOKUMENT_FEIL}
        res = fyll_skjema_kjerne(ktx.tekst, self.mal)
        if not res.get("ok"):
            return {"type": "skjema", "ok": False,
                    "feil": res.get("feil"), "raasvar": res.get("raasvar")}
        return {"type": "skjema", "ok": True, "motor": "modell",
                "data": res["skjema"], "avvik": res.get("avvik", [])}


class KorrigerOperasjon(Operasjon):
    type = "korriger"

    def _krever_borealis(self):
        return True

    def utfor(self, ktx):
        if not _borealis_er_klar():
            return {"type": "korriger", "ok": False,
                    "feil": _borealis_nede_feil()}
        if not ktx.ocr_brukt:
            return {"type": "korriger", "ok": False,
                    "feil": "Dokumentet har tekstlag — ingen OCR-feil å korrigere"}
        if ktx.er_tom():
            return {"type": "korriger", "ok": False, "feil": _TOM_DOKUMENT_FEIL}
        return {"type": "korriger", "ok": True,
                "data": korriger_borealis(ktx.tekst)}


def bygg_operasjon(spec):
    """Bygger én Operasjon fra en {type, …}-spesifikasjon (fra
    operasjoner-kontraktet). Ukjent type eller manglende påkrevd felt gir
    ValueError med en tydelig norsk melding — fanges av handleren som 400."""
    if not isinstance(spec, dict):
        raise ValueError("hver operasjon må være et objekt med 'type'")
    t = str(spec.get("type", "")).strip().lower()
    if not t:
        raise ValueError("operasjon mangler 'type'")

    if t == "tekst":
        return TekstOperasjon()
    if t == "felter":
        return FelterOperasjon()
    if t == "struktur":
        return StrukturOperasjon()
    if t == "svar":
        sporsmal = str(spec.get("sporsmal", "")).strip()
        if not sporsmal:
            raise ValueError("operasjon 'svar' krever feltet 'sporsmal'")
        return SvarOperasjon(sporsmal)
    if t == "korriger":
        return KorrigerOperasjon()
    if t == "skjema":
        mal = spec.get("mal")
        if not isinstance(mal, (dict, list)) or not mal:
            raise ValueError(
                "operasjon 'skjema' krever 'mal' (et ikke-tomt objekt/liste)")
        motor = str(spec.get("motor", "modell")).strip().lower() or "modell"
        if motor not in SkjemaOperasjon.MOTORER:
            raise ValueError(
                f"ukjent 'motor': {motor!r} — bruk "
                + "/".join(SkjemaOperasjon.MOTORER))
        return SkjemaOperasjon(mal, motor)

    raise ValueError(
        f"ukjent operasjonstype: {t!r} — gyldige: tekst, felter, struktur, "
        "svar, skjema, korriger")


class Operasjonsmotor:
    """Kjører en liste operasjoner mot én kontekst. Hver operasjon feiler
    UAVHENGIG: en som kaster, blir til et {ok: False, feil}-resultat i
    stedet for å rive med seg de andre — samme løfte som /dokument alt
    gir per del."""

    def kjor(self, ktx, operasjoner, advarsler=None):
        """Kjører operasjonene i rekkefølge, innenfor et BUDSJETT.

        Uten budsjett kunne én forespørsel be om 20 svar-operasjoner à
        opptil 5 modellkall = 100 genereringer. Målt kostnad er 0,3–2,8 s
        per generering, alt serialisert bak GPU-låsen — altså 30–280 s i
        ÉN forespørsel, mot en socketfrist på 120 s, mens den holder én
        av to kapasitetsplasser. Klienten fikk ikke svar, og alle andre
        stod i kø imens.

        Nå stopper vi når budsjettet er brukt og leverer det som ER
        gjort, med en ærlig beskjed om resten. Delvis svar slår et svar
        som aldri kommer."""
        resultater = []
        brukt_tid = time.time()
        modellkall = 0
        for nr, op in enumerate(operasjoner):
            krever_modell = op._krever_borealis()
            over_frist = (time.time() - brukt_tid) > OPERASJON_FRIST_S
            if krever_modell and (modellkall >= MAKS_MODELLOPERASJONER
                                  or over_frist):
                grunn = ("tidsbudsjettet på "
                         f"{OPERASJON_FRIST_S:.0f} s er brukt" if over_frist
                         else f"budsjettet på {MAKS_MODELLOPERASJONER} "
                              "modelloperasjoner er brukt")
                melding = (
                    f"Operasjon {nr + 1} ({getattr(op, 'type', '?')}) ble "
                    f"ikke kjørt: {grunn}. Del opp forespørselen, eller "
                    f"bruk POST /jobb for store bestillinger.")
                resultater.append({"type": getattr(op, "type", "operasjon"),
                                   "ok": False, "feil": melding,
                                   "utelatt": True})
                if advarsler is not None and melding not in advarsler:
                    advarsler.append(melding)
                continue
            try:
                resultater.append(op.utfor(ktx))
                if krever_modell:
                    modellkall += 1
            except Exception as exc:      # noqa: BLE001 — én del skal ikke
                resultater.append({       # kunne velte de andre
                    "type": getattr(op, "type", "operasjon"),
                    "ok": False,
                    "feil": f"Operasjonen feilet ({type(exc).__name__}): "
                            f"{exc}"[:300]})
        return resultater


def _varm_opp_ocr():
    """Laster OCR-modellene på forhånd, i bakgrunnen.

    Venter til Borealis har tatt sin plass på GPU-en først — ellers ville
    OCR-motorene kunne legge beslag på minne språkmodellen trenger, og
    rekkefølgen på GPU-en ville avhenge av tilfeldig timing.
    """
    # R58: flagget settes FØR ventingen, ikke etter. Settes det etterpå,
    # finnes det et vindu på opptil ett sekund mellom at Borealis blir
    # klar og at oppvarmingen tar motorlåsen — og en forespørsel som
    # traff akkurat der ble stående i nesten et halvt minutt i stedet for
    # å få beskjed om å prøve igjen.
    _oppvarming["pagaar"] = True
    try:
        # R-fiks 2026-07-23: vent lenger, og GI OPP hvis Borealis fortsatt
        # laster. Før: etter 60 s fortsatte oppvarmingen mens Borealis var
        # midt i allokeringen — VRAM-avgjørelsen så et halvtomt kort, begge
        # motorene la seg på GPU-en, og neste llama.cpp-buffer sprengte den
        # (stille nativ krasj). Å hoppe over oppvarming er ufarlig: modellene
        # lastes da ved første forespørsel, med RIKTIG VRAM-bilde.
        for _ in range(180):
            if _borealis["status"] in ("klar", "feil"):
                break
            time.sleep(1)
        if _borealis["status"] not in ("klar", "feil"):
            print("  [OCR] Oppvarming hoppet over — Borealis laster ennå "
                  "(motorene lastes trygt ved første forespørsel).")
            return
        import numpy as _np

        from delt.region_ocr import ocr_side
        # Et bittelite hvitt bilde: laster og initialiserer motorene uten
        # å gjøre noe reelt arbeid.
        ocr_side(_np.full((64, 256, 3), 255, dtype=_np.uint8))
        from delt.region_ocr import _hent_norhand
        _hent_norhand()
        print("  OCR-motorene er varme — første dokument slipper ventetiden.")
    except Exception as exc:
        # Oppvarming er en optimalisering, aldri et krav: feiler den,
        # lastes modellene som før ved første forespørsel.
        print(f"  [OCR] Oppvarming hoppet over ({type(exc).__name__}: {exc})")
    finally:
        _oppvarming["pagaar"] = False


def main():
    try:
        server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    except OSError as exc:
        print(f"\n!!! Port {PORT} opptatt: {exc}")
        print("    Bruk en annen: set DOKUMENT_API_PORT=8601 && python skript/dokument_api.py\n")
        return
    # Borealis lastes i bakgrunnen — /analyser virker med en gang,
    # /spor blir klar når modellen er lastet (~1-2 min).
    if os.path.isdir(BOREALIS_STI):
        threading.Thread(target=_last_borealis_bakgrunn, daemon=True).start()
    else:
        _borealis.update(status="feil", feil=f"Modellmappe finnes ikke: {BOREALIS_STI}")

    # Jobbsystem: last ferdige jobber fra disk og start arbeidstråden
    _jobb_last_fra_disk()
    threading.Thread(target=_jobb_arbeider, daemon=True).start()

    # Motoravtrykk: varsle høyt hvis EasyOCR-/RapidOCR-/Doc-UFCN-/Borealis-
    # vektene er byttet siden tersklene ble kalibrert (norhand har sin egen,
    # sterkere mekanisme: grunnmodell.json + automatisk retrening).
    try:
        from delt import motoravtrykk
        motoravtrykk.sjekk()
    except Exception as exc:
        print(f"(motoravtrykk-sjekk hoppet over: {exc})")

    # R54: varm opp OCR-motorene i bakgrunnen. Uten dette betaler den
    # FØRSTE brukerforespørselen for at modellene lastes — målt på en
    # taxikvittering: 10,3 s første gang, 4,3 s deretter, der ~6 s var
    # ren lasting av håndskriftmodellen. Den kostnaden hører hjemme i
    # oppstarten, ikke i et tilfeldig brukerkall.
    threading.Thread(target=_varm_opp_ocr, daemon=True).start()

    strek = "=" * 64
    print(strek)
    print("  NAV dokument-API (generelt) — SERVEREN KJØRER NÅ")
    print(strek)
    print(f"  Felter (deterministisk): POST http://<din-ip>:{PORT}/analyser   (felt: fil)")
    print(f"  Fritt spørsmål (LLM):    POST http://<din-ip>:{PORT}/spor       (felter: fil + sporsmal)")
    print("  Alle endepunkter: GET /hjelp. Borealis laster i bakgrunnen.")
    if _ENV_SATT:
        print(f"  Leste fra .env: {', '.join(sorted(_ENV_SATT))}")
    # Sikkerheten skal ALDRI være noe man må gjette seg til. Står serveren
    # åpen samtidig som tunnelen er oppe, er dokumenter med
    # personopplysninger fritt tilgjengelige på internett — det skal stå
    # med store bokstaver i oppstarten, ikke gjemmes i GET /hjelp.
    if API_NOKKEL or API_NOKLER:
        kilder = []
        if API_NOKKEL:
            kilder.append("API_NOKKEL")
        if API_NOKLER:
            kilder.append(f"API_NOKLER ({len(API_NOKLER)} navngitte)")
        print(f"  Sikkerhet: X-API-Key KREVES ({' + '.join(kilder)}).")
        if API_NOKLER:
            # Navnene, ALDRI nøklene. Operatøren skal kunne se hvem som
            # er sluppet inn uten at loggen eller skjermbildet blir en
            # nøkkellekkasje.
            print(f"  Klienter: {', '.join(sorted(API_NOKLER))}")
        svake = svake_nokler(API_NOKLER)
        if svake:
            print(f"  ADVARSEL: for korte nøkler ({', '.join(svake)}) — "
                  f"under {MINSTE_NOKKELLENGDE} tegn er gjettbart.")
        for delte in gjenbrukte_nokler(API_NOKLER):
            # To navn med samme nøkkel er ÉN klient med to navn, og da
            # lyver klient_id i loggen — som er det eneste hele
            # klientidentiteten bygger på.
            print(f"  ADVARSEL: {', '.join(delte)} DELER nøkkel — "
                  f"klient_id i loggen blir da vilkårlig.")
        if not API_NOKLER:
            print("  MERK: én delt nøkkel ⇒ alle kall er anonyme i "
                  "tilgangsloggen. Sett API_NOKLER=navn:nøkkel,… for å "
                  "kunne se hvem som bruker hva (R91).")
    else:
        print("  " + "!" * 60)
        print("  ADVARSEL: API-et er ÅPENT — hvem som helst som når porten")
        print("  kan sende inn og lese ut dokumenter. Kjører du tunnelen,")
        print("  gjelder det HELE INTERNETT. Sett API_NOKKEL i .env (eller")
        print("  som miljøvariabel) og start på nytt for å kreve X-API-Key.")
        print("  " + "!" * 60)
    print("  Avslutt med Ctrl+C.")
    print(strek + "\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStoppet.")


if __name__ == "__main__":
    main()

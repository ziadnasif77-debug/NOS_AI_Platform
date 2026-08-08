"""
Skrivebordsklient (GUI) for NAV dokument-API-et (Borealis).

Inneholder også et KONTROLLPANEL (første fane): start/stopp av tjenestene
på denne maskinen (dokument-API, Prefect, Label Studio, tunnel) med
grønn/rød/gul statusindikator, «Start alt»/«Stopp alt», og live-grafer
for GPU, VRAM, CPU og RAM. Tjenester startes skjult via oppstart\-mappen
(samme mekanisme som start_alt.bat) — ingen vinduer å lukke ved uhell.

Dekker alle endepunktene i serveren (skript/dokument_api.py) — feltnavn,
statusverdier og feilkoder er VERIFISERT mot serverkoden, ikke gjettet:

  - Dokument     POST /dokument       ETT kall med brytere (felter/struktur/
                                      svar/skjema/korriger) — leses én gang
  - Spør         POST /spor           fil og/eller spørsmål → svar
  - Fyll skjema  POST /dokument  skjema_mal → utfylte felter
  - Analyser     POST /dokument  felter=ja → deterministisk felt-/datoanalyse
  - Uttrekk      POST /uttrekk        fil → strukturert uttrekk med fast skjema
  - Storjobb     POST /jobb m.fl.     bakgrunnsbehandling av store skanninger,
                                      med automatisk statusoppfølging
  - Serverinfo   GET /hjelp, /openapi.json og lenke til /dokumentasjon

Slik kjører du:
  python skript/api_klient_gui.py

Sikkerhet:
  Serveren kan startes med miljøvariabelen API_NOKKEL (R38) — da kreves
  headeren X-API-Key på alle forespørsler. Fyll inn nøkkelen i feltet
  øverst; den sendes automatisk med alle kall.

Innstillinger (server-URL og API-nøkkel) lagres i ~/.nav_api_klient.json
og huskes til neste gang — praktisk siden trycloudflare-adressen bytter
ved hver tunnelomstart.

Ingen manuell pip-installasjon trengs: manglende pakker (requests, Pillow,
fpdf2, pywin32) installeres automatisk første gang de faktisk brukes.
Merk: dette gjelder KLIENTMASKINEN — den isolerte serveren bruker
offline-distribusjonen (skript/installer_offline.py) som før.

Filtyper som støttes overalt der en fil kan lastes opp (konverteres
automatisk til PDF før opplasting):
  - PDF                          → sendes som den er
  - Bilder (jpg, png, bmp,
    tif, gif, webp)              → konverteres til én-siders PDF
  - Tekst (.txt)                 → konverteres til PDF
  - Word (.docx, .doc)           → konverteres via Microsoft Word
  - Excel (.xlsx, .xls)          → konverteres via Microsoft Excel
  - PowerPoint (.pptx, .ppt)     → konverteres via Microsoft PowerPoint

Om Office-konvertering:
  Konvertering av Office-filer krever at det tilhørende Office-programmet
  faktisk er installert på denne Windows-maskinen. Er det ikke det, vises
  en tydelig feilmelding — bruk da Fil > Lagre som > PDF i Office og last
  opp PDF-en i stedet.
"""

import importlib
import subprocess
import sys


def _sikre_pakke(import_navn: str, pip_navn: str | None = None) -> None:
    """Sørger for at `import_navn` kan importeres — installerer `pip_navn`
    (eller `import_navn`) med pip først om nødvendig. Installerer inn i
    akkurat den Python-tolken som kjører dette skriptet (sys.executable),
    så pakken alltid havner der skriptet ser den."""
    try:
        importlib.import_module(import_navn)
        return
    except ImportError:
        pass

    pakke = pip_navn or import_navn
    print(f"«{pakke}» er ikke installert — installerer med pip ...")

    grunnkommando = [sys.executable, "-m", "pip", "install", "--quiet", pakke]
    try:
        subprocess.check_call(grunnkommando)
    except subprocess.CalledProcessError:
        # Vanlig installasjon kan feile uten administratorrettigheter når
        # Python er installert for hele maskinen — prøv per-bruker i stedet.
        try:
            subprocess.check_call(grunnkommando + ["--user"])
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"Klarte ikke å installere «{pakke}» automatisk. Kjør manuelt:\n"
                f"    {sys.executable} -m pip install {pakke}"
            ) from exc

    # En per-bruker-installasjon kan havne i brukerens site-packages, som
    # bare ligger på sys.path hvis mappen fantes da tolken startet — la
    # den til selv så den allerede kjørende prosessen ser pakken.
    import site

    bruker_site = site.getusersitepackages()
    if bruker_site not in sys.path:
        sys.path.insert(0, bruker_site)
    site.addsitedir(bruker_site)
    importlib.invalidate_caches()

    try:
        importlib.import_module(import_navn)
    except ImportError as exc:
        raise RuntimeError(
            f"«{pakke}» ble installert av pip, men Python finner den fortsatt "
            "ikke. Lukk terminalen, åpne en ny og kjør skriptet på nytt — "
            f"eller kjør manuelt:\n    {sys.executable} -m pip install {pakke}"
        ) from exc

    print(f"«{pakke}» er installert.")


# `requests` trengs umiddelbart (alle kall bruker den) og sikres med en
# gang. Pillow / fpdf2 / pywin32 trengs bare for enkelte filtyper og
# sikres lat, rett før første bruk, lenger ned.
try:
    _sikre_pakke("requests")
except RuntimeError as exc:
    # tkinter er del av standardbiblioteket, så denne dialogen er
    # tilgjengelig selv om hoved-GUI-et ikke har startet ennå.
    try:
        import tkinter as _tk
        from tkinter import messagebox as _messagebox

        _rot = _tk.Tk()
        _rot.withdraw()
        _messagebox.showerror("Manglende avhengighet", str(exc))
        _rot.destroy()
    except Exception:
        pass
    print(str(exc))
    sys.exit(1)

import collections
import ctypes
import json
import os
import re
import shutil
import tempfile
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext

import requests

# --- innstillinger som huskes mellom kjøringer -----------------------------
KONFIG_STI = Path.home() / ".nav_api_klient.json"
# R51: IPv4-adressen direkte, IKKE «localhost». Windows slår opp
# localhost som IPv6 (::1) først, mens serveren lytter på IPv4 — hvert
# kall betaler da ~2 sekunder på et oppslag som må feile før det faller
# tilbake. Målt: localhost 2,07 s mot 127.0.0.1 0,016 s for GET /hjelp.
STANDARD_URL = "http://127.0.0.1:8600"

TIDSAVBRUDD_KORT = 30    # sekunder — status/oppslag
TIDSAVBRUDD_LANG = 180   # sekunder — opplasting + modellsvar
JOBB_POLL_MS = 3000      # automatisk statussjekk for storjobber

BILDE_ENDELSER = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".gif", ".webp"}
TEKST_ENDELSER = {".txt"}
OFFICE_APPER = {
    ".docx": "Word.Application",
    ".doc": "Word.Application",
    ".xlsx": "Excel.Application",
    ".xls": "Excel.Application",
    ".pptx": "PowerPoint.Application",
    ".ppt": "PowerPoint.Application",
}

FILDIALOG_TYPER = [
    (
        "Støttede filer",
        "*.pdf *.jpg *.jpeg *.png *.bmp *.tif *.tiff *.gif *.webp "
        "*.txt *.docx *.doc *.xlsx *.xls *.pptx *.ppt",
    ),
    ("PDF-filer", "*.pdf"),
    ("Bilder", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.gif *.webp"),
    ("Word-dokumenter", "*.docx *.doc"),
    ("Excel-regneark", "*.xlsx *.xls"),
    ("PowerPoint-presentasjoner", "*.pptx *.ppt"),
    ("Tekstfiler", "*.txt"),
    ("Alle filer", "*.*"),
]

# Fremdriftsindikator: klossen sveiper over på SVEIP_SEKUNDER og tilbake
# på SVEIP_SEKUNDER — styrt av klokken, ikke antall steg, så bevegelsen
# er jevn uavhengig av maskinens hastighet.
ANIM_SVEIP_SEKUNDER = 1.0
ANIM_BILDE_MS = 16  # ~60 bilder/sekund
ANIM_KLOSS_BREDDE_ANDEL = 0.14

# --- mørkt fargetema -------------------------------------------------------
BG_HOVED = "#0d0d0d"       # vindusbakgrunn
BG_PANEL = "#161616"       # LabelFrame-/panelbakgrunner
BG_INNDATA = "#1e1e1e"     # Entry-/Text-bakgrunner
BG_KNAPP = "#242424"       # vanlige knapper
BG_KNAPP_AKTIV = "#333333"
FG_TEKST = "#e8e8e8"       # primærtekst
FG_DEMPET = "#9a9a9a"      # sekundær-/statustekst
KANTLINJE = "#333333"
AKSENT = "#2563eb"         # primærknapper + fokusmarkering
AKSENT_AKTIV = "#1d4ed8"
FREMDRIFT_BG = "#242424"
FREMDRIFT_KANT = "#3a3a3a"
FREMDRIFT_KLOSS = "#22c55e"
ADVARSEL_BG = "#3a2a06"
ADVARSEL_FG = "#fbbf24"

# --- kontrollpanelets fargepalett (statuser + tjenester + grafer) ----------
GRONN = "#22c55e"          # kjører / start-knapper
GRONN_AKTIV = "#16a34a"
ROD = "#ef4444"            # stoppet / stopp-knapper
ROD_AKTIV = "#dc2626"
GUL = "#f59e0b"            # starter / modell laster
CYAN = "#06b6d4"           # dokument-API
BLAA = "#3b82f6"           # Prefect + CPU-graf
ROSA = "#ec4899"           # Label Studio
ORANSJE = "#fb923c"        # tunnel + VRAM-graf
LILLA = "#a855f7"          # RAM-graf

# Bredden på den reserverte plassen ytterst til høyre i hvert
# tjenestekort. Bare Label Studio bruker den (knappen «Passord»), men
# plassen holdes av på ALLE rader — ellers blir den ene raden bredere
# enn de andre og skyver de fire faste knappene ut av kolonnene (R177).
# Målt for teksten «Passord» i Segoe UI 9 bold med padx 12.
EKSTRAKNAPP_BREDDE = 84

# Fanene i appen, i rekkefølge: (intern nøkkel, knappetekst)
FANER = [
    ("kontroll", "Kontrollpanel"),
    ("flyt", "Flytskjema"),
    ("innsyn", "Innsyn"),
    ("trening", "Trening"),
    ("dokument", "Dokument"),
    ("operasjoner", "Operasjoner"),
    ("spor", "Spør"),
    ("fyll_skjema", "Fyll skjema"),
    ("analyser", "Analyser"),
    ("uttrekk", "Uttrekk"),
    ("jobb", "Storjobb"),
    ("info", "Serverinfo"),
]

# Limer noen inn en full endepunkt-URL (f.eks. «.../spor») i URL-feltet i
# stedet for bare tunneladressen, strippes stien av igjen — begge former
# virker, og en fane ender aldri opp med å bygge «.../spor/spor».
KJENTE_ENDEPUNKT_SUFFIKSER = (
    "/spor", "/jobb", "/dokument", "/dokument/operasjoner",
    "/hjelp", "/dokumentasjon", "/openapi.json",
)

# Statusverdier en storjobb kan ha (verifisert mot serverkoden)
JOBB_AKTIVE_STATUSER = ("kø", "pågår")
JOBB_FERDIG_STATUSER = ("ferdig", "feil", "avbrutt")

EKSEMPEL_SKJEMA = """{
  "navn": null,
  "fodselsnummer": null,
  "dato": null,
  "belop": null,
  "adresse": null
}"""

# Eksempelmal for felter-/auto-motoren: {feltnavn}-plassholdere som
# flettes deterministisk (auto lar modellen ta det regelen ikke fant).
EKSEMPEL_SKJEMA_FLETT = """{
  "kunde": "{navn}",
  "telefon": "{telefon}",
  "sted": "{poststed}",
  "ytelse": "{ytelse}",
  "belop": "{belop}"
}"""

# De tre skjema-motorene, delt av /dokument og /fyll_skjema.
SKJEMA_MOTORER = [
    ("modell", "Modell — Borealis fyller alt (tregere, forstår fritekst)"),
    ("felter", "Felter — deterministisk {feltnavn} (raskt, uten modell)"),
    ("auto", "Auto — hybrid: regel der mulig, modell for resten (navn o.l.)"),
]

# Eksempel for Operasjoner-fanen: det uniforme kontraktet der ÉN
# forespørsel ber om flere ting på rad, hver med sitt eget resultat.
EKSEMPEL_OPERASJONER = """[
  { "type": "felter" },
  { "type": "skjema", "motor": "auto",
    "mal": { "kunde": "{navn}", "telefon": "{telefon}", "ytelse": "{ytelse}" } }
]"""


def les_konfig() -> dict:
    """Leser lagrede innstillinger — tom dict om filen mangler/er ødelagt."""
    try:
        data = json.loads(KONFIG_STI.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def lagre_konfig(url: str, api_nokkel: str) -> None:
    """Lagrer innstillinger for neste kjøring. Feiler stille — manglende
    lagring skal aldri stoppe selve arbeidet."""
    try:
        KONFIG_STI.write_text(
            json.dumps({"base_url": url, "api_nokkel": api_nokkel},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def formater_varighet(sekunder: float) -> str:
    if sekunder < 60:
        return f"{sekunder:.1f} s"
    minutter = int(sekunder // 60)
    rest = sekunder % 60
    return f"{minutter} min {rest:.0f} s"


def formater_json(data: dict) -> str:
    """Full, lesbar JSON — den trygge visningen som aldri skjuler noe av
    det serveren faktisk sendte."""
    try:
        return json.dumps(data, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(data)


def bygg_advarselstekst(data: dict) -> str:
    """Løfter frem API-ets ærlighetsfelter likt på tvers av alle faner —
    ikke bare der en bestemt visning kjenner dem fra før."""
    deler = []
    if data.get("uten_dokument"):
        deler.append(
            "⚠ Generelt modellsvar, IKKE lest fra noe dokument. Tallvakten som "
            "beskytter beløp, datoer og identifikatorer gjelder ikke her — "
            "kontroller alt som betyr noe før du stoler på det."
        )
    if data.get("svar_avkortet"):
        deler.append("⚠ Svaret ble avkortet av serveren (svar_avkortet) — det kan være ufullstendig.")
    if data.get("korrigert_tekst"):
        deler.append(
            "⚠ Den korrigerte teksten er skrevet av modellen, ikke lest fra "
            "dokumentet. Tallvakten gjelder bare den rå OCR-teksten — "
            "kontroller beløp, datoer og identifikatorer mot originalen "
            "lenger ned før du bruker dem."
        )
    if data.get("advarsel"):
        deler.append(f"⚠ Advarsel fra serveren: {data['advarsel']}")
    if data.get("avvik"):
        avvik = data["avvik"]
        avvik_tekst = "; ".join(str(a) for a in avvik) if isinstance(avvik, list) else str(avvik)
        deler.append(f"⚠ Deklarerte avvik: {avvik_tekst}")
    return "\n".join(deler)


def _hent_feildetalj(respons) -> str:
    """Trekker ut den mest nyttige meldingen fra et feilet HTTP-svar — et
    JSON-feilfelt om det finnes, ellers rå kropp — slik at en feil aldri
    reduseres til bare en statuskode når serveren forklarte hvorfor."""
    try:
        kropp = respons.json()
    except ValueError:
        tekst = (respons.text or "").strip()
        return tekst[:500] if tekst else ""
    if isinstance(kropp, dict):
        for nokkel in ("feil", "melding", "error", "detail", "message"):
            if kropp.get(nokkel):
                return str(kropp[nokkel])
        return formater_json(kropp)
    return str(kropp)


def er_eksplisitt_feil(data) -> bool:
    return isinstance(data, dict) and data.get("ok") is False


class KonverteringsFeil(Exception):
    """Kastes når en fil ikke kan gjøres om til PDF for opplasting."""


def _bilde_til_pdf(sti: Path) -> Path:
    try:
        _sikre_pakke("PIL", "Pillow")
    except RuntimeError as exc:
        raise KonverteringsFeil(str(exc))
    from PIL import Image

    try:
        bilde = Image.open(sti)
        if bilde.mode in ("RGBA", "P", "LA"):
            bilde = bilde.convert("RGB")
        ut_sti = Path(tempfile.gettempdir()) / f"{sti.stem}_konvertert.pdf"
        bilde.save(ut_sti, "PDF", resolution=150.0)
        return ut_sti
    except KonverteringsFeil:
        raise
    except Exception as exc:
        raise KonverteringsFeil(f"Klarte ikke å lese denne bildefilen. Detaljer: {exc}")


def _tekst_til_pdf(sti: Path) -> Path:
    try:
        _sikre_pakke("fpdf", "fpdf2")
    except RuntimeError as exc:
        raise KonverteringsFeil(str(exc))
    from fpdf import FPDF

    try:
        tekst = sti.read_text(encoding="utf-8", errors="replace")
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)
        for linje in tekst.splitlines() or [""]:
            pdf.multi_cell(0, 6, linje, new_x="LMARGIN", new_y="NEXT")
        ut_sti = Path(tempfile.gettempdir()) / f"{sti.stem}_konvertert.pdf"
        pdf.output(str(ut_sti))
        return ut_sti
    except Exception as exc:
        raise KonverteringsFeil(f"Klarte ikke å konvertere denne tekstfilen. Detaljer: {exc}")


def _office_til_pdf(sti: Path, app_navn: str) -> Path:
    try:
        _sikre_pakke("win32com.client", "pywin32")
        import win32com.client
    except Exception as exc:
        raise KonverteringsFeil(
            f"Konvertering av {sti.suffix}-filer krever pywin32-pakken pluss "
            f"Microsoft Office installert på Windows. Detaljer: {exc}\n"
            f"Ble pywin32 nettopp installert og det fortsatt feiler, prøv:\n"
            f"    {sys.executable} -m pywin32_postinstall -install\n"
            "Omvei: åpne filen i Office og bruk Fil > Lagre som > PDF, og "
            "last opp den PDF-en i stedet."
        )

    ut_sti = Path(tempfile.gettempdir()) / f"{sti.stem}_konvertert.pdf"
    app = None
    try:
        app = win32com.client.DispatchEx(app_navn)
        if app_navn == "Word.Application":
            app.Visible = False
            dok = app.Documents.Open(str(sti))
            dok.SaveAs(str(ut_sti), FileFormat=17)  # wdFormatPDF
            dok.Close(False)
        elif app_navn == "Excel.Application":
            app.Visible = False
            arbeidsbok = app.Workbooks.Open(str(sti))
            arbeidsbok.ExportAsFixedFormat(0, str(ut_sti))  # 0 = xlTypePDF
            arbeidsbok.Close(False)
        elif app_navn == "PowerPoint.Application":
            presentasjon = app.Presentations.Open(str(sti), WithWindow=False)
            presentasjon.SaveAs(str(ut_sti), 32)  # 32 = ppSaveAsPDF
            presentasjon.Close()
    except Exception as exc:
        raise KonverteringsFeil(
            f"Klarte ikke å konvertere denne {sti.suffix}-filen med {app_navn}. "
            "Sjekk at det tilhørende Office-programmet er installert og at "
            f"ingen dialog blokkerer det i bakgrunnen. Detaljer: {exc}"
        )
    finally:
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass

    if not ut_sti.exists():
        raise KonverteringsFeil(
            f"{app_navn} produserte ingen PDF for denne {sti.suffix}-filen."
        )
    return ut_sti


def forbered_pdf(sti: Path) -> tuple[Path, bool]:
    """Returnerer (pdf_sti, er_midlertidig). Konverterer ikke-PDF til PDF."""
    endelse = sti.suffix.lower()

    if endelse == ".pdf":
        return sti, False
    if endelse in BILDE_ENDELSER:
        return _bilde_til_pdf(sti), True
    if endelse in TEKST_ENDELSER:
        return _tekst_til_pdf(sti), True
    if endelse in OFFICE_APPER:
        return _office_til_pdf(sti, OFFICE_APPER[endelse]), True

    raise KonverteringsFeil(
        f"«{endelse or 'denne filen'}» er ikke en støttet filtype. "
        "Støttet: PDF, bilder (jpg/png/bmp/tif/gif/webp), tekst (.txt) og "
        "Word/Excel/PowerPoint (krever Office installert)."
    )


# ==========================================================================
# HTTP-laget — helt uavhengig av GUI-et, så det kan gjenbrukes fra
# kommandolinje eller automatiserte tester uten å dra inn tkinter.
# ==========================================================================
class ApiKlient:
    """Tynn klient mot dokument-API-et. Sender X-API-Key-headeren på alle
    kall når en nøkkel er satt (serveren krever den hvis den er startet
    med miljøvariabelen API_NOKKEL, jf. R38)."""

    def __init__(self, base_url: str = "", api_nokkel: str = ""):
        self.base_url = base_url
        self.api_nokkel = api_nokkel

    def _hoder(self) -> dict:
        return {"X-API-Key": self.api_nokkel} if self.api_nokkel else {}

    def _post(self, endepunkt: str, *, filer=None, felter=None,
              tidsavbrudd=TIDSAVBRUDD_LANG):
        respons = requests.post(
            self.base_url + endepunkt, files=filer, data=felter,
            headers=self._hoder(), timeout=tidsavbrudd,
        )
        respons.raise_for_status()
        return respons.json()

    def _get(self, endepunkt: str, *, tidsavbrudd=TIDSAVBRUDD_KORT):
        respons = requests.get(
            self.base_url + endepunkt, headers=self._hoder(), timeout=tidsavbrudd,
        )
        respons.raise_for_status()
        return respons.json()

    # -- endepunkter -------------------------------------------------------
    def spor_med_fil(self, pdf_sti: Path, sporsmal: str, korriger: bool = False):
        felter = {"sporsmal": sporsmal}
        if korriger:
            felter["korriger"] = "ja"
        with open(pdf_sti, "rb") as fil:
            return self._post(
                "/spor",
                filer={"fil": (pdf_sti.name, fil, "application/pdf")},
                felter=felter,
            )

    def spor_uten_fil(self, sporsmal: str, jobb_id: str = ""):
        # Uten fil ville `data=` alene sendt urlenkodet kropp — serverens
        # egne eksempler bruker alltid multipart (-F), så
        # files={felt: (None, verdi)} tvinger multipart uten noen faktisk fil.
        filer = {"sporsmal": (None, sporsmal)}
        if jobb_id:
            filer["jobb_id"] = (None, jobb_id)
        return self._post("/spor", filer=filer)

    def fyll_skjema(self, pdf_sti: Path, skjema_json: str,
                    skjema_motor: str = "modell"):
        """Går via /dokument. Det gamle /fyll_skjema ga de samme fakta i
        en annen form og er fjernet. MERK feltnavnet: malen heter
        «skjema_mal» her — i /dokument er «skjema» en ja/nei-bryter."""
        svar = self.dokument_samlet(pdf_sti, {
            "skjema_mal": skjema_json, "skjema_motor": skjema_motor,
            "felter": "nei", "tekst": "nei"})
        return self._pakk_ut(svar, "skjema")

    @staticmethod
    def _pakk_ut(svar: dict, del_: str) -> dict:
        """Løfter én del opp til toppnivå, slik de gamle endepunktene
        svarte. Fellesfeltene blir med, så visningskoden i fanene
        trenger ikke vite at veien er lagt om."""
        if not isinstance(svar, dict):
            return svar
        innhold = svar.get(del_)
        ut = {n: svar[n] for n in
              ("ok", "status", "filnavn", "tekst", "antall_tegn",
               "antall_sider", "strekkoder", "handskrift", "kvalitet",
               "varsler", "dokumentprofil", "fra_cache", "tid_sekunder",
               "kilde", "versjon") if n in svar}
        if isinstance(innhold, dict):
            ut.update(innhold)
        elif innhold is not None:
            ut[del_] = innhold
        return ut

    def analyser(self, pdf_sti: Path):
        """Det gamle /analyser: felter + datoer, deterministisk."""
        return self._pakk_ut(
            self.dokument_samlet(pdf_sti, {"felter": "ja"}), "felter")

    def uttrekk(self, pdf_sti: Path):
        """Det gamle /uttrekk: komplett strukturert JSON."""
        return self._pakk_ut(
            self.dokument_samlet(pdf_sti, {"struktur": "ja", "felter": "nei"}),
            "struktur")

    def send_fil(self, endepunkt: str, pdf_sti: Path):
        """Bare en fil inn. Brukes nå av /jobb; /analyser og /uttrekk har
        egne metoder som går via /dokument."""
        with open(pdf_sti, "rb") as fil:
            return self._post(
                endepunkt,
                filer={"fil": (pdf_sti.name, fil, "application/pdf")},
            )

    def dokument_samlet(self, pdf_sti: Path, felter: dict):
        """POST /dokument — ETT kall med brytere: felter/struktur/tekst/
        svar/skjema/korriger (+ sporsmal/skjema_mal ved behov)."""
        with open(pdf_sti, "rb") as fil:
            return self._post(
                "/dokument",
                filer={"fil": (pdf_sti.name, fil, "application/pdf")},
                felter=felter,
            )

    def dokument_operasjoner(self, pdf_sti: Path, operasjoner_json: str):
        """POST /dokument med det uniforme operasjoner-kontraktet: en
        JSON-liste av {type, …} → {ok, resultater:[…]}."""
        with open(pdf_sti, "rb") as fil:
            return self._post(
                "/dokument",
                filer={"fil": (pdf_sti.name, fil, "application/pdf")},
                felter={"operasjoner": operasjoner_json},
            )

    def jobb_status(self, jobb_id: str):
        return self._get(f"/jobb/{jobb_id}")

    def jobb_tekst(self, jobb_id: str):
        return self._get(f"/jobb/{jobb_id}/tekst", tidsavbrudd=60)

    def jobb_avbryt(self, jobb_id: str):
        return self._post(f"/jobb/{jobb_id}/avbryt", tidsavbrudd=TIDSAVBRUDD_KORT)

    def hjelp(self):
        return self._get("/hjelp")

    def openapi(self):
        return self._get("/openapi.json")


# --- utklippstavle --------------------------------------------------------
# Tk sine innebygde Ctrl+V/C/X/A-bindinger kan svikte avhengig av
# Tcl/Tk-bygg, tastaturoppsett eller fokus-særegenheter på Windows, så
# disse kobles opp eksplisitt i stedet for å stole på standardene.
def _lim_inn(rot, felt):
    try:
        utklipp = rot.clipboard_get()
    except tk.TclError:
        return "break"  # ingenting på utklippstavlen
    try:
        felt.delete("sel.first", "sel.last")
    except tk.TclError:
        pass  # ingenting var markert — helt greit
    felt.insert("insert", utklipp)
    return "break"


def _kopier_markering(rot, felt):
    # Text og Entry har ULIKT get()-API: Text.get(fra, til) tar indekser,
    # mens Entry.get() ikke tar argumenter i det hele tatt. Kalles den med
    # indekser, blir det en TypeError — som IKKE fanges av TclError, så
    # Ctrl+C/Ctrl+X krasjet på alle enlinjefelter (URL, nøkkel, spørsmål).
    try:
        if isinstance(felt, tk.Text):
            tekst = felt.get("sel.first", "sel.last")
        else:
            if not felt.selection_present():
                return "break"          # ingenting markert
            tekst = felt.get()[felt.index("sel.first"):felt.index("sel.last")]
    except tk.TclError:
        return "break"  # ingenting markert
    rot.clipboard_clear()
    rot.clipboard_append(tekst)
    return "break"


def _klipp_ut(rot, felt):
    _kopier_markering(rot, felt)
    try:
        felt.delete("sel.first", "sel.last")
    except tk.TclError:
        pass
    return "break"


def _marker_alt(felt):
    if isinstance(felt, tk.Text):
        felt.tag_add("sel", "1.0", "end-1c")
    else:
        felt.selection_range(0, "end")
    return "break"


def bind_utklippstavle(rot, felt):
    felt.bind("<Control-v>", lambda e: _lim_inn(rot, felt))
    felt.bind("<Control-V>", lambda e: _lim_inn(rot, felt))
    felt.bind("<Control-c>", lambda e: _kopier_markering(rot, felt))
    felt.bind("<Control-C>", lambda e: _kopier_markering(rot, felt))
    felt.bind("<Control-x>", lambda e: _klipp_ut(rot, felt))
    felt.bind("<Control-X>", lambda e: _klipp_ut(rot, felt))
    felt.bind("<Control-a>", lambda e: _marker_alt(felt))
    felt.bind("<Control-A>", lambda e: _marker_alt(felt))

    # Høyreklikk-meny som reserve i tilfelle Ctrl+V aldri når frem til
    # feltet (f.eks. fanget opp av annen programvare).
    meny = tk.Menu(
        felt, tearoff=0, bg=BG_KNAPP, fg=FG_TEKST,
        activebackground=AKSENT, activeforeground="white", bd=0,
    )
    meny.add_command(label="Klipp ut", command=lambda: _klipp_ut(rot, felt))
    meny.add_command(label="Kopier", command=lambda: _kopier_markering(rot, felt))
    meny.add_command(label="Lim inn", command=lambda: _lim_inn(rot, felt))
    meny.add_separator()
    meny.add_command(label="Marker alt", command=lambda: _marker_alt(felt))
    felt.bind("<Button-3>", lambda e: meny.tk_popup(e.x_root, e.y_root))


# --- temabaserte widget-byggere -------------------------------------------
def tema_rammefelt(forelder, tekst):
    return tk.LabelFrame(
        forelder, text=tekst, bg=BG_PANEL, fg=FG_DEMPET, bd=1,
        relief="solid", highlightbackground=KANTLINJE,
    )


def tema_innfelt(forelder, tekstvariabel, **ekstra):
    valg = dict(
        textvariable=tekstvariabel, font=("Segoe UI", 10),
        bg=BG_INNDATA, fg=FG_TEKST, insertbackground=FG_TEKST, relief="flat",
        highlightthickness=1, highlightbackground=KANTLINJE, highlightcolor=AKSENT,
    )
    valg.update(ekstra)
    return tk.Entry(forelder, **valg)


def tema_tekstfelt(forelder, **valg):
    felt = scrolledtext.ScrolledText(
        forelder, bg=BG_INNDATA, fg=FG_TEKST, insertbackground=FG_TEKST, relief="flat",
        highlightthickness=1, highlightbackground=KANTLINJE, highlightcolor=AKSENT, **valg,
    )
    try:
        felt.vbar.configure(bg=BG_KNAPP, activebackground=BG_KNAPP_AKTIV, troughcolor=BG_PANEL)
    except (tk.TclError, AttributeError):
        pass  # kun kosmetikk — ikke alle plattformer/bygg eksponerer dette likt
    return felt


def tema_knapp(forelder, tekst, kommando, **ekstra):
    valg = dict(
        bg=BG_KNAPP, fg=FG_TEKST, activebackground=BG_KNAPP_AKTIV, activeforeground=FG_TEKST,
        disabledforeground=FG_DEMPET, relief="flat", highlightthickness=0, padx=10, pady=4,
    )
    valg.update(ekstra)
    return tk.Button(forelder, text=tekst, command=kommando, **valg)


def primaerknapp(forelder, tekst, kommando):
    return tk.Button(
        forelder, text=tekst, command=kommando, bg=AKSENT, fg="white",
        activebackground=AKSENT_AKTIV, activeforeground="white",
        font=("Segoe UI", 11, "bold"), relief="flat", highlightthickness=0, pady=8,
    )


# --- animert fremdriftsindikator ------------------------------------------
class AnimertFremdrift:
    """En liten canvas-tegnet kloss som sveiper over på nøyaktig
    ANIM_SVEIP_SEKUNDER og tilbake på like lang tid — styrt av klokken
    (time.perf_counter), ikke stegtelling, så bevegelsen holder seg jevn
    uansett maskinhastighet."""

    def __init__(self, forelder, rot):
        self.rot = rot
        self.canvas = tk.Canvas(
            forelder, height=8, bg=FREMDRIFT_BG, highlightthickness=1,
            highlightbackground=FREMDRIFT_KANT,
        )
        self.kloss = self.canvas.create_rectangle(0, 0, 0, 8, fill=FREMDRIFT_KLOSS, width=0)
        self._jobb = None
        self._kjorer = False
        self._retning = 1
        self._starttid = 0.0

    def pack(self, **valg):
        self.canvas.pack(**valg)

    def start(self):
        self._kjorer = True
        self._retning = 1
        self._starttid = time.perf_counter()
        self._steg()

    def _steg(self):
        if not self._kjorer:
            return
        bredde = self.canvas.winfo_width()
        if bredde <= 1:
            self._jobb = self.rot.after(ANIM_BILDE_MS, self._steg)
            return
        kloss_bredde = max(24, int(bredde * ANIM_KLOSS_BREDDE_ANDEL))
        bane = max(0, bredde - kloss_bredde)
        gaatt = time.perf_counter() - self._starttid
        andel = min(gaatt / ANIM_SVEIP_SEKUNDER, 1.0)
        x0 = bane * andel if self._retning == 1 else bane * (1 - andel)
        self.canvas.coords(self.kloss, x0, 0, x0 + kloss_bredde, 8)
        if andel >= 1.0:
            self._retning *= -1
            self._starttid = time.perf_counter()
        self._jobb = self.rot.after(ANIM_BILDE_MS, self._steg)

    def stopp(self):
        self._kjorer = False
        if self._jobb is not None:
            self.rot.after_cancel(self._jobb)
            self._jobb = None
        self.canvas.coords(self.kloss, 0, 0, 0, 8)


# --- gjenbrukbart svarpanel ------------------------------------------------
class SvarPanel:
    """Samler statuslinjen, varigheten, fremdriftsindikatoren,
    advarselsbanneret og resultatboksen som viser utfallet av ett
    API-kall. Deles av alle fanene så hvert endepunkts resultat ser ut og
    oppfører seg likt."""

    def __init__(self, forelder, rot, etikett="Resultat"):
        self.rot = rot
        self.siste_data = None

        statusrad = tk.Frame(forelder, bg=BG_HOVED)
        statusrad.pack(fill="x", padx=12)
        self.status_var = tk.StringVar(value="Klar")
        tk.Label(statusrad, textvariable=self.status_var, fg=FG_DEMPET, bg=BG_HOVED, anchor="w").pack(
            side="left", fill="x", expand=True
        )
        self.varighet_var = tk.StringVar(value="")
        tk.Label(statusrad, textvariable=self.varighet_var, fg=FG_DEMPET, bg=BG_HOVED, anchor="e").pack(
            side="right"
        )

        self.fremdrift = AnimertFremdrift(forelder, rot)
        self.fremdrift.pack(fill="x", padx=12, pady=(2, 8))

        svarramme = tema_rammefelt(forelder, etikett)
        svarramme.pack(fill="both", expand=True, padx=12, pady=6)

        self.advarsel_var = tk.StringVar(value="")
        self.advarsel_etikett = tk.Label(
            svarramme, textvariable=self.advarsel_var, fg=ADVARSEL_FG, bg=ADVARSEL_BG,
            anchor="w", wraplength=560, justify="left",
        )
        # pakkes (vises) bare når det faktisk finnes en advarsel

        self.svartekst = tema_tekstfelt(svarramme, wrap="word", font=("Segoe UI", 11), height=10)
        self.svartekst.pack(fill="both", expand=True, padx=8, pady=8)
        self.svartekst.config(state="disabled")

        knapperad = tk.Frame(forelder, bg=BG_HOVED)
        knapperad.pack(fill="x", padx=12, pady=(0, 12))
        self.vis_tekst_knapp = tema_knapp(knapperad, "Vis utlest tekst", self._vis_utlest_tekst)
        self.vis_tekst_knapp.config(state="disabled")
        self.vis_tekst_knapp.pack(side="right", padx=(8, 0))
        tema_knapp(knapperad, "Kopier", self.kopier_resultat).pack(side="right")

    def nullstill(self, statustekst="Sender ..."):
        self.status_var.set(statustekst)
        self.varighet_var.set("")
        self.sett_advarsel("")
        self.sett_svar("")
        self.siste_data = None
        self.vis_tekst_knapp.config(state="disabled")
        self.fremdrift.start()

    def sett_svar(self, tekst: str):
        self.svartekst.config(state="normal")
        self.svartekst.delete("1.0", "end")
        self.svartekst.insert("1.0", tekst)
        self.svartekst.config(state="disabled")

    def sett_advarsel(self, tekst: str):
        if tekst:
            self.advarsel_var.set(tekst)
            self.advarsel_etikett.pack(fill="x", padx=8, pady=(8, 0), before=self.svartekst)
        else:
            self.advarsel_var.set("")
            self.advarsel_etikett.pack_forget()

    def merk_data(self, data):
        self.siste_data = data if isinstance(data, dict) else {}
        har_tekst = bool(self.siste_data.get("tekst"))
        self.vis_tekst_knapp.config(state="normal" if har_tekst else "disabled")

    def _vis_utlest_tekst(self):
        if not self.siste_data:
            return
        tekst = self.siste_data.get("tekst") or ""
        antall_tegn = self.siste_data.get("antall_tegn", len(tekst))

        vindu = tk.Toplevel(self.rot)
        vindu.title("Utlest tekst")
        vindu.geometry("560x480")
        vindu.configure(bg=BG_HOVED)

        tk.Label(vindu, text=f"Antall tegn: {antall_tegn}", fg=FG_DEMPET, bg=BG_HOVED, anchor="w").pack(
            fill="x", padx=10, pady=(10, 0)
        )

        boks = tema_tekstfelt(vindu, wrap="word", font=("Segoe UI", 10))
        boks.pack(fill="both", expand=True, padx=10, pady=10)
        boks.insert("1.0", tekst or "(ingen tekst ble returnert)")
        boks.config(state="disabled")

    def kopier_resultat(self):
        tekst = self.svartekst.get("1.0", "end").strip()
        if not tekst:
            return
        self.rot.clipboard_clear()
        self.rot.clipboard_append(tekst)
        self.status_var.set("Kopiert til utklippstavlen")


# ==========================================================================
# Kontrollpanel — start/stopp av tjenestene på DENNE maskinen + live
# ressursgrafer (GPU / VRAM / CPU / RAM). Gjenbruker oppstart\-mappens
# skjulte startere (_skjult.vbs), så tjenester startet her oppfører seg
# identisk med start_alt.bat: ingen vinduer, logg i data\logger\.
# ==========================================================================
PROSJEKT_ROT = Path(__file__).resolve().parent.parent
OPPSTART_MAPPE = PROSJEKT_ROT / "oppstart"
LOGG_MAPPE = PROSJEKT_ROT / "data" / "logger"
SKJULT_VBS = OPPSTART_MAPPE / "_skjult.vbs"

# Vindusløse barneprosesser (netstat/taskkill/nvidia-smi/wscript) — uten
# dette blinker et svart konsollvindu for hvert kall.
_UTEN_VINDU = getattr(subprocess, "CREATE_NO_WINDOW", 0)

KONTROLL_STATUS_S = 3.0    # sekunder mellom tjenestesjekker
RESSURS_PULS_S = 1.0       # sekunder mellom ressursmålinger

KONTROLL_TJENESTER = [
    {
        "key": "api", "navn": "Dokument-API", "farge": CYAN, "port": 8600,
        "sjekk_url": "http://127.0.0.1:8600/hjelp",
        "aapne_url": "http://127.0.0.1:8600/dokumentasjon",
        # VAKTHUNDEN, ikke API-et direkte. Kontrollpanelet er den ENESTE
        # veien inn for brukeren, så alt som skal være oppe må startes
        # herfra — ellers kjører serveren uovervåket akkurat når det
        # betyr mest. Vakthunden starter API-et, helsesjekker /hjelp, og
        # skriver EXITKODEN når det dør. Uten den ga to døgn med krasj
        # null informasjon å feilsøke på.
        "bat": "start_api_med_vakthund.bat", "logg": "oppstart_api.log",
        # Prosessen som må dø FØRST når tjenesten stoppes: dreper vi bare
        # porten, ser vakthunden en død server og starter den på nytt —
        # og «Stopp» ser ut til å ikke virke.
        "vokter": "vakthund.py",
        "beskrivelse": "OCR + Borealis  ·  :8600  ·  overvåket",
        "starter_frist": 240,   # Borealis-lasting tar tid
    },
    {
        "key": "prefect", "navn": "Prefect", "farge": BLAA, "port": 4200,
        "sjekk_url": "http://127.0.0.1:4200/api/health",
        "aapne_url": "http://127.0.0.1:4200",
        "bat": "start_prefect.bat", "logg": "oppstart_prefect.log",
        "beskrivelse": "Treningsflyt  ·  :4200",
        "starter_frist": 240,   # kan bygge venv på nytt første gang
    },
    {
        "key": "label_studio", "navn": "Label Studio", "farge": ROSA, "port": 8080,
        "sjekk_url": "http://127.0.0.1:8080/",
        "aapne_url": "http://127.0.0.1:8080",
        "bat": "start_label_studio.bat", "logg": "oppstart_label_studio.log",
        "beskrivelse": "Korrektur/annotering  ·  :8080",
        "starter_frist": 120,
    },
    {
        "key": "tunnel", "navn": "Tunnel", "farge": ORANSJE, "port": None,
        "sjekk_url": None, "aapne_url": None,
        "bat": "start_tunnel.bat", "logg": "oppstart_tunnel.log",
        "beskrivelse": "Offentlig lenke (cloudflared)",
        "starter_frist": 60,
    },
]

_TUNNEL_LENKE_MONSTER = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def _bland(farge: str, mot: str, andel: float) -> str:
    """Blander `farge` mot `mot` (0=ren farge, 1=helt `mot`) — gir mørke
    fyllvarianter til grafene uten alfakanal (tk.Canvas mangler den)."""
    f = [int(farge[i:i + 2], 16) for i in (1, 3, 5)]
    m = [int(mot[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(
        round(fv + (mv - fv) * andel) for fv, mv in zip(f, m))


# --- ressursmåling (uten nye avhengigheter) --------------------------------
# psutil brukes hvis den finnes; ellers Windows-API direkte via ctypes.
try:
    import psutil  # type: ignore
except ImportError:
    psutil = None


class _FILETIME(ctypes.Structure):
    _fields_ = [("lav", ctypes.c_uint32), ("hoy", ctypes.c_uint32)]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


def _filetime_tall(ft: _FILETIME) -> int:
    return (ft.hoy << 32) | ft.lav


class RessursMaaler:
    """Leser CPU-, RAM-, GPU- og VRAM-bruk. GPU/VRAM via nvidia-smi (følger
    NVIDIA-driveren); CPU/RAM via psutil eller Windows-API. Alle kall er
    trygge å kjøre i bakgrunnstråd og returnerer None når kilden mangler."""

    def __init__(self):
        self._forrige_cpu = None  # (idle, kernel+user) fra GetSystemTimes
        self.nvidia_ok = shutil.which("nvidia-smi") is not None
        if psutil is not None:
            try:
                psutil.cpu_percent(interval=None)  # prim: første kall gir alltid 0.0
            except Exception:
                pass

    def cpu_prosent(self):
        if psutil is not None:
            try:
                return psutil.cpu_percent(interval=None)
            except Exception:
                return None
        try:
            idle, kjerne, bruker = _FILETIME(), _FILETIME(), _FILETIME()
            if not ctypes.windll.kernel32.GetSystemTimes(
                    ctypes.byref(idle), ctypes.byref(kjerne), ctypes.byref(bruker)):
                return None
            i, t = _filetime_tall(idle), _filetime_tall(kjerne) + _filetime_tall(bruker)
            if self._forrige_cpu is None:
                self._forrige_cpu = (i, t)
                return None  # første måling har ingen delta ennå
            di, dt = i - self._forrige_cpu[0], t - self._forrige_cpu[1]
            self._forrige_cpu = (i, t)
            if dt <= 0:
                return None
            return max(0.0, min(100.0, 100.0 * (1.0 - di / dt)))
        except Exception:
            return None

    def ram(self):
        """→ (prosent, brukt_gb, totalt_gb) eller None."""
        if psutil is not None:
            try:
                m = psutil.virtual_memory()
                return (m.percent, (m.total - m.available) / 1024 ** 3,
                        m.total / 1024 ** 3)
            except Exception:
                return None
        try:
            status = _MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return (float(status.dwMemoryLoad),
                    (status.ullTotalPhys - status.ullAvailPhys) / 1024 ** 3,
                    status.ullTotalPhys / 1024 ** 3)
        except Exception:
            return None

    def gpu(self):
        """→ (gpu_prosent, vram_brukt_mb, vram_totalt_mb) eller None."""
        if not self.nvidia_ok:
            return None
        try:
            resultat = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=utilization.gpu,memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=4,
                creationflags=_UTEN_VINDU,
            )
            if resultat.returncode != 0:
                return None
            deler = resultat.stdout.strip().splitlines()[0].split(",")
            return (float(deler[0]), float(deler[1]), float(deler[2]))
        except Exception:
            return None


class MiniGraf:
    """Liten rullende kurve (siste ~2 min) tegnet rett på en tk.Canvas —
    ingen tunge plotteavhengigheter. Nyeste verdi ytterst til høyre."""

    HOYDE = 72

    def __init__(self, forelder, tittel, farge):
        self.farge = farge
        self.fyll = _bland(farge, BG_INNDATA, 0.80)
        self.verdier = collections.deque(maxlen=120)

        self.ramme = tk.Frame(
            forelder, bg=BG_PANEL, highlightthickness=1,
            highlightbackground=KANTLINJE,
        )
        hode = tk.Frame(self.ramme, bg=BG_PANEL)
        hode.pack(fill="x", padx=8, pady=(6, 0))
        tk.Label(hode, text=tittel, bg=BG_PANEL, fg=FG_DEMPET,
                 font=("Segoe UI", 9)).pack(side="left")
        self.verdi_var = tk.StringVar(value="—")
        tk.Label(hode, textvariable=self.verdi_var, bg=BG_PANEL, fg=farge,
                 font=("Segoe UI", 11, "bold")).pack(side="right")

        self.canvas = tk.Canvas(self.ramme, height=self.HOYDE, bg=BG_INNDATA,
                                highlightthickness=0)
        self.canvas.pack(fill="x", padx=8, pady=(2, 8))
        self.canvas.bind("<Configure>", lambda _e: self._tegn())

    def grid(self, **valg):
        self.ramme.grid(**valg)

    def legg_til(self, prosent: float, tekst: str):
        self.verdier.append(max(0.0, min(100.0, prosent)))
        self.verdi_var.set(tekst)
        self._tegn()

    def sett_utilgjengelig(self, tekst: str):
        self.verdi_var.set(tekst)

    def _tegn(self):
        c = self.canvas
        c.delete("all")
        bredde, hoyde = c.winfo_width(), c.winfo_height()
        if bredde <= 1 or not self.verdier:
            return
        for prosent in (25, 50, 75):
            y = hoyde - (prosent / 100.0) * hoyde
            c.create_line(0, y, bredde, y, fill=KANTLINJE, dash=(2, 4))
        steg = bredde / (self.verdier.maxlen - 1)
        antall = len(self.verdier)
        punkter = []
        for i, verdi in enumerate(self.verdier):
            x = bredde - (antall - 1 - i) * steg
            y = hoyde - (verdi / 100.0) * (hoyde - 4) - 2
            punkter.append((x, y))
        if len(punkter) >= 2:
            flate = [(punkter[0][0], hoyde)] + punkter + [(punkter[-1][0], hoyde)]
            c.create_polygon([k for p in flate for k in p],
                             fill=self.fyll, outline="")
            c.create_line([k for p in punkter for k in p],
                          fill=self.farge, width=2)
        else:
            x, y = punkter[0]
            c.create_oval(x - 2, y - 2, x + 2, y + 2, fill=self.farge, outline="")


class KontrollPanel:
    """Fanen som styrer alt: start/stopp per tjeneste (grønn = kjører,
    rød = stoppet, gul = starter/laster), «Start alt»/«Stopp alt», og
    live-grafer for GPU, VRAM, CPU og RAM. Tjenestesjekk og målinger går
    i bakgrunnstråder; all widget-oppdatering skjer på hovedtråden via
    rot.after (tk-regelen)."""

    STATUSTEKST = {
        "kjorer": ("●", GRONN, "Kjører"),
        "laster": ("●", GUL, "Kjører — laster"),
        "starter": ("●", GUL, "Starter ..."),
        "stopper": ("●", GUL, "Stopper ..."),
        "stoppet": ("●", ROD, "Stoppet"),
    }
    STOPPER_FRIST_S = 30  # så lenge overstyrer «Stopper ...» et utdatert «Kjører»

    def __init__(self, forelder, rot, app=None):
        self.rot = rot
        self.app = app          # for «Bruk i klienten» (fyller Server-URL)
        self._lukket = False
        self._vekk = threading.Event()      # settes for øyeblikkelig re-sjekk
        self._start_tid: dict[str, float] = {}
        self._stopp_tid: dict[str, float] = {}
        self._status: dict[str, str] = {t["key"]: "stoppet" for t in KONTROLL_TJENESTER}
        self._tunnel_lenke = ""
        self._tunnel_ok_lenke = ""          # siste lenke bekreftet nåbar
        self._tunnel_siste_forsok = 0.0
        self._maaler = RessursMaaler()
        self._kort: dict[str, dict] = {}

        self._bygg(forelder)
        threading.Thread(target=self._status_lokke, daemon=True).start()
        threading.Thread(target=self._ressurs_lokke, daemon=True).start()

    # ---------- oppbygging ----------
    def _bygg(self, forelder):
        pad = {"padx": 12, "pady": 6}

        # -- Start alt / Stopp alt --
        masterrad = tk.Frame(forelder, bg=BG_HOVED)
        masterrad.pack(fill="x", **pad)
        self.start_alt_knapp = tk.Button(
            masterrad, text="▶  START ALT", command=self._start_alt,
            bg=GRONN, fg="white", activebackground=GRONN_AKTIV,
            activeforeground="white", font=("Segoe UI", 12, "bold"),
            relief="flat", highlightthickness=0, pady=10,
        )
        self.start_alt_knapp.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.stopp_alt_knapp = tk.Button(
            masterrad, text="■  STOPP ALT", command=self._stopp_alt,
            bg=ROD, fg="white", activebackground=ROD_AKTIV,
            activeforeground="white", font=("Segoe UI", 12, "bold"),
            relief="flat", highlightthickness=0, pady=10,
        )
        self.stopp_alt_knapp.pack(side="left", fill="x", expand=True, padx=(6, 0))

        # -- tjenestekort --
        tjenesteramme = tema_rammefelt(forelder, "Tjenester på denne maskinen")
        tjenesteramme.pack(fill="x", **pad)
        for tjeneste in KONTROLL_TJENESTER:
            self._bygg_kort(tjenesteramme, tjeneste)
            if tjeneste["key"] == "tunnel":
                self._bygg_tunnel_lenke(tjenesteramme)

        # -- ressursgrafer --
        ressursramme = tema_rammefelt(forelder, "Ressursbruk (live, siste ~2 minutter)")
        ressursramme.pack(fill="both", expand=True, **pad)
        rutenett = tk.Frame(ressursramme, bg=BG_PANEL)
        rutenett.pack(fill="both", expand=True, padx=8, pady=8)
        rutenett.columnconfigure(0, weight=1, uniform="graf")
        rutenett.columnconfigure(1, weight=1, uniform="graf")

        self.graf_gpu = MiniGraf(rutenett, "GPU (skjermkort)", GRONN)
        self.graf_gpu.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=(0, 4))
        self.graf_vram = MiniGraf(rutenett, "GPU-minne (VRAM)", ORANSJE)
        self.graf_vram.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=(0, 4))
        self.graf_cpu = MiniGraf(rutenett, "Prosessor (CPU)", BLAA)
        self.graf_cpu.grid(row=1, column=0, sticky="nsew", padx=(0, 4), pady=(4, 0))
        self.graf_ram = MiniGraf(rutenett, "Minne (RAM)", LILLA)
        self.graf_ram.grid(row=1, column=1, sticky="nsew", padx=(4, 0), pady=(4, 0))

        # -- bunnlinje: disk + forklaring --
        self.bunn_var = tk.StringVar(value="")
        tk.Label(forelder, textvariable=self.bunn_var, fg=FG_DEMPET,
                 bg=BG_HOVED, anchor="w").pack(fill="x", padx=12, pady=(0, 8))

    def _bygg_kort(self, forelder, tjeneste):
        rad = tk.Frame(forelder, bg=BG_PANEL)
        rad.pack(fill="x", padx=8, pady=3)

        stripe = tk.Frame(rad, bg=tjeneste["farge"], width=5)
        stripe.pack(side="left", fill="y")

        dot = tk.Label(rad, text="●", font=("Segoe UI", 14), fg=ROD, bg=BG_PANEL)
        dot.pack(side="left", padx=(8, 4))

        tekstboks = tk.Frame(rad, bg=BG_PANEL)
        tekstboks.pack(side="left", fill="x", expand=True)
        tk.Label(tekstboks, text=tjeneste["navn"], font=("Segoe UI", 11, "bold"),
                 fg=tjeneste["farge"], bg=BG_PANEL, anchor="w").pack(fill="x")
        status_var = tk.StringVar(value="Stoppet — " + tjeneste["beskrivelse"])
        tk.Label(tekstboks, textvariable=status_var, fg=FG_DEMPET, bg=BG_PANEL,
                 anchor="w", font=("Segoe UI", 9)).pack(fill="x")

        # EKSTRAKNAPPEN FÅR SIN EGEN, RESERVERTE PLASS (R177).
        #
        # Da Label Studio fikk en femte knapp, ble den raden bredere enn
        # de andre — og siden knapperaden er høyrestilt, skjøv den de
        # fire faste knappene mot venstre. Kolonnene sluttet å stå under
        # hverandre, og et panel der like knapper ikke ligger på linje
        # ser ustelt ut selv når alt virker.
        #
        # Plassen reserveres på ALLE rader, tom hos dem som ikke bruker
        # den. `pack_propagate(False)` er det som holder bredden fast —
        # uten den krymper en tom ramme til null, og vi er tilbake til
        # skjevheten.
        ekstra = tk.Frame(rad, bg=BG_PANEL, width=EKSTRAKNAPP_BREDDE)
        ekstra.pack(side="right", fill="y", padx=(0, 6), pady=4)
        ekstra.pack_propagate(False)

        knapper = tk.Frame(rad, bg=BG_PANEL)
        knapper.pack(side="right", padx=(4, 0), pady=4)
        start_knapp = tk.Button(
            knapper, text="Start", command=lambda t=tjeneste: self._start_tjeneste(t),
            bg=GRONN, fg="white", activebackground=GRONN_AKTIV,
            activeforeground="white", relief="flat", highlightthickness=0,
            padx=12, pady=3, font=("Segoe UI", 9, "bold"),
            disabledforeground=_bland("#ffffff", BG_PANEL, 0.6),
        )
        start_knapp.pack(side="left", padx=(0, 4))
        stopp_knapp = tk.Button(
            knapper, text="Stopp", command=lambda t=tjeneste: self._stopp_tjeneste(t),
            bg=ROD, fg="white", activebackground=ROD_AKTIV,
            activeforeground="white", relief="flat", highlightthickness=0,
            padx=12, pady=3, font=("Segoe UI", 9, "bold"),
            disabledforeground=_bland("#ffffff", BG_PANEL, 0.6),
        )
        stopp_knapp.pack(side="left", padx=(0, 4))
        aapne_knapp = tema_knapp(
            knapper, "Åpne", lambda t=tjeneste: self._aapne_tjeneste(t))
        aapne_knapp.pack(side="left", padx=(0, 4))
        logg_knapp = tema_knapp(
            knapper, "Logg", lambda t=tjeneste: self._aapne_logg(t))
        logg_knapp.pack(side="left")

        # Label Studio har egne brukerkontoer med passord — og et glemt
        # passord er den eneste feilen her som IKKE er et driftsproblem,
        # men et menneske som står låst ute. Knappen hører derfor hjemme
        # ved siden av tjenesten, ikke i et skript ingen finner (R176).
        #
        # Den bor i den reserverte plassen ytterst til høyre, ikke i
        # knapperaden: den gjør noe annet enn de fire — de styrer
        # TJENESTEN, denne gjelder en BRUKER — og avstanden sier det uten
        # at noe må forklares (R177).
        if tjeneste["key"] == "label_studio":
            tema_knapp(ekstra, "Passord",
                       self._nullstill_ls_passord).pack(fill="both",
                                                        expand=True)

        self._kort[tjeneste["key"]] = {
            "dot": dot, "status_var": status_var, "rad": rad,
            "start": start_knapp, "stopp": stopp_knapp, "aapne": aapne_knapp,
        }

    def _nullstill_ls_passord(self):
        """Åpner passordnullstilling for en Label Studio-bruker.

        PASSORDET GÅR ALDRI GJENNOM DENNE PROSESSEN. Panelet gjør bare
        HVEM-delen: leser brukerlista fra basen og lar deg velge. Selve
        HEMMELIGHETEN skrives inn i et eget konsollvindu, rett til Label
        Studios egen `reset_password` som spør med `getpass`.

        Det er et bevisst skille. Et passordfelt her ville lagt
        hemmeligheten i denne prosessens minne, i Tkinters
        strengvariabler og potensielt i en feilmelding — og GUI-et er
        nettopp den delen som logger mest. Konsollveien har ingen av
        delene: verdien går fra tastaturet rett inn i Django-hasheren,
        aldri via kommandolinja (der den ville havnet i skallhistorikk
        og i prosesslista for enhver som kjører `tasklist`)."""
        import subprocess
        import tkinter.messagebox as mb
        import tkinter.simpledialog as sd

        skript = PROSJEKT_ROT / "skript" / "nullstill_ls_passord.py"
        if not skript.is_file():
            mb.showerror("Mangler skript",
                         f"Fant ikke {skript}")
            return

        brukere = self._ls_brukere()
        if brukere is None:
            return
        if not brukere:
            mb.showwarning(
                "Ingen brukere",
                "Fant ingen brukere i Label Studio-basen.\n\n"
                "Er Label Studio startet minst én gang fra denne mappa?")
            return

        if len(brukere) == 1:
            bruker = brukere[0]
        else:
            bruker = sd.askstring(
                "Nullstill passord",
                "Hvilken bruker?\n\n" + "\n".join(f"  · {b}" for b in brukere),
                initialvalue=brukere[0], parent=self.rot)
            if not bruker:
                return
            bruker = bruker.strip()
            if bruker not in brukere:
                mb.showerror("Ukjent bruker",
                             f"«{bruker}» finnes ikke i basen.")
                return

        # Eget konsollvindu: der, og BARE der, skrives passordet.
        try:
            subprocess.Popen(
                [str(PROSJEKT_ROT / ".pyruntime" / "python.exe"),
                 str(skript), bruker],
                cwd=str(PROSJEKT_ROT),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        except OSError as exc:
            mb.showerror("Kunne ikke starte",
                         f"{type(exc).__name__}: {exc}")
            return
        mb.showinfo(
            "Skriv det nye passordet i konsollvinduet",
            f"Bruker: {bruker}\n\n"
            "Et konsollvindu er åpnet. Skriv det nye passordet der — "
            "det vises ikke mens du skriver, og passerer aldri gjennom "
            "kontrollpanelet.\n\n"
            "Får du «database is locked»: stopp Label Studio først, "
            "prøv igjen, og start den etterpå.")

    def _ls_brukere(self):
        """Brukerlista, lest direkte fra basen (kun lesing).

        Returnerer None hvis noe gikk galt — da er feilen alt vist."""
        import sqlite3
        import tkinter.messagebox as mb

        base = (PROSJEKT_ROT / "data" / "label-studio"
                / "label_studio.sqlite3")
        if not base.is_file():
            mb.showwarning(
                "Fant ingen base",
                f"Fant ingen Label Studio-database her:\n{base}\n\n"
                "Start Label Studio én gang først.")
            return None
        try:
            kobling = sqlite3.connect(f"file:{base}?mode=ro", uri=True)
            try:
                rader = kobling.execute(
                    "SELECT email FROM htx_user WHERE is_active = 1 "
                    "ORDER BY id").fetchall()
            finally:
                kobling.close()
        except sqlite3.Error as exc:
            mb.showerror("Kunne ikke lese basen",
                         f"{type(exc).__name__}: {exc}")
            return None
        return [r[0] for r in rader if r[0]]

    def _bygg_tunnel_lenke(self, forelder):
        """Den offentlige lenken vises RETT UNDER tunnelkortet, i et felt
        du kan markere og kopiere. Adressen er ny for hver tunnelomstart,
        så den skal være lett å hente ut — ikke noe man må lete etter i
        loggen. Raden er skjult til lenken finnes og er bekreftet nåbar."""
        self.tunnel_ramme = tk.Frame(forelder, bg=BG_INNDATA,
                                     highlightthickness=1,
                                     highlightbackground=ORANSJE)
        self._tunnel_rad_vist = False
        # pakkes/skjules av _vis_alle — ingen tom ramme før tunnelen er oppe
        tk.Label(self.tunnel_ramme,
                 text="Offentlig lenke til API-et — bruk denne som "
                      "Server-URL utenfra:",
                 fg=ORANSJE, bg=BG_INNDATA, anchor="w",
                 font=("Segoe UI", 9, "bold")).pack(fill="x", padx=8, pady=(6, 0))

        rad = tk.Frame(self.tunnel_ramme, bg=BG_INNDATA)
        rad.pack(fill="x", padx=8, pady=(3, 7))
        self.tunnel_lenke_var = tk.StringVar(value="")
        felt = tk.Entry(rad, textvariable=self.tunnel_lenke_var,
                        state="readonly", readonlybackground=BG_PANEL,
                        fg=FG_TEKST, font=("Consolas", 10), relief="flat",
                        highlightthickness=1, highlightbackground=KANTLINJE)
        felt.pack(side="left", fill="x", expand=True, ipady=3)
        bind_utklippstavle(self.rot, felt)      # markér + Ctrl+C virker òg
        self.tunnel_kopi_knapp = tema_knapp(rad, "Kopier", self._kopier_tunnel)
        self.tunnel_kopi_knapp.pack(side="left", padx=(6, 0))
        tema_knapp(rad, "Bruk i klienten",
                   self._bruk_tunnel_i_klienten).pack(side="left", padx=(4, 0))

        # Ærlig merking: er adressen bekreftet nåbar herfra, eller venter
        # den fortsatt på DNS? Cloudflare sier selv «it may take some time
        # to be reachable», og lenken kan virke utenfra før den gjør det her.
        self.tunnel_status_var = tk.StringVar(value="")
        self.tunnel_status_etikett = tk.Label(
            self.tunnel_ramme, textvariable=self.tunnel_status_var,
            fg=FG_DEMPET, bg=BG_INNDATA, anchor="w",
            font=("Segoe UI", 8), wraplength=880, justify="left")
        self.tunnel_status_etikett.pack(fill="x", padx=8, pady=(0, 6))

    def _kopier_tunnel(self):
        lenke = self.tunnel_lenke_var.get().strip()
        if not lenke:
            return
        self.rot.clipboard_clear()
        self.rot.clipboard_append(lenke)
        # Kvittering i selve knappen: en dialog for hver kopiering ville
        # vært i veien, men uten tilbakemelding vet man ikke om det virket
        self.tunnel_kopi_knapp.config(text="Kopiert ✓")
        self.rot.after(1500, lambda: self._tilbakestill_kopiknapp())

    def _tilbakestill_kopiknapp(self):
        try:
            self.tunnel_kopi_knapp.config(text="Kopier")
        except tk.TclError:
            pass    # vinduet er lukket

    def _bruk_tunnel_i_klienten(self):
        """Setter lenken som Server-URL i de andre fanene — da slipper du
        å kopiere den over for hånd hver gang tunnelen starter på nytt."""
        lenke = self.tunnel_lenke_var.get().strip()
        if not lenke or self.app is None:
            return
        try:
            self.app.url_var.set(lenke)
        except Exception:
            return
        messagebox.showinfo(
            "Server-URL oppdatert",
            f"Fanene bruker nå tunnelen:\n{lenke}\n\n"
            "Adressen huskes til neste gang. Merk at den endrer seg hver "
            "gang tunnelen startes på nytt.")

    # ---------- handlinger ----------
    def _start_tjeneste(self, tjeneste):
        bat = OPPSTART_MAPPE / tjeneste["bat"]
        if not bat.is_file() or not SKJULT_VBS.is_file():
            messagebox.showwarning(
                "Kun på servermaskinen",
                "Fant ikke oppstart-mappen — start/stopp virker bare på "
                "maskinen der nav-mappa (tjenestene) faktisk ligger.",
            )
            return
        LOGG_MAPPE.mkdir(parents=True, exist_ok=True)
        logg = LOGG_MAPPE / tjeneste["logg"]
        miljo = {**os.environ, "NAV_SKJULT": "1"}
        try:
            subprocess.Popen(
                ["wscript", "//nologo", str(SKJULT_VBS), str(bat), str(logg)],
                cwd=str(PROSJEKT_ROT), env=miljo, creationflags=_UTEN_VINDU,
            )
        except OSError as exc:
            messagebox.showerror("Feil", f"Klarte ikke å starte {tjeneste['navn']}: {exc}")
            return
        self._start_tid[tjeneste["key"]] = time.monotonic()
        self._stopp_tid.pop(tjeneste["key"], None)
        self._status[tjeneste["key"]] = "starter"
        self._vis_kort(tjeneste["key"], "starter", tjeneste["beskrivelse"])
        self._vekk.set()

    def _stopp_tjeneste(self, tjeneste, stille: bool = False):
        # Samme vakt som start: på en ren KLIENTMASKIN (uten oppstart\)
        # kan port 8080/4200 tilhøre en helt urelatert app — da skal vi
        # aldri taskkill-e den.
        if not SKJULT_VBS.is_file():
            if not stille:
                messagebox.showwarning(
                    "Kun på servermaskinen",
                    "Fant ikke oppstart-mappen — start/stopp virker bare på "
                    "maskinen der nav-mappa (tjenestene) faktisk ligger.",
                )
            return
        self._start_tid.pop(tjeneste["key"], None)
        self._stopp_tid[tjeneste["key"]] = time.monotonic()
        self._vis_kort(tjeneste["key"], "stopper", "")

        def arbeider():
            # VOKTEREN FØRST. Vakthunden holder ingen port og har ingen
            # vindustittel, så verken _pids_paa_port eller det gamle
            # stopp_alt.bat traff den. Drepte vi bare API-et, ville
            # vakthunden se en død server og starte den igjen — og
            # brukeren konkluderte med at «Stopp» ikke virker, eller at
            # API-et «starter av seg selv».
            for pid in self._pids_for_python(tjeneste.get("vokter")):
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, creationflags=_UTEN_VINDU)

            pids = set()
            if tjeneste["port"]:
                pids |= self._pids_paa_port(tjeneste["port"])
            # Fanger også «Starter ...»-fasen, der porten ikke er bundet
            # ennå: drep den skjulte cmd-en som kjører tjenestens .bat.
            pids |= self._pids_for_bat(tjeneste["bat"])
            for pid in pids:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, creationflags=_UTEN_VINDU)
            if tjeneste["key"] == "tunnel":
                subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"],
                               capture_output=True, creationflags=_UTEN_VINDU)
            self._vekk.set()

        threading.Thread(target=arbeider, daemon=True).start()

    def _start_alt(self):
        if not SKJULT_VBS.is_file():
            messagebox.showwarning(
                "Kun på servermaskinen",
                "Fant ikke oppstart-mappen — start/stopp virker bare på "
                "maskinen der nav-mappa (tjenestene) faktisk ligger.")
            return
        for tjeneste in KONTROLL_TJENESTER:
            if tjeneste["key"] == "tunnel":
                continue  # offentlig eksponering skal være et bevisst valg
            if self._status.get(tjeneste["key"]) == "stoppet":
                self._start_tjeneste(tjeneste)

    def _stopp_alt(self):
        if not SKJULT_VBS.is_file():
            messagebox.showwarning(
                "Kun på servermaskinen",
                "Fant ikke oppstart-mappen — start/stopp virker bare på "
                "maskinen der nav-mappa (tjenestene) faktisk ligger.")
            return
        for tjeneste in KONTROLL_TJENESTER:
            if self._status.get(tjeneste["key"]) != "stoppet":
                self._stopp_tjeneste(tjeneste, stille=True)

    def _aapne_tjeneste(self, tjeneste):
        if tjeneste["key"] == "tunnel":
            if self._tunnel_lenke:
                webbrowser.open(self._tunnel_lenke)
            return
        webbrowser.open(tjeneste["aapne_url"])

    def _aapne_logg(self, tjeneste):
        logg = LOGG_MAPPE / tjeneste["logg"]
        if logg.is_file():
            os.startfile(str(logg))  # noqa: S606 — åpner i standard tekstprogram
        else:
            messagebox.showinfo("Ingen logg ennå",
                                f"Loggfilen finnes ikke ennå:\n{logg}")

    @staticmethod
    def _pids_paa_port(port: int) -> set[int]:
        """PID-ene som LYTTER på porten — samme logikk som stopp_alt.bat."""
        try:
            resultat = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True,
                timeout=10, creationflags=_UTEN_VINDU,
            )
        except Exception:
            return set()
        pids = set()
        for linje in resultat.stdout.splitlines():
            if f":{port} " in linje and "LISTENING" in linje:
                deler = linje.split()
                if deler and deler[-1].isdigit():
                    pids.add(int(deler[-1]))
        return pids

    @staticmethod
    def _pids_for_bat(bat_navn: str) -> set[int]:
        """cmd-prosessene som kjører tjenestens .bat (den skjulte verten).
        Trengs for å stoppe en tjeneste i «Starter ...»-fasen, der porten
        ikke er bundet ennå og _pids_paa_port derfor finner ingenting."""
        try:
            resultat = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process -Filter "
                 f"\"Name='cmd.exe' AND CommandLine LIKE '%{bat_navn}%'\" "
                 "| Select-Object -ExpandProperty ProcessId"],
                capture_output=True, text=True, timeout=15,
                creationflags=_UTEN_VINDU,
            )
            return {int(del_) for del_ in resultat.stdout.split()
                    if del_.strip().isdigit()}
        except Exception:
            return set()

    @staticmethod
    def _pids_for_python(skript: str | None) -> set[int]:
        """Python-prosessene som kjører et bestemt skript.

        Vakthunden er en `python.exe` uten lyttende port og uten
        vindustittel — de to kjennetegnene alt annet stopp-maskineri
        leter etter. Uten dette overlever den «Stopp alt» og starter
        API-et igjen ~20 sekunder senere."""
        if not skript:
            return set()
        try:
            resultat = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process -Filter "
                 "\"Name LIKE '%python%'\" | Where-Object "
                 f"{{ $_.CommandLine -like '*{skript}*' }} "
                 "| Select-Object -ExpandProperty ProcessId"],
                capture_output=True, text=True, timeout=15,
                creationflags=_UTEN_VINDU,
            )
            return {int(del_) for del_ in resultat.stdout.split()
                    if del_.strip().isdigit()}
        except Exception:
            return set()

    # ---------- statuspolling (bakgrunnstråd) ----------
    def _status_lokke(self):
        while not self._lukket:
            resultater = {}
            for tjeneste in KONTROLL_TJENESTER:
                resultater[tjeneste["key"]] = self._sjekk_tjeneste(tjeneste)
            self._trygg_after(self._vis_alle, resultater)
            self._vekk.wait(timeout=KONTROLL_STATUS_S)
            self._vekk.clear()

    def _sjekk_tjeneste(self, tjeneste):
        """→ (status, detalj) målt utenfra: 'kjorer'/'laster'/'stoppet'."""
        if tjeneste["key"] == "tunnel":
            if self._prosess_finnes("cloudflared.exe"):
                # Lenken vises SÅ SNART cloudflared har skrevet den — med
                # ærlig merking av om den er bekreftet nåbar herfra. Å
                # holde den skjult til bekreftelsen kom, var feil: tunnelen
                # er til bruk UTENFRA, og en maskin som ikke får slått opp
                # trycloudflare.com i DNS ville aldri fått se sin egen
                # lenke — selv om den virker utmerket for alle andre.
                lenke = self._finn_tunnel_lenke()
                self._tunnel_lenke = lenke
                if lenke and lenke != self._tunnel_ok_lenke:
                    naa = time.monotonic()
                    if naa - self._tunnel_siste_forsok > 15:
                        self._tunnel_siste_forsok = naa
                        try:
                            svar = requests.get(lenke + "/hjelp", timeout=4)
                            if svar.status_code < 500:  # 530 = død tunnel
                                self._tunnel_ok_lenke = lenke
                        except requests.exceptions.RequestException:
                            pass
                # selve adressen står i lenkeraden rett under kortet, der
                # den kan markeres og kopieres — ikke som statustekst her
                return ("kjorer", "offentlig lenke klar — se under" if lenke
                        else "venter på offentlig lenke ...")
            self._tunnel_lenke = ""
            return ("stoppet", tjeneste["beskrivelse"])
        try:
            respons = requests.get(tjeneste["sjekk_url"], timeout=1.5)
            if tjeneste["key"] == "api":
                try:
                    borealis = respons.json().get("borealis", "")
                except ValueError:
                    borealis = ""
                if borealis == "laster":
                    return ("laster", "Borealis: laster ...")
                if borealis == "feil":
                    # Terminal tilstand (ingen retry i serveren) — ikke lov
                    # en lasting som aldri kommer: /analyser virker, /spor ikke.
                    return ("kjorer",
                            "Borealis FEILET (se logg) — /spor er nede, /analyser virker")
                return ("kjorer", tjeneste["beskrivelse"])
            return ("kjorer", tjeneste["beskrivelse"])
        except requests.exceptions.RequestException:
            return ("stoppet", tjeneste["beskrivelse"])

    @staticmethod
    def _prosess_finnes(navn: str) -> bool:
        try:
            resultat = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {navn}", "/NH"],
                capture_output=True, text=True, timeout=10,
                creationflags=_UTEN_VINDU,
            )
            return navn.lower() in resultat.stdout.lower()
        except Exception:
            return False

    @staticmethod
    def _finn_tunnel_lenke() -> str:
        """Lenken som hører til DENNE tunnelkjøringen. Loggen samler opp
        flere kjøringer, så vi leser bare det som står etter siste
        «Requesting new quick Tunnel» — ellers ville en gammel, død
        adresse fra forrige kjøring blitt vist mens den nye lastes."""
        logg = LOGG_MAPPE / "oppstart_tunnel.log"
        try:
            innhold = logg.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        start = innhold.rfind("Requesting new quick Tunnel")
        treff = _TUNNEL_LENKE_MONSTER.findall(
            innhold[start:] if start >= 0 else innhold)
        return treff[-1] if treff else ""

    def _vis_alle(self, resultater: dict):
        if self._lukket:
            return
        for tjeneste in KONTROLL_TJENESTER:
            nokkel = tjeneste["key"]
            status, detalj = resultater[nokkel]
            # nystartet men porten svarer ikke ennå → vis gult «Starter ...»
            if status == "stoppet" and nokkel in self._start_tid:
                if time.monotonic() - self._start_tid[nokkel] < tjeneste["starter_frist"]:
                    status = "starter"
                    detalj = f"se loggen ved behov: data\\logger\\{tjeneste['logg']}"
                else:
                    del self._start_tid[nokkel]  # ga opp — vis ærlig rødt
            elif status in ("kjorer", "laster"):
                self._start_tid.pop(nokkel, None)
            # nystoppet men et (mulig utdatert) svar sier fortsatt «kjører»
            # → hold gult «Stopper ...» til porten faktisk er død
            if status == "stoppet":
                self._stopp_tid.pop(nokkel, None)
            elif status in ("kjorer", "laster") and nokkel in self._stopp_tid:
                if time.monotonic() - self._stopp_tid[nokkel] < self.STOPPER_FRIST_S:
                    status, detalj = "stopper", ""
                else:
                    del self._stopp_tid[nokkel]  # ga ikke etter — vis ærlig grønt
            self._status[nokkel] = status
            self._vis_kort(nokkel, status, detalj)
        self._vis_tunnel_lenke()

    def _vis_tunnel_lenke(self):
        """Viser lenkeraden så snart tunnelen har en bekreftet nåbar
        adresse — og skjuler den igjen når tunnelen stoppes, så det aldri
        står en død adresse igjen som noen kan komme til å bruke."""
        ramme = getattr(self, "tunnel_ramme", None)
        if ramme is None:
            return
        # EGEN tilstandsflagg, ikke winfo_ismapped(): står brukeren i en
        # annen fane, er hele kontrollpanelet umappet, og ismapped() ville
        # løyet om at raden er borte — da ble den aldri skjult når
        # tunnelen stoppet, bare tømt.
        try:
            lenke = self._tunnel_lenke
            if lenke:
                if self.tunnel_lenke_var.get() != lenke:
                    self.tunnel_lenke_var.set(lenke)
                if lenke == self._tunnel_ok_lenke:
                    self.tunnel_status_var.set(
                        "Bekreftet nåbar — API-et svarer gjennom tunnelen.")
                    self.tunnel_status_etikett.config(fg=GRONN)
                else:
                    self.tunnel_status_var.set(
                        "Ikke bekreftet herfra ennå (DNS bruker gjerne et "
                        "minutt). Lenken kan alt virke for andre — prøv den "
                        "gjerne. Kontrollpanelet fortsetter å sjekke.")
                    self.tunnel_status_etikett.config(fg=ORANSJE)
                if not self._tunnel_rad_vist:
                    # «after» binder raden til tunnelkortet, ikke til
                    # bunnen av rammen — den blir stående rett under
                    # kortet selv om flere tjenester kommer til senere
                    kort = self._kort.get("tunnel") or {}
                    if kort.get("rad") is not None:
                        ramme.pack(fill="x", padx=8, pady=(0, 6),
                                   after=kort["rad"])
                    else:
                        ramme.pack(fill="x", padx=8, pady=(0, 6))
                    self._tunnel_rad_vist = True
            else:
                self.tunnel_lenke_var.set("")
                if self._tunnel_rad_vist:
                    ramme.pack_forget()
                    self._tunnel_rad_vist = False
        except tk.TclError:
            pass  # vinduet er i ferd med å lukkes

    def _vis_kort(self, nokkel: str, status: str, detalj: str):
        try:
            kort = self._kort[nokkel]
            _tegn, farge, tekst = self.STATUSTEKST[status]
            kort["dot"].config(fg=farge)
            kort["status_var"].set(f"{tekst} — {detalj}" if detalj else tekst)
            kort["start"].config(state="disabled" if status != "stoppet" else "normal")
            kort["stopp"].config(
                state="normal" if status in ("kjorer", "laster", "starter") else "disabled")
            kan_aapne = status in ("kjorer", "laster")
            if nokkel == "tunnel":
                kan_aapne = kan_aapne and bool(self._tunnel_lenke)
            kort["aapne"].config(state="normal" if kan_aapne else "disabled")
        except tk.TclError:
            pass  # vinduet er i ferd med å lukkes

    # ---------- ressursgrafer (bakgrunnstråd) ----------
    def _ressurs_lokke(self):
        while not self._lukket:
            cpu = self._maaler.cpu_prosent()
            ram = self._maaler.ram()
            gpu = self._maaler.gpu()
            try:
                disk = shutil.disk_usage(PROSJEKT_ROT)
            except OSError:
                disk = None
            self._trygg_after(self._vis_ressurser, cpu, ram, gpu, disk)
            time.sleep(RESSURS_PULS_S)

    def _vis_ressurser(self, cpu, ram, gpu, disk):
        if self._lukket:
            return
        try:
            if cpu is not None:
                self.graf_cpu.legg_til(cpu, f"{cpu:.0f} %")
            if ram is not None:
                prosent, brukt_gb, totalt_gb = ram
                self.graf_ram.legg_til(
                    prosent, f"{prosent:.0f} %  ({brukt_gb:.1f}/{totalt_gb:.0f} GB)")
            if gpu is not None:
                gpu_prosent, vram_brukt, vram_totalt = gpu
                self.graf_gpu.legg_til(gpu_prosent, f"{gpu_prosent:.0f} %")
                if vram_totalt > 0:
                    self.graf_vram.legg_til(
                        100.0 * vram_brukt / vram_totalt,
                        f"{vram_brukt / 1024:.1f}/{vram_totalt / 1024:.1f} GB")
            elif not self._maaler.nvidia_ok:
                self.graf_gpu.sett_utilgjengelig("ingen NVIDIA")
                self.graf_vram.sett_utilgjengelig("ingen NVIDIA")
            deler = []
            if disk is not None:
                deler.append(f"Disk {PROSJEKT_ROT.drive} {disk.free / 1024**3:.0f} GB ledig")
            deler.append("Kontrollpanelet styrer tjenestene på denne maskinen")
            self.bunn_var.set("   ·   ".join(deler))
        except tk.TclError:
            pass  # vinduet er i ferd med å lukkes

    def _trygg_after(self, fn, *argumenter):
        try:
            self.rot.after(0, fn, *argumenter)
        except (tk.TclError, RuntimeError):
            pass  # vinduet er lukket — trådene avslutter via self._lukket

    def lukk(self):
        self._lukket = True
        self._vekk.set()


# ==========================================================================
# Flytskjema — interaktivt, farget kart over hele prosjektet fra dokument
# inn til selvforbedringssløyfen. Tegnet rett på tk.Canvas (ingen nye
# avhengigheter, helt portabelt). Klikk en boks for forklaring, eller
# «Spill av» for en guidet gjennomgang steg for steg.
# ==========================================================================
FLYT_NODER = [
    # (nokkel, tittel, undertekst, farge, x, y, bredde, hoyde)
    ("inn", "1 · Dokument inn", "PDF · bilde · Word · Excel · CSV · tekst", CYAN, 30, 14, 310, 58),
    ("lese", "2 · Lesing", "tekstlag · OCR · Doc-UFCN + norhand for håndskrift", BLAA, 30, 98, 310, 58),
    ("uttrekk", "3 · Deterministisk uttrekk", "datoer · beløp · ID (mod 11) · tallvakt", GRONN, 30, 182, 310, 58),
    ("borealis", "4 · Borealis (LLM)", "spørsmål/svar på GPU — tallvakt-beskyttet", LILLA, 30, 266, 310, 58),
    ("svar", "5 · Ærlig svar ut", "advarsel · avvik · kilde · versjon", GRONN, 30, 350, 310, 58),
    ("labelstudio", "6 · Label Studio", "menneske retter dårlig lesing", ROSA, 430, 98, 280, 58),
    ("trening", "7 · Finjustering", "norhand trenes på korreksjonene", ORANSJE, 430, 210, 280, 58),
    ("port", "8 · Kvalitetsport", "CER + konfidensintervall → fire utfall", GUL, 430, 322, 280, 58),
]

FLYT_DETALJER = {
    "inn": "UiPath, GUI-klienten eller ren HTTP laster opp dokumentet. Endepunkter: "
           "/dokument (SAMLET: ett kall med brytere for felter/struktur/svar/skjema/"
           "korriger — dokumentet leses én gang), /dokument/operasjoner (samme, som "
           "liste), /spor (spørsmål), /sladd (fjern identifikatorer fra teksten), "
           "/forhandssjekk, /innsyn og /jobb for store skanninger i bakgrunnen. "
           "Bilder og Office-filer konverteres til PDF; CSV og ren tekst leses "
           "direkte.",
    "lese": "Har PDF-en tekstlag, leses det direkte (raskt og eksakt). Skannede sider "
            "går til regionbasert OCR: EasyOCR/RapidOCR for trykt tekst, norhand "
            "(TrOCR, Nasjonalbiblioteket) for norsk håndskrift, pyzbar for strekkoder. "
            "Håndskriftstunge/usikre sider får et ANDREPASS: Doc-UFCN (NorHand, "
            "Teklia) segmenterer tekstlinjene på CPU, norhand leser dem — og passet "
            "med høyest målt konfidens vinner. Målt gevinst på løkkeskrift: 22 → 88 %.",
    "uttrekk": "delt/tekstuttrekk.py finner datoer, beløp og identifikatorer "
               "deterministisk, med kontrollsiffer-validering (mod 11). Tallvakten "
               "sjekker hvert tall på TRE siffer eller mer mot dokumentet — kortere "
               "tall (sidetall, «to vedlegg») ville gitt så mange falske treff at "
               "vakten ble ubrukelig. Ber du ikke om svar fra modellen, går "
               "resultatet RETT ut herfra — uten LLM (den grønne snarveien).",
    "borealis": "Spørsmål besvares av Borealis 4B (GGUF via llama.cpp på CUDA). "
                "Modellen får OCR-teksten + spørsmålet; tallvakt og kodevalidering "
                "stopper hallusinerte tall før de når svaret. Et rent spørsmål "
                "uten fil hopper hit direkte (den lilla stiplede snarveien) og "
                "merkes ærlig med uten_dokument.",
    "svar": "Svaret deklarerer ærlig hva som skjedde: advarsel, avvik, uten_dokument, "
            "kilde og versjonsstempel (api/prompt/modell). Ble noe holdt tilbake av "
            "profil=sammendrag, står det navngitt i «utelatt» — ingenting forsvinner "
            "i stillhet. Alle kall logges i tilgangsloggen med rate-begrensning.",
    "labelstudio": "Leses et dokument dårlig (lav konfidens, håndskrift eller tomt), "
                   "sendes det automatisk til Label Studio — med OCR-boksene "
                   "FORHÅNDSMERKET på bildet og teksten forhåndsutfylt, så den "
                   "ansatte bare retter feilene. Samme dokument sendes aldri to "
                   "ganger. Etter at rettingen er hentet ut og arkivert, SLETTES "
                   "oppgaven i Label Studio — råteksten blir ikke liggende igjen. "
                   "Best-effort: API-et virker fint uten Label Studio.",
    "trening": "skript/finjuster.py trener norhand videre på de menneskerettede "
               "eksemplene (eksportert fra Label Studio, med bildene kopiert inn i "
               "arkivet så oppbevaringsfristen på gjennomgangskøen ikke river dem "
               "bort). Kjøres av den planlagte Windows-oppgaven "
               "NAV-Trening-ukentlig — serveren stoppes først så GPU-en er ledig. "
               "(Prefect-flyten finnes som et alternativ, men er ikke det som "
               "kjører til vanlig.)",
    "port": "valider_modell.py måler CER for kandidatmodellen mot dagens modell på et "
            "kontrollsett, med 95 %-konfidensintervall — to punkttall kan ikke "
            "skilles på et lite sett. FIRE utfall: bedre → promoteres til "
            "modeller/norhand · dårligere → rulles tilbake · ikke_skillbar → "
            "ingenting skjer, live blir stående · ingen_live_modell. "
            "MERK: kontrollsettet data/validering/norhand.json finnes ikke ennå, "
            "så porten har aldri kjørt mot en ekte modell. Den feiler LUKKET — "
            "uten sett promoteres ingenting.",
    "_slutt": "Sløyfen er sluttet: den forbedrede modellen leser neste dokument bedre — "
              "og slik blir systemet gradvis skarpere helt av seg selv.",
}

FLYT_PILER = [
    # (fra, til, retning) — retning: "ned" eller "hoyre"
    ("inn", "lese", "ned"), ("lese", "uttrekk", "ned"),
    ("uttrekk", "borealis", "ned"), ("borealis", "svar", "ned"),
    ("lese", "labelstudio", "hoyre"),
    ("labelstudio", "trening", "ned"), ("trening", "port", "ned"),
]

FLYT_REKKEFOLGE = ["inn", "lese", "uttrekk", "borealis", "svar",
                   "labelstudio", "trening", "port"]
FLYT_STEG_MS = 2600  # per steg i avspillingen


class FlytskjemaPanel:
    """Interaktivt flytskjema over hele prosjektet. Alt kjører på
    hovedtråden (ren tegning + after-animasjon) — ingen tråder her."""

    def __init__(self, forelder, rot):
        self.rot = rot
        self._valgt = None
        self._anim_jobb = None
        self._anim_indeks = 0
        self._elementer = {}   # nokkel -> {"boks": id, "farge": ...}

        topp = tk.Frame(forelder, bg=BG_HOVED)
        topp.pack(fill="x", padx=12, pady=(8, 2))
        self.spill_knapp = tk.Button(
            topp, text="▶  Spill av flyten", command=self._spill_eller_stopp,
            bg=AKSENT, fg="white", activebackground=AKSENT_AKTIV,
            activeforeground="white", font=("Segoe UI", 10, "bold"),
            relief="flat", highlightthickness=0, padx=14, pady=5,
        )
        self.spill_knapp.pack(side="left")
        tk.Label(topp, text="… eller klikk på en boks for forklaring",
                 fg=FG_DEMPET, bg=BG_HOVED).pack(side="left", padx=10)

        self.canvas = tk.Canvas(forelder, width=730, height=444, bg=BG_HOVED,
                                highlightthickness=0)
        self.canvas.pack(padx=12, pady=(4, 2))

        detaljramme = tema_rammefelt(forelder, "Forklaring")
        detaljramme.pack(fill="both", expand=True, padx=12, pady=(4, 10))
        self.detalj_var = tk.StringVar(
            value="Slik virker hele prosjektet: dokument inn → lesing → uttrekk → "
                  "svar, pluss sløyfen til høyre som gjør modellen bedre over tid. "
                  "Klikk en boks, eller trykk «Spill av flyten».")
        tk.Label(detaljramme, textvariable=self.detalj_var, fg=FG_TEKST,
                 bg=BG_PANEL, anchor="nw", justify="left", wraplength=690,
                 font=("Segoe UI", 10)).pack(fill="both", expand=True, padx=10, pady=8)

        self._tegn()

    # ---------- tegning ----------
    @staticmethod
    def _rund_boks(canvas, x1, y1, x2, y2, radius, **valg):
        punkter = [
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        return canvas.create_polygon(punkter, smooth=True, **valg)

    def _tegn(self):
        c = self.canvas
        rekt = {}
        for nokkel, _t, _u, _f, x, y, b, h in FLYT_NODER:
            rekt[nokkel] = (x, y, x + b, y + h)

        # kolonneoverskrifter
        c.create_text(185, 6, text="DOKUMENTFLYT (hver forespørsel)",
                      fill=FG_DEMPET, font=("Segoe UI", 8, "bold"))
        c.create_text(570, 6, text="FORBEDRINGSSLØYFE (over tid)",
                      fill=FG_DEMPET, font=("Segoe UI", 8, "bold"))

        # piler foerst (bak boksene)
        for fra, til, retning in FLYT_PILER:
            x1a, y1a, x2a, y2a = rekt[fra]
            x1b, y1b, x2b, y2b = rekt[til]
            farge = dict((n[0], n[3]) for n in FLYT_NODER)[til]
            if retning == "ned":
                midt = (x1a + x2a) // 2
                c.create_line(midt, y2a, midt, y1b, fill=farge, width=3,
                              arrow=tk.LAST, arrowshape=(10, 12, 5))
            else:
                midty = (y1a + y2a) // 2
                c.create_line(x2a, midty, x1b, midty, fill=farge, width=3,
                              arrow=tk.LAST, arrowshape=(10, 12, 5))
                c.create_text((x2a + x1b) // 2, midty - 10, text="dårlig lesing",
                              fill=ROSA, font=("Segoe UI", 8, "italic"))

        # -- de tre alternative stiene (uten disse mangler ekte flyt) --
        # A) deterministisk: uten spørsmål hopper svaret OVER Borealis.
        # Etiketten navnga /analyser og /uttrekk — ruter som ble FJERNET
        # (R157). Et kart som peker på dører som ikke finnes, sender
        # neste integrator på leting etter noe som aldri var der.
        xu1, yu1, xu2, yu2 = rekt["uttrekk"]
        xs1, ys1, xs2, ys2 = rekt["svar"]
        midt_u, midt_s = (yu1 + yu2) // 2, (ys1 + ys2) // 2
        c.create_line(xu2, midt_u, 400, midt_u, 400, midt_s, xs2, midt_s,
                      fill=GRONN, width=2, arrow=tk.LAST, arrowshape=(10, 12, 5))
        c.create_text(409, (midt_u + midt_s) // 2, angle=90,
                      text="uten LLM: /dokument uten spørsmål · /sladd",
                      fill=GRONN, font=("Segoe UI", 8, "italic"))
        # B) rent spørsmål UTEN fil: rett fra inn til Borealis
        xi1, yi1, xi2, yi2 = rekt["inn"]
        xb1, yb1, xb2, yb2 = rekt["borealis"]
        midt_i, midt_b = (yi1 + yi2) // 2, (yb1 + yb2) // 2
        c.create_line(xi2, midt_i, 372, midt_i, 372, midt_b, xb2, midt_b,
                      fill=LILLA, width=2, dash=(5, 3),
                      arrow=tk.LAST, arrowshape=(10, 12, 5))
        c.create_text(363, (midt_i + midt_b) // 2 + 26, angle=90,
                      text="rent spørsmål (uten fil)",
                      fill=LILLA, font=("Segoe UI", 8, "italic"))
        # C) kvalitetsporten kan ogsaa FORKASTE: rull tilbake til trening
        x1p, y1p, x2p, y2p = rekt["port"]
        x1t, y1t, x2t, y2t = rekt["trening"]
        c.create_line(640, y1p, 640, y2t, fill=ROD, width=2, dash=(5, 3),
                      arrow=tk.LAST, arrowshape=(10, 12, 5))
        c.create_text(628, (y1p + y2t) // 2, anchor="e",
                      text="dårligere → rull tilbake",
                      fill=ROD, font=("Segoe UI", 8, "italic"))

        # tilbakesloeyfen: kvalitetsport → (rundt utsiden) → lesing
        x1l, y1l, x2l, y2l = rekt["lese"]
        midtp = (x1p + x2p) // 2
        self._sloyfe = c.create_line(
            midtp, y2p, midtp, 430, 14, 430, 14, (y1l + y2l) // 2,
            x1l, (y1l + y2l) // 2,
            fill=GRONN, width=2, dash=(6, 4), arrow=tk.LAST,
            arrowshape=(10, 12, 5), smooth=False)
        c.create_text(150, 418, text="bedre modell → neste dokument leses bedre",
                      fill=GRONN, font=("Segoe UI", 8, "italic"))

        # boksene
        for nokkel, tittel, under, farge, x, y, b, h in FLYT_NODER:
            fyll = _bland(farge, BG_INNDATA, 0.72)
            boks = self._rund_boks(c, x, y, x + b, y + h, 14,
                                   fill=fyll, outline=farge, width=2,
                                   tags=("node", nokkel))
            c.create_text(x + 14, y + h / 2 - 10, text=tittel, anchor="w",
                          fill="white", font=("Segoe UI", 10, "bold"),
                          tags=("node", nokkel))
            c.create_text(x + 14, y + h / 2 + 11, text=under, anchor="w",
                          fill=_bland("#ffffff", farge, 0.25),
                          font=("Segoe UI", 8), tags=("node", nokkel))
            self._elementer[nokkel] = {"boks": boks, "farge": farge}

        c.tag_bind("node", "<Button-1>", self._ved_klikk)
        c.tag_bind("node", "<Enter>", lambda _e: c.config(cursor="hand2"))
        c.tag_bind("node", "<Leave>", lambda _e: c.config(cursor=""))

    # ---------- interaksjon ----------
    def _ved_klikk(self, hendelse):
        self._stopp_avspilling()
        for tagg in self.canvas.gettags("current"):
            if tagg in self._elementer:
                self._velg(tagg)
                return

    def _velg(self, nokkel):
        for n, e in self._elementer.items():
            aktiv = n == nokkel
            self.canvas.itemconfig(
                e["boks"],
                width=4 if aktiv else 2,
                outline="white" if aktiv else e["farge"],
                fill=_bland(e["farge"], BG_INNDATA, 0.55 if aktiv else 0.72),
            )
        self._valgt = nokkel
        self.detalj_var.set(FLYT_DETALJER[nokkel])

    # ---------- avspilling ----------
    def _spill_eller_stopp(self):
        if self._anim_jobb is not None:
            self._stopp_avspilling()
            return
        self._anim_indeks = 0
        self.spill_knapp.config(text="■  Stopp", bg=ROD, activebackground=ROD_AKTIV)
        self._neste_steg()

    def _neste_steg(self):
        if self._anim_indeks < len(FLYT_REKKEFOLGE):
            self._velg(FLYT_REKKEFOLGE[self._anim_indeks])
            self._anim_indeks += 1
            self._anim_jobb = self.rot.after(FLYT_STEG_MS, self._neste_steg)
            return
        # siste steg: marker sløyfen tilbake
        self.canvas.itemconfig(self._sloyfe, width=4)
        self._velg("lese")
        self.detalj_var.set(FLYT_DETALJER["_slutt"])
        self._anim_jobb = self.rot.after(
            FLYT_STEG_MS, lambda: self._stopp_avspilling(behold_tekst=True))

    def _stopp_avspilling(self, behold_tekst=False):
        if self._anim_jobb is not None:
            self.rot.after_cancel(self._anim_jobb)
            self._anim_jobb = None
        try:
            self.canvas.itemconfig(self._sloyfe, width=2)
            self.spill_knapp.config(text="▶  Spill av flyten", bg=AKSENT,
                                    activebackground=AKSENT_AKTIV)
        except tk.TclError:
            pass
        if not behold_tekst and self._valgt:
            self.detalj_var.set(FLYT_DETALJER[self._valgt])


# ==========================================================================
# Trening — én knapp kjører hele treningsløkken (eksport → finjustering →
# kvalitetsport) med ekte fremdriftslinje, kravliste og telling av
# dokumenter (klare / venter på ansatt / trent gjennom livstiden).
# API-serveren stoppes automatisk (GPU-en må være ledig) og startes igjen.
# ==========================================================================
TRENING_FASER = {
    "eksport": ("1/3 — Eksport fra Label Studio", 0.02, 0.10),
    "trening": ("2/3 — Finjustering av norhand", 0.10, 0.85),
    "port": ("3/3 — Kvalitetsport (CER)", 0.85, 0.98),
}
TRENING_EPOKER = 3.0          # num_train_epochs i finjuster.py
TRENING_MIN_EKSEMPLER = 10    # MIN_EKSEMPLER i finjuster.py

TRENING_RESULTATER = {
    "promotert": ("Kandidaten var minst like god — PROMOTERT til live. "
                  "API-omstarten lastet den nye modellen.", GRONN),
    "avvist_daarligere": ("Kandidaten var dårligere — AVVIST i porten. "
                          "Live-modellen står urørt.", ROD),
    "ingen_data": ("Ingen annoterte korreksjoner i Label Studio — "
                   "ingenting å trene på ennå.", GUL),
    "for_faa": (f"For få eksempler (minimum {TRENING_MIN_EKSEMPLER}) — "
                "annoter flere i Label Studio først.", GUL),
    "ingen_valideringssett": ("Kandidat trent, men uten valideringssett "
                              "(data/validering/norhand.json) promoteres den "
                              "ikke automatisk.", GUL),
    "ukjent": ("Løpet stoppet uventet — se loggen under.", ROD),
    "avbrutt": ("Treningen ble avbrutt av deg.", GUL),
    "ingen_nye": ("Ingen nye korreksjoner siden forrige trening — modellen "
                  "er allerede oppdatert på alt.", GUL),
}


def _les_lokal_env() -> dict:
    """Leser oppstart\\lokal_env.bat (set \"K=V\"-linjer) OG .env i
    prosjektroten — gir GUI-en samme hemmeligheter som serveren
    (Label Studio-token, API_NOKKEL m.m.).

    .env leses FØRST, så lokal_env.bat kan overstyre den: launcheren er
    den som faktisk starter tjenestene. Uten .env her ville GUI-en blitt
    låst ute med 401 i det øyeblikket API_NOKKEL begynte å virke."""
    miljo = {}
    try:
        for linje in (PROSJEKT_ROT / ".env").read_text(
                encoding="utf-8", errors="replace").splitlines():
            linje = linje.strip()
            if not linje or linje.startswith("#") or "=" not in linje:
                continue
            navn, verdi = linje.split("=", 1)
            verdi = verdi.strip().strip('"').strip("'")
            if navn.strip() and verdi:
                miljo[navn.strip()] = verdi
    except OSError:
        pass
    try:
        for linje in (OPPSTART_MAPPE / "lokal_env.bat").read_text(
                encoding="ascii", errors="replace").splitlines():
            treff = re.match(r'\s*set\s+"([^=]+)=([^"]*)"', linje, re.IGNORECASE)
            if treff:
                miljo[treff.group(1)] = treff.group(2)
    except OSError:
        pass
    return miljo


class TreningPanel:
    """Treningsfanen. Statistikk hentes i bakgrunnstråd; selve løpet kjøres
    som subprocess (kjor_treningslop.py) med linjeparsing for fremdrift.
    All widget-oppdatering skjer på hovedtråden via rot.after."""

    def __init__(self, forelder, rot, kontroll: "KontrollPanel"):
        self.rot = rot
        self.kontroll = kontroll
        self._lukket = False
        self._vekk = threading.Event()
        self._prosess = None          # subprocess.Popen under kjøring
        self._api_var_oppe = False
        self._fase = None
        self._start_tid = None
        self._klokke_jobb = None

        self._bygg(forelder)
        threading.Thread(target=self._statistikk_lokke, daemon=True).start()

    # ---------- oppbygging ----------
    def _bygg(self, forelder):
        pad = {"padx": 12, "pady": 6}

        knapperad = tk.Frame(forelder, bg=BG_HOVED)
        knapperad.pack(fill="x", **pad)
        self.start_knapp = tk.Button(
            knapperad, text="▶  START TRENING", command=self._start_eller_avbryt,
            bg=LILLA, fg="white", activebackground=_bland(LILLA, "#000000", 0.2),
            activeforeground="white", font=("Segoe UI", 12, "bold"),
            relief="flat", highlightthickness=0, pady=10,
        )
        self.start_knapp.pack(side="left", fill="x", expand=True)
        self.hent_knapp = tk.Button(
            knapperad, text="⬇  Hent korreksjoner", command=self._hent_korreksjoner,
            bg=GRONN, fg="white", activebackground=GRONN_AKTIV,
            activeforeground="white", font=("Segoe UI", 10, "bold"),
            relief="flat", highlightthickness=0, padx=12, pady=10,
        )
        self.hent_knapp.pack(side="left", padx=(10, 0))
        tema_knapp(knapperad, "Annoter i Label Studio",
                   lambda: webbrowser.open("http://127.0.0.1:8080/projects/"
                                           + _les_lokal_env().get(
                                               "LABEL_STUDIO_OCR_PROSJEKT_ID", "1"))
                   ).pack(side="left", padx=(10, 0))
        tema_knapp(knapperad, "Oppdater", self._vekk.set).pack(side="left", padx=(8, 0))

        # -- fremdrift --
        fr = tk.Frame(forelder, bg=BG_HOVED)
        fr.pack(fill="x", padx=12)
        self.fase_var = tk.StringVar(value="Klar — treningen stopper API-et "
                                           "automatisk og starter det igjen etterpå.")
        tk.Label(fr, textvariable=self.fase_var, fg=FG_TEKST, bg=BG_HOVED,
                 anchor="w", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.tid_var = tk.StringVar(value="")
        tk.Label(fr, textvariable=self.tid_var, fg=FG_DEMPET, bg=BG_HOVED,
                 anchor="e").pack(side="right")
        self.fremdrift = tk.Canvas(forelder, height=14, bg=FREMDRIFT_BG,
                                   highlightthickness=1,
                                   highlightbackground=FREMDRIFT_KANT)
        self.fremdrift.pack(fill="x", padx=12, pady=(2, 6))
        self._fyllt = self.fremdrift.create_rectangle(0, 0, 0, 14, fill=LILLA, width=0)
        self._prosent_tekst = self.fremdrift.create_text(
            8, 7, anchor="w", text="", fill="white", font=("Segoe UI", 8, "bold"))

        # -- telling (det brukeren spurte om) --
        telleramme = tema_rammefelt(forelder, "Dokumenter i treningsløkka")
        telleramme.pack(fill="x", **pad)
        rute = tk.Frame(telleramme, bg=BG_PANEL)
        rute.pack(fill="x", padx=8, pady=8)
        for kol in range(4):
            rute.columnconfigure(kol, weight=1, uniform="telle")
        self.telle_vars = {}
        for kol, (nokkel, tittel, farge) in enumerate([
                ("venter", "Venter på ansatt\n(ikke annotert ennå)", GUL),
                ("klare", "Klare til henting\n(annotert av ansatt)", GRONN),
                ("klargjort", "Klargjort til trening\n(hentet, ikke trent)", ORANSJE),
                ("livstid", "Trent gjennom livstiden\n(unike dokumenter)", CYAN)]):
            boks = tk.Frame(rute, bg=BG_INNDATA, highlightthickness=1,
                            highlightbackground=KANTLINJE)
            boks.grid(row=0, column=kol, sticky="nsew",
                      padx=(0 if kol == 0 else 6, 0))
            var = tk.StringVar(value="—")
            tk.Label(boks, textvariable=var, fg=farge, bg=BG_INNDATA,
                     font=("Segoe UI", 22, "bold")).pack(pady=(8, 0))
            tk.Label(boks, text=tittel, fg=FG_DEMPET, bg=BG_INNDATA,
                     font=("Segoe UI", 8), justify="center").pack(pady=(0, 8))
            self.telle_vars[nokkel] = var
        self.siste_var = tk.StringVar(value="Ingen treningskjøringer ennå.")
        tk.Label(telleramme, textvariable=self.siste_var, fg=FG_DEMPET,
                 bg=BG_PANEL, anchor="w", wraplength=830).pack(
                     fill="x", padx=8, pady=(0, 8))
        # Vises BARE når norhand-vektene avviker fra sist kjente avtrykk —
        # dvs. basismodellen er byttet utenfra og arkivet venter på retrening.
        self.basis_advarsel = tk.Label(
            telleramme,
            text=("⚠ NY BASISMODELL oppdaget — korreksjonsarkivet er ikke "
                  "lært inn i den nye modellen ennå. Neste treningsløp "
                  "retrener automatisk på HELE arkivet (trykk START TRENING, "
                  "eller vent på den planlagte kjøringen)."),
            fg=GUL, bg=BG_PANEL, anchor="w", wraplength=830,
            font=("Segoe UI", 9, "bold"), justify="left")

        # -- krav --
        kravramme = tema_rammefelt(forelder, "Krav for å trene (sjekkes live)")
        kravramme.pack(fill="x", **pad)
        self.krav_rader = {}
        for nokkel, tekst in [
                ("ls", "Label Studio kjører og API-nøkkelen virker"),
                ("data", f"Nok annoterte korreksjoner (minst {TRENING_MIN_EKSEMPLER} totalt)"),
                ("gpu", "NVIDIA-GPU tilgjengelig (API-et stoppes automatisk for å frigjøre VRAM)"),
                ("modell", "Basismodellen norhand finnes (modeller/norhand)"),
                ("validering", "Valideringssett for auto-promotering (ellers manuell promotering)")]:
            rad = tk.Frame(kravramme, bg=BG_PANEL)
            rad.pack(fill="x", padx=8, pady=1)
            dot = tk.Label(rad, text="●", fg=FG_DEMPET, bg=BG_PANEL,
                           font=("Segoe UI", 11))
            dot.pack(side="left")
            var = tk.StringVar(value=tekst)
            tk.Label(rad, textvariable=var, fg=FG_TEKST, bg=BG_PANEL,
                     anchor="w", font=("Segoe UI", 9)).pack(
                         side="left", fill="x", expand=True, padx=(6, 0))
            self.krav_rader[nokkel] = (dot, var, tekst)

        # -- resultat + logg --
        self.resultat_var = tk.StringVar(value="")
        self.resultat_etikett = tk.Label(
            forelder, textvariable=self.resultat_var, fg="white", bg=BG_PANEL,
            anchor="w", wraplength=830, font=("Segoe UI", 10, "bold"),
            padx=10, pady=6)
        # pakkes først når et løp er ferdig

        loggramme = tema_rammefelt(forelder, "Logg fra treningsløpet (live)")
        loggramme.pack(fill="both", expand=True, **pad)
        self.logg = tema_tekstfelt(loggramme, wrap="none",
                                   font=("Consolas", 8), height=7)
        self.logg.pack(fill="both", expand=True, padx=8, pady=8)
        self.logg.config(state="disabled")

    # ---------- statistikk (bakgrunnstråd) ----------
    def _statistikk_lokke(self):
        while not self._lukket:
            stat = self._hent_statistikk()
            self._trygg_after(self._vis_statistikk, stat)
            self._vekk.wait(timeout=15.0)
            self._vekk.clear()

    def _hent_statistikk(self) -> dict:
        miljo = _les_lokal_env()
        nokkel = miljo.get("LABEL_STUDIO_API_KEY", "")
        prosjekt = miljo.get("LABEL_STUDIO_OCR_PROSJEKT_ID", "1")
        stat = {"ls_ok": False, "totalt": 0, "annotert_ids": set()}

        if nokkel:
            try:
                svar = requests.get(
                    f"http://127.0.0.1:8080/api/tasks?project={prosjekt}",
                    headers={"Authorization": f"Token {nokkel}"}, timeout=4)
                if svar.ok:
                    stat["ls_ok"] = True
                    oppgaver = svar.json().get("tasks", [])
                    stat["totalt"] = len(oppgaver)
                    stat["annotert_ids"] = {
                        o["id"] for o in oppgaver
                        if o.get("total_annotations", 0) > 0}
            except requests.exceptions.RequestException:
                pass

        # historikken leses først — den skiller TRENT fra bare KLARGJORT
        historikk_sti = (PROSJEKT_ROT / "data" / "finjustering"
                         / "treningshistorikk.json")
        stat["historikk"] = []
        try:
            if historikk_sti.is_file():
                stat["historikk"] = json.loads(
                    historikk_sti.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        siste_trening = 0.0
        from datetime import datetime as _dt
        for rad in stat["historikk"]:
            if isinstance(rad, dict) and rad.get("trent_paa", 0) > 0:
                try:
                    siste_trening = max(
                        siste_trening,
                        _dt.fromisoformat(rad["tidspunkt"]).timestamp())
                except (KeyError, ValueError, TypeError):
                    pass

        # klargjorte filer deles i TRENT (fantes ved siste fullførte
        # trening — finjusteringen leser alle filene) og KLARGJORT
        # (hentet i ettertid, venter på neste trening)
        trent, klargjort = set(), set()
        eksempler = 0
        for fil in (PROSJEKT_ROT / "data" / "finjustering").glob("trocr_*.json"):
            try:
                mtime = fil.stat().st_mtime
                for rad in json.loads(fil.read_text(encoding="utf-8")):
                    eksempler += 1
                    oid = rad.get("oppgave_id")
                    if oid is not None:
                        (trent if mtime <= siste_trening + 5
                         else klargjort).add(oid)
            except (OSError, ValueError):
                continue
        klargjort -= trent
        stat["trent_ids"] = trent
        stat["klargjort_ids"] = klargjort
        stat["eksempler"] = eksempler

        # basisbytte: live-vektene avviker fra sist kjente avtrykk →
        # korreksjonsarkivet venter på automatisk retrening (samme
        # avtrykksalgoritme som valider_modell.modell_avtrykk)
        stat["ny_basis"] = False
        try:
            import hashlib
            vekter = (PROSJEKT_ROT / "modeller" / "norhand"
                      / "model.safetensors")
            kjent = json.loads(
                (PROSJEKT_ROT / "data" / "finjustering" / "grunnmodell.json")
                .read_text(encoding="utf-8")).get("basis")
            h = hashlib.sha256()
            h.update(str(vekter.stat().st_size).encode())
            with open(vekter, "rb") as f:
                h.update(f.read(1024 * 1024))
            stat["ny_basis"] = bool(kjent) and h.hexdigest()[:16] != kjent
        except (OSError, ValueError):
            pass

        stat["gpu"] = self.kontroll._maaler.gpu()
        stat["gpu_finnes"] = self.kontroll._maaler.nvidia_ok
        stat["modell_ok"] = (PROSJEKT_ROT / "modeller" / "norhand"
                             / "config.json").is_file()
        stat["validering_ok"] = (PROSJEKT_ROT / "data" / "validering"
                                 / "norhand.json").is_file()
        return stat

    def _vis_statistikk(self, stat: dict):
        if self._lukket:
            return
        try:
            klare = (stat["annotert_ids"] - stat["trent_ids"]
                     - stat["klargjort_ids"])
            venter = stat["totalt"] - len(stat["annotert_ids"])
            self.telle_vars["venter"].set(str(max(0, venter)) if stat["ls_ok"] else "?")
            self.telle_vars["klare"].set(str(len(klare)) if stat["ls_ok"] else "?")
            self.telle_vars["klargjort"].set(str(len(stat["klargjort_ids"])))
            self.telle_vars["livstid"].set(str(len(stat["trent_ids"])))

            historikk = stat["historikk"]
            if historikk:
                siste = historikk[-1]
                self.siste_var.set(
                    f"Siste kjøring: {siste.get('tidspunkt', '?')} — resultat: "
                    f"{siste.get('resultat', '?')} ({siste.get('trent_paa', 0)} "
                    f"eksempler, {siste.get('varighet_s', 0):.0f} s). "
                    f"Totalt {len(historikk)} kjøringer gjennom livstiden.")
            else:
                self.siste_var.set("Ingen treningskjøringer ennå.")

            if stat.get("ny_basis"):
                self.basis_advarsel.pack(fill="x", padx=8, pady=(0, 8))
            else:
                self.basis_advarsel.pack_forget()

            annotert_totalt = len(stat["annotert_ids"] | stat["trent_ids"]
                                  | stat["klargjort_ids"])
            self._annotert_totalt = annotert_totalt
            self._sett_krav("ls", stat["ls_ok"],
                            detalj=None if stat["ls_ok"]
                            else "— start den fra Kontrollpanelet")
            self._sett_krav("data", annotert_totalt >= TRENING_MIN_EKSEMPLER,
                            detalj=f"— har {annotert_totalt}")
            gpu_detalj = None
            if stat["gpu"]:
                _p, brukt, totalt = stat["gpu"]
                gpu_detalj = f"— VRAM nå: {brukt/1024:.1f}/{totalt/1024:.1f} GB"
            self._sett_krav("gpu", stat["gpu_finnes"], detalj=gpu_detalj)
            self._sett_krav("modell", stat["modell_ok"])
            self._sett_krav("validering", stat["validering_ok"],
                            advarsel=True)
        except tk.TclError:
            pass

    def _sett_krav(self, nokkel, oppfylt, detalj=None, advarsel=False):
        dot, var, grunntekst = self.krav_rader[nokkel]
        dot.config(fg=GRONN if oppfylt else (GUL if advarsel else ROD))
        var.set(grunntekst + (f" {detalj}" if detalj else ""))

    # ---------- henting av korreksjoner (uten trening) ----------
    def _hent_korreksjoner(self):
        """Kjører KUN eksporten: henter det de ansatte har annotert og
        klargjør det for trening (inkrementelt — aldri duplikater).
        Trenger ikke GPU, så API-et får stå urørt."""
        if self._prosess is not None:
            return  # trening/henting pågår allerede
        self.hent_knapp.config(state="disabled")
        self.start_knapp.config(state="disabled")
        self.fase_var.set("Henter korreksjoner fra Label Studio ...")
        self._sett_logg("")
        miljo = {**os.environ, **_les_lokal_env(),
                 "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1"}

        def arbeider():
            try:
                self._prosess = subprocess.Popen(
                    [str(PROSJEKT_ROT / ".pyruntime" / "python.exe"), "-u",
                     str(PROSJEKT_ROT / "skript" / "eksporter_fra_label_studio.py")],
                    cwd=str(PROSJEKT_ROT), env=miljo,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=_UTEN_VINDU)
            except OSError as exc:
                self._prosess = None
                self._trygg_after(self._hent_ferdig,
                                  f"Klarte ikke å starte hentingen: {exc}")
                return
            nye = None
            for linje in self._prosess.stdout:
                linje = linje.rstrip()
                if not linje:
                    continue
                treff = re.search(r"Totalt eksportert:\s*(\d+)", linje)
                if treff:
                    nye = int(treff.group(1))
                self._trygg_after(self._logglinje, linje)
            self._prosess.wait()
            self._prosess = None
            self._vekk.set()   # oppdater tellingen med en gang
            self._trygg_after(self._hent_ferdig,
                              "Henting ferdig — se loggen." if nye is None else
                              f"{nye} nye korreksjoner klargjort til trening.")

        threading.Thread(target=arbeider, daemon=True).start()

    def _hent_ferdig(self, melding: str):
        try:
            self.hent_knapp.config(state="normal")
            self.start_knapp.config(state="normal")
            self.fase_var.set(melding)
        except tk.TclError:
            pass

    # ---------- selve treningsløpet ----------
    def _start_eller_avbryt(self):
        if self._prosess is not None:
            self._avbryt()
            return
        if not (PROSJEKT_ROT / "skript" / "kjor_treningslop.py").is_file():
            messagebox.showwarning(
                "Kun på servermaskinen",
                "Fant ikke treningsskriptene — trening kjøres på maskinen "
                "der nav-mappa ligger.")
            return
        # Si det HØYT før vi kaster bort en kjøring: under minstekravet
        # ender løpet garantert i «for_faa» (som bare synes i småskrift).
        annotert = getattr(self, "_annotert_totalt", None)
        if annotert is not None and annotert < TRENING_MIN_EKSEMPLER:
            if not messagebox.askyesno(
                    "For få korreksjoner",
                    f"Du har bare {annotert} annoterte korreksjoner — "
                    f"minst {TRENING_MIN_EKSEMPLER} trengs.\n\n"
                    "Treningen vil stoppe med «for få». Annoter flere i "
                    "Label Studio først.\n\nStarte likevel?"):
                return
        self.resultat_etikett.pack_forget()
        self._sett_logg("")
        self.hent_knapp.config(state="disabled")
        self.start_knapp.config(text="■  AVBRYT TRENING", bg=ROD,
                                activebackground=ROD_AKTIV)
        self.fase_var.set("Stopper API-et (frigjør GPU-en) ...")
        self._start_tid = time.monotonic()
        self._tikk_klokke()
        threading.Thread(target=self._kjor_lop, daemon=True).start()

    def _kjor_lop(self):
        # 1) stopp API-et hvis det kjører (Borealis holder ellers VRAM-en)
        api = KONTROLL_TJENESTER[0]
        self._api_var_oppe = bool(self.kontroll._pids_paa_port(api["port"]))
        if self._api_var_oppe:
            self.kontroll._stopp_tjeneste(api, stille=True)
            frist = time.monotonic() + 30
            while (time.monotonic() < frist
                   and self.kontroll._pids_paa_port(api["port"])):
                time.sleep(2)
            time.sleep(4)   # la CUDA slippe minnet helt

        # 2) kjør treningsløpet
        self._trygg_after(self.fase_var.set, "Starter treningsløpet ...")
        miljo = {**os.environ, **_les_lokal_env(),
                 "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1"}
        try:
            self._prosess = subprocess.Popen(
                [str(PROSJEKT_ROT / ".pyruntime" / "python.exe"), "-u",
                 str(PROSJEKT_ROT / "skript" / "kjor_treningslop.py")],
                cwd=str(PROSJEKT_ROT), env=miljo,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=_UTEN_VINDU)
        except OSError as exc:
            self._trygg_after(self._ferdig, "ukjent", f"Klarte ikke å starte: {exc}")
            return

        resultat = "ukjent"
        for linje in self._prosess.stdout:
            linje = linje.rstrip()
            if not linje:
                continue
            treff = re.search(r"resultat=(\w+)", linje)
            if treff:
                resultat = treff.group(1)
            self._trygg_after(self._logglinje, linje)
        kode = self._prosess.wait()
        avbrutt = self._prosess is None or getattr(self, "_ble_avbrutt", False)
        self._ble_avbrutt = False
        self._prosess = None
        if avbrutt:
            resultat = "avbrutt"
        elif kode != 0 and resultat == "ukjent":
            resultat = "ukjent"

        # 3) start API-et igjen (laster evt. promotert modell)
        if self._api_var_oppe:
            self._trygg_after(self.fase_var.set,
                              "Starter API-et igjen (laster modellen) ...")
            self._trygg_after(lambda: self.kontroll._start_tjeneste(api))
        self._vekk.set()
        self._trygg_after(self._ferdig, resultat, None)

    def _avbryt(self):
        prosess = self._prosess
        if prosess is None:
            return
        self._ble_avbrutt = True
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(prosess.pid)],
                       capture_output=True, creationflags=_UTEN_VINDU)

    def _ferdig(self, resultat: str, ekstra: str | None):
        try:
            if self._klokke_jobb is not None:
                self.rot.after_cancel(self._klokke_jobb)
                self._klokke_jobb = None
            tekst, farge = TRENING_RESULTATER.get(
                resultat, TRENING_RESULTATER["ukjent"])
            if ekstra:
                tekst = f"{tekst} ({ekstra})"
            self.resultat_var.set(("✔  " if farge == GRONN else "✖  " if farge == ROD
                                   else "⚠  ") + tekst)
            self.resultat_etikett.config(bg=_bland(farge, BG_HOVED, 0.6))
            self.resultat_etikett.pack(fill="x", padx=12, pady=(0, 6),
                                       before=self.logg.master)
            self.start_knapp.config(text="▶  START TRENING", bg=LILLA,
                                    activebackground=_bland(LILLA, "#000000", 0.2))
            self.hent_knapp.config(state="normal")
            self.fase_var.set("Klar.")
            self._fase = None
            self._sett_fremdrift(1.0 if resultat == "promotert" else 0.0)
        except tk.TclError:
            pass

    # ---------- fremdrift/logg (hovedtråden) ----------
    def _logglinje(self, linje: str):
        try:
            if "=== 1/3" in linje:
                self._fase = "eksport"
            elif "=== 2/3" in linje:
                self._fase = "trening"
            elif "=== 3/3" in linje:
                self._fase = "port"
            andel = None
            if self._fase == "trening":
                treff = re.search(r"'epoch':\s*([0-9.]+)", linje)
                if treff:
                    andel = min(float(treff.group(1)) / TRENING_EPOKER, 1.0)
            if self._fase:
                tittel, fra, til = TRENING_FASER[self._fase]
                total = fra if andel is None else fra + (til - fra) * andel
                epok = (f" — epoke {andel * TRENING_EPOKER:.1f}/"
                        f"{TRENING_EPOKER:.0f}" if andel is not None else "")
                self.fase_var.set(tittel + epok)
                self._sett_fremdrift(total)

            self.logg.config(state="normal")
            self.logg.insert("end", linje + "\n")
            if int(self.logg.index("end-1c").split(".")[0]) > 400:
                self.logg.delete("1.0", "100.0")   # hold loggen lett
            self.logg.see("end")
            self.logg.config(state="disabled")
        except tk.TclError:
            pass

    def _sett_fremdrift(self, andel: float):
        bredde = self.fremdrift.winfo_width()
        self.fremdrift.coords(self._fyllt, 0, 0, bredde * max(0.0, min(andel, 1.0)), 14)
        self.fremdrift.itemconfig(self._prosent_tekst,
                                  text=f"{andel * 100:.0f} %" if andel > 0.02 else "")

    def _tikk_klokke(self):
        if self._start_tid is None or self._prosess is None and self._fase is None:
            pass
        gaatt = time.monotonic() - (self._start_tid or time.monotonic())
        self.tid_var.set(f"{int(gaatt // 60)} min {int(gaatt % 60):02d} s")
        self._klokke_jobb = self.rot.after(1000, self._tikk_klokke)

    def _sett_logg(self, tekst: str):
        self.logg.config(state="normal")
        self.logg.delete("1.0", "end")
        if tekst:
            self.logg.insert("1.0", tekst)
        self.logg.config(state="disabled")

    def _trygg_after(self, fn, *argumenter):
        try:
            self.rot.after(0, fn, *argumenter)
        except (tk.TclError, RuntimeError):
            pass

    def har_aktiv_trening(self) -> bool:
        return self._prosess is not None

    def lukk(self):
        self._lukket = True
        self._vekk.set()


# ==========================================================================
# Innsyn — DIREKTEVISNING i eget vindu: se dokumentet bli behandlet LIVE.
# Serveren strømmer hendelser (side rendret → forbehandlet → hver region
# lest → andrepass → ferdig) via POST /innsyn + GET /innsyn/<id>?fra=N,
# og vinduet tegner dem i sanntid: bildet retter seg, boksene dukker opp
# én og én i motorens farge, og teksten fylles inn når den leses.
# ==========================================================================
INNSYN_MOTORFARGER = {"easy": GRONN, "rapid": BLAA, "norhand": ROSA,
                      "ufcn": ORANSJE}


class InnsynVindu:
    """Selve direktevisningsvinduet (Toplevel). Poller økta i en
    bakgrunnstråd; all tegning skjer på hovedtråden via after."""

    def __init__(self, rot, klient: ApiKlient, innsyn_id: str, filnavn: str):
        self.rot = rot
        self.klient = klient
        self.innsyn_id = innsyn_id
        self._lukket = False
        self._faktor = (1.0, 1.0)      # full-koordinat → canvas-koordinat
        self._foto = None              # holdes i live (ellers GC-es bildet)

        self.vindu = tk.Toplevel(rot)
        self.vindu.title(f"Innsyn — {filnavn}")
        self.vindu.geometry("1150x800")
        self.vindu.configure(bg=BG_HOVED)
        self.vindu.protocol("WM_DELETE_WINDOW", self._ved_lukking)

        topp = tk.Frame(self.vindu, bg=BG_HOVED)
        topp.pack(fill="x", padx=10, pady=(8, 2))
        self.status_var = tk.StringVar(value="Venter på serveren ...")
        tk.Label(topp, textvariable=self.status_var, fg=GUL, bg=BG_HOVED,
                 font=("Segoe UI", 12, "bold"), anchor="w").pack(side="left")
        self.tid_var = tk.StringVar(value="")
        tk.Label(topp, textvariable=self.tid_var, fg=FG_DEMPET,
                 bg=BG_HOVED).pack(side="right")

        # fargeforklaring
        legende = tk.Frame(self.vindu, bg=BG_HOVED)
        legende.pack(fill="x", padx=10)
        for tekst, farge in (("EasyOCR (trykt)", GRONN), ("RapidOCR", BLAA),
                             ("norhand (håndskrift)", ROSA),
                             ("Doc-UFCN-andrepass", ORANSJE)):
            tk.Label(legende, text="■ " + tekst, fg=farge, bg=BG_HOVED,
                     font=("Segoe UI", 8)).pack(side="left", padx=(0, 12))

        hoved = tk.Frame(self.vindu, bg=BG_HOVED)
        hoved.pack(fill="both", expand=True, padx=10, pady=6)

        self.canvas = tk.Canvas(hoved, width=700, height=680, bg=BG_INNDATA,
                                highlightthickness=1,
                                highlightbackground=KANTLINJE)
        self.canvas.pack(side="left", fill="both", expand=True)

        side = tk.Frame(hoved, bg=BG_HOVED, width=400)
        side.pack(side="left", fill="both", padx=(10, 0))
        tk.Label(side, text="Hendelser (live)", fg=FG_DEMPET, bg=BG_HOVED,
                 anchor="w").pack(fill="x")
        self.logg = tema_tekstfelt(side, wrap="word", font=("Consolas", 9),
                                   height=22, width=48)
        self.logg.pack(fill="both", expand=True)
        for navn, farge in (("gronn", GRONN), ("blaa", BLAA), ("rosa", ROSA),
                            ("oransje", ORANSJE), ("gul", GUL), ("rod", ROD),
                            ("dempet", FG_DEMPET)):
            self.logg.tag_configure(navn, foreground=farge)
        self.logg.config(state="disabled")

        tk.Label(side, text="Slutttekst", fg=FG_DEMPET, bg=BG_HOVED,
                 anchor="w").pack(fill="x", pady=(6, 0))
        self.tekst = tema_tekstfelt(side, wrap="word", font=("Segoe UI", 9),
                                    height=9, width=48)
        self.tekst.pack(fill="x")
        self.tekst.config(state="disabled")

        self._start = time.monotonic()
        self._tikk()
        threading.Thread(target=self._poll_lokke, daemon=True).start()

    # ---------- polling (bakgrunnstråd) ----------
    def _poll_lokke(self):
        fra = 0
        feil_paa_rad = 0
        while not self._lukket:
            time.sleep(0.3)
            try:
                svar = requests.get(
                    f"{self.klient.base_url}/innsyn/{self.innsyn_id}?fra={fra}",
                    headers=self.klient._hoder(), timeout=10).json()
                feil_paa_rad = 0
            except requests.exceptions.RequestException:
                feil_paa_rad += 1
                if feil_paa_rad > 10:
                    self._trygg_after(self._sett_status,
                                      "Mistet kontakten med serveren", ROD)
                    return
                continue
            for hendelse in svar.get("hendelser", []):
                self._trygg_after(self._vis_hendelse, hendelse)
            fra = svar.get("neste", fra)
            if svar.get("status") in ("ferdig", "feil"):
                self._trygg_after(self._ferdig, svar)
                return

    # ---------- tegning (hovedtråden) ----------
    def _vis_hendelse(self, h: dict):
        if self._lukket:
            return
        try:
            type_ = h.get("type")
            if type_ == "side_bilde":
                self._vis_bilde(h)
            elif type_ == "forstepass_lest":
                motor = h.get("motor", "easy")
                farge = INNSYN_MOTORFARGER.get(motor, GRONN)
                regioner = h.get("regioner", [])
                self._logglinje(f"Førstepass ({motor}): {len(regioner)} "
                                "tekstregioner funnet", "gronn")
                # boksene dukker opp én og én — ekte data, paced visning
                for indeks, region in enumerate(regioner):
                    self.rot.after(indeks * 60, self._tegn_region,
                                   region, farge)
            elif type_ == "norhand_lest":
                vant = h.get("vant")
                self._tegn_boks(h.get("boks"), ROSA, solid=vant)
                self._logglinje(
                    ("norhand vant: " if vant else "norhand (easy beholdt): ")
                    + f"«{h.get('tekst', '')[:38]}» "
                    f"({h.get('konfidens', 0):.2f})", "rosa")
            elif type_ == "andrepass_start":
                self._logglinje("Doc-UFCN-andrepass: segmenterer "
                                "tekstlinjene ...", "oransje")
            elif type_ == "andrepass_linjer":
                for boks in h.get("bokser", []):
                    self._tegn_boks(boks, ORANSJE, stiplet=True)
                self._logglinje(f"{len(h.get('bokser', []))} linjer funnet "
                                "— norhand leser dem ...", "oransje")
            elif type_ == "andrepass_lest":
                self._tegn_boks(h.get("boks"), ORANSJE, solid=True)
                self._logglinje(f"  «{h.get('tekst', '')[:42]}» "
                                f"({h.get('konfidens', 0):.2f})", "oransje")
            elif type_ == "andrepass_resultat":
                if h.get("vant"):
                    self._logglinje(
                        f"Andrepasset VANT ({h.get('ny_konfidens')} mot "
                        f"{h.get('gammel_konfidens')}) — brukes som svar",
                        "oransje")
                else:
                    self._logglinje(
                        f"Førstepasset beholdt ({h.get('gammel_konfidens')} "
                        f"mot {h.get('ny_konfidens')})", "dempet")
            elif type_ == "feil":
                self._logglinje("FEIL: " + h.get("melding", ""), "rod")
        except tk.TclError:
            pass

    def _vis_bilde(self, h: dict):
        import base64
        from io import BytesIO

        from PIL import Image, ImageTk
        raa = base64.b64decode(h["bilde"])
        img = Image.open(BytesIO(raa))
        lerret_b = max(self.canvas.winfo_width(), 660)
        lerret_h = max(self.canvas.winfo_height(), 620)
        skala = min(lerret_b / img.width, lerret_h / img.height, 1.0)
        img = img.resize((max(1, int(img.width * skala)),
                          max(1, int(img.height * skala))))
        self._foto = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._foto)
        full_b = h.get("full_bredde") or img.width
        full_h = h.get("full_hoyde") or img.height
        self._faktor = (img.width / full_b, img.height / full_h)
        if h.get("stadie") == "original":
            self._logglinje("Side 1 rendret", "dempet")
            self._sett_status("Forbehandler bildet ...", GUL)
        else:
            rapport = h.get("rapport") or {}
            deler = []
            if rapport.get("skjevhet_grader"):
                deler.append(f"rettet {rapport['skjevhet_grader']}° skjevhet")
            if rapport.get("belysning_flatet"):
                deler.append("skygge utjevnet")
            if rapport.get("perspektiv_rettet"):
                deler.append("perspektiv rettet")
            if rapport.get("linjer_fjernet"):
                deler.append("linjal-linjer fjernet")
            kvalitet = rapport.get("kvalitet") or {}
            for advarsel in kvalitet.get("advarsler", []):
                self._logglinje("⚠ " + advarsel, "gul")
            self._logglinje("Forbehandlet"
                            + (": " + ", ".join(deler) if deler else
                               " (ingenting å rette)"), "blaa")
            self._sett_status("Leser tekstregioner ...", GUL)

    def _tegn_region(self, region: dict, farge: str):
        try:
            self._tegn_boks(region.get("boks"), farge,
                            solid=region.get("skrift") != "handskrift")
        except tk.TclError:
            pass

    def _tegn_boks(self, boks, farge, solid=False, stiplet=False):
        if not boks or len(boks) != 4:
            return
        fx, fy = self._faktor
        x0, y0, x1, y1 = (boks[0] * fx, boks[1] * fy,
                          boks[2] * fx, boks[3] * fy)
        valg = {"outline": farge, "width": 2}
        if stiplet:
            valg["dash"] = (4, 3)
        self.canvas.create_rectangle(x0, y0, x1, y1, **valg)

    def _ferdig(self, svar: dict):
        try:
            resultat = svar.get("resultat") or {}
            if svar.get("status") == "feil":
                self._sett_status("Feilet: "
                                  + (svar.get("feil") or "ukjent"), ROD)
                return
            konfidens = resultat.get("ocr_konfidens")
            kilde = resultat.get("kilde")
            if kilde == "tekstlag":
                self._sett_status("Ferdig — PDF-en hadde tekstlag "
                                  "(ingen OCR nødvendig)", GRONN)
                self._logglinje("Tekstlag lest direkte — raskt og eksakt",
                                "gronn")
            else:
                self._sett_status(
                    f"Ferdig — samlet konfidens {konfidens * 100:.0f} %"
                    if konfidens is not None else "Ferdig", GRONN)
            motorer = resultat.get("ocr_motorer") or {}
            if motorer:
                self._logglinje("Motorer: " + ", ".join(
                    f"{navn}: {antall}" for navn, antall in motorer.items()),
                    "dempet")
            self.tekst.config(state="normal")
            self.tekst.delete("1.0", "end")
            self.tekst.insert("1.0", resultat.get("tekst") or "(ingen tekst)")
            self.tekst.config(state="disabled")
        except tk.TclError:
            pass

    # ---------- småting ----------
    def _logglinje(self, tekst: str, tagg: str = "dempet"):
        try:
            self.logg.config(state="normal")
            self.logg.insert("end",
                             f"+{time.monotonic() - self._start:5.1f}s  ",
                             "dempet")
            self.logg.insert("end", tekst + "\n", tagg)
            self.logg.see("end")
            self.logg.config(state="disabled")
        except tk.TclError:
            pass

    def _sett_status(self, tekst: str, farge: str):
        try:
            self.status_var.set(tekst)
            for barn in self.vindu.winfo_children():
                pass
        except tk.TclError:
            pass

    def _tikk(self):
        if self._lukket:
            return
        self.tid_var.set(f"{time.monotonic() - self._start:.0f} s")
        self.rot.after(1000, self._tikk)

    def _trygg_after(self, fn, *argumenter):
        try:
            self.rot.after(0, fn, *argumenter)
        except (tk.TclError, RuntimeError):
            pass

    def _ved_lukking(self):
        self._lukket = True
        self.vindu.destroy()


class InnsynPanel:
    """Innsyn-fanen: velg dokument → «Se dokumentet bli lest LIVE» åpner
    direktevisningsvinduet."""

    def __init__(self, forelder, rot, app):
        self.rot = rot
        self.app = app
        self.valgt_fil = None

        pad = {"padx": 12, "pady": 6}
        ramme = tema_rammefelt(forelder,
                               "Dokument (PDF, bilde, Word, Excel — som ellers)")
        ramme.pack(fill="x", **pad)
        rad = tk.Frame(ramme, bg=BG_PANEL)
        rad.pack(fill="x", padx=8, pady=8)
        self.fil_etikett = tk.Label(rad, text="Ingen fil valgt",
                                    fg=FG_DEMPET, bg=BG_PANEL, anchor="w")
        self.fil_etikett.pack(side="left", fill="x", expand=True)
        tema_knapp(rad, "Bla gjennom ...", self._velg_fil).pack(side="right")

        self.start_knapp = tk.Button(
            forelder, text="▶  SE DOKUMENTET BLI LEST — LIVE",
            command=self._start, bg=CYAN,
            activebackground=_bland(CYAN, "#000000", 0.2),
            fg="white", activeforeground="white",
            font=("Segoe UI", 12, "bold"), relief="flat",
            highlightthickness=0, pady=10)
        self.start_knapp.pack(fill="x", **pad)

        self.status_var = tk.StringVar(value="")
        tk.Label(forelder, textvariable=self.status_var, fg=FG_DEMPET,
                 bg=BG_HOVED, anchor="w").pack(fill="x", padx=12)

        tk.Label(forelder, text=(
            "Direktevisningen åpner et eget vindu som viser prosessen mens "
            "den skjer:\n"
            "  1. Siden rendres og forbehandles (skjevhet/skygge/perspektiv "
            "rettes foran øynene dine)\n"
            "  2. Tekstregionene dukker opp én og én i motorens farge\n"
            "  3. Håndskriftmodellen norhand leser usikre regioner — du ser "
            "hver lesing og hvem som vant\n"
            "  4. Doc-UFCN-andrepasset tegnes med oransje linjer når det "
            "trår til\n"
            "  5. Slutteksten og samlet konfidens vises når alt er ferdig\n\n"
            "Ingenting sendes til Label Studio herfra — ren inspeksjon."),
            fg=FG_DEMPET, bg=BG_HOVED, anchor="nw", justify="left",
            wraplength=830).pack(fill="both", expand=True, padx=12, pady=8)

    def _velg_fil(self):
        sti = filedialog.askopenfilename(title="Velg et dokument",
                                         filetypes=FILDIALOG_TYPER)
        if sti:
            self.valgt_fil = sti
            self.fil_etikett.config(text=os.path.basename(sti), fg=FG_TEKST)

    def _start(self, sti: str | None = None):
        sti = sti or self.valgt_fil
        if not sti or not os.path.isfile(sti):
            messagebox.showwarning("Merk", "Velg en fil først.")
            return
        if not self.app._oppdater_klient():
            return
        self.status_var.set("Klargjør og sender ...")
        self.start_knapp.config(state="disabled")

        def arbeider():
            konvertert = None
            try:
                pdf_sti, midlertidig = forbered_pdf(Path(sti))
                if midlertidig:
                    konvertert = pdf_sti
                with open(pdf_sti, "rb") as fil:
                    svar = requests.post(
                        self.app.klient.base_url + "/innsyn",
                        files={"fil": (pdf_sti.name, fil, "application/pdf")},
                        headers=self.app.klient._hoder(), timeout=60)
                svar.raise_for_status()
                innsyn_id = svar.json().get("innsyn_id")
                if not innsyn_id:
                    raise RuntimeError(svar.json().get("feil", "mangler innsyn_id"))
                self.rot.after(0, self._aapne_vindu, innsyn_id,
                               os.path.basename(sti))
            except Exception as exc:
                self.rot.after(0, self._feil, str(exc))
            finally:
                if konvertert is not None:
                    try:
                        os.remove(konvertert)
                    except OSError:
                        pass

        threading.Thread(target=arbeider, daemon=True).start()

    def _aapne_vindu(self, innsyn_id: str, filnavn: str):
        try:
            self.status_var.set("Direktevisning åpnet i eget vindu.")
            self.start_knapp.config(state="normal")
            InnsynVindu(self.rot, self.app.klient, innsyn_id, filnavn)
        except tk.TclError:
            pass

    def _feil(self, melding: str):
        try:
            self.status_var.set("Feilet: " + melding)
            self.start_knapp.config(state="normal")
        except tk.TclError:
            pass


class DokumentKlientApp:
    def __init__(self, rot: tk.Tk):
        self.rot = rot
        self.rot.title("NAV dokument-API — klient (Borealis)")
        self.rot.geometry("980x920")
        self.rot.minsize(640, 700)
        self.rot.configure(bg=BG_HOVED)

        self.klient = ApiKlient()
        self._fane_rammer = {}
        self._fane_knapper = {}
        self._jobb_poll_planlagt = None

        konfig = les_konfig()
        self._lagret_url = konfig.get("base_url") or STANDARD_URL
        # Har brukeren ikke lagret en nøkkel selv, hentes serverens egen
        # (.env / lokal_env.bat). Da virker GUI-en videre i det øyeblikket
        # API_NOKKEL slår inn, i stedet for å møte 401 uten forklaring.
        self._lagret_nokkel = (konfig.get("api_nokkel")
                               or _les_lokal_env().get("API_NOKKEL", ""))

        self._bygg_ui()
        self.rot.protocol("WM_DELETE_WINDOW", self._ved_lukking)

    def _ved_lukking(self):
        if hasattr(self, "trening") and self.trening.har_aktiv_trening():
            if not messagebox.askyesno(
                    "Trening pågår",
                    "Et treningsløp kjører fortsatt. Avbryte treningen og "
                    "lukke likevel?"):
                return
            self.trening._avbryt()
        if hasattr(self, "trening"):
            self.trening.lukk()
        if hasattr(self, "kontroll"):
            self.kontroll.lukk()  # stopper bakgrunnstrådene rent
        lagre_konfig(self.url_var.get().strip(), self.nokkel_var.get().strip())
        self.rot.destroy()

    def _base_url(self) -> str:
        url = self.url_var.get().strip().rstrip("/")
        for suffiks in KJENTE_ENDEPUNKT_SUFFIKSER:
            if url.endswith(suffiks):
                url = url[: -len(suffiks)].rstrip("/")
                break
        # «localhost:8600» uten skjema er en ærlig glipp — reparer den
        # i stedet for å la requests feile med en kryptisk melding.
        if url and "://" not in url:
            url = "http://" + url
        return url

    def _oppdater_klient(self) -> bool:
        """Synkroniserer ApiKlient med feltene øverst. False = mangler URL."""
        base = self._base_url()
        if not base:
            messagebox.showwarning("Merk", "Fyll inn server-URL-en først.")
            return False
        self.klient.base_url = base
        self.klient.api_nokkel = self.nokkel_var.get().strip()
        lagre_konfig(self.url_var.get().strip(), self.klient.api_nokkel)
        return True

    # ---------- bygg UI ----------
    def _bygg_ui(self):
        pad = {"padx": 12, "pady": 6}

        topp = tema_rammefelt(
            self.rot, "Tilkobling (huskes til neste gang i ~/.nav_api_klient.json)"
        )
        topp.pack(fill="x", **pad)

        tk.Label(topp, text="Server-URL (tunneladresse eller http://127.0.0.1:8600, uten sti):",
                 fg=FG_DEMPET, bg=BG_PANEL, anchor="w").pack(fill="x", padx=8, pady=(8, 0))
        self.url_var = tk.StringVar(value=self._lagret_url)
        url_felt = tema_innfelt(topp, self.url_var)
        url_felt.pack(fill="x", padx=8, pady=(2, 6))
        bind_utklippstavle(self.rot, url_felt)

        tk.Label(topp, text="API-nøkkel (X-API-Key) — bare nødvendig når serveren er startet med API_NOKKEL:",
                 fg=FG_DEMPET, bg=BG_PANEL, anchor="w").pack(fill="x", padx=8)
        self.nokkel_var = tk.StringVar(value=self._lagret_nokkel)
        nokkel_felt = tema_innfelt(topp, self.nokkel_var, show="•")
        nokkel_felt.pack(fill="x", padx=8, pady=(2, 8))
        bind_utklippstavle(self.rot, nokkel_felt)

        self._bygg_fanelinje()

        fanebeholder = tk.Frame(self.rot, bg=BG_HOVED)
        fanebeholder.pack(fill="both", expand=True)

        for nokkel, _tekst in FANER:
            self._fane_rammer[nokkel] = tk.Frame(fanebeholder, bg=BG_HOVED)

        self.kontroll = KontrollPanel(self._fane_rammer["kontroll"], self.rot,
                                      self)
        self.flytskjema = FlytskjemaPanel(self._fane_rammer["flyt"], self.rot)
        self.innsyn = InnsynPanel(self._fane_rammer["innsyn"], self.rot, self)
        self.trening = TreningPanel(self._fane_rammer["trening"], self.rot,
                                    self.kontroll)
        self._bygg_dokument_fane(self._fane_rammer["dokument"])
        self._bygg_operasjoner_fane(self._fane_rammer["operasjoner"])
        self._bygg_spor_fane(self._fane_rammer["spor"])
        self._bygg_fyll_skjema_fane(self._fane_rammer["fyll_skjema"])
        self._bygg_analyser_fane(self._fane_rammer["analyser"])
        self._bygg_uttrekk_fane(self._fane_rammer["uttrekk"])
        self._bygg_jobb_fane(self._fane_rammer["jobb"])
        self._bygg_info_fane(self._fane_rammer["info"])

        self._vis_fane("kontroll")

    def _bygg_fanelinje(self):
        linje = tk.Frame(self.rot, bg=BG_HOVED)
        linje.pack(fill="x", padx=12, pady=(4, 0))
        for nokkel, tekst in FANER:
            knapp = tk.Button(
                linje, text=tekst, command=lambda n=nokkel: self._vis_fane(n),
                bg=BG_KNAPP, fg=FG_TEKST, activebackground=BG_KNAPP_AKTIV,
                activeforeground=FG_TEKST, relief="flat", highlightthickness=0,
                padx=10, pady=6,
            )
            knapp.pack(side="left", padx=(0, 4))
            self._fane_knapper[nokkel] = knapp

    def _vis_fane(self, nokkel):
        for n, ramme in self._fane_rammer.items():
            if n == nokkel:
                ramme.pack(fill="both", expand=True)
                self._fane_knapper[n].config(bg=AKSENT, fg="white")
            else:
                ramme.pack_forget()
                self._fane_knapper[n].config(bg=BG_KNAPP, fg=FG_TEKST)

    # ---------- felles forespørselskjøring ----------
    def _kjor_foresporsel(self, panel: SvarPanel, foresporsel_fn, ved_suksess):
        """
        foresporsel_fn(tidtaker) kjører i bakgrunnstråd og returnerer en
        dict. Den skal gjøre lokal filklargjøring FØR den setter
        tidtaker['start'] = time.perf_counter() og så gjøre HTTP-kallet —
        slik dekker den rapporterte varigheten nøyaktig nettverksrunden,
        ikke lokal filkonvertering. ved_suksess(data, brukt) kjører på
        hovedtråden.
        """
        tidtaker = {"start": None}

        def brukt():
            return time.perf_counter() - tidtaker["start"] if tidtaker["start"] is not None else None

        def arbeider():
            try:
                data = foresporsel_fn(tidtaker)
                self.rot.after(0, ved_suksess, data, brukt())
            except KonverteringsFeil as exc:
                self.rot.after(0, self._panel_feil, panel, str(exc), None)
            except requests.exceptions.Timeout:
                self.rot.after(
                    0, self._panel_feil, panel,
                    "Forespørselen fikk tidsavbrudd. Prøv igjen.", brukt(),
                )
            except requests.exceptions.ConnectionError:
                self.rot.after(
                    0, self._panel_feil, panel,
                    "Fikk ikke kontakt med serveren. Sjekk URL-en og at "
                    "hjemmemaskinen og tunnelen kjører.", brukt(),
                )
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else "?"
                detalj = _hent_feildetalj(exc.response) if exc.response is not None else None
                if status == 401:
                    melding = ("Serveren avviste forespørselen (401): ugyldig eller "
                               "manglende API-nøkkel. Fyll inn riktig X-API-Key i "
                               "feltet øverst.")
                elif status == 503:
                    # Serveren skiller mellom «språkmodellen laster» og
                    # «OCR-motorene varmer opp», og de har svært ulik
                    # ventetid. Vis dens egen forklaring når den finnes,
                    # i stedet for én gjetning som passer på begge.
                    melding = detalj or ("Serveren laster fortsatt modellen "
                                         "(Borealis). Prøv igjen om ett minutt.")
                elif status == 409 and detalj:
                    melding = f"Ikke klart ennå (409): {detalj}"
                elif detalj:
                    melding = f"Serveren returnerte en feil (status {status}): {detalj}"
                else:
                    melding = f"Serveren returnerte en feil (status {status})."
                self.rot.after(0, self._panel_feil, panel, melding, brukt())
            except ValueError:
                self.rot.after(
                    0, self._panel_feil, panel, "Serversvaret var ikke gyldig JSON.", brukt()
                )
            except Exception as exc:
                self.rot.after(0, self._panel_feil, panel, f"Uventet feil: {exc}", brukt())

        threading.Thread(target=arbeider, daemon=True).start()

    def _panel_feil(self, panel: SvarPanel, melding: str, brukt):
        panel.fremdrift.stopp()
        panel.varighet_var.set(f"Feilet etter {formater_varighet(brukt)}" if brukt is not None else "")
        panel.status_var.set("Det oppstod en feil")
        panel.sett_advarsel("")
        panel.sett_svar(melding)

    def _fullfor_suksess(self, panel: SvarPanel, data, brukt, statustekst: str, advarselstekst: str = ""):
        """Felles avslutning for et vellykket svar: stopp indikatoren,
        vis varighet, husk dataene og sett advarsel + status."""
        panel.fremdrift.stopp()
        panel.varighet_var.set(f"Tok {formater_varighet(brukt)}" if brukt is not None else "")
        panel.merk_data(data)
        panel.status_var.set(statustekst)
        panel.sett_advarsel(advarselstekst)

    def _standard_suksess(self, panel: SvarPanel, statustekst: str, formatter=None,
                          etterpaa=None):
        """Bygger en ved_suksess-callback med den felles hale-logikken alle
        fanene deler: eksplisitt ok=False vises som feil, ellers vises
        advarsler + formatert svar. `formatter(data) -> str` styrer
        visningen (standard: full JSON); `etterpaa(data)` kjører til slutt
        for fanespesifikke behov (f.eks. å plukke opp jobb_id)."""
        def ved_suksess(data, brukt):
            if er_eksplisitt_feil(data):
                panel.fremdrift.stopp()
                panel.varighet_var.set(f"Tok {formater_varighet(brukt)}" if brukt is not None else "")
                panel.merk_data(data)
                panel.status_var.set("Forespørselen feilet")
                panel.sett_advarsel("")
                panel.sett_svar(data.get("feil") or str(data))
                return
            self._fullfor_suksess(panel, data, brukt, statustekst, bygg_advarselstekst(data))
            panel.sett_svar(formatter(data) if formatter else formater_json(data))
            if etterpaa:
                etterpaa(data)
        return ved_suksess

    def _fil_foresporsel(self, kilde_sti: str, send_fn):
        """Felles kropp for endepunkter som tar en fil: konverterer til
        PDF ved behov, kaller send_fn(pdf_sti) og rydder opp midlertidig
        fil etterpå."""
        def foresporsel_fn(tidtaker):
            konvertert_sti = None
            try:
                pdf_sti, er_midlertidig = forbered_pdf(Path(kilde_sti))
                if er_midlertidig:
                    konvertert_sti = pdf_sti
                tidtaker["start"] = time.perf_counter()
                return send_fn(pdf_sti)
            finally:
                if konvertert_sti is not None:
                    try:
                        os.remove(konvertert_sti)
                    except OSError:
                        pass
        return foresporsel_fn

    def _velg_fil_til(self, etikett, sett_sti):
        sti = filedialog.askopenfilename(title="Velg et dokument", filetypes=FILDIALOG_TYPER)
        if sti:
            sett_sti(sti)
            etikett.config(text=os.path.basename(sti), fg=FG_TEKST)

    def _sjekk_valgt_fil(self, sti: str | None, paakrevd=True) -> bool:
        if not sti:
            if paakrevd:
                messagebox.showwarning("Merk", "Velg en fil først.")
            return not paakrevd
        if not os.path.isfile(sti):
            messagebox.showerror("Feil", "Den valgte filen finnes ikke lenger på disk.")
            return False
        return True

    # ======================================================================
    # Fane: Spør (/spor)
    # ======================================================================
    # ======================================================================
    # Fane: Dokument (/dokument) — ETT kall med brytere: dokumentet leses
    # én gang, og bare delene som er slått PÅ kjøres. Modelldelene er AV
    # som standard, så det raske forblir raskt.
    # ======================================================================
    def _bygg_motorvelger(self, forelder, var):
        """Felles radiovelger for skjema_motor (modell/felter/auto). Brukes
        i både Dokument- og Fyll skjema-fanen så valget ser likt ut."""
        ramme = tema_rammefelt(forelder, "Skjema-motor (for utfylling av JSON-mal)")
        ramme.pack(fill="x", padx=12, pady=6)
        for nokkel, tekst in SKJEMA_MOTORER:
            tk.Radiobutton(
                ramme, text=tekst, value=nokkel, variable=var, anchor="w",
                bg=BG_PANEL, fg=FG_TEKST, selectcolor=BG_INNDATA,
                activebackground=BG_PANEL, activeforeground=FG_TEKST,
                highlightthickness=0,
            ).pack(fill="x", padx=10, pady=1)
        tk.Label(
            ramme,
            text="«felter»/«auto» bruker plassholdere som {telefon} i malen; "
                 "«modell» fyller tomme strenger. «auto» lar modellen finne "
                 "det regelen ikke fant (f.eks. navn) og merker kilden per felt.",
            fg=FG_DEMPET, bg=BG_PANEL, anchor="w", wraplength=880,
            justify="left").pack(fill="x", padx=10, pady=(2, 6))
        return ramme

    def _bygg_dokument_fane(self, forelder):
        pad = {"padx": 12, "pady": 6}
        self.dokument_valgt_fil: str | None = None

        filramme = tema_rammefelt(forelder, "Dokument (påkrevd)")
        filramme.pack(fill="x", **pad)
        filrad = tk.Frame(filramme, bg=BG_PANEL)
        filrad.pack(fill="x", padx=8, pady=8)
        self.dokument_fil_etikett = tk.Label(
            filrad, text="Ingen fil valgt", fg=FG_DEMPET, bg=BG_PANEL, anchor="w"
        )
        self.dokument_fil_etikett.pack(side="left", fill="x", expand=True)
        tema_knapp(
            filrad, "Bla gjennom ...",
            lambda: self._velg_fil_til(self.dokument_fil_etikett,
                                       self._sett_dokument_fil),
        ).pack(side="right")

        bryterramme = tema_rammefelt(
            forelder, "Hva skal gjøres? (dokumentet leses ÉN gang uansett)")
        bryterramme.pack(fill="x", **pad)
        rutenett = tk.Frame(bryterramme, bg=BG_PANEL)
        rutenett.pack(fill="x", padx=8, pady=6)
        rutenett.columnconfigure(0, weight=1)
        rutenett.columnconfigure(1, weight=1)
        self.dokument_brytere = {}
        for i, (nokkel, tekst, standard) in enumerate([
                ("felter", "Felter + datoer (raskt, uten modell)", True),
                ("struktur", "Strukturert uttrekk (raskt, uten modell)", False),
                ("tekst", "Full tekst i svaret", True),
                ("korriger", "Korriger OCR-tekst (modell — tregere)", False),
                ("svar", "Svar på spørsmål (modell — tregere)", False),
                ("skjema", "Fyll JSON-mal (modell — tregere)", False)]):
            var = tk.BooleanVar(value=standard)
            tk.Checkbutton(
                rutenett, text=tekst, variable=var, anchor="w",
                bg=BG_PANEL, fg=FG_TEKST, selectcolor=BG_INNDATA,
                activebackground=BG_PANEL, activeforeground=FG_TEKST,
                highlightthickness=0,
            ).grid(row=i // 2, column=i % 2, sticky="w", padx=4, pady=1)
            self.dokument_brytere[nokkel] = var

        tk.Label(bryterramme,
                 text="Skriver du spørsmål eller JSON-mal under, slås delen "
                      "på av seg selv. Delene er uavhengige: feiler én, "
                      "kommer resten likevel.",
                 fg=FG_DEMPET, bg=BG_PANEL, anchor="w", wraplength=880,
                 justify="left").pack(fill="x", padx=8, pady=(0, 6))

        tk.Label(forelder, text="Spørsmål (til «Svar på spørsmål»):",
                 fg=FG_DEMPET, bg=BG_HOVED, anchor="w").pack(fill="x", padx=12)
        self.dokument_sporsmal_var = tk.StringVar()
        sporsmal_felt = tema_innfelt(forelder, self.dokument_sporsmal_var)
        sporsmal_felt.pack(fill="x", padx=12, pady=(2, 4))
        bind_utklippstavle(self.rot, sporsmal_felt)

        tk.Label(forelder, text="JSON-mal (til «Fyll JSON-mal») — "
                                'f.eks. {"navn": "", "belop": ""}:',
                 fg=FG_DEMPET, bg=BG_HOVED, anchor="w").pack(fill="x", padx=12)
        self.dokument_mal_tekst = tema_tekstfelt(forelder, height=3)
        self.dokument_mal_tekst.pack(fill="x", padx=12, pady=(2, 4))
        bind_utklippstavle(self.rot, self.dokument_mal_tekst)

        self.dokument_motor_var = tk.StringVar(value="modell")
        self._bygg_motorvelger(forelder, self.dokument_motor_var)

        primaerknapp(forelder, "Kjør valgte deler (ett kall)",
                     self._send_dokument).pack(fill="x", **pad)

        self.dokument_panel = SvarPanel(forelder, self.rot, etikett="Dokument")

    def _sett_dokument_fil(self, sti):
        self.dokument_valgt_fil = sti

    def _send_dokument(self):
        if not self._sjekk_valgt_fil(self.dokument_valgt_fil):
            return
        if not self._oppdater_klient():
            return
        sporsmal = self.dokument_sporsmal_var.get().strip()
        mal = self.dokument_mal_tekst.get("1.0", "end").strip()
        # Utfylt felt = åpenbar hensikt → delen skal på (som serveren gjør).
        # Selve bryterne flippes FØRST når alt er validert: avbrytes kallet
        # her, skal brukeren finne panelet slik hen forlot det.
        vil_svar = self.dokument_brytere["svar"].get() or bool(sporsmal)
        vil_skjema = self.dokument_brytere["skjema"].get() or bool(mal)
        if vil_svar and not sporsmal:
            messagebox.showwarning(
                "Mangler spørsmål",
                "«Svar på spørsmål» er på — skriv spørsmålet først "
                "(eller slå av bryteren).")
            return
        if vil_skjema:
            if not mal:
                messagebox.showwarning(
                    "Mangler JSON-mal",
                    "«Fyll JSON-mal» er på — lim inn malen først "
                    "(eller slå av bryteren).")
                return
            try:
                tolket = json.loads(mal)
            except ValueError as exc:
                messagebox.showwarning("Ugyldig JSON",
                                       f"JSON-malen er ugyldig: {exc}")
                return
            # Samme krav som serveren, så feilen fanges her i stedet for
            # å komme tilbake som en 400 etter at filen er lastet opp
            if not isinstance(tolket, (dict, list)) or not tolket:
                messagebox.showwarning(
                    "Tom eller ugyldig mal",
                    "JSON-malen må være et objekt (eller en liste) med "
                    'felter, f.eks. {"navn": "", "belop": ""}.')
                return

        self.dokument_brytere["svar"].set(vil_svar)
        self.dokument_brytere["skjema"].set(vil_skjema)
        felter = {nokkel: ("ja" if var.get() else "nei")
                  for nokkel, var in self.dokument_brytere.items()}
        if sporsmal:
            felter["sporsmal"] = sporsmal
        if mal and self.dokument_brytere["skjema"].get():
            felter["skjema_mal"] = mal
            felter["skjema_motor"] = self.dokument_motor_var.get()

        panel = self.dokument_panel
        panel.nullstill("Klargjør filen ...")

        def formatter(data):
            linjer = []
            valg = data.get("valg") or {}
            linjer.append("Deler kjørt: "
                          + (", ".join(n for n, p in valg.items() if p) or "ingen"))
            sv = data.get("svar")
            if isinstance(sv, dict):
                linjer.append("")
                linjer.append("Svar: " + (str(sv.get("svar"))
                                          if sv.get("ok")
                                          else f"FEILET — {sv.get('feil')}"))
                if sv.get("svar_avkortet"):
                    linjer.append("  (svaret nådde maksimal lengde og kan "
                                  "være avkortet)")
                if sv.get("tolket_sporsmal"):
                    linjer.append(f"  (tolket spørsmål: {sv['tolket_sporsmal']})")
                if sv.get("ok") and not sv.get("tall_verifisert", True):
                    linjer.append("  (ADVARSEL: svaret har tall som ikke står "
                                  "ordrett i dokumentet)")
            ko = data.get("korriger")
            if isinstance(ko, dict) and not ko.get("ok"):
                linjer.append("")
                linjer.append(f"Korrigering FEILET — {ko.get('feil')}")
            sk = data.get("skjema")
            if isinstance(sk, dict):
                linjer.append("")
                if sk.get("ok"):
                    motor = sk.get("motor")
                    linjer.append("Utfylt skjema"
                                  + (f" (motor: {motor})" if motor else "") + ":")
                    linjer.append(formater_json(sk.get("skjema") or {}))
                    if sk.get("kilde_per_felt"):
                        linjer.append("  Kilde per felt: "
                                      + ", ".join(f"{k}={v}" for k, v
                                                  in sk["kilde_per_felt"].items()))
                    if sk.get("ukjente_felter"):
                        linjer.append("  Fant ikke: "
                                      + ", ".join(sk["ukjente_felter"]))
                    if sk.get("avvik"):
                        for a in sk["avvik"]:
                            linjer.append(f"  Avvik: {a}")
                else:
                    linjer.append(f"Skjema FEILET — {sk.get('feil')}")
            f = data.get("felter")
            if isinstance(f, dict) and f.get("felter"):
                linjer.append("")
                linjer.append("Felter:")
                for navn, verdi in f["felter"].items():
                    linjer.append(f"  {navn}: {verdi}")
            for adv in (data.get("kvalitet") or {}).get("advarsler") or []:
                linjer.append(f"ADVARSEL: {adv}")
            linjer.append("")
            linjer.append("Fullt svar (JSON):")
            linjer.append(formater_json(data))
            return "\n".join(linjer)

        self._kjor_foresporsel(
            panel,
            self._fil_foresporsel(self.dokument_valgt_fil,
                                  lambda pdf: self.klient.dokument_samlet(pdf, felter)),
            self._standard_suksess(panel, "Samlet svar mottatt", formatter),
        )

    # ======================================================================
    # Fane: Operasjoner (/dokument med feltet 'operasjoner') — det uniforme
    # kontraktet: en JSON-liste av {type, …} kjøres på rad mot samme
    # dokument, hver med sitt eget resultat.
    # ======================================================================
    def _bygg_operasjoner_fane(self, forelder):
        pad = {"padx": 12, "pady": 6}
        self.operasjoner_valgt_fil: str | None = None

        filramme = tema_rammefelt(forelder, "Dokument (påkrevd)")
        filramme.pack(fill="x", **pad)
        filrad = tk.Frame(filramme, bg=BG_PANEL)
        filrad.pack(fill="x", padx=8, pady=8)
        self.operasjoner_fil_etikett = tk.Label(
            filrad, text="Ingen fil valgt", fg=FG_DEMPET, bg=BG_PANEL, anchor="w")
        self.operasjoner_fil_etikett.pack(side="left", fill="x", expand=True)
        tema_knapp(
            filrad, "Bla gjennom ...",
            lambda: self._velg_fil_til(self.operasjoner_fil_etikett,
                                       self._sett_operasjoner_fil),
        ).pack(side="right")

        opramme = tema_rammefelt(
            forelder, "Operasjoner (JSON-liste) — kjøres på rad mot dokumentet")
        opramme.pack(fill="both", **pad)
        ophode = tk.Frame(opramme, bg=BG_PANEL)
        ophode.pack(fill="x", padx=8, pady=(8, 0))
        tk.Label(ophode, text="Gyldige typer: tekst, felter, struktur, svar "
                 "(+sporsmal), skjema (+mal, +motor), korriger",
                 fg=FG_DEMPET, bg=BG_PANEL, anchor="w").pack(side="left")
        tema_knapp(ophode, "Sett inn eksempel",
                   self._sett_inn_operasjoner_eksempel).pack(side="right")
        self.operasjoner_tekst = tema_tekstfelt(
            opramme, wrap="word", font=("Consolas", 10), height=8)
        self.operasjoner_tekst.pack(fill="both", expand=True, padx=8, pady=8)
        bind_utklippstavle(self.rot, self.operasjoner_tekst)

        primaerknapp(forelder, "Kjør operasjoner",
                     self._send_operasjoner).pack(fill="x", **pad)

        self.operasjoner_panel = SvarPanel(forelder, self.rot,
                                           etikett="Resultater")

    def _sett_operasjoner_fil(self, sti):
        self.operasjoner_valgt_fil = sti

    def _sett_inn_operasjoner_eksempel(self):
        naavaerende = self.operasjoner_tekst.get("1.0", "end").strip()
        if naavaerende and not messagebox.askyesno(
            "Erstatte?", "Dette erstatter det som står i feltet nå. Fortsette?"):
            return
        self.operasjoner_tekst.delete("1.0", "end")
        self.operasjoner_tekst.insert("1.0", EKSEMPEL_OPERASJONER)

    def _send_operasjoner(self):
        if not self._sjekk_valgt_fil(self.operasjoner_valgt_fil):
            return
        raa = self.operasjoner_tekst.get("1.0", "end").strip()
        if not raa:
            messagebox.showwarning(
                "Merk", "Lim inn en JSON-liste av operasjoner først "
                        "(eller trykk «Sett inn eksempel»).")
            return
        # Fang ugyldig JSON / feil form lokalt — samme krav som serveren,
        # så brukeren slipper en serverrunde for en åpenbar skrivefeil.
        try:
            tolket = json.loads(raa)
        except json.JSONDecodeError as exc:
            messagebox.showerror("Ugyldig JSON",
                                 f"Operasjonene er ikke gyldig JSON: {exc}")
            return
        if isinstance(tolket, dict) and "operasjoner" in tolket:
            tolket = tolket["operasjoner"]
        if not isinstance(tolket, list) or not tolket:
            messagebox.showwarning(
                "Feil form", "Operasjonene må være en ikke-tom JSON-liste, "
                'f.eks. [{"type":"felter"}].')
            return

        panel = self.operasjoner_panel
        panel.nullstill("Klargjør filen ...")

        def formatter(data):
            linjer = []
            for r in data.get("resultater") or []:
                t, ok = r.get("type"), r.get("ok")
                if not ok:
                    linjer.append(f"[{t}] FEILET — {r.get('feil')}")
                    linjer.append("")
                    continue
                if t == "skjema":
                    linjer.append(f"[skjema] motor: {r.get('motor')}")
                    linjer.append(formater_json(r.get("data") or {}))
                    if r.get("kilde_per_felt"):
                        linjer.append("    kilde: " + ", ".join(
                            f"{k}={v}" for k, v in r["kilde_per_felt"].items()))
                    if r.get("ukjente_felter"):
                        linjer.append("    fant ikke: "
                                      + ", ".join(r["ukjente_felter"]))
                elif t == "felter":
                    linjer.append("[felter]")
                    for navn, verdi in ((r.get("data") or {}).get("felter")
                                        or {}).items():
                        linjer.append(f"    {navn}: {verdi}")
                elif t == "svar":
                    # Svarfeltene ligger naa i «data», ikke paa
                    # toppnivaa: `resultater[i].data` er en paalitelig
                    # sti for ALLE operasjonstyper.
                    linjer.append(f"[svar] {(r.get('data') or {}).get('svar')}")
                elif t in ("tekst", "korriger"):
                    # «data» er alltid et objekt naa — teksten laa
                    # tidligere direkte i feltet, saa den var `str` for
                    # denne typen og `dict` for alle andre.
                    utdrag = str((r.get("data") or {}).get("tekst") or "")[:800]
                    linjer.append(f"[{t}]")
                    linjer.append("    " + utdrag.replace("\n", "\n    "))
                elif t == "struktur":
                    linjer.append("[struktur]")
                    linjer.append(formater_json(r.get("data") or {}))
                else:
                    linjer.append(f"[{t}]")
                    linjer.append(formater_json(r))
                linjer.append("")
            for adv in (data.get("kvalitet") or {}).get("advarsler") or []:
                linjer.append(f"ADVARSEL: {adv}")
            linjer.append("Fullt svar (JSON):")
            linjer.append(formater_json(data))
            return "\n".join(linjer)

        self._kjor_foresporsel(
            panel,
            self._fil_foresporsel(
                self.operasjoner_valgt_fil,
                lambda pdf: self.klient.dokument_operasjoner(pdf, raa)),
            self._standard_suksess(panel, "Resultater mottatt", formatter),
        )

    def _bygg_spor_fane(self, forelder):
        pad = {"padx": 12, "pady": 6}
        self.spor_valgt_fil: str | None = None

        filramme = tema_rammefelt(
            forelder, "Dokument (valgfritt — PDF, bilde, Word, Excel, PowerPoint eller tekst)"
        )
        filramme.pack(fill="x", **pad)
        filrad = tk.Frame(filramme, bg=BG_PANEL)
        filrad.pack(fill="x", padx=8, pady=8)
        self.spor_fil_etikett = tk.Label(
            filrad, text="Ingen fil valgt (still et generelt spørsmål i stedet)",
            fg=FG_DEMPET, bg=BG_PANEL, anchor="w",
        )
        self.spor_fil_etikett.pack(side="left", fill="x", expand=True)
        tema_knapp(
            filrad, "Bla gjennom ...",
            lambda: self._velg_fil_til(self.spor_fil_etikett, self._sett_spor_fil),
        ).pack(side="right")

        sporsmalsramme = tema_rammefelt(
            forelder,
            "Spørsmålet ditt (tomt = hele den utleste teksten når fil er vedlagt, "
            "ellers påkrevd) — Ctrl+Enter sender",
        )
        sporsmalsramme.pack(fill="x", **pad)
        self.spor_sporsmal = tema_tekstfelt(sporsmalsramme, wrap="word", font=("Segoe UI", 10), height=4)
        self.spor_sporsmal.pack(fill="x", padx=8, pady=(8, 4))
        self.spor_sporsmal.bind("<Control-Return>", lambda _e: self._send_spor())
        bind_utklippstavle(self.rot, self.spor_sporsmal)

        self.spor_korriger_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            sporsmalsramme,
            text="Korriger OCR-teksten med modellen først (korriger=ja — tregere, men renere tekst)",
            variable=self.spor_korriger_var, bg=BG_PANEL, fg=FG_DEMPET,
            activebackground=BG_PANEL, activeforeground=FG_TEKST,
            selectcolor=BG_INNDATA, anchor="w", highlightthickness=0,
        ).pack(fill="x", padx=8, pady=(0, 8))

        primaerknapp(forelder, "Send", self._send_spor).pack(fill="x", **pad)

        self.spor_panel = SvarPanel(forelder, self.rot, etikett="Svar")

    def _sett_spor_fil(self, sti):
        self.spor_valgt_fil = sti

    def _send_spor(self):
        sporsmal = self.spor_sporsmal.get("1.0", "end").strip()
        if not self.spor_valgt_fil and not sporsmal:
            messagebox.showwarning(
                "Merk", "Velg en fil, skriv et spørsmål, eller begge deler — minst én trengs."
            )
            return
        if not self._oppdater_klient():
            return
        if not self._sjekk_valgt_fil(self.spor_valgt_fil, paakrevd=False):
            return

        kilde_sti = self.spor_valgt_fil
        korriger = self.spor_korriger_var.get()
        panel = self.spor_panel
        panel.nullstill("Klargjør filen ..." if kilde_sti else "Sender ...")

        def foresporsel_fn(tidtaker):
            konvertert_sti = None
            try:
                if kilde_sti:
                    pdf_sti, er_midlertidig = forbered_pdf(Path(kilde_sti))
                    if er_midlertidig:
                        konvertert_sti = pdf_sti
                    self.rot.after(
                        0, panel.status_var.set,
                        "Sender ... første forespørsel etter omstart kan ta 20–40 s "
                        "(lenger med OCR)",
                    )
                    tidtaker["start"] = time.perf_counter()
                    return self.klient.spor_med_fil(pdf_sti, sporsmal, korriger)
                self.rot.after(0, panel.status_var.set, "Sender ...")
                tidtaker["start"] = time.perf_counter()
                return self.klient.spor_uten_fil(sporsmal)
            finally:
                if konvertert_sti is not None:
                    try:
                        os.remove(konvertert_sti)
                    except OSError:
                        pass

        self._kjor_foresporsel(
            panel, foresporsel_fn,
            lambda data, brukt: self._haandter_spor_suksess(panel, data, brukt),
        )

    def _haandter_spor_suksess(self, panel: SvarPanel, data, brukt):
        if er_eksplisitt_feil(data):
            panel.fremdrift.stopp()
            panel.varighet_var.set(f"Tok {formater_varighet(brukt)}" if brukt is not None else "")
            panel.merk_data(data)
            panel.status_var.set("Forespørselen feilet")
            panel.sett_advarsel("")
            panel.sett_svar(data.get("feil") or str(data))
            return

        kilde = data.get("kilde", "-")
        ocr_notis = " — OCR ble brukt" if data.get("ocr_brukt") else ""
        motorer = data.get("ocr_motorer")
        motor_notis = ""
        if motorer:
            motor_notis = " | Motorer: " + ", ".join(f"{navn}:{antall}" for navn, antall in motorer.items())
        generell_notis = " — generell kunnskap, uten dokument" if data.get("uten_dokument") else ""
        statustekst = f"Vellykket (kilde: {kilde}){ocr_notis}{motor_notis}{generell_notis}"

        self._fullfor_suksess(panel, data, brukt, statustekst, bygg_advarselstekst(data))

        svar = data.get("svar")
        korrigert = data.get("korrigert_tekst")
        if korrigert:
            # R59: serveren legger den modellrettede teksten i sitt eget
            # felt og lar 'svar' være den rå OCR-lesningen. Klienten viste
            # bare 'svar', så den som huket av «Korriger OCR-teksten»
            # betalte for jobben uten å se resultatet.
            #
            # Begge vises, i denne rekkefølgen: du ba om den rettede, så
            # den kommer først — men den rå står under, fordi den er
            # fasiten. Rettingen er modellarbeid og kan ta feil.
            panel.sett_svar(
                "KORRIGERT AV MODELLEN (kontroller mot originalen under):\n"
                + korrigert.strip()
                + "\n\n" + "-" * 60 + "\n"
                + "RÅ OCR-TEKST — det dokumentet faktisk ble lest som:\n"
                + (svar or "").strip()
            )
        elif svar:
            panel.sett_svar(svar)
        elif data.get("melding"):
            panel.sett_svar(data["melding"])
        elif data.get("feil"):
            panel.sett_svar(data["feil"])
        else:
            panel.sett_svar("Serveren returnerte ikke noe svar.")

    # ======================================================================
    # Fane: Fyll skjema (/fyll_skjema)
    # ======================================================================
    def _bygg_fyll_skjema_fane(self, forelder):
        pad = {"padx": 12, "pady": 6}
        self.fyll_valgt_fil: str | None = None

        filramme = tema_rammefelt(forelder, "Dokument å fylle fra (påkrevd)")
        filramme.pack(fill="x", **pad)
        filrad = tk.Frame(filramme, bg=BG_PANEL)
        filrad.pack(fill="x", padx=8, pady=8)
        self.fyll_fil_etikett = tk.Label(
            filrad, text="Ingen fil valgt", fg=FG_DEMPET, bg=BG_PANEL, anchor="w"
        )
        self.fyll_fil_etikett.pack(side="left", fill="x", expand=True)
        tema_knapp(
            filrad, "Bla gjennom ...",
            lambda: self._velg_fil_til(self.fyll_fil_etikett, self._sett_fyll_fil),
        ).pack(side="right")

        skjemaramme = tema_rammefelt(
            forelder, "JSON-mal (skjema) — lim inn malen som skal fylles ut"
        )
        skjemaramme.pack(fill="both", **pad)
        skjemahode = tk.Frame(skjemaramme, bg=BG_PANEL)
        skjemahode.pack(fill="x", padx=8, pady=(8, 0))
        tk.Label(
            skjemahode, text="Usikker på formatet? Prøv:",
            fg=FG_DEMPET, bg=BG_PANEL, anchor="w",
        ).pack(side="left")
        tema_knapp(skjemahode, "Sett inn eksempel", self._sett_inn_skjemaeksempel).pack(side="right")
        self.skjema_tekst = tema_tekstfelt(
            skjemaramme, wrap="word", font=("Consolas", 10), height=6
        )
        self.skjema_tekst.pack(fill="both", expand=True, padx=8, pady=8)
        bind_utklippstavle(self.rot, self.skjema_tekst)

        self.fyll_motor_var = tk.StringVar(value="modell")
        self._bygg_motorvelger(forelder, self.fyll_motor_var)

        primaerknapp(forelder, "Fyll skjema", self._send_fyll_skjema).pack(fill="x", **pad)

        self.fyll_panel = SvarPanel(forelder, self.rot, etikett="Utfylt resultat")

    def _sett_fyll_fil(self, sti):
        self.fyll_valgt_fil = sti

    def _sett_inn_skjemaeksempel(self):
        naavaerende = self.skjema_tekst.get("1.0", "end").strip()
        if naavaerende and not messagebox.askyesno(
            "Erstatte malen?", "Dette erstatter det som står i skjemafeltet nå. Fortsette?"
        ):
            return
        # felter/auto flettes fra {feltnavn}-plassholdere; modell fyller
        # tomme verdier. Sett inn eksempelet som passer valgt motor.
        motor = getattr(self, "fyll_motor_var", None)
        flett = motor is not None and motor.get() in ("felter", "auto")
        self.skjema_tekst.delete("1.0", "end")
        self.skjema_tekst.insert("1.0",
                                 EKSEMPEL_SKJEMA_FLETT if flett else EKSEMPEL_SKJEMA)

    def _send_fyll_skjema(self):
        if not self._sjekk_valgt_fil(self.fyll_valgt_fil):
            return
        skjema = self.skjema_tekst.get("1.0", "end").strip()
        if not skjema:
            messagebox.showwarning("Merk", "Lim inn en JSON-mal i skjemafeltet først.")
            return
        # Fang ugyldig JSON lokalt — sparer en serverrunde og gir en
        # feilmelding som peker på nøyaktig hvor malen er ødelagt.
        try:
            json.loads(skjema)
        except json.JSONDecodeError as exc:
            messagebox.showerror("Ugyldig JSON", f"Malen er ikke gyldig JSON: {exc}")
            return
        if not self._oppdater_klient():
            return

        kilde_sti = self.fyll_valgt_fil
        panel = self.fyll_panel
        panel.nullstill("Klargjør filen ...")

        def formatter(data):
            # Selve skjemaet øverst (det brukeren ba om), deretter hele
            # svaret — så både nytte og full sporbarhet er synlig.
            deler = []
            if isinstance(data.get("skjema"), dict):
                motor = data.get("motor")
                deler.append("Utfylt skjema"
                             + (f" (motor: {motor})" if motor else "") + ":")
                deler.append(formater_json(data["skjema"]))
                if data.get("kilde_per_felt"):
                    deler.append("Kilde per felt: "
                                 + ", ".join(f"{k}={v}" for k, v
                                             in data["kilde_per_felt"].items()))
                if data.get("ukjente_felter"):
                    deler.append("Fant ikke (regelen): "
                                 + ", ".join(data["ukjente_felter"]))
                deler.append("")
                deler.append("Fullt svar (JSON):")
            deler.append(formater_json(data))
            return "\n".join(deler)

        motor = self.fyll_motor_var.get()
        self._kjor_foresporsel(
            panel,
            self._fil_foresporsel(
                kilde_sti,
                lambda pdf: self.klient.fyll_skjema(pdf, skjema, skjema_motor=motor)),
            self._standard_suksess(panel, "Skjema utfylt", formatter),
        )

    # ======================================================================
    # Fane: Analyser (/analyser)
    # ======================================================================
    def _bygg_analyser_fane(self, forelder):
        pad = {"padx": 12, "pady": 6}
        self.analyser_valgt_fil: str | None = None

        filramme = tema_rammefelt(forelder, "Dokument å analysere (påkrevd)")
        filramme.pack(fill="x", **pad)
        filrad = tk.Frame(filramme, bg=BG_PANEL)
        filrad.pack(fill="x", padx=8, pady=8)
        self.analyser_fil_etikett = tk.Label(
            filrad, text="Ingen fil valgt", fg=FG_DEMPET, bg=BG_PANEL, anchor="w"
        )
        self.analyser_fil_etikett.pack(side="left", fill="x", expand=True)
        tema_knapp(
            filrad, "Bla gjennom ...",
            lambda: self._velg_fil_til(self.analyser_fil_etikett, self._sett_analyser_fil),
        ).pack(side="right")

        tk.Label(
            forelder,
            text="Deterministisk analyse: felter, alle datoer (med begrunnelse), "
                 "strekkoder/QR, håndskriftdeteksjon og full tekst — uten fritt modellsvar.",
            fg=FG_DEMPET, bg=BG_HOVED, anchor="w", wraplength=700, justify="left",
        ).pack(fill="x", padx=12)

        primaerknapp(forelder, "Analyser", self._send_analyser).pack(fill="x", **pad)

        self.analyser_panel = SvarPanel(forelder, self.rot, etikett="Analyse")

    def _sett_analyser_fil(self, sti):
        self.analyser_valgt_fil = sti

    def _send_analyser(self):
        if not self._sjekk_valgt_fil(self.analyser_valgt_fil):
            return
        if not self._oppdater_klient():
            return

        panel = self.analyser_panel
        panel.nullstill("Klargjør filen ...")

        def formatter(data):
            linjer = []
            felter = data.get("felter")
            if isinstance(felter, dict) and felter:
                linjer.append("Felter:")
                for navn, verdi in felter.items():
                    linjer.append(f"  {navn}: {verdi}")
                linjer.append("")
            linjer.append("Fullt svar (JSON):")
            linjer.append(formater_json(data))
            return "\n".join(linjer)

        self._kjor_foresporsel(
            panel,
            self._fil_foresporsel(self.analyser_valgt_fil,
                                  lambda pdf: self.klient.analyser(pdf)),
            self._standard_suksess(panel, "Analyse fullført", formatter),
        )

    # ======================================================================
    # Fane: Uttrekk (/uttrekk)
    # ======================================================================
    def _bygg_uttrekk_fane(self, forelder):
        pad = {"padx": 12, "pady": 6}
        self.uttrekk_valgt_fil: str | None = None

        filramme = tema_rammefelt(forelder, "Dokument å trekke ut fra (påkrevd)")
        filramme.pack(fill="x", **pad)
        filrad = tk.Frame(filramme, bg=BG_PANEL)
        filrad.pack(fill="x", padx=8, pady=8)
        self.uttrekk_fil_etikett = tk.Label(
            filrad, text="Ingen fil valgt", fg=FG_DEMPET, bg=BG_PANEL, anchor="w"
        )
        self.uttrekk_fil_etikett.pack(side="left", fill="x", expand=True)
        tema_knapp(
            filrad, "Bla gjennom ...",
            lambda: self._velg_fil_til(self.uttrekk_fil_etikett, self._sett_uttrekk_fil),
        ).pack(side="right")

        tk.Label(
            forelder,
            text="Komplett strukturert uttrekk med fast skjema: alle nøkler er alltid "
                 "med, og identifikatorer er kontrollsiffer-validert.",
            fg=FG_DEMPET, bg=BG_HOVED, anchor="w", wraplength=700, justify="left",
        ).pack(fill="x", padx=12)

        primaerknapp(forelder, "Trekk ut", self._send_uttrekk).pack(fill="x", **pad)

        self.uttrekk_panel = SvarPanel(forelder, self.rot, etikett="Uttrekk")

    def _sett_uttrekk_fil(self, sti):
        self.uttrekk_valgt_fil = sti

    def _send_uttrekk(self):
        if not self._sjekk_valgt_fil(self.uttrekk_valgt_fil):
            return
        if not self._oppdater_klient():
            return

        panel = self.uttrekk_panel
        panel.nullstill("Klargjør filen ...")
        self._kjor_foresporsel(
            panel,
            self._fil_foresporsel(self.uttrekk_valgt_fil,
                                  lambda pdf: self.klient.uttrekk(pdf)),
            self._standard_suksess(panel, "Uttrekk fullført"),
        )

    # ======================================================================
    # Fane: Storjobb (/jobb-flyten) — store skannede dokumenter behandlet i
    # bakgrunnen. Statusverdier og feltnavn (kø/pågår/ferdig/feil/avbrutt,
    # sider_ferdig, sider_totalt, sekunder_igjen_estimat) er verifisert
    # mot serverkoden. Etter innsending følges statusen automatisk.
    # ======================================================================
    def _bygg_jobb_fane(self, forelder):
        pad = {"padx": 12, "pady": 6}
        self.jobb_valgt_fil: str | None = None
        self.jobb_id: str | None = None

        filramme = tema_rammefelt(
            forelder, "Stort skannet dokument (ubegrenset antall sider, behandles i bakgrunnen)"
        )
        filramme.pack(fill="x", **pad)
        filrad = tk.Frame(filramme, bg=BG_PANEL)
        filrad.pack(fill="x", padx=8, pady=8)
        self.jobb_fil_etikett = tk.Label(
            filrad, text="Ingen fil valgt", fg=FG_DEMPET, bg=BG_PANEL, anchor="w"
        )
        self.jobb_fil_etikett.pack(side="left", fill="x", expand=True)
        tema_knapp(
            filrad, "Bla gjennom ...",
            lambda: self._velg_fil_til(self.jobb_fil_etikett, self._sett_jobb_fil),
        ).pack(side="right")

        primaerknapp(forelder, "Send inn jobb", self._send_inn_jobb).pack(fill="x", **pad)

        statusramme = tema_rammefelt(forelder, "Jobbstatus (oppdateres automatisk hvert 3. sekund)")
        statusramme.pack(fill="x", **pad)
        self.jobb_id_var = tk.StringVar(value="Ingen jobb sendt inn ennå")
        tk.Label(statusramme, textvariable=self.jobb_id_var, fg=FG_TEKST, bg=BG_PANEL, anchor="w").pack(
            fill="x", padx=8, pady=(8, 4)
        )
        jobb_knapperad = tk.Frame(statusramme, bg=BG_PANEL)
        jobb_knapperad.pack(fill="x", padx=8, pady=(0, 8))
        self.jobb_oppdater_knapp = tema_knapp(jobb_knapperad, "Vis full status", self._oppdater_jobbstatus)
        self.jobb_oppdater_knapp.config(state="disabled")
        self.jobb_oppdater_knapp.pack(side="left")
        self.jobb_tekst_knapp = tema_knapp(jobb_knapperad, "Hent hele teksten", self._hent_jobbtekst)
        self.jobb_tekst_knapp.config(state="disabled")
        self.jobb_tekst_knapp.pack(side="left", padx=(8, 0))
        self.jobb_avbryt_knapp = tema_knapp(jobb_knapperad, "Avbryt jobben", self._avbryt_jobb)
        self.jobb_avbryt_knapp.config(state="disabled")
        self.jobb_avbryt_knapp.pack(side="left", padx=(8, 0))

        sporramme = tema_rammefelt(forelder, "Still spørsmål til jobbens dokument (når jobben er ferdig)")
        sporramme.pack(fill="x", **pad)
        self.jobb_sporsmal = tema_tekstfelt(sporramme, wrap="word", font=("Segoe UI", 10), height=3)
        self.jobb_sporsmal.pack(fill="x", padx=8, pady=8)
        bind_utklippstavle(self.rot, self.jobb_sporsmal)
        self.jobb_spor_knapp = tema_knapp(sporramme, "Spør", self._spor_jobb)
        self.jobb_spor_knapp.config(state="disabled")
        self.jobb_spor_knapp.pack(padx=8, pady=(0, 8), anchor="e")

        self.jobb_panel = SvarPanel(forelder, self.rot, etikett="Jobbsvar")

    def _sett_jobb_fil(self, sti):
        self.jobb_valgt_fil = sti

    def _sett_jobb_id(self, jobb_id):
        self.jobb_id = str(jobb_id)
        self.jobb_id_var.set(f"Jobb-ID: {self.jobb_id}")
        for knapp in (self.jobb_oppdater_knapp, self.jobb_tekst_knapp,
                      self.jobb_avbryt_knapp, self.jobb_spor_knapp):
            knapp.config(state="normal")
        self._planlegg_jobb_poll()

    # -- automatisk statusoppfølging --------------------------------------
    def _planlegg_jobb_poll(self):
        self._stopp_jobb_poll()
        self._jobb_poll_planlagt = self.rot.after(JOBB_POLL_MS, self._poll_jobbstatus)

    def _stopp_jobb_poll(self):
        if self._jobb_poll_planlagt is not None:
            self.rot.after_cancel(self._jobb_poll_planlagt)
            self._jobb_poll_planlagt = None

    def _poll_jobbstatus(self):
        """Lettvekts bakgrunnssjekk som bare oppdaterer statuslinjen —
        rører ikke svarpanelet, så den overskriver aldri noe brukeren
        holder på med. Stopper selv når jobben når en sluttstatus."""
        self._jobb_poll_planlagt = None
        jobb_id = self.jobb_id
        if not jobb_id:
            return

        def arbeider():
            try:
                data = self.klient.jobb_status(jobb_id)
            except Exception:
                # Midlertidig nettverksglipp — prøv igjen ved neste puls
                self.rot.after(0, self._planlegg_jobb_poll)
                return
            self.rot.after(0, self._vis_jobb_pollresultat, data)

        threading.Thread(target=arbeider, daemon=True).start()

    def _vis_jobb_pollresultat(self, data: dict):
        if not isinstance(data, dict) or self.jobb_id is None:
            return
        status = data.get("status", "ukjent")
        deler = [f"Jobb-ID: {self.jobb_id} — status: {status}"]
        if data.get("sider_totalt"):
            ferdig = data.get("sider_ferdig", 0)
            deler.append(f"side {ferdig} av {data['sider_totalt']}")
        if data.get("sekunder_igjen_estimat"):
            deler.append(f"ca. {formater_varighet(data['sekunder_igjen_estimat'])} igjen")
        self.jobb_id_var.set(" — ".join(deler))

        if status in JOBB_AKTIVE_STATUSER:
            self._planlegg_jobb_poll()
            return
        # Sluttstatus: gi tydelig beskjed uten å kreve flere klikk
        if status == "ferdig":
            self.jobb_panel.status_var.set(
                "Jobben er ferdig — hent hele teksten eller still spørsmål under."
            )
        elif status == "feil":
            self.jobb_panel.status_var.set(f"Jobben feilet: {data.get('feil', 'ukjent årsak')}")
        elif status == "avbrutt":
            self.jobb_panel.status_var.set("Jobben ble avbrutt.")

    def _send_inn_jobb(self):
        if not self._sjekk_valgt_fil(self.jobb_valgt_fil):
            return
        if not self._oppdater_klient():
            return

        panel = self.jobb_panel
        panel.nullstill("Laster opp ...")

        def etterpaa(data):
            jobb_id = data.get("jobb_id")
            if jobb_id:
                self._sett_jobb_id(jobb_id)
            else:
                panel.status_var.set(
                    "Sendt inn, men uten jobb_id i svaret — se rått svar under"
                )

        self._kjor_foresporsel(
            panel,
            self._fil_foresporsel(self.jobb_valgt_fil,
                                  lambda pdf: self.klient.send_fil("/jobb", pdf)),
            self._standard_suksess(panel, "Jobb sendt inn — statusen følges automatisk",
                                   etterpaa=etterpaa),
        )

    def _oppdater_jobbstatus(self):
        if not self.jobb_id or not self._oppdater_klient():
            return
        panel = self.jobb_panel
        panel.nullstill("Sjekker status ...")
        jobb_id = self.jobb_id

        def foresporsel_fn(tidtaker):
            tidtaker["start"] = time.perf_counter()
            return self.klient.jobb_status(jobb_id)

        self._kjor_foresporsel(
            panel, foresporsel_fn, self._standard_suksess(panel, "Status oppdatert"),
        )

    def _hent_jobbtekst(self):
        if not self.jobb_id or not self._oppdater_klient():
            return
        panel = self.jobb_panel
        panel.nullstill("Henter hele teksten ...")
        jobb_id = self.jobb_id

        def foresporsel_fn(tidtaker):
            tidtaker["start"] = time.perf_counter()
            return self.klient.jobb_tekst(jobb_id)

        self._kjor_foresporsel(
            panel, foresporsel_fn,
            self._standard_suksess(
                panel, "Hele teksten hentet",
                formatter=lambda data: data.get("tekst") or formater_json(data),
            ),
        )

    def _avbryt_jobb(self):
        if not self.jobb_id or not self._oppdater_klient():
            return
        panel = self.jobb_panel
        panel.nullstill("Avbryter ...")
        jobb_id = self.jobb_id

        def foresporsel_fn(tidtaker):
            tidtaker["start"] = time.perf_counter()
            return self.klient.jobb_avbryt(jobb_id)

        def etterpaa(_data):
            self._stopp_jobb_poll()
            for knapp in (self.jobb_oppdater_knapp, self.jobb_tekst_knapp,
                          self.jobb_avbryt_knapp, self.jobb_spor_knapp):
                knapp.config(state="disabled")

        self._kjor_foresporsel(
            panel, foresporsel_fn,
            self._standard_suksess(panel, "Jobb avbrutt", etterpaa=etterpaa),
        )

    def _spor_jobb(self):
        if not self.jobb_id:
            return
        sporsmal = self.jobb_sporsmal.get("1.0", "end").strip()
        if not sporsmal:
            messagebox.showwarning("Merk", "Skriv et spørsmål først.")
            return
        if not self._oppdater_klient():
            return
        panel = self.jobb_panel
        panel.nullstill("Sender ...")
        jobb_id = self.jobb_id

        def foresporsel_fn(tidtaker):
            tidtaker["start"] = time.perf_counter()
            return self.klient.spor_uten_fil(sporsmal, jobb_id=jobb_id)

        self._kjor_foresporsel(
            panel, foresporsel_fn,
            lambda data, brukt: self._haandter_spor_suksess(panel, data, brukt),
        )

    # ======================================================================
    # Fane: Serverinfo (/hjelp, /openapi.json, /dokumentasjon)
    # ======================================================================
    def _bygg_info_fane(self, forelder):
        pad = {"padx": 12, "pady": 6}

        lenkeramme = tema_rammefelt(forelder, "Dokumentasjon og status")
        lenkeramme.pack(fill="x", **pad)
        rad = tk.Frame(lenkeramme, bg=BG_PANEL)
        rad.pack(fill="x", padx=8, pady=8)
        tema_knapp(rad, "Åpne Swagger i nettleseren", self._aapne_dokumentasjon).pack(side="left")
        tema_knapp(rad, "Hent OpenAPI-spesifikasjonen", self._hent_openapi).pack(side="left", padx=(8, 0))
        tema_knapp(rad, "Sjekk serverstatus (/hjelp)", self._sjekk_hjelp).pack(side="left", padx=(8, 0))

        self.info_panel = SvarPanel(forelder, self.rot, etikett="Svar")

    def _aapne_dokumentasjon(self):
        if not self._oppdater_klient():
            return
        webbrowser.open(self.klient.base_url + "/dokumentasjon")

    def _hent_openapi(self):
        if not self._oppdater_klient():
            return
        panel = self.info_panel
        panel.nullstill("Henter OpenAPI-spesifikasjonen ...")

        def foresporsel_fn(tidtaker):
            tidtaker["start"] = time.perf_counter()
            return self.klient.openapi()

        self._kjor_foresporsel(
            panel, foresporsel_fn,
            self._standard_suksess(panel, "OpenAPI-spesifikasjon hentet"),
        )

    def _sjekk_hjelp(self):
        if not self._oppdater_klient():
            return
        panel = self.info_panel
        panel.nullstill("Sjekker serverstatus ...")

        def foresporsel_fn(tidtaker):
            tidtaker["start"] = time.perf_counter()
            return self.klient.hjelp()

        def formatter(data):
            # De viktigste driftsfeltene løftes øverst; alt vises under.
            linjer = []
            if data.get("borealis"):
                linjer.append(f"Borealis: {data['borealis']}")
            if data.get("borealis_modell"):
                linjer.append(f"Modell: {data['borealis_modell']}")
            if data.get("sikkerhet"):
                linjer.append(f"Sikkerhet: {data['sikkerhet']}")
            if linjer:
                linjer.append("")
                linjer.append("Fullt svar (JSON):")
            linjer.append(formater_json(data))
            return "\n".join(linjer)

        self._kjor_foresporsel(
            panel, foresporsel_fn,
            self._standard_suksess(panel, "Serveren svarte", formatter),
        )


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from delt import enkeltinstans

    # R141: panelet er den ENESTE inngangen, så et dobbelt klikk på
    # snarveien er den mest sannsynlige måten alt startes to ganger på.
    # Hvert panel har sine egne start/stopp-knapper, så to av dem
    # betyr to vakthunder, to servere som deler det samme 8 GB-kortet,
    # og en stoppknapp som dreper den andres prosesser.
    #
    # Meldingen må i et VINDU: panelet kjøres med pythonw, uten konsoll,
    # så en print til stderr forsvinner sporløst — og brukeren ville
    # bare sett at ingenting skjedde.
    _laas = enkeltinstans.ta("kontrollpanel")
    if _laas is None:
        _skjult = tk.Tk()
        _skjult.withdraw()
        messagebox.showinfo(
            "Kontrollpanelet kjører allerede",
            "Kontrollpanelet er allerede åpent — se etter vinduet, eller "
            "i oppgavelinja.\n\n"
            "To paneler startes ikke, fordi hvert av dem har sine egne "
            "start- og stoppknapper: to vakthunder ville startet hver "
            "sin server på det samme GPU-kortet, og en stoppknapp ville "
            "drept den andres prosesser.")
        _skjult.destroy()
        sys.exit(0)
    try:
        rot = tk.Tk()
        app = DokumentKlientApp(rot)
        rot.mainloop()
    finally:
        _laas.frigi()

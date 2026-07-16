"""
UiPath-klart analyse-API — kjører lokalt på din maskin, uten Docker.

Forskjellen fra lokal_api.py: dette endepunktet tar imot selve FILEN
(multipart/form-data upload), akkurat slik UiPath / Power Automate /
enhver ekstern klient sender den — ikke en filsti. Det er DENNE
kontrakten et RPA-verktøy bruker.

Flyt:
    UiPath  --(HTTP POST, fil vedlagt)-->  /analyser
                                              |
                              leser PDF-tekstlaget (PyMuPDF)
                                              |
                        deterministisk uttrekk (mod11, anti-hallusinering)
                                              |
    UiPath  <--(JSON: felter + trenger_ocr)--

For tekst-PDF-er svarer det med felter med en gang. For skannede
bilde-PDF-er (uten tekstlag) svarer det trenger_ocr=true og forklarer
at den fulle Docker-pipelinen med OCR-modeller trengs — ærlig, ikke
tomt svar.

Kun standardbibliotek + PyMuPDF. Start:
    python skript/uipath_api.py
Så, fra UiPath: HTTP Request-aktivitet, POST http://localhost:8600/analyser,
med filen som "attachment"/multipart-felt "fil".
"""
import io
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)

from delt.tekstuttrekk import utvid_entiteter

PORT = int(os.environ.get("UIPATH_API_PORT", "8600"))
MAKS_BYTES = int(os.environ.get("MAKS_OPPLASTING_MB", "50")) * 1024 * 1024


# ------------------------------------------------------------------ #
#  Multipart-parsing (kun stdlib) — henter ut opplastet fil           #
# ------------------------------------------------------------------ #

def _hent_fil_fra_multipart(body: bytes, content_type: str):
    """Returnerer (filnavn, filbytes) fra en multipart/form-data-body,
    eller (None, None) hvis ingen fil finnes."""
    if "boundary=" not in content_type:
        return None, None
    boundary = content_type.split("boundary=", 1)[1].strip().strip('"')
    skille = ("--" + boundary).encode()
    for del_ in body.split(skille):
        if b"filename=" not in del_:
            continue
        # Skill hoder fra innhold ved første tomme linje (\r\n\r\n)
        if b"\r\n\r\n" not in del_:
            continue
        hoder, _, innhold = del_.partition(b"\r\n\r\n")
        # filnavn ut av Content-Disposition
        filnavn = "opplastet.pdf"
        for linje in hoder.split(b"\r\n"):
            if b"filename=" in linje:
                try:
                    filnavn = linje.split(b'filename="', 1)[1].split(b'"', 1)[0].decode("utf-8", "replace")
                except Exception:
                    pass
        # fjern etterfølgende \r\n før neste boundary
        innhold = innhold.rstrip(b"\r\n")
        return filnavn, innhold
    return None, None


# ------------------------------------------------------------------ #
#  Analyse                                                            #
# ------------------------------------------------------------------ #

def analyser_bytes(filnavn: str, data: bytes) -> dict:
    if not data:
        return {"ok": False, "feil": "Tom fil"}
    if not filnavn.lower().endswith(".pdf"):
        return {"ok": False, "feil": "Kun PDF støttes"}
    try:
        import fitz
    except ImportError:
        return {"ok": False, "feil": "PyMuPDF (fitz) ikke installert"}
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        return {"ok": False, "feil": f"Ugyldig/korrupt PDF: {exc}"}

    sider = []
    total_tekst = 0
    for i, side in enumerate(doc):
        tekst = side.get_text() or ""
        total_tekst += len(tekst.strip())
        sider.append({"side_nummer": i, "tegn": len(tekst),
                      "felter": utvid_entiteter(tekst, {})})
    doc.close()

    # Aggreger på tvers av sider (første ikke-tomme verdi per felt)
    felter = {}
    for s in sider:
        for k, v in s["felter"].items():
            if k not in felter and v not in (None, ""):
                felter[k] = v

    # Skannet bilde uten tekstlag → vær ærlig: trenger ekte OCR
    if total_tekst < 20:
        return {
            "ok": True,
            "filnavn": filnavn,
            "antall_sider": len(sider),
            "trenger_ocr": True,
            "felter": {},
            "melding": ("Dokumentet har ikke tekstlag (trolig skannet bilde). "
                        "Deterministisk uttrekk kan ikke lese bilder — send dette "
                        "til den fulle pipelinen (POST /last-opp/ i Docker-oppsettet) "
                        "som kjører ekte OCR med modeller."),
        }

    return {
        "ok": True,
        "filnavn": filnavn,
        "antall_sider": len(sider),
        "trenger_ocr": False,
        "kilde": "deterministisk_tekstlag",
        "felter": felter,
        "per_side": sider,
    }


# ------------------------------------------------------------------ #
#  HTTP                                                               #
# ------------------------------------------------------------------ #

class Handler(BaseHTTPRequestHandler):
    def _svar(self, kode, data):
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(kode)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path.rstrip("/") in ("", "/hjelp"):
            return self._svar(200, {
                "tjeneste": "NAV UiPath-klart analyse-API",
                "endepunkt": "POST /analyser  (multipart/form-data, felt: fil)",
                "uipath": "HTTP Request → Method POST → Attachment/Body: filen som multipart-felt 'fil'",
                "svar": "JSON med 'felter' og 'trenger_ocr'",
            })
        return self._svar(404, {"ok": False, "feil": "Bruk POST /analyser"})

    def do_POST(self):
        if self.path.rstrip("/") != "/analyser":
            return self._svar(404, {"ok": False, "feil": "Bruk POST /analyser"})
        lengde = int(self.headers.get("Content-Length", "0"))
        if lengde > MAKS_BYTES:
            return self._svar(413, {"ok": False, "feil": f"Filen er for stor (maks {MAKS_BYTES//1024//1024} MB)"})
        body = self.rfile.read(lengde) if lengde else b""
        ct = self.headers.get("Content-Type", "")

        if "multipart/form-data" in ct:
            filnavn, data = _hent_fil_fra_multipart(body, ct)
            if data is None:
                return self._svar(400, {"ok": False, "feil": "Ingen fil funnet i multipart-body (felt 'fil')"})
        else:
            # tillat òg rå PDF-bytes i body (Content-Type: application/pdf)
            filnavn, data = "opplastet.pdf", body

        resultat = analyser_bytes(filnavn, data)
        return self._svar(200 if resultat.get("ok") else 400, resultat)

    def log_message(self, fmt, *args):
        # Én ryddig linje per forespørsel så du ser at UiPath treffer
        print(f"  [{self.command}] {self.path} → {args[1] if len(args) > 1 else ''}")


def main():
    try:
        server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    except OSError as exc:
        print(f"\n!!! Port {PORT} opptatt: {exc}")
        print("    Bruk en annen: set UIPATH_API_PORT=8601 && python skript/uipath_api.py\n")
        return
    strek = "=" * 64
    print(strek)
    print("  NAV UiPath-klart analyse-API — SERVEREN KJØRER NÅ")
    print(strek)
    print("  IKKE lukk dette vinduet mens UiPath tester.")
    print(f"  Endepunkt for UiPath:  POST  http://<din-ip>:{PORT}/analyser")
    print(f"  Fra samme maskin:      POST  http://localhost:{PORT}/analyser")
    print("  Send filen som multipart/form-data, feltnavn: fil")
    print("  Svar: JSON med 'felter' og 'trenger_ocr'.")
    print("  Avslutt med Ctrl+C.")
    print(strek + "\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStoppet.")


if __name__ == "__main__":
    main()

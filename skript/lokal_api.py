"""
Lokal analyse-API — kjører rett på din maskin, uten Docker/modeller.

Bruker det DETERMINISTISKE uttrekkslaget (delt/tekstuttrekk.py) med alle
revisjonsfiksene fra i dag (mod11, anti-hallusinering, deterministisk
fylke). Leser tekstlaget i PDF-en via PyMuPDF — ingen GPU, ingen
container, svar på millisekunder.

Bruk:
    python skript/lokal_api.py
    # så, i en nettleser eller curl:
    #   http://localhost:8500/analyser?sti=D:/nav/data/inntak/2254711543.pdf
    # eller POST JSON:  {"sti": "C:/full/sti/til/fil.pdf"}

Kun standardbibliotek + PyMuPDF (allerede installert). Ingen FastAPI/
uvicorn nødvendig — garantert at det starter.

MERK: leser PDF-ens tekstlag. For skannede bilde-PDF-er (uten tekstlag)
kreves OCR-modellene (Docker-pipelinen) — da sier svaret det tydelig.
"""
import io
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

# Windows-terminaler bruker ofte en kodeside (cp1256/cp1252) som ikke kan
# skrive æ/ø/å → tving UTF-8 på konsollen så norske meldinger ikke krasjer.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Gjør delt/-pakken importerbar uansett hvor skriptet kjøres fra
ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)

from delt.tekstuttrekk import utvid_entiteter

PORT = int(os.environ.get("LOKAL_API_PORT", "8500"))


def analyser_fil(sti: str) -> dict:
    """Leser PDF-tekst og trekker ut felter. Returnerer et resultat-dict."""
    sti = sti.strip().strip('"').strip("'")
    if not sti:
        return {"ok": False, "feil": "Tom filsti"}
    if not os.path.isfile(sti):
        return {"ok": False, "feil": f"Fil finnes ikke: {sti}"}
    if not sti.lower().endswith(".pdf"):
        return {"ok": False, "feil": "Kun PDF støttes i lokal-modus"}

    try:
        import fitz
    except ImportError:
        return {"ok": False, "feil": "PyMuPDF (fitz) ikke installert — kjør: pip install pymupdf"}

    try:
        doc = fitz.open(sti)
    except Exception as exc:
        return {"ok": False, "feil": f"Kunne ikke åpne PDF: {exc}"}

    sider = []
    samlet_tekst = []
    for i, side in enumerate(doc):
        tekst = side.get_text() or ""
        samlet_tekst.append(tekst)
        felter = utvid_entiteter(tekst, {})
        sider.append({
            "side_nummer": i,
            "tegn_i_tekstlag": len(tekst),
            "felter": felter,
        })
    doc.close()

    total_tekst = "".join(samlet_tekst)
    if len(total_tekst.strip()) < 20:
        return {
            "ok": True,
            "advarsel": "PDF-en har lite/ingen tekstlag — trolig skannet bilde. "
                        "Ekte OCR (Docker-pipelinen med modeller) trengs for slike. "
                        "Det deterministiske laget fant lite fordi det ikke er tekst å lese.",
            "fil": sti,
            "antall_sider": len(sider),
            "sider": sider,
        }

    # Aggreger felter på tvers av sider: første ikke-tomme verdi per felt
    aggregert = {}
    for s in sider:
        for k, v in s["felter"].items():
            if k not in aggregert and v not in (None, ""):
                aggregert[k] = v

    return {
        "ok": True,
        "fil": sti,
        "antall_sider": len(sider),
        "felter": aggregert,          # samlet forretningskontrakt
        "per_side": sider,            # detaljer per side
    }


class Handler(BaseHTTPRequestHandler):
    def _svar(self, kode: int, data: dict):
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(kode)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/hjelp"):
            return self._svar(200, {
                "tjeneste": "NAV lokal analyse-API",
                "bruk_GET": "/analyser?sti=<full-sti-til-pdf>",
                "bruk_POST": 'POST /analyser  body: {"sti": "C:/.../fil.pdf"}',
                "eksempel": f"http://localhost:{PORT}/analyser?sti={os.path.join(ROT, 'data', 'inntak', '2254711543.pdf').replace(os.sep, '/')}",
            })
        if parsed.path == "/analyser":
            q = parse_qs(parsed.query)
            sti = unquote(q.get("sti", [""])[0])
            resultat = analyser_fil(sti)
            return self._svar(200 if resultat.get("ok") else 400, resultat)
        return self._svar(404, {"ok": False, "feil": "Ukjent sti. Bruk /analyser"})

    def do_POST(self):
        if urlparse(self.path).path != "/analyser":
            return self._svar(404, {"ok": False, "feil": "Bruk POST /analyser"})
        lengde = int(self.headers.get("Content-Length", "0"))
        raa = self.rfile.read(lengde) if lengde else b"{}"
        try:
            data = json.loads(raa.decode("utf-8"))
            sti = data.get("sti", "")
        except Exception:
            # tillat òg ren tekst-body med bare stien
            sti = raa.decode("utf-8", "replace").strip()
        resultat = analyser_fil(sti)
        return self._svar(200 if resultat.get("ok") else 400, resultat)

    def log_message(self, *_):
        pass   # stille — ikke spam terminalen


def main():
    eksempel = os.path.join(ROT, "data", "inntak", "2254711543.pdf").replace(os.sep, "/")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as exc:
        print(f"\n!!! Kunne ikke starte på port {PORT}: {exc}")
        print(f"    Porten er trolig i bruk. Prøv en annen port:")
        print(f"    set LOKAL_API_PORT=8600 && python skript/lokal_api.py\n")
        return

    strek = "=" * 62
    print(strek)
    print("  NAV lokal analyse-API — SERVEREN KJØRER NÅ")
    print(strek)
    print("  IKKE lukk dette vinduet mens du tester.")
    print("  Åpne nettleseren (i et ANNET vindu) på:")
    print(f"     http://localhost:{PORT}/analyser?sti={eksempel}")
    print("  Bytt sti= til din egen PDF.")
    print("  (Åpner nettleseren automatisk om 1 sekund ...)")
    print("  Avslutt serveren med Ctrl+C.")
    print(strek + "\n")

    # Åpne nettleseren automatisk på et ekte eksempel så brukeren SER svaret
    try:
        import threading, webbrowser
        url = f"http://localhost:{PORT}/analyser?sti={eksempel}"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStoppet.")


if __name__ == "__main__":
    main()

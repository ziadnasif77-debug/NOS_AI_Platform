#!/usr/bin/env python3
"""
nav_klient.py — enkel klient mot NAV dokument-API-et (POST /dokument).

Kjøres fra HVILKEN SOM HELST maskin over tunnelen. Eneste avhengighet
er `requests` (pip install requests).

ETT kall, og du velger selv hva som skal gjøres. Dokumentet leses ÉN
gang på serveren; bare delene du slår på kjøres. De raske delene er PÅ
som standard, de som koster modellkall er AV til du ber om dem — så det
raske forblir raskt.

OPPSETT (gjør dette én gang):
    set NAV_URL=https://din-tunnel.trycloudflare.com     (Windows)
    set NAV_NOKKEL=<API_NOKKEL fra .env på servermaskinen>

    export NAV_URL=...        (macOS/Linux)
    export NAV_NOKKEL=...

BRUK:
    python nav_klient.py brev.pdf
    python nav_klient.py brev.pdf --struktur
    python nav_klient.py brev.pdf --sporsmal "Hva er beløpet?"
    python nav_klient.py brev.pdf --skjema mal.json
    python nav_klient.py brev.pdf --korriger --ingen-tekst
    python nav_klient.py --status

MERK: tunneladressen er NY hver gang tunnelen startes på nytt. Hent den
fra Kontrollpanelet på servermaskinen (raden under «Tunnel»).
"""
import argparse
import json
import os
import sys

try:
    import requests
except ImportError:
    sys.exit("Mangler «requests». Installer med:  pip install requests")

STANDARD_URL = "http://127.0.0.1:8600"


def _grunnadresse() -> str:
    url = (os.environ.get("NAV_URL") or STANDARD_URL).strip().rstrip("/")
    # tåler at man limer inn hele endepunktet i stedet for bare verten
    for hale in ("/dokument/operasjoner", "/dokument", "/spor",
                 "/jobb", "/hjelp"):
        if url.endswith(hale):
            url = url[: -len(hale)]
    return url


def _hoder(korr: str = None) -> dict:
    h = {}
    nokkel = (os.environ.get("NAV_NOKKEL") or "").strip()
    if nokkel:
        h["X-API-Key"] = nokkel
    # Sporing på tvers av tjenester: sender du en egen ID, følges kallet
    # ditt gjennom serverens logg under nøyaktig den. Ellers lager
    # serveren en og gir den tilbake i X-Correlation-ID-svarhodet.
    if korr:
        h["X-Correlation-ID"] = korr
    return h


def status() -> int:
    """Er serveren oppe, og hva er den klar til?"""
    r = requests.get(f"{_grunnadresse()}/hjelp", headers=_hoder(), timeout=30)
    r.raise_for_status()
    d = r.json()
    kap = d.get("kapasitet") or {}
    print(f"Tjeneste  : {d.get('tjeneste')}  (API {d['versjon']['api']})")
    print(f"Borealis  : {d.get('borealis')}   OCR: "
          f"{(d.get('ocr') or {}).get('ocr_motor_i_bruk')}")
    print(f"Kapasitet : {kap.get('grense')} samtidige "
          f"(begrenset av {kap.get('binder')}), {kap.get('i_arbeid')} i arbeid")
    print(f"Sikkerhet : {d.get('sikkerhet')}")
    return 0


def send(sti: str, valg: dict, sporsmal: str, mal: dict, tidsavbrudd: int):
    felter = {k: ("ja" if v else "nei") for k, v in valg.items()}
    if sporsmal:
        felter["sporsmal"] = sporsmal
    if mal is not None:
        felter["skjema_mal"] = json.dumps(mal, ensure_ascii=False)

    with open(sti, "rb") as fil:
        r = requests.post(
            f"{_grunnadresse()}/dokument",
            headers=_hoder(),
            files={"fil": (os.path.basename(sti), fil,
                           "application/octet-stream")},
            data=felter,
            timeout=tidsavbrudd,
        )

    # Korrelasjons-ID-en serveren brukte — oppgi den til support ved feil
    korr = r.headers.get("X-Correlation-ID", "?")
    if r.status_code == 401:
        sys.exit("401: feil eller manglende API-nøkkel. Sett NAV_NOKKEL "
                 "(verdien står som API_NOKKEL i .env på servermaskinen).")
    if r.status_code == 503:
        # Serveren er ærlig om kø og oppvarming — vis det, ikke en traceback
        sys.exit(f"503: {r.json().get('feil')}\n"
                 f"Prøv igjen om {r.headers.get('Retry-After', '30')} sekunder.")
    if r.status_code >= 400:
        d = {}
        try:
            d = r.json()
        except ValueError:
            pass
        linjer = [f"HTTP {r.status_code}: {d.get('feil') or r.text[:300]}"]
        # RFC 9457: vis HVILKET felt som er galt, når serveren sier det
        for e in (d.get("problem") or {}).get("errors") or []:
            linjer.append(f"  felt {e.get('pointer')}: {e.get('message')}")
        linjer.append(f"Referanse (uuid) for support: {d.get('uuid') or korr}")
        sys.exit("\n".join(linjer))
    return r.json()


def skriv_ut(d: dict) -> None:
    print("=" * 62)
    print(f"Fil       : {d.get('filnavn')}   ({d.get('antall_tegn')} tegn)")
    kval = d.get("kvalitet") or {}
    print(f"OCR brukt : {kval.get('ocr_brukt')}   motorer: "
          f"{kval.get('ocr_motorer') or '—'}")
    print(f"Tid       : {d.get('tid_sekunder')} s"
          f"{'  (fra hurtigbuffer)' if d.get('fra_cache') else ''}")

    f = d.get("felter")
    if f:
        dd = f.get("dokumentdato") or {}
        print("-" * 62)
        if dd.get("dato"):
            per = dd.get("periode") or {}
            spenn = ("" if per.get("fra") == per.get("til")
                     else f"   (filen dekker {per.get('fra')} – {per.get('til')})")
            print(f"Dokumentets dato: {dd['dato']}  [{dd.get('type')}, "
                  f"sikkerhet: {dd.get('konfidens')}]{spenn}")
        else:
            print("Dokumentets dato: ikke funnet (datoene hører til innholdet)")
        if f.get("felter"):
            print("Felter          :", f["felter"])

    s = d.get("struktur")
    if s:
        print("-" * 62)
        print("Identifikatorer :", s.get("identifikatorer"))
        print("Beløp           :", [b["verdi"] for b in s.get("belop", [])])
        print("Datoer          :", [x.get("dato") for x in s.get("datoer", [])])

    sv = d.get("svar")
    if sv:
        print("-" * 62)
        if sv.get("ok"):
            print(f"Svar            : {sv['svar']}")
            if not sv.get("tall_verifisert", True):
                print("  ADVARSEL: svaret har tall som ikke står ordrett "
                      "i dokumentet")
        else:
            print(f"Svar FEILET     : {sv.get('feil')}")

    sk = d.get("skjema")
    if sk:
        print("-" * 62)
        if sk.get("ok"):
            print("Utfylt skjema   :")
            print(json.dumps(sk["skjema"], ensure_ascii=False, indent=2))
            if sk.get("avvik"):
                print("Avvik (kodevalidering):", sk["avvik"])
        else:
            print(f"Skjema FEILET   : {sk.get('feil')}")

    if d.get("korrigert_tekst"):
        print("-" * 62)
        print("Korrigert tekst :")
        print(d["korrigert_tekst"])

    if d.get("tekst"):
        print("-" * 62)
        print("Utlest tekst    :")
        print(d["tekst"])

    for a in kval.get("advarsler") or []:
        print(f"! {a}")
    print("=" * 62)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Klient mot NAV dokument-API (POST /dokument)")
    p.add_argument("fil", nargs="?", help="dokumentet (PDF, bilde, DOCX, TXT …)")
    p.add_argument("--status", action="store_true",
                   help="vis serverstatus og avslutt")
    p.add_argument("--sporsmal", help="still et spørsmål om dokumentet (modell)")
    p.add_argument("--skjema", metavar="MAL.json",
                   help="fyll ut din egen JSON-mal fra dokumentet (modell)")
    p.add_argument("--korriger", action="store_true",
                   help="LLM-korrigert OCR-tekst (modell)")
    p.add_argument("--struktur", action="store_true",
                   help="komplett strukturert uttrekk (raskt)")
    p.add_argument("--ingen-felter", action="store_true",
                   help="hopp over felt-/datouttrekket")
    p.add_argument("--ingen-tekst", action="store_true",
                   help="ikke ta med fullteksten i svaret")
    p.add_argument("--json", action="store_true", help="skriv rått JSON-svar")
    p.add_argument("--tidsavbrudd", type=int, default=600,
                   help="sekunder å vente (standard 600)")
    a = p.parse_args()

    if a.status:
        return status()
    if not a.fil:
        p.error("oppgi en fil (eller --status)")
    if not os.path.isfile(a.fil):
        sys.exit(f"Finner ikke filen: {a.fil}")

    mal = None
    if a.skjema:
        with open(a.skjema, encoding="utf-8") as f:
            mal = json.load(f)

    valg = {
        "tekst": not a.ingen_tekst,
        "felter": not a.ingen_felter,
        "struktur": a.struktur,
        "svar": bool(a.sporsmal),
        "skjema": mal is not None,
        "korriger": a.korriger,
    }
    svar = send(a.fil, valg, a.sporsmal, mal, a.tidsavbrudd)
    if a.json:
        print(json.dumps(svar, ensure_ascii=False, indent=2))
    else:
        skriv_ut(svar)
    return 0


if __name__ == "__main__":
    sys.exit(main())

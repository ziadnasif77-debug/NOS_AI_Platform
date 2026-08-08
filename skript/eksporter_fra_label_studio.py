"""
Eksporterer korreksjoner fra Label Studio og konverterer til
treningsformat for finjustering av TrOCR-NorHand (håndskrift).

Bare tekstkorreksjonene (textarea) hentes ut — det er den eneste modellen
serveren faktisk bruker. Tidligere ble også dokumenttype-valg (choices)
eksportert til NB-BERT, men den modellen er fjernet (2026-07-21).

Kjøres MANUELT: `make eksporter-korreksjoner`, eller via
`kjor_treningslop.py`. Det finnes ingen automatisk «etter N
korreksjoner»-utløser i koden (den påstanden var aldri implementert).
"""
import os
import json
import shutil

import requests
from pathlib import Path
from datetime import datetime

# UTF-8-trygg utskrift (se finjuster.py): norsk skal ikke krasje som subprocess.
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LABEL_STUDIO_URL = os.environ.get("LABEL_STUDIO_URL", "http://localhost:8080")
LABEL_STUDIO_API_KEY = os.environ.get("LABEL_STUDIO_API_KEY", "")
FINJUSTERING_STI = os.environ.get("FINJUSTERING_STI", "./data/finjustering")
# Bildene Label Studio viser ble kopiert hit av send_til_label_studio.py
# (GJENNOMGANG_STI/bilder/<id>.png), og eksponert som URL-en
# «/data/local-files/?d=bilder/<id>.png». Vi må oversette den URL-en
# tilbake til den faktiske filstien, ellers får finjuster.py en URL den
# ikke kan åpne → trente før på blanke bilder (R-fiks 2026-07-20).
GJENNOMGANG_STI = os.environ.get("GJENNOMGANG_STI", "./data/gjennomgang")


def _arkivmappe() -> Path:
    return Path(FINJUSTERING_STI) / "bilder"


def _arkiver_bilde(kilde: str, oppgave_id) -> str:
    """Kopierer treningsbildet INN i korreksjonsarkivet.

    `data/gjennomgang/` er en KØ med oppbevaringsfrist (30 dager,
    `rydd_gjennomgang.py`). `data/finjustering/` er dokumentert som
    permanent. Et arkiv som PEKER inn i køen er derfor tomt den dagen
    fristen faktisk håndheves — og `finjuster.py` stopper med
    FileNotFoundError på hver eneste kjøring etterpå, fordi de ødelagte
    oppføringene ligger i et arkiv som aldri ryddes (R170).

    De to policyene kan ikke begge være sanne om samme fil. Arkivet
    eier nå sine egne bilder, og køen kan tømmes uten å røre dem."""
    if not kilde or not os.path.isfile(kilde):
        return kilde or ""
    mappe = _arkivmappe()
    mappe.mkdir(parents=True, exist_ok=True)
    maal = mappe / f"oppgave_{oppgave_id}{Path(kilde).suffix or '.png'}"
    if not maal.exists():
        shutil.copy2(kilde, maal)
    return str(maal)


def _kildenokkel(oppgave: dict) -> str:
    """Hvilket dokument rettingen stammer fra.

    Uten en slik nøkkel kan ingen finne igjen hvilke rader i arkivet
    som gjelder en bestemt person — og da er retten til sletting (GDPR
    art. 17) ikke teknisk mulig å oppfylle, uansett hva en policy sier.
    Se `skript/slett_person.py`."""
    data = oppgave.get("data") or {}
    for felt in ("fil_id", "dokument_id", "filnavn", "kilde"):
        if data.get(felt):
            return str(data[felt])
    bilde = data.get("bilde") or ""
    return Path(bilde).stem if bilde else ""


def _lokal_bildesti(bilde_url: str) -> str:
    """Oversetter en Label Studio local-files-URL til en ekte filsti.
    «/data/local-files/?d=bilder/x.png» → «<GJENNOMGANG_STI>/bilder/x.png».
    Ukjente former returneres uendret (kan allerede være en filsti)."""
    if not bilde_url:
        return ""
    if "?d=" in bilde_url:
        rel = bilde_url.split("?d=", 1)[1].split("&", 1)[0]
        try:
            from urllib.parse import unquote
            rel = unquote(rel)
        except Exception:
            pass
        return str(Path(GJENNOMGANG_STI) / rel)
    return bilde_url

HEADERS = {
    "Authorization": f"Token {LABEL_STUDIO_API_KEY}",
    "Content-Type": "application/json",
}


def hent_prosjekter() -> list:
    """Henter alle Label Studio-prosjekter."""
    try:
        svar = requests.get(
            f"{LABEL_STUDIO_URL}/api/projects/",
            headers=HEADERS,
            timeout=10
        )
        svar.raise_for_status()
        return svar.json().get("results", [])
    except requests.RequestException as feil:
        print(f"Kunne ikke hente prosjekter: {feil}")
        return []


def hent_fullforte_oppgaver(prosjekt_id: int) -> list:
    """Henter oppgavene som HAR annoteringer i ett prosjekt (paginert).

    MERK (Label Studio 1.23): liste-endepunktet /api/tasks returnerer IKKE
    lenger selve annoteringsinnholdet (feltet «annotations» er None) —
    før denne fiksen eksporterte vi derfor alltid 0, uansett hvor mye de
    ansatte hadde rettet. Innholdet hentes nå per oppgave i
    hent_annoteringer()."""
    oppgaver = []
    side = 1
    try:
        while True:
            svar = requests.get(
                f"{LABEL_STUDIO_URL}/api/tasks"
                f"?project={prosjekt_id}&page={side}&page_size=200",
                headers=HEADERS,
                timeout=30
            )
            svar.raise_for_status()
            bunke = svar.json().get("tasks", [])
            oppgaver.extend(o for o in bunke
                            if o.get("total_annotations", 0) > 0)
            if len(bunke) < 200:
                return oppgaver
            side += 1
    except requests.RequestException as feil:
        print(f"Kunne ikke hente oppgaver for prosjekt {prosjekt_id}: {feil}")
        return oppgaver


def hent_annoteringer(oppgave_id: int) -> list:
    """Henter selve annoteringene for én oppgave — det verifisert
    fungerende endepunktet i Label Studio 1.23."""
    try:
        svar = requests.get(
            f"{LABEL_STUDIO_URL}/api/tasks/{oppgave_id}/annotations/",
            headers=HEADERS,
            timeout=15
        )
        svar.raise_for_status()
        return svar.json()
    except requests.RequestException as feil:
        print(f"Kunne ikke hente annoteringer for oppgave {oppgave_id}: {feil}")
        return []


def konverter_til_trocr_format(oppgave: dict) -> dict | None:
    """
    Konverterer en Label Studio-oppgave til TrOCR-treningsformat.
    TrOCR forventer:
    {
        "fil_sti": "sti/til/bilde.png",
        "tekst": "korrekt tekst fra annotator"
    }
    """
    annoteringer = oppgave.get("annotations", [])
    if not annoteringer:
        return None
    annotering = annoteringer[0]
    resultater = annotering.get("result", [])
    for resultat in resultater:
        if resultat.get("type") == "textarea":
            korrekt_tekst = resultat.get("value", {}).get("text", [""])[0]
            # En tom retting er ikke en fasit. Den ville blitt et
            # treningspar «bilde → ingenting», og modellen lærer da å
            # svare tomt på nettopp de vanskelige bildene.
            if not (korrekt_tekst or "").strip():
                return None
            bilde_url = oppgave.get("data", {}).get("bilde", "")
            oppgave_id = oppgave.get("id")
            return {
                # ARKIVET EIER SITT EGET BILDE (R170). Her sto stien inn
                # i `data/gjennomgang/bilder/` — en KØ med
                # oppbevaringsfrist. Arkivet er dokumentert som
                # permanent («slettes aldri automatisk»), så de to
                # motsier hverandre: den dagen oppbevaringsfristen
                # faktisk håndheves, forsvinner bildene arkivet peker
                # på, og `finjuster.py` stopper med FileNotFoundError —
                # hver uke, for alltid, fordi de ødelagte oppføringene
                # ligger i et arkiv som aldri ryddes.
                "fil_sti": _arkiver_bilde(_lokal_bildesti(bilde_url),
                                          oppgave_id),
                "tekst": korrekt_tekst,
                "oppgave_id": oppgave_id,
                "annotert_av": annotering.get("completed_by"),
                "tidsstempel": datetime.now().isoformat(),
                # Nøkkelen tilbake til dokumentet rettingen kom fra.
                # Uten den kan ingen finne igjen hva som gjelder hvem —
                # og da er retten til sletting (GDPR art. 17) ikke
                # teknisk mulig å oppfylle (R170).
                "kilde_dokument": _kildenokkel(oppgave),
            }
    return None


def _allerede_klargjorte_ider() -> set:
    """Oppgave-ID-ene som allerede ligger i tidligere trocr_*.json —
    eksporten er INKREMENTELL: samme korreksjon klargjøres aldri to
    ganger (før dette ble alt re-eksportert hver gang → duplikater som
    skjevvektet treningen)."""
    ider = set()
    for fil in Path(FINJUSTERING_STI).glob("trocr_*.json"):
        try:
            for rad in json.loads(fil.read_text(encoding="utf-8")):
                if rad.get("oppgave_id") is not None:
                    ider.add(rad["oppgave_id"])
        except (OSError, ValueError):
            continue
    return ider


def _slett_oppgaver(oppgave_ider: list, trocr_fil: str) -> int:
    """Sletter oppgavene i Label Studio ETTER at rettingen er arkivert.

    VERIFISERER FØRST. Å slette kilden fordi vi TROR vi skrev arkivet
    er den ene rekkefølgen som kan miste data for godt: feiler
    skrivingen, står vi igjen uten både retting og oppgave. Fila leses
    derfor tilbake og id-ene sammenlignes før noe slettes.

    `AVSLAA_SLETTING=1` slår det av — for den som vil beholde oppgavene
    i Label Studio en stund til. Da vokser basen, og det er et VALG,
    ikke en glipp: uten sletting er `label_studio.sqlite3` et permanent
    arkiv over råtekst fra hvert dokument som ble lest dårlig (R171)."""
    if os.environ.get("AVSLAA_SLETTING") == "1":
        print("  (AVSLAA_SLETTING=1 — oppgavene blir stående i Label Studio)")
        return 0
    try:
        arkivert = {r.get("oppgave_id")
                    for r in json.loads(
                        Path(trocr_fil).read_text(encoding="utf-8"))}
    except (OSError, ValueError) as exc:
        print(f"  ADVARSEL: kunne ikke lese tilbake {trocr_fil} "
              f"({type(exc).__name__}) — sletter INGENTING", file=sys.stderr)
        return 0

    slettet = 0
    for oid in oppgave_ider:
        if oid not in arkivert:
            print(f"  ADVARSEL: oppgave {oid} står ikke i arkivet — "
                  f"beholdes i Label Studio", file=sys.stderr)
            continue
        try:
            svar = requests.delete(
                f"{LABEL_STUDIO_URL}/api/tasks/{oid}",
                headers={"Authorization": f"Token {LABEL_STUDIO_API_KEY}"},
                timeout=30)
            if svar.status_code in (200, 204):
                slettet += 1
            else:
                print(f"  ADVARSEL: kunne ikke slette oppgave {oid} "
                      f"(HTTP {svar.status_code})", file=sys.stderr)
        except requests.RequestException as exc:
            print(f"  ADVARSEL: sletting av oppgave {oid} feilet "
                  f"({type(exc).__name__})", file=sys.stderr)
    return slettet


def eksporter():
    """Hovedfunksjon — eksporterer NYE korreksjoner (inkrementelt)."""
    Path(FINJUSTERING_STI).mkdir(parents=True, exist_ok=True)

    prosjekter = hent_prosjekter()
    print(f"Fant {len(prosjekter)} prosjekt(er) i Label Studio")

    klargjort = _allerede_klargjorte_ider()
    trocr_data = []
    hoppet_over = 0

    for prosjekt in prosjekter:
        prosjekt_id = prosjekt["id"]
        prosjekt_navn = prosjekt["title"]
        print(f"Behandler: {prosjekt_navn} (ID: {prosjekt_id})")

        oppgaver = hent_fullforte_oppgaver(prosjekt_id)
        print(f"  -> {len(oppgaver)} annoterte oppgaver")

        for oppgave in oppgaver:
            if oppgave.get("id") in klargjort:
                hoppet_over += 1
                continue
            # LS 1.23: annoteringsinnholdet må hentes per oppgave (lista
            # over har det ikke) — kun for NYE oppgaver, så det er billig.
            oppgave["annotations"] = hent_annoteringer(oppgave["id"])
            trocr = konverter_til_trocr_format(oppgave)
            if trocr:
                trocr_data.append(trocr)

    if hoppet_over:
        print(f"  ({hoppet_over} allerede klargjort tidligere — hoppet over)")

    tidsstempel = datetime.now().strftime("%Y%m%d_%H%M%S")

    if trocr_data:
        trocr_fil = f"{FINJUSTERING_STI}/trocr_{tidsstempel}.json"
        with open(trocr_fil, "w", encoding="utf-8") as f:
            json.dump(trocr_data, f, ensure_ascii=False, indent=2)
        print(f"\nTrOCR-treningsdata: {len(trocr_data)} eksempler -> {trocr_fil}")
        # SLETT OPPGAVENE I LABEL STUDIO — men FØRST nå, når rettingen
        # ligger trygt i arkivet med sitt eget bilde (R171).
        #
        # Ingenting slettet dem før: det fantes ikke ett eneste
        # `requests.delete` i hele prosjektet. Basen
        # `data/label-studio/label_studio.sqlite3` beholdt dermed
        # råteksten fra HVERT dokument som noen gang ble lest dårlig,
        # sammen med navn, dato og ytelse — for alltid, uten policy.
        #
        # Rekkefølgen er hele vernet: skriv arkivet, verifiser at det
        # kan leses tilbake, SÅ slett kilden. Motsatt vei mister vi
        # rettingen hvis skrivingen feiler.
        slettet = _slett_oppgaver([r["oppgave_id"] for r in trocr_data],
                                  trocr_fil)
        print(f"Slettet {slettet} av {len(trocr_data)} oppgaver i "
              f"Label Studio (råteksten blir ikke liggende igjen)")

    print(f"\nTotalt eksportert: {len(trocr_data)} korreksjoner")
    print("Kjor 'make finjuster' for a starte modelltrening.")
    return len(trocr_data)


_HJELP = """Henter ferdig annoterte korreksjoner fra Label Studio og
klargjør dem som treningsdata i data/finjustering. Inkrementell: bare
oppgaver som ikke er hentet før.

  python skript/eksporter_fra_label_studio.py            hent nye
  python skript/eksporter_fra_label_studio.py --hjelp    vis denne teksten

Krever at Label Studio kjører og at API-nøkkelen er satt
(oppstart/lokal_env.bat).
"""

if __name__ == "__main__":
    # Argumentene ble IGNORERT — «--hjelp» kjørte en ekte eksport.
    if any(a in ("--hjelp", "-h", "--help", "/?") for a in sys.argv[1:]):
        print(_HJELP)
        sys.exit(0)
    _flagg = [a for a in sys.argv[1:] if a.startswith("-")]
    if _flagg:
        print(f"Ukjent flagg: {' '.join(_flagg)}\n\n{_HJELP}")
        sys.exit(2)
    totalt = eksporter()
    if totalt > 0:
        print("\nEtter finjustering: start serveren på nytt for å ta den "
              "nytrente modellen i bruk (modeller lastes ved oppstart).")

"""
Kjører HELE treningsløkken som ett løp:

  1) eksporter korreksjoner fra Label Studio  ->  data/finjustering/trocr_*.json
  2) finjuster norhand (TrOCR)                 ->  KANDIDAT (ikke live)
  3) kvalitetsport: evaluer kandidat vs live (CER), promoter BARE hvis minst
     like god (valider_modell.py) — ellers står live urørt
  (deretter starter du serveren på nytt for å ta en promotert modell i bruk)

Skriver et sammendrag av løpet til stdout / data/logger. Planlegg
tilbakevendende kjøring med Windows Task Scheduler.
"""
import sys
import time
from datetime import datetime
from pathlib import Path

# Gjør utskrift UTF-8-trygg: æøå (og norske navn i loggen) skal ikke krasje
# når stdout er omdirigert til en fil med et ikke-UTF-8-kodesett.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _allerede_trent_paa(totalt: int) -> bool:
    """Har en tidligere fullført trening allerede dekket nøyaktig dette
    antallet klargjorte eksempler? (Eksporten er inkrementell, så antallet
    vokser bare når noe nytt kommer til.)"""
    import json
    import os
    sti = (Path(os.environ.get("FINJUSTERING_STI", "./data/finjustering"))
           / "treningshistorikk.json")
    try:
        historikk = json.loads(sti.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return any(rad.get("trent_paa", 0) == totalt and totalt > 0
               for rad in historikk if isinstance(rad, dict))


def _skriv_historikk(resultat: str, varighet: float,
                     eksportert: int, trent: int, basis: str) -> None:
    """Livstidshistorikk over treningsløp (data/finjustering/
    treningshistorikk.json) — leses av GUI-ets Trening-fane. Skrives av
    ALLE løpere (GUI, ukejobb, manuell kjøring) siden alle går via her."""
    import json
    import os
    sti = (Path(os.environ.get("FINJUSTERING_STI", "./data/finjustering"))
           / "treningshistorikk.json")
    try:
        historikk = (json.loads(sti.read_text(encoding="utf-8"))
                     if sti.is_file() else [])
        if not isinstance(historikk, list):
            historikk = []
    except (OSError, ValueError):
        historikk = []
    historikk.append({
        "tidspunkt": datetime.now().isoformat(timespec="seconds"),
        "resultat": resultat, "varighet_s": varighet,
        "eksportert": eksportert, "trent_paa": trent,
        "basis": basis,
    })
    try:
        sti.parent.mkdir(parents=True, exist_ok=True)
        sti.write_text(json.dumps(historikk, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    except OSError as exc:
        print(f"(klarte ikke å skrive treningshistorikk: {exc})")


def kjor() -> None:
    start = time.time()
    resultat = "ukjent"
    antall_eksportert = 0
    antall_trent = 0
    import valider_modell as vm
    basis = vm.modell_avtrykk()
    kjent = vm.kjent_avtrykk()
    # Ny basismodell = live-vektene avviker fra sist registrerte avtrykk.
    # Egne bytter (promotering/rull-tilbake) registrerer selv, så bare et
    # bytte UTENFRA (ny modellutgave lagt inn) utløser dette.
    ny_basis = kjent is not None and basis != "ukjent" and basis != kjent
    try:
        # 1) Eksport fra Label Studio (inkrementell — henter bare NYE).
        # GUI-ets «Hent korreksjoner»-knapp kan ha klargjort data på
        # forhånd, så 0 nye betyr IKKE nødvendigvis ingenting å trene på.
        print("=== 1/3  Eksporterer korreksjoner fra Label Studio ===")
        import json
        import eksporter_fra_label_studio as eksport
        antall_eksportert = eksport.eksporter() or 0

        totalt_klargjort = 0
        finjustering = Path(eksport.FINJUSTERING_STI)
        for fil in finjustering.glob("trocr_*.json"):
            try:
                totalt_klargjort += len(json.loads(fil.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        print(f"Klargjort totalt: {totalt_klargjort} eksempler "
              f"({antall_eksportert} nye i denne kjøringen)")

        if totalt_klargjort == 0:
            print("Ingen korreksjoner klargjort — hopper over trening.")
            resultat = "ingen_data"
            return
        if ny_basis:
            print(f"NY BASISMODELL oppdaget (avtrykk {basis}, kjente {kjent})"
                  " — retrener HELE korreksjonsarkivet "
                  f"({totalt_klargjort} eksempler) på det nye grunnlaget.")
        elif antall_eksportert == 0 and _allerede_trent_paa(totalt_klargjort):
            print("Ingen nye korreksjoner siden forrige trening — hopper over.")
            resultat = "ingen_nye"
            return

        # 2) Finjuster norhand (TrOCR) → KANDIDAT (ikke live)
        print("\n=== 2/3  Finjusterer norhand (TrOCR) → kandidat ===")
        import finjuster
        antall_trent = finjuster.finjuster_norhand() or 0
        if not antall_trent:
            print("For få korreksjoner — ingen kandidat trent.")
            resultat = "for_faa"
            return

        # 3) Kvalitetsport: kandidat vs live på et fast valideringssett.
        # Promoter BARE hvis kandidaten er minst like god (lavere/lik CER),
        # så en dårlig batch aldri når produksjon — den stoppes i porten.
        print("\n=== 3/3  Kvalitetsport: kandidat vs live (CER) ===")
        v = vm.vurder()
        if v["godkjent"]:
            vm.promuster()
            resultat = "promotert"
            print(f"GODKJENT (CER {v['cer_kandidat']} <= {v['cer_live']}). "
                  "Server-omstart tar den nye modellen i bruk.")
        elif v["grunn"] == "mangler_valideringssett":
            resultat = "ingen_valideringssett"
            print("INGEN valideringssett — kandidaten er IKKE promotert. Lag "
                  f"{vm.VALIDERING_STI} for automatisk promotering, eller "
                  "promoter manuelt: python skript/valider_modell.py --promuster")
        else:
            resultat = "avvist_daarligere"
            print(f"AVVIST (CER {v['cer_kandidat']} > {v['cer_live']}). Live "
                  "urørt; kandidat i modeller/norhand-kandidat. Rull tilbake: "
                  "python skript/valider_modell.py --rull-tilbake")
    finally:
        varighet = round(time.time() - start, 1)
        print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] resultat={resultat} "
              f"varighet={varighet}s")
        _skriv_historikk(resultat, varighet, antall_eksportert, antall_trent,
                         basis)
        # Registrer live-avtrykket som «kjent» — men IKKE etter krasj
        # («ukjent»), så et uhåndtert basisbytte oppdages på nytt neste løp.
        if resultat != "ukjent":
            vm.husk_avtrykk("trening")
        print("Ferdig.")


_HJELP = """Kjører hele treningsløkken: eksport fra Label Studio →
finjustering av norhand (kandidat) → kvalitetsport (CER) → promotering
bare hvis kandidaten er minst like god som live.

  python skript/kjor_treningslop.py            kjør løpet
  python skript/kjor_treningslop.py --hjelp    vis denne teksten

MERK: løpet laster modeller på GPU-en og kan ta flere minutter. Stopp
API-serveren først hvis kortet er lite (den holder Borealis residerende).
"""

if __name__ == "__main__":
    # Argumentene ble tidligere IGNORERT: «--hjelp» startet et ekte
    # treningsløp på GPU-en. Et løp skal aldri være noe man utløser ved
    # å be om hjelp — ukjente flagg avvises nå i stedet.
    _flagg = [a for a in sys.argv[1:] if a.startswith("-")]
    if any(a in ("--hjelp", "-h", "--help", "/?") for a in sys.argv[1:]):
        print(_HJELP)
        sys.exit(0)
    if _flagg:
        print(f"Ukjent flagg: {' '.join(_flagg)}\n")
        print(_HJELP)
        sys.exit(2)
    kjor()

"""
Kvalitetsport for norhand: evaluerer en nytrent KANDIDAT-modell mot den
LIVE modellen på et FAST valideringssett FØR den slippes til produksjon.
Slik kan en dårlig korreksjonsbatch aldri stille forringe lesekvaliteten
— en regresjon blir stoppet i porten, ikke oppdaget i produksjon.

Valideringssettet: data/validering/norhand.json
  [ {"fil_sti": "…/bilde.png", "tekst": "fasit"}, … ]
Det skal være et LITE, STABILT sett som ALDRI endres — da er tallene
sammenlignbare mellom løp. Hold det atskilt fra treningsdataene (ellers
måler du hvor godt modellen husker, ikke hvor godt den generaliserer).

Mål: tegnfeilrate (CER) — lavere er bedre. Kandidaten promoteres bare
hvis den er minst like god som live (innenfor CER_MARGIN).

Modellmapper under modeller/:
  norhand           = live (den serveren laster)
  norhand-kandidat  = nytrent, venter på porten
  norhand-forrige   = forrige live (for umiddelbar rull-tilbake)

CLI:
  python skript/valider_modell.py              # evaluer kandidat vs live
  python skript/valider_modell.py --promuster  # tving promotering manuelt
  python skript/valider_modell.py --rull-tilbake  # gå tilbake til forrige
"""
import os
import sys
import json
import shutil
from datetime import datetime
from pathlib import Path

# UTF-8-trygg utskrift (se finjuster.py): norsk skal ikke krasje som subprocess.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

MODELLER_STI = os.environ.get("MODELLER_STI", "./modeller")
VALIDERING_STI = os.environ.get("VALIDERING_STI", "./data/validering/norhand.json")
LIVE = Path(MODELLER_STI) / "norhand"
KANDIDAT = Path(MODELLER_STI) / "norhand-kandidat"
FORRIGE = Path(MODELLER_STI) / "norhand-forrige"
# Her sto `CER_MARGIN` — «hvor mye dårligere kandidaten kan være og
# fremdeles godtas», standard 0.0. Den er fjernet (R148), ikke satt til
# en annen verdi: en fast margin på et lite sett flytter bare terskelen
# for hvilken STØY som slipper gjennom. Forskjellen mellom CER 0.041 og
# 0.043 på tredve dokumenter er ikke en forbedring, og ingen margin kan
# gjøre den til en.
#
# Dommen faller nå på konfidensintervaller (`bootstrap_ki`): overlapper
# de, kan modellene ikke skilles på dette settet, og da promoteres
# ingenting. En bryter som ser ut som en innstilling og ikke lenger
# styrer noe, er verre enn ingen (R140) — derfor er den også ute av
# .env.example.
# Sist KJENTE avtrykk av live-vektene. Avviker live fra dette, er modellen
# byttet ut UTENFRA (ny utgave fra Nasjonalbiblioteket) — og treningsløpet
# retrener automatisk hele korreksjonsarkivet på det nye grunnlaget.
GRUNNMODELL_STI = (Path(os.environ.get("FINJUSTERING_STI",
                                       "./data/finjustering"))
                   / "grunnmodell.json")


def modell_avtrykk() -> str:
    """Avtrykk av live-vektene (modeller/norhand): størrelse + sha256 av
    første megabyte av model.safetensors. Billig, men skiller sikkert
    mellom to ulike modellutgaver."""
    import hashlib
    sti = LIVE / "model.safetensors"
    try:
        h = hashlib.sha256()
        h.update(str(sti.stat().st_size).encode())
        with open(sti, "rb") as f:
            h.update(f.read(1024 * 1024))
        return h.hexdigest()[:16]
    except OSError:
        return "ukjent"


def kjent_avtrykk():
    """Avtrykket vi SIST registrerte for live-modellen (None = aldri
    registrert, f.eks. første kjøring etter oppgradering)."""
    try:
        return json.loads(GRUNNMODELL_STI.read_text(encoding="utf-8")).get("basis")
    except (OSError, ValueError):
        return None


def husk_avtrykk(hendelse: str) -> None:
    """Registrer nåværende live-avtrykk som «kjent». Kalles etter hvert
    treningsløp OG etter promotering/rull-tilbake, så våre EGNE bytter
    aldri feiltolkes som en ny basismodell."""
    avtrykk = modell_avtrykk()
    if avtrykk == "ukjent":
        return
    try:
        GRUNNMODELL_STI.parent.mkdir(parents=True, exist_ok=True)
        GRUNNMODELL_STI.write_text(json.dumps({
            "basis": avtrykk,
            "tidspunkt": datetime.now().isoformat(timespec="seconds"),
            "hendelse": hendelse,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"(klarte ikke å registrere basis-avtrykk: {exc})")


def _lev(a: str, b: str) -> int:
    """Levenshtein-avstand, iterativt — ingen ekstern avhengighet."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    forrige = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        naa = [i]
        for j, cb in enumerate(b, 1):
            naa.append(min(forrige[j] + 1, naa[j - 1] + 1, forrige[j - 1] + (ca != cb)))
        forrige = naa
    return forrige[-1]


def les_valideringssett(sti: str = VALIDERING_STI) -> list:
    """Leser valideringssettet. Beholder bare oppføringer med fasit og et
    bilde som faktisk finnes på disk. Tomt hvis fila mangler."""
    p = Path(sti)
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return [d for d in data
            if d.get("tekst") and os.path.isfile(d.get("fil_sti", ""))]


def cer_for_modell(modell_sti, sett: list, per_dokument: bool = False):
    """Tegnfeilrate (CER) for modellen på settet, eller None ved tomt sett.

    `per_dokument=True` gir i tillegg tallene PER DOKUMENT (R148). Uten
    dem er et konfidensintervall umulig å regne ut: funksjonen summerte
    feil og tegn og kastet fordelingen, og da finnes det ikke noe å
    resample.

    To snitt, og de svarer på ulike spørsmål:

        micro = sum(feil) / sum(tegn)   domineres av det LANGE dokumentet
        macro = snitt av CER per dok    domineres av det KORTE

    Et dokument på ti tegn som leses helt feil gir CER 1.0 og drar
    macro voldsomt opp, mens det knapt rører micro. Står de to langt fra
    hverandre, er ytelsen ujevn over dokumentlengder — og det er en
    opplysning i seg selv, ikke støy å velge bort."""
    if not sett:
        return None
    import torch
    from PIL import Image
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel

    prosessor = TrOCRProcessor.from_pretrained(str(modell_sti))
    modell = VisionEncoderDecoderModel.from_pretrained(str(modell_sti))
    modell.eval()
    paa_gpu = torch.cuda.is_available()
    if paa_gpu:
        modell.to("cuda")

    feil_per_dok, tegn_per_dok = [], []
    for d in sett:
        bilde = Image.open(d["fil_sti"]).convert("RGB")
        piksel = prosessor(images=bilde, return_tensors="pt").pixel_values
        if paa_gpu:
            piksel = piksel.to("cuda")
        with torch.no_grad():
            ids = modell.generate(piksel, max_new_tokens=128)
        pred = prosessor.batch_decode(ids, skip_special_tokens=True)[0]
        fasit = d["tekst"]
        feil_per_dok.append(_lev(pred, fasit))
        tegn_per_dok.append(max(1, len(fasit)))

    resultat = round(sum(feil_per_dok) / sum(tegn_per_dok), 4)
    del modell
    if paa_gpu:
        torch.cuda.empty_cache()
    if per_dokument:
        return resultat, feil_per_dok, tegn_per_dok
    return resultat


def macro_cer(feil_per_dok, tegn_per_dok) -> float:
    """Snittet av CER PER DOKUMENT — ikke av alle tegn under ett.

    Et dokument på ti tegn som leses helt feil gir CER 1.0 her, men
    knapt et utslag i micro. Sprik mellom de to betyr at ytelsen er
    ujevn over dokumentlengder."""
    if not tegn_per_dok:
        return 0.0
    return round(sum(f / t for f, t in zip(feil_per_dok, tegn_per_dok))
                 / len(tegn_per_dok), 4)


def bootstrap_ki(feil_per_dok, tegn_per_dok, runder: int = 2000,
                 froe: int = 20260807):
    """95 % konfidensintervall for micro-CER, ved resampling (R148).

    Dokumentene trekkes MED tilbakelegging `runder` ganger, og CER
    regnes på nytt for hvert utvalg. Bredden på intervallet forteller
    hvor mye av tallet som er sett — og hvor mye som er tilfeldighet.

    `froe` er fast MED VILJE. En kvalitetsport som gir ulik dom på
    samme inndata fra kjøring til kjøring er verre enn en fast margin:
    den er ikke bare upresis, den er uetterrettelig. Med fast frø kan
    en avvist kandidat undersøkes på nytt og gi samme svar."""
    import random
    if not tegn_per_dok:
        return (0.0, 0.0)
    tilfeldig = random.Random(froe)
    n = len(tegn_per_dok)
    verdier = []
    for _ in range(runder):
        valgt = [tilfeldig.randrange(n) for _ in range(n)]
        f = sum(feil_per_dok[i] for i in valgt)
        t = sum(tegn_per_dok[i] for i in valgt)
        verdier.append(f / t if t else 0.0)
    verdier.sort()
    lav = verdier[int(0.025 * runder)]
    hoy = verdier[min(runder - 1, int(0.975 * runder))]
    return (round(lav, 4), round(hoy, 4))


def intervallene_overlapper(a, b) -> bool:
    """Overlapper de to konfidensintervallene?

    Er svaret ja, kan vi ikke skille modellene på dette settet — og da
    er «kandidaten er bedre» en påstand tallene ikke bærer."""
    return a[0] <= b[1] and b[0] <= a[1]


def _flytt(kilde: Path, maal: Path) -> None:
    """Flytt kilde → mål (erstatter mål). Trygt på Windows (samme disk)."""
    if maal.exists():
        shutil.rmtree(maal)
    shutil.move(str(kilde), str(maal))


def promuster() -> bool:
    """Kandidat → live, og nåværende live → forrige (for rull-tilbake)."""
    if not KANDIDAT.exists():
        print("Ingen kandidat å promotere.")
        return False
    if LIVE.exists():
        _flytt(LIVE, FORRIGE)          # ta vare på nåværende for rollback
    _flytt(KANDIDAT, LIVE)
    # Versjonsstempel for sporbarhet (§4): API-et leser dette og legger det
    # på hvert svar, så et result kan spores til nøyaktig norhand-modellen.
    try:
        (LIVE / "nav_versjon.txt").write_text(
            f"norhand-{datetime.now():%Y%m%d-%H%M%S}", encoding="utf-8")
    except Exception:
        pass
    husk_avtrykk("promotering")    # egen promotering er IKKE et basisbytte
    print(f"Promotert: kandidat → live (forrige lagret i {FORRIGE.name} "
          "for rull-tilbake).")
    return True


def rull_tilbake() -> bool:
    """Gjenopprett forrige live-modell umiddelbart."""
    if not FORRIGE.exists():
        print("Ingen forrige modell å rulle tilbake til.")
        return False
    if LIVE.exists():
        _flytt(LIVE, Path(f"{LIVE}-avvist"))   # ta vare på den vi ruller vekk
    _flytt(FORRIGE, LIVE)
    husk_avtrykk("rull_tilbake")   # egen rull-tilbake er heller ikke et bytte
    print("Rullet tilbake: forrige → live. Start serveren på nytt.")
    return True


def vurder() -> dict:
    """Evaluer kandidat vs live på valideringssettet.
    godkjent=True betyr at kandidaten er trygg å promotere."""
    sett = les_valideringssett()
    if not sett:
        return {"godkjent": False, "grunn": "mangler_valideringssett",
                "cer_live": None, "cer_kandidat": None, "antall": 0}
    if not KANDIDAT.exists():
        return {"godkjent": False, "grunn": "mangler_kandidat",
                "cer_live": None, "cer_kandidat": None, "antall": len(sett)}
    if LIVE.exists():
        cer_live, feil_live, tegn_live = cer_for_modell(LIVE, sett,
                                                        per_dokument=True)
    else:
        # Ingen live-modell: alt er bedre enn ingenting, og da finnes
        # det ikke noe intervall å sammenligne med.
        cer_live, feil_live, tegn_live = 1.0, [], []
    cer_kand, feil_kand, tegn_kand = cer_for_modell(KANDIDAT, sett,
                                                    per_dokument=True)

    ki_live = bootstrap_ki(feil_live, tegn_live) if tegn_live else None
    ki_kand = bootstrap_ki(feil_kand, tegn_kand)

    # R148: dommen faller på INTERVALLER, ikke på to punkttall.
    #
    # `CER_MARGIN` var 0.0 — «kandidaten må være minst like god». På et
    # lite sett er forskjellen mellom 0.041 og 0.043 ren støy, og porten
    # promoterte eller avviste altså på tilfeldighet. En fast margin
    # gjør det ikke bedre: den flytter bare terskelen for hvilken støy
    # som slipper gjennom.
    #
    # Overlapper intervallene, kan vi ikke SKILLE modellene på dette
    # settet — og «kandidaten er bedre» er da en påstand tallene ikke
    # bærer. Vi promoterer ikke på et likt resultat; live blir stående,
    # for det er det trygge valget.
    if ki_live is None:
        godkjent = True
        grunn = "ingen_live_modell"
    elif intervallene_overlapper(ki_kand, ki_live):
        godkjent = False
        grunn = "ikke_skillbar"
    elif ki_kand[1] < ki_live[0]:
        godkjent = True
        grunn = "bedre"
    else:
        godkjent = False
        grunn = "daarligere"

    return {"godkjent": godkjent, "grunn": grunn,
            "cer_live": cer_live, "cer_kandidat": cer_kand,
            # micro er tallet over; macro sier om ytelsen er JEVN
            "macro_cer_live": macro_cer(feil_live, tegn_live) if tegn_live
                              else None,
            "macro_cer_kandidat": macro_cer(feil_kand, tegn_kand),
            "ki_live": ki_live, "ki_kandidat": ki_kand,
            "antall": len(sett)}


if __name__ == "__main__":
    if "--rull-tilbake" in sys.argv:
        sys.exit(0 if rull_tilbake() else 1)
    if "--promuster" in sys.argv:
        sys.exit(0 if promuster() else 1)
    if "--port" in sys.argv:
        # Kvalitetsport for automatikk (Prefect): valider OG promoter kun hvis
        # kandidaten er minst like god. Avvist/manglende sett er IKKE en feil
        # (porten gjorde jobben) — exit 0; ekte feil (modell-lasting o.l.)
        # propagerer som unntak → non-zero → synlig som rødt i Prefect.
        v = vurder()
        print(json.dumps(v, ensure_ascii=False))
        if v["godkjent"]:
            promuster()
        else:
            print(f"Ikke promotert ({v['grunn']}).")
        sys.exit(0)

    v = vurder()
    print(json.dumps(v, ensure_ascii=False, indent=2))
    if v["grunn"] == "mangler_valideringssett":
        print(f"\nLag et fast valideringssett i {VALIDERING_STI} for å "
              "aktivere kvalitetsporten (se data/validering/README.md).")
    elif v["grunn"] == "mangler_kandidat":
        print("\nIngen kandidat ennå — kjør 'make finjuster' eller 'make trening' først.")
    elif v["godkjent"]:
        print(f"\nKandidat CER {v['cer_kandidat']} ≤ live {v['cer_live']} → trygg. "
              "Promuster med 'python skript/valider_modell.py --promuster'.")
    else:
        print(f"\nKandidat CER {v['cer_kandidat']} > live {v['cer_live']} → DÅRLIGERE. "
              "Ikke promotert; live står urørt.")

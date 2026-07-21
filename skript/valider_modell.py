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
from pathlib import Path

MODELLER_STI = os.environ.get("MODELLER_STI", "./modeller")
VALIDERING_STI = os.environ.get("VALIDERING_STI", "./data/validering/norhand.json")
LIVE = Path(MODELLER_STI) / "norhand"
KANDIDAT = Path(MODELLER_STI) / "norhand-kandidat"
FORRIGE = Path(MODELLER_STI) / "norhand-forrige"
# Hvor mye DÅRLIGERE kandidaten kan være og fremdeles godtas.
# 0.0 = må være minst like god. En liten margin tåler støy i små sett.
CER_MARGIN = float(os.environ.get("CER_MARGIN", "0.0"))


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


def cer_for_modell(modell_sti, sett: list):
    """Gjennomsnittlig tegnfeilrate (CER) for modellen på settet.
    Returnerer None hvis settet er tomt."""
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

    feil = 0
    tegn = 0
    for d in sett:
        bilde = Image.open(d["fil_sti"]).convert("RGB")
        piksel = prosessor(images=bilde, return_tensors="pt").pixel_values
        if paa_gpu:
            piksel = piksel.to("cuda")
        with torch.no_grad():
            ids = modell.generate(piksel, max_new_tokens=128)
        pred = prosessor.batch_decode(ids, skip_special_tokens=True)[0]
        fasit = d["tekst"]
        feil += _lev(pred, fasit)
        tegn += max(1, len(fasit))

    resultat = round(feil / tegn, 4)
    del modell
    if paa_gpu:
        torch.cuda.empty_cache()
    return resultat


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
    cer_live = cer_for_modell(LIVE, sett) if LIVE.exists() else 1.0
    cer_kand = cer_for_modell(KANDIDAT, sett)
    godkjent = cer_kand <= cer_live + CER_MARGIN
    return {"godkjent": godkjent,
            "grunn": "bedre_eller_lik" if godkjent else "daarligere",
            "cer_live": cer_live, "cer_kandidat": cer_kand, "antall": len(sett)}


if __name__ == "__main__":
    if "--rull-tilbake" in sys.argv:
        sys.exit(0 if rull_tilbake() else 1)
    if "--promuster" in sys.argv:
        sys.exit(0 if promuster() else 1)

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

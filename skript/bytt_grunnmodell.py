"""
Bytter BASISMODELLEN (modeller/norhand) til en nyere utgave — f.eks. når
Nasjonalbiblioteket/Språkbanken slipper en bedre TrOCR-norhand.

Kunnskapen fra korreksjonene deres bor IKKE i vektene, men i det varige
korreksjonsarkivet (data/finjustering/trocr_*.json + bilder i
data/gjennomgang/bilder/). Byttet rører aldri arkivet. Neste treningsløp
oppdager automatisk at basisen er ny (avtrykket avviker fra
data/finjustering/grunnmodell.json) og retrener HELE arkivet på det nye
grunnlaget — kvalitetsporten avgjør som vanlig om resultatet promoteres.

Bruk:
  python skript/bytt_grunnmodell.py <sti-til-ny-modellmappe>
  python skript/bytt_grunnmodell.py <sti> --tren-naa   # retren umiddelbart

Den gamle modellen arkiveres som modeller/norhand-utgaatt-<tidsstempel>
(slett den selv når du er trygg på den nye).
"""
import os
import sys
import shutil
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

MODELLER_STI = Path(os.environ.get("MODELLER_STI", "./modeller"))
LIVE = MODELLER_STI / "norhand"
# Filer en TrOCR-modellmappe MÅ ha for at serveren skal kunne laste den.
PAAKREVD = ("model.safetensors", "config.json")


def bytt(ny_sti: str, tren_naa: bool = False) -> int:
    ny = Path(ny_sti)
    mangler = [f for f in PAAKREVD if not (ny / f).is_file()]
    if mangler:
        print(f"AVBRUTT: {ny} mangler {', '.join(mangler)} — "
              "er dette virkelig en TrOCR-modellmappe?")
        return 1

    import valider_modell as vm
    gammelt = vm.modell_avtrykk()

    stempel = f"{datetime.now():%Y%m%d-%H%M%S}"
    arkiv = MODELLER_STI / f"norhand-utgaatt-{stempel}"
    if LIVE.exists():
        arkiv.mkdir(parents=True, exist_ok=True)
        shutil.move(str(LIVE), str(arkiv / "norhand"))
        print(f"Gammel basis arkivert: {arkiv}")
    # Kandidat og forrige tilhører den GAMLE slektslinjen — blir de liggende,
    # kan «--promuster» senere legge en gammel-basis-kandidat OVER den nye
    # basisen, eller rull-tilbake gjenopprette den gamle basisen i det stille.
    for slektning in (vm.KANDIDAT, vm.FORRIGE):
        if slektning.exists():
            arkiv.mkdir(parents=True, exist_ok=True)
            shutil.move(str(slektning), str(arkiv / slektning.name))
            print(f"Utdatert {slektning.name} arkivert samme sted "
                  "(tilhørte den gamle basisen).")
    shutil.copytree(str(ny), str(LIVE))
    # Sporbarhetsstempel (API-et legger det på hvert svar). Promotering
    # skriver sitt eget — en fersk oppstrøms-basis må også få ett.
    try:
        (LIVE / "nav_versjon.txt").write_text(
            f"norhand-basis-{stempel}", encoding="utf-8")
    except OSError:
        pass

    nytt = vm.modell_avtrykk()
    if nytt == gammelt:
        print("MERK: ny modell har SAMME avtrykk som den gamle — "
              "ingen retrening vil utløses (identiske vekter?).")
    else:
        print(f"Ny basis på plass (avtrykk {gammelt} → {nytt}).")
        print("Neste treningsløp retrener automatisk HELE korreksjonsarkivet "
              "på den nye basisen. Start serveren på nytt for å ta den i bruk.")

    if tren_naa:
        print("\n--tren-naa: starter treningsløpet nå …\n")
        import kjor_treningslop
        kjor_treningslop.kjor()
    return 0


if __name__ == "__main__":
    argv = [a for a in sys.argv[1:] if a != "--tren-naa"]
    if len(argv) != 1:
        print(__doc__)
        sys.exit(1)
    sys.exit(bytt(argv[0], tren_naa="--tren-naa" in sys.argv))

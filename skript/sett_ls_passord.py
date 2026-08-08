# -*- coding: utf-8 -*-
"""Setter passordet til en Label Studio-bruker. Passordet leses fra STDIN.

    echo|set /p="hemmelig" | python skript/sett_ls_passord.py <e-post>

Ment for kontrollpanelet, som sender passordet gjennom en pipe. Kan
også kjøres for hånd, men da er `nullstill_ls_passord.py` bedre — den
spør med `getpass`, så ingenting havner i skallhistorikken.

HVORFOR STDIN OG IKKE ET ARGUMENT
`--password <verdi>` legger passordet i prosesslista, synlig for enhver
som kjører `tasklist` mens kommandoen står på. Det havner også i
skallhistorikken. En pipe har ingen av delene: verdien går fra
avsenderens minne rett inn i vårt, og videre inn i Djangos hasher.

HVORFOR IKKE `label-studio reset_password`
Den kommandoen spør med `getpass`, som leser fra KONSOLLET — ikke fra
stdin. Startet fra et vindusprogram uten konsoll ville den enten hengt
eller falt tilbake på et upålitelig standardinnlesing. Vi bruker derfor
Djangos egne funksjoner direkte: `set_password` bruker nøyaktig samme
hasher som Label Studio selv, så resultatet er identisk med det
kommandoen ville gitt.

SKRIVER ALDRI UT PASSORDET — heller ikke i en feilmelding.
"""
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Uten denne peker Label Studio på standardkatalogen i brukerprofilen
# på C: — en HELT annen, tom base. Passordet ville blitt satt der, mens
# innlogging fortsatt feilet i den ekte.
os.environ.setdefault("LABEL_STUDIO_BASE_DATA_DIR",
                      os.path.join(ROT, "data", "label-studio"))
os.environ.setdefault("PYTHONNOUSERSITE", "1")

MINSTE_LENGDE = 8
# Prefiks på svarlinja, så kalleren finner den blant
# eventuelle biblioteksadvarsler.
SVARMERKE = "SVAR: "


def sett(e_post: str, passord: str) -> tuple:
    """(ok, melding) — meldingen inneholder ALDRI passordet."""
    if not e_post:
        return False, "Ingen bruker oppgitt."
    if len(passord) < MINSTE_LENGDE:
        return False, (f"Passordet må være minst {MINSTE_LENGDE} tegn. "
                       f"Du skrev {len(passord)}.")
    try:
        # Label Studios egne innstillinger importerer `core.…` som en
        # TOPPNIVÅ-pakke, ikke som `label_studio.core.…`. Uten pakkens
        # egen mappe på sys.path gir django.setup() «No module named
        # core» — en feil som ser ut som en manglende installasjon, men
        # bare er feil søkesti (R178).
        import django
        import label_studio
        sys.path.insert(0, label_studio.__path__[0])
        os.environ.setdefault("DJANGO_SETTINGS_MODULE",
                              "core.settings.label_studio")
        django.setup()
        from django.contrib.auth import get_user_model
    except Exception as exc:                       # noqa: bred med vilje
        # Typen, ikke teksten: en Django-oppstartsfeil kan inneholde
        # stier og konfigurasjon som ikke hører hjemme i en dialogboks.
        return False, (f"Klarte ikke å starte Label Studio-laget "
                       f"({type(exc).__name__}). Er Label Studio "
                       f"installert i dette miljøet?")

    Bruker = get_user_model()
    bruker = Bruker.objects.filter(email=e_post).first()
    if bruker is None:
        return False, f"Fant ingen bruker med e-posten «{e_post}»."
    if bruker.check_password(passord):
        return False, "Det nye passordet er det samme som det gamle."
    try:
        bruker.set_password(passord)     # Djangos egen hasher
        bruker.save()
    except Exception as exc:             # noqa: typen, ikke teksten
        return False, (f"Klarte ikke å lagre ({type(exc).__name__}). "
                       f"Kjører Label Studio? Stopp den og prøv igjen.")
    return True, f"Passordet til «{e_post}» er endret."


def main() -> int:
    argumenter = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not argumenter:
        print("Bruk: sett_ls_passord.py <e-post>   (passord leses fra stdin)",
              file=sys.stderr)
        return 2

    # Én linje fra stdin. `readline` og ikke `read`, så et etterfølgende
    # linjeskift fra avsenderen ikke blir en del av passordet — en feil
    # som gir «feil passord» ved neste innlogging og er svært vanskelig
    # å finne igjen.
    passord = sys.stdin.readline().rstrip("\r\n")
    ok, melding = sett(argumenter[0], passord)
    # Overskriv den lokale referansen. Python garanterer ikke at
    # strengen forsvinner fra minnet, men vi lar den i det minste ikke
    # ligge i en levende variabel resten av prosessens levetid.
    passord = "x" * len(passord)
    del passord
    # ALLTID pa stdout, med et fast merke (R178). Stderr er ikke vår
    # alene: importerte biblioteker skriver advarsler dit — målt ble
    # «RequestsDependencyWarning: urllib3 …» det første kontrollpanelet
    # viste i feildialogen, mens den ekte grunnen lå under. Et merke gir
    # kalleren en linje den kan plukke ut med sikkerhet.
    print(SVARMERKE + melding)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

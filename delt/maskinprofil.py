"""Maskinprofil: maskinen bestemmer takene, ikke en frossen konstant.

Prosjektet skal kunne kopieres til en server ingen har sett ennå. I dag
er halvparten av takene født av ETT kort på 8 GB — `BOREALIS_KONTEKST`
er 4096 fordi 8192 segfaultet HER, `SAMTIDIGE_PER_GPU` er 4 fordi det
passet HER. Flyttes mappa til et større kort, arver den småkortets
grenser og bruker ikke en megabyte av det den fikk.

Denne modulen måler maskinen én gang og utleder takene fra målingen.

REGELEN ER USYMMETRISK, OG DET ER MED VILJE
  NEDOVER er fritt. Et svakere kort skal få lavere tak umiddelbart —
  det er alltid trygt.
  OPPOVER er konservativt og har et tak. En for høy verdi gir ikke en
  feilmelding, men et NATIVT KRASJ uten traceback (0xC0000005): 8192
  segfaultet under KV-cache-allokering på 8 GB. Den som står med
  serveren skal aldri måtte feilsøke det. Derfor hever automatikken
  aldri over `KONTEKST_AUTO_TAK`; over det sier profilen fra at kortet
  tåler mer, og lar et menneske ta valget.
  SIKKERHETSRESERVER SENKES ALDRI automatisk. `OCR_MINSTE_LEDIG_GPU_MB`
  ble en gang satt til 800 og felte tjenesten (R140); at et lite kort
  «ikke har råd» til 2600 er en grunn til å si fra, ikke til å slakke.

Miljøvariabler vinner alltid over profilen — den setter STANDARDEN, den
overstyrer ingen som har bestemt seg.

    python -m delt.maskinprofil        # vis profilen for denne maskinen
"""
import json
import os
import re
from pathlib import Path

ROT = Path(__file__).resolve().parent.parent

# ── Ankeret: den ENE målingen vi stoler på ──────────────────────────
# RTX 3070, 8192 MiB: Borealis Q8 (~4,1 GB) + OCR-reserve på 2600 MiB
# lot 4096 tokens kontekst kjøre stabilt, mens 8192 segfaultet under
# KV-cache-allokeringen. Alt annet her skaleres fra det punktet.
ANKER_VRAM_MB = 8192
ANKER_KONTEKST = 4096
# Hva 4096 tokens kontekst faktisk KOSTER, avledet av ankeret:
# 8192 - 4460 (modell med buffere) - 2600 (OCR) = 1132 MiB til KV-cache.
# Det er ~283 MiB per 1024 tokens — nesten tre ganger et naivt anslag,
# og nettopp derfor «burde få plass» ikke er godt nok (R140).
#
# Ankeret gir bare en ØVRE grense for kostnaden: vi VET at 4096 fikk
# plass i 1132 MiB, og at 8192 ikke gjorde det. Den sanne kostnaden
# ligger et sted mellom. Vi bruker den øvre grensen, altså det
# konservative valget.
KV_MB_PER_1K = 283.0
# Hodrommet ankeret faktisk hadde. Brukes til en regel som er viktigere
# enn hele regnestykket over: har maskinen minst like mye plass som
# ankeret hadde, er ankerets kontekst MÅLT trygg — og en måling slår et
# anslag. Uten den lander regnestykket på 4094,4 av 4096 og runder ned
# til halv kontekst på nøyaktig den maskinen tallene kommer fra.
#
# Regnes ut av de samme konstantene, ikke skrevet som et tall: skrevet
# som 1131.6 ble sammenligningen usann på ankermaskinen selv, fordi
# 4130 × 1.08 gir 4460.400000000001 og hodrommet dermed 1131.5999999999985.
ANKER_MODELL_MB = 4130.0
BUFFERPAASLAG = 1.08

# Automatikken hever aldri konteksten over dette. Ikke fordi tallet er
# magisk, men fordi et krasj her ikke etterlater noe å feilsøke på.
KONTEKST_AUTO_TAK = int(os.environ.get("KONTEKST_AUTO_TAK", "8192"))
KONTEKST_GULV = 2048

# OCR-reserven er ABSOLUTT, ikke prosentvis: EasyOCR trenger like mye
# på et stort kort som på et lite. Den skaleres derfor ikke — verken
# opp eller ned.
OCR_RESERVE_MB = 2600
ANKER_HODROM_MB = (ANKER_VRAM_MB - ANKER_MODELL_MB * BUFFERPAASLAG
                   - OCR_RESERVE_MB)

PROFIL_STI = ROT / "data" / "maskinprofil.json"
VAKTHUND_LOGG = ROT / "data" / "logger" / "vakthund.log"
# Exitkoden som betyr «native krasj» — se skript/vakthund.py.
NATIV_KRASJ = 3221225477


# ── Måling ──────────────────────────────────────────────────────────

def _kort_via_nvidia_smi():
    """(navn, total_MB) per kort — UTEN å røre CUDA i vår egen prosess.

    Dette er grunnen til at vi ikke bare kaller torch her: `torch.cuda`
    oppretter en CUDA-kontekst for å svare, og den konteksten koster
    et par hundre MB som blir stående. På ankermaskinen er hele
    hodrommet 1132 MB — å bruke en firedel av det på å MÅLE hvor mye
    plass vi har, ville vært å skyte seg selv i foten. Kontrollpanelet
    måler på samme måte, av samme grunn."""
    import subprocess
    uten_vindu = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        ut = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
            creationflags=uten_vindu)
        if ut.returncode != 0:
            return None
    except Exception:                                           # noqa: BLE001
        return None
    kort = []
    for linje in (ut.stdout or "").strip().splitlines():
        deler = [d.strip() for d in linje.split(",")]
        if len(deler) < 2:
            continue
        try:
            kort.append((deler[0], float(deler[1])))
        except ValueError:
            continue
    return kort or None


def mal_maskinen() -> dict:
    """Rå måling av maskinen. Ingen tolkning, ingen tak."""
    kort, vram_totalt_mb, kortnavn = 0, 0.0, []
    fra_smi = _kort_via_nvidia_smi()
    if fra_smi:
        kort = len(fra_smi)
        kortnavn = [navn for navn, _ in fra_smi]
        vram_totalt_mb = sum(mb for _, mb in fra_smi)
    else:
        # Ingen nvidia-smi (eller den svarte ikke). Da er torch eneste
        # kilde, og kostnaden ved en CUDA-kontekst er prisen for å vite.
        try:
            import torch
            if torch.cuda.is_available():
                kort = torch.cuda.device_count()
                for i in range(kort):
                    try:
                        vram_totalt_mb += (torch.cuda.mem_get_info(i)[1]
                                           / (1024 ** 2))
                        kortnavn.append(torch.cuda.get_device_name(i))
                    except Exception:                           # noqa: BLE001
                        continue
        except Exception:                                       # noqa: BLE001
            pass
    try:
        kjerner = os.cpu_count() or 2
    except Exception:                                           # noqa: BLE001
        kjerner = 2
    ram_mb = 0.0
    try:
        import ctypes

        class _Minne(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        m = _Minne()
        m.dwLength = ctypes.sizeof(_Minne)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        ram_mb = m.ullTotalPhys / (1024 ** 2)
    except Exception:                                           # noqa: BLE001
        try:
            import psutil
            ram_mb = psutil.virtual_memory().total / (1024 ** 2)
        except Exception:                                       # noqa: BLE001
            ram_mb = 8192.0
    # Kortet vi FAKTISK legger modellen på. Flere kort summeres i
    # `vram_totalt_mb` for kapasitetsregning, men Borealis og OCR pinnes
    # begge til kort 0 i dag — å regne konteksten av summen ville lovet
    # plass som ikke finnes på det kortet den skal ligge på.
    if fra_smi:
        vram_kort0_mb = fra_smi[0][1]
    else:
        vram_kort0_mb = vram_totalt_mb / max(1, kort) if kort else 0.0
    return {"gpu_kort": kort, "gpu_navn": kortnavn,
            "vram_totalt_mb": round(vram_totalt_mb),
            "vram_kort0_mb": round(vram_kort0_mb),
            "kjerner": kjerner, "ram_mb": round(ram_mb)}


# ── Utledning ───────────────────────────────────────────────────────

def _rund_ned_toerpotens(tokens: float) -> int:
    """Nærmeste toerpotens under `tokens`. llama.cpp er gladest i dem,
    og et rundt tall er lettere å kjenne igjen i en logg."""
    verdi = KONTEKST_GULV
    while verdi * 2 <= tokens:
        verdi *= 2
    return verdi


def utled(maaling: dict, modell_mb: float = None,
          brent_kontekst: int = None) -> dict:
    """Takene denne maskinen skal kjøre med.

    `modell_mb` er språkmodellens filstørrelse; uten den antas dagens
    Q8 (~4,1 GB). `brent_kontekst` er en verdi som HAR felt serveren —
    da holder vi oss under den uansett hva regnestykket sier."""
    vram0 = maaling.get("vram_kort0_mb") or 0
    kort = maaling.get("gpu_kort") or 0
    ram_mb = maaling.get("ram_mb") or 8192
    kjerner = maaling.get("kjerner") or 2
    modell_mb = 4130.0 if modell_mb is None else float(modell_mb)
    modell_med_buffer = modell_mb * BUFFERPAASLAG

    merknader = []

    # -- Borealis-kontekst -------------------------------------------
    if not kort:
        kontekst = KONTEKST_GULV
        merknader.append(
            "Ingen CUDA funnet — modellen kjører på CPU. Den virker, men "
            "er mange ganger tregere. Konteksten holdes lav.")
    else:
        hodrom = vram0 - modell_med_buffer - OCR_RESERVE_MB
        if hodrom <= 0:
            kontekst = KONTEKST_GULV
            merknader.append(
                f"Kortet har {vram0:.0f} MB; modellen ({modell_med_buffer:.0f} MB) "
                f"og OCR-reserven ({OCR_RESERVE_MB} MB) fyller det alene. "
                "Sett BOREALIS_GPU_LAG lavere for å dele modellen med "
                "RAM, eller bruk en mindre modell.")
        else:
            kontekst = _rund_ned_toerpotens(hodrom / KV_MB_PER_1K * 1024)
            # Målingen slår anslaget: har kortet minst ankerets hodrom,
            # er ankerets kontekst bevist trygg her. Én MB slingring —
            # flyttallsstøy skal ikke avgjøre en kontekststørrelse.
            if hodrom >= ANKER_HODROM_MB - 1.0:
                kontekst = max(kontekst, ANKER_KONTEKST)
    kontekst = max(KONTEKST_GULV, kontekst)

    kunne_tatt = kontekst
    if kontekst > KONTEKST_AUTO_TAK:
        kontekst = KONTEKST_AUTO_TAK
        merknader.append(
            f"Kortet ser ut til å tåle {kunne_tatt} tokens kontekst, men "
            f"automatikken stopper på {KONTEKST_AUTO_TAK}. En for høy "
            "verdi gir ikke en feilmelding — den gir et nativt krasj uten "
            f"traceback. Vil du høyere, sett BOREALIS_KONTEKST={kunne_tatt} "
            "manuelt og følg med på data/logger/vakthund.log.")

    # Brent finger: en verdi som har felt serveren gjenbrukes ikke.
    if brent_kontekst and kontekst >= brent_kontekst:
        trygg = max(KONTEKST_GULV, _rund_ned_toerpotens(brent_kontekst - 1))
        merknader.append(
            f"Serveren har krasjet nativt med kontekst {brent_kontekst} på "
            f"denne maskinen. Går ned til {trygg} og blir der til noen "
            "hever den bevisst.")
        kontekst = trygg

    # -- Resten skaleres fra konteksten og kortet --------------------
    # Tegngrensen henger sammen med konteksten: 12000 tegn hørte til
    # 4096 tokens. Skalerer den ikke med, blir et større kort like
    # begrenset som et lite på nøyaktig det som betyr noe for brukeren.
    maks_llm_tegn = int(12000 * kontekst / ANKER_KONTEKST)

    # 4 samtidige per kort ved 8 GB ⇒ ett spor per 2 GB.
    samtidige_per_gpu = max(2, int(vram0 // 2048)) if kort else 2
    # Analysecachen holder ferdiglest tekst i RAM.
    analyse_cache = max(32, min(256, int(ram_mb // 1024)))
    # Håndskriftbudsjettet per side følger kortets størrelse: norhand er
    # den dyreste lesningen vi gjør, og på et lite kort er taket det som
    # hindrer at én side spiser hele forespørselen (R52/R55).
    norhand_per_side = max(12, min(48, int(vram0 // 680))) if kort else 12

    # -- Største modell dette kortet tåler ---------------------------
    if kort:
        kv_mb = kontekst / 1024.0 * KV_MB_PER_1K
        maks_modell_mb = max(0.0, (vram0 - OCR_RESERVE_MB - kv_mb)
                             / BUFFERPAASLAG)
    else:
        maks_modell_mb = 0.0

    if kort > 1:
        merknader.append(
            f"{kort} kort funnet ({maaling.get('vram_totalt_mb')} MB til "
            "sammen), men modell og OCR ligger begge på kort 0 i dag. "
            "Kort 1 og oppover står ubrukt til flerkort-arbeid er gjort.")

    return {
        "borealis_kontekst": int(kontekst),
        "maks_llm_tegn": int(maks_llm_tegn),
        "samtidige_per_gpu": int(samtidige_per_gpu),
        "analyse_cache_maks": int(analyse_cache),
        "maks_norhand_per_side": int(norhand_per_side),
        "ocr_minste_ledig_gpu_mb": OCR_RESERVE_MB,
        "maks_modell_mb": round(maks_modell_mb),
        "kontekst_kortet_kunne_tatt": int(kunne_tatt),
        "merknader": merknader,
    }


# ── Brent finger: les vakthundloggen ────────────────────────────────

def brent_kontekst(logg_sti: Path = None, profil_sti: Path = None):
    """Kontekstverdien som SIST felte serveren nativt, hvis noen.

    Vakthunden logger exitkoden, og profilen som kjørte er lagret ved
    forrige oppstart. Var siste hendelse et nativt krasj, vet vi hvilken
    kontekst som sto på — og den skal ikke prøves igjen av seg selv.
    Feiltolker vi loggen, returnerer vi None: å tvinge en unødvendig
    nedskalering er mildere enn å gjenta et krasj, men å gjette er
    verre enn begge."""
    logg_sti = VAKTHUND_LOGG if logg_sti is None else logg_sti
    profil_sti = PROFIL_STI if profil_sti is None else profil_sti
    try:
        linjer = logg_sti.read_text(encoding="utf-8",
                                    errors="replace").splitlines()
    except OSError:
        return None
    siste_krasj = False
    for linje in reversed(linjer):
        if "exitkode" not in linje:
            continue
        siste_krasj = str(NATIV_KRASJ) in linje or "0xC0000005" in linje.upper()
        break
    if not siste_krasj:
        return None
    try:
        lagret = json.loads(profil_sti.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    verdi = (lagret.get("valgt") or {}).get("borealis_kontekst")
    return int(verdi) if isinstance(verdi, int) and verdi > 0 else None


def _env_navn(nokkel: str) -> str:
    return {
        "borealis_kontekst": "BOREALIS_KONTEKST",
        "maks_llm_tegn": "MAKS_LLM_TEGN",
        "samtidige_per_gpu": "SAMTIDIGE_PER_GPU",
        "analyse_cache_maks": "ANALYSE_CACHE_MAKS",
        "maks_norhand_per_side": "MAKS_NORHAND_PER_SIDE",
        "ocr_minste_ledig_gpu_mb": "OCR_MINSTE_LEDIG_GPU_MB",
    }.get(nokkel, nokkel.upper())


_bufret = {"profil": None}


def profil(paa_nytt: bool = False) -> dict:
    """Hele profilen: måling, utledede tak, og hva som faktisk gjelder
    etter at miljøvariabler har fått siste ord."""
    if _bufret["profil"] is not None and not paa_nytt:
        return _bufret["profil"]
    maaling = mal_maskinen()
    utledet = utled(maaling, brent_kontekst=brent_kontekst())
    valgt, overstyrt = {}, []
    for nokkel, verdi in utledet.items():
        if nokkel in ("merknader", "maks_modell_mb",
                      "kontekst_kortet_kunne_tatt"):
            continue
        fra_env = os.environ.get(_env_navn(nokkel), "").strip()
        if fra_env:
            try:
                valgt[nokkel] = int(float(fra_env))
                overstyrt.append(f"{_env_navn(nokkel)}={fra_env}")
                continue
            except ValueError:
                pass
        valgt[nokkel] = verdi
    _bufret["profil"] = {"maaling": maaling, "utledet": utledet,
                         "valgt": valgt, "overstyrt": overstyrt}
    return _bufret["profil"]


def verdi(nokkel: str, reserve):
    """Den gjeldende verdien for ett tak — profilen, eller `reserve`
    hvis noe gikk galt under målingen. Kallstedene skal aldri stå uten
    en verdi fordi en GPU-spørring feilet."""
    try:
        return profil()["valgt"].get(nokkel, reserve)
    except Exception:                                           # noqa: BLE001
        return reserve


def lagre(p: dict = None) -> None:
    """Skriv profilen til disk, så neste oppstart vet hva som kjørte
    da et eventuelt krasj skjedde."""
    p = profil() if p is None else p
    try:
        PROFIL_STI.parent.mkdir(parents=True, exist_ok=True)
        PROFIL_STI.write_text(json.dumps(p, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except OSError:
        pass


def rapport(p: dict = None) -> str:
    """Profilen i klartekst — den skal kunne leses av noen som ikke
    kjenner koden."""
    p = profil() if p is None else p
    m, u, v = p["maaling"], p["utledet"], p["valgt"]
    linjer = ["Maskinprofil"]
    if m["gpu_kort"]:
        navn = m["gpu_navn"][0] if m["gpu_navn"] else "ukjent kort"
        linjer.append(f"  Skjermkort:      {navn}, "
                      f"{m['vram_kort0_mb']} MB VRAM"
                      + (f" ({m['gpu_kort']} kort, {m['vram_totalt_mb']} MB "
                         "til sammen)" if m["gpu_kort"] > 1 else ""))
    else:
        linjer.append("  Skjermkort:      ingen CUDA funnet (alt på CPU)")
    linjer.append(f"  Prosessor/minne: {m['kjerner']} kjerner, "
                  f"{m['ram_mb'] / 1024:.0f} GB RAM")
    linjer.append("")
    linjer.append(f"  Borealis-kontekst:   {v['borealis_kontekst']} tokens")
    linjer.append(f"  Tegn til modellen:   {v['maks_llm_tegn']}")
    linjer.append(f"  Samtidige per kort:  {v['samtidige_per_gpu']}")
    linjer.append(f"  Håndskrift per side: {v['maks_norhand_per_side']}")
    linjer.append(f"  OCR-reserve:         {v['ocr_minste_ledig_gpu_mb']} MB "
                  "(senkes aldri automatisk)")
    if u["maks_modell_mb"]:
        linjer.append(f"  Største språkmodell: ~{u['maks_modell_mb'] / 1024:.1f} GB "
                      "GGUF med disse innstillingene")
    if p["overstyrt"]:
        linjer.append("")
        linjer.append("  Overstyrt i miljøet: " + ", ".join(p["overstyrt"]))
    for merknad in u["merknader"]:
        linjer.append("")
        linjer.append("  MERK: " + merknad)
    return "\n".join(linjer)


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                           # noqa: BLE001
        pass
    print(rapport())

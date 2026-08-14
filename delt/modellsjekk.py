"""Førflight-sjekker før en språkmodell slippes til i produksjon.

De fire sjekkene her er valgt fordi de dekker feilene som faktisk har
felt tjenesten — og fordi de alle FEILER STILLE uten en vakt:

  1. VRAM-budsjett (R140).  En større modell tar plassen OCR trenger.
     Utslaget er ikke en feilmelding, men et nativt krasj uten
     traceback (0xC0000005) eller en OCR som stille faller til CPU.
  2. Promptankre (CLAUDE.md §4).  Klippingen av lange dokumenter
     finner dokumentdelen via faste ankre. Endres ordlyden i
     regler/prompter.md, treffer ikke ankrene lenger, og lange
     dokumenter klippes på feil sted — svaret ser helt normalt ut.
  3. Determinisme (R6).  Samme spørsmål skal gi samme svar. En modell
     som svarer ulikt fra gang til gang gjør hvert avvik uetterprøvbart.
  4. Tallvakt-raten (R147).  Vakten stopper tall som ikke står i
     dokumentet. Spretter raten opp, dikter modellen tall; faller den
     til null, er vakten kanskje slått av — og begge er alvorlige.

Sjekk 1 og 2 er statiske og kjøres FØR en modell lastes. Sjekk 3 og 4
krever en kjørende modell og måles av spørsmålskorpuset.

Alt her er rene funksjoner uten sideeffekter, så både
skript/bytt_modell.py og kontrollpanelet kaller nøyaktig samme kode —
og testene kan kjøre dem uten GPU.
"""
import os

# Hvor mye VRAM OCR må ha igjen for å bli på GPU-en. Samme tall som
# delt/region_ocr.MINSTE_LEDIG_GPU_MB, lest fra samme miljøvariabel —
# to steder med hver sin standard ville før eller siden sagt hver sitt.
OCR_KRAV_MB = int(os.environ.get("OCR_MINSTE_LEDIG_GPU_MB", "2600"))

# Påslag på filstørrelsen for llama.cpp sine egne buffere (compute,
# vekter som ikke pakkes helt, allokeringsslark). Målt grovt på
# Q8_0-modellen vi kjører i dag; det er et ANSLAG, og sjekken sier det.
BUFFERPAASLAG = 1.08

# KV-cachen vokser med kontekstvinduet. 4096 tokens på en 4B-modell
# ligger rundt 400 MiB; tallet skaleres lineært med konteksten. Dette
# er også et anslag — det er nettopp derfor 8192 ble målt til å
# segfaulte selv om «det burde få plass».
KV_CACHE_MB_PER_1K_TOKEN = 100.0


def vram_anslag_mb(filstorrelse_bytes: int, kontekst: int = 4096) -> float:
    """Anslått VRAM-behov for en GGUF-modell, i MiB.

    ANSLAG, ikke en måling. Poenget er å stoppe det åpenbart umulige
    før noe lastes — ikke å love at det som passerer, får plass."""
    fil_mb = filstorrelse_bytes / (1024 * 1024)
    kv_mb = (max(kontekst, 0) / 1024.0) * KV_CACHE_MB_PER_1K_TOKEN
    return fil_mb * BUFFERPAASLAG + kv_mb


def vram_budsjett(filstorrelse_bytes: int, totalt_mb: float,
                  kontekst: int = 4096, ocr_krav_mb: int = None) -> dict:
    """Får modellen plass — OG blir det nok igjen til OCR?

    To spørsmål, ikke ett. En modell kan få plass på kortet og likevel
    være feil valg, fordi OCR da faller til CPU og hele lesingen blir
    6–17× tregere (R51). Derfor er `holder` False også når modellen
    passer, men etterlater mindre enn OCR-kravet."""
    ocr_krav_mb = OCR_KRAV_MB if ocr_krav_mb is None else ocr_krav_mb
    behov = vram_anslag_mb(filstorrelse_bytes, kontekst)
    igjen = totalt_mb - behov
    if totalt_mb <= 0:
        return {"holder": None, "behov_mb": round(behov),
                "totalt_mb": 0, "igjen_til_ocr_mb": None,
                "ocr_krav_mb": ocr_krav_mb,
                "forklaring": ("Fant ikke noe CUDA-kort å måle mot. "
                               "Kjører du uten GPU, gjelder ikke dette "
                               "budsjettet — men da blir modellen treg.")}
    if behov >= totalt_mb:
        forklaring = (f"Modellen trenger anslagsvis {behov:.0f} MB, men "
                      f"kortet har {totalt_mb:.0f} MB totalt. Den får "
                      "ikke plass i det hele tatt.")
    elif igjen < ocr_krav_mb:
        forklaring = (f"Modellen får plass ({behov:.0f} MB av "
                      f"{totalt_mb:.0f} MB), men etterlater bare "
                      f"{igjen:.0f} MB til OCR — grensen er "
                      f"{ocr_krav_mb} MB. OCR vil falle til CPU og bli "
                      "6–17 ganger tregere (R51).")
    else:
        forklaring = (f"Modellen trenger anslagsvis {behov:.0f} MB av "
                      f"{totalt_mb:.0f} MB, og etterlater {igjen:.0f} MB "
                      f"til OCR (grensen er {ocr_krav_mb} MB).")
    return {"holder": bool(behov < totalt_mb and igjen >= ocr_krav_mb),
            "behov_mb": round(behov), "totalt_mb": round(totalt_mb),
            "igjen_til_ocr_mb": round(igjen), "ocr_krav_mb": ocr_krav_mb,
            "forklaring": forklaring}


# Ankerparene som avgrenser den KLIPPBARE dokumentdelen, og blokkene de
# skal treffe i. Speiler _PROMPT_ANKRE i skript/dokument_api.py — står
# de to fra hverandre, er det nettopp det denne sjekken skal oppdage.
# Hvert element: (promptblokk, felter å fylle, hodeanker, haleanker).
ANKERPUNKTER = [
    ("spor.dokumentsporsmal",
     {"egne_regler": "", "ocr_merknad": "", "dokument": "DOKUMENTTEKST",
      "sporsmal": "SPØRSMÅLET"},
     "\nDokument:\n", "\n\nSpørsmål:"),
    ("fyll_skjema.mal",
     {"dokument": "DOKUMENTTEKST", "grunnlag": "", "mal": "{}"},
     "\nDokument:\n", "\n\nJSON-mal:"),
    ("korriger.forste_pass",
     {"usikre_blokk": "", "ocr_tekst": "OCR-TEKSTEN"},
     "OCR-tekst:\n", "\n\nKorrigert tekst:"),
]


def sjekk_promptankre(hent=None) -> dict:
    """Treffer klippeankrene fortsatt promptene de skal klippe i?

    Dette er den mest lumske av de fire. Bommer et anker, kastes
    dokumentet IKKE — det klippes bare et vilkårlig sted, eller ikke i
    det hele tatt, og svaret ser like troverdig ut som før. Feilen
    dukker først opp på LANGE dokumenter, altså sjelden nok til at
    ingen kobler den til en ordlydsendring i regler/prompter.md.

    `hent` injiseres i tester; til vanlig brukes prompter.hent."""
    if hent is None:
        from delt import prompter
        hent = prompter.hent
    avvik = []
    sjekket = []
    for blokk, felter, hode, hale in ANKERPUNKTER:
        try:
            tekst = hent(blokk, **felter)
        except Exception as exc:                      # noqa: BLE001
            avvik.append(f"{blokk}: kunne ikke bygges ({exc})")
            continue
        i = tekst.find(hode)
        j = tekst.rfind(hale)
        if i == -1:
            avvik.append(f"{blokk}: fant ikke hodeankeret {hode!r} — "
                         "lange dokumenter klippes ikke der de skal")
        elif j <= i:
            avvik.append(f"{blokk}: haleankeret {hale!r} står før eller "
                         "mangler etter hodeankeret — klippeområdet er tomt")
        else:
            sjekket.append(blokk)
    return {"ok": not avvik, "avvik": avvik, "sjekket": sjekket}


def determinisme_dom(svar_a: str, svar_b: str) -> dict:
    """R6: samme spørsmål to ganger skal gi samme svar.

    Sammenligner ordrett etter trimming. Er de ulike, er ikke bare
    dette ene svaret usikkert — hver eneste feilsøking blir uetterprøvbar,
    for du kan ikke gjenskape det du så."""
    a = (svar_a or "").strip()
    b = (svar_b or "").strip()
    return {"ok": a == b, "svar_1": a[:200], "svar_2": b[:200]}


def tallvakt_dom(stoppet: int, antall_svar: int,
                 grense_hoy: float = 0.25) -> dict:
    """R147: hvor ofte grep tallvakten inn?

    To ytterpunkter, hver sin alvorlige betydning:
      høy rate  → modellen dikter tall som ikke står i dokumentet
      null      → vakten kan være slått av, og ingen vet det

    Null er derfor ikke automatisk «bra». Det er verdt et blikk."""
    if antall_svar <= 0:
        return {"rate": None, "dom": "ikke_maalt",
                "forklaring": "Ingen svar å måle på."}
    rate = stoppet / antall_svar
    if rate >= grense_hoy:
        dom = "hoy"
        forklaring = (f"Tallvakten stoppet tall i {stoppet} av "
                      f"{antall_svar} svar ({rate:.0%}). Så høy rate "
                      "betyr at modellen gjengir tall som ikke står i "
                      "dokumentet.")
    elif stoppet == 0:
        dom = "null"
        forklaring = (f"Tallvakten grep aldri inn i {antall_svar} svar. "
                      "Det kan bety at modellen er presis — eller at "
                      "vakten ikke kjørte. Kontroller at svarene "
                      "faktisk inneholder tall.")
    else:
        dom = "normal"
        forklaring = (f"Tallvakten stoppet tall i {stoppet} av "
                      f"{antall_svar} svar ({rate:.0%}).")
    return {"rate": round(rate, 4), "dom": dom, "stoppet": stoppet,
            "antall_svar": antall_svar, "forklaring": forklaring}

"""
Maskinprofilen (R190): maskinen bestemmer takene, ikke en frossen
konstant fra ankermaskinen.

Den viktigste testen i fila er den kjedeligste: at ankermaskinen
(8 GB) gir NØYAKTIG de verdiene prosjektet kjørte med før profilen
fantes. En «forbedring» som stille endrer oppførselen på maskinen alle
målingene er gjort på, er ikke en forbedring — den er en regresjon med
god begrunnelse.
"""
import json
import sys

sys.path.insert(0, ".")

import pytest

from delt import maskinprofil as mp


def maskin(vram_mb, kort=1, ram_mb=32768, kjerner=12):
    return {"gpu_kort": kort, "gpu_navn": ["testkort"] * kort,
            "vram_totalt_mb": vram_mb * max(1, kort),
            "vram_kort0_mb": vram_mb, "kjerner": kjerner, "ram_mb": ram_mb}


# ------------------------------------------------------------------ #
#  Ankeret: 8 GB skal gi dagens verdier, bit for bit                  #
# ------------------------------------------------------------------ #

def test_ankermaskinen_gir_noeyaktig_dagens_verdier():
    """Verdiene prosjektet kjørte med før R190. Endres én av dem, er
    det en atferdsendring på maskinen alle målingene er gjort på."""
    u = mp.utled(maskin(8192))
    assert u["borealis_kontekst"] == 4096
    assert u["maks_llm_tegn"] == 12000
    assert u["samtidige_per_gpu"] == 4
    assert u["analyse_cache_maks"] == 32
    assert u["maks_norhand_per_side"] == 12
    assert u["ocr_minste_ledig_gpu_mb"] == 2600


def test_ankeret_slaar_avrundingen():
    """Regnestykket lander på 4094,4 av 4096 på ankermaskinen og ville
    rundet ned til HALV kontekst. Målingen sier at 4096 virker her, og
    en måling slår et anslag."""
    hodrom = 8192 - mp.ANKER_MODELL_MB * mp.BUFFERPAASLAG - mp.OCR_RESERVE_MB
    assert hodrom / mp.KV_MB_PER_1K * 1024 < 4096, (
        "forutsetningen for testen er borte — regnestykket når nå 4096 selv")
    assert mp.utled(maskin(8192))["borealis_kontekst"] == 4096


# ------------------------------------------------------------------ #
#  Nedover er fritt                                                   #
# ------------------------------------------------------------------ #

def test_svakere_kort_faar_lavere_tak():
    liten = mp.utled(maskin(4096))
    anker = mp.utled(maskin(8192))
    assert liten["borealis_kontekst"] <= anker["borealis_kontekst"]
    assert liten["samtidige_per_gpu"] < anker["samtidige_per_gpu"]


def test_kort_uten_plass_til_modellen_sier_hvorfor():
    """Et 4 GB-kort har ikke plass til modell + OCR-reserve. Da skal
    profilen si hva man gjør med det, ikke bare gi et lavt tall."""
    u = mp.utled(maskin(4096))
    assert u["merknader"], "ingen merknad om at kortet er for lite"
    samlet = " ".join(u["merknader"])
    assert "BOREALIS_GPU_LAG" in samlet or "mindre modell" in samlet


def test_uten_gpu_faller_alt_til_gulvet():
    u = mp.utled(maskin(0, kort=0))
    assert u["borealis_kontekst"] == mp.KONTEKST_GULV
    assert u["maks_modell_mb"] == 0
    assert any("CPU" in m for m in u["merknader"])


# ------------------------------------------------------------------ #
#  Oppover er konservativt                                            #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("vram", [12288, 16384, 24576, 49152, 81920])
def test_stoerre_kort_gir_mer_men_aldri_over_taket(vram):
    u = mp.utled(maskin(vram))
    anker = mp.utled(maskin(8192))
    assert u["borealis_kontekst"] > anker["borealis_kontekst"]
    assert u["borealis_kontekst"] <= mp.KONTEKST_AUTO_TAK, (
        "automatikken hevet konteksten over taket — en for høy verdi gir "
        "et nativt krasj uten traceback, ikke en feilmelding")
    assert u["samtidige_per_gpu"] > anker["samtidige_per_gpu"]
    assert u["maks_modell_mb"] > anker["maks_modell_mb"]


def test_stort_kort_sier_fra_at_det_taaler_mer():
    """Taket er en sikkerhetsgrense, ikke en påstand om kortet. Den som
    vil høyere skal få vite at det er mulig — og hvordan."""
    u = mp.utled(maskin(81920))
    assert u["kontekst_kortet_kunne_tatt"] > mp.KONTEKST_AUTO_TAK
    samlet = " ".join(u["merknader"])
    assert "BOREALIS_KONTEKST" in samlet


def test_flere_kort_nevnes_men_brukes_ikke_stille():
    """To kort er ikke dobbelt kapasitet før noen har gjort arbeidet.
    Profilen skal si at kort 1 står ubrukt, ikke late som."""
    u = mp.utled(maskin(24576, kort=2))
    assert any("kort 0" in m for m in u["merknader"])


# ------------------------------------------------------------------ #
#  Sikkerhetsreserven senkes ALDRI                                    #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("vram", [0, 2048, 4096, 8192, 24576, 81920])
def test_ocr_reserven_er_den_samme_uansett_kort(vram):
    """R140: 800 var verdien som felte tjenesten. At et lite kort «ikke
    har råd» til 2600 er en grunn til å si fra, ikke til å slakke."""
    u = mp.utled(maskin(vram, kort=0 if not vram else 1))
    assert u["ocr_minste_ledig_gpu_mb"] == 2600


# ------------------------------------------------------------------ #
#  Brent finger: en verdi som har felt serveren prøves ikke igjen     #
# ------------------------------------------------------------------ #

def test_krasjet_kontekst_gjenbrukes_ikke():
    u = mp.utled(maskin(24576), brent_kontekst=8192)
    assert u["borealis_kontekst"] < 8192
    assert any("krasjet" in m for m in u["merknader"])


def test_brent_kontekst_leses_av_vakthundloggen(tmp_path):
    logg = tmp_path / "vakthund.log"
    profil = tmp_path / "maskinprofil.json"
    logg.write_text("2026-08-15 10:00:00  startet\n"
                    "2026-08-15 10:02:00  PROSESSEN DØDE — exitkode "
                    "3221225477 (0xC0000005 MINNETILGANGSFEIL)\n",
                    encoding="utf-8")
    profil.write_text(json.dumps({"valgt": {"borealis_kontekst": 8192}}),
                      encoding="utf-8")
    assert mp.brent_kontekst(logg, profil) == 8192


def test_ryddig_avslutning_er_ikke_en_brent_finger(tmp_path):
    """Bare NATIVE krasj teller. En server noen stoppet med vilje skal
    ikke føre til at maskinen degraderes ved neste oppstart."""
    logg = tmp_path / "vakthund.log"
    profil = tmp_path / "maskinprofil.json"
    logg.write_text("2026-08-15 10:02:00  avsluttet — exitkode 0 "
                    "(ryddig avslutning)\n", encoding="utf-8")
    profil.write_text(json.dumps({"valgt": {"borealis_kontekst": 8192}}),
                      encoding="utf-8")
    assert mp.brent_kontekst(logg, profil) is None


def test_manglende_logg_gir_ingen_gjetning(tmp_path):
    assert mp.brent_kontekst(tmp_path / "finnes-ikke.log",
                             tmp_path / "heller-ikke.json") is None


# ------------------------------------------------------------------ #
#  Miljøet vinner alltid                                              #
# ------------------------------------------------------------------ #

def test_miljovariabel_overstyrer_profilen(monkeypatch):
    monkeypatch.setenv("BOREALIS_KONTEKST", "1024")
    monkeypatch.setattr(mp, "_bufret", {"profil": None})
    p = mp.profil(paa_nytt=True)
    assert p["valgt"]["borealis_kontekst"] == 1024
    assert any("BOREALIS_KONTEKST" in o for o in p["overstyrt"])


def test_soppel_i_miljovariabel_faller_tilbake_paa_profilen(monkeypatch):
    """En tastefeil i .env skal ikke felle oppstarten — da står den som
    ikke kan koden igjen med en server som ikke starter."""
    monkeypatch.setenv("SAMTIDIGE_PER_GPU", "fire")
    monkeypatch.setattr(mp, "_bufret", {"profil": None})
    p = mp.profil(paa_nytt=True)
    assert isinstance(p["valgt"]["samtidige_per_gpu"], int)


def test_verdi_gir_reserve_naar_alt_feiler(monkeypatch):
    def _sprekk(*a, **k):
        raise RuntimeError("ingen maskin")
    monkeypatch.setattr(mp, "profil", _sprekk)
    assert mp.verdi("borealis_kontekst", 4096) == 4096


# ------------------------------------------------------------------ #
#  Målingen skal ikke koste det den måler                             #
# ------------------------------------------------------------------ #

def test_maalingen_lager_ikke_cuda_kontekst():
    """Å bruke torch.cuda for å måle ledig VRAM oppretter en
    CUDA-kontekst på et par hundre MB. På ankermaskinen er HELE
    hodrommet 1132 MB — da ville målingen spist en firedel av det den
    måler. nvidia-smi svarer uten å røre vår egen prosess."""
    import subprocess
    ut = subprocess.run(
        [sys.executable, "-X", "utf8", "-c",
         "import sys; sys.path.insert(0, '.');"
         "from delt import maskinprofil as m; m.mal_maskinen();"
         "print('torch' in sys.modules)"],
        capture_output=True, text=True, timeout=120)
    if "nvidia-smi" not in (ut.stdout + ut.stderr) and ut.returncode == 0:
        assert ut.stdout.strip().endswith("False"), (
            "målingen lastet torch og opprettet dermed en CUDA-kontekst")


# ------------------------------------------------------------------ #
#  Sammenheng med modellbytte-porten                                  #
# ------------------------------------------------------------------ #

def test_stoerste_modell_stemmer_med_vram_budsjettet():
    """Profilen sier «dette kortet tåler ~X GB», og porten avgjør om en
    konkret fil får plass. Sier de to ulike ting, er råd og dom i strid
    — og den som står med serveren får to svar på samme spørsmål."""
    from delt import modellsjekk
    for vram in (8192, 16384, 24576):
        u = mp.utled(maskin(vram))
        maks_bytes = int(u["maks_modell_mb"] * 1024 * 1024)
        dom = modellsjekk.vram_budsjett(
            int(maks_bytes * 0.95), vram, u["borealis_kontekst"])
        assert dom["holder"] is True, (
            f"{vram} MB: profilen lover {u['maks_modell_mb']} MB, men "
            f"porten avviser 95 % av det — {dom['forklaring']}")


def test_rapporten_er_lesbar_for_et_menneske():
    p = {"maaling": maskin(8192), "utledet": mp.utled(maskin(8192)),
         "valgt": mp.utled(maskin(8192)), "overstyrt": []}
    tekst = mp.rapport(p)
    for ord_ in ("Maskinprofil", "Borealis-kontekst", "OCR-reserve"):
        assert ord_ in tekst

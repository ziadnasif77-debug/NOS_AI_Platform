"""
Modellbytte: førflight-sjekkene (R188) og porten som dømmer (R189).

Det viktigste her er ikke at et bytte VIRKER, men at et bytte som ikke
burde skje, BLIR STOPPET — og at grunnen står i klartekst. Serveren
skal kunne stelles av noen som ikke kjenner koden.
"""
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

from delt import modellsjekk


# ------------------------------------------------------------------ #
#  VRAM-budsjettet (R140)                                             #
# ------------------------------------------------------------------ #

GB = 1024 ** 3


def test_dagens_modell_faar_plass_med_rom_til_ocr():
    """Q8-modellen vi kjører i dag på et 8 GB-kort — utgangspunktet
    alle andre vurderinger måles mot."""
    dom = modellsjekk.vram_budsjett(4_130_402_720, 8192, kontekst=4096)
    assert dom["holder"] is True
    assert dom["igjen_til_ocr_mb"] > dom["ocr_krav_mb"]


def test_for_stor_modell_avvises():
    dom = modellsjekk.vram_budsjett(8 * GB, 8192, kontekst=4096)
    assert dom["holder"] is False
    assert "plass" in dom["forklaring"]


def test_modell_som_sulter_ocr_avvises_selv_om_den_faar_plass():
    """DEN VIKTIGE: en modell kan få plass på kortet og likevel være
    feil valg. Uten denne regelen faller OCR til CPU og hele lesingen
    blir 6–17× tregere (R51) — uten at noen får en feilmelding."""
    dom = modellsjekk.vram_budsjett(5 * GB, 8192, kontekst=4096)
    assert dom["behov_mb"] < dom["totalt_mb"], "modellen får jo plass"
    assert dom["holder"] is False
    assert "OCR" in dom["forklaring"]


def test_stor_kontekst_spiser_budsjettet():
    """8192 er verdien som segfaultet i praksis. Budsjettet skal vise
    hvorfor, ikke bare si nei."""
    liten = modellsjekk.vram_budsjett(4 * GB, 8192, kontekst=4096)
    stor = modellsjekk.vram_budsjett(4 * GB, 8192, kontekst=8192)
    assert stor["behov_mb"] > liten["behov_mb"]


def test_uten_gpu_er_dommen_ukjent_ikke_nei():
    """«Vi kan ikke måle» er ikke det samme som «det går ikke» (R128)."""
    dom = modellsjekk.vram_budsjett(4 * GB, 0)
    assert dom["holder"] is None


# ------------------------------------------------------------------ #
#  Promptankrene (CLAUDE.md §4) — den lumske                          #
# ------------------------------------------------------------------ #

def test_promptankrene_treffer_de_ekte_promptene():
    """Vakten mot den stilleste feilen i systemet: endres ordlyden rundt
    «Dokument:» eller «Spørsmål:» i regler/prompter.md, klippes lange
    dokumenter på feil sted — og svaret ser helt normalt ut."""
    dom = modellsjekk.sjekk_promptankre()
    assert dom["ok"], "ankre som ikke treffer: " + "; ".join(dom["avvik"])
    assert len(dom["sjekket"]) == len(modellsjekk.ANKERPUNKTER)


def test_ankervakten_oppdager_en_endret_ordlyd():
    """Motprøven. En vakt som alltid er grønn er verre enn ingen vakt —
    her bevises det at den faktisk slår ut."""
    def _forfalsket(navn, **felter):
        return "Dokumentasjon:\nnoe tekst\n\nHva lurer du på:"
    dom = modellsjekk.sjekk_promptankre(hent=_forfalsket)
    assert dom["ok"] is False
    assert dom["avvik"]


# ------------------------------------------------------------------ #
#  Determinisme (R6) og tallvakt-raten (R147)                         #
# ------------------------------------------------------------------ #

def test_determinisme():
    assert modellsjekk.determinisme_dom("4 812 kroner", " 4 812 kroner ")["ok"]
    assert not modellsjekk.determinisme_dom("4 812", "4 813")["ok"]


def test_tallvakt_hoy_rate_er_et_varsel():
    dom = modellsjekk.tallvakt_dom(stoppet=15, antall_svar=45)
    assert dom["dom"] == "hoy"
    assert "dikter" in dom["forklaring"] or "ikke står" in dom["forklaring"]


def test_tallvakt_null_er_ikke_automatisk_bra():
    """R147: null kan bety «presis modell» ELLER «vakten er av», og de
    to er ikke samme sak."""
    dom = modellsjekk.tallvakt_dom(stoppet=0, antall_svar=45)
    assert dom["dom"] == "null"
    assert "vakten" in dom["forklaring"]


def test_tallvakt_uten_svar_er_ikke_maalt():
    assert modellsjekk.tallvakt_dom(0, 0)["dom"] == "ikke_maalt"


# ------------------------------------------------------------------ #
#  Porten som dømmer (R189)                                           #
# ------------------------------------------------------------------ #

@pytest.fixture
def bytt():
    import bytt_modell
    return bytt_modell


def _maaling(utfall, kode_bestatt=8, kode_antall=8, tallvakt_stoppet=2,
             deterministisk=True):
    return {
        "utfall": utfall,
        "antall": len(utfall), "bestatt": sum(utfall),
        "modell_bestatt": sum(utfall) - kode_bestatt,
        "modell_antall": len(utfall) - kode_antall,
        "kode_bestatt": kode_bestatt, "kode_antall": kode_antall,
        "sekunder_per_svar": 4.0,
        "tallvakt": modellsjekk.tallvakt_dom(tallvakt_stoppet, len(utfall)),
        "determinisme": {"ok": deterministisk, "avvik": []},
    }


def test_liten_forskjell_er_ikke_en_forbedring(bytt):
    """R148 i praksis: 24 mot 22 riktige av 45 er ikke en forbedring —
    det er støy. En fast margin kan ikke gjøre den til noe annet."""
    live = _maaling([1] * 22 + [0] * 23)
    kandidat = _maaling([1] * 24 + [0] * 21)
    avgjorelse = bytt.dom(live, kandidat)
    assert avgjorelse["godkjent"] is False
    assert avgjorelse["grunn"] == "ikke_skillbar"


def test_stor_forbedring_godkjennes(bytt):
    live = _maaling([1] * 20 + [0] * 25)
    kandidat = _maaling([1] * 43 + [0] * 2)
    avgjorelse = bytt.dom(live, kandidat)
    assert avgjorelse["godkjent"] is True
    assert avgjorelse["grunn"] == "bedre"


def test_klart_daarligere_avvises(bytt):
    live = _maaling([1] * 43 + [0] * 2)
    kandidat = _maaling([1] * 18 + [0] * 27)
    avgjorelse = bytt.dom(live, kandidat)
    assert avgjorelse["godkjent"] is False
    assert avgjorelse["grunn"] == "daarligere"


def test_brutt_ruting_stopper_byttet_uansett_hvor_gode_tallene_er(bytt):
    """Kontrollgruppen. Spørsmålene koden svarer på går ikke gjennom
    modellen i det hele tatt — faller de, er det rutingen som er brutt,
    og da sier resten av tallene ingenting om modellen."""
    live = _maaling([1] * 20 + [0] * 25, kode_bestatt=8)
    kandidat = _maaling([1] * 44 + [0] * 1, kode_bestatt=5)
    avgjorelse = bytt.dom(live, kandidat)
    assert avgjorelse["godkjent"] is False
    assert avgjorelse["grunn"] == "ruting_brutt"


def test_ikke_deterministisk_modell_avvises_uansett(bytt):
    live = _maaling([1] * 20 + [0] * 25)
    kandidat = _maaling([1] * 44 + [0] * 1, deterministisk=False)
    avgjorelse = bytt.dom(live, kandidat)
    assert avgjorelse["godkjent"] is False
    assert avgjorelse["grunn"] == "ikke_deterministisk"


def test_modell_som_dikter_tall_avvises_uansett(bytt):
    live = _maaling([1] * 20 + [0] * 25)
    kandidat = _maaling([1] * 44 + [0] * 1, tallvakt_stoppet=20)
    avgjorelse = bytt.dom(live, kandidat)
    assert avgjorelse["godkjent"] is False
    assert avgjorelse["grunn"] == "dikter_tall"


def test_umaalt_gir_ikke_gront_lys(bytt):
    assert bytt.dom({}, {})["godkjent"] is False
    assert bytt.dom(_maaling([1] * 45), {})["godkjent"] is False


def test_dommen_er_lik_hver_gang(bytt):
    """Fast frø: en port som dømmer ulikt på samme inndata fra kjøring
    til kjøring er verre enn ingen port."""
    live = _maaling([1] * 22 + [0] * 23)
    kandidat = _maaling([1] * 30 + [0] * 15)
    assert bytt.dom(live, kandidat) == bytt.dom(live, kandidat)


def test_gguf_signatur_leses_ikke_filnavnet(bytt, tmp_path):
    """En omdøpt tekstfil skal stoppes her — ikke av llama.cpp, som
    svarer med et nativt krasj uten traceback."""
    falsk = tmp_path / "modell.gguf"
    falsk.write_bytes(b"dette er ikke en modell")
    assert bytt.er_gguf(falsk) is False
    ekte = tmp_path / "ekte.gguf"
    ekte.write_bytes(b"GGUF" + b"\x00" * 64)
    assert bytt.er_gguf(ekte) is True


def test_forsjekk_avviser_fil_som_ikke_finnes(bytt, tmp_path):
    dom = bytt.forsjekk(tmp_path / "finnes-ikke.gguf")
    assert dom["holder"] is False
    assert any("Fant ikke" in linje for linje in dom["linjer"])


# ------------------------------------------------------------------ #
#  Spørsmålskorpuset                                                  #
# ------------------------------------------------------------------ #

def test_korpuset_finnes_og_har_begge_grupper():
    import kjor_sporsmaalskorpus as k
    fasit = k.les_fasit()
    sporsmaal = fasit["sporsmaal"]
    assert len(sporsmaal) >= 40, "korpuset er for lite til å måle noe"
    grupper = {s.get("svares_av", "modell") for s in sporsmaal}
    assert grupper == {"modell", "kode"}, (
        "korpuset trenger BEGGE grupper: modellspørsmålene måler modellen, "
        "kodespørsmålene er kontrollgruppen som avslører brutt ruting")


def test_hvert_sporsmaal_kan_faktisk_dommes():
    """Et spørsmål uten en sjekk er en mening, ikke en måling."""
    import kjor_sporsmaalskorpus as k
    for sp in k.les_fasit()["sporsmaal"]:
        assert any(sp.get(n) for n in ("maa_inneholde", "ett_av", "felt")), (
            f"«{sp['id']}» har ingen sjekk — det kan aldri feile")
        assert sp.get("fasit"), f"«{sp['id']}» mangler fasit for et menneske"


def test_ingen_personnumre_i_fasitfila():
    """Fasiten ligger i git for alltid. Fødselsnumre og kontonumre
    sjekkes derfor mot uttrekket ved kjøretid, aldri som verdier her."""
    import io
    import os
    import re
    sti = os.path.join("tester", "korpus", "sporsmaal_syntetisk_bunke.json")
    tekst = io.open(sti, encoding="utf-8").read()
    for treff in re.findall(r"\b\d{11}\b", tekst):
        assert treff == "1002345678911", (
            f"ellevesifret tall i fasiten: {treff} — bruk «felt» i stedet")


def test_svarvurderingen_normaliserer_mellomrom_i_tall():
    """«4 812,00» og «4812,00» er samme beløp. En fasit som bare godtar
    den ene formen måler skrivemåte, ikke riktighet."""
    import kjor_sporsmaalskorpus as k
    sp = {"maa_inneholde": ["4812"]}
    assert k.vurder_svar(sp, "Beløpet er 4 812,00 kroner.", {})[0] is True
    assert k.vurder_svar(sp, "Beløpet er 5 000 kroner.", {})[0] is False


def test_felt_sjekken_maaler_mot_uttrekket():
    # Numrene bygges på KJØRETID (syntetiske_nummer) — et ellevesifret
    # tall i kildekoden ser ut som et fødselsnummer uansett hvor
    # syntetisk det er ment å være.
    from syntetiske_nummer import lag_kontonummer
    riktig, feil = lag_kontonummer(0), lag_kontonummer(1)
    import kjor_sporsmaalskorpus as k
    svar = {"struktur": {"identifikatorer": {"kontonummer": [riktig]}}}
    sp = {"felt": "struktur.identifikatorer.kontonummer.0"}
    assert k.vurder_svar(sp, f"Kontonummeret er {riktig}.", svar)[0] is True
    assert k.vurder_svar(sp, f"Kontonummeret er {feil}.", svar)[0] is False


def test_manglende_uttrekk_teller_ikke_som_bestatt():
    """R146: «kan ikke dømmes» er ikke «riktig»."""
    import kjor_sporsmaalskorpus as k
    sp = {"felt": "struktur.identifikatorer.kontonummer.0"}
    bestatt, grunn = k.vurder_svar(sp, "Et eller annet svar", {})
    assert bestatt is False
    assert "ingen verdi" in grunn


def test_tomt_svar_er_aldri_bestatt():
    import kjor_sporsmaalskorpus as k
    assert k.vurder_svar({"ett_av": ["noe"]}, "", {})[0] is False


# ------------------------------------------------------------------ #
#  Parvis dom (R196): riktig test for to kjøringer av SAMME korpus    #
# ------------------------------------------------------------------ #

def test_mcnemar_teller_bare_det_som_endret_seg(bytt):
    """De spørsmålene som var riktige begge ganger sier ingenting om
    hvilken modell som er best. Bare endringene bærer informasjon."""
    live = [1, 1, 1, 0, 0]
    kand = [1, 1, 0, 1, 1]
    rettet, odelagt, p = bytt.mcnemar(live, kand)
    assert (rettet, odelagt) == (2, 1)


def test_parvis_test_ser_forskjellen_uavhengige_intervaller_mister(bytt):
    """DEN EKTE MÅLINGEN som avslørte at porten brukte feil test: 27
    spørsmål rettet, 7 ødelagt av 133. Uavhengige konfidensintervaller
    overlapper og sier «ikke skillbar»; den parvise testen ser det
    tydelig (p = 0,0008)."""
    live = [1] * 89 + [0] * 44
    kand = [1] * 82 + [0] * 7 + [1] * 27 + [0] * 17
    assert sum(kand) == 109
    rettet, odelagt, p = bytt.mcnemar(live, kand)
    assert (rettet, odelagt) == (27, 7)
    assert p < 0.01
    assert bytt.overlapper(bytt.bootstrap_ki(kand),
                           bytt.bootstrap_ki(live)) is True, (
        "forutsetningen for testen er borte — intervallene overlapper ikke "
        "lenger, og da illustrerer den ikke poenget")
    assert bytt.dom(_maaling(live), _maaling(kand))["grunn"] == "bedre"


def test_identiske_kjoringer_er_ikke_en_forbedring(bytt):
    rettet, odelagt, p = bytt.mcnemar([1, 0, 1], [1, 0, 1])
    assert (rettet, odelagt, p) == (0, 0, 1.0)


def test_ulik_lengde_gir_ingen_dom(bytt):
    assert bytt.mcnemar([1, 0], [1, 0, 1])[2] is None

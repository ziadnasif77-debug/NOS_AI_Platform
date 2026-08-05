"""
Tester for navngitte API-nøkler og klientidentitet (R91).

Revisjonen kalte dette forutsetningen for hele fase 4: uten
klientidentitet er hver forespørsel anonym, spørsmålet «bruker noen
fortsatt dette?» har ikke noe svar, og et utgått felt må derfor stå for
alltid.

To ting testes særlig hardt: at den gamle enkeltnøkkelen fortsatt
virker (ellers brekker hver eksisterende integrasjon i det øyeblikket
navngitte nøkler skrus på), og at nøkkelen aldri havner i loggen.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import klientrapport
from delt.klienter import (AAPEN, ELDRE, MINSTE_LENGDE, finn_klient,
                           gjenbrukte_nokler, les_nokler, svake_nokler)

LANG_A = "a" * 40
LANG_B = "b" * 40


# ------------------------------------------------------------------ #
#  1. Tolking av API_NOKLER                                            #
# ------------------------------------------------------------------ #

def test_navn_og_nokkel_skilles_pa_forste_kolon():
    """Alt etter FØRSTE kolon er nøkkelen, så en nøkkel kan selv
    inneholde kolon uten å bli klippet."""
    nokler = les_nokler(f"uipath:{LANG_A},arkiv:nokkel:med:kolon")
    assert nokler == {"uipath": LANG_A, "arkiv": "nokkel:med:kolon"}


def test_mellomrom_og_tomme_ledd_tas_ikke_med():
    assert les_nokler(f" uipath : {LANG_A} , , ugyldig ,") == {"uipath": LANG_A}


def test_tom_konfigurasjon_gir_tomt_kart():
    for raa in ("", None, "   ", ","):
        assert les_nokler(raa) == {}


# ------------------------------------------------------------------ #
#  2. Oppslag                                                          #
# ------------------------------------------------------------------ #

def test_riktig_nokkel_gir_klientens_navn():
    nokler = {"uipath": LANG_A, "arkiv": LANG_B}
    assert finn_klient(LANG_A, nokler) == "uipath"
    assert finn_klient(LANG_B, nokler) == "arkiv"


def test_ukjent_nokkel_gir_ingen_klient():
    assert finn_klient("feil", {"uipath": LANG_A}) is None
    assert finn_klient("", {"uipath": LANG_A}) is None
    assert finn_klient(None, {"uipath": LANG_A}) is None


def test_den_gamle_enkeltnokkelen_virker_fortsatt():
    """Uten dette brekker HVER eksisterende integrasjon i det øyeblikket
    navngitte nøkler skrus på. Den får sitt eget navn i loggen, så man
    ser hvem som ennå ikke har byttet."""
    assert finn_klient(LANG_A, {}, eldre_nokkel=LANG_A) == ELDRE
    assert finn_klient(LANG_B, {"ny": LANG_B}, eldre_nokkel=LANG_A) == "ny"


def test_en_nokkel_som_ligner_slipper_ikke_inn():
    """compare_digest, ikke `in` eller startswith."""
    nokler = {"uipath": LANG_A}
    assert finn_klient(LANG_A[:-1], nokler) is None
    assert finn_klient(LANG_A + "x", nokler) is None


def test_oppslaget_gar_gjennom_ALLE_noklene():
    """Ingen tidlig utgang: svartiden skal ikke røpe hvilken nøkkel som
    traff eller hvor langt ut i lista den lå. Målt indirekte — en nøkkel
    sist i lista må finnes like sikkert som en først."""
    nokler = {f"klient{i:02d}": f"{i:02d}" + "x" * 38 for i in range(20)}
    for navn, nokkel in nokler.items():
        assert finn_klient(nokkel, nokler) == navn


# ------------------------------------------------------------------ #
#  3. Advarsler ved oppstart                                           #
# ------------------------------------------------------------------ #

def test_for_korte_nokler_meldes():
    svake = svake_nokler({"kort": "abc", "lang": LANG_A})
    assert svake == ["kort"]
    assert len("abc") < MINSTE_LENGDE


def test_to_klienter_med_samme_nokkel_meldes():
    """To navn med samme nøkkel er ÉN klient med to navn — og da lyver
    klient_id i loggen, som er det eneste hele ordningen bygger på."""
    delte = gjenbrukte_nokler({"a": LANG_A, "b": LANG_A, "c": LANG_B})
    assert delte == [["a", "b"]]


def test_ulike_nokler_gir_ingen_advarsel():
    assert gjenbrukte_nokler({"a": LANG_A, "b": LANG_B}) == []


# ------------------------------------------------------------------ #
#  4. Serveren: nøkkelen skal ALDRI i loggen                           #
# ------------------------------------------------------------------ #

def test_tilgangsloggen_far_navnet_men_aldri_nokkelen(tmp_path, monkeypatch):
    """En nøkkel i en logg er en lekkasje som overlever i
    sikkerhetskopier. Et navn er nyttig."""
    import dokument_api as api

    logg = tmp_path / "tilgang.log"
    monkeypatch.setattr(api, "TILGANGSLOGG_STI", str(logg))
    monkeypatch.setattr(api, "_tilgang_logger", None)

    class Falsk:
        command = "POST"
        path = "/dokument?x=1"
        headers = {"X-API-Key": LANG_A}
        _korr_id = "abc"
        _klient_id = "uipath-fakturamottak"

        def _klient_ip(self):
            return "127.0.0.1"

    api._skriv_tilgang(Falsk(), 200)
    for h in api._tilgangslogger().handlers:
        h.flush()

    innhold = logg.read_text(encoding="utf-8")
    assert LANG_A not in innhold, "NØKKELEN havnet i tilgangsloggen"
    rad = json.loads(innhold.strip().splitlines()[-1])
    assert rad["klient_id"] == "uipath-fakturamottak"
    assert rad["nokkel"] is True
    assert rad["sti"] == "/dokument"        # query droppes (kan bære PII)


def test_apen_modus_sier_apen_ikke_tomt():
    """«Ingen nøkkel påkrevd» og «nøkkelen traff ingen» er ikke det
    samme, og loggen skal kunne skille dem."""
    assert AAPEN and AAPEN != ELDRE


# ------------------------------------------------------------------ #
#  5. Rapporten                                                        #
# ------------------------------------------------------------------ #

def _skriv_logg(sti, rader):
    with open(sti, "w", encoding="utf-8") as f:
        for rad in rader:
            f.write(json.dumps(rad, ensure_ascii=False) + "\n")


def test_rapporten_teller_per_klient_og_sti(tmp_path):
    logg = tmp_path / "t.log"
    _skriv_logg(logg, [
        {"t": "2026-08-05T10:00:00", "klient_id": "uipath",
         "sti": "/dokument", "kode": 200},
        {"t": "2026-08-05T10:00:01", "klient_id": "uipath",
         "sti": "/dokument", "kode": 500},
        {"t": "2026-08-05T10:00:02", "klient_id": "arkiv",
         "sti": "/analyser", "kode": 200},
    ])
    r = klientrapport.oppsummer(klientrapport.les_rader(str(logg)))
    assert r["per_klient"]["uipath"] == 2
    assert r["feil"]["uipath"] == 1
    assert r["stier"]["arkiv"]["/analyser"] == 1


def test_rapporten_teller_rader_uten_klient_for_seg(tmp_path):
    """Rader fra før R91 kan ikke tilskrives noen. Blandes de inn i
    tellingene, ser et endepunkt ubrukt ut fordi kallene er anonyme —
    og da fjernes noe i god tro."""
    logg = tmp_path / "t.log"
    _skriv_logg(logg, [
        {"t": "2026-08-05T10:00:00", "sti": "/analyser", "kode": 200},
        {"t": "2026-08-05T10:00:01", "klient_id": "uipath",
         "sti": "/dokument", "kode": 200},
    ])
    r = klientrapport.oppsummer(klientrapport.les_rader(str(logg)))
    assert r["anonyme"] == 1
    assert "/analyser" not in r["stier"].get("uipath", {})


def test_hvem_bruker_svarer_tomt_nar_ingen_gjor_det(tmp_path):
    """Det tomme svaret er hele grunnen til at rapporten finnes."""
    logg = tmp_path / "t.log"
    _skriv_logg(logg, [{"t": "2026-08-05T10:00:00", "klient_id": "uipath",
                        "sti": "/dokument", "kode": 200}])
    rader = klientrapport.les_rader(str(logg))
    assert klientrapport.hvem_bruker(rader, "/uttrekk") == {}
    assert klientrapport.hvem_bruker(rader, "/dokument")["uipath"] == 1


def test_ukjent_sti_gir_feil_ikke_et_falskt_gront_lys(tmp_path, capsys,
                                                      monkeypatch):
    """Den farligste feilen rapporten kan gjøre. En sti som ikke finnes i
    loggen gir samme TOMME svar som en ubrukt sti — og her betyr tomt
    «trygt å pensjonere». En skrivefeil ville altså blitt lest som et
    grønt lys. (Reelt tilfelle: Git Bash gjør «/analyser» om til
    «C:/Program Files/Git/analyser» før skriptet ser det.)"""
    logg = tmp_path / "t.log"
    _skriv_logg(logg, [{"t": "2026-08-05T10:00:00", "klient_id": "uipath",
                        "sti": "/dokument", "kode": 200}])
    monkeypatch.setattr(klientrapport, "TILGANGSLOGG_STI", str(logg))
    kode = klientrapport.main(["--sti", "C:/Program Files/Git/analyser",
                               "--dager", "3650"])
    ut = capsys.readouterr().out
    assert kode == 1, "en ukjent sti må gi feilkode, ikke 0"
    assert "finnes ikke i loggen" in ut
    assert "/dokument" in ut, "de kjente stiene skal listes opp"


def test_kjent_sti_uten_klient_id_er_heller_ikke_gront_lys(tmp_path, capsys,
                                                           monkeypatch):
    """Kalt, men anonymt. Da vet vi at noen bruker den — bare ikke hvem.
    Det er det motsatte av grunnlag for å fjerne den."""
    logg = tmp_path / "t.log"
    _skriv_logg(logg, [{"t": "2026-08-05T10:00:00", "sti": "/analyser",
                        "kode": 200}])
    monkeypatch.setattr(klientrapport, "TILGANGSLOGG_STI", str(logg))
    kode = klientrapport.main(["--sti", "/analyser", "--dager", "3650"])
    assert kode == 1
    assert "kan ikke tilskrives noen" in capsys.readouterr().out


def test_halvskrevet_siste_linje_stopper_ikke_rapporten(tmp_path):
    """Normalt når serveren skriver mens rapporten leser."""
    logg = tmp_path / "t.log"
    with open(logg, "w", encoding="utf-8") as f:
        f.write('{"t": "2026-08-05T10:00:00", "klient_id": "a", '
                '"sti": "/dokument", "kode": 200}\n')
        f.write('{"t": "2026-08-05T10:00:01", "klient_i')
    rader = klientrapport.les_rader(str(logg))
    assert len(rader) == 1

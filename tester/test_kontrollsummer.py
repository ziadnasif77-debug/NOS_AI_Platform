"""
Offline-bunten skal være checksum-verifisert (§26, §23 — R211).

§26: «Offline installasjon skal være reproduserbar og
checksum-verifisert.» §23: bunten skal inneholde `/checksums` og
`release-manifest.json`, og «eksisterende offline-installasjonsverktøy
skal gjenbrukes og utvides».

Verktøyene fantes: `pakk_for_offline.py` bygger bunten,
`installer_offline.py` installerer den, og `MANIFEST.txt` sier hva som
ble pakket. Det som manglet var integriteten — ingenting kunne si om
bunten kom FRAM hel.

HVORFOR IKKE `avtrykk()` FRA bytt_modell.py
Den ville vært den naturlige gjenbruken, og det var også planen. Men den
hasher STØRRELSE + FØRSTE MiB med vilje, fordi den er et raskt
fingeravtrykk for GB-store modellfiler. Til integritet er det feil
verktøy: **en avbrutt nedlasting har et helt korrekt første MiB.** Det
var nøyaktig R202-feilen — en 6,5 MB fil som skulle vært 2,4 GB — og en
kontrollsum som ikke ville fanget den, er ingen kontrollsum.

To hasher for to formål er derfor riktig her, ikke duplisering.
"""
import io
import json
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

from delt import kontrollsummer


@pytest.fixture
def bunt(tmp_path):
    (tmp_path / "wheels").mkdir()
    (tmp_path / "wheels" / "pakke-1.0.whl").write_bytes(b"hjul" * 100)
    (tmp_path / "modeller").mkdir()
    (tmp_path / "modeller" / "liten.gguf").write_bytes(b"GGUF" + b"\x00" * 500)
    (tmp_path / "krav_lokal.txt").write_text("requests\n", encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------------ #
#  Hele filen — ikke bare starten                                     #
# ------------------------------------------------------------------ #

def test_en_avkortet_fil_blir_oppdaget(bunt):
    """Selve grunnen til at `avtrykk()` ikke kunne gjenbrukes. Fila her
    har IDENTISK start og identisk lengde på første MiB — bare halen er
    borte, som i en avbrutt nedlasting (R202)."""
    stor = bunt / "modeller" / "stor.bin"
    stor.write_bytes(b"A" * 3000)
    kontrollsummer.lag(str(bunt))
    stor.write_bytes(b"A" * 2000)          # samme start, kortere hale
    r = kontrollsummer.verifiser(str(bunt))
    assert not r["ok"]
    assert "modeller/stor.bin" in r["endret"], (
        "en avkortet fil ble ikke oppdaget — da hasher vi bare starten, "
        "og det var nettopp den feilen R202 handlet om")


def test_hel_bunt_er_ok(bunt):
    kontrollsummer.lag(str(bunt))
    r = kontrollsummer.verifiser(str(bunt))
    assert r["ok"] and r["sjekket"] == 3
    assert not r["mangler"] and not r["endret"]


# ------------------------------------------------------------------ #
#  Tre utfall som krever tre ulike handlinger                         #
# ------------------------------------------------------------------ #

def test_manglende_og_endret_holdes_fra_hverandre(bunt):
    """«Mangler» betyr at kopieringen ikke ble ferdig — kopier på nytt.
    «Endret» betyr at fila er ødelagt eller byttet ut — stopp. Én samlet
    «feil» ville gjort de to til samme sak."""
    kontrollsummer.lag(str(bunt))
    (bunt / "krav_lokal.txt").unlink()
    (bunt / "wheels" / "pakke-1.0.whl").write_bytes(b"noe helt annet")
    r = kontrollsummer.verifiser(str(bunt))
    assert r["mangler"] == ["krav_lokal.txt"]
    assert r["endret"] == ["wheels/pakke-1.0.whl"]


def test_ekstra_fil_er_ikke_det_samme_som_oedelagt(bunt):
    """En fil som er kommet til etterpå er som regel ufarlig. Teller
    man den som feil, blir verifiseringen rød av en loggfil — og da
    slutter folk å kjøre den."""
    kontrollsummer.lag(str(bunt))
    (bunt / "ny_logg.txt").write_text("noe", encoding="utf-8")
    r = kontrollsummer.verifiser(str(bunt))
    assert r["ok"], "en ekstra fil skal ikke gjøre bunten «ikke hel»"
    assert r["ekstra"] == ["ny_logg.txt"]


def test_manglende_sha256sums_er_ikke_stille_ok(bunt):
    """Ingen SHA256SUMS betyr IKKE «alt er bra» — det betyr at ingenting
    ble sjekket, og de to må ikke se like ut."""
    r = kontrollsummer.verifiser(str(bunt))
    assert not r["ok"]
    assert "mangler" in r["grunn"].lower()


# ------------------------------------------------------------------ #
#  Formatet §23 ber om                                                #
# ------------------------------------------------------------------ #

def test_sha256sums_har_standardformat(bunt):
    """Samme format som `sha256sum`: da kan bunten verifiseres med
    standardverktøy hvis vårt skript av en eller annen grunn ikke
    finnes på serveren."""
    kontrollsummer.lag(str(bunt))
    linjer = (bunt / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert linjer
    for linje in linjer:
        sum_, navn = linje.split("  ", 1)
        assert len(sum_) == 64 and all(c in "0123456789abcdef" for c in sum_)
        assert "\\" not in navn, "stier skal bruke / så fila er plattformnøytral"


def test_release_manifest_finnes_og_sier_hva_bunten_er(bunt):
    """§23 navngir fila. Den skal si hva bunten ER, ikke bare hva den
    inneholder."""
    kontrollsummer.lag(str(bunt), versjon="1.2.3")
    m = json.loads((bunt / "release-manifest.json").read_text(encoding="utf-8"))
    assert m["versjon"] == "1.2.3"
    for felt in ("bygget", "antall_filer", "sum_bytes", "algoritme"):
        assert felt in m
    assert "HELE" in m["algoritme"], (
        "manifestet sier ikke at hele filen hashes — og det er nettopp "
        "det som skiller den fra et fingeravtrykk")


def test_egne_filer_telles_ikke_med(bunt):
    """SHA256SUMS kan ikke inneholde sin egen sum."""
    kontrollsummer.lag(str(bunt))
    navn = set(kontrollsummer.les_summer(str(bunt)))
    assert "SHA256SUMS" not in navn
    assert "release-manifest.json" not in navn


# ------------------------------------------------------------------ #
#  Verktøyene er UTVIDET, ikke erstattet (§23)                        #
# ------------------------------------------------------------------ #

def _kilde(navn):
    """Leser skriptet som TEKST i stedet for å importere det.

    De to offline-skriptene bytter ut `sys.stdout` ved import — de er
    ment å kjøres som kommandolinjeverktøy, ikke importeres. Under
    pytest river det capture-mekanismen ned. Å lese kilden gir samme
    svar for en kildekontroll, uten bivirkningen."""
    return io.open(os.path.join("skript", navn), encoding="utf-8").read()


def test_pakkingen_skriver_kontrollsummer_selv():
    """Var det et eget skript man måtte huske å kjøre, ville den første
    bunten noen laget i en fart vært uten."""
    kilde = _kilde("pakk_for_offline.py")
    assert "_skriv_kontrollsummer" in kilde
    assert "kontrollsummer.lag" in kilde


def test_installasjonen_verifiserer_FOR_den_installerer():
    """Etterpå er verifiseringen en obduksjon."""
    kilde = _kilde("installer_offline.py")
    plass_verifiser = kilde.index("    _verifiser_bunten()")
    plass_install = kilde.index("[1/3] Installerer hjul")
    assert plass_verifiser < plass_install, (
        "installasjonen begynner før bunten er verifisert")


def test_installasjonen_STOPPER_ved_avvik():
    """En sjekk som skriver «advarsel» og fortsetter, er en sjekk ingen
    oppdager at feilet."""
    kilde = _kilde("installer_offline.py")
    assert "BUNTEN ER IKKE HEL" in kilde
    assert "STOPPET" in kilde
    assert "raise SystemExit" in kilde


def test_gammel_bunt_uten_summer_sier_det_hoyt():
    """En bunt fra et eldre verktøy skal kunne installeres — men ingen
    skal TRO at den ble verifisert."""
    assert "IKKE verifisert" in _kilde("installer_offline.py")

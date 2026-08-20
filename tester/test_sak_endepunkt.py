"""
R244: POST /sak — flere dokumenter lest som ÉN sak.

Endepunktet er den første ruten som leser MER ENN ÉN fil. Multipart-
parseren har alltid latt «første fil vinne» og kastet resten i stillhet,
så /sak går sin egen vei gjennom kroppen — men gjennom SAMME
delegjennomgang (`_multipart_deler`), ikke en kopi av den. To parsere
ville før eller siden blitt uenige om en klientvariant, og det er
nettopp klientvariantene parseren finnes for (R63/R111).

Testene dekker tre ting: at flere filer faktisk blir lest, at det som
IKKE kom med blir sagt, og at svaret ikke sprer fødselsnumre bredere enn
oppgaven krever.
"""
import json
import sys
import types

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api as api


# ------------------------------------------------------------------ #
#  Testrigg                                                           #
# ------------------------------------------------------------------ #

def _handler():
    h = api.Handler.__new__(api.Handler)
    h.headers = {}
    h.path = "/sak"
    h.command = "POST"
    h.client_address = ("127.0.0.1", 4321)
    fanget = {}
    h.send_response = lambda k: fanget.__setitem__("kode", k)
    h.send_header = lambda n, v: None
    h.end_headers = lambda: None
    h.wfile = types.SimpleNamespace(
        write=lambda b: fanget.__setitem__("kropp", json.loads(b)))
    h._cors_origin = lambda: None
    h._eier_jobben = lambda jobb: True
    return h, fanget


GRENSE = "----prove"


def _kropp(filer=(), felter=()):
    """Bygger en multipart-kropp med FLERE filer."""
    biter = []
    for filnavn, data in filer:
        biter.append(
            f"--{GRENSE}\r\nContent-Disposition: form-data; name=\"fil\"; "
            f"filename=\"{filnavn}\"\r\n\r\n".encode() + data + b"\r\n")
    for navn, verdi in felter:
        biter.append(
            f"--{GRENSE}\r\nContent-Disposition: form-data; "
            f"name=\"{navn}\"\r\n\r\n{verdi}\r\n".encode())
    biter.append(f"--{GRENSE}--\r\n".encode())
    return b"".join(biter), f"multipart/form-data; boundary={GRENSE}"


def _pdf(linjer) -> bytes:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    side = doc.new_page()
    y = 80
    for linje in linjer:
        side.insert_text((60, y), linje, fontsize=12)
        y += 22
    data = doc.tobytes()
    doc.close()
    return data


SOKNAD = ("Søknad om sykepenger", "Saksnummer: 4417820",
          "Mottatt: 10.01.2026")
VEDTAK = ("Vedtak om sykepenger", "Saksnummer: 4417820",
          "Vedtaksdato: 01.02.2026")
ANNEN = ("Vedtak om dagpenger", "Saksnummer: 9990001",
         "Vedtaksdato: 03.03.2026")


def _svar(filer=(), felter=(), handler=None):
    h, fanget = handler or _handler()
    body, ct = _kropp(filer, felter)
    tekstfelter = api._parse_multipart(body, ct)[2]
    h._sak(body, ct, tekstfelter)
    return fanget


@pytest.fixture(autouse=True)
def eget_lager(tmp_path, monkeypatch):
    """Hver test får sin egen lagermappe — aldri den ekte data/saker."""
    from delt import sakslager
    monkeypatch.setattr(sakslager, "SAK_STI", str(tmp_path / "saker"))
    return sakslager


# ------------------------------------------------------------------ #
#  Flere filer blir faktisk lest                                      #
# ------------------------------------------------------------------ #

def test_to_filer_blir_til_en_sak():
    fanget = _svar([("1.pdf", _pdf(SOKNAD)), ("2.pdf", _pdf(VEDTAK))])
    assert fanget["kode"] == 200
    svar = fanget["kropp"]
    assert svar["ok"] is True
    assert svar["antall_dokumenter"] == 2, (
        "bare én fil ble lest — «første fil vinner» har lekket inn i /sak")
    assert svar["antall_saker"] == 1
    assert svar["saker"][0]["nokkel"]["verdi"] == "4417820"


def test_ulike_saksnumre_gir_ulike_saker():
    fanget = _svar([("1.pdf", _pdf(SOKNAD)), ("2.pdf", _pdf(ANNEN))])
    assert fanget["kropp"]["antall_saker"] == 2


def test_tidslinjen_er_med_og_er_kronologisk():
    fanget = _svar([("2.pdf", _pdf(VEDTAK)), ("1.pdf", _pdf(SOKNAD))])
    tidslinje = fanget["kropp"]["saker"][0]["tidslinje"]
    datoer = [h["dato"] for h in tidslinje["hendelser"]]
    assert datoer == sorted(datoer)
    assert tidslinje["fra"] <= tidslinje["til"]


def test_motsigelsene_rapporterer_hva_som_ble_sjekket():
    """Et tomt funn er ingen frikjennelse (R128)."""
    fanget = _svar([("1.pdf", _pdf(SOKNAD))])
    motsigelser = fanget["kropp"]["saker"][0]["motsigelser"]
    assert motsigelser["funn"] == []
    assert "flere_personer" in motsigelser["sjekket"]


def test_umulig_rekkefolge_meldes_gjennom_endepunktet():
    """Vedtaket er datert før søknaden det svarer på."""
    fanget = _svar([
        ("1.pdf", _pdf(("Søknad om sykepenger", "Saksnummer: 4417820",
                        "Mottatt: 01.05.2026"))),
        ("2.pdf", _pdf(("Vedtak om sykepenger", "Saksnummer: 4417820",
                        "Vedtaksdato: 01.02.2026"))),
    ])
    funn = fanget["kropp"]["saker"][0]["motsigelser"]["funn"]
    assert [f["type"] for f in funn] == ["umulig_rekkefolge"]


# ------------------------------------------------------------------ #
#  Det som ikke kom med, blir sagt                                    #
# ------------------------------------------------------------------ #

def test_ingen_dokumenter_gir_400_som_sier_hva_som_mangler():
    fanget = _svar([])
    assert fanget["kode"] == 400
    assert "jobb_id" in fanget["kropp"]["feil"]


def test_ukjent_jobb_id_meldes_i_uleste_uten_a_felle_kallet():
    """R24: en sak bygget av færre dokumenter enn klienten sendte, er en
    annen sak — forskjellen skal ikke måtte gjettes."""
    fanget = _svar([("1.pdf", _pdf(SOKNAD))],
                   [("jobb_id", "finnesikke123")])
    svar = fanget["kropp"]
    assert svar["ok"] is True
    assert svar["antall_dokumenter"] == 1
    assert svar["uleste"] == [{"kilde": "finnesikke123",
                               "feil": "Ukjent jobb_id"}]


def test_korrupt_fil_stopper_ikke_resten_av_mappa():
    fanget = _svar([("1.pdf", _pdf(SOKNAD)), ("ødelagt.pdf", b"ikke en pdf")])
    svar = fanget["kropp"]
    assert svar["antall_dokumenter"] == 1
    assert len(svar["uleste"]) == 1
    assert svar["uleste"][0]["kilde"] == "ødelagt.pdf"


def test_for_mange_filer_avvises_med_veien_videre():
    filer = [(f"{i}.pdf", _pdf(SOKNAD))
             for i in range(api.MAKS_SAKSFILER + 1)]
    fanget = _svar(filer)
    assert fanget["kode"] == 400
    assert "POST /jobb" in fanget["kropp"]["feil"]


# ------------------------------------------------------------------ #
#  Personvern og kontrakt                                             #
# ------------------------------------------------------------------ #

def test_dokumentlista_gjentar_ikke_fodselsnummer():
    """Grupperingen trenger fødselsnummeret; svaret trenger det ikke per
    dokument. Hvem saken gjelder står i «relasjoner» når det betyr noe."""
    fanget = _svar([("1.pdf", _pdf(SOKNAD)), ("2.pdf", _pdf(VEDTAK))])
    for sak in fanget["kropp"]["saker"]:
        for dok in sak["dokumenter"]:
            assert "fnr" not in dok


def test_svaret_er_flatt_og_har_de_faste_feltene():
    """UiPath leser svaret felt for felt; formen er kontrakten."""
    svar = _svar([("1.pdf", _pdf(SOKNAD))])["kropp"]
    for felt in ("ok", "antall_dokumenter", "antall_saker", "saker",
                 "relasjoner", "uleste", "forklaring", "versjon"):
        assert felt in svar, f"svaret mangler «{felt}»"


def test_ingen_sprakmodell_er_involvert():
    """Saken er deterministisk. Kalles modellen herfra, blir svaret
    hverken reproduserbart eller raskt."""
    import inspect
    kilde = inspect.getsource(api.Handler._sak) \
        + inspect.getsource(api.Handler._saksdokument)
    for forbudt in ("_borealis_generer", "prompter.hent", "klassifiser_borealis"):
        assert forbudt not in kilde, f"/sak kaller {forbudt}"


def test_samme_mappe_gir_samme_svar():
    """R6 — to kall, samme resultat."""
    filer = [("1.pdf", _pdf(SOKNAD)), ("2.pdf", _pdf(VEDTAK))]
    assert _svar(filer)["kropp"]["saker"] == _svar(filer)["kropp"]["saker"]


# ------------------------------------------------------------------ #
#  Ruting og felt                                                     #
# ------------------------------------------------------------------ #

def test_ruten_er_kjent_og_har_et_feltsett():
    """Feltsettet er kontrakten: et felt som ikke står her, blir avvist
    som ukjent i stedet for å forsvinne i stillhet."""
    assert "/sak" in api._FELTSETT_PER_RUTE
    assert api._FELTSETT_PER_RUTE["/sak"] == {"jobb_id", "sak_id"}


# ------------------------------------------------------------------ #
#  R245: mappa overlever forespørselen                                #
# ------------------------------------------------------------------ #

def test_svaret_gir_en_sak_id_aa_bygge_videre_paa():
    svar = _svar([("1.pdf", _pdf(SOKNAD))])["kropp"]
    from delt import sakslager
    assert sakslager.gyldig_id(svar["sak_id"])
    assert svar["lagt_til"] == 1
    assert svar["duplikater_hoppet_over"] == 0


def test_dokumenter_kan_legges_til_i_flere_kall():
    """Selve poenget med R245: arkivet bygges over tid, ikke i ett kall."""
    forste = _svar([("1.pdf", _pdf(SOKNAD))])["kropp"]
    andre = _svar([("2.pdf", _pdf(VEDTAK))],
                  [("sak_id", forste["sak_id"])])["kropp"]

    assert andre["sak_id"] == forste["sak_id"]
    assert andre["antall_dokumenter"] == 2
    assert andre["antall_saker"] == 1
    assert [h["filnavn"] for h in andre["saker"][0]["tidslinje"]["hendelser"]] \
        == ["1.pdf", "2.pdf"]


def test_samme_fil_sendt_paa_nytt_dobler_ikke_saken():
    """En robot som prøver igjen etter et nettverksbrudd sender de samme
    filene. Uten duplikatvakten ville tidslinjen fått dem to ganger."""
    forste = _svar([("1.pdf", _pdf(SOKNAD))])["kropp"]
    igjen = _svar([("1.pdf", _pdf(SOKNAD))],
                  [("sak_id", forste["sak_id"])])["kropp"]

    assert igjen["antall_dokumenter"] == 1
    assert igjen["lagt_til"] == 0
    assert igjen["duplikater_hoppet_over"] == 1


def test_mappa_kan_hentes_tilbake_med_get():
    forste = _svar([("1.pdf", _pdf(SOKNAD)), ("2.pdf", _pdf(VEDTAK))])["kropp"]
    h, fanget = _handler()
    h._hent_sak(forste["sak_id"])
    assert fanget["kode"] == 200
    assert fanget["kropp"]["antall_dokumenter"] == 2
    assert fanget["kropp"]["sak_id"] == forste["sak_id"]


def test_ukjent_sak_id_gir_404_ved_henting():
    h, fanget = _handler()
    h._hent_sak("abc123abc123")
    assert fanget["kode"] == 404


def test_ukjent_sak_id_gir_404_ved_paafylling():
    fanget = _svar([("1.pdf", _pdf(SOKNAD))], [("sak_id", "abc123abc123")])
    assert fanget["kode"] == 404


def test_ugyldig_sak_id_avvises_for_den_naar_filsystemet():
    """«../../noe» er ikke en id, det er en sti."""
    fanget = _svar([("1.pdf", _pdf(SOKNAD))], [("sak_id", "../../noe")])
    assert fanget["kode"] == 400
    assert "heksesiffer" in fanget["kropp"]["feil"]


def test_en_annens_mappe_finnes_ikke():
    """R153: å legge dokumenter i en annens saksmappe er verre enn å
    lese den — det endrer en sak noen andre bygger."""
    h1, _ = _handler()
    h1._klient_id = "robot-1"
    h1._eier_jobben = lambda jobb: True
    forste = _svar([("1.pdf", _pdf(SOKNAD))], handler=(h1, {}))
    # _svar returnerte fanget-dicten fra h1; hent id-en derfra
    h1b, fanget1 = _handler()
    h1b._klient_id = "robot-1"
    sak_id = _svar([("1.pdf", _pdf(SOKNAD))],
                   handler=(h1b, fanget1))["kropp"]["sak_id"]

    h2, fanget2 = _handler()
    h2._klient_id = "robot-2"
    h2._hent_sak(sak_id)
    assert fanget2["kode"] == 404, "en annen klient fikk lese mappa"


def test_grupperingen_regnes_ved_hver_lesing():
    """Lagret gruppering ville frosset reglene slik de var den dagen."""
    forste = _svar([("1.pdf", _pdf(SOKNAD))])["kropp"]
    from delt import sakslager
    lagret = sakslager.hent(forste["sak_id"])
    assert "saker" not in lagret and "tidslinje" not in lagret


def test_paafylling_uten_nye_filer_er_lov_og_gir_mappa_tilbake():
    """En klient som bare vil se mappa si skal ikke måtte sende en fil."""
    forste = _svar([("1.pdf", _pdf(SOKNAD))])["kropp"]
    igjen = _svar([], [("sak_id", forste["sak_id"])])
    assert igjen["kode"] == 200
    assert igjen["kropp"]["antall_dokumenter"] == 1


def test_jobb_ider_taaler_komma_mellomrom_og_linjeskift():
    assert api._jobb_ider("a, b\nc;d  e") == ["a", "b", "c", "d", "e"]
    assert api._jobb_ider("a, a, b") == ["a", "b"]
    assert api._jobb_ider("") == []
    assert api._jobb_ider(None) == []

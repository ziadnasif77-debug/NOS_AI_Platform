"""
/ekko må se det serveren FAKTISK forstår.

Ruten finnes for å feilsøke klienter der tekstfeltene «forsvinner» —
UiPath og andre .NET-baserte klienter, som sender bare LF og usiterte
feltnavn (R63). Den hadde sin egen, naive parsing: `split("boundary=")`
uten å stoppe ved neste «;», og et hardkodet `\\r\\n\\r\\n`.

Målt mot kjørende server, .NET-formen:

    antall_deler              0        «jeg mottok ingenting»
    parser_ser.tekstfelt_navn ['sporsmal']
    /dokument på samme kropp  HTTP 200

Én halvdel av svaret var ærlig og den andre blind. En utvikler som
åpnet /ekko for å finne ut hvorfor feltene forsvant, leste «null deler»
og mistenkte sin egen klient — mens serveren hadde mottatt alt.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api

G = "----ekkoprove"


def _kropp(nylinje="\r\n", siter=True, ct_ekstra=""):
    n = '"sporsmal"' if siter else "sporsmal"
    f = '"fil"' if siter else "fil"
    d = [f"--{G}{nylinje}Content-Disposition: form-data; "
         f"name={n}{nylinje}{nylinje}Hva er beløpet?{nylinje}",
         f"--{G}{nylinje}Content-Disposition: form-data; "
         f'name={f}; filename="dok.txt"{nylinje}'
         f"Content-Type: text/plain{nylinje}{nylinje}INNHOLD{nylinje}",
         f"--{G}--{nylinje}"]
    ct = f"multipart/form-data; boundary={G}{ct_ekstra}"
    return "".join(d).encode("utf-8"), ct


def _ekko(kropp, ct):
    H = api.Handler

    class Fake:
        _ekko = H._ekko

        def __init__(self):
            self.svar = None

        def _svar(self, kode, data, hoder=None):
            self.svar = (kode, data)
            return (kode, data)

    f = Fake()
    f._ekko(kropp, ct)
    return f.svar[1]


VARIANTER = {
    "vanlig CRLF, siterte navn": _kropp(),
    "bare LF, usiterte navn (.NET)": _kropp(nylinje="\n", siter=False),
    "usiterte navn, CRLF": _kropp(siter=False),
    "bare LF, siterte navn": _kropp(nylinje="\n"),
    "boundary med ekstra parameter": _kropp(ct_ekstra="; charset=utf-8"),
}


@pytest.mark.parametrize("merke", sorted(VARIANTER))
def test_ekko_ser_alle_delene(merke):
    """Kjernen: to deler sendt, to deler sett — i HVER variant."""
    kropp, ct = VARIANTER[merke]
    svar = _ekko(kropp, ct)
    assert svar["antall_deler"] == 2, (
        f"«{merke}»: /ekko så {svar['antall_deler']} av 2 deler")


@pytest.mark.parametrize("merke", sorted(VARIANTER))
def test_de_to_halvdelene_er_enige(merke):
    """Det var uenigheten som var feilen: `parser_ser` fant alt mens
    `raa_deler` var tom, i SAMME svar."""
    kropp, ct = VARIANTER[merke]
    svar = _ekko(kropp, ct)
    fra_raa = {d["tolket_feltnavn"] for d in svar["raa_deler"]
               if d["tolket_feltnavn"] and not d["tolket_filnavn"]}
    assert fra_raa == set(svar["parser_ser"]["tekstfelt_navn"]), (
        f"«{merke}»: raa_deler og parser_ser er uenige")


def test_diagnosen_navngir_R63_variantene():
    """Uten dette måtte utvikleren sammenligne rå bytes selv for å se om
    klienten sender formen som pleide å falle ut."""
    kropp, ct = _kropp(nylinje="\n", siter=False)
    d = _ekko(kropp, ct)["diagnose"]
    assert d["bare_lf"] is True
    assert d["usiterte_feltnavn"] is True

    kropp, ct = _kropp()
    d = _ekko(kropp, ct)["diagnose"]
    assert d["bare_lf"] is False
    assert d["usiterte_feltnavn"] is False


def test_boundary_med_flere_parametre():
    """Den naive `split("boundary=")` tok med alt som fulgte, så en
    Content-Type med «; charset=utf-8» ga en boundary som ikke fantes i
    kroppen — og ALT forsvant."""
    kropp, ct = _kropp(ct_ekstra="; charset=utf-8")
    svar = _ekko(kropp, ct)
    assert svar["boundary"] == G
    assert svar["antall_deler"] == 2


def test_uten_fil_er_fil_bytes_null_ikke_null_bytes():
    """R128: «ingen fil» og «en fil på null bytes» er ulike svar."""
    kropp = (f"--{G}\r\nContent-Disposition: form-data; "
             f'name="sporsmal"\r\n\r\nhei\r\n--{G}--\r\n').encode()
    svar = _ekko(kropp, f"multipart/form-data; boundary={G}")
    assert svar["parser_ser"]["fil_bytes"] is None


def test_ikke_multipart_gir_tom_liste_ikke_krasj():
    """En ren PDF-kropp har genuint ingen deler — [] er riktig der."""
    svar = _ekko(b"%PDF-1.4 ...", "application/pdf")
    assert svar["raa_deler"] == []
    assert svar["antall_deler"] == 0
    assert svar["boundary"] is None


def test_ekko_bruker_den_ekte_parserens_hjelpere():
    """Vakt mot at den naive kopien snek seg inn igjen. To parsinger av
    samme format vil alltid gli fra hverandre — det var hele feilen.

    KODEN måles, ikke kommentarene: forklaringen over funksjonen SITERER
    den gamle, naive splitten for å si hva som var galt, og et rent
    tekstsøk fant sitatet. Tredje gang samme felle i denne runden — så
    strimlingen står i en egen hjelper nå."""
    import inspect
    kilde = "\n".join(
        l for l in inspect.getsource(api.Handler._ekko).splitlines()
        if not l.strip().startswith("#"))
    assert '_cd_parameter' in kilde, "/ekko må bruke den ekte grenselesingen"
    assert 'split("boundary=' not in kilde, "den naive splitten er tilbake"
    assert 'b"\\r\\n\\r\\n"' not in kilde, (
        "hardkodet CRLF er tilbake — da faller bare-LF-kropper ut igjen")

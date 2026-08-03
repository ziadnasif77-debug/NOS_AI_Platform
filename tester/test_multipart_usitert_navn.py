"""
R63 — multipart-parseren droppet ALLE tekstfelter fra .NET-klienter.

Funnet ved ekte UiPath-testing mot en taxikvittering fra en annen maskin:
fila kom fram, men «sporsmal» (og tidligere «skjema_mal»/«skjema_motor»)
nådde aldri serveren. Svaret var et misvisende 200 med valg.svar=false.

Årsaken: RFC 7578 sier parameterverdien BØR siteres, men .NET —
og dermed UiPath — sender et enkelt token USITERT:

    Content-Disposition: form-data; name=sporsmal          <- .NET
    Content-Disposition: form-data; name="sporsmal"        <- curl m.fl.

Parseren krevde `name="` med anførselstegn. Fila slapp likevel gjennom
fordi et filnavn med mellomrom («Taxi fra.pdf») MÅ siteres — derfor så
det ut som om bare tekstfeltene forsvant.

Ren parserlogikk — ingen socket, ingen modell.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api as api

GRENSE = "graense123"
CT = "multipart/form-data; boundary=" + GRENSE


def _kropp(*deler: bytes) -> bytes:
    """Setter sammen en multipart-kropp av ferdige del-blokker."""
    ut = []
    for d in deler:
        ut.append(b"--" + GRENSE.encode() + b"\r\n" + d)
    ut.append(b"--" + GRENSE.encode() + b"--\r\n")
    return b"\r\n".join(ut)


def _del(disposisjon: bytes, innhold: bytes) -> bytes:
    return b"Content-Disposition: " + disposisjon + b"\r\n\r\n" + innhold


FIL_SITERT = b'form-data; name="fil"; filename="Taxi fra.pdf"'
FIL_USITERT = b'form-data; name=fil; filename="Taxi fra.pdf"'
PDF = b"%PDF-1.4 lat som"


@pytest.mark.parametrize("fil_cd,tekst_cd", [
    # Slik curl/Python/nettlesere sender — siterte navn
    (FIL_SITERT, b'form-data; name="sporsmal"'),
    # Slik .NET/UiPath sender — USITERT token. Dette var regresjonen.
    (FIL_USITERT, b"form-data; name=sporsmal"),
    # Blandet: .NET siterer filnavnet (mellomrom) men ikke feltnavnet
    (FIL_SITERT, b"form-data; name=sporsmal"),
    # Ekstra mellomrom rundt likhetstegnet
    (FIL_SITERT, b"form-data; name = sporsmal"),
])
def test_tekstfelt_leses_uansett_sitering(fil_cd, tekst_cd):
    kropp = _kropp(_del(fil_cd, PDF),
                   _del(tekst_cd, "Hva er totalbeløpet?".encode("utf-8")))
    filnavn, filbytes, tekstfelter = api._parse_multipart(kropp, CT)
    assert filnavn == "Taxi fra.pdf"
    assert filbytes == PDF
    assert tekstfelter == {"sporsmal": "Hva er totalbeløpet?"}


def test_flere_tekstfelter_usitert():
    """Hele UiPath-oppsettet: fil + de tre tekstfeltene som stille forsvant."""
    kropp = _kropp(
        _del(FIL_USITERT, PDF),
        _del(b"form-data; name=sporsmal", b"Hva er totalen?"),
        _del(b"form-data; name=skjema_motor", b"auto"),
        _del(b"form-data; name=skjema_mal", b'{"kunde":"{navn}"}'),
    )
    _, _, tekstfelter = api._parse_multipart(kropp, CT)
    assert tekstfelter == {
        "sporsmal": "Hva er totalen?",
        "skjema_motor": "auto",
        "skjema_mal": '{"kunde":"{navn}"}',
    }


def test_navn_forveksles_ikke_med_filename():
    """«name» må ikke plukkes ut av «filename=» — filparten skal fortsatt
    bli en FIL, ikke et tekstfelt som heter «Taxi fra.pdf»."""
    kropp = _kropp(_del(b"form-data; name=fil; filename=taxi.pdf", PDF))
    filnavn, filbytes, tekstfelter = api._parse_multipart(kropp, CT)
    assert (filnavn, filbytes) == ("taxi.pdf", PDF)
    assert tekstfelter == {}


def test_usitert_filnavn():
    """Filnavn uten mellomrom siteres ikke nødvendigvis."""
    filnavn, filbytes, _ = api._parse_multipart(
        _kropp(_del(b"form-data; name=fil; filename=kvittering.pdf", PDF)), CT)
    assert (filnavn, filbytes) == ("kvittering.pdf", PDF)


def test_tomt_filnavn_faller_tilbake():
    """Bevart oppførsel: filparten uten brukbart filnavn får standardnavn."""
    filnavn, filbytes, _ = api._parse_multipart(
        _kropp(_del(b'form-data; name="fil"; filename=""', PDF)), CT)
    assert (filnavn, filbytes) == ("opplastet.pdf", PDF)


@pytest.mark.parametrize("disposisjon,forventet", [
    (b'form-data; name="fil"; filename="a b.pdf"', "a b.pdf"),
    (b"form-data; filename=a.pdf; name=fil", "a.pdf"),
])
def test_cd_parameter_henter_filnavn(disposisjon, forventet):
    assert api._cd_parameter(b"Content-Disposition: " + disposisjon,
                             "filename") == forventet


def test_cd_parameter_mangler_gir_none():
    assert api._cd_parameter(b'Content-Disposition: form-data; name=fil',
                             "filename") is None


# ------------------------------------------------------------------ #
#  Samme feilmodus, andre klientvarianter                             #
#  Alle faller stille ut og gir 200 «som om feltet aldri ble sendt».  #
# ------------------------------------------------------------------ #

def test_boundary_med_flere_parametre():
    """«boundary=X; charset=utf-8» — naiv split tok med resten av
    strengen som del av boundaryen, og HELE kroppen ble usynlig."""
    kropp = _kropp(_del(FIL_USITERT, PDF),
                   _del(b"form-data; name=sporsmal", b"Hva er totalen?"))
    ct = "multipart/form-data; boundary=" + GRENSE + "; charset=utf-8"
    filnavn, _, tekstfelter = api._parse_multipart(kropp, ct)
    assert filnavn == "Taxi fra.pdf"
    assert tekstfelter == {"sporsmal": "Hva er totalen?"}


def test_sitert_boundary():
    kropp = _kropp(_del(b"form-data; name=sporsmal", b"hei"))
    ct = 'multipart/form-data; boundary="' + GRENSE + '"'
    assert api._parse_multipart(kropp, ct)[2] == {"sporsmal": "hei"}


def test_uten_boundary_gir_tomt():
    assert api._parse_multipart(b"noe", "multipart/form-data") == \
        (None, None, {})


def test_bare_lf_som_linjeskift():
    """Klienter som sender LF i stedet for CRLF: krever vi CRLF, hoppes
    HVER del over og kroppen ser tom ut."""
    kropp = (b"--" + GRENSE.encode() + b"\n"
             b"Content-Disposition: form-data; name=fil; filename=a.pdf\n\n"
             + PDF + b"\n"
             b"--" + GRENSE.encode() + b"\n"
             b"Content-Disposition: form-data; name=sporsmal\n\n"
             b"Hva er totalen?\n"
             b"--" + GRENSE.encode() + b"--\n")
    filnavn, filbytes, tekstfelter = api._parse_multipart(kropp, CT)
    assert (filnavn, filbytes) == ("a.pdf", PDF)
    assert tekstfelter == {"sporsmal": "Hva er totalen?"}


@pytest.mark.parametrize("disposisjon,forventet", [
    # .NET bruker RFC 5987-formen så snart navnet har æøå — altså for
    # ethvert norsk filnavn. Uten støtte ble filparten tolket som TEKST.
    (b"form-data; name=fil; filename*=UTF-8''taxi%20fr%C3%A5.pdf",
     "taxi frå.pdf"),
    # Begge former sendt samtidig (vanlig): den utvidede skal vinne,
    # for det er den som bærer tegnene riktig.
    (b'form-data; name=fil; filename="taxi fra.pdf";'
     b" filename*=UTF-8''taxi%20fr%C3%A5.pdf", "taxi frå.pdf"),
])
def test_filnavn_rfc5987(disposisjon, forventet):
    filnavn, filbytes, tekstfelter = api._parse_multipart(
        _kropp(_del(disposisjon, PDF)), CT)
    assert (filnavn, filbytes) == (forventet, PDF)
    assert tekstfelter == {}, "filparten må ikke bli et tekstfelt"


def test_tekstfelt_med_eget_tegnsett():
    """Del som oppgir latin-1: dekodes vi alltid som UTF-8, blir æøå krøll."""
    kropp = _kropp(_del(
        b"form-data; name=sporsmal\r\nContent-Type: text/plain; charset=iso-8859-1",
        "Hva er totalbeløpet?".encode("iso-8859-1")))
    assert api._parse_multipart(kropp, CT)[2] == \
        {"sporsmal": "Hva er totalbeløpet?"}


def test_utf8_er_standard_uten_charset():
    """Uten charset-angivelse (det UiPath faktisk sender) skal UTF-8 gjelde."""
    kropp = _kropp(_del(b"form-data; name=sporsmal",
                        "Hva er totalbeløpet?".encode("utf-8")))
    assert api._parse_multipart(kropp, CT)[2] == \
        {"sporsmal": "Hva er totalbeløpet?"}

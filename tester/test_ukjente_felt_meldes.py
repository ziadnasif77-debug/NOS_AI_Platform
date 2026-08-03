"""
Et ukjent feltnavn skal ALLTID meldes — på alle veier inn i API-et.

Funnet under en systematisk gjennomgang av endepunktene: koden regnet ut
advarselen om ukjente felt og kastet den (`_, omvendte = ...`) på både
/fyll_skjema og operasjoner-veien. Bare /dokument meldte fra.

Konkret utslag: /fyll_skjema kaller motorfeltet «skjema_motor». Sender en
klient «motor=felter» — et nærliggende feilnavn — ble feltet ignorert i
stillhet, kallet falt tilbake til modell-motoren, og klienten betalte
GPU-tid for nøyaktig det den hadde bedt om å slippe. Svaret var 200 uten
et eneste signal.

Samme feilmodus som R63: klienten tror den ba om noe, og får 200 som om
den fikk det.
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

import dokument_api as api


# ---------- selve hjelperen ----------

def test_ingen_ukjente_gir_ingen_advarsel():
    assert api._ukjent_felt_advarsel([], {"skjema", "skjema_motor"}) == []


def test_ukjent_felt_navngis_sammen_med_de_kjente():
    linjer = api._ukjent_felt_advarsel(["motor"], {"skjema", "skjema_motor"})
    assert len(linjer) == 1
    assert "motor" in linjer[0]
    # klienten skal kunne se HVA den skulle ha sendt
    assert "skjema_motor" in linjer[0]


def test_flere_ukjente_i_samme_advarsel():
    linjer = api._ukjent_felt_advarsel(["motor", "mal"], {"skjema"})
    assert "motor" in linjer[0] and "mal" in linjer[0]


# ---------- feltnavn-inndelingen ----------

@pytest.mark.parametrize("feltnavn,kjente,forventet_mild", [
    ({"motor": "felter"}, {"skjema", "skjema_motor"}, ["motor"]),
    ({"skjema_motor": "felter"}, {"skjema", "skjema_motor"}, []),
    ({"skjema": "{}", "motor": "x"}, {"skjema"}, ["motor"]),
])
def test_sjekk_feltnavn_skiller_ukjent_fra_kjent(feltnavn, kjente,
                                                 forventet_mild):
    milde, omvendte = api._sjekk_feltnavn(feltnavn, kjente)
    assert milde == forventet_mild
    assert omvendte == []


def test_verdi_som_feltnavn_er_omvendt_ikke_bare_ukjent():
    """«auto» som NAVN betyr at klienten snudde argumentene — det er en
    hard feil (400), ikke en mild advarsel."""
    milde, omvendte = api._sjekk_feltnavn({"auto": "skjema_motor"},
                                          {"skjema_motor"})
    assert omvendte == ["auto"]
    assert milde == []


# ---------- feilmeldingen må lære bort RIKTIG UiPath-rekkefølge ----------

def test_feilmelding_laerer_bort_verdi_foerst():
    """Meldingen påsto tidligere at NAVNET kommer først i
    TextFormDataPart. Det er feil, og den sendte brukeren rett i grøfta:
    legger man JSON-malen i andre argument, kaster UiPath
    «The format of value '{…}' is invalid» før requesten sendes."""
    feil = api._omvendt_felt_feil(["auto"], {"skjema_motor"})
    tekst = feil["feil"]
    assert "TextFormDataPart(verdi, navn)" in tekst
    assert "TextFormDataPart(navn, verdi)" not in tekst
    # eksempelet må vise verdi først, navn sist
    assert 'New TextFormDataPart("auto", "skjema_motor")' in tekst


def test_feilmelding_lister_kjente_felt():
    feil = api._omvendt_felt_feil(["ja"], {"skjema", "skjema_motor"})
    assert feil["kjente_felt"] == ["skjema", "skjema_motor"]
    assert feil["ok"] is False


# ---------- vakt mot at advarselen kastes igjen ----------

@pytest.mark.parametrize("metode", [
    "_do_post_intern",          # ruteren — her ligger /fyll_skjema-vakten
    "_dokument_operasjoner",
    "_dokument_samlet",
])
def test_advarselen_kastes_ikke(metode):
    """Regresjonen var bokstavelig talt «_, omvendte = ...» — resultatet
    ble regnet ut og forkastet. Vakt mot at det snik seg inn igjen."""
    import inspect
    kilde = inspect.getsource(getattr(api.Handler, metode))
    assert "_sjekk_feltnavn" in kilde, f"{metode} sjekker ikke feltnavn"
    assert "_, omvendte = _sjekk_feltnavn" not in kilde, \
        f"{metode} kaster advarselen om ukjente felt igjen"
    assert "_ukjent_felt_advarsel" in kilde, \
        f"{metode} melder ikke fra om ukjente felt"


def test_fyll_skjema_svarer_alltid_med_advarsler_noekkelen():
    """Alle tre motorene skal ha samme nøkkel, ellers forsvinner
    advarselen når klienten bytter motor."""
    import inspect
    kilde = inspect.getsource(api.Handler._fyll_skjema_flyt)
    assert '"advarsler": list(ekstra_advarsler or [])' in kilde

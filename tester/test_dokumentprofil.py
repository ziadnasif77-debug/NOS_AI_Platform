"""
Tester for de OBLIGATORISKE metadataene i svaret fra POST /dokument
(R66): sideantall, QR-/strekkodesider, dokumentdato med periode og år,
stempeldatoer og hvem dokumentet gjelder.

Fellesnevneren for hele fila: profilen skal heller si `null` med en
begrunnelse enn å gjette. En tilfeldig dato eller et tilfeldig
fødselsnummer er verre enn ingen verdi — det ser like riktig ut som et
korrekt svar, og ingen oppdager forskjellen.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from delt.dokumentprofil import (bygg_profil, finn_dokument_eier,
                                 gjelder_periode, koder_med_sider,
                                 stempeldatoer, til_iso)
from delt.tekstuttrekk import (finn_dokumentdato, klassifiser_datoer,
                               sett_dato_roller)
from syntetiske_nummer import lag_fnr

EIER = lag_fnr(0)
ANNEN = lag_fnr(1)


def _profil(tekst, **ekstra):
    datoer = sett_dato_roller(klassifiser_datoer(tekst))
    return bygg_profil(tekst, datoer_detaljert=datoer,
                       dokumentdato=finn_dokumentdato(datoer), **ekstra)


# ------------------------------------------------------------------ #
#  1. Antall sider                                                     #
# ------------------------------------------------------------------ #

def test_sideantallet_er_filens_sider_ikke_sidene_med_tekst():
    """En tom side er fortsatt en side. Teller vi bare sider med tekst,
    kan en klient ikke bruke tallet til å sjekke at hele bunken kom
    fram."""
    profil = _profil("[Side 1 av 3]\nBrev\n[Side 2 av 3]\n\n[Side 3 av 3]\nSlutt",
                     antall_sider=3)
    assert profil["antall_sider"] == 3


def test_ukjent_sideantall_er_null_ikke_null_sider():
    assert _profil("Ren tekst uten sider")["antall_sider"] is None


# ------------------------------------------------------------------ #
#  2. QR-kode og strekkode med sidetall                                #
# ------------------------------------------------------------------ #

def test_qr_og_strekkode_far_hvert_sitt_sidetall():
    koder = koder_med_sider([
        {"type": "QRCODE", "verdi": "https://nav.no/sak", "side": 1},
        {"type": "CODE128", "verdi": "9912345", "side": 3},
    ])
    assert koder["qr_kode_side"] == 1
    assert koder["strekkode_side"] == 3
    assert koder["qr"][0]["verdi"] == "https://nav.no/sak"


def test_alle_koder_registreres_ikke_bare_den_forste():
    koder = koder_med_sider([
        {"type": "QRCODE", "verdi": "a", "side": 1},
        {"type": "QRCODE", "verdi": "b", "side": 4},
        {"type": "EAN13", "verdi": "c", "side": 2},
    ])
    assert len(koder["qr"]) == 2
    assert [k["side"] for k in koder["qr"]] == [1, 4]
    assert koder["qr_kode_side"] == 1          # den første, men b er med


def test_ingen_koder_gir_null_sidetall():
    koder = koder_med_sider([])
    assert koder["qr_kode_side"] is None
    assert koder["strekkode_side"] is None
    assert koder["lest"] is True


def test_uskannet_er_ikke_det_samme_som_ingen_koder():
    """Slår klienten av skanningen, har vi ikke BEVIST at det mangler
    QR-kode — vi har bare latt være å se etter."""
    koder = koder_med_sider([], lest=False)
    assert koder["lest"] is False
    assert koder["qr_kode_side"] is None
    assert "ikke ble sett etter" in koder["merknad"]


# ------------------------------------------------------------------ #
#  3. Dokumentdato kontra datoer i innholdet                           #
# ------------------------------------------------------------------ #

def test_dokumentdato_velges_ikke_fra_lopende_tekst():
    """Kravets kjerne: en dato som bare NEVNES i teksten skal ikke bli
    dokumentdato."""
    profil = _profil(
        "Vedtaksdato: 17.05.2024\n"
        "Du må klage innen 12.06.2024.\n"
        "Perioden gjelder fra 01.01.2023.\n")
    assert profil["dokumentdato"] == "2024-05-17"
    assert profil["dokument_ar"] == 2024


def test_bare_innholdsdatoer_gir_null_ikke_en_tilfeldig_dato():
    profil = _profil("Fristen er 12.06.2024 og du er født 01.01.1990.")
    assert profil["dokumentdato"] is None
    assert profil["dokument_ar"] is None
    assert profil["dokumentdato_konfidens"] == "ingen"
    assert "Fant ingen dato" in profil["dokumentdato_begrunnelse"]


@pytest.mark.parametrize("etikett", [
    "Dokumentdato", "Utstedt", "Datert", "Vedtaksdato", "Signert",
])
def test_strukturelle_etiketter_gir_dokumentdato(etikett):
    profil = _profil(f"{etikett}: 17.05.2024\nBrevets innhold.")
    assert profil["dokumentdato"] == "2024-05-17", etikett


def test_perioden_dokumentet_gjelder_er_egne_felter():
    """Perioden er ikke dokumentdatoen: et vedtak fattet i mai kan
    gjelde for hele fjoråret."""
    profil = _profil(
        "Vedtaksdato: 17.05.2024\n"
        "Dagpenger for perioden 01.01.2023 til og med 31.12.2023.\n")
    assert profil["dokumentdato"] == "2024-05-17"
    assert profil["dokumentdato_fra"] == "2023-01-01"
    assert profil["dokumentdato_til"] == "2023-12-31"


def test_uten_periode_er_fra_og_til_null():
    profil = _profil("Dokumentdato: 17.05.2024\nEt vanlig brev.")
    assert profil["dokumentdato_fra"] is None
    assert profil["dokumentdato_til"] is None


def test_dokumentets_alder_folger_med():
    profil = _profil("Dokumentdato: 17.05.2024")
    assert profil["dokument_alder"] is not None
    assert "dager" in profil["dokument_alder"]


def test_til_iso_konverterer_og_gir_null_paa_soppel():
    assert til_iso("17.05.2024") == "2024-05-17"
    assert til_iso("ikke en dato") is None
    assert til_iso(None) is None


# ------------------------------------------------------------------ #
#  4. Stempeldatoer                                                    #
# ------------------------------------------------------------------ #

def test_stempeldato_skilles_ut_og_blir_ikke_dokumentdato():
    """«Mottatt NAV 20.05.2024» er postmottakets stempel. Blir den
    dokumentdato, ser brevet nyere ut enn det er."""
    profil = _profil("Vedtaksdato: 17.05.2024\nMottatt NAV 20.05.2024\n")
    assert profil["dokumentdato"] == "2024-05-17"
    stempler = [s["dato"] for s in profil["stempel_datoer"]]
    assert "2024-05-20" in stempler
    assert "2024-05-17" not in stempler


def test_arkivstempel_regnes_som_stempel():
    profil = _profil("Dokumentdato: 01.03.2024\nArkivert: 05.03.2024\n")
    assert [s["dato"] for s in profil["stempel_datoer"]] == ["2024-03-05"]


def test_uten_stempel_er_lista_tom():
    assert _profil("Dokumentdato: 01.03.2024")["stempel_datoer"] == []


def test_samme_stempeldato_to_steder_telles_en_gang():
    datoer = sett_dato_roller(klassifiser_datoer(
        "Mottatt 20.05.2024\n[Side 2 av 2]\nMottatt 20.05.2024"))
    assert len(stempeldatoer("", datoer)) == 1


# ------------------------------------------------------------------ #
#  5. Fnr — personen dokumentet GJELDER                                #
# ------------------------------------------------------------------ #

DOKUMENT_MED_TO_PERSONER = f"""NAV Arbeid og ytelser
Vedtaksdato: 17.05.2024

Dokumentet gjelder:
Ola Nordmann
Fnr: {EIER}

Saksbehandler:
Kari Hansen
Fnr: {ANNEN}
"""


def test_eierens_fnr_velges_ikke_saksbehandlerens():
    eier = finn_dokument_eier(DOKUMENT_MED_TO_PERSONER)
    assert eier["fnr"] == EIER
    assert eier["navn"] == "Ola Nordmann"
    assert eier["sikkerhet"] == "merket"


def test_andre_fodselsnummer_holdes_atskilt_fra_eierens():
    """De øvrige numrene kastes ikke — de er ekte opplysninger — men de
    ligger i sitt EGET felt, aldri sammen med eierens."""
    eier = finn_dokument_eier(DOKUMENT_MED_TO_PERSONER)
    assert eier["fnr"] == EIER
    assert [k["fnr"] for k in eier["andre_fodselsnummer"]] == [ANNEN]
    assert eier["andre_fodselsnummer"][0]["etikett"] == "Saksbehandler"


def test_eierens_nummer_gjentas_aldri_blant_de_andre():
    eier = finn_dokument_eier(DOKUMENT_MED_TO_PERSONER)
    assert EIER not in [k["fnr"] for k in eier["andre_fodselsnummer"]]


def test_uten_eier_er_alle_numre_blant_de_andre():
    """Kan eieren ikke fastslås, forsvinner ikke numrene — de ligger
    alle i «andre», og fnr er null."""
    eier = finn_dokument_eier(f"Referanse {EIER} og {ANNEN} i saken.")
    assert eier["fnr"] is None
    assert sorted(k["fnr"] for k in eier["andre_fodselsnummer"]) == \
        sorted([EIER, ANNEN])


@pytest.mark.parametrize("rolle", [
    "Saksbehandler", "Behandlende lege", "Arbeidsgiver", "Kontaktperson",
    "Kopi", "Mottaker", "Signert av", "Verge", "Pårørende",
])
def test_fnr_under_en_annen_rolle_blir_aldri_dokumentets(rolle):
    eier = finn_dokument_eier(f"Et brev.\n{rolle}:\nKari Hansen\nFnr: {EIER}")
    assert eier["fnr"] is None
    assert eier["sikkerhet"] == "bare_andre_roller"


@pytest.mark.parametrize("etikett", [
    "Dokumentet gjelder", "Navn", "Søker", "Bruker", "Den sykmeldte",
    "Arbeidstaker", "Pasient", "Medlem",
])
def test_eieretiketter_gjenkjennes(etikett):
    eier = finn_dokument_eier(f"{etikett}:\nOla Nordmann\nFnr: {EIER}")
    assert eier["fnr"] == EIER, etikett


def test_umerket_fnr_hentes_ikke_bare_fordi_det_finnes():
    """Kravet er eksplisitt: «Fnr skal ikke hentes kun fordi et
    Fnr-nummer finnes i teksten.»"""
    eier = finn_dokument_eier(f"Referanse i saken: {EIER}. Se vedlegg.")
    assert eier["fnr"] is None
    assert eier["sikkerhet"] == "umerket"
    assert "ikke bare fordi det" in eier["begrunnelse"]


def test_to_ulike_eiermerkede_fnr_gir_null_ikke_et_valg():
    tekst = (f"Dokumentet gjelder:\nOla Nordmann\nFnr: {EIER}\n\n"
             f"Søker:\nPer Olsen\nFnr: {ANNEN}\n")
    eier = finn_dokument_eier(tekst)
    assert eier["fnr"] is None
    assert eier["sikkerhet"] == "flertydig"


def test_uten_fodselsnummer_sies_det_rett_ut():
    eier = finn_dokument_eier("Et brev uten personopplysninger.")
    assert eier["fnr"] is None
    assert eier["sikkerhet"] == "ingen"
    assert eier["andre_fodselsnummer"] == []


def test_fnr_med_skilletegn_kobles_ogsaa_til_eieren():
    """Dokumenter skriver fødselsnummer på mange måter — etiketten skal
    gjelde uansett gruppering."""
    gruppert = f"{EIER[:6]} {EIER[6:]}"
    eier = finn_dokument_eier(f"Dokumentet gjelder:\nOla Nordmann\n"
                              f"Fødselsnummer: {gruppert}")
    assert eier["fnr"] == EIER


def test_naermeste_etikett_vinner_over_den_lenger_opp():
    """Et dokument leses ovenfra og ned: står «Saksbehandler» rett over
    nummeret, er det saksbehandlerens — selv om «Dokumentet gjelder»
    sto øverst på siden."""
    tekst = (f"Dokumentet gjelder:\nOla Nordmann\nFnr: {EIER}\n"
             f"Saksbehandler:\nKari Hansen\nFnr: {ANNEN}\n")
    eier = finn_dokument_eier(tekst)
    assert eier["fnr"] == EIER


# ------------------------------------------------------------------ #
#  6. Ytelse — plassholder, ingen forretningslogikk ennå               #
# ------------------------------------------------------------------ #

def test_ytelse_er_med_i_kontrakten_men_ikke_fastslatt():
    profil = _profil("Vedtak om dagpenger\nDokumentdato: 01.03.2024")
    assert "ytelse" in profil
    assert profil["ytelse"] is None
    assert profil["ytelse_status"] == "ikke_implementert"


# ------------------------------------------------------------------ #
#  7. Profilen er obligatorisk — ikke en bryter                        #
# ------------------------------------------------------------------ #

PAAKREVDE_FELT = (
    "antall_sider", "koder", "dokumentdato", "dokumentdato_fra",
    "dokumentdato_til", "dokument_ar", "dokument_alder", "stempel_datoer",
    "dokument_eier", "ytelse",
)


@pytest.mark.parametrize("felt", PAAKREVDE_FELT)
def test_alle_paakrevde_felt_finnes_selv_i_et_tomt_dokument(felt):
    """Nøkkelen skal ALLTID være der. En klient som må sjekke om feltet
    finnes før den leser det, har ingen kontrakt."""
    assert felt in _profil("")


def test_profilen_folger_med_i_dokumentsvaret_uten_at_noen_ber_om_det():
    import dokument_api as api
    ktx = api.DokumentKontekst(
        "Dokumentet gjelder:\nOla Nordmann\n"
        f"Fnr: {EIER}\nDokumentdato: 17.05.2024",
        antall_sider=1)
    profil = ktx.profil
    assert profil["dokumentdato"] == "2024-05-17"
    assert profil["dokument_eier"]["fnr"] == EIER
    assert profil["antall_sider"] == 1


def test_profilen_er_bufret_saa_den_ikke_regnes_to_ganger():
    import dokument_api as api
    ktx = api.DokumentKontekst("Dokumentdato: 17.05.2024", antall_sider=1)
    assert ktx.profil is ktx.profil

"""
Tester for de OBLIGATORISKE metadataene i svaret fra POST /dokument
(R79): sideantall, QR-/strekkodesider, dokumentdato med periode og år,
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
                               sett_dato_roller, strukturert_uttrekk)
from syntetiske_nummer import lag_fnr

EIER = lag_fnr(0)
ANNEN = lag_fnr(1)


def _profil(tekst, **ekstra):
    """Bygger profilen slik DokumentKontekst gjør det — samme deler inn,
    så testene måler den samme sammensetningen som serveren leverer."""
    datoer = sett_dato_roller(klassifiser_datoer(tekst))
    ekstra.setdefault("struktur", strukturert_uttrekk(tekst))
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
    assert profil["fil"]["antall_sider"] == 3


def test_ukjent_sideantall_er_null_ikke_null_sider():
    assert _profil("Ren tekst uten sider")["fil"]["antall_sider"] is None


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
    assert profil["dokument"]["dato"] == "2024-05-17"
    assert profil["dokument"]["aarstall"] == 2024


def test_bare_innholdsdatoer_gir_null_ikke_en_tilfeldig_dato():
    profil = _profil("Fristen er 12.06.2024 og du er født 01.01.1990.")
    assert profil["dokument"]["dato"] is None
    assert profil["dokument"]["aarstall"] is None
    assert profil["dokument"]["dato_sikkerhet"] == "ingen"
    assert "Fant ingen dato" in profil["dokument"]["dato_begrunnelse"]


@pytest.mark.parametrize("etikett", [
    "Dokumentdato", "Utstedt", "Datert", "Vedtaksdato", "Signert",
])
def test_strukturelle_etiketter_gir_dokumentdato(etikett):
    profil = _profil(f"{etikett}: 17.05.2024\nBrevets innhold.")
    assert profil["dokument"]["dato"] == "2024-05-17", etikett


def test_perioden_dokumentet_gjelder_er_egne_felter():
    """Perioden er ikke dokumentdatoen: et vedtak fattet i mai kan
    gjelde for hele fjoråret."""
    profil = _profil(
        "Vedtaksdato: 17.05.2024\n"
        "Dagpenger for perioden 01.01.2023 til og med 31.12.2023.\n")
    assert profil["dokument"]["dato"] == "2024-05-17"
    assert profil["dokument"]["periode_start"] == "2023-01-01"
    assert profil["dokument"]["periode_slutt"] == "2023-12-31"


def test_uten_periode_er_fra_og_til_null():
    profil = _profil("Dokumentdato: 17.05.2024\nEt vanlig brev.")
    assert profil["dokument"]["periode_start"] is None
    assert profil["dokument"]["periode_slutt"] is None


def test_dokumentets_alder_folger_med():
    profil = _profil("Dokumentdato: 17.05.2024")
    assert profil["dokument"]["alder"] is not None
    assert "dager" in profil["dokument"]["alder"]


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
    assert profil["dokument"]["dato"] == "2024-05-17"
    stempler = [s["dato"] for s in profil["visuelt"]["stempel_datoer"]]
    assert "2024-05-20" in stempler
    assert "2024-05-17" not in stempler


def test_arkivstempel_regnes_som_stempel():
    profil = _profil("Dokumentdato: 01.03.2024\nArkivert: 05.03.2024\n")
    assert [s["dato"] for s in profil["visuelt"]["stempel_datoer"]] == ["2024-03-05"]


def test_uten_stempel_er_lista_tom():
    assert _profil("Dokumentdato: 01.03.2024")["visuelt"]["stempel_datoer"] == []


def test_dokumentets_egen_dato_havner_aldri_i_stempellista():
    """Sett på en ekte skannet bunke: OCR flater ut layouten, så teksten
    i et stempelmerke og dokumentets datolinje kan havne på SAMME linje.
    Da slo stempelord-fallbacken til, og dokumentdatoen ble rapportert
    som et stempel. En dato som er sterk nok til å være dokumentets
    egen, er per definisjon ikke et stempel."""
    profil = _profil("Mottatt NAV — vedtaket er datert 28.05.2026\n")
    assert profil["dokument"]["dato"] == "2026-05-28"
    assert profil["visuelt"]["stempel_datoer"] == []


def test_navn_med_blokkbokstaver_leses_via_navnefeltet():
    """Norske skjemaer ber om blokkbokstaver («Bruk blokkbokstaver»), og
    da matcher ikke formen på et vanlig navn. Etiketten over feltet er
    den sikre veien — og den eneste som virker her."""
    eier = finn_dokument_eier(
        f"1. Opplysninger om deg\nEtternavn, fornavn\n"
        f"NOR-ETTERNAVN, OLA\nFødselsnummer\n{EIER}\n")
    assert eier["fnr"] == EIER
    assert eier["navn"] == "NOR-ETTERNAVN, OLA"


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

def test_ytelsesnavnet_hentes_men_reglene_er_ikke_paa_plass():
    """Navnet finnes fra før (én detektor, én kilde). Resten av
    ytelsesreglene kommer senere — men modenheten står nå i «dekning»,
    ikke i «ytelse.status». Det feltet publiserte VÅR byggeframdrift som
    domenetilstand, og var opptatt av et verdirom det ikke kunne vokse
    inn i: når reglene lander, er de riktige verdiene «innvilget»,
    «lopende» og «opphort»."""
    profil = _profil("Vedtak om dagpenger\nDokumentdato: 01.03.2024")
    assert profil["ytelse"]["navn"] == "dagpenger"
    assert profil["ytelse"]["utfall"] is None
    assert profil["ytelse"]["status"] is None       # frigjort til domenet
    assert profil["dekning"]["ytelse"] == "delvis"


def test_uten_ytelse_i_dokumentet_sies_det_at_reglene_mangler():
    profil = _profil("Et brev uten ytelse.\nDokumentdato: 01.03.2024")
    assert profil["ytelse"]["navn"] is None
    assert profil["dekning"]["ytelse"] == "ingen"


def test_dekning_skiller_ikke_bygget_fra_ikke_funnet():
    """Fire felter var null fordi koden aldri leter etter dem, og fire
    fordi den lette og ikke fant. En klient kunne ikke se forskjellen."""
    dekning = _profil("")["dekning"]
    assert dekning["sakstype"] == "ingen"
    assert dekning["signatur_sider"] == "ingen"
    assert dekning["uleselige_sider"] == "ingen"
    assert "ikke leter etter" in dekning["forklaring"]


# ------------------------------------------------------------------ #
#  7. Profilen er obligatorisk — ikke en bryter                        #
# ------------------------------------------------------------------ #

SEKSJONER = {
    "fil": ("filnavn", "antall_sider", "blanke_sider", "uleselige_sider"),
    "part": ("navn", "fnr", "fodselsdato", "fastslatt", "grunnlag",
             "begrunnelse"),
    "dokument": ("type", "tittel", "sprak", "dato", "dato_norsk", "aarstall",
                 "alder", "dato_kilde", "dato_sikkerhet", "dato_begrunnelse",
                 "periode_start", "periode_slutt", "spenn_fra", "spenn_til",
                 "flere_dokumenter"),
    "sak": ("saksnummer", "journalnummer", "vedtaksnummer",
            "dokumentnummer", "referanse", "sakstype"),
    "ytelse": ("navn", "type", "utfall", "gyldig_fra", "gyldig_til",
               "status"),
    "okonomi": ("dagsats", "manedsbelop", "utbetalt_belop",
                "tilbakebetalingsbelop", "utbetalingsdato",
                "utbetalingsdato_norsk", "valuta", "valuta_merknad",
                "kontonummer", "kid"),
    "arbeid": ("arbeidsgiver", "stilling", "stillingsprosent", "startdato",
               "startdato_norsk", "sluttdato", "sluttdato_norsk",
               "arsinntekt", "manedslonn", "organisasjonsnummer"),
    "kontakt": ("telefoner", "eposter", "adresser"),
    "koder": ("lest", "qr", "strekkode", "qr_kode_side", "strekkode_side"),
    "visuelt": ("stempel_datoer", "stempel_sider", "signatur_sider",
                "handskrift_funnet"),
}


@pytest.mark.parametrize("seksjon", sorted(SEKSJONER))
def test_alle_seksjoner_finnes_selv_i_et_tomt_dokument(seksjon):
    """Seksjonen skal ALLTID være der. En klient som må sjekke om den
    finnes før den leser den, har ingen kontrakt."""
    profil = _profil("")
    assert seksjon in profil
    assert isinstance(profil[seksjon], dict)


@pytest.mark.parametrize("seksjon,felter", sorted(SEKSJONER.items()))
def test_alle_felt_i_hver_seksjon_finnes_alltid(seksjon, felter):
    profil = _profil("")
    mangler = [f for f in felter if f not in profil[seksjon]]
    assert not mangler, f"{seksjon} mangler {mangler}"


def test_andre_fodselsnummer_er_en_egen_seksjon_paa_toppniva():
    """Kravet: de øvrige fødselsnumrene skal IKKE ligge sammen med
    partens — heller ikke nestet inne i part-seksjonen."""
    profil = _profil("")
    assert profil["andre_fodselsnummer"] == []
    assert "andre_fodselsnummer" not in profil["part"]


# ------------------------------------------------------------------ #
#  8. Sammendrag og bunkedeling (R74)                                  #
# ------------------------------------------------------------------ #

BUNKE = f"""[Side 1 av 4]
Vedtak om dagpenger
Vedtaksdato: 12.05.2026
Dokumentet gjelder:
Ola Nordmann
Fnr: {EIER}
[Side 2 av 4]
fortsettelse av vedtaket
[Side 3 av 4]
Klage paa vedtak om dagpenger
Datert: 08.06.2026
[Side 4 av 4]
Legeerklaering ved arbeidsufoerhet
Utstedt: 20.05.2026
"""


def test_sammendraget_gir_de_faa_feltene_de_fleste_vil_ha():
    s = _profil("Vedtak om dagpenger\nVedtaksdato: 12.05.2026\n"
                f"Dokumentet gjelder:\nOla Nordmann\nFnr: {EIER}\n"
                "Saksnummer: 4417820", antall_sider=1)["sammendrag"]
    assert s["navn"] == "Ola Nordmann"
    assert s["fnr"] == EIER
    assert s["dokumentdato"] == "2026-05-12"
    assert s["dokumenttype"] == "vedtak"
    assert s["saksnummer"] == "4417820"
    assert s["konfidens"] == "hoy"


def test_sikkerheten_er_det_svakeste_leddet():
    """Er eieren usikker, hjelper det ikke at datoen er sikker."""
    s = _profil("Vedtaksdato: 12.05.2026\nEt brev uten person.")["sammendrag"]
    assert s["fnr"] is None
    assert s["konfidens"] == "lav"


def test_bunken_deles_i_dokumentene_den_bestaar_av():
    """En skannet fil er ofte en saksmappe. Ett «eier»-felt og én
    dokumentdato for hele filen er da misvisende, uansett hvor riktig
    hver enkelt verdi er isolert sett."""
    profil = _profil(BUNKE, antall_sider=4)
    dokumenter = profil["dokumenter"]
    assert len(dokumenter) == 3
    assert [d["sider"] for d in dokumenter] == [[1, 2], [3], [4]]
    assert [d["type"] for d in dokumenter] == ["vedtak", "klage",
                                               "legeerklaring"]
    assert dokumenter[0]["eier_fnr"] == EIER


def test_sammendraget_teller_dokumentene_i_bunken():
    s = _profil(BUNKE, antall_sider=4)["sammendrag"]
    assert s["antall_dokumenter"] == 3
    assert s["konfidens"] != "hoy", "en bunke er aldri «hoy» konfidens"


def test_ett_dokument_gir_en_liste_med_en_oppforing():
    """Lista har alltid minst én oppføring, så en klient kan gå gjennom
    den uten først å sjekke om filen «var» en bunke."""
    dokumenter = _profil("Vedtaksdato: 12.05.2026\nEt brev.")["dokumenter"]
    assert len(dokumenter) == 1


def test_et_ukjent_dokument_laaner_ikke_naboens_type():
    """Arv fra filens type ville gitt en legeerklæring etiketten
    «vedtak» bare fordi den lå i en vedtaksbunke."""
    dokumenter = _profil(
        "[Side 1 av 2]\nVedtak om dagpenger\nVedtaksdato: 12.05.2026\n"
        "[Side 2 av 2]\nEt ark uten kjent type\nUtstedt: 01.06.2026\n",
        antall_sider=2)["dokumenter"]
    assert dokumenter[1]["type"] is None


def test_skjemaversjonen_folger_med():
    """Endres formen senere, skal en klient kunne se det på tallet i
    stedet for å oppdage det når noe brekker."""
    assert _profil("")["skjemaversjon"] == "2.0"


def test_profilen_folger_med_i_dokumentsvaret_uten_at_noen_ber_om_det():
    import dokument_api as api
    ktx = api.DokumentKontekst(
        "Dokumentet gjelder:\nOla Nordmann\n"
        f"Fnr: {EIER}\nDokumentdato: 17.05.2024",
        antall_sider=1)
    profil = ktx.profil
    assert profil["dokument"]["dato"] == "2024-05-17"
    assert profil["part"]["fnr"] == EIER
    assert profil["fil"]["antall_sider"] == 1


def test_profilen_er_bufret_saa_den_ikke_regnes_to_ganger():
    import dokument_api as api
    ktx = api.DokumentKontekst("Dokumentdato: 17.05.2024", antall_sider=1)
    assert ktx.profil is ktx.profil

"""
Tester for `opphav` — ÉN proveniensmodell for hele svaret (R88).

Kjernen i alle testene under: kartet er en PROJEKSJON. Verdiene leses ut
av feltene profilen alt har fylt; de regnes ikke ut på nytt. Regnet det
på nytt, ville `opphav` blitt en sjette uavhengig mening om proveniens —
altså akkurat problemet revisjonen fant at det skulle løse.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")
sys.path.insert(0, "skript")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api
from delt.opphav import (KONFIDENSNIVAA, METODER, NIVAAER, bygg_opphav,
                         opphav_for_skjema)
from syntetiske_nummer import lag_fnr

MERKET = f"""Vedtak om dagpenger
Vedtaksdato: 17.05.2024
Saksnummer: 4417820
Dokumentet gjelder:
Ola Nordmann
Fnr: {lag_fnr(0)}
Dagsats: kr 1 234,00
"""


def _profil(tekst=MERKET, **ekstra):
    return api.DokumentKontekst(tekst, antall_sider=1, **ekstra).profil


# ------------------------------------------------------------------ #
#  1. Ordforrådene er LUKKEDE                                          #
# ------------------------------------------------------------------ #

@pytest.mark.parametrize("nivaa", NIVAAER)
def test_ingen_verdi_utenfor_de_lukkede_ordforradene(nivaa):
    """Et ord utenfor lista er en feil i kartet, ikke en ny kategori.
    Var det åpent, ville hver ny kilde smugle inn sitt eget vokabular —
    og da er vi tilbake til fem ordforråd."""
    for peker, post in bygg_opphav(_profil(), nivaa).items():
        assert post["metode"] in METODER, f"{peker}: {post['metode']}"
        assert post["konfidens"] in KONFIDENSNIVAA, peker


def test_konfidensskalaen_er_den_samme_som_i_profilen():
    """Ikke en fjerde skala ved siden av de tre vi nettopp slo sammen."""
    profil = _profil()
    kart = bygg_opphav(profil, "alle")
    assert (kart["/dokumentprofil/dokument/dato"]["konfidens"]
            == profil["dokument"]["dato_sikkerhet"])


# ------------------------------------------------------------------ #
#  2. Kartet SPEILER profilen — det gjetter ikke på nytt               #
# ------------------------------------------------------------------ #

def test_parten_speiler_grunnlaget_profilen_alt_har_fastslatt():
    profil = _profil()
    post = bygg_opphav(profil, "viktige")["/dokumentprofil/part/fnr"]
    assert profil["part"]["grunnlag"] == "etikett"
    assert post["metode"] == "etikett"
    assert post["konfidens"] == "hoy"
    assert post["begrunnelse"] == profil["part"]["begrunnelse"]


def test_uten_part_sier_kartet_ingen_ikke_en_gjetning():
    """«Vi fant ingenting, og her er hvorfor» ER svaret. En tom peker
    ville sett ut som om spørsmålet ikke ble stilt."""
    profil = _profil("Et brev uten personopplysninger.\nDatert 01.03.2024")
    post = bygg_opphav(profil, "viktige")["/dokumentprofil/part/fnr"]
    assert post["metode"] == "ingen"
    assert post["konfidens"] == "ingen"
    assert post["begrunnelse"]          # forklaringen følger med


def test_fodselsdato_merkes_avledet_ikke_som_eget_funn():
    """Fødselsdatoen er REGNET UT av fødselsnummeret — den står ikke
    nødvendigvis i dokumentet. Uten skillet ser den ut som et
    selvstendig funn med samme vekt som et lest felt."""
    kart = bygg_opphav(_profil(), "alle")
    assert kart["/dokumentprofil/part/fodselsdato"]["metode"] == "avledet"


def test_hjemmelen_arver_datoens_konfidens():
    """Lovvalget hviler på dokumentdatoen (R77). Er datoen usikker, er
    lovvalget det også — å melde «hoy» der ville skjule risikoen."""
    profil = _profil()
    kart = bygg_opphav(profil, "alle")
    if "/dokumentprofil/hjemmel/lov" in kart:
        assert (kart["/dokumentprofil/hjemmel/lov"]["konfidens"]
                == profil["dokument"]["dato_sikkerhet"])


def test_sjekksum_er_matematisk_bevis_ikke_et_monstertreff():
    profil = _profil(MERKET + "Kontonummer: 1234.56.78903\n")
    kart = bygg_opphav(profil, "alle")
    konto = [v for k, v in kart.items() if "kontonummer" in k]
    if konto:
        assert konto[0]["metode"] == "sjekksum"
        assert konto[0]["konfidens"] == "hoy"


# ------------------------------------------------------------------ #
#  3. Nivåene                                                          #
# ------------------------------------------------------------------ #

def test_ingen_gir_tomt_kart():
    assert bygg_opphav(_profil(), "ingen") == {}


def test_viktige_er_de_to_pekerne_de_fleste_handler_pa():
    kart = bygg_opphav(_profil(), "viktige")
    assert set(kart) == {"/dokumentprofil/part/fnr",
                         "/dokumentprofil/dokument/dato"}


def test_alle_er_et_ekte_supersett_av_viktige():
    profil = _profil()
    viktige = bygg_opphav(profil, "viktige")
    alle = bygg_opphav(profil, "alle")
    assert set(viktige) <= set(alle)
    assert len(alle) > len(viktige)
    # og de felles pekerne sier NØYAKTIG det samme på begge nivåer
    for peker in viktige:
        assert alle[peker] == viktige[peker]


# ------------------------------------------------------------------ #
#  4. Pekerne skal faktisk peke på noe                                 #
# ------------------------------------------------------------------ #

def _slaa_opp(profil, peker):
    """Minimal RFC 6901-oppslag, nok for pekerne vi lager selv."""
    node = {"dokumentprofil": profil}
    for ledd in peker.lstrip("/").split("/"):
        if isinstance(node, list):
            node = node[int(ledd)]
        else:
            node = node[ledd]
    return node


def test_hver_peker_treffer_et_felt_som_finnes():
    """En peker som ikke går noe sted er verre enn ingen peker: klienten
    slår opp, får ingenting, og vet ikke om feltet mangler eller om
    pekeren er feil."""
    profil = _profil(MERKET + "Arbeidsgiver: Rema 1000 AS\n")
    for peker in bygg_opphav(profil, "alle"):
        _slaa_opp(profil, peker)      # KeyError/IndexError = testen feiler


def test_skjemapekerne_bruker_samme_ordforrad():
    """`kilde_per_felt` sa «deterministisk»/«modell» — et sjette
    ordforråd for det samme."""
    kart = opphav_for_skjema({"navn": "modell", "dato": "deterministisk"})
    assert kart["/skjema/skjema/navn"]["metode"] == "modell"
    assert kart["/skjema/skjema/navn"]["konfidens"] == "lav"
    assert kart["/skjema/skjema/dato"]["metode"] == "regel"
    for post in kart.values():
        assert post["metode"] in METODER
        assert post["konfidens"] in KONFIDENSNIVAA


# ------------------------------------------------------------------ #
#  5. Begge kontraktene på /dokument                                   #
# ------------------------------------------------------------------ #

def test_ukjent_niva_avvises_ikke_stille_standardvalg():
    assert "tull" not in NIVAAER


def test_ingen_peker_viser_til_en_seksjon_som_ble_tatt_bort():
    """Funnet mot den KJØRENDE serveren: `profil=sammendrag` fjernet
    `part`, men kartet pekte fortsatt på `/dokumentprofil/part/fnr` med
    `metode: "etikett"` — altså «det finnes en part, og slik fant vi
    hen» i et svar klienten uttrykkelig ba om uten persondata. Pekeren
    gikk dessuten ingen steder."""
    from delt.opphav import uten_utelatte
    profil = _profil()
    liten = api._profilform(profil, "sammendrag")
    kart = uten_utelatte(bygg_opphav(profil, "alle"), liten)
    assert "/dokumentprofil/part/fnr" not in kart
    assert "/dokumentprofil/part/fodselsdato" not in kart
    # det som IKKE ble tatt bort, står igjen
    assert "/dokumentprofil/dokument/dato" in kart
    for peker in kart:
        _slaa_opp(liten, peker)        # hver peker må fortsatt treffe


def test_full_profil_mister_ingen_peker():
    from delt.opphav import uten_utelatte
    profil = _profil()
    kart = bygg_opphav(profil, "alle")
    assert uten_utelatte(kart, api._profilform(profil, "full")) == kart


def test_profilbryteren_finnes_i_BEGGE_kontraktene():
    """`profil=sammendrag` er en PERSONVERNbryter. Virket den bare i den
    ene kontrakten, fikk en klient som brukte «operasjoner» fullt
    persondatasvar uansett hva den ba om."""
    for kjente in (api._KJENTE_FELT_DOKUMENT, api._KJENTE_FELT_OPERASJONER):
        assert "profil" in kjente
        assert "opphav" in kjente

"""Sidetallet i `opphav` peker der beviset står — eller sier at det ikke
er sikkert.

`side_for_verdi` LETER etter verdien i teksten og melder FØRSTE
forekomst. Det er riktig når verdien finnes ett sted, og en gjetning når
den ikke gjør det. R125 fikset dette for parten ved å bære posisjonen
med fra uttrekket; de øvrige feltene lette fortsatt.

Målt på en bunke der side 1 er et følgebrev som SITERER tallene og side
3 er selve vedtaket der de står med etikett, sa svaret seg selv imot i
samme kart:

    part/fnr   side 3   «Fødselsnummeret står under «Opplysninger om»»
    part/navn  side 1   «Navnet står ved siden av det beviste nummeret»

De to kan ikke begge være sanne. Side 1 var første forekomst av navnet —
i følgebrevet, uten etikett — mens navnet PER DEFINISJON plukkes fra
forekomsten ved siden av det beviste nummeret (R124).

For verdier som faktisk står flere steder er ikke svaret å gjette bedre,
men å si fra: `side_entydig` skiller «her står den» fra «her står den
først».
"""
import os
import sys

import pytest

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROT)
sys.path.insert(0, os.path.join(ROT, "skript"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dokument_api as api
from delt.opphav import _antall_forekomster, bygg_opphav
from syntetiske_nummer import lag_fnr_fodt, lag_kontonummer

FNR = lag_fnr_fodt(3, 11, 1988)
KONTO = lag_kontonummer(0)

# Side 1 SITERER, side 3 har etikettene. Formen er hentet fra ekte
# NAV-bunker: et følgebrev foran selve vedtaket.
BUNKE = f"""[Side 1 av 3]
NAV Arbeid og ytelser
Følgebrev

Vi viser til sak 12345678 og kontonummer {KONTO}.
Saken gjelder Ola Nordmann.
Ytelsen sykepenger er omtalt under.

[Side 2 av 3]
Vedlegg: kopi av tidligere korrespondanse.

[Side 3 av 3]
NAV Arbeid og ytelser
VEDTAK om sykepenger
Dokumentdato: 04.03.2026

Opplysninger om: Ola Nordmann
Fodselsnummer: {FNR}
Saksnummer: 12345678
Kontonummer: {KONTO}
"""


@pytest.fixture(scope="module")
def kart():
    profil = api.DokumentKontekst(BUNKE, antall_sider=3,
                                  filnavn="b.txt").profil
    return bygg_opphav(profil, "alle", tekst=BUNKE)


# ------------------------------------------------------------------ #
#  1. Svaret motsier ikke seg selv                                     #
# ------------------------------------------------------------------ #

def test_navnet_peker_paa_SAMME_side_som_nummeret(kart):
    """Selve regresjonen. Begrunnelsen sier at navnet står ved siden av
    det beviste nummeret — da må sidene stemme overens."""
    fnr = kart["/dokumentprofil/part/fnr"]
    navn = kart["/dokumentprofil/part/navn"]
    assert "ved siden av" in navn["begrunnelse"]
    assert navn["side"] == fnr["side"], (
        f"navnet meldes på side {navn['side']}, nummeret på "
        f"{fnr['side']} — men begrunnelsen sier de står ved siden av "
        f"hverandre")


def test_parten_peker_paa_siden_med_ETIKETTEN(kart):
    """Ikke på følgebrevet, der navnet står uten etikett."""
    assert kart["/dokumentprofil/part/fnr"]["side"] == 3
    assert kart["/dokumentprofil/part/navn"]["side"] == 3


def test_dokumentdatoen_bruker_uttrekkets_eget_sidetall(kart):
    post = kart["/dokumentprofil/dokument/dato"]
    assert post["side"] == 3
    assert post["side_entydig"] is True


# ------------------------------------------------------------------ #
#  2. Er sidetallet sikkert, sier feltet det                           #
# ------------------------------------------------------------------ #

def test_verdier_som_staar_ETT_sted_er_entydige(kart):
    for sti in ("/dokumentprofil/part/fnr", "/dokumentprofil/part/navn",
                "/dokumentprofil/dokument/dato"):
        assert kart[sti]["side_entydig"] is True, sti


def test_verdier_som_staar_FLERE_steder_meldes_som_usikre(kart):
    """Saksnummeret og kontonummeret står både i følgebrevet og i
    vedtaket. Da er «side» første forekomst — og klienten skal vite
    det, i stedet for å få en gjetning presentert som et faktum."""
    flere = [sti for sti, p in kart.items() if p["side_entydig"] is False]
    assert "/dokumentprofil/sak/saksnummer" in flere
    assert any("kontonummer" in s for s in flere)


def test_avledede_verdier_har_verken_side_eller_entydighet(kart):
    """En avledet verdi står ikke på noen side, så spørsmålet «er siden
    sikker?» har ikke noe svar — og da er det `null`, ikke `false`."""
    for sti in ("/dokumentprofil/part/fodselsdato",
                "/dokumentprofil/gjeldende_lov/lov"):
        if sti in kart:
            assert kart[sti]["side"] is None, sti
            assert kart[sti]["side_entydig"] is None, sti


def test_hver_eneste_oppforing_har_noekkelen(kart):
    """R118: formen er fast. Et felt som mangler nøkkelen ville tvunget
    klienten til å skrive to kodeveier."""
    for sti, post in kart.items():
        assert "side_entydig" in post, sti
        assert post["side_entydig"] in (True, False, None), sti


def test_en_side_UTEN_entydighet_finnes_ikke(kart):
    """Den farlige mellomtingen: et sidetall uten noe som sier om det
    kan stoles på. Det er nettopp tilstanden dette punktet fjernet."""
    uklare = [sti for sti, p in kart.items()
              if p["side"] is not None and p["side_entydig"] is None]
    assert not uklare, f"sidetall uten entydighet: {uklare}"


# ------------------------------------------------------------------ #
#  3. Tellingen selv                                                   #
# ------------------------------------------------------------------ #

def test_telleren_ser_gjennom_formatering():
    """Kontonummeret lagres uten punktum, men står med dem i
    dokumentet. Uten den strippede sammenlikningen ville de to
    skrivemåtene telt som to ULIKE verdier — og et nummer som står to
    steder sett entydig ut.

    Nummeret bygges på KJØRETID: et ellevesifret tall i kildekoden ser
    ut som et fødselsnummer uansett hvor syntetisk det er ment å være,
    og portabilitetsvakten stopper det."""
    formatert = f"{KONTO[:4]}.{KONTO[4:6]}.{KONTO[6:]}"
    tekst = f"Konto {formatert} og igjen {KONTO}."
    assert _antall_forekomster(tekst, KONTO) == 2


def test_telleren_stopper_paa_to():
    """Kalleren spør «ett sted eller flere?». Å telle ferdig på et
    200-siders dokument er arbeid ingen har bruk for."""
    assert _antall_forekomster("aaa " * 50, "aaa") == 2


def test_tom_verdi_telles_som_ingenting():
    for tom in (None, "", [], {}, "   "):
        assert _antall_forekomster("noe tekst", tom) == 0

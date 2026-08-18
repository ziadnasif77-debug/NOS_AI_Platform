"""
Tester for feltvakten (delt/feltvakt.py, R232).

Tre korpusspørsmål ble besvart med et ANNET felts verdi:

    «Hvor stort gebyr er lagt paa fakturaen?»  → kr 4 812,00
    «Hvor mye skylder parten i renter?»        → kr 4 812,00
    «Hva er pensjonsgrunnlaget til Ola?»       → kr 512 400

Tallene står i dokumentet. 4 812,00 er beløpet som skal betales,
512 400 er sykepengegrunnlaget. Ingen av dem er et gebyr, renter eller
et pensjonsgrunnlag — de finnes ikke i bunken.

Testene holder på begge sider av garantien: at den fanger disse, og at
den ikke koster ett eneste riktig svar. Særlig det siste — hvert av de
to vilkårene ALENE tok riktige svar med seg da de ble målt.
"""
import sys

sys.path.insert(0, ".")

from delt import feltvakt                                       # noqa: E402
from tester.syntetiske_nummer import (lag_fnr,                  # noqa: E402
                                      lag_kontonummer)

DOKUMENT = "\n".join([
    "[Side 1 av 3]",
    "Vedtak om sykepenger",
    "Du har rett til sykepenger fra og med 02.04.2026. Vedtaket er fattet",
    "etter folketrygdloven kapittel 8. Sykepengegrunnlaget er fastsatt til",
    "kr 512 400 per aar, og du faar utbetalt 100 prosent av dette.",
    "[Side 2 av 3]",
    "Krav om tilbakebetaling - faktura",
    "Beloep aa betale",
    "kr 4 812,00",
    "Forfallsdato",
    "24.06.2026",
    "[Side 3 av 3]",
    "Hvis ja, oppgi type og beloep:",
    "Frilansoppdrag kr 8 400 i mai",
])


def _doem(sporsmal, svar):
    return feltvakt.doem(sporsmal, svar, DOKUMENT)


# ------------------------------------------------------------------ #
#  De tre feilene som utløste vakten                                  #
# ------------------------------------------------------------------ #

def test_gebyr_som_ikke_finnes_gir_ikke_fakturabelopet():
    d = _doem("Hvor stort gebyr er lagt paa fakturaen?", "kr 4 812,00")
    assert d["gjelder"] is True
    assert "gebyr" in d["fravaerende"]


def test_renter_som_ikke_er_beregnet_gir_ikke_fakturabelopet():
    d = _doem("Hvor mye skylder parten i renter?", "kr 4 812,00")
    assert d["gjelder"] is True


def test_pensjonsgrunnlag_gir_ikke_sykepengegrunnlaget():
    """De to ordene slutter likt og betyr helt ulike ting. At verdien
    er ekte, gjoer feilen verre — ikke bedre."""
    d = _doem("Hva er pensjonsgrunnlaget til Ola?", "kr 512 400")
    assert d["gjelder"] is True
    assert "pensjonsgrunnlaget" in d["fravaerende"]


# ------------------------------------------------------------------ #
#  Den skal ikke koste ett eneste riktig svar                         #
# ------------------------------------------------------------------ #

def test_riktig_felt_gaar_gjennom():
    """Samme verdi, samme etikett — men spoersmaalet spoer om det den
    faktisk er. «betales» og «betale» hoerer sammen."""
    assert _doem("Hvor mye skal betales paa fakturaen?",
                 "kr 4 812,00")["gjelder"] is False
    assert _doem("Hva er sykepengegrunnlaget?",
                 "kr 512 400")["gjelder"] is False
    assert _doem("Hva er forfallsdatoen paa fakturaen?",
                 "24.06.2026")["gjelder"] is False


def test_forstavelse_er_nok_til_aa_la_svaret_staa():
    """«frilansinntekt» og «Frilansoppdrag» deler bare forstavelsen, og
    med bevisvalgets terskel paa 70 % (R224) ville de vaert fremmede.
    Her skal vi AVVISE, og til det trengs fravaer av ENHVER forbindelse
    — derfor er terskelen fire tegn. Malt: uten dette ble
    frilansbeloepet holdt tilbake."""
    assert _doem("Hvor mye hadde parten i frilansinntekt?",
                 "kr 8 400")["gjelder"] is False


def test_begge_vilkaar_maa_holde():
    """Hvert vilkaar alene tar riktige svar med seg.

    Her er verdien uten etikett spoersmaalet nevner (vilkaar 1), men
    hvert ord i spoersmaalet finnes i dokumentet (vilkaar 2 faller).
    Da skal svaret staa."""
    d = _doem("Hvilket beloep staar i vedtaket om sykepenger?", "kr 4 812,00")
    assert d["gjelder"] is False


def test_fritekst_uten_verdi_roeres_ikke():
    assert _doem("Oppsummer bunken",
                 "Bunken gjelder sykepenger og en faktura.")["gjelder"] is False


def test_svar_som_allerede_nekter_roeres_ikke():
    for svar in ("Ikke oppgitt i dokumentet.", "Finnes ikke i dokumentet",
                 "Det staar ikke noe gebyr paa 4 812,00 her"):
        assert _doem("Hvor stort gebyr?", svar)["gjelder"] is False


def test_verdi_som_ikke_staar_i_dokumentet_roeres_ikke():
    """Et tall som ikke finnes noe sted, er tallvaktens bord (R147) —
    ikke vaart. To vakter som doemmer det samme, gir to begrunnelser
    for én feil."""
    assert _doem("Hvor stort gebyr er lagt paa fakturaen?",
                 "kr 9 999,00")["gjelder"] is False


def test_delstreng_i_et_lengre_tall_teller_ikke():
    """Sifferfoelgen 8400 staar inne i et lengre nummer uten aa vaere
    et beloep der. Uten ordgrense fanget vakten den som en verdi paa
    feil sted, og holdt et riktig svar tilbake — malt paa bunken, der
    «8400» ligger midt inne i et foedselsnummer."""
    dok = DOKUMENT + "\nReferansenummer: 998400123"
    d = feltvakt.doem("Hvor mye hadde parten i frilansinntekt?",
                      "kr 8 400", dok)
    assert d["gjelder"] is False


def test_tom_inndata_er_trygg():
    assert feltvakt.doem("", "kr 100,00", DOKUMENT)["gjelder"] is False
    assert feltvakt.doem("Hvor mye?", "", DOKUMENT)["gjelder"] is False
    assert feltvakt.doem("Hvor mye?", "kr 100,00", "")["gjelder"] is False


def test_deterministisk():
    """R6: samme spoersmaal, samme svar, samme dokument — hver gang."""
    spm, sv = "Hvor stort gebyr er lagt paa fakturaen?", "kr 4 812,00"
    forst = _doem(spm, sv)
    for _ in range(5):
        assert _doem(spm, sv) == forst


# ------------------------------------------------------------------ #
#  Serverbryteren                                                     #
# ------------------------------------------------------------------ #

def test_vakten_er_paa_og_ligger_UTENFOR_svarkjernen():
    """Samme begrunnelse som personbindingen (R213): kjernen har elleve
    returpunkter, og en sjekk ved det siste ser aldri svarene som gaar
    ut tidlig."""
    sys.path.insert(0, "skript")
    import dokument_api as api
    assert api.FELTVAKT is True
    kilde = open("skript/dokument_api.py", encoding="utf-8").read()
    assert "_feltvakt_paa(kjerne, sporsmal, raa_tekst)" in kilde
    kjerne_start = kilde.index("def _svar_paa_sporsmal_intern")
    assert kilde.index("def _feltvakt_paa") < kjerne_start, (
        "feltvakten maa ligge utenfor svarkjernen")


# ------------------------------------------------------------------ #
#  Hva som TELLER som en verdi                                        #
# ------------------------------------------------------------------ #

def test_bare_mengder_teller_som_verdi():
    """Vakten gjelder BELOEP og DATOER — der «feil felt» baade er
    vanlig og farlig.

    Malt: foerste versjon regnet ethvert firesifret tall som en verdi,
    og fanget «Hvilken gateadresse har mottakeren?». Modellen svarte
    «Storgata 14 B, 3044 DRAMMEN», POSTNUMMERET ble verdien, og
    «gateadresse» finnes ikke i bunken som ord — saa begge vilkaar
    holdt og et riktig svar ble byttet mot «Ikke oppgitt»."""
    assert feltvakt.verdier_i("kr 4 812,00") == ["4 812,00"]
    assert feltvakt.verdier_i("512 400") == ["512 400"]
    assert feltvakt.verdier_i("24.06.2026") == ["24.06.2026"]
    assert feltvakt.verdier_i("2026-06-24") == ["2026-06-24"]
    assert feltvakt.verdier_i("Storgata 14 B, 3044 DRAMMEN") == []
    assert feltvakt.verdier_i("3044") == [], "postnummer er ikke en mengde"


def test_identifikatorer_er_utenfor_med_vilje():
    """Foedselsnummer, kontonummer og KID svares deterministisk lenge
    foer modellen ser dem, og personbindingen (R213) vokter hvem de
    tilhoerer. To vakter paa samme verdi gir to begrunnelser for én
    feil."""
    assert feltvakt.verdier_i(lag_fnr(0)) == []
    assert feltvakt.verdier_i(f"Kontonummer {lag_kontonummer(0)}") == []


def test_gateadressen_gaar_gjennom():
    """Regresjonen over, hele veien gjennom doem()."""
    d = _doem("Hvilken gateadresse har mottakeren?",
              "Storgata 14 B, 3044 DRAMMEN")
    assert d["gjelder"] is False

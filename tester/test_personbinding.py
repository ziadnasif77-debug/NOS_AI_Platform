"""
Svarer vi om RIKTIG person? (R213)

Målt på den syntetiske bunken, der Marit står på side 9 og Ola på 1–6:

    «Hva er e-postadressen til Marit Testperson?»
        → ola.testperson@eksempel.no          Olas, fra side 4
    «Hvor mye blir neste utbetaling til Marit?»
        → 512 400                             Olas, fra side 1–2

Ingen av dem er hallusinasjon. Verdiene STÅR i dokumentet — de tilhører
bare en annen person. Og i det første tilfellet svarte ikke modellen i
det hele tatt: den deterministiske feltuttrekkeren fant bunkens ENESTE
e-post og leverte den (`modell_brukt: false`).

DERFOR KODE OG IKKE PROMPT (§4)
«Prompten styrer, koden garanterer.» En instruks om å passe på hvem det
spørres om, ville ikke nådd feltuttrekkeren i det hele tatt — den leser
ikke prompter.

DERFOR EN INNPAKNING OG IKKE EN SJEKK PÅ SLUTTEN
Første forsøk la sjekken ved det siste returpunktet i svarkjernen. Den
virket ikke: kjernen har elleve returpunkter, og det VERSTE tilfellet
gikk ut av et av de tidlige. Sjekken så aldri svaret den var laget for.
Nå ligger garantien i en innpakning rundt hele kjernen — samme mønster
som `_ocr_side_intern` og `_do_get_intern` ellers i fila.

MÅLT FØR DEN BLE SLÅTT PÅ
    før 109 av 133 · etter 111 av 133 · regresjoner: ingen
    determinisme: samme svar hver gang
"""
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "skript")

import pytest

from delt import personbinding as pb


SIDER = {
    1: "NAV Arbeid og ytelser\nOLA NORDMANN\nVedtak om sykepenger\n"
       "Grunnlag: kr 512 400 per aar\nSaksnummer: 4417820",
    2: "Utbetalingsplan for 512 400 kroner",
    3: "Faktura til Ola Nordmann\nBeloep kr 4 812,00",
    4: "Kontakt: ola.testperson@eksempel.no",
    5: "Generell informasjon om ytelser",
    9: "Legeerklaering for Marit Testperson\nFoedt 02.09.1991",
}


# ------------------------------------------------------------------ #
#  De to tilfellene som utløste hele greia                            #
# ------------------------------------------------------------------ #

def test_marits_epost_blir_ikke_olas():
    d = pb.doem("Hva er e-postadressen til Marit Testperson?",
                "ola.testperson@eksempel.no", SIDER)
    assert d["gjelder"] is True
    assert d["navn"] == "Marit Testperson"
    assert d["personsider"] == [9]
    assert d["funnet_paa"] == [4]


def test_marits_utbetaling_blir_ikke_olas_grunnlag():
    d = pb.doem("Hvor mye blir neste utbetaling til Marit?",
                "Beloep: 512 400 NOK", SIDER)
    assert d["gjelder"] is True


# ------------------------------------------------------------------ #
#  Den skal ikke koste ett eneste riktig svar                         #
# ------------------------------------------------------------------ #

def test_olas_eget_grunnlag_gaar_gjennom():
    """Verdien står på Olas side. Da er svaret riktig, og garantien
    skal ikke røre det."""
    d = pb.doem("Hva er grunnlaget til Ola Nordmann?", "kr 512 400", SIDER)
    assert d["gjelder"] is False


def test_versaler_i_adressefeltet_teller_som_samme_person():
    """Side 1 skriver «OLA NORDMANN» i blokkbokstaver, spørsmålet
    «Ola Nordmann». Med et versalfølsomt søk fant garantien ikke side 1,
    trodde den tilhørte en annen, og slo til på et helt riktig svar."""
    d = pb.doem("Hva er saksnummeret til Ola Nordmann?", "4417820", SIDER)
    assert d["gjelder"] is False
    assert 1 in d["personsider"], (
        "side 1 ble ikke gjenkjent som Olas — versalfølsomt navnesøk")


def test_sporsmal_uten_navn_roeres_ikke():
    d = pb.doem("Hva er saksnummeret?", "Saksnummer: 4417820", SIDER)
    assert d["gjelder"] is False and d["navn"] is None


def test_sammendrag_roeres_ikke():
    """Et sammendrag «tilhører» ingen enkeltside. En garanti som slo til
    på sammendrag ville tatt riktige svar med seg.

    Merk hva som HOLDER dette ute nå: setningen står ikke ordrett på
    noen side. Det er skillet garantien bruker — ikke om svaret er tall
    eller bokstaver, men om det lar seg spore til et sted."""
    d = pb.doem("Oppsummer dokumentet for Marit Testperson",
                "Dette er en legeerklaering.", SIDER)
    assert d["gjelder"] is False


# ------------------------------------------------------------------ #
#  Fri tekst er også en verdi — når den står ordrett et sted           #
# ------------------------------------------------------------------ #

def test_arbeidsgiver_fra_feil_persons_side_fanges():
    """Verdien er skrevet med bokstaver, ikke tall — og det spiller
    ingen rolle. «Nordbygg Entreprenoer AS» står på Olas side, ikke på
    Marits, og en saksbehandler som får den merket med Marits navn, tar
    like feil som med et fødselsnummer."""
    sider = {**SIDER, 6: "Inntektsmelding\nArbeidsgiver: Nordbygg "
                         "Entreprenoer AS\nAnsatt: Ola Nordmann"}
    d = pb.doem("Hvem er arbeidsgiveren til Marit Testperson?",
                "Nordbygg Entreprenoer AS", sider)
    assert d["gjelder"] is True
    assert d["funnet_paa"] == [6]


def test_samme_verdi_paa_personens_egen_side_gaar_gjennom():
    sider = {**SIDER, 9: "Legeerklaering for Marit Testperson\n"
                         "Arbeidsgiver: Nordbygg Entreprenoer AS"}
    d = pb.doem("Hvem er arbeidsgiveren til Marit Testperson?",
                "Nordbygg Entreprenoer AS", sider)
    assert d["gjelder"] is False


def test_haandskriftfelt_i_biter_blir_funnet():
    """Utfylte felter kommer tegn for tegn — både i tekstlaget til
    skjemaer og fra OCR. Uten luft-uavhengig sammenligning ville
    garantien vært blind for nettopp de feltene som oftest bommer."""
    sider = {**SIDER, 5: "Diagnose (ICPC-2):\nL\n8\n6 R\ny\ngg\nsyndrom"}
    d = pb.doem("Hvilken diagnose har Marit Testperson?",
                "L86 Ryggsyndrom", sider)
    assert d["funnet_paa"] == [5], "håndskriftfeltet ble ikke gjenkjent"
    assert d["gjelder"] is True


def test_for_kort_svar_doemmes_ikke():
    """«Ja» og «Nei» kan ikke spores til en side. Å dømme dem ville
    byttet ut riktige ja/nei-svar med «Ikke oppgitt»."""
    for svar in ("Ja", "Nei", "Ola"):
        d = pb.doem("Har Marit Testperson klaget?", svar, SIDER)
        assert d["gjelder"] is False, f"{svar!r} ble dømt"


def test_svar_som_allerede_sier_ikke_oppgitt_roeres_ikke():
    d = pb.doem("Hva er diagnosen til Marit Testperson?",
                "Ikke oppgitt i dokumentet", SIDER)
    assert d["gjelder"] is False


def test_verdi_som_ikke_staar_noe_sted_doemmes_ikke():
    """Modellen svarte «Ryggsmerter» der dokumentet sier «Ryggsyndrom».
    Da finnes verdien ingen steder, og garantien kan ikke vite hvilken
    side den kom fra. Den holder seg unna — å gjette her ville vært
    nøyaktig den feilen den er bygget for å hindre."""
    d = pb.doem("Hvilken diagnose har Marit Testperson?",
                "L86 Ryggsmerter med utstraaling", SIDER)
    assert d["gjelder"] is False
    assert d["funnet_paa"] == []


def test_ett_dokument_kan_ikke_forveksles():
    d = pb.doem("Hva er e-posten til Marit?",
                "ola.testperson@eksempel.no", {1: SIDER[1]})
    assert d["gjelder"] is False


def test_to_navn_i_sporsmalet_gir_ingen_dom():
    """Nevnes både Ola og Marit, vet vi ikke hvem svaret gjaldt — og en
    gjetning her ville vært nøyaktig den feilen vi prøver å hindre."""
    d = pb.doem("Har Ola Nordmann og Marit Testperson samme adresse?",
                "512 400", SIDER)
    assert d["gjelder"] is False


def test_navn_som_ikke_finnes_i_dokumentet_gir_ingen_dom():
    """Er personen ikke i dokumentet, er «ikke oppgitt» allerede riktig
    svar uten vår hjelp — og vi har ingen sider å sammenligne mot."""
    d = pb.doem("Hva er e-posten til Kari Hansen?",
                "ola.testperson@eksempel.no", SIDER)
    assert d["gjelder"] is False


# ------------------------------------------------------------------ #
#  Navnegjenkjenningen                                                #
# ------------------------------------------------------------------ #

def test_fullt_navn_er_ETT_navn():
    """«Marit Testperson» er én person. Uten sammenslåing av ord med
    stor forbokstav telte det som to, og garantien — som krever
    nøyaktig ett navn — ville aldri slått til på nettopp de
    spørsmålene den ble laget for."""
    assert pb.navn_i_sporsmal(
        "Hva er e-postadressen til Marit Testperson?", SIDER) \
        == ["Marit Testperson"]


def test_sporreord_er_ikke_navn():
    """«Hva», «Hvilken» og «Hvem» står med stor forbokstav først i
    setningen."""
    for spm in ("Hva er beloepet?", "Hvilken ytelse gjelder?",
                "Hvem er mottaker?"):
        assert pb.navn_i_sporsmal(spm, SIDER) == []


def test_fornavn_brukes_naar_fullt_navn_ikke_staar_i_dokumentet():
    d = pb.doem("Hvor mye faar Marit?", "512 400", SIDER)
    assert d["navn"] == "Marit"


# ------------------------------------------------------------------ #
#  Innpakningen — den viktigste strukturelle testen                   #
# ------------------------------------------------------------------ #

def test_garantien_ligger_UTENFOR_svarkjernen():
    """Kjernen har elleve returpunkter, og det verste tilfellet gikk ut
    av et av de tidlige — der svarte den deterministiske
    feltuttrekkeren, ikke modellen. En sjekk ved siste returpunkt så
    aldri det svaret."""
    import inspect
    import dokument_api as api
    ytre = inspect.getsource(api.svar_paa_sporsmal)
    assert "_svar_paa_sporsmal_intern" in ytre, (
        "garantien er ikke en innpakning rundt kjernen")
    assert "personbinding.doem" in ytre
    indre = inspect.getsource(api._svar_paa_sporsmal_intern)
    assert "personbinding.doem" not in indre, (
        "garantien ligger INNE i kjernen igjen — da dekker den bare de "
        "returpunktene noen husket på")


def test_svaret_sier_at_opplysningen_finnes_for_en_ANNEN():
    """«Ikke oppgitt» alene ville fått en saksbehandler til å tro at
    opplysningen ikke fantes i bunken i det hele tatt."""
    import dokument_api as api
    assert "en annen person" in api.PERSONBINDING_SVAR


def test_garantien_er_paa():
    """Slått på etter måling: 109 → 111 av 133, ingen regresjoner."""
    import dokument_api as api
    assert api.PERSONBINDING is True

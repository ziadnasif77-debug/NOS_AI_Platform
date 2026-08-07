"""
Tester for det deterministiske uttrekkslaget (delt/tekstuttrekk.py).
Ren logikk — ingen modeller, ingen tjenester.
"""
import sys
sys.path.insert(0, ".")

import pytest

from delt.tekstuttrekk import (
    er_gyldig_fnr, er_gyldig_kontonummer,
    finn_fodselsnummer, finn_kontonummer, finn_dato, finn_telefon,
    finn_epost, finn_postnummer_sted, finn_belop, finn_saksnummer,
    finn_kontornavn, finn_ytelse, finn_fylke, utvid_entiteter,
)


# ------------------------------------------------------------------ #
#  Hjelpere: bygg gyldige nummer med UAVHENGIG sjekksum-beregning      #
# ------------------------------------------------------------------ #

def _lag_gyldig_fnr() -> str:
    """Bygger et syntetisk fnr med korrekte kontrollsifre (beregnet
    her i testen, uavhengig av implementasjonen)."""
    for basis in range(10_000_000, 11_000_000):
        d = f"010190{str(basis)[-3:]}"  # 01.01.90 + individsifre
        s1 = sum(int(d[i]) * v for i, v in enumerate([3, 7, 6, 1, 8, 9, 4, 5, 2]))
        k1 = 11 - (s1 % 11)
        k1 = 0 if k1 == 11 else k1
        if k1 == 10:
            continue
        d10 = d + str(k1)
        s2 = sum(int(d10[i]) * v for i, v in enumerate([5, 4, 3, 2, 7, 6, 5, 4, 3, 2]))
        k2 = 11 - (s2 % 11)
        k2 = 0 if k2 == 11 else k2
        if k2 == 10:
            continue
        return d10 + str(k2)
    raise RuntimeError("fant ikke gyldig fnr")


def _lag_gyldig_konto() -> str:
    for basis in range(1_000_000_000, 1_000_001_000):
        d = str(basis)
        s = sum(int(d[i]) * v for i, v in enumerate([5, 4, 3, 2, 7, 6, 5, 4, 3, 2]))
        k = 11 - (s % 11)
        k = 0 if k == 11 else k
        if k == 10:
            continue
        konto = d + str(k)
        # Må ikke tilfeldigvis også være et gyldig fnr
        if not er_gyldig_fnr(konto):
            return konto
    raise RuntimeError("fant ikke gyldig konto")


GYLDIG_FNR = _lag_gyldig_fnr()
GYLDIG_KONTO = _lag_gyldig_konto()


# ------------------------------------------------------------------ #
#  Sjekksummer                                                         #
# ------------------------------------------------------------------ #

def test_gyldig_fnr_godkjennes():
    assert er_gyldig_fnr(GYLDIG_FNR)


def test_ugyldig_fnr_avvises():
    # Flipp siste siffer → sjekksummen ryker
    tullet = GYLDIG_FNR[:-1] + str((int(GYLDIG_FNR[-1]) + 1) % 10)
    assert not er_gyldig_fnr(tullet)
    assert not er_gyldig_fnr("12345678910")
    assert not er_gyldig_fnr("kort")
    assert not er_gyldig_fnr("")
    assert not er_gyldig_fnr(None)


def test_gyldig_kontonummer_godkjennes():
    assert er_gyldig_kontonummer(GYLDIG_KONTO)
    assert not er_gyldig_kontonummer("12345678910")


# ------------------------------------------------------------------ #
#  Uttrekk fra tekst                                                   #
# ------------------------------------------------------------------ #

def test_finn_fnr_i_tekst_med_og_uten_mellomrom():
    assert finn_fodselsnummer(f"Fødselsnummer: {GYLDIG_FNR} er registrert") == GYLDIG_FNR
    med_mellomrom = f"{GYLDIG_FNR[:6]} {GYLDIG_FNR[6:]}"
    assert finn_fodselsnummer(f"fnr {med_mellomrom} slutt") == GYLDIG_FNR


def test_finn_fnr_forkaster_ugyldige_kandidater():
    assert finn_fodselsnummer("nummeret 12345678910 er ikke et fnr") is None


def test_finn_kontonummer_med_punktum_format():
    formatert = f"{GYLDIG_KONTO[:4]}.{GYLDIG_KONTO[4:6]}.{GYLDIG_KONTO[6:]}"
    assert finn_kontonummer(f"Utbetales til {formatert}.") == GYLDIG_KONTO


def test_konto_og_fnr_blandes_ikke():
    tekst = f"fnr {GYLDIG_FNR} konto {GYLDIG_KONTO}"
    assert finn_fodselsnummer(tekst) == GYLDIG_FNR
    assert finn_kontonummer(tekst) == GYLDIG_KONTO


@pytest.mark.parametrize("tekst,forventet", [
    ("Vedtaksdato: 12.03.2021", "2021-03-12"),
    ("dato 3/1/2020 gjelder", "2020-01-03"),
    ("mottatt 2019-11-05 hos NAV", "2019-11-05"),
    ("Oslo, 12. januar 2020", "2020-01-12"),
    ("den 5 desember 1998", "1998-12-05"),
])
def test_finn_dato_alle_formater(tekst, forventet):
    assert finn_dato(tekst) == forventet


def test_finn_dato_forkaster_umulige():
    assert finn_dato("32.13.2020 og 00/00/1800") is None


def test_finn_telefon():
    assert finn_telefon("Ring oss på 22 33 44 55 i dag") == "22334455"
    assert finn_telefon("tlf: +47 91234567") == "91234567"
    assert finn_telefon("ingen nummer her") is None


def test_finn_epost():
    assert finn_epost("kontakt ola.nordmann@nav.no for info") == "ola.nordmann@nav.no"


def test_finn_postnummer_og_sted():
    postnr, sted = finn_postnummer_sted("Adresse: Storgata 1, 0181 Oslo")
    assert postnr == "0181"
    assert sted == "Oslo"


@pytest.mark.parametrize("tekst,forventet", [
    ("utbetalt kr 12 345,50 per måned", 12345.50),
    ("beløp: NOK 5000", 5000.0),
    ("sum 12.345,- totalt", 12345.0),
])
def test_finn_belop(tekst, forventet):
    assert finn_belop(tekst) == forventet


def test_finn_saksnummer():
    assert finn_saksnummer("Saksnr: 21/12345 behandles") == "21/12345"
    assert finn_saksnummer("skjema NAV 04-01.03 vedlagt") == "NAV 04-01.03"


def test_finn_kontornavn():
    assert finn_kontornavn("Behandlet av NAV Grünerløkka i dag") == "NAV Grünerløkka"
    assert finn_kontornavn("ingen etat nevnt") is None


def test_finn_ytelse_via_kanonisk_liste():
    assert finn_ytelse("Søknad om Dagpenger innvilges") == "dagpenger"
    assert finn_ytelse("dette handler om noe annet") is None


def test_finn_fylke():
    assert finn_fylke("bosatt i Trøndelag siden 2001") == "Trøndelag"


# ------------------------------------------------------------------ #
#  Sammenslåing med modell-entiteter                                   #
# ------------------------------------------------------------------ #

def test_utvid_beholder_modellens_navn():
    tekst = f"Vedtak for søker, fnr {GYLDIG_FNR}, dato 01.02.2020"
    resultat = utvid_entiteter(tekst, {"navn": "Kari Nordmann"})
    assert resultat["navn"] == "Kari Nordmann"          # modellen vinner for navn
    assert resultat["fodselsnummer"] == GYLDIG_FNR       # deterministisk fyller
    assert resultat["dato"] == "2020-02-01"


def test_utvid_overstyrer_ugyldig_modell_ytelse():
    # Gammel svakhet: enhver ORG ble gjettet som ytelse. Nå: kanonisk
    # liste vinner over modell-gjett som ikke er en ekte ytelse.
    tekst = "Vedtak om sykepenger for søkeren"
    resultat = utvid_entiteter(tekst, {"ytelse": "Statens Vegvesen"})
    assert resultat["ytelse"] == "sykepenger"


def test_utvid_bevarer_gyldig_modell_ytelse():
    tekst = "Dokument som også nevner dagpenger i teksten"
    resultat = utvid_entiteter(tekst, {"ytelse": "uforetrygd"})
    assert resultat["ytelse"] == "uforetrygd"   # allerede gyldig — ikke rør


def test_utvid_alle_nye_felter_samtidig():
    tekst = (
        f"NAV Sagene, saksnr 22/9876. Søker (fnr {GYLDIG_FNR}) "
        f"innvilges dagpenger fra 15. mars 2023 med kr 18 500,- . "
        f"Utbetaling til konto {GYLDIG_KONTO}. "
        f"Kontakt: post@nav.no / 21 07 00 00. Adresse 0181 Oslo."
    )
    r = utvid_entiteter(tekst, {})
    assert r["fodselsnummer"] == GYLDIG_FNR
    assert r["kontonummer"] == GYLDIG_KONTO
    assert r["dato"] == "2023-03-15"
    assert r["belop"] == 18500.0
    assert r["saksnummer"] == "22/9876"
    assert r["kontornavn"] == "NAV Sagene"
    assert r["epost"] == "post@nav.no"
    assert r["telefon"] == "21070000"
    assert r["postnummer"] == "0181"
    assert r["poststed"] == "Oslo"
    assert r["ytelse"] == "dagpenger"
    assert r["fylke"] == "Oslo"


# ── Regresjon for revisjonsfikser (F3-2 anti-hallusinering, F3-3 fylke) ──

def test_f3_3_fylke_deterministisk_lengste_forst():
    # «Troms og Finnmark» skal alltid gi hele navnet, ikke «Troms»
    assert finn_fylke("Sak i Troms og Finnmark fylke") == "Troms og Finnmark"


def test_f3_2_forkaster_hallusinert_telefon():
    # modellen finner på telefon uten kilde i teksten → skal forkastes
    r = utvid_entiteter("Brev uten telefonnummer", {"telefon": "ikke-et-nummer"})
    assert "telefon" not in r


def test_f3_2_forkaster_hallusinert_epost():
    r = utvid_entiteter("Brev uten epost", {"epost": "bare tekst"})
    assert "epost" not in r


def test_f3_2_forkaster_hallusinert_belop():
    r = utvid_entiteter("Brev uten beløp", {"belop": "kjempemye"})
    assert "belop" not in r


def test_f3_2_beholder_gyldig_modell_epost_uten_determ_treff():
    # gyldig epost som modellen fant (determ. finner den også her, men test
    # at gyldig format overlever)
    r = utvid_entiteter("Kontakt", {"epost": "ola@nav.no"})
    assert r.get("epost") == "ola@nav.no"

"""
Enhetstester for virksomhetsregler i dokumentspørsmål —
les_regler (kommentar-/tomlinjefiltrering) og regelinjisering i prompt.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tjenester", "api"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ruter.sporsmal import les_regler, bygg_prompt


def test_les_regler_hopper_over_kommentarer_og_tomme(tmp_path):
    fil = tmp_path / "regler.md"
    fil.write_text(
        "# Overskrift — skal aldri til modellen\n"
        "\n"
        "Svar alltid med kun verdien.\n"
        "   \n"
        "# enda en kommentar\n"
        "Datoer normaliseres til dd.mm.yyyy.\n",
        encoding="utf-8",
    )
    regler = les_regler(str(fil))
    assert regler == [
        "Svar alltid med kun verdien.",
        "Datoer normaliseres til dd.mm.yyyy.",
    ]


def test_les_regler_manglende_fil_gir_tom_liste(tmp_path):
    assert les_regler(str(tmp_path / "finnes_ikke.md")) == []


def test_prompt_uten_regler_har_ingen_regelblokk():
    p = bygg_prompt("Hva er beløpet?", "[Side 1]\ntekst", [])
    assert "VIRKSOMHETSREGLER" not in p


def test_prompt_med_regler_nummererer_og_plasserer_foer_dokumentet():
    regler = ["Svar kun med verdien.", "Ikke bruk forkortelser."]
    p = bygg_prompt("Hva er beløpet?", "[Side 1]\ntekst", regler)
    assert "VIRKSOMHETSREGLER" in p
    assert "1. Svar kun med verdien." in p
    assert "2. Ikke bruk forkortelser." in p
    # reglene skal stå FØR dokumentteksten (instruks, ikke data)
    assert p.index("VIRKSOMHETSREGLER") < p.index("Dokument:")
    # og grunnreglene beholdes
    assert "Ikke gjett" in p


def test_standardfilen_i_repoet_er_gyldig():
    sti = os.path.join(os.path.dirname(__file__), "..",
                       "config", "sporsmal_regler.md")
    regler = les_regler(sti)
    assert len(regler) >= 3
    assert all(not r.startswith("#") for r in regler)

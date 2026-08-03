# -*- coding: utf-8 -*-
"""Koordinater per uttrekt funn — broen fra tekst til posisjon på siden.

To kilder, samme svarform:

  * OCR-veien: regionene fra region_ocr har bokser i FORBEHANDLEDE
    bildepiksler (perspektiv-/skjevhetsrettet). Registeret fra
    flett_regioner_med_register knytter tegnområder til regioner.
  * Tekstlagsveien: PDF-er med tekstlag kjører aldri OCR — der bygges et
    tilsvarende register av ordene fra PyMuPDF (get_text("words")),
    med bokser i PDF-PUNKTER (72 per tomme).

Svaret DEKLARERER hvilket koordinatrom boksene lever i
(«koordinatrom»), pluss sidens dimensjoner i samme rom — uten det kan
klienten ikke skalere en utheving riktig, og en boks er bare fire tall.

Funnene er de samme beviste identifikatorene som /sladd bruker
(finn_sladdeomraader): mod11-/sjekksum-/formatvalidert, aldri modell.
Samme finner på samme tekst — koordinatene og sladdingen kan ikke være
uenige om hva som er et funn.
"""
from delt.region_ocr import flett_regioner_med_register, regioner_for_omraade
from delt.tekstuttrekk import finn_sladdeomraader


def funn_paa_side(regioner: list, typer=None) -> list:
    """Beviste funn på ÉN side, med bokser.

    regioner: [{"boks": [x0,y0,x1,y1], "tekst": str}, …] — flettes her,
    så treffposisjonene garantert gjelder nøyaktig den teksten
    registeret beskriver.

    Returnerer [{"type", "tekst", "bokser"}] i leserekkefølge. «tekst»
    er tegnene slik de står i dokumentet (grupperingen beholdt) — det
    er den formen et menneske skal kjenne igjen ved kontroll."""
    tekst, register = flett_regioner_med_register(regioner)
    funn = []
    for start, slutt, type_ in finn_sladdeomraader(tekst, typer):
        bokser = [r["boks"]
                  for r in regioner_for_omraade(register, start, slutt)]
        if bokser:
            funn.append({"type": type_, "tekst": tekst[start:slutt],
                         "bokser": bokser})
    return funn


def ord_regioner_fra_pdfside(side) -> list:
    """Ordene på en PDF-side med tekstlag, som regioner på samme form
    som OCR-regionene — slik at resten av kjeden er identisk for begge
    veier.

    PyMuPDF gir (x0, y0, x1, y1, ord, blokk, linje, ordnr) i
    PDF-punkter, i leserekkefølge. Flettingen grupperer på vertikalt
    overlapp akkurat som for OCR-bokser."""
    return [{"boks": [w[0], w[1], w[2], w[3]], "tekst": w[4]}
            for w in side.get_text("words") if str(w[4]).strip()]


def koordinater_for_sider(sider: list, koordinatrom: str,
                          typer=None) -> dict:
    """Samlet koordinatsvar for et dokument.

    sider: [{"side": 1-basert, "regioner": […], "bredde": …, "hoyde": …}]
    koordinatrom: «forbehandlet_bilde_piksler» (OCR-veien) eller
                  «pdf_punkter» (tekstlagsveien).

    Sider uten funn er med (tomt funn-felt) — at en side IKKE har
    identifikatorer er også et svar, og klienten skal slippe å gjette
    på om siden ble vurdert."""
    ut_sider = []
    antall = 0
    for s in sider:
        funn = funn_paa_side(s["regioner"], typer)
        antall += len(funn)
        ut_sider.append({"side": s["side"], "bredde": s["bredde"],
                         "hoyde": s["hoyde"], "funn": funn})
    return {"koordinatrom": koordinatrom, "sider": ut_sider,
            "antall_funn": antall}

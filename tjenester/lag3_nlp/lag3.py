import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

sys.path.insert(0, "/config")
sys.path.insert(0, "/delt")
from config.config_loader import CONFIG

if not CONFIG["lag"]["lag3_nlp"]:
    raise SystemExit("Lag 3 (NLP) er deaktivert i config.yaml")

import uvicorn
import torch
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import (
    AutoTokenizer, AutoModelForCausalLM, pipeline,
    LayoutLMv3Processor, LayoutLMv3ForTokenClassification,
)
from PIL import Image

app = FastAPI(title="NAV Lag 3 — NLP")

_PORT = CONFIG["porter"]["lag3"]
_MODELLER_STI = CONFIG["stier"]["modeller"]
_GPU_ENHET = CONFIG["gpu"]["enhet"]

enhet = "cuda" if _GPU_ENHET.startswith("cuda") and torch.cuda.is_available() else "cpu"
enhet_indeks = 0 if enhet == "cuda" else -1

bert_klassifiserer = pipeline(
    "zero-shot-classification",
    model=f"{_MODELLER_STI}/{CONFIG['modeller']['nb_bert']}",
    device=enhet_indeks
)

_layoutlm_laster = True
try:
    layoutlm_prosessor = LayoutLMv3Processor.from_pretrained(
        f"{_MODELLER_STI}/{CONFIG['modeller']['layoutlmv3']}", apply_ocr=False
    )
    layoutlm_modell = LayoutLMv3ForTokenClassification.from_pretrained(
        f"{_MODELLER_STI}/{CONFIG['modeller']['layoutlmv3']}",
        num_labels=6, ignore_mismatched_sizes=True
    ).to(enhet)
    _layoutlm_laster = False
except Exception:
    _layoutlm_laster = True
    ner_pipeline = pipeline(
        "ner",
        model=f"{_MODELLER_STI}/{CONFIG['modeller']['nb_bert_ner']}",
        tokenizer=AutoTokenizer.from_pretrained(
            f"{_MODELLER_STI}/{CONFIG['modeller']['nb_bert_ner']}"
        ),
        aggregation_strategy="simple",
        device=enhet_indeks
    )

borealis_tokenizer = AutoTokenizer.from_pretrained(
    f"{_MODELLER_STI}/{CONFIG['modeller']['borealis']}"
)
borealis_modell = AutoModelForCausalLM.from_pretrained(
    f"{_MODELLER_STI}/{CONFIG['modeller']['borealis']}",
    torch_dtype=torch.float16,
    device_map="auto"
)

_ETIKETTER = ["NAVN", "FODSELSNUMMER", "DATO", "ADRESSE", "SIGNATUR", "O"]
_ID_TIL_ETIKETT = {i: e for i, e in enumerate(_ETIKETTER)}

_NORSKE_FYLKER = [
    "Møre og Romsdal", "Vestfold og Telemark", "Troms og Finnmark",
    "Nord-Trøndelag", "Sør-Trøndelag",
    "Aust-Agder", "Vest-Agder",
    "Sogn og Fjordane",
    "Akershus", "Oslo", "Innlandet", "Vestfold", "Telemark", "Agder",
    "Rogaland", "Vestland", "Trøndelag", "Nordland", "Troms", "Finnmark",
    "Viken", "Buskerud", "Østfold", "Hedmark", "Oppland", "Hordaland",
]


class AnalyseInn(BaseModel):
    fil_id: str
    tekst: str
    tokens: list
    bokser: list
    bilde_sti: str


def _ekstraher_fylke(tekst: str) -> Optional[str]:
    tekst_liten = tekst.lower()
    for fylke in _NORSKE_FYLKER:
        if fylke.lower() in tekst_liten:
            return fylke
    return None


def _klassifiser_dokument(tekst: str) -> dict:
    dokumenttyper = ["soknad", "vedtak", "korrespondanse", "skjema"]
    ytelser = ["uforetrygd", "dagpenger", "pensjon", "sykepenger", "annet"]
    utfall_typer = ["innvilget", "avslatt", "under_behandling", "ukjent"]
    try:
        dok_res = bert_klassifiserer(tekst[:512], candidate_labels=dokumenttyper)
        ytelse_res = bert_klassifiserer(tekst[:512], candidate_labels=ytelser)
        utfall_res = bert_klassifiserer(tekst[:512], candidate_labels=utfall_typer)
        return {
            "dokumenttype": dok_res["labels"][0],
            "ytelse": ytelse_res["labels"][0],
            "utfall": utfall_res["labels"][0],
        }
    except Exception:
        return {"dokumenttype": "ukjent", "ytelse": "annet", "utfall": "ukjent"}


def _layoutlmv3_ekstraher(bilde_sti: str, tokens: list, bokser: list) -> dict:
    try:
        bilde = Image.open(bilde_sti).convert("RGB")
        if not tokens or not bokser:
            innganger = layoutlm_prosessor(bilde, return_tensors="pt").to(enhet)
        else:
            innganger = layoutlm_prosessor(
                bilde, text=tokens, boxes=bokser,
                return_tensors="pt", truncation=True
            ).to(enhet)
        with torch.no_grad():
            utganger = layoutlm_modell(**innganger)
        prediksjoner = utganger.logits.argmax(-1).squeeze().tolist()
        if isinstance(prediksjoner, int):
            prediksjoner = [prediksjoner]
        resultat: dict = {}
        aktuell_etikett = None
        aktuell_tekst: list = []
        for token_id, pred_id in enumerate(prediksjoner):
            etikett = _ID_TIL_ETIKETT.get(pred_id, "O")
            if etikett != "O":
                if etikett == aktuell_etikett:
                    if token_id < len(tokens):
                        aktuell_tekst.append(tokens[token_id])
                else:
                    if aktuell_etikett and aktuell_tekst:
                        resultat.setdefault(aktuell_etikett, " ".join(aktuell_tekst))
                    aktuell_etikett = etikett
                    aktuell_tekst = [tokens[token_id]] if token_id < len(tokens) else []
            else:
                if aktuell_etikett and aktuell_tekst:
                    resultat.setdefault(aktuell_etikett, " ".join(aktuell_tekst))
                aktuell_etikett = None
                aktuell_tekst = []
        if aktuell_etikett and aktuell_tekst:
            resultat.setdefault(aktuell_etikett, " ".join(aktuell_tekst))
        return resultat
    except Exception:
        return _trekk_ut_entiteter_ner("")


def _trekk_ut_entiteter_ner(tekst: str) -> dict:
    try:
        entiteter = ner_pipeline(tekst[:512])
        resultat = {}
        for e in entiteter:
            etikett = e["entity_group"]
            if etikett not in resultat:
                resultat[etikett] = e["word"]
        return resultat
    except Exception:
        return {}


def _borealis_analyse(tekst: str, klassifisering: dict, entiteter: dict) -> dict:
    prompt = f"""Du er en norsk arkivar som analyserer historiske NAV-dokumenter.
Dokument:
{tekst[:1000]}
Allerede funnet:
- Type: {klassifisering.get('dokumenttype')}
- Ytelse: {klassifisering.get('ytelse')}
Svar på norsk bokmål med:
1. Kort oppsummering (maks 2 setninger)
2. Fylke (hvis nevnt i dokumentet)
3. Eventuelle manglende felt"""
    try:
        innganger = borealis_tokenizer(prompt, return_tensors="pt").to(borealis_modell.device)
        with torch.no_grad():
            utganger = borealis_modell.generate(
                **innganger, max_new_tokens=200, temperature=0.1, do_sample=False
            )
        svar = borealis_tokenizer.decode(utganger[0], skip_special_tokens=True)
        fylke = _ekstraher_fylke(svar) or _ekstraher_fylke(tekst)
        return {"oppsummering": svar[:500], "fylke": fylke}
    except Exception:
        return {"oppsummering": None, "fylke": _ekstraher_fylke(tekst)}


@app.post("/analyser")
async def analyser(data: AnalyseInn):
    with ThreadPoolExecutor(max_workers=2) as executor:
        klassifisering_fremtid = executor.submit(_klassifiser_dokument, data.tekst)
        if not _layoutlm_laster and data.bilde_sti:
            entiteter_fremtid = executor.submit(
                _layoutlmv3_ekstraher, data.bilde_sti, data.tokens, data.bokser
            )
        else:
            entiteter_fremtid = executor.submit(_trekk_ut_entiteter_ner, data.tekst)
        klassifisering = klassifisering_fremtid.result()
        entiteter = entiteter_fremtid.result()

    borealis_data = _borealis_analyse(data.tekst, klassifisering, entiteter)

    konfidens = 0.9 if entiteter else 0.5

    return {
        "navn": entiteter.get("NAVN") or entiteter.get("PER"),
        "fodselsnummer": entiteter.get("FODSELSNUMMER"),
        "dato": entiteter.get("DATO") or entiteter.get("DATE"),
        "adresse": entiteter.get("ADRESSE") or entiteter.get("LOC"),
        "signatur": entiteter.get("SIGNATUR"),
        "ytelse": klassifisering.get("ytelse"),
        "dokumenttype": klassifisering.get("dokumenttype", "ukjent"),
        "utfall": klassifisering.get("utfall"),
        "fylke": borealis_data.get("fylke") or entiteter.get("LOC"),
        "oppsummering": borealis_data.get("oppsummering"),
        "konfidens": konfidens,
    }


@app.get("/helse")
async def helse():
    return {
        "status": "ok",
        "lag": 3,
        "layoutlmv3": "lastet" if not _layoutlm_laster else "ikke tilgjengelig",
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=_PORT)

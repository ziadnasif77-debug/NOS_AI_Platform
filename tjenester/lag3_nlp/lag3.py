import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

sys.path.insert(0, "/app")
from config.config_loader import CONFIG

if not CONFIG["lag"]["lag3_nlp"]:
    raise SystemExit("Lag 3 (NLP) er deaktivert i config.yaml")

import uvicorn
import torch
from fastapi import FastAPI
from pydantic import BaseModel
from PIL import Image

app = FastAPI(title="NAV Lag 3 — NLP")

_PORT = CONFIG["porter"]["lag3"]
_MODELLER_STI = CONFIG["stier"]["modeller"]
_GPU_ENHET = CONFIG["gpu"]["enhet"]

_ETIKETTER = ["NAVN", "FODSELSNUMMER", "DATO", "ADRESSE", "SIGNATUR", "O"]
_ID_TIL_ETIKETT = dict(enumerate(_ETIKETTER))

_NORSKE_FYLKER = [
    "Møre og Romsdal", "Vestfold og Telemark", "Troms og Finnmark",
    "Nord-Trøndelag", "Sør-Trøndelag",
    "Aust-Agder", "Vest-Agder",
    "Sogn og Fjordane",
    "Akershus", "Oslo", "Innlandet", "Vestfold", "Telemark", "Agder",
    "Rogaland", "Vestland", "Trøndelag", "Nordland", "Troms", "Finnmark",
    "Viken", "Buskerud", "Østfold", "Hedmark", "Oppland", "Hordaland",
]

# Lazy singleton state
_modell_lås = threading.Lock()
_bert_klassifiserer = None
_layoutlm_prosessor = None
_layoutlm_modell = None
_layoutlm_utilgjengelig = False
_ner_pipeline = None
_borealis_tokenizer = None
_borealis_modell = None


def _enhet() -> str:
    return "cuda" if _GPU_ENHET.startswith("cuda") and torch.cuda.is_available() else "cpu"


def _enhet_indeks() -> int:
    return 0 if _enhet() == "cuda" else -1


def _hent_bert():
    global _bert_klassifiserer
    if _bert_klassifiserer is None:
        with _modell_lås:
            if _bert_klassifiserer is None:
                from transformers import pipeline
                _bert_klassifiserer = pipeline(
                    "zero-shot-classification",
                    model=f"{_MODELLER_STI}/{CONFIG['modeller']['nb_bert']}",
                    device=_enhet_indeks(),
                )
    return _bert_klassifiserer


def _hent_layoutlm():
    global _layoutlm_prosessor, _layoutlm_modell, _layoutlm_utilgjengelig
    if _layoutlm_utilgjengelig:
        return None, None
    if _layoutlm_modell is None:
        with _modell_lås:
            if _layoutlm_modell is None and not _layoutlm_utilgjengelig:
                try:
                    from transformers import LayoutLMv3Processor, LayoutLMv3ForTokenClassification
                    _layoutlm_prosessor = LayoutLMv3Processor.from_pretrained(
                        f"{_MODELLER_STI}/{CONFIG['modeller']['layoutlmv3']}",
                        apply_ocr=False,
                    )
                    _layoutlm_modell = LayoutLMv3ForTokenClassification.from_pretrained(
                        f"{_MODELLER_STI}/{CONFIG['modeller']['layoutlmv3']}",
                        num_labels=6,
                        ignore_mismatched_sizes=True,
                    ).to(_enhet())
                except Exception:
                    _layoutlm_utilgjengelig = True
    return _layoutlm_prosessor, _layoutlm_modell


def _hent_ner():
    global _ner_pipeline
    if _ner_pipeline is None:
        with _modell_lås:
            if _ner_pipeline is None:
                from transformers import AutoTokenizer, pipeline
                _ner_pipeline = pipeline(
                    "ner",
                    model=f"{_MODELLER_STI}/{CONFIG['modeller']['nb_bert_ner']}",
                    tokenizer=AutoTokenizer.from_pretrained(
                        f"{_MODELLER_STI}/{CONFIG['modeller']['nb_bert_ner']}"
                    ),
                    aggregation_strategy="simple",
                    device=_enhet_indeks(),
                )
    return _ner_pipeline


def _hent_borealis():
    global _borealis_tokenizer, _borealis_modell
    if _borealis_modell is None:
        with _modell_lås:
            if _borealis_modell is None:
                from transformers import AutoTokenizer, AutoModelForCausalLM
                _borealis_tokenizer = AutoTokenizer.from_pretrained(
                    f"{_MODELLER_STI}/{CONFIG['modeller']['borealis']}"
                )
                _borealis_modell = AutoModelForCausalLM.from_pretrained(
                    f"{_MODELLER_STI}/{CONFIG['modeller']['borealis']}",
                    torch_dtype=torch.float16,
                    device_map="auto",
                )
    return _borealis_tokenizer, _borealis_modell


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
        bert = _hent_bert()
        dok_res = bert(tekst[:512], candidate_labels=dokumenttyper)
        ytelse_res = bert(tekst[:512], candidate_labels=ytelser)
        utfall_res = bert(tekst[:512], candidate_labels=utfall_typer)
        return {
            "dokumenttype": dok_res["labels"][0],
            "ytelse": ytelse_res["labels"][0],
            "utfall": utfall_res["labels"][0],
        }
    except Exception:
        return {"dokumenttype": "ukjent", "ytelse": "annet", "utfall": "ukjent"}


def _layoutlmv3_ekstraher(bilde_sti: str, tokens: list, bokser: list) -> dict:
    prosessor, modell = _hent_layoutlm()
    if prosessor is None or modell is None:
        return _trekk_ut_entiteter_ner("")
    try:
        enhet = _enhet()
        bilde = Image.open(bilde_sti).convert("RGB")
        if not tokens or not bokser:
            innganger = prosessor(bilde, return_tensors="pt").to(enhet)
        else:
            innganger = prosessor(
                bilde, text=tokens, boxes=bokser,
                return_tensors="pt", truncation=True,
            ).to(enhet)
        with torch.no_grad():
            utganger = modell(**innganger)
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
        entiteter = _hent_ner()(tekst[:512])
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
        tokenizer, modell = _hent_borealis()
        innganger = tokenizer(prompt, return_tensors="pt").to(modell.device)
        with torch.no_grad():
            utganger = modell.generate(
                **innganger, max_new_tokens=200, temperature=0.1, do_sample=False
            )
        svar = tokenizer.decode(utganger[0], skip_special_tokens=True)
        fylke = _ekstraher_fylke(svar) or _ekstraher_fylke(tekst)
        return {"oppsummering": svar[:500], "fylke": fylke}
    except Exception:
        return {"oppsummering": None, "fylke": _ekstraher_fylke(tekst)}


@app.post("/analyser")
async def analyser(data: AnalyseInn):
    _, layoutlm_modell = _hent_layoutlm()
    bruk_layoutlm = layoutlm_modell is not None and bool(data.bilde_sti)

    with ThreadPoolExecutor(max_workers=2) as executor:
        klassifisering_fremtid = executor.submit(_klassifiser_dokument, data.tekst)
        if bruk_layoutlm:
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
    _, layoutlm_modell = _hent_layoutlm() if not _layoutlm_utilgjengelig else (None, None)
    return {
        "status": "ok",
        "lag": 3,
        "layoutlmv3": "lastet" if layoutlm_modell is not None else "ikke lastet",
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=_PORT)

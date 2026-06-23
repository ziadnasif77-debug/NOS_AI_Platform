import os
import sys
import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from transformers import (
    AutoTokenizer, AutoModelForCausalLM, pipeline,
    LayoutLMv3Processor, LayoutLMv3ForTokenClassification,
)
import torch
from PIL import Image

sys.path.insert(0, "/delt")
from delt.verktøy import konfigurer_logging, les_json
from delt.skjemaer import UttrukketData

logger = konfigurer_logging("nlp-tjeneste")
app = FastAPI(title="NAV NLP-tjeneste")

MODELLER_STI = os.environ.get("MODELLER_STI", "/modeller")
SOK_URL = os.environ.get("SOK_URL", "http://sok:8003")
GPU_ENHET = os.environ.get("GPU_ENHET", "cpu")

enhet = "cuda" if GPU_ENHET.startswith("cuda") and torch.cuda.is_available() else "cpu"
enhet_indeks = 0 if enhet == "cuda" else -1

# NB-BERT for zero-shot document classification
logger.info("Laster NB-BERT-base...")
bert_klassifiserer = pipeline(
    "zero-shot-classification",
    model=f"{MODELLER_STI}/nb-bert",
    device=enhet_indeks
)

# LayoutLMv3 for field extraction (text + layout)
logger.info("Laster LayoutLMv3...")
_layoutlm_laster = True
try:
    layoutlm_prosessor = LayoutLMv3Processor.from_pretrained(
        f"{MODELLER_STI}/layoutlmv3", apply_ocr=False
    )
    layoutlm_modell = LayoutLMv3ForTokenClassification.from_pretrained(
        f"{MODELLER_STI}/layoutlmv3"
    ).to(enhet)
    _layoutlm_laster = False
    logger.info("LayoutLMv3 lastet")
except Exception as feil:
    logger.warning(f"LayoutLMv3 ikke tilgjengelig, faller tilbake til NB-BERT-NER: {feil}")
    _layoutlm_laster = True
    ner_pipeline = pipeline(
        "ner",
        model=f"{MODELLER_STI}/nb-bert-ner",
        tokenizer=AutoTokenizer.from_pretrained(f"{MODELLER_STI}/nb-bert-ner"),
        aggregation_strategy="simple",
        device=enhet_indeks
    )

# Borealis-4B for summarization and context
logger.info("Laster Borealis-4B...")
borealis_tokenizer = AutoTokenizer.from_pretrained(f"{MODELLER_STI}/borealis")
borealis_modell = AutoModelForCausalLM.from_pretrained(
    f"{MODELLER_STI}/borealis",
    torch_dtype=torch.float16,
    device_map="auto"
)

# LayoutLMv3 label mapping (B-/I- prefix per NER convention)
_ETIKETTER = ["O", "B-NAVN", "I-NAVN", "B-FODSELSNUMMER", "I-FODSELSNUMMER",
              "B-DATO", "I-DATO", "B-ADRESSE", "I-ADRESSE",
              "B-SIGNATUR", "I-SIGNATUR"]
_ID_TIL_ETIKETT = {i: e for i, e in enumerate(_ETIKETTER)}


@app.post("/behandle")
async def behandle(data: dict):
    fil_id = data.get("fil_id")
    renset_sti = data.get("renset_sti")
    bilde_sti = data.get("bilde_sti")  # OCR sender nå bilde-sti også
    if not fil_id or not renset_sti:
        raise HTTPException(status_code=400, detail="fil_id og renset_sti er paakrevd")
    try:
        ocr_data = les_json(renset_sti)
        tekst = ocr_data.get("tekst", "")
        tokens = ocr_data.get("tokens", [])
        bokser = ocr_data.get("bokser", [])

        klassifisering = _klassifiser_dokument(tekst)

        # Bruk LayoutLMv3 hvis tilgjengelig og bildet finnes
        if not _layoutlm_laster and bilde_sti:
            entiteter = _layoutlmv3_ekstraher(bilde_sti, tokens, bokser)
        else:
            entiteter = _trekk_ut_entiteter_ner(tekst)

        borealis_data = _borealis_analyse(tekst, klassifisering, entiteter)

        resultat = UttrukketData(
            fil_id=fil_id,
            fodselsnummer=entiteter.get("FODSELSNUMMER"),
            navn=entiteter.get("NAVN") or entiteter.get("PER"),
            dato=entiteter.get("DATO") or entiteter.get("DATE"),
            adresse=entiteter.get("ADRESSE") or entiteter.get("LOC"),
            signatur=entiteter.get("SIGNATUR"),
            ytelse=klassifisering.get("ytelse"),
            kontornavn=entiteter.get("ORG"),
            fylke=borealis_data.get("fylke") or entiteter.get("LOC"),
            dokumenttype=klassifisering.get("dokumenttype", "ukjent"),
            utfall=klassifisering.get("utfall"),
            oppsummering=borealis_data.get("oppsummering"),
        )
        _send_til_sok(fil_id, tekst, resultat)
        return resultat.model_dump()
    except Exception as feil:
        logger.error(f"NLP-feil for {fil_id}: {feil}")
        raise HTTPException(status_code=500, detail=str(feil))


def _layoutlmv3_ekstraher(bilde_sti: str, tokens: list, bokser: list) -> dict:
    """
    Bruker LayoutLMv3 til feltuttrekking — ser tekst + layout samtidig.
    Mye mer nøyaktig enn NB-BERT-NER for strukturerte NAV-skjemaer.
    """
    try:
        bilde = Image.open(bilde_sti).convert("RGB")
        if not tokens or not bokser:
            # Fallback: bruk bare bildet uten forhåndsberegnet OCR
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

        # Samle tokens per etikett
        resultat: dict = {}
        gjeldende_etikett = None
        gjeldende_ord = []
        for token_id, pred_id in enumerate(prediksjoner):
            etikett = _ID_TIL_ETIKETT.get(pred_id, "O")
            if etikett.startswith("B-"):
                if gjeldende_etikett and gjeldende_ord:
                    resultat[gjeldende_etikett] = " ".join(gjeldende_ord)
                gjeldende_etikett = etikett[2:]
                gjeldende_ord = [tokens[token_id]] if token_id < len(tokens) else []
            elif etikett.startswith("I-") and gjeldende_etikett:
                if token_id < len(tokens):
                    gjeldende_ord.append(tokens[token_id])
            else:
                if gjeldende_etikett and gjeldende_ord:
                    resultat[gjeldende_etikett] = " ".join(gjeldende_ord)
                gjeldende_etikett = None
                gjeldende_ord = []

        if gjeldende_etikett and gjeldende_ord:
            resultat[gjeldende_etikett] = " ".join(gjeldende_ord)

        logger.info(f"LayoutLMv3 fant: {list(resultat.keys())}")
        return resultat
    except Exception as feil:
        logger.error(f"LayoutLMv3-feil: {feil}")
        return _trekk_ut_entiteter_ner("")


def _trekk_ut_entiteter_ner(tekst: str) -> dict:
    """Fallback: NB-BERT-NER når LayoutLMv3 ikke er tilgjengelig."""
    try:
        entiteter = ner_pipeline(tekst[:512])
        resultat = {}
        for e in entiteter:
            etikett = e["entity_group"]
            if etikett not in resultat:
                resultat[etikett] = e["word"]
        return resultat
    except Exception as feil:
        logger.error(f"NER-feil: {feil}")
        return {}


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
    except Exception as feil:
        logger.error(f"Klassifiseringsfeil: {feil}")
        return {"dokumenttype": "ukjent", "ytelse": "annet", "utfall": "ukjent"}


def _borealis_analyse(tekst: str, klassifisering: dict, entiteter: dict) -> dict:
    prompt = f"""Du er en norsk arkivar som analyserer historiske NAV-dokumenter.
Dokument:
{tekst[:1000]}
Allerede funnet:
- Type: {klassifisering.get('dokumenttype')}
- Ytelse: {klassifisering.get('ytelse')}
Svar pa norsk bokmal med:
1. Kort oppsummering (maks 2 setninger)
2. Fylke (hvis nevnt)
3. Eventuelle manglende felt"""
    try:
        innganger = borealis_tokenizer(prompt, return_tensors="pt").to(borealis_modell.device)
        with torch.no_grad():
            utganger = borealis_modell.generate(
                **innganger,
                max_new_tokens=200,
                temperature=0.1,
                do_sample=False
            )
        svar = borealis_tokenizer.decode(utganger[0], skip_special_tokens=True)
        return {"oppsummering": svar[:500], "fylke": None}
    except Exception as feil:
        logger.error(f"Borealis-feil: {feil}")
        return {"oppsummering": None, "fylke": None}


def _send_til_sok(fil_id: str, tekst: str, data: UttrukketData) -> None:
    try:
        requests.post(
            f"{SOK_URL}/indekser",
            json={"fil_id": fil_id, "tekst": tekst, "metadata": data.model_dump()},
            timeout=60
        )
    except requests.RequestException as feil:
        logger.warning(f"Kunne ikke sende til sok: {feil}")


@app.get("/helse")
async def helse():
    return {
        "status": "ok",
        "tjeneste": "nlp",
        "layoutlmv3": "lastet" if not _layoutlm_laster else "ikke tilgjengelig (NB-BERT-NER aktiv)"
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)

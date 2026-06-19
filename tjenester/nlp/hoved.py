import os
import sys
import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
import torch

sys.path.insert(0, "/delt")
from delt.verktøy import konfigurer_logging, les_json
from delt.skjemaer import UttrukketData

logger = konfigurer_logging("nlp-tjeneste")
app = FastAPI(title="NAV NLP-tjeneste")

MODELLER_STI = os.environ.get("MODELLER_STI", "/modeller")
SOK_URL = os.environ.get("SOK_URL", "http://sok:8003")
GPU_ENHET = os.environ.get("GPU_ENHET", "cpu")

enhet_indeks = 0 if GPU_ENHET.startswith("cuda") else -1

logger.info("Laster NB-BERT-base...")
bert_klassifiserer = pipeline(
    "zero-shot-classification",
    model=f"{MODELLER_STI}/nb-bert",
    device=enhet_indeks
)

logger.info("Laster NB-BERT-NER...")
ner_pipeline = pipeline(
    "ner",
    model=f"{MODELLER_STI}/nb-bert-ner",
    tokenizer=AutoTokenizer.from_pretrained(f"{MODELLER_STI}/nb-bert-ner"),
    aggregation_strategy="simple",
    device=enhet_indeks
)

logger.info("Laster Borealis-4B...")
borealis_tokenizer = AutoTokenizer.from_pretrained(f"{MODELLER_STI}/borealis")
borealis_modell = AutoModelForCausalLM.from_pretrained(
    f"{MODELLER_STI}/borealis",
    torch_dtype=torch.float16,
    device_map="auto"
)


@app.post("/behandle")
async def behandle(data: dict):
    fil_id = data.get("fil_id")
    renset_sti = data.get("renset_sti")
    if not fil_id or not renset_sti:
        raise HTTPException(status_code=400, detail="fil_id og renset_sti er paakrevd")
    try:
        ocr_data = les_json(renset_sti)
        tekst = ocr_data.get("tekst", "")
        klassifisering = _klassifiser_dokument(tekst)
        entiteter = _trekk_ut_entiteter(tekst)
        borealis_data = _borealis_analyse(tekst, klassifisering, entiteter)
        resultat = UttrukketData(
            fil_id=fil_id,
            fodselsnummer=entiteter.get("NUM"),
            navn=entiteter.get("PER"),
            dato=entiteter.get("DATE"),
            adresse=entiteter.get("LOC"),
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


def _trekk_ut_entiteter(tekst: str) -> dict:
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
    return {"status": "ok", "tjeneste": "nlp"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)

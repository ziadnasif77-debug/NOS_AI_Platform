"""
Lag 2 — NLP Worker (inkluderer validering og kryssvalidering)
Kombinerer lag3_nlp + lag4_validering + lag5_kryssvalidering.
"""
import sys
import os
import re
import logging
import socket
from datetime import datetime
from typing import Optional

sys.path.insert(0, "/app")
from config.config_loader import CONFIG
from delt.konstanter import TRYKT, TABELL
from delt.skjemaer import OCRResultat
from tjenester.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)

WORKER_ID = f"lag2-{socket.gethostname()}"

NORSKE_FYLKER = {
    "Oslo", "Viken", "Innlandet", "Vestfold og Telemark",
    "Agder", "Rogaland", "Vestland", "Møre og Romsdal",
    "Trøndelag", "Nordland", "Troms og Finnmark",
    "Troms", "Finnmark",
}

OBLIGATORISKE_FELT = {
    "dagpenger": ["navn", "fodselsnummer", "dato"],
    "uforetrygd": ["navn", "fodselsnummer", "dato", "ytelse"],
    "sykepenger": ["navn", "fodselsnummer", "dato"],
}


class NLPWorker(BaseWorker):

    def __init__(self):
        cfg = CONFIG["redis"]
        super().__init__(
            worker_id=WORKER_ID,
            queue_name=cfg["kooer"]["nlp"],
            dlq_name=cfg["dlq"]["nlp"],
            running_state="NLP_PROCESSING",
            done_state="ROUTING",
        )
        self._layoutlm_processor = None
        self._layoutlm_model = None
        self._layoutlmv3_available = False
        self._borealis_pipeline = None
        self._borealis_available = False
        self._nb_bert_pipeline = None
        self._nb_bert_available = False
        self._last_modeller()

    def _last_modeller(self):
        """Laster alle NLP-modeller én gang ved oppstart — ikke per dokument."""
        try:
            from transformers import LayoutLMv3Processor, LayoutLMv3ForTokenClassification
            modell_sti = CONFIG["modeller"]["layoutlmv3"]
            self._layoutlm_processor = LayoutLMv3Processor.from_pretrained(
                modell_sti, apply_ocr=False
            )
            self._layoutlm_model = LayoutLMv3ForTokenClassification.from_pretrained(
                modell_sti, num_labels=6, ignore_mismatched_sizes=True
            )
            self._layoutlm_model.eval()
            self._layoutlmv3_available = True
            logger.info("LayoutLMv3 lastet.")
        except Exception as exc:
            logger.warning("LayoutLMv3 lasting feilet: %s", exc)

        try:
            from transformers import pipeline
            self._borealis_pipeline = pipeline(
                "ner", model=CONFIG["modeller"]["borealis"], aggregation_strategy="simple"
            )
            self._borealis_available = True
            logger.info("Borealis NER lastet.")
        except Exception as exc:
            logger.warning("Borealis lasting feilet: %s", exc)

        try:
            from transformers import pipeline
            self._nb_bert_pipeline = pipeline(
                "ner", model=CONFIG["modeller"]["nb_bert_ner"], aggregation_strategy="simple"
            )
            self._nb_bert_available = True
            logger.info("NB-BERT-NER lastet.")
        except Exception as exc:
            logger.warning("NB-BERT lasting feilet: %s", exc)

        tilgjengelige = [
            m for m, ok in [
                ("layoutlmv3", self._layoutlmv3_available),
                ("borealis",   self._borealis_available),
                ("nb-bert-ner", self._nb_bert_available),
            ] if ok
        ]
        if not tilgjengelige:
            raise RuntimeError(
                "Ingen NLP-modeller tilgjengelige — NLPWorker kan ikke starte. "
                "Kjør 'make last-ned-modeller' for å laste ned nødvendige modeller."
            )
        logger.info("NLPWorker klar. Tilgjengelige modeller: %s", tilgjengelige)

    def process(self, job: dict, pg_conn) -> dict:
        job_id = job["job_id"]
        ocr_res = OCRResultat.model_validate(job["forrige_resultat"])
        tekst = ocr_res.text
        tokens = ocr_res.tokens
        bokser = ocr_res.boxes
        dokumenttype = ocr_res.document_type
        bilde_sti = ocr_res.raw_path
        ocr_konfidens = ocr_res.confidence

        entiteter, dokklasse, ytelse, nlp_konfidens, modell = self._ekstraher(
            tekst, tokens, bokser, dokumenttype, bilde_sti
        )

        utfall = self._bestem_utfall(entiteter, tekst)
        oppsummering = self._lag_oppsummering(entiteter, dokklasse, utfall)

        validering = self._valider(entiteter, dokklasse)
        anomali = self._sjekk_anomali(entiteter, validering)

        # Kryssvalidering (kun hvis aktivert)
        if CONFIG["lag"].get("lag5_kryssvalidering", False):
            anomali.update(self._kryssvalider(entiteter))

        if not validering["gyldig"] or anomali.get("har_anomali"):
            project_id = CONFIG["label_studio"]["prosjekter"]["lag4"]
            self.send_til_label_studio(
                job_id=job_id,
                image_path=job.get("fil_sti", ""),
                ocr_text=tekst,
                project_id=project_id,
                stage="validering",
            )

        return {
            "job_id": job_id,
            "entities": entiteter,
            "document_class": dokklasse,
            "ytelse": ytelse,
            "utfall": utfall,
            "summary": oppsummering,
            "nlp_confidence": round(nlp_konfidens, 4),
            "nlp_model_used": modell,
            "validation": validering,
            "anomaly": anomali,
            "ocr_confidence": round(ocr_konfidens, 4),
        }

    # ------------------------------------------------------------------ #
    #  NLP-motor-routing                                                   #
    # ------------------------------------------------------------------ #

    def _ekstraher(self, tekst, tokens, bokser, dokumenttype, bilde_sti=""):
        har_layout = bool(tokens) and bool(bokser)
        if dokumenttype in (TRYKT, TABELL) and har_layout and self._layoutlmv3_available:
            return self._layoutlmv3(bilde_sti, tokens, bokser, tekst)
        elif len(tekst) > 500 and self._borealis_available:
            return self._borealis(tekst)
        else:
            return self._nb_bert(tekst)

    _ETIKETTER = ["NAVN", "FODSELSNUMMER", "DATO", "ADRESSE", "SIGNATUR", "O"]
    _ID_TIL_ETIKETT = dict(enumerate(["NAVN", "FODSELSNUMMER", "DATO", "ADRESSE", "SIGNATUR", "O"]))

    def _layoutlmv3(self, bilde_sti, tokens, bokser, tekst=""):
        try:
            from PIL import Image
            import torch

            try:
                bilde = Image.open(bilde_sti).convert("RGB")
            except Exception:
                bilde = Image.new("RGB", (224, 224), color=255)

            innganger = self._layoutlm_processor(
                bilde, text=tokens, boxes=bokser,
                return_tensors="pt", truncation=True
            )
            with torch.no_grad():
                utganger = self._layoutlm_model(**innganger)

            prediksjoner = utganger.logits.argmax(-1).squeeze().tolist()
            if isinstance(prediksjoner, int):
                prediksjoner = [prediksjoner]

            entiteter: dict = {}
            aktuell_etikett = None
            aktuell_tekst: list = []
            for token_id, pred_id in enumerate(prediksjoner):
                etikett = self._ID_TIL_ETIKETT.get(pred_id, "O")
                if etikett != "O":
                    if etikett == aktuell_etikett:
                        if token_id < len(tokens):
                            aktuell_tekst.append(tokens[token_id])
                    else:
                        if aktuell_etikett and aktuell_tekst:
                            entiteter.setdefault(aktuell_etikett.lower(), " ".join(aktuell_tekst))
                        aktuell_etikett = etikett
                        aktuell_tekst = [tokens[token_id]] if token_id < len(tokens) else []
                else:
                    if aktuell_etikett and aktuell_tekst:
                        entiteter.setdefault(aktuell_etikett.lower(), " ".join(aktuell_tekst))
                    aktuell_etikett = None
                    aktuell_tekst = []
            if aktuell_etikett and aktuell_tekst:
                entiteter.setdefault(aktuell_etikett.lower(), " ".join(aktuell_tekst))

            return entiteter, "skjema", entiteter.get("ytelse"), 0.91, "layoutlmv3"
        except Exception as exc:
            logger.warning("LayoutLMv3 feilet: %s — bruker NB-BERT", exc)
            return self._nb_bert(tekst)

    def _borealis(self, tekst):
        try:
            ner_res = self._borealis_pipeline(tekst[:1024])
            entiteter = self._konverter_ner(ner_res)
            return entiteter, "brev", entiteter.get("ytelse"), 0.87, "borealis"
        except Exception as exc:
            logger.warning("Borealis feilet: %s — bruker NB-BERT", exc)
            return self._nb_bert(tekst)

    def _nb_bert(self, tekst):
        if not self._nb_bert_available:
            logger.error("NB-BERT ikke tilgjengelig — alle modeller feilet")
            return {}, "ukjent", None, 0.0, "ingen-modell"
        try:
            ner_res = self._nb_bert_pipeline(tekst[:512])
            entiteter = self._konverter_ner(ner_res)
            return entiteter, "ukjent", entiteter.get("ytelse"), 0.82, "nb-bert-ner"
        except Exception as exc:
            logger.warning("NB-BERT feilet: %s", exc)
            return {}, "ukjent", None, 0.0, "nb-bert-feil"

    # ------------------------------------------------------------------ #
    #  Hjelpemetoder for entiteter                                         #
    # ------------------------------------------------------------------ #

    def _konverter_ner(self, ner_res: list) -> dict:
        entiteter = {}
        for e in ner_res:
            label = e.get("entity_group", "").upper()
            verdi = e.get("word", "").strip()
            if "PER" in label or "NAVN" in label:
                entiteter.setdefault("navn", verdi)
            elif "LOC" in label or "FYLKE" in label:
                entiteter.setdefault("fylke", verdi)
            elif "ORG" in label:
                entiteter.setdefault("ytelse", verdi)
            elif "DATE" in label or "DATO" in label:
                entiteter.setdefault("dato", verdi)
        return entiteter

    # ------------------------------------------------------------------ #
    #  Utfall og oppsummering                                              #
    # ------------------------------------------------------------------ #

    def _bestem_utfall(self, entiteter: dict, tekst: str) -> str:
        tekst_lower = tekst.lower()
        if any(w in tekst_lower for w in ["innvilget", "godkjent", "godkjenner"]):
            return "innvilget"
        elif any(w in tekst_lower for w in ["avslått", "avslår", "nei", "ikke innvilget"]):
            return "avslatt"
        elif any(w in tekst_lower for w in ["under behandling", "til behandling"]):
            return "under_behandling"
        return "ukjent"

    def _lag_oppsummering(self, entiteter: dict, dokklasse: str, utfall: str) -> str:
        navn = entiteter.get("navn", "ukjent")
        return f"{dokklasse.capitalize()} for {navn} — utfall: {utfall}"

    # ------------------------------------------------------------------ #
    #  Validering (direkte funksjonskall, ingen HTTP)                     #
    # ------------------------------------------------------------------ #

    def _valider(self, entiteter: dict, dokklasse: str) -> dict:
        feil = []
        fnr = entiteter.get("fodselsnummer")
        if fnr and not self._valider_fnr(fnr):
            feil.append("ugyldig_fodselsnummer")

        dato = entiteter.get("dato")
        if dato and not self._valider_dato(dato):
            feil.append("ugyldig_dato")

        fylke = entiteter.get("fylke")
        if fylke and fylke not in NORSKE_FYLKER:
            feil.append("ukjent_fylke")

        obligatoriske = OBLIGATORISKE_FELT.get(dokklasse, [])
        mangler = [f for f in obligatoriske if not entiteter.get(f)]
        if mangler:
            feil.append(f"mangler_felt: {','.join(mangler)}")

        return {"gyldig": len(feil) == 0, "feil": feil}

    def _valider_fnr(self, fnr: str) -> bool:
        if not fnr or not fnr.isdigit() or len(fnr) != 11:
            return False
        vekter1 = [3, 7, 6, 1, 8, 9, 4, 5, 2]
        vekter2 = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]

        def k(sifre, v):
            s = sum(int(sifre[i]) * v[i] for i in range(len(v)))
            r = 11 - (s % 11)
            return 0 if r == 11 else r

        return k(fnr, vekter1) == int(fnr[9]) and k(fnr, vekter2) == int(fnr[10])

    def _valider_dato(self, dato: str) -> bool:
        if not dato:
            return False
        for fmt in ["%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"]:
            try:
                d = datetime.strptime(dato.strip(), fmt)
                return 1900 <= d.year <= datetime.utcnow().year
            except ValueError:
                continue
        return False

    def _sjekk_anomali(self, entiteter: dict, validering: dict) -> dict:
        terskel = CONFIG["terskler"]["anomali_score"]
        antall_feil = len(validering.get("feil", []))
        score = min(antall_feil * 0.25, 1.0)
        return {
            "har_anomali": score >= terskel,
            "anomali_score": round(score, 4),
            "detaljer": validering.get("feil", []),
        }

    def _kryssvalider(self, entiteter: dict) -> dict:
        feil = []
        fnr = entiteter.get("fodselsnummer", "")
        dato = entiteter.get("dato", "")
        if fnr and len(fnr) >= 6 and dato:
            dag_mnd = fnr[:4]
            try:
                d = datetime.strptime(dato, "%d.%m.%Y")
                forventet = d.strftime("%d%m")
                if dag_mnd != forventet:
                    feil.append("fnr_dato_mismatch")
            except ValueError:
                pass
        return {"kryssvalidering_feil": feil}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    NLPWorker().run()

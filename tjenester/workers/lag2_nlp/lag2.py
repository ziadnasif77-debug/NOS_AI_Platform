"""
Lag 2 — NLP Worker (inkluderer validering og kryssvalidering)
Kombinerer lag3_nlp + lag4_validering + lag5_kryssvalidering.
"""
import sys
import os
import re
import json
import logging
import socket
import torch
from datetime import datetime
from typing import Optional

sys.path.insert(0, "/app")
from config.config_loader import CONFIG
from delt.konstanter import TRYKT, TABELL, NORSKE_FYLKER
from delt.skjemaer import OCRResultat, NLPResultat, ValideringsResultat, AnomalyResultat
from delt.tekstuttrekk import utvid_entiteter, er_gyldig_fnr
from tjenester.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)

WORKER_ID = f"lag2-{socket.gethostname()}"
MODELLER_STI = os.environ.get("MODELLER_STI", "/modeller")
GPU_ENHET = CONFIG["gpu"]["enhet"]

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
        self._borealis_tokenizer = None
        self._borealis_model = None
        self._borealis_available = False
        self._nb_bert_pipeline = None
        self._nb_bert_available = False
        self._last_modeller()

    def _last_modeller(self):
        """Laster alle NLP-modeller én gang ved oppstart — ikke per dokument."""
        try:
            from transformers import LayoutLMv3Processor, LayoutLMv3ForTokenClassification
            modell_sti = f"{MODELLER_STI}/{CONFIG['modeller']['layoutlmv3']}"
            self._layoutlm_processor = LayoutLMv3Processor.from_pretrained(
                modell_sti, apply_ocr=False
            )
            self._layoutlm_model = LayoutLMv3ForTokenClassification.from_pretrained(
                modell_sti, num_labels=6, ignore_mismatched_sizes=True,
                dtype=torch.float16,
            )
            self._layoutlm_model.to(GPU_ENHET)
            self._layoutlm_model.eval()
            self._layoutlmv3_available = True
            logger.info("LayoutLMv3 lastet.")
        except Exception as exc:
            logger.warning("LayoutLMv3 lasting feilet: %s", exc)

        try:
            from transformers import (
                AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig,
            )
            borealis_sti = f"{MODELLER_STI}/{CONFIG['modeller']['borealis']}"
            self._borealis_tokenizer = AutoTokenizer.from_pretrained(borealis_sti)
            # 4-bit NF4: ~2.6 GB i stedet for ~8 GB — nødvendig for at
            # 4B-modellen skal dele GPU med LayoutLMv3 og NB-BERT.
            kvantisering = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
            )
            self._borealis_model = AutoModelForCausalLM.from_pretrained(
                borealis_sti, quantization_config=kvantisering,
                device_map=GPU_ENHET, attn_implementation="eager",
            )
            self._borealis_model.eval()
            self._borealis_available = True
            logger.info("Borealis (LLM) lastet.")
        except Exception as exc:
            logger.warning("Borealis lasting feilet: %s", exc)

        try:
            from transformers import pipeline
            self._nb_bert_pipeline = pipeline(
                "ner", model=f"{MODELLER_STI}/{CONFIG['modeller']['nb_bert_ner']}",
                aggregation_strategy="simple",
                device=GPU_ENHET, torch_dtype=torch.float16,
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
        # Deterministisk lag: sjekksum-/mønsterfelter (fnr, konto, dato,
        # telefon, e-post, beløp, saksnr, kontor, postnr) — matematikk
        # slår gjetning for strukturerte felter.
        entiteter = utvid_entiteter(tekst, entiteter)
        entiteter = self._ordne_entiteter(entiteter)
        ytelse = entiteter.get("ytelse") or ytelse

        utfall = self._bestem_utfall(entiteter, tekst)
        oppsummering = self._lag_oppsummering(entiteter, dokklasse, utfall)

        validering = self._valider(entiteter, dokklasse)
        anomali = self._sjekk_anomali(entiteter, validering)

        # Kryssvalidering (kun hvis aktivert)
        if CONFIG["lag"].get("lag5_kryssvalidering", False):
            anomali.update(self._kryssvalider(entiteter))

        if not validering["gyldig"] or anomali.get("har_anomali"):
            project_id = CONFIG["label_studio"]["prosjekter"]["validering"]
            self.send_til_label_studio(
                job_id=job_id,
                image_path=job.get("fil_sti", ""),
                ocr_text=tekst,
                project_id=project_id,
                stage="validering",
            )

        return NLPResultat(
            job_id=job_id,
            entities=entiteter,
            document_class=dokklasse,
            ytelse=ytelse,
            utfall=utfall,
            summary=oppsummering,
            nlp_confidence=round(nlp_konfidens, 4),
            nlp_model_used=modell,
            validation=ValideringsResultat(**validering),
            anomaly=AnomalyResultat(**anomali),
            ocr_confidence=round(ocr_konfidens, 4),
        ).model_dump()

    # ------------------------------------------------------------------ #
    #  NLP-motor-routing                                                   #
    # ------------------------------------------------------------------ #

    def _ekstraher(self, tekst, tokens, bokser, dokumenttype, bilde_sti=""):
        # Borealis (LLM) gjør åpen feltuttrekking — den generelle motoren
        # som finner alle felter dokumentet faktisk inneholder.
        # LayoutLMv3 krever et finjustert klassifiseringshode og brukes
        # kun når LLM-en ikke er tilgjengelig.
        if len(tekst) > 200 and self._borealis_available:
            return self._borealis(tekst)
        har_layout = bool(tokens) and bool(bokser)
        if dokumenttype in (TRYKT, TABELL) and har_layout and self._layoutlmv3_available:
            return self._layoutlmv3(bilde_sti, tokens, bokser, tekst)
        return self._nb_bert(tekst)

    # Kanoniske nøkler — brukes i prompten og for å ordne resultatet.
    # Alt annet dokumentet inneholder trekkes ut med beskrivende nøkler.
    _KANONISKE_FELT = [
        "navn", "fodselsnummer", "dato", "adresse", "postnummer", "poststed",
        "telefon", "epost", "fylke", "ytelse", "saksnummer", "kontornavn",
        "belop", "kontonummer", "organisasjon",
    ]
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
            prompt = (
                "Du analyserer et dokument. Trekk ut ALLE viktige felter du "
                "finner i teksten under, som ETT flatt JSON-objekt.\n"
                "- Bruk beskrivende norske nøkler i snake_case "
                "(f.eks. ordrenummer, butikk, total_belop, betalingsmetode).\n"
                "- Bruk disse kanoniske nøklene når feltet finnes: "
                + ", ".join(self._KANONISKE_FELT) + ".\n"
                "- Ta også med nøkkelen dokumenttype: en kort kategori som "
                "brev, vedtak, faktura, kvittering, ordrebekreftelse, soknad.\n"
                "- Ta KUN med felter som faktisk står i teksten — ikke gjett, "
                "og utelat felter som mangler.\n"
                "- Svar KUN med JSON-objektet, ingen annen tekst.\n\n"
                f"Dokument:\n{tekst[:3000]}\n\nJSON:"
            )
            innganger = self._borealis_tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}],
                add_generation_prompt=True, return_tensors="pt", return_dict=True,
            ).to(GPU_ENHET)
            with torch.no_grad():
                utgang = self._borealis_model.generate(
                    **innganger, max_new_tokens=512, do_sample=False,
                    pad_token_id=self._borealis_tokenizer.eos_token_id,
                )
            inn_lengde = innganger["input_ids"].shape[-1]
            svar = self._borealis_tokenizer.decode(
                utgang[0][inn_lengde:], skip_special_tokens=True
            )
            entiteter = self._parse_borealis_json(svar)
            dokklasse = entiteter.pop("dokumenttype", None) or "brev"
            return entiteter, dokklasse, entiteter.get("ytelse"), 0.87, "borealis"
        except Exception as exc:
            logger.warning("Borealis feilet: %s — bruker NB-BERT", exc)
            return self._nb_bert(tekst)

    def _parse_borealis_json(self, svar: str) -> dict:
        """Åpen parsing: alle nøkler beholdes (normalisert til snake_case),
        nøstede objekter flates ut, lister slås sammen. Tomme verdier
        forkastes. Maks 40 felter — mot runaway-generering."""
        treff = re.search(r"\{.*\}", svar, re.DOTALL)
        if not treff:
            return {}
        try:
            rådata = json.loads(treff.group(0))
        except json.JSONDecodeError:
            return {}
        if not isinstance(rådata, dict):
            return {}

        def _norm_nokkel(k) -> str:
            k = str(k).strip().lower().replace(" ", "_").replace("-", "_")
            return re.sub(r"[^a-z0-9æøå_]", "", k)

        entiteter: dict = {}
        for k, v in rådata.items():
            if len(entiteter) >= 40:
                break
            nokkel = _norm_nokkel(k)
            if not nokkel or v in (None, "", "null", [], {}):
                continue
            if isinstance(v, dict):
                for uk, uv in v.items():
                    if uv in (None, "", "null") or len(entiteter) >= 40:
                        continue
                    entiteter.setdefault(f"{nokkel}_{_norm_nokkel(uk)}", str(uv).strip())
            elif isinstance(v, list):
                entiteter[nokkel] = ", ".join(
                    str(x).strip() for x in v if x not in (None, "")
                )
            else:
                entiteter[nokkel] = str(v).strip()
        return entiteter

    def _ordne_entiteter(self, entiteter: dict) -> dict:
        """Ordner feltene: kanoniske felter først (i fast rekkefølge),
        deretter dokumentspesifikke felter alfabetisk."""
        kanonisk = {k: entiteter[k] for k in self._KANONISKE_FELT if k in entiteter}
        ovrige = {k: entiteter[k] for k in sorted(entiteter) if k not in kanonisk}
        return {**kanonisk, **ovrige}

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
                # ORG er IKKE automatisk en ytelse: NAV-kontor gjenkjennes
                # på navn, ytelser valideres mot den kanoniske listen i
                # utvid_entiteter — resten lagres som organisasjon.
                if verdi.upper().startswith("NAV"):
                    entiteter.setdefault("kontornavn", verdi)
                else:
                    entiteter.setdefault("organisasjon", verdi)
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
        return er_gyldig_fnr(fnr)

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

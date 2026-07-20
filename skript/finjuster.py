"""
Finjustering av OCR- og NLP-modeller (TrOCR, NB-BERT, LayoutLMv3).

Kjøres MANUELT: `make finjuster` (eller via KFP-treningspipelinen).
Det finnes INGEN automatisk utløser på korreksjonsantall eller tid i
koden — den tidligere påstanden om «automatisk etter 500 korreksjoner
eller 90 dager» var aldri implementert (verifisert 2026-07-20). Ønskes
det, må en cron/recurring-run settes opp eksplisitt.
"""
import os
import json
import shutil
import torch
from pathlib import Path
from datetime import datetime
from PIL import Image
from torch.utils.data import Dataset, DataLoader

FINJUSTERING_STI = os.environ.get("FINJUSTERING_STI", "./data/finjustering")
MODELLER_STI = os.environ.get("MODELLER_STI", "./modeller")
MIN_EKSEMPLER = 10


class TrOCRDatasett(Dataset):
    def __init__(self, oppforinger: list, prosessor):
        self.oppforinger = oppforinger
        self.prosessor = prosessor

    def __len__(self):
        return len(self.oppforinger)

    def __getitem__(self, idx):
        oppf = self.oppforinger[idx]
        bilde_sti = oppf.get("fil_sti", "")
        tekst = oppf.get("tekst", "")
        try:
            bilde = Image.open(bilde_sti).convert("RGB")
        except Exception:
            bilde = Image.new("RGB", (224, 224), color=255)
        piksel = self.prosessor(images=bilde, return_tensors="pt").pixel_values.squeeze(0)
        etiketter = self.prosessor.tokenizer(
            tekst, return_tensors="pt", padding="max_length",
            max_length=128, truncation=True
        ).input_ids.squeeze(0)
        etiketter[etiketter == self.prosessor.tokenizer.pad_token_id] = -100
        return {"pixel_values": piksel, "labels": etiketter}


def finjuster_norhand():
    from transformers import (
        TrOCRProcessor, VisionEncoderDecoderModel,
        Seq2SeqTrainer, Seq2SeqTrainingArguments
    )

    print("Starter finjustering av TrOCR-NorHand...")

    korreksjoner = []
    for fil in Path(FINJUSTERING_STI).glob("trocr_*.json"):
        with open(fil, encoding="utf-8") as f:
            korreksjoner.extend(json.load(f))

    if len(korreksjoner) < MIN_EKSEMPLER:
        print(f"For få korreksjoner ({len(korreksjoner)}) — minimum {MIN_EKSEMPLER} nødvendig.")
        return

    print(f"Finjusterer med {len(korreksjoner)} eksempler...")

    modell_sti = f"{MODELLER_STI}/norhand"
    prosessor = TrOCRProcessor.from_pretrained(modell_sti)
    modell = VisionEncoderDecoderModel.from_pretrained(modell_sti)

    modell.config.decoder_start_token_id = prosessor.tokenizer.cls_token_id
    modell.config.pad_token_id = prosessor.tokenizer.pad_token_id

    datasett = TrOCRDatasett(korreksjoner, prosessor)

    treningsarg = Seq2SeqTrainingArguments(
        output_dir=f"{MODELLER_STI}/norhand-finjustert",
        num_train_epochs=3,
        per_device_train_batch_size=4,
        learning_rate=5e-5,
        warmup_steps=50,
        save_strategy="epoch",
        predict_with_generate=True,
        fp16=torch.cuda.is_available(),
        logging_steps=10,
        report_to="none",
    )

    trener = Seq2SeqTrainer(
        model=modell,
        args=treningsarg,
        train_dataset=datasett,
    )
    # Backup før overskrivning
    backup_sti = f"{MODELLER_STI}/norhand-backup-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if Path(f"{MODELLER_STI}/norhand").exists():
        shutil.copytree(f"{MODELLER_STI}/norhand", backup_sti)
        print(f"Backup lagret: {backup_sti}")

    trener.train()
    trener.save_model(f"{MODELLER_STI}/norhand")
    print(f"TrOCR-NorHand finjustering fullført — {len(korreksjoner)} eksempler.")


def finjuster_nb_bert():
    from transformers import (
        AutoTokenizer, AutoModelForSequenceClassification,
        Trainer, TrainingArguments
    )

    print("Starter finjustering av NB-BERT...")

    korreksjoner = []
    for fil in Path(FINJUSTERING_STI).glob("nb_bert_*.json"):
        with open(fil, encoding="utf-8") as f:
            korreksjoner.extend(json.load(f))

    if len(korreksjoner) < MIN_EKSEMPLER:
        print(f"For få NB-BERT-korreksjoner ({len(korreksjoner)}) — hopper over.")
        return

    etiketter = sorted(set(k["etikett"] for k in korreksjoner))
    etikett_til_id = {e: i for i, e in enumerate(etiketter)}

    modell_sti = f"{MODELLER_STI}/nb-bert"
    tokenizer = AutoTokenizer.from_pretrained(modell_sti)
    modell = AutoModelForSequenceClassification.from_pretrained(
        modell_sti, num_labels=len(etiketter)
    )

    class NbBertDatasett(Dataset):
        def __init__(self, data):
            self.data = data

        def __len__(self):
            return len(self.data)

        def __getitem__(self, idx):
            oppf = self.data[idx]
            tokens = tokenizer(
                oppf["tekst"][:512], truncation=True,
                padding="max_length", max_length=512, return_tensors="pt"
            )
            return {
                "input_ids": tokens["input_ids"].squeeze(0),
                "attention_mask": tokens["attention_mask"].squeeze(0),
                "labels": torch.tensor(etikett_til_id[oppf["etikett"]], dtype=torch.long),
            }

    datasett = NbBertDatasett(korreksjoner)
    treningsarg = TrainingArguments(
        output_dir=f"{MODELLER_STI}/nb-bert-finjustert",
        num_train_epochs=3,
        per_device_train_batch_size=8,
        learning_rate=2e-5,
        save_strategy="epoch",
        fp16=torch.cuda.is_available(),
        logging_steps=10,
        report_to="none",
    )
    # Backup før overskrivning
    backup_sti = f"{MODELLER_STI}/nb-bert-backup-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if Path(f"{MODELLER_STI}/nb-bert").exists():
        shutil.copytree(f"{MODELLER_STI}/nb-bert", backup_sti)
        print(f"Backup lagret: {backup_sti}")

    trener = Trainer(model=modell, args=treningsarg, train_dataset=datasett)
    trener.train()
    trener.save_model(f"{MODELLER_STI}/nb-bert")
    print(f"NB-BERT finjustering fullført — {len(korreksjoner)} eksempler.")


def finjuster_layoutlmv3():
    from transformers import (
        LayoutLMv3Processor, LayoutLMv3ForTokenClassification,
        Trainer, TrainingArguments
    )

    print("Starter finjustering av LayoutLMv3...")

    treningsfiler = list(Path(FINJUSTERING_STI).glob("layoutlmv3_*.json"))
    alle_data = []
    for fil in treningsfiler:
        with open(fil, encoding="utf-8") as f:
            alle_data.extend(json.load(f))

    if len(alle_data) < MIN_EKSEMPLER:
        print(f"For få LayoutLMv3-eksempler ({len(alle_data)}) — minimum {MIN_EKSEMPLER} nødvendig.")
        print("Kjør 'make lag-datasett' og annotter i Label Studio, deretter 'make konverter-annotasjoner'.")
        return

    print(f"Finjusterer LayoutLMv3 med {len(alle_data)} eksempler...")

    # 6 flate etiketter — samme som konverter_til_layoutlmv3.py og nlp/hoved.py
    ANTALL_ETIKETTER = 6

    modell_sti = f"{MODELLER_STI}/layoutlmv3"
    prosessor = LayoutLMv3Processor.from_pretrained(modell_sti, apply_ocr=False)
    modell = LayoutLMv3ForTokenClassification.from_pretrained(
        modell_sti, num_labels=ANTALL_ETIKETTER, ignore_mismatched_sizes=True
    )

    class LayoutLMDatasett(Dataset):
        def __init__(self, data):
            self.data = data

        def __len__(self):
            return len(self.data)

        def __getitem__(self, idx):
            oppf = self.data[idx]
            try:
                bilde = Image.open(oppf["bilde_sti"]).convert("RGB")
            except Exception:
                bilde = Image.new("RGB", (224, 224), color=255)

            koding = prosessor(
                bilde,
                text=oppf["tokens"],
                boxes=oppf["bokser"],
                word_labels=oppf["etiketter"],
                return_tensors="pt",
                truncation=True,
                padding="max_length",
                max_length=512,
            )
            return {k: v.squeeze(0) for k, v in koding.items()}

    datasett = LayoutLMDatasett(alle_data)

    treningsarg = TrainingArguments(
        output_dir=f"{MODELLER_STI}/layoutlmv3-finjustert",
        num_train_epochs=5,
        per_device_train_batch_size=2,
        learning_rate=5e-5,
        warmup_steps=50,
        save_strategy="epoch",
        fp16=torch.cuda.is_available(),
        logging_steps=10,
        report_to="none",
    )

    backup_sti = f"{MODELLER_STI}/layoutlmv3-backup-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if Path(modell_sti).exists():
        shutil.copytree(modell_sti, backup_sti)
        print(f"Backup lagret: {backup_sti}")

    trener = Trainer(model=modell, args=treningsarg, train_dataset=datasett)
    trener.train()
    trener.save_model(modell_sti)
    print(f"LayoutLMv3 finjustering fullført — {len(alle_data)} eksempler.")


if __name__ == "__main__":
    finjuster_norhand()
    finjuster_nb_bert()
    finjuster_layoutlmv3()
    print("Alle modeller oppdatert.")

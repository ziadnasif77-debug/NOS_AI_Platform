"""
Periodisk finjustering av OCR- og NLP-modeller.
Kjøres automatisk etter 500 korreksjoner eller 90 dager.
"""
import os
import json
import torch
from pathlib import Path
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
    trener = Trainer(model=modell, args=treningsarg, train_dataset=datasett)
    trener.train()
    trener.save_model(f"{MODELLER_STI}/nb-bert")
    print(f"NB-BERT finjustering fullført — {len(korreksjoner)} eksempler.")


if __name__ == "__main__":
    finjuster_norhand()
    finjuster_nb_bert()
    print("Alle modeller oppdatert.")

"""
Finjustering av håndskriftmodellen (TrOCR-NorHand) på menneskelige
korreksjoner fra Label Studio.

Kjøres MANUELT (`make finjuster`) eller via orkestratoren
`kjor_treningslop.py` (som også sporer løpet i MLflow). Det finnes INGEN
automatisk utløser på korreksjonsantall eller tid i koden — ønskes det,
planlegg kjøringen med Windows Task Scheduler.

Bare norhand trenes her, fordi det er den eneste trente modellen serveren
faktisk bruker. Tidligere trente denne fila også NB-BERT (dokumenttype)
og LayoutLMv3 (layout) — modeller ingenting i leseløypa kalte. De er
fjernet (2026-07-21).

Miljøvariabel TRENING_RAPPORT styrer Hugging Face-loggingen:
  "none" (standard) eller "mlflow" (settes av kjor_treningslop.py).
"""
import os
import json
import shutil
import torch
from pathlib import Path
from PIL import Image
from torch.utils.data import Dataset

FINJUSTERING_STI = os.environ.get("FINJUSTERING_STI", "./data/finjustering")
MODELLER_STI = os.environ.get("MODELLER_STI", "./modeller")
MIN_EKSEMPLER = 10
# "none" | "mlflow" — Hugging Face-trenerens rapportering. Orkestratoren
# setter "mlflow" så treningstap havner i samme MLflow-løp.
TRENING_RAPPORT = os.environ.get("TRENING_RAPPORT", "none")


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
        # R-fiks 2026-07-20: FEIL høylytt i stedet for å trene på et
        # blankt hvitt bilde. Den gamle stille fallbacken gjorde at en
        # ødelagt bildesti ga TrOCR-trening på tomme bilder — verre enn
        # ingen trening, for den forgifter modellen uten et eneste spor.
        try:
            bilde = Image.open(bilde_sti).convert("RGB")
        except Exception as feil:
            raise RuntimeError(
                f"Kan ikke åpne treningsbildet «{bilde_sti}» "
                f"(oppføring {idx}): {feil}. Sjekk at eksporten oversatte "
                "Label Studio-URL-en til en ekte filsti."
            )
        piksel = self.prosessor(images=bilde, return_tensors="pt").pixel_values.squeeze(0)
        etiketter = self.prosessor.tokenizer(
            tekst, return_tensors="pt", padding="max_length",
            max_length=128, truncation=True
        ).input_ids.squeeze(0)
        etiketter[etiketter == self.prosessor.tokenizer.pad_token_id] = -100
        return {"pixel_values": piksel, "labels": etiketter}


def finjuster_norhand() -> int | None:
    """Finjusterer TrOCR-NorHand på trocr_*.json-korreksjonene og lagrer
    resultatet som KANDIDAT (modeller/norhand-kandidat) — ikke live.
    Returnerer antall eksempler den trente på, eller None hvis hoppet
    over (for få korreksjoner)."""
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
        return None

    # R-fiks 2026-07-20: sjekk at bildene FAKTISK finnes før vi starter
    # en lang treningsjobb. Ellers oppdages en ødelagt bildesti først
    # midt i treningen (eller, før fiksen, aldri — den trente på blanke).
    mangler = [k.get("fil_sti", "") for k in korreksjoner
               if not os.path.isfile(k.get("fil_sti", ""))]
    if mangler:
        raise FileNotFoundError(
            f"{len(mangler)} av {len(korreksjoner)} treningsbilder finnes "
            f"ikke på disk (f.eks. «{mangler[0]}»). Kjør "
            "eksporter_fra_label_studio.py på nytt — den oversetter nå "
            "Label Studio-URL-er til ekte filstier. Avbryter for å unngå "
            "trening på blanke bilder."
        )

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
        report_to=TRENING_RAPPORT,
    )

    trener = Seq2SeqTrainer(
        model=modell,
        args=treningsarg,
        train_dataset=datasett,
    )
    trener.train()

    # Lagre som KANDIDAT — ikke live. Kvalitetsporten (valider_modell.py)
    # avgjør om den er god nok til å promoteres. Slik kan en dårlig
    # korreksjonsbatch aldri stille forringe produksjonsmodellen.
    kandidat = f"{MODELLER_STI}/norhand-kandidat"
    if Path(kandidat).exists():
        shutil.rmtree(kandidat)
    trener.save_model(kandidat)
    prosessor.save_pretrained(kandidat)   # så kandidaten kan lastes selvstendig
    print(f"TrOCR-NorHand finjustering fullført — {len(korreksjoner)} eksempler.")
    print(f"Kandidat lagret: {kandidat} (IKKE live ennå — porten avgjør).")
    return len(korreksjoner)


if __name__ == "__main__":
    finjuster_norhand()
    print("Kandidat klar. Kjør 'python skript/valider_modell.py' for å "
          "sjekke den mot live før promotering (eller 'make trening' som "
          "gjør alt i ett).")

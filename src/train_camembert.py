"""
train_camembert.py
Étape C du guide : fine-tune CamemBERT sur data/dataset.csv pour classifier
les textes en C1/C2/C3/C4.

Le modèle apprend UNIQUEMENT à partir du texte et du label (colonne "label").
La colonne "categorie" du dataset (issue de la cartographie, taxonomy.py)
n'est PAS utilisée comme entrée d'entraînement ici : elle sert uniquement
en aval, au moment du scoring (voir scoring.py), pour nuancer le score une
fois que l'IA a déjà décidé de la classe. Le modèle n'apprend donc bien
qu'à reconnaître les documents à partir de leur contenu, pas de règles.

Prérequis :
    - data/dataset.csv existe (colonnes: texte, categorie, label) -> generate_dataset.py
    - pip install transformers torch scikit-learn pandas accelerate

Usage :
    python src/train_camembert.py

Résultat :
    - modèle fine-tuné sauvegardé dans models/camembert_dlp/
    - ce modèle peut ensuite être chargé par CamembertClassifier
      (voir classification.py) à la place de classify_demo_without_model()
"""

from pathlib import Path

import pandas as pd
import torch
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import accuracy_score, classification_report, f1_score
from transformers import (
    CamembertTokenizer,
    CamembertForSequenceClassification,
    Trainer,
    TrainingArguments,
)

LABELS = ["C1", "C2", "C3", "C4"]
LABEL2ID = {label: i for i, label in enumerate(LABELS)}
ID2LABEL = {i: label for i, label in enumerate(LABELS)}

BASE_DIR = Path(__file__).resolve().parent.parent
DATASET_PATH = BASE_DIR / "data" / "dataset.csv"
MODEL_OUTPUT_DIR = BASE_DIR / "models" / "camembert_dlp"


class DLPDataset(torch.utils.data.Dataset):
    def __init__(self, encodings, labels):
        self.encodings = encodings
        self.labels = labels

    def __getitem__(self, idx):
        item = {k: v[idx] for k, v in self.encodings.items()}
        item["labels"] = torch.tensor(self.labels[idx])
        return item

    def __len__(self):
        return len(self.labels)


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    predictions = logits.argmax(axis=-1)
    return {
        "accuracy": accuracy_score(labels, predictions),
        "macro_f1": f1_score(labels, predictions, average="macro", zero_division=0),
    }


def split_by_document_type(df: pd.DataFrame):
    """Hold out complete document types to avoid template leakage.

    A random row split lets near-identical generated templates appear in both
    train and validation sets, producing misleadingly perfect scores.
    """
    for seed in range(42, 142):
        splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
        train_idx, val_idx = next(splitter.split(df, groups=df["type_document"]))
        train, validation = df.iloc[train_idx], df.iloc[val_idx]
        if set(train["label_id"]) == set(LABEL2ID.values()) and set(validation["label_id"]) == set(LABEL2ID.values()):
            return train, validation
    raise ValueError("Impossible de créer une validation par type de document couvrant C1 à C4.")


def main():
    print("1. Chargement du dataset...")
    df = pd.read_csv(DATASET_PATH)
    df["label_id"] = df["label"].map(LABEL2ID)

    if "type_document" not in df.columns:
        raise ValueError("Le dataset doit contenir la colonne type_document pour une validation fiable.")
    train_df, val_df = split_by_document_type(df)
    train_texts, val_texts = train_df["texte"].tolist(), val_df["texte"].tolist()
    train_labels, val_labels = train_df["label_id"].tolist(), val_df["label_id"].tolist()
    print(f"   -> {len(train_texts)} exemples train / {len(val_texts)} exemples validation")

    print("2. Chargement du tokenizer et du modèle CamemBERT de base...")
    tokenizer = CamembertTokenizer.from_pretrained("camembert-base")
    model = CamembertForSequenceClassification.from_pretrained(
        "camembert-base",
        num_labels=len(LABELS),
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )

    print("3. Tokenisation...")
    train_encodings = tokenizer(train_texts, truncation=True, padding=True, max_length=512)
    val_encodings = tokenizer(val_texts, truncation=True, padding=True, max_length=512)

    train_dataset = DLPDataset(
        {k: torch.tensor(v) for k, v in train_encodings.items()}, train_labels
    )
    val_dataset = DLPDataset(
        {k: torch.tensor(v) for k, v in val_encodings.items()}, val_labels
    )

    print("4. Configuration de l'entraînement...")
    training_args = TrainingArguments(
        output_dir=str(BASE_DIR / "models" / "checkpoints"),
        num_train_epochs=4,
        per_device_train_batch_size=8,
        per_device_eval_batch_size=8,
        eval_strategy="epoch",
        save_strategy="epoch",
        logging_dir=str(BASE_DIR / "models" / "logs"),
        logging_steps=10,
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        greater_is_better=True,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        compute_metrics=compute_metrics,
    )

    print("5. Entraînement (fine-tuning)...")
    trainer.train()

    print("6. Évaluation finale...")
    predictions = trainer.predict(val_dataset)
    preds = predictions.predictions.argmax(axis=-1)
    report = classification_report(val_labels, preds, target_names=LABELS)
    print(report)

    print(f"7. Sauvegarde du modèle dans {MODEL_OUTPUT_DIR} ...")
    MODEL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(MODEL_OUTPUT_DIR)
    tokenizer.save_pretrained(MODEL_OUTPUT_DIR)

    # Sauvegarde du rapport textuel
    with open(MODEL_OUTPUT_DIR / "classification_report.txt", "w", encoding="utf-8") as f:
        f.write(report)

    # Génération et sauvegarde de la matrice de confusion
    try:
        import matplotlib.pyplot as plt
        import seaborn as sns
        from sklearn.metrics import confusion_matrix

        cm = confusion_matrix(val_labels, preds)
        plt.figure(figsize=(6, 5))
        sns.heatmap(cm, annot=True, fmt="d", cmap="Blues", xticklabels=LABELS, yticklabels=LABELS)
        plt.ylabel("Vrai Label")
        plt.xlabel("Label Prédit")
        plt.title("Matrice de Confusion - CamemBERT DLP")
        plt.tight_layout()

        cm_path = MODEL_OUTPUT_DIR / "confusion_matrix.png"
        plt.savefig(cm_path, dpi=150)
        plt.close()
        print(f"   -> Matrice de confusion sauvegardée sous : {cm_path}")
    except Exception as e:
        print(f"Erreur lors de la génération de la matrice de confusion : {e}")

    print("Terminé. Le modèle peut maintenant être chargé via :")
    print(f'   CamembertClassifier(model_path="{MODEL_OUTPUT_DIR}")')


if __name__ == "__main__":
    main()

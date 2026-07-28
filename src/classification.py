"""
classification.py (v3)
Étape 2 du pipeline DLP : classifier un texte selon son niveau de confidentialité
(C1 Public, C2 Interne, C3 Confidentiel, C4 Hautement Confidentiel).

Principe directeur :
    La classe de confidentialité (C1-C4) est déterminée par le modèle
    CamemBERT entraîné. Des garde-fous explicites, conservateurs et traçables
    peuvent uniquement promouvoir un contenu dont la criticité C4 est prouvée ;
    ils ne peuvent jamais abaisser la décision du modèle.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from taxonomy import CATEGORIES


@dataclass
class ClassificationResult:
    level: str
    confidence: float
    category: str = "Indeterminee"
    entities_found: list = field(default_factory=list)
    safeguards: list = field(default_factory=list)


class CamembertClassifier:
    """Modèle CamemBERT fine-tuné pour la classification à 4 classes (C1-C4)."""

    LABELS = ["C1", "C2", "C3", "C4"]

    def __init__(self, model_path: str):
        from transformers import CamembertTokenizer, CamembertForSequenceClassification
        import torch

        self.torch = torch
        self.tokenizer = CamembertTokenizer.from_pretrained(model_path)
        self.model = CamembertForSequenceClassification.from_pretrained(model_path)
        self.model.eval()

    def predict(self, text: str) -> ClassificationResult:
        # CamemBERT can only process a bounded passage.  Average several
        # overlapping passages instead of silently using only the first page.
        chunks = _text_chunks(text)
        probabilities = []
        with self.torch.no_grad():
            for chunk in chunks:
                inputs = self.tokenizer(chunk, return_tensors="pt", truncation=True, max_length=512)
                outputs = self.model(**inputs)
                probabilities.append(self.torch.softmax(outputs.logits, dim=1)[0])
            probs = self.torch.stack(probabilities).mean(dim=0)
        predicted_idx = int(self.torch.argmax(probs))
        confidence = float(probs[predicted_idx])

        level = self.LABELS[predicted_idx]
        safeguards = _high_risk_guardrails(text)
        # The ML model remains the primary classifier.  These narrowly scoped
        # safeguards prevent a clearly evidenced C4 document from being
        # downgraded because the model has not seen its exact wording yet.
        # This is intentionally a one-way promotion: a rule can never lower
        # the model's classification.
        if safeguards:
            level = "C4"
        return ClassificationResult(
            level=level,
            confidence=round(confidence, 3),
            category=detect_category(text),
            entities_found=count_sensitive_entities(text),
            safeguards=safeguards,
        )


def _text_chunks(text: str, size: int = 1800, overlap: int = 300, max_chunks: int = 8) -> list[str]:
    """Create bounded, overlapping passages while preserving short texts."""
    text = text.strip()
    if len(text) <= size:
        return [text or " "]
    chunks, start = [], 0
    while start < len(text) and len(chunks) < max_chunks:
        end = min(len(text), start + size)
        if end < len(text):
            boundary = max(text.rfind("\n", start, end), text.rfind(" ", start, end))
            if boundary > start + size // 2:
                end = boundary
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


CATEGORY_KEYWORDS = {
    "Medicale": [
        "médical", "medecin", "médecin", "santé", "arrêt de travail", "arrêt maladie",
        "secret médical", "maladie", "certificat médical", "ordonnance", "diagnostic",
        "cnam", "mutuelle", "incapacité", "hospitalisation", "patient", "prescription",
        "compte-rendu médical", "dossier médical", "clinique", "hôpital",
    ],
    "Finance": [
        "iban", "rib", "facture", "paiement", "budget", "rémunération", "salaire",
        "montant", "bancaire", "tnd", "dinars", "dinar", "prélèvement", "attestation bancaire",
    ],
    "RH": [
        "contrat de travail", "service rh", "collaborateur", "note de service",
        "planning", "réunion d'équipe", "bulletin de paie", "embauche",
    ],
    "Juridique": [
        "contrat", "litige", "avocat", "juridique", "contentieux",
        "propriété intellectuelle", "procédure judiciaire",
    ],
    "Strategique": [
        "fusion", "acquisition", "restructuration", "comité exécutif",
        "stratégique", "rapprochement", "négociation",
    ],
    "Personnelles": [
        "données personnelles", "coordonnées", "client", "identité", "rgpd",
        "cin", "assuré", "sinistre", "police n°", "fiche client",
    ],
    "Publique": [
        "communiqué de presse", "site web", "offre d'emploi", "public", "carrière",
    ],
}


def _normalise(text: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(char))


def _occurrences(text: str, phrase: str) -> int:
    return len(re.findall(r"(?<!\\w)" + re.escape(phrase) + r"(?!\\w)", text))


# Strong contextual indicators deliberately outweigh generic terms such as
# "montant" and "TND", which can occur in a medical reimbursement or case.
CATEGORY_WEIGHTS = {
    "Medicale": {"certificat medical": 6, "ordonnance": 6, "secret medical": 6, "dossier medical": 6, "compte rendu medical": 6, "resultat d analyse": 5, "bilan biologique": 5, "imagerie medicale": 5, "diagnostic": 4, "patient": 3, "cnam": 4, "mutuelle": 4, "arret maladie": 6, "arret de travail": 5, "incapacite temporaire": 5, "hospitalisation": 5, "sante": 3, "maladie": 3, "medecin": 3, "pharmacien": 3, "hopital": 3, "clinique": 3},
    "Strategique": {"fusion": 6, "acquisition": 6, "restructuration": 6, "comite executif": 5, "conseil d administration": 5, "secret d affaires": 6, "appel d offres": 3, "strategique": 4, "rapprochement": 5, "negociation": 3, "due diligence": 5},
    "Juridique": {"litige": 5, "contentieux": 5, "procedure judiciaire": 6, "mise en demeure": 5, "assignation": 5, "avocat": 4, "juridique": 3, "propriete intellectuelle": 5, "contrat": 2},
    "RH": {"contrat de travail": 5, "bulletin de paie": 5, "evaluation annuelle": 4, "dossier disciplinaire": 5, "service rh": 4, "note de service": 4, "planning": 3, "embauche": 4, "collaborateur": 2},
    "Finance": {"iban": 6, "rib": 6, "attestation bancaire": 5, "coordonnees bancaires": 5, "carte bancaire": 5, "facture": 4, "prelevement": 4, "bancaire": 3, "budget": 3, "remuneration": 4, "salaire": 3, "montant": 0.5, "tnd": 0.5, "dinar": 0.5, "dinars": 0.5, "paiement": 2},
    "Personnelles": {"donnees personnelles": 5, "fiche client": 5, "rgpd": 4, "identite": 3, "adresse postale": 3, "date de naissance": 3, "coordonnees": 2, "assure": 3, "sinistre": 3, "police": 2, "client": 1},
    "Publique": {"communique de presse": 5, "site web": 4, "offre d'emploi": 5, "grand public": 3, "carriere": 2},
}


HIGH_RISK_SIGNAL_SETS = {
    "medical": {
        "certificat medical", "ordonnance", "secret medical", "dossier medical",
        "compte rendu medical", "resultat d analyse", "bilan biologique",
        "imagerie medicale", "diagnostic", "hospitalisation", "incapacite temporaire",
        "arret de travail", "arret maladie", "prescription", "patient",
    },
    "strategic": {
        "fusion", "acquisition", "restructuration", "secret d affaires",
        "due diligence", "conseil d administration", "comite executif",
    },
    "executive_finance": {"remuneration", "package de remuneration", "dirigeant", "comite executif", "conseil d administration"},
    "major_legal": {"litige", "contentieux", "procedure judiciaire", "assignation", "mise en demeure", "secret professionnel"},
}


def is_blank_template_or_non_sensitive(text: str) -> bool:
    normalized = _normalise(text)
    # Check for blank templates first (contains placeholders like "[nom", "[prenom", "[cin", "[iban", "[insérer", "[________________]", "pol-xxxxxx", "sin-xxxxxxx", "template de", "modele de")
    has_template_markers = any(marker in normalized for marker in [
        "[nom", "[prenom", "[cin", "[iban", "[inserer", "[________________]", "pol-xxxxxx", "sin-xxxxxxx", "template de", "modele de"
    ]) or "____" in normalized
    
    if has_template_markers:
        # If it has template markers and no sensitive entities like actual email/tel/cin/iban, it's a counter-example
        if not count_sensitive_entities(text):
            return True
            
    # Check for general public information (newsletters, guides, privacy policies)
    has_public_markers = any(marker in normalized for marker in [
        "charte de confidentialite", "politique de confidentialite", "newsletter", "guide pratique de l'assure", "bien-etre", "conseils sante", "communique financier"
    ])
    if has_public_markers:
        # If it has public markers and no sensitive entities, it's a counter-example
        if not count_sensitive_entities(text):
            return True

    # Meeting scheduling counter-example
    if "reunion" in normalized or "planning" in normalized or "planifier" in normalized:
        # If it has no sensitive entities, and doesn't contain high-risk terms (like fusion, acquisition, secret medical, restructuration, etc.)
        if not count_sensitive_entities(text) and not any(kw in normalized for kw in [
            "fusion", "acquisition", "restructuration", "secret medical", "bulletin de paie", "remuneration"
        ]):
            return True
            
    return False


def _high_risk_guardrails(text: str) -> list[str]:
    """Return explicit C4 evidence, never a speculative keyword-only match."""
    if is_blank_template_or_non_sensitive(text):
        return []
    normalized = _normalise(text)
    medical_matches = [term for term in HIGH_RISK_SIGNAL_SETS["medical"] if _occurrences(normalized, term)]
    strategic_matches = [term for term in HIGH_RISK_SIGNAL_SETS["strategic"] if _occurrences(normalized, term)]
    safeguards = []
    # A unique health-document signal, or two independent medical signals,
    # is sufficient evidence to request the strictest POC handling.
    unique_medical = {"certificat medical", "ordonnance", "dossier medical", "secret medical", "compte rendu medical", "bilan biologique", "imagerie medicale"}
    if unique_medical.intersection(medical_matches) or len(medical_matches) >= 2:
        safeguards.append("C4 santé : preuve médicale explicite")
    if len(strategic_matches) >= 2:
        safeguards.append("C4 stratégie : information stratégique explicite")
    executive_matches = [term for term in HIGH_RISK_SIGNAL_SETS["executive_finance"] if _occurrences(normalized, term)]
    if "remuneration" in executive_matches and len(executive_matches) >= 2:
        safeguards.append("C4 finance : rémunération de dirigeant explicite")
    legal_matches = [term for term in HIGH_RISK_SIGNAL_SETS["major_legal"] if _occurrences(normalized, term)]
    if len(legal_matches) >= 2:
        safeguards.append("C4 juridique : contentieux majeur explicite")
    return safeguards


def detect_category(text: str) -> str:
    text_lower = _normalise(text)
    scores = {category: 0.0 for category in CATEGORIES}
    for category, indicators in CATEGORY_WEIGHTS.items():
        for phrase, weight in indicators.items():
            scores[category] += _occurrences(text_lower, phrase) * weight

    entity_categories = {
        "iban_fr": "Finance", "iban_tn": "Finance", "iban": "Finance", "rib_tunisie": "Finance",
        "cin_tunisie": "Personnelles", "email": "Personnelles", "tel_tunisie_local": "Personnelles",
        "tel_tunisie_intl": "Personnelles", "num_sinistre": "Personnelles", "num_police": "Personnelles",
    }
    for entity in count_sensitive_entities(text):
        category = entity_categories.get(entity)
        if category:
            scores[category] += 2

    priority = {"Medicale": 7, "Strategique": 6, "Juridique": 5, "RH": 4, "Finance": 3, "Personnelles": 2, "Publique": 1}
    best_category = max(scores, key=lambda category: (scores[category], priority[category]))
    return best_category if scores[best_category] else "Indeterminee"


ENTITY_PATTERNS = {
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "iban_fr": r"\bFR\d{2}[A-Z0-9]{10,30}\b",
    "iban_tn": r"\bTN\d{2}[A-Z0-9]{10,30}\b",
    "iban": r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b",
    "rib_tunisie": r"\b\d{20}\b",
    "numero_secu": r"\b[12]\d{2}(0[1-9]|1[0-2])\d{2}\d{3}\d{3}(\d{2})?\b",
    "montant": r"\b\d[\d\s]{2,}\s?(€|TND|EUR|dinars?)\b",
    "cin_tunisie": r"\b[01]\d{7}\b",
    "tel_tunisie_local": r"\b(?:2[0-9]|5[0-9]|7[0-9]|9[0-9])\d{6}\b",
    "tel_tunisie_intl": r"(?:\+216|00216)[\s\-.]?(?:2[0-9]|5[0-9]|7[0-9]|9[0-9])[\s\-.]?\d{3}[\s\-.]?\d{3}",
    "matricule_fiscal_tn": r"\b\d{7}\s?[A-Z]\s?/\s?[A-P]\s?/\s?[C-N]\s?/\s?000\b",
    "num_sinistre": r"\bSIN-\d{7}\b",
    "num_police": r"\bPOL-\d{6}\b",
}

ENTITY_DISPLAY = {
    "email": ("#FFF3CD", "#856404", "EMAIL"),
    "iban_fr": ("#F8D7DA", "#721C24", "IBAN FR"),
    "iban_tn": ("#F8D7DA", "#721C24", "IBAN TN"),
    "iban": ("#F8D7DA", "#721C24", "IBAN"),
    "rib_tunisie": ("#FCE4EC", "#880E4F", "RIB TN"),
    "numero_secu": ("#D1ECF1", "#0C5460", "N° SÉCU"),
    "montant": ("#E2E3E5", "#383D41", "MONTANT"),
    "cin_tunisie": ("#FFE8D6", "#A0522D", "CIN TN"),
    "tel_tunisie_local": ("#D4EDDA", "#155724", "TÉL TN"),
    "tel_tunisie_intl": ("#C8E6C9", "#1B5E20", "TÉL +216"),
    "matricule_fiscal_tn": ("#E8D4F7", "#5B108F", "MATR. FISCAL TN"),
    "num_sinistre": ("#FFF9C4", "#F57F17", "SINISTRE"),
    "num_police": ("#E1F5FE", "#0277BD", "POLICE"),
}


def count_sensitive_entities(text: str) -> list:
    found = []
    for name, pattern in ENTITY_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            found.append(name)
    return found


def classify_archive_items(items: list[dict], classifier: CamembertClassifier | None = None) -> tuple[ClassificationResult, list[dict]]:
    """Classify each ZIP member and retain the most sensitive member result."""
    results: list[tuple[dict, ClassificationResult]] = []
    details = []
    for item in items:
        result = classifier.predict(item["text"]) if classifier else classify_demo_without_model(item["text"])
        results.append((item, result))
        details.append({"fichier": item["name"], "niveau": result.level, "categorie": result.category,
                        "confiance": result.confidence, "entites": ", ".join(result.entities_found) or "-"})
    if not results:
        return ClassificationResult("C1", 0.0), details
    rank = {"C1": 1, "C2": 2, "C3": 3, "C4": 4}
    _, selected = max(results, key=lambda pair: (rank[pair[1].level], pair[1].confidence))
    return selected, details


def classify_demo_without_model(text: str) -> ClassificationResult:
    """Mode dégradé sans modèle IA — affiche un avertissement dans le dashboard."""
    text_lower = text.lower()
    safeguards = _high_risk_guardrails(text)
    
    is_counter = is_blank_template_or_non_sensitive(text)
    
    level = "C4" if safeguards else "C1"
    if not safeguards:
        if is_counter:
            if any(kw in text_lower for kw in ["réunion", "planning", "planifier"]):
                level = "C2"
            else:
                level = "C1"
        else:
            if any(kw in text_lower for kw in [
                "comité exécutif", "fusion", "dirigeant", "secret médical",
                "certificat médical", "ordonnance", "dossier médical", "cnam",
                "rapport médical", "médecin conseil",
            ]):
                level = "C4"
            elif any(kw in text_lower for kw in [
                "confidentiel", "contrat", "iban", "rib", "bancaire", "réservé",
                "sinistre", "données personnelles", "cin", "devis", "simulation",
                "cotisation", "souscription", "police", "bulletin de paie",
            ]):
                level = "C3"
            elif any(kw in text_lower for kw in ["interne", "note de service", "réunion", "planning"]):
                level = "C2"

    return ClassificationResult(
        level=level,
        confidence=0.0,
        category=detect_category(text),
        entities_found=count_sensitive_entities(text),
        safeguards=safeguards,
    )


if __name__ == "__main__":
    samples = [
        "Certificat médical — Patient Karim Ben Ali (CIN 01234567), Tél: +216 22 123 456. Diagnostic : lombalgie.",
        "Fiche client COMAR : Ahmed Trabelsi (CIN 09876543, Tél: +216-50-987-654). Police n° POL-123456.",
        "Communiqué de presse : COMAR Assurances lance sa nouvelle gamme à Tunis.",
    ]
    for s in samples:
        r = classify_demo_without_model(s)
        print(f"[DEMO] {r.level} | {r.category} | entités: {r.entities_found}")

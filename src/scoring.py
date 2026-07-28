"""
scoring.py (v2.1)
Étape 3 du pipeline DLP : calculer un score de risque nuancé à partir du
résultat de classification IA.

Barème (bandes de score par niveau, avant nuances) :
    C1 (Public)                 -> base 10  (plage typique 10-40)
    C2 (Interne)                -> base 30  (plage typique 30-60)
    C3 (Confidentiel)           -> base 50  (plage typique 50-80)
    C4 (Hautement confidentiel) -> base 70  (plage typique 70-100)

Le seuil d'alerte est fixé à 70/100 : un document C4 est donc presque
toujours proche ou au-dessus du seuil (cohérent avec son niveau de
criticité), tandis qu'un document C3 cumulant plusieurs facteurs de
risque (catégorie sensible + entités détectées) peut lui aussi franchir
le seuil et déclencher une alerte — ce qui reflète bien qu'au sein d'une
même classe, deux documents n'ont pas nécessairement le même risque réel.

Point clé (retour d'expérience projet) : deux documents classés dans la
MÊME classe (ex: C3) peuvent représenter des niveaux de risque différents.
Le score combine donc :
    1. Un score de base associé au niveau décidé par l'IA (C1 < C2 < C3 < C4)
    2. La confiance du modèle dans sa prédiction (un document ambigu pour
       le modèle est traité avec plus de prudence)
    3. Le poids de risque de la catégorie métier détectée (Médicale/Finance/
       Stratégique pèsent plus lourd que RH/Publique, voir taxonomy.py)
    4. Le nombre d'entités sensibles structurées détectées (IBAN, email...)

La CLASSE (C1-C4) reste décidée uniquement par l'IA (classification.py).
Ce module ne fait que nuancer le score de risque associé à cette classe,
il ne remet jamais en cause la classe elle-même.
"""

from dataclasses import dataclass

from classification import ClassificationResult
from taxonomy import CATEGORY_RISK_WEIGHT


LEVEL_BASE_SCORE = {
    "C1": 10,
    "C2": 30,
    "C3": 50,
    "C4": 70,
}

ENTITY_BONUS_PER_ITEM = 4
ENTITY_BONUS_MAX = 12

ALERT_THRESHOLD = 70  # au-delà de ce score -> alerte déclenchée


@dataclass
class ScoringResult:
    score: int
    level: str
    category: str
    confidence: float
    alert_triggered: bool
    reason: str


def compute_score(classification_result: ClassificationResult) -> ScoringResult:
    base = LEVEL_BASE_SCORE.get(classification_result.level, 0)

    # La confiance du modèle module légèrement le score : un document
    # classé avec une confiance faible (modèle hésitant) est traité avec
    # un peu plus de prudence -> score tiré vers le haut, dans une
    # amplitude limitée pour ne pas dénaturer le niveau de base.
    confidence_adjustment = round((1 - classification_result.confidence) * 8)

    category_weight = CATEGORY_RISK_WEIGHT.get(classification_result.category, 0)

    entity_bonus = min(
        len(classification_result.entities_found) * ENTITY_BONUS_PER_ITEM,
        ENTITY_BONUS_MAX,
    )

    total_score = base + confidence_adjustment + category_weight + entity_bonus
    total_score = max(0, min(total_score, 100))  # borné entre 0 et 100

    alert = total_score >= ALERT_THRESHOLD

    reason = (
        f"Base niveau {classification_result.level} : {base} pts | "
        f"Confiance IA {classification_result.confidence:.0%} (ajust. +{confidence_adjustment}) | "
        f"Catégorie {classification_result.category} (+{category_weight}) | "
        f"{len(classification_result.entities_found)} entité(s) sensible(s) (+{entity_bonus})"
    )

    return ScoringResult(
        score=total_score,
        level=classification_result.level,
        category=classification_result.category,
        confidence=classification_result.confidence,
        alert_triggered=alert,
        reason=reason,
    )


if __name__ == "__main__":
    from classification import classify_demo_without_model

    text_a = "Contrat de travail réservé aux ressources humaines et à l'intéressé."
    text_b = "Enregistrement des coordonnées bancaires du client : IBAN FR7630006000011234567890189, réservé au service Finance."

    for label, text in [("Document A (RH, contrat)", text_a), ("Document B (Finance, IBAN)", text_b)]:
        classification = classify_demo_without_model(text)
        scoring = compute_score(classification)
        print(f"{label} -> niveau {scoring.level}, score {scoring.score}/100, alerte {scoring.alert_triggered}")
        print(f"   {scoring.reason}\n")

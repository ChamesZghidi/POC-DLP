"""
taxonomy.py
Cartographie des données sensibles du projet DLP.

Ce fichier centralise :
  1. Les catégories métier de données sensibles (RH, Finance, Médicale, ...)
  2. Le référentiel "type de document -> catégorie -> niveau de confidentialité
     attendu", utilisé pour CONSTRUIRE le dataset d'entraînement labellisé.
  3. Les poids de risque par catégorie, utilisés par le moteur de scoring
     pour nuancer le score (mais jamais pour décider seul de la classe :
     la classification finale est faite par le modèle IA, pas par ce
     référentiel).

Cette cartographie doit être validée/adaptée avec le RSSI ou le DPO de
l'entreprise avant tout déploiement réel (cf. cahier des charges, section 7).
"""

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# 1. Catégories de données sensibles
# ---------------------------------------------------------------------------

CATEGORIES = {
    "Publique": "Contenu destiné à être diffusé sans restriction (communiqués, site web).",
    "Personnelles": "Données à caractère personnel (identité, coordonnées, CIN, téléphone +216).",
    "RH": "Documents liés à la gestion des ressources humaines (contrats, évaluations, notes internes).",
    "Finance": "Données financières et bancaires (IBAN TN, RIB, factures, budgets, résultats).",
    "Medicale": "Données de santé (certificats médicaux, ordonnances, arrêts maladie, dossiers CNAM).",
    "Juridique": "Contrats, litiges, propriété intellectuelle.",
    "Strategique": "Informations stratégiques sensibles (fusions-acquisitions, secrets d'affaires).",
}

# Poids de risque relatif par catégorie (utilisé uniquement pour NUANCER
# le score de risque, jamais pour décider de la classe de confidentialité).
CATEGORY_RISK_WEIGHT = {
    "Publique": 0,
    "Personnelles": 5,
    "RH": 4,
    "Finance": 9,
    "Medicale": 10,
    "Juridique": 6,
    "Strategique": 10,
}


# ---------------------------------------------------------------------------
# 2. Référentiel : type de document -> catégorie -> niveau attendu
#    Sert de base à la génération du dataset labellisé (voir generate_dataset.py)
# ---------------------------------------------------------------------------

@dataclass
class DocumentType:
    nom: str
    categorie: str
    niveau: str  # C1 | C2 | C3 | C4


DOCUMENT_TYPES = [
    # --- Publique (C1) ---
    DocumentType("Communiqué de presse", "Publique", "C1"),
    DocumentType("Page site web institutionnel", "Publique", "C1"),
    DocumentType("Offre d'emploi publiée", "Publique", "C1"),
    DocumentType("Conseils prévention et santé", "Publique", "C1"),
    DocumentType("Politique de confidentialité publique", "Publique", "C1"),
    DocumentType("Actualités financières COMAR", "Publique", "C1"),
    DocumentType("Guide assurance auto/habitation", "Publique", "C1"),
    DocumentType("Modèle de document vierge", "Publique", "C1"),

    # --- Interne (C2) ---
    DocumentType("Note de service", "RH", "C2"),
    DocumentType("Compte-rendu de réunion d'équipe", "RH", "C2"),
    DocumentType("Planning d'équipe", "RH", "C2"),
    DocumentType("Procédure interne", "RH", "C2"),
    DocumentType("Invitation et planification réunion", "RH", "C2"),

    # --- Confidentiel (C3) ---
    DocumentType("Contrat de travail", "RH", "C3"),
    DocumentType("Bulletin de paie", "Finance", "C3"),
    DocumentType("Facture client", "Finance", "C3"),
    DocumentType("Contrat commercial", "Juridique", "C3"),
    DocumentType("Déclaration sinistre assurance", "Personnelles", "C3"),
    DocumentType("Devis et simulation assurance", "Finance", "C3"),
    DocumentType("Demande de souscription contrat", "Personnelles", "C3"),
    DocumentType("Avis d'échéance et appel de cotisations", "Finance", "C3"),
    DocumentType("Conditions particulières de police", "Personnelles", "C3"),

    # --- Hautement confidentiel (C4) ---
    DocumentType("Certificat médical", "Medicale", "C4"),
    DocumentType("Ordonnance médicale", "Medicale", "C4"),
    DocumentType("Arrêt maladie", "Medicale", "C4"),
    DocumentType("Dossier médical complet", "Medicale", "C4"),
    DocumentType("Attestation CNAM / mutuelle", "Medicale", "C4"),
    DocumentType("Rémunération dirigeant", "Finance", "C4"),
    DocumentType("Plan de fusion-acquisition", "Strategique", "C4"),
    DocumentType("Plan de restructuration", "Strategique", "C4"),
    DocumentType("Litige juridique majeur", "Juridique", "C4"),
    DocumentType("Rapport médical médecin conseil", "Medicale", "C4"),
    DocumentType("Dossier client (données personnelles)", "Personnelles", "C4"),
    DocumentType("Coordonnées bancaires client", "Finance", "C4"),
    DocumentType("Attestation bancaire (RIB tunisien)", "Finance", "C4"),
]


def get_expected_level(document_type_name: str) -> str:
    """Retourne le niveau attendu pour un type de document donné (référentiel)."""
    for dt in DOCUMENT_TYPES:
        if dt.nom == document_type_name:
            return dt.niveau
    raise ValueError(f"Type de document inconnu : {document_type_name}")


if __name__ == "__main__":
    print("Cartographie des données sensibles :\n")
    for cat, desc in CATEGORIES.items():
        print(f"- {cat} (poids risque {CATEGORY_RISK_WEIGHT[cat]}) : {desc}")

    print("\nRéférentiel type de document -> catégorie -> niveau :\n")
    for dt in DOCUMENT_TYPES:
        print(f"- {dt.nom:45s} | {dt.categorie:12s} | {dt.niveau}")

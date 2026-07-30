"""
generate_dataset.py (v3)
Génère un dataset labellisé (texte, categorie, label) à partir de la
cartographie des données sensibles (taxonomy.py).

Enrichissements v3 :
  - Données tunisiennes : téléphones +216, IBAN TN59, RIB bancaire, CIN, matricule fiscal
  - Types médicaux détaillés : certificat médical, ordonnance, arrêt maladie, CNAM
  - Contexte assurantiel COMAR (sinistres, dossiers clients)

Usage :
    python src/generate_dataset.py
    -> écrit data/dataset.csv (colonnes : texte, categorie, label, type_document)
"""

import csv
import random
import re
from pathlib import Path

from taxonomy import DOCUMENT_TYPES

random.seed(42)

NOMS = [
    "Sophie Martin", "Karim Ben Ali", "Julie Dupont", "Ahmed Trabelsi",
    "Laura Bernard", "Youssef Chaabane", "Emma Girard", "Nabil Hamdi",
    "Fatma Bouzid", "Mohamed Jebali", "Amira Gharbi", "Slim Karray",
]
SERVICES = ["Marketing", "Production", "Logistique", "Support client", "R&D", "Achats", "Sinistres", "Souscription"]
MONTANTS = ["12 500 TND", "48 000 TND", "3 200 TND", "150 000 TND", "7 800 TND", "22 900 TND", "1 850 TND"]
DATES = ["12/03/2026", "05/06/2026", "22/01/2026", "30/09/2025", "18/11/2026"]
PARTENAIRES = ["un partenaire industriel", "un fonds d'investissement", "une société concurrente", "un groupe international"]
VILLES = ["Tunis", "Sfax", "Sousse", "Bizerte", "Gabès", "Nabeul", "Monastir", "Ariana", "La Marsa"]
MEDECINS = ["Dr. Sami Mejri", "Dr. Leila Hammami", "Dr. Fares Ben Youssef", "Dr. Henda Trabelsi"]
ETABLISSEMENTS = ["Clinique El Amen", "Hôpital Charles Nicolle", "Polyclinique Les Berges du Lac", "Centre médical COMAR"]
DIAGNOSTICS = ["lombalgie chronique", "hypertension artérielle", "fracture du poignet", "grippe saisonnière", "burn-out professionnel"]

# Shared C4 contexts make the model learn the sensitivity concept rather than
# memorising one document title.  All examples remain entirely fictitious.
C4_CONTEXTS = [
    "Diffusion limitée aux personnes habilitées ; toute transmission externe est interdite.",
    "Information de niveau hautement confidentiel, soumise au secret professionnel.",
    "Accès réservé au circuit autorisé et conservation dans le dossier sécurisé.",
    "Toute copie, impression ou diffusion nécessite une validation préalable.",
]


def fake_iban_fr():
    return "FR76" + "".join(str(random.randint(0, 9)) for _ in range(23))


def fake_iban_tn():
    """IBAN tunisien factice (TN59 + 20 caractères)."""
    return "TN59" + "".join(str(random.randint(0, 9)) for _ in range(2)) + "0" + "".join(
        str(random.randint(0, 9)) for _ in range(16)
    )


def fake_rib_tn():
    """RIB bancaire tunisien factice (20 chiffres)."""
    return "".join(str(random.randint(0, 9)) for _ in range(20))


def fake_cin():
    return random.choice(["0", "1"]) + "".join(str(random.randint(0, 9)) for _ in range(7))


def fake_phone_local():
    prefix = random.choice(["20", "21", "22", "23", "24", "25", "26", "27", "28", "29",
                            "50", "51", "52", "53", "54", "55", "56", "57", "58", "59",
                            "70", "71", "72", "73", "74", "75", "76", "77", "78", "79",
                            "90", "91", "92", "93", "94", "95", "96", "97", "98", "99"])
    return prefix + "".join(str(random.randint(0, 9)) for _ in range(6))


def fake_phone_intl():
    """Numéro tunisien au format international +216."""
    local = fake_phone_local()
    fmt = random.choice([
        f"+216 {local[:2]} {local[2:5]} {local[5:]}",
        f"+216-{local[:2]}-{local[2:5]}-{local[5:]}",
        f"+216{local}",
        f"(+216) {local[:2]}.{local[2:5]}.{local[5:]}",
    ])
    return fmt


def fake_matricule():
    return (
        f"{random.randint(1000000, 9999999)}{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}/"
        f"{random.choice('AP')}/{random.choice('CMN')}/000"
    )


def fake_num_sinistre():
    return f"SIN-{random.randint(2024000, 2026999)}"


def fake_num_police():
    return f"POL-{random.randint(100000, 999999)}"


def ctx():
    phone_local = fake_phone_local()
    return {
        "nom": random.choice(NOMS),
        "service": random.choice(SERVICES),
        "montant": random.choice(MONTANTS),
        "date": random.choice(DATES),
        "iban_fr": fake_iban_fr(),
        "iban_tn": fake_iban_tn(),
        "rib": fake_rib_tn(),
        "partenaire": random.choice(PARTENAIRES),
        "cin": fake_cin(),
        "phone": phone_local,
        "phone_intl": fake_phone_intl(),
        "matricule": fake_matricule(),
        "ville": random.choice(VILLES),
        "medecin": random.choice(MEDECINS),
        "etablissement": random.choice(ETABLISSEMENTS),
        "diagnostic": random.choice(DIAGNOSTICS),
        "num_sinistre": fake_num_sinistre(),
        "num_police": fake_num_police(),
        "duree_arret": random.choice(["3 jours", "5 jours", "10 jours", "15 jours", "30 jours"]),
    }


TEMPLATES_BY_DOC_TYPE = {
    "Communiqué de presse": [
        "Communiqué de presse du {date} : COMAR Assurances annonce le lancement de sa nouvelle gamme de produits, disponible dès aujourd'hui pour le grand public tunisien.",
        "L'entreprise a le plaisir d'informer l'ensemble de ses parties prenantes et du public du succès de son événement annuel organisé à {ville} le {date}.",
        "Retrouvez notre actualité et nos communiqués officiels sur notre site internet, librement accessibles à tous.",
    ],
    "Page site web institutionnel": [
        "Présentation de notre mission, de nos valeurs et de notre histoire, publiée sur la page d'accueil de notre site institutionnel COMAR Assurances.",
        "Découvrez notre engagement en matière de responsabilité sociétale à {ville}, à retrouver sur notre site web ouvert à tous les visiteurs.",
    ],
    "Offre d'emploi publiée": [
        "Nous recrutons un(e) chargé(e) de projet pour rejoindre notre service {service} à {ville}. Candidature à envoyer via notre site carrière.",
        "Offre d'emploi ouverte à candidature : poste à pourvoir au sein de l'équipe {service}, annonce publiée sur les plateformes de recrutement tunisiennes.",
    ],
    "Note de service": [
        "À l'attention de l'équipe {service} : merci de prendre connaissance des nouveaux horaires applicables à partir du {date}. Diffusion limitée aux collaborateurs.",
        "Note interne du {date} concernant l'organisation du service {service} pour le trimestre à venir. Ne pas transmettre en dehors de l'entreprise.",
        "Petit rappel à toute l'équipe {service} : la salle de réunion B sera indisponible le {date} pour travaux.",
    ],
    "Compte-rendu de réunion d'équipe": [
        "Compte-rendu de la réunion du service {service} du {date} : points abordés, décisions prises et actions à suivre par l'équipe.",
        "Synthèse de l'échange hebdomadaire de l'équipe {service}, destinée uniquement aux membres présents et à leur hiérarchie directe.",
    ],
    "Planning d'équipe": [
        "Planning prévisionnel de l'équipe {service} pour le mois en cours, à consulter par les collaborateurs concernés uniquement.",
        "Organisation des congés et astreintes du service {service} jusqu'au {date}.",
    ],
    "Procédure interne": [
        "Procédure de fonctionnement du service {service} : étapes à suivre pour le traitement des demandes courantes, réservée au personnel de l'entreprise.",
        "Mode opératoire interne applicable au sein de l'équipe {service}, non destiné à être communiqué à des tiers.",
    ],
    "Contrat de travail": [
        "Contrat de travail établi entre COMAR Assurances et {nom}, affecté(e) au service {service} à {ville}, prenant effet le {date}. CIN : {cin}. Ce document engage les deux parties.",
        "Le présent contrat fixe les conditions d'emploi de {nom} au sein du service {service}. Sa diffusion est strictement réservée aux ressources humaines et à l'intéressé(e).",
    ],
    "Bulletin de paie": [
        "Bulletin de salaire de {nom} pour le mois en cours, service {service}. Montant net à payer : {montant}. Document personnel ne pouvant être partagé sans consentement.",
        "Récapitulatif de rémunération de {nom} : {montant}, à conserver dans le dossier du salarié, accès restreint au service RH.",
    ],
    "Facture client": [
        "Facture n° 2026-{date} émise au nom de {nom} pour un montant de {montant}. Coordonnées de paiement : IBAN {iban_tn}.",
        "Relevé de facturation du client {nom}, montant total {montant}, à traiter exclusivement par le service comptabilité.",
    ],
    "Coordonnées bancaires client": [
        "Enregistrement des coordonnées bancaires du client {nom} (CIN {cin}) : IBAN {iban_tn}, RIB {rib}. Ces informations financières ne doivent en aucun cas être communiquées à un tiers non autorisé.",
        "Mise à jour du moyen de paiement de {nom} : nouvel IBAN {iban_tn} enregistré dans le système, accès limité au service Finance.",
        "Fiche de prélèvement bancaire COMAR : Client {nom}, IBAN {iban_tn}, CIN {cin}, Tél: {phone_intl}.",
    ],
    "Contrat commercial": [
        "Accord commercial conclu entre COMAR Assurances et {partenaire}, portant sur une prestation d'un montant de {montant}. Les termes de cet accord ne peuvent être divulgués sans autorisation.",
        "Le présent contrat lie l'entreprise à {partenaire} à compter du {date}. Sa communication est réservée aux signataires et à la direction juridique.",
    ],
    "Dossier client (données personnelles)": [
        "Fiche client de {nom} : coordonnées personnelles, historique d'achats et préférences. CIN {cin}, Tél: {phone_intl}. Données soumises au RGPD et à la loi tunisienne sur la protection des données.",
        "Dossier de suivi du client {nom}, incluant ses informations de contact (Mobile: {phone_intl}, Fixe: {phone}). Accès réservé aux collaborateurs habilités du service {service}.",
        "Fiche client COMAR : {nom} (CIN {cin}, {ville}, Tél: {phone_intl}). Police n° {num_police}. Ce dossier contient des données sensibles assurantielles.",
    ],
    "Attestation bancaire (RIB tunisien)": [
        "Attestation bancaire établie pour {nom} (CIN {cin}) : RIB {rib}, IBAN {iban_tn}. Document à usage exclusif du service Finance et du client concerné.",
        "Relevé d'identité bancaire COMAR : titulaire {nom}, banque STB, RIB {rib}, IBAN {iban_tn}. Ne pas transmettre par messagerie non sécurisée.",
    ],
    "Déclaration sinistre assurance": [
        "Déclaration de sinistre n° {num_sinistre} — Assuré : {nom} (CIN {cin}, Tél: {phone_intl}). Police {num_police}. Montant réclamé : {montant}. Dossier à traiter par le service Sinistres.",
        "Rapport d'expertise sinistre pour {nom}, référence {num_sinistre}. Coordonnées : {phone_intl}, {ville}. Document contenant des données personnelles et financières sensibles.",
    ],
    "Certificat médical": [
        "CERTIFICAT MÉDICAL — Je soussigné(e) {medecin}, certifie avoir examiné ce jour M./Mme {nom} (CIN {cin}) et constate un état de santé nécessitant un repos de {duree_arret}. Établi à {ville} le {date}. Ce document est couvert par le secret médical.",
        "Certificat médical délivré par {etablissement} concernant {nom} (CIN {cin}). Diagnostic : {diagnostic}. Durée d'incapacité : {duree_arret}. Document strictement confidentiel, réservé au médecin conseil COMAR et au service RH.",
        "Attestation médicale — Patient : {nom}, CIN {cin}, Tél: {phone_intl}. Consultation du {date} à {etablissement}. Motif : {diagnostic}. Ne pas diffuser en dehors du circuit médical autorisé.",
    ],
    "Ordonnance médicale": [
        "ORDONNANCE — {medecin}, {etablissement}, {ville}. Patient : {nom} (CIN {cin}). Prescription médicale pour {diagnostic}. Document de santé protégé par le secret médical.",
        "Ordonnance médicale concernant {nom} (CIN {cin}). Traitement prescrit le {date} par {medecin}. Ce document ne peut être consulté que par le personnel médical habilité et le pharmacien.",
    ],
    "Arrêt maladie": [
        "Arrêt de travail médical — {nom} (CIN {cin}, Matricule {matricule}). Durée : {duree_arret} à compter du {date}. Motif : {diagnostic}. À transmettre uniquement au service RH dans le respect du secret médical.",
        "Certificat d'arrêt de travail de {nom}, établi par {medecin} le {date}. Incapacité temporaire de {duree_arret}. Document couvert par le secret médical, accès restreint au médecin du travail COMAR.",
    ],
    "Dossier médical complet": [
        "Dossier médical confidentiel de {nom} (CIN {cin}, Tél: {phone_intl}). Antécédents : {diagnostic}. Suivi à {etablissement}. Accès strictement restreint au médecin conseil COMAR.",
        "Compte-rendu médical concernant {nom} (CIN {cin}), établi le {date} par {medecin}. Ce document relève du secret médical et ne peut être consulté que par le personnel de santé autorisé.",
    ],
    "Attestation CNAM / mutuelle": [
        "Attestation CNAM — Bénéficiaire : {nom} (CIN {cin}). Numéro d'affiliation : {matricule}. Prise en charge médicale pour {diagnostic}. Document contenant des données de santé protégées.",
        "Relevé de remboursement mutuelle pour {nom} (CIN {cin}). Montant remboursé : {montant}. Acte médical : {diagnostic}. Données de santé couvertes par le secret médical.",
    ],
    "Rémunération dirigeant": [
        "Rémunération globale du dirigeant {nom} pour l'exercice en cours : {montant}. Cette information est réservée aux membres du conseil d'administration.",
        "Package de rémunération du comité exécutif, {nom} inclus, montant total {montant}. Diffusion strictement limitée à la direction générale.",
    ],
    "Plan de fusion-acquisition": [
        "Projet d'acquisition en cours de négociation avec {partenaire}, montant envisagé {montant}. Ce dossier ne doit être consulté que par les membres du comité exécutif jusqu'à son annonce officielle.",
        "Éléments stratégiques relatifs au rapprochement avec {partenaire}, prévu pour le {date}. Toute fuite d'information avant l'annonce officielle exposerait l'entreprise à un risque financier majeur.",
    ],
    "Plan de restructuration": [
        "Plan de réorganisation du service {service}, prévu pour le {date}, impliquant une révision des effectifs. Document réservé au comité de direction.",
        "Scénario de restructuration stratégique concernant le service {service}. Ces éléments sont classés au plus haut niveau de sensibilité et leur divulgation prématurée est interdite.",
    ],
    "Litige juridique majeur": [
        "Dossier de contentieux opposant COMAR Assurances à {partenaire}, enjeu financier estimé à {montant}. Ce dossier est couvert par le secret professionnel.",
        "Procédure judiciaire en cours concernant un différend avec {partenaire}. Les pièces de ce dossier ne peuvent être communiquées qu'aux avocats mandatés et à la direction générale.",
    ],
    "Conseils prévention et santé": [
        "COMAR Santé : Pour votre bien-être, adoptez une alimentation équilibrée et pratiquez une activité physique régulière. Pour toute question médicale, consultez votre médecin traitant.",
        "Guide de santé publique : comment prévenir les maladies saisonnières. Des conseils simples pour renforcer votre système immunitaire cet hiver.",
    ],
    "Politique de confidentialité publique": [
        "Politique de confidentialité et cookies de COMAR Assurances. Nous attachons une grande importance à la protection de vos données personnelles et au respect du RGPD.",
        "Charte de confidentialité : comment nous traitons vos données personnelles collectées sur notre site web institutionnel. Conformément à la législation en vigueur, vous disposez d'un droit d'accès et de rectification.",
    ],
    "Actualités financières COMAR": [
        "Communiqué financier : COMAR Assurances affiche des résultats solides pour l'exercice écoulé, avec une hausse du chiffre d'affaires global et de nombreux nouveaux contrats signés à Tunis.",
        "COMAR Assurances annonce des performances financières stables pour ce semestre, consolidant sa position de leader sur le marché tunisien avec un montant net d'investissements record.",
    ],
    "Guide assurance auto/habitation": [
        "Guide pratique de l'assuré : comment déclarer un sinistre en ligne et obtenir une assistance immédiate. Les étapes clés pour être remboursé rapidement.",
        "Tout savoir sur l'assurance habitation : garanties obligatoires, franchises et options disponibles pour protéger votre logement et votre famille.",
    ],
    "Modèle de document vierge": [
        "MODÈLE DE FICHE CLIENT VIERGE - COMAR ASSURANCES\nNom de l'assuré : [Insérer Nom]\nCIN : [__ __ __ __ __ __ __ __]\nTéléphone : [Insérer Numéro]\nAdresse : [Insérer Ville]\nNuméro de police : POL-xxxxxx\nNuméro de sinistre : SIN-xxxxxxx",
        "TEMPLATE DE CERTIFICAT MEDICAL D'APTITUDE\nJe soussigné Dr [Nom du médecin] certifie que M./Mme [Nom du patient] ... \nDiagnostic : [________________]\nSignature et cachet du médecin :",
    ],
    "Invitation et planification réunion": [
        "Bonjour à tous, je vous propose de planifier une réunion de travail pour faire le point sur le dossier de l'assurance client de M. Ben Ali. Merci de m'indiquer vos disponibilités.",
        "Invitation réunion d'équipe : ordre du jour concernant le planning des audits internes et le suivi du dossier client. Rendez-vous dans la salle de conférence.",
    ],
    "Devis et simulation assurance": [
        "Simulation de tarif pour une assurance auto COMAR. Client : {nom}. Véhicule de tourisme, usage privé. Montant de la cotisation annuelle estimé à {montant}. Valable 30 jours.",
        "Devis d'assurance habitation n° {num_police} établi pour {nom} (CIN {cin}). Cotisation annuelle : {montant} pour une couverture multirisque à {ville}.",
    ],
    "Demande de souscription contrat": [
        "Demande d'adhésion au contrat d'assurance groupe COMAR. Adhérent : {nom}, résidant à {ville}. CIN : {cin}, Tél : {phone_intl}. Signature requise pour finaliser la souscription.",
        "Formulaire de souscription assurance vie. Souscripteur : {nom} (CIN {cin}, Tél: {phone_intl}). Bénéficiaire désigné en cas de décès : conjoint(e). Reçu le {date}.",
    ],
    "Avis d'échéance et appel de cotisations": [
        "Avis d'échéance COMAR Assurances. Client : {nom}. Police n° {num_police}. Cotisation due pour la période du {date} : {montant}. À régler par prélèvement sur votre compte IBAN {iban_tn}.",
        "Appel de cotisation pour votre assurance auto n° {num_police}. Assuré : {nom}. Montant net à payer : {montant} avant le {date}. Coordonnées bancaires COMAR pour virement : RIB {rib}.",
    ],
    "Conditions particulières de police": [
        "Conditions particulières du contrat d'assurance auto n° {num_police} souscrit par {nom} (CIN {cin}, Tél: {phone_intl}). Date d'effet : {date}. Garanties : Responsabilité Civile, Vol et Incendie.",
        "Police d'assurance habitation n° {num_police} - Conditions particulières. Assuré : {nom} ({ville}). Franchise générale de {montant} par sinistre. Document contractuel confidentiel.",
    ],
    "Rapport médical médecin conseil": [
        "Rapport d'expertise médicale confidentiel rédigé par {medecin}, médecin conseil de COMAR Assurances. Suite à l'examen de l'assuré {nom} (CIN {cin}) après son accident du {date}. Diagnostic : {diagnostic} entraînant une incapacité permanente partielle. Destiné exclusivement au service médical.",
        "Rapport d'évaluation médicale - Médecin conseil : {medecin}. Assuré : {nom} (CIN {cin}, Tél : {phone_intl}). Examen médical du dossier de sinistre {num_sinistre}. Conclusion : {diagnostic}, incapacité de {duree_arret} à valider. Soumis au secret médical strict.",
    ],
}


def anonymize_text(text: str) -> str:
    """Anonymise les exemples de dataset pour respecter le cahier de charge."""
    anonymized = text
    anonymized = re.sub(r"\b(?:[01]\d{7}|\d{8})\b", "[IDENTIFIANT]", anonymized)
    anonymized = re.sub(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", "[PERSONNE]", anonymized)
    anonymized = re.sub(r"\b(?:Dr\.|Docteur)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", "[MEDECIN]", anonymized)
    anonymized = re.sub(r"\b(?:service|service\s+[A-Za-zÀ-ÿ]+)\b", "[SERVICE]", anonymized, flags=re.IGNORECASE)
    anonymized = re.sub(r"\b(?:Tél|Téléphone|Mobile|Fixe)\s*[:\-]?\s*(?:\+216[\s\-\.]?\d{8}|\d{8})", "[CONTACT]", anonymized, flags=re.IGNORECASE)
    anonymized = re.sub(r"\b(?:IBAN|RIB|CIN|Matricule|Numéro de police|Numéro de sinistre)\b", "[IDENTIFIANT]", anonymized, flags=re.IGNORECASE)
    anonymized = anonymized.replace("COMAR Assurances", "[ORGANISATION]").replace("COMAR", "[ORGANISATION]")
    anonymized = anonymized.replace("CNAM", "[ORGANISME]").replace("mutuelle", "[ORGANISME]")
    return anonymized


def generate_dataset(n_per_doc_type: int = 30) -> list:
    rows = []
    for doc_type in DOCUMENT_TYPES:
        templates = TEMPLATES_BY_DOC_TYPE.get(doc_type.nom, [])
        if not templates:
            continue
        for _ in range(n_per_doc_type):
            template = random.choice(templates)
            text = template.format(**ctx())
            if doc_type.niveau == "C4":
                text = f"{text} {random.choice(C4_CONTEXTS)}"
            anonymized = anonymize_text(text)
            if not re.search(r"\[(?:PERSONNE|IDENTIFIANT|SERVICE|CONTACT|ORGANISATION|ORGANISME|DONNEES)\]", anonymized):
                anonymized = f"[DONNEES] {anonymized}"
            rows.append({
                "texte": anonymized,
                "categorie": doc_type.categorie,
                "label": doc_type.niveau,
                "type_document": doc_type.nom,
                "anonymized": True,
            })
    random.shuffle(rows)
    return rows


def main():
    output_path = Path(__file__).resolve().parent.parent / "data" / "dataset.csv"
    output_path.parent.mkdir(exist_ok=True)

    rows = generate_dataset(n_per_doc_type=30)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["texte", "categorie", "label", "type_document", "anonymized"])
        writer.writeheader()
        writer.writerows(rows)

    counts = {}
    cat_counts = {}
    for r in rows:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
        cat_counts[r["categorie"]] = cat_counts.get(r["categorie"], 0) + 1

    print(f"Dataset généré : {output_path} ({len(rows)} exemples)")
    print(f"Répartition par niveau : {counts}")
    print(f"Répartition par catégorie : {cat_counts}")


if __name__ == "__main__":
    main()

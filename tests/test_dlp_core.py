import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from extraction import extract_text
from classification import _high_risk_guardrails, classify_archive_items, detect_category
from generate_dataset import anonymize_text, generate_dataset
from policy import check_transfer_policy
from m365_integration import M365Integration


class ExtractionTests(unittest.TestCase):
    def test_xml_text_is_extracted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "client.xml"
            path.write_text("<client><name>Karim Ben Ali</name><iban>TN591234567890123456789012</iban></client>", encoding="utf-8")
            result = extract_text(str(path))
        self.assertEqual(result["metadata"]["format"], "xml")
        self.assertIn("Karim Ben Ali", result["text"])

    def test_zip_analyses_supported_members_without_extracting_them(self):
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr("note.txt", "CIN 01234567")
            archive.writestr("ignore.exe", b"binary")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "documents.zip"
            path.write_bytes(buffer.getvalue())
            result = extract_text(str(path))
        self.assertIn("CIN 01234567", result["text"])
        self.assertEqual(result["metadata"]["analysed_files"], ["note.txt"])
        self.assertEqual(result["metadata"]["skipped_files"], ["ignore.exe"])
        self.assertEqual(result["metadata"]["analysis_items"][0]["name"], "note.txt")

    def test_medical_evidence_beats_generic_financial_words(self):
        text = "Certificat médical : diagnostic du patient. Montant remboursé : 7 800 TND."
        self.assertEqual(detect_category(text), "Medicale")

    def test_zip_uses_the_most_sensitive_member_category(self):
        items = [
            {"name": "budget.txt", "text": "Budget prévisionnel : 1 200 TND."},
            {"name": "sante.txt", "text": "Certificat médical et secret médical du patient."},
        ]
        result, details = classify_archive_items(items)
        self.assertEqual(result.category, "Medicale")
        self.assertEqual(len(details), 2)

    def test_xml_dtd_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unsafe.xml"
            path.write_text("<!DOCTYPE a [<!ENTITY x 'danger'>]><a>&x;</a>", encoding="utf-8")
            with self.assertRaises(ValueError):
                extract_text(str(path))

    def test_medical_variants_are_detected_as_medical(self):
        variants = [
            "Résultat d'analyse biologique du patient : hospitalisation confirmée.",
            "Compte-rendu médical : prescription et incapacité temporaire.",
            "Imagerie médicale réalisée après une fracture du poignet.",
        ]
        for text in variants:
            self.assertEqual(detect_category(text), "Medicale")

    def test_c4_safeguard_promotes_explicit_medical_content(self):
        safeguards = _high_risk_guardrails(
            "Compte-rendu médical : bilan biologique du patient après hospitalisation."
        )
        self.assertTrue(any("C4 santé" in item for item in safeguards))

    def test_classification_explanation_lists_detected_terms(self):
        from classification import classify_demo_without_model

        text = "Certificat médical du patient, diagnostic confirmé, dossier médical confidentiel."
        result = classify_demo_without_model(text)
        self.assertEqual(result.level, "C4")
        self.assertTrue(result.evidence_terms)
        self.assertIn("certificat médical", result.evidence_terms)
        self.assertIn("diagnostic", result.explanation.lower())

    def test_c4_safeguards_cover_other_critical_categories(self):
        cases = [
            ("Projet de fusion soumis au comité exécutif pour due diligence.", "C4 stratégie"),
            ("Rémunération du dirigeant validée par le conseil d'administration.", "C4 finance"),
            ("Contentieux et procédure judiciaire couverts par le secret professionnel.", "C4 juridique"),
        ]
        for text, expected in cases:
            self.assertTrue(any(expected in item for item in _high_risk_guardrails(text)))

    def test_anonymize_text_replaces_identifiers_with_placeholders(self):
        sample = "Certificat médical pour Karim Ben Ali, CIN 01234567, Tél: +216 22 123 456."
        anonymized = anonymize_text(sample)
        self.assertNotIn("Karim Ben Ali", anonymized)
        self.assertNotIn("01234567", anonymized)
        self.assertIn("[PERSONNE]", anonymized)
        self.assertIn("[IDENTIFIANT]", anonymized)

    def test_generated_dataset_is_anonymized_and_labeled(self):
        rows = generate_dataset(n_per_doc_type=2)
        self.assertTrue(rows)
        self.assertTrue(all(row["anonymized"] for row in rows))
        self.assertTrue(all("[" in row["texte"] and "]" in row["texte"] for row in rows))

    def test_counter_examples_are_classified_c1_or_c2(self):
        from classification import classify_demo_without_model
        from scoring import compute_score
        
        cases = [
            "Bonjour, je propose de planifier une réunion de travail pour faire le point sur l'assurance client mardi. Merci de m'indiquer vos disponibilités.",
            "COMAR Santé : Pour votre bien-être, adoptez une alimentation équilibrée et pratiquez une activité physique régulière. Pour toute question médicale, consultez votre médecin.",
            "Politique de confidentialité et cookies de COMAR Assurances. Nous protégeons vos données personnelles conformément au RGPD.",
            "MODÈLE DE FICHE CLIENT VIERGE - Nom de l'assuré : [Insérer Nom] - CIN : [__ __ __ __ __ __ __ __]",
            "Communiqué financier : COMAR Assurances affiche des résultats solides avec une hausse du chiffre d'affaires global."
        ]
        
        for text in cases:
            res = classify_demo_without_model(text)
            score_res = compute_score(res)
            self.assertIn(res.level, ["C1", "C2"])
            self.assertLess(score_res.score, 70)
            self.assertFalse(score_res.alert_triggered)

    def test_insurance_scenarios_are_classified_correctly(self):
        from classification import classify_demo_without_model
        
        # Devis (C3)
        devis_text = "Simulation de tarif pour une assurance auto COMAR. Client : Julie Dupont. Cotisation annuelle estimée à 3 200 TND."
        res = classify_demo_without_model(devis_text)
        self.assertEqual(res.level, "C3")
        
        # Rapport médecin conseil (C4)
        rapport_text = "Rapport d'expertise médicale confidentiel rédigé par Dr. Sami Mejri, médecin conseil de COMAR Assurances. Diagnostic : lombalgie chronique du patient."
        res = classify_demo_without_model(rapport_text)
        self.assertEqual(res.level, "C4")

        # Dossier client avec données personnelles et bancaires (C4)
        client_doc_text = """
        DOSSIER CLIENT 
        Compagnie d'assurance : COMAR Assurances
        Nom : Mohamed Ben Salah
        Date de naissance : 15/03/1985
        Numéro CIN : 14667664 [CIN TN]
        Adresse : 25 Rue de la République, Tunis
        Téléphone : 98 456 789
        Email : mohamed.bensalah@email.com
        Compte bancaire : TN59 1234 5678 9012 3456
        """
        res = classify_demo_without_model(client_doc_text)
        self.assertEqual(res.level, "C4")


class PolicyTests(unittest.TestCase):
    def test_c3_external_transfer_requires_encryption(self):
        result = check_transfer_policy("C3", "a@comar.tn", "b@example.org", "Exchange Online (Pro)", False)
        self.assertFalse(result.allowed)
        self.assertTrue(result.alert_triggered)

    def test_sensitive_external_transfer_requires_justification(self):
        result = check_transfer_policy(
            "C3",
            "a@comar.tn",
            "b@example.org",
            "Exchange Online (Pro)",
            True,
            justification="",
        )
        self.assertFalse(result.allowed)
        self.assertTrue(result.alert_triggered)
        self.assertIn("justification", result.reason.lower())


class M365Tests(unittest.TestCase):
    def test_alert_email_is_blocked_in_simulation(self):
        sent, message = M365Integration().send_dlp_alert("test", "<p>test</p>", b"type,statut\nanalyse,ok\n")
        self.assertFalse(sent)
        self.assertIn("simulation", message)

    def test_c4_external_transfer_is_always_blocked(self):
        result = check_transfer_policy("C4", "a@comar.tn", "b@example.org", "Exchange Online (Pro)", True)
        self.assertFalse(result.allowed)
        self.assertTrue(result.alert_triggered)


if __name__ == "__main__":
    unittest.main()

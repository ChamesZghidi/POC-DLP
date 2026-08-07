"""
m365_integration.py
Module de préparation à l'intégration Microsoft 365 / Purview DLP.

Fonctionnement :
  - Mode SIMULATION (par défaut) : génère des incidents DLP simulés et mappe
    les niveaux C1-C4 vers les étiquettes de sensibilité Microsoft.
  - Mode LIVE (si credentials Azure configurés dans .env) : authentification
    MSAL + appels Microsoft Graph pour lire les e-mails/fichiers récents.

Prérequis pour le mode live :
  1. Application enregistrée dans Entra ID (Azure AD)
  2. Permissions : Mail.Read, Files.Read, User.Read (Application ou Delegated)
  3. Variables d'environnement : AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
"""

import base64
import json
import os
from urllib.parse import quote
from urllib.request import Request, urlopen
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

# Alias de catégories détectées vers les clés de routage_validation (config.yaml).
CATEGORY_ROUTING_ALIASES = {
    "Personnelles": "Personnelles",
    "Personelle": "Personnelles",
    "Personnelle": "Personnelles",
    "Medical": "Medicale",
    "Médicale": "Medicale",
    "Stratégique": "Strategique",
    "Securité": "Securite",
    "Sécurité": "Securite",
    "Indeterminee": "default",
    "Publique": "default",
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


@dataclass
class SensitivityLabelMapping:
    level: str
    microsoft_label: str
    description: str


@dataclass
class PurviewIncident:
    incident_id: str
    timestamp: str
    document_name: str
    level: str
    sensitivity_label: str
    action: str
    channel: str
    severity: str
    status: str
    details: str


@dataclass
class M365ConnectionStatus:
    mode: str  # "simulation" | "live" | "error"
    connected: bool
    tenant_id: Optional[str] = None
    user_display_name: Optional[str] = None
    user_email: Optional[str] = None
    message: str = ""
    scopes: list = field(default_factory=list)


@dataclass
class GraphMailItem:
    subject: str
    sender: str
    received: str
    preview: str
    item_id: str


class M365Integration:
    """Connecteur Microsoft 365 / Purview pour le POC DLP."""

    def __init__(self):
        self.config = load_config()
        self.m365_config = self.config.get("microsoft365", {})
        self.label_map = self.m365_config.get("sensitivity_labels", {
            "C1": "Public", "C2": "Interne", "C3": "Confidentiel", "C4": "Hautement Confidentiel",
        })
        self._token = None
        self._graph_client = None

    def _load_env_credentials(self) -> dict:
        try:
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        except ImportError:
            pass

        return {
            "tenant_id": os.getenv("AZURE_TENANT_ID", self.m365_config.get("tenant_id", "")),
            "client_id": os.getenv("AZURE_CLIENT_ID", self.m365_config.get("client_id", "")),
            "client_secret": os.getenv("AZURE_CLIENT_SECRET", ""),
            "target_user_id": os.getenv("GRAPH_TARGET_USER", self.m365_config.get("target_user_id", "")),
            "alert_recipients": os.getenv("DLP_ALERT_RECIPIENTS", ""),
        }

    def _live_mode_enabled(self) -> bool:
        """Évite tout appel réseau accidentel avec des secrets présents en local."""
        return bool(self.m365_config.get("enabled", False))

    def get_connection_status(self) -> M365ConnectionStatus:
        creds = self._load_env_credentials()
        scopes = self.m365_config.get("graph_application_permissions", [])

        if not self._live_mode_enabled():
            return M365ConnectionStatus(
                mode="simulation", connected=False,
                message="Mode simulation verrouillé. Aucun appel Microsoft Graph n'est autorisé tant que microsoft365.enabled=true.",
                scopes=scopes,
            )

        if not all([creds["tenant_id"], creds["client_id"], creds["client_secret"], creds["target_user_id"]]):
            return M365ConnectionStatus(
                mode="simulation",
                connected=False,
                message=(
                    "Configuration pilote incomplète : renseignez AZURE_TENANT_ID, AZURE_CLIENT_ID, "
                    "AZURE_CLIENT_SECRET et GRAPH_TARGET_USER."
                ),
                scopes=scopes,
            )

        try:
            token = self._acquire_token(creds)
            if token:
                user_info = self._get_user_info(token, creds["target_user_id"])
                return M365ConnectionStatus(
                    mode="live",
                    connected=True,
                    tenant_id=creds["tenant_id"][:8] + "...",
                    user_display_name=user_info.get("displayName", "N/A"),
                    user_email=user_info.get("mail") or user_info.get("userPrincipalName", "N/A"),
                    message="Connecté au tenant Microsoft 365 via Microsoft Graph API.",
                    scopes=scopes,
                )
        except Exception as e:
            return M365ConnectionStatus(
                mode="error",
                connected=False,
                tenant_id=creds["tenant_id"][:8] + "...",
                message=f"Erreur de connexion : {e}",
                scopes=scopes,
            )

        return M365ConnectionStatus(
            mode="simulation",
            connected=False,
            message="Authentification échouée — mode simulation activé.",
            scopes=scopes,
        )

    def _acquire_token(self, creds: dict) -> Optional[str]:
        try:
            import msal
        except ImportError:
            raise ImportError("Installez msal : pip install msal")

        app = msal.ConfidentialClientApplication(
            creds["client_id"],
            authority=f"https://login.microsoftonline.com/{creds['tenant_id']}",
            client_credential=creds["client_secret"],
        )
        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" in result:
            self._token = result["access_token"]
            return self._token
        raise RuntimeError(result.get("error_description", "Token acquisition failed"))

    @staticmethod
    def _graph_get(token: str, path: str) -> dict:
        """Appel Graph minimal, avec un chemin fourni par le code (pas l'UI)."""
        req = Request(
            f"https://graph.microsoft.com/v1.0{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    @staticmethod
    def _graph_post(token: str, path: str, payload: dict) -> None:
        req = Request(
            f"https://graph.microsoft.com/v1.0{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=15):
            pass

    def _get_user_info(self, token: str, target_user_id: str) -> dict:
        user = quote(target_user_id, safe="@.")
        return self._graph_get(token, f"/users/{user}?$select=id,displayName,mail,userPrincipalName")

    def get_sensitivity_label(self, level: str) -> SensitivityLabelMapping:
        label = self.label_map.get(level, "Non classifié")
        descriptions = {
            "C1": "Diffusion libre — équivalent étiquette Microsoft « Public »",
            "C2": "Usage interne — équivalent étiquette Microsoft « Interne »",
            "C3": "Données confidentielles — étiquette « Confidentiel » avec chiffrement recommandé",
            "C4": "Données hautement sensibles — étiquette « Hautement Confidentiel » avec chiffrement obligatoire",
        }
        return SensitivityLabelMapping(
            level=level,
            microsoft_label=label,
            description=descriptions.get(level, ""),
        )

    def get_all_label_mappings(self) -> list:
        return [self.get_sensitivity_label(lvl) for lvl in ["C1", "C2", "C3", "C4"]]

    def get_routage_validation(self) -> dict[str, str]:
        """Retourne la table catégorie -> adresse du groupe validateur."""
        routing = self.m365_config.get("routage_validation", {})
        return {str(key): str(value) for key, value in routing.items() if key != "default"}

    def get_validation_recipient(self, category: Optional[str]) -> str:
        """Résout l'adresse du groupe validateur pour une catégorie métier."""
        routing = self.m365_config.get("routage_validation", {})
        default = routing.get("default", "rssi@comar.tn")
        if not category:
            return default

        candidates = [category.strip()]
        alias = CATEGORY_ROUTING_ALIASES.get(category.strip())
        if alias and alias not in candidates:
            candidates.append(alias)

        for key in candidates:
            if key in routing:
                return routing[key]
        return default

    def resolve_alert_recipients(
        self,
        category: Optional[str] = None,
        explicit_recipients: Optional[list[str]] = None,
    ) -> list[str]:
        """Priorité : destinataires explicites > routage par catégorie > .env."""
        if explicit_recipients:
            return [address.strip() for address in explicit_recipients if address.strip()]

        if category:
            routed = self.get_validation_recipient(category)
            if routed:
                return [routed]

        env_recipients = self._load_env_credentials().get("alert_recipients", "")
        return [value.strip() for value in env_recipients.split(",") if value.strip()]

    def get_rssi_address(self) -> str:
        return str(self.m365_config.get("routage_validation", {}).get("default", "rssi@comar.tn"))

    def should_cc_rssi(
        self,
        category: Optional[str],
        level: Optional[str] = None,
        score: Optional[int] = None,
    ) -> bool:
        """Met le RSSI en copie lorsque l'alerte est adressée à un groupe métier sensible."""
        primary = self.get_validation_recipient(category).lower()
        if primary == self.get_rssi_address().lower():
            return False
        if level == "C4":
            return True
        if score is not None and score > 80:
            return True
        if category in ("Strategique", "Medicale", "Juridique"):
            return True
        if level == "C3":
            return True
        return False

    def resolve_alert_routing(
        self,
        category: Optional[str] = None,
        level: Optional[str] = None,
        score: Optional[int] = None,
        explicit_recipients: Optional[list[str]] = None,
    ) -> tuple[list[str], list[str]]:
        to_recipients = self.resolve_alert_recipients(
            category=category,
            explicit_recipients=explicit_recipients,
        )
        cc_recipients: list[str] = []
        if self.should_cc_rssi(category, level, score):
            rssi = self.get_rssi_address()
            if rssi and rssi not in to_recipients:
                cc_recipients = [rssi]
        return to_recipients, cc_recipients

    def create_purview_incident(
        self,
        document_name: str,
        level: str,
        action: str,
        channel: str,
        score: int,
        blocked: bool,
    ) -> PurviewIncident:
        label = self.get_sensitivity_label(level)
        severity = "high" if level in ("C3", "C4") and blocked else "medium" if blocked else "low"
        incident_id = f"DLP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{level}"

        return PurviewIncident(
            incident_id=incident_id,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            document_name=document_name,
            level=level,
            sensitivity_label=label.microsoft_label,
            action=action,
            channel=channel,
            severity=severity,
            status="blocked" if blocked else "allowed",
            details=(
                f"Politique {self.m365_config.get('purview', {}).get('policy_template', 'COMAR-DLP-POC')} — "
                f"Score {score}/100 — Étiquette {label.microsoft_label}"
            ),
        )

    def get_purview_policy_summary(self) -> dict:
        purview = self.m365_config.get("purview", {})
        dlp = self.config.get("dlp", {})
        return {
            "policy_name": purview.get("policy_template", "COMAR-DLP-POC"),
            "mode": "simulation" if purview.get("simulation", True) else "production",
            "locations": purview.get("locations", []),
            "approved_channels": dlp.get("canaux_approuves", []),
            "blocked_channels": dlp.get("canaux_interdits", []),
            "label_mappings": [
                {"level": m.level, "label": m.microsoft_label, "description": m.description}
                for m in self.get_all_label_mappings()
            ],
        }

    def build_purview_policy_spec(self) -> dict:
        """Produit un artefact de validation pour Purview, sans modifier le tenant.

        La création et l'activation d'une politique restent une opération
        administrateur dans le portail Purview, avec revue RSSI/DPO.
        """
        return {
            "policy_name": self.m365_config.get("purview", {}).get("policy_template", "COMAR-DLP-POC"),
            "mode": "test_with_notifications",
            "locations": self.m365_config.get("purview", {}).get("locations", []),
            "rules": [
                {"level": "C1", "action": "audit", "justification_required": False},
                {"level": "C2", "action": "audit_and_notify", "external_sharing": "block"},
                {"level": "C3", "action": "block_external_unless_encrypted", "justification_required": True},
                {"level": "C4", "action": "block_external_and_restrict_internal", "encryption_required": True},
            ],
            "deployment_guardrails": [
                "Pilote limité à une boîte, un site SharePoint et un OneDrive de test.",
                "Mode test et journalisation avant passage en blocage.",
                "Validation RSSI, DPO, propriétaires métier et licences Purview.",
            ],
        }

    def send_dlp_alert(
        self,
        subject: str,
        html_body: str,
        report_bytes: bytes,
        report_name: str = "rapport-dlp.pdf",
        report_content_type: str = "application/pdf",
        category: Optional[str] = None,
        justification: Optional[str] = None,
        level: Optional[str] = None,
        score: Optional[int] = None,
        recipients: Optional[list[str]] = None,
    ) -> tuple[bool, str]:
        """Envoie un rapport DLP en pièce jointe via la boîte pilote Graph."""
        creds = self._load_env_credentials()
        to_recipients, cc_recipients = self.resolve_alert_routing(
            category=category,
            level=level,
            score=score,
            explicit_recipients=recipients,
        )
        if justification and justification.strip():
            safe_justification = (
                justification.strip()
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            html_body += f"<p><b>Justification métier :</b> {safe_justification}</p>"
        if not self._live_mode_enabled():
            routed_to = ", ".join(to_recipients) if to_recipients else "non configuré"
            if cc_recipients:
                routed_to += f" (copie : {', '.join(cc_recipients)})"
            return False, (
                "Envoi désactivé : le connecteur M365 est en mode simulation. "
                f"Destinataire(s) prévu(s) : {routed_to}."
            )
        if not to_recipients:
            return False, (
                "Envoi désactivé : configurez routage_validation dans config.yaml "
                "ou DLP_ALERT_RECIPIENTS dans .env."
            )
        if not all([creds["tenant_id"], creds["client_id"], creds["client_secret"], creds["target_user_id"]]):
            return False, "Envoi impossible : configuration Graph pilote incomplète."
        try:
            token = self._acquire_token(creds)
            attachment = base64.b64encode(report_bytes).decode("ascii")
            payload = {
                "message": {
                    "subject": subject,
                    "body": {"contentType": "HTML", "content": html_body},
                    "toRecipients": [{"emailAddress": {"address": address}} for address in to_recipients],
                    "attachments": [{
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": report_name, "contentType": report_content_type, "contentBytes": attachment,
                    }],
                },
                "saveToSentItems": True,
            }
            if cc_recipients:
                payload["message"]["ccRecipients"] = [
                    {"emailAddress": {"address": address}} for address in cc_recipients
                ]
            user_id = quote(creds["target_user_id"], safe="@.")
            self._graph_post(token, f"/users/{user_id}/sendMail", payload)
            success_msg = f"Alerte envoyée avec le rapport PDF en pièce jointe vers {', '.join(to_recipients)}."
            if cc_recipients:
                success_msg += f" Copie RSSI : {', '.join(cc_recipients)}."
            return True, success_msg
        except Exception as exc:
            return False, f"Échec de l'envoi Graph : {exc}"

    def fetch_recent_emails(self, top: int = 5) -> list:
        """Récupère les e-mails récents via Graph API (mode live uniquement)."""
        creds = self._load_env_credentials()
        if not self._live_mode_enabled() or not all([
            creds["tenant_id"], creds["client_id"], creds["client_secret"], creds["target_user_id"]
        ]):
            return self._simulated_emails(top)

        try:
            token = self._acquire_token(creds)
            user_id = quote(creds["target_user_id"], safe="@.")
            mail_path = (
                f"/users/{user_id}/messages"
                f"?$top={top}&$select=subject,from,receivedDateTime,bodyPreview"
            )
            mails = self._graph_get(token, mail_path).get("value", [])

            return [
                GraphMailItem(
                    subject=m.get("subject", "(sans objet)"),
                    sender=m.get("from", {}).get("emailAddress", {}).get("address", "inconnu"),
                    received=m.get("receivedDateTime", "")[:19].replace("T", " "),
                    preview=(m.get("bodyPreview", "")[:200]),
                    item_id=m.get("id", ""),
                )
                for m in mails
            ]
        except Exception:
            return self._simulated_emails(top)

    def _simulated_emails(self, top: int) -> list:
        samples = [
            GraphMailItem(
                subject="Déclaration sinistre n° SIN-2026123 — Client Ben Ali",
                sender="sinistres@comar.tn",
                received=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                preview="Assuré Karim Ben Ali (CIN 01234567, Tél: +216 22 123 456). Montant réclamé : 7 800 TND.",
                item_id="sim-001",
            ),
            GraphMailItem(
                subject="Certificat médical — Arrêt maladie Chaabane",
                sender="rh@comar.tn",
                received=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                preview="Certificat d'arrêt de travail de Youssef Chaabane, 10 jours. Document couvert par le secret médical.",
                item_id="sim-002",
            ),
            GraphMailItem(
                subject="Compte-rendu réunion équipe Sinistres",
                sender="manager@comar.tn",
                received=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                preview="Synthèse de la réunion hebdomadaire du service Sinistres. Diffusion interne uniquement.",
                item_id="sim-003",
            ),
            GraphMailItem(
                subject="Communiqué de presse — Lancement produit 2026",
                sender="communication@comar.tn",
                received=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                preview="COMAR Assurances annonce le lancement de sa nouvelle gamme à Tunis.",
                item_id="sim-004",
            ),
            GraphMailItem(
                subject="FW: Coordonnées bancaires client Trabelsi",
                sender="finance@comar.tn",
                received=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                preview="IBAN TN59 1234 5678 9012 3456 7890 1234, RIB 12345678901234567890. Accès restreint Finance.",
                item_id="sim-005",
            ),
        ]
        return samples[:top]


if __name__ == "__main__":
    m365 = M365Integration()
    status = m365.get_connection_status()
    print(f"Mode : {status.mode} | Connecté : {status.connected}")
    print(f"Message : {status.message}")
    print("\nMapping étiquettes :")
    for m in m365.get_all_label_mappings():
        print(f"  {m.level} -> {m.microsoft_label}")

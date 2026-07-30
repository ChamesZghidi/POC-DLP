"""
policy.py
Étape 4 du pipeline DLP : moteur de règles appliquant une politique d'usage
en fonction du niveau de confidentialité décidé par l'IA.

Important : ce moteur n'intervient JAMAIS dans la décision de classification.
Il prend la classe (C1-C4) déjà déterminée par le modèle IA en entrée, et
applique des règles d'AUTORISATION D'ACTIONS (imprimer, copier, télécharger,
partager) -- exactement comme le ferait un connecteur Microsoft Purview
DLP en aval d'une classification de sensibilité.
"""

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Politique par niveau de confidentialité
# ---------------------------------------------------------------------------
# journalisation : l'action est toujours enregistrée dans l'historique
# autorise       : l'action est autorisée (True) ou bloquée (False)

POLICY = {
    "C1": {
        "description": "Public — accès libre, sans restriction.",
        "impression": True,
        "copie": True,
        "telechargement": True,
        "partage": True,
        "journalisation": False,
    },
    "C2": {
        "description": "Interne — autorisé, mais toutes les actions sont journalisées.",
        "impression": True,
        "copie": True,
        "telechargement": True,
        "partage": True,
        "journalisation": True,
    },
    "C3": {
        "description": "Confidentiel — impression bloquée, autres actions journalisées.",
        "impression": False,
        "copie": True,
        "telechargement": True,
        "partage": True,
        "journalisation": True,
    },
    "C4": {
        "description": "Hautement confidentiel — impression, copie, téléchargement et partage interdits.",
        "impression": False,
        "copie": False,
        "telechargement": False,
        "partage": False,
        "journalisation": True,
    },
}

ACTION_LABELS = {
    "impression": "Imprimer",
    "copie": "Copier",
    "telechargement": "Télécharger",
    "partage": "Partager",
}


@dataclass
class ActionCheckResult:
    action: str
    level: str
    allowed: bool
    alert_triggered: bool
    message: str


def check_action(level: str, action: str) -> ActionCheckResult:
    """
    Vérifie si une action (impression, copie, téléchargement, partage) est
    autorisée pour un document classé à un niveau donné, et détermine si
    une alerte doit être déclenchée (cas d'une action bloquée).
    """
    if level not in POLICY:
        raise ValueError(f"Niveau de confidentialité inconnu : {level}")
    if action not in ACTION_LABELS:
        raise ValueError(f"Action inconnue : {action}")

    rules = POLICY[level]
    allowed = rules[action]
    action_label = ACTION_LABELS[action]

    if allowed:
        message = f"✅ Action « {action_label} » autorisée pour un document {level}."
        if rules["journalisation"]:
            message += " (journalisée)"
        alert = False
    else:
        message = (
            f"🔴 Alerte DLP : tentative de « {action_label} » bloquée sur un "
            f"document classé {level} ({rules['description']})"
        )
        alert = True

    return ActionCheckResult(
        action=action,
        level=level,
        allowed=allowed,
        alert_triggered=alert,
        message=message,
    )


@dataclass
class TransferCheckResult:
    allowed: bool
    alert_triggered: bool
    message: str
    reason: str


def is_internal_email(email_str: str) -> bool:
    """Vérifie si une adresse e-mail appartient au domaine COMAR/HAYETT."""
    if not email_str:
        return False
    email_str = email_str.lower().strip()
    if "@" in email_str:
        domain = email_str.split("@")[-1]
        return domain in ("comar.tn", "comar.com.tn", "hayett.com.tn")
    return False


def check_transfer_policy(
    level: str,
    sender: str,
    recipient: str,
    channel: str,
    is_encrypted: bool,
    justification: str | None = None,
) -> TransferCheckResult:
    """
    Simule la politique COMAR d'encadrement des transferts internes et externes (C1-C4) :
    - Canaux autorisés : Teams Pro, OneDrive Pro, Exchange Pro.
    - Canaux interdits : Messagerie perso, Clé USB non chiffrée, etc.
    - Destinataires : Internes vs Externes.
    - Chiffrement : Obligatoire pour C3 (si externe) et C4 (interne).
    """
    if level not in POLICY:
        raise ValueError(f"Niveau inconnu : {level}")

    dest_interne = is_internal_email(recipient)
    canal_approuve = channel in (
        "Teams professionnel",
        "OneDrive d'entreprise",
        "Exchange Online (Pro)",
    )

    # 1. Niveau C1 - Public
    if level == "C1":
        return TransferCheckResult(
            allowed=True,
            alert_triggered=False,
            message="✅ Transfert autorisé (Document Public C1).",
            reason="Les documents Publics ne font l'objet d'aucune restriction de diffusion.",
        )

    # Vérification commune du canal pour C2/C3/C4
    if not canal_approuve:
        return TransferCheckResult(
            allowed=False,
            alert_triggered=True,
            message="🔴 Transfert Bloqué : Canal non autorisé.",
            reason=f"Le canal '{channel}' n'est pas approuvé par la politique de sécurité COMAR pour les documents sensibles ({level}).",
        )

    # 2. Niveau C2 - Interne
    if level == "C2":
        if not dest_interne:
            return TransferCheckResult(
                allowed=False,
                alert_triggered=True,
                message="🔴 Transfert Bloqué : Destinataire externe interdit.",
                reason="Les informations de niveau C2 (Interne) ne doivent pas être transmises à des tiers externes.",
            )
        return TransferCheckResult(
            allowed=True,
            alert_triggered=False,
            message="✅ Transfert autorisé en interne.",
            reason="Le document C2 est envoyé à un collaborateur via un canal sécurisé.",
        )

    # 3. Niveau C3 - Confidentiel
    if level == "C3":
        if not dest_interne:
            if not justification or not justification.strip():
                return TransferCheckResult(
                    allowed=False,
                    alert_triggered=True,
                    message="🔴 Transfert Bloqué : justification métier obligatoire.",
                    reason="Le transfert externe d'un document C3 (Confidentiel) requiert une justification métier et un chiffrement conforme à la politique COMAR.",
                )
            if is_encrypted:
                return TransferCheckResult(
                    allowed=True,
                    alert_triggered=False,
                    message="✅ Transfert autorisé vers l'externe (Chiffré).",
                    reason="Le transfert externe d'un document C3 (Confidentiel) est autorisé car la pièce jointe est chiffrée, partagée via un outil approuvé et justifiée par un besoin métier.",
                )
            else:
                return TransferCheckResult(
                    allowed=False,
                    alert_triggered=True,
                    message="🔴 Transfert Bloqué : Destinataire externe interdit sans chiffrement.",
                    reason="Le transfert externe d'un document C3 (Confidentiel) requiert impérativement un chiffrement de la pièce jointe et une justification métier.",
                )
        # Interne
        return TransferCheckResult(
            allowed=True,
            alert_triggered=False,
            message="✅ Transfert autorisé en interne.",
            reason="Le document C3 est partagé de manière sécurisée au sein du réseau COMAR.",
        )

    # 4. Niveau C4 - Hautement Confidentiel
    if level == "C4":
        if not dest_interne:
            return TransferCheckResult(
                allowed=False,
                alert_triggered=True,
                message="🔴 Transfert Bloqué : Sortie externe interdite.",
                reason="Les informations de niveau C4 (Hautement Confidentiel) ne peuvent jamais être transmises hors de l'organisation, même avec une justification métier.",
            )
        # Interne
        if is_encrypted:
            return TransferCheckResult(
                allowed=True,
                alert_triggered=False,
                message="✅ Transfert autorisé en interne (Chiffré).",
                reason="Le partage d'un document C4 en interne est autorisé car il est chiffré et transite par un canal approuvé.",
            )
        else:
            return TransferCheckResult(
                allowed=False,
                alert_triggered=True,
                message="🔴 Transfert Bloqué : Chiffrement interne obligatoire.",
                reason="Le partage interne d'un document C4 (Hautement Confidentiel) nécessite un chiffrement obligatoire.",
            )

    return TransferCheckResult(
        allowed=False, alert_triggered=True, message="🔴 Bloqué par défaut.", reason="Erreur de règle."
    )


if __name__ == "__main__":
    for level in ["C1", "C2", "C3", "C4"]:
        print(f"\n--- Niveau {level} : {POLICY[level]['description']} ---")
        for action in ACTION_LABELS:
            result = check_action(level, action)
            print(f"  {result.message}")

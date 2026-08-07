"""
dashboard.py (v3 - édition professionnelle)
Tableau de bord Streamlit pour RSSI/DPO.

Nouveautés v3 :
    - Interface professionnelle : bandeau d'en-tête, badges colorés par
      niveau, cartes KPI, onglets, graphiques Plotly.
    - Support de l'analyse d'e-mails (.eml), en plus de Word/PDF/texte.
    - Actions RÉELLEMENT fonctionnelles (dans les limites d'une application
      web locale, cf. cahier des charges = simulation DLP, pas un agent de
      production) :
        - Télécharger : téléchargement réel du fichier (si autorisé)
        - Imprimer    : ouvre la vraie boîte de dialogue d'impression du
                        navigateur sur le contenu du document (si autorisé)
        - Copier      : copie réelle du texte dans le presse-papiers (si autorisé)
        - Partager    : ouvre un e-mail pré-rempli dans le client de
                        messagerie par défaut (si autorisé)
      Chaque action passe par le moteur de règles (policy.py) : si le
      niveau de confidentialité l'interdit, l'action réelle n'est pas
      exécutée et une alerte est déclenchée à la place.

Lancer avec :
    streamlit run src/dashboard.py
"""

import json
import hashlib
import tempfile
import re
import html
from urllib.parse import urlencode
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from extraction import extract_text
from classification import CamembertClassifier, classify_demo_without_model, classify_archive_items
from scoring import compute_score
from policy import check_action, check_transfer_policy, ACTION_LABELS
from taxonomy import CATEGORIES, CATEGORY_RISK_WEIGHT, DOCUMENT_TYPES
from m365_integration import M365Integration
from reporting import build_document_report_pdf


# ---------------------------------------------------------------------------
# Configuration & style
# ---------------------------------------------------------------------------

st.set_page_config(page_title="DLP POC - COMAR", page_icon="🛡️", layout="wide")

LEVEL_COLORS = {
    "C1": "#2E7D32",  # vert
    "C2": "#1565C0",  # bleu
    "C3": "#E65100",  # orange
    "C4": "#C62828",  # rouge
}
LEVEL_LABELS = {
    "C1": "Public",
    "C2": "Interne",
    "C3": "Confidentiel",
    "C4": "Hautement Confidentiel",
}

CUSTOM_CSS = """
<style>
    .dlp-header {
        background: linear-gradient(90deg, #0F2A43 0%, #1F3B57 100%);
        padding: 1.6rem 2rem;
        border-radius: 10px;
        margin-bottom: 1.4rem;
    }
    .dlp-header h1 { color: #FFFFFF; margin: 0; font-size: 1.7rem; }
    .dlp-header p { color: #C7D4E0; margin: 0.3rem 0 0 0; font-size: 0.95rem; }

    .kpi-card {
        background: #FFFFFF;
        border: 1px solid #E3E8EC;
        border-left: 5px solid #1F3B57;
        border-radius: 8px;
        padding: 0.9rem 1.1rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }
    .kpi-card .kpi-label { font-size: 0.78rem; color: #5A6B7B; text-transform: uppercase; letter-spacing: 0.03em; }
    .kpi-card .kpi-value { font-size: 1.6rem; font-weight: 700; color: #1F3B57; }

    .level-badge {
        display: inline-block; padding: 0.25rem 0.7rem; border-radius: 999px;
        color: white; font-weight: 600; font-size: 0.85rem;
    }
    .section-title {
        font-size: 1.05rem; font-weight: 700; color: #1F3B57;
        margin-top: 0.4rem; margin-bottom: 0.6rem; border-bottom: 2px solid #EEF2F5; padding-bottom: 0.4rem;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "camembert_dlp"
LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "comar_logo.jpg"


def highlight_entities(text: str, entities_found: list) -> str:
    """
    Surligne dans le texte (en HTML) les entités trouvées à l'aide de regex.
    """
    from classification import ENTITY_PATTERNS

    # Convert text to HTML-safe string
    html_text = html.escape(text)

    # mapping keys to display colors and labels
    colors = {
        "email": ("#FFF3CD", "#856404", "EMAIL"),
        "iban": ("#F8D7DA", "#721C24", "IBAN"),
        "numero_secu": ("#D1ECF1", "#0C5460", "N° SÉCU"),
        "montant": ("#E2E3E5", "#383D41", "MONTANT"),
        "cin_tunisie": ("#FFE8D6", "#A0522D", "CIN TN"),
        "tel_tunisie": ("#D4EDDA", "#155724", "TÉL TN"),
        "matricule_fiscal_tn": ("#E8D4F7", "#5B108F", "MATR. FISCAL TN"),
    }

    # Replace pattern matches in HTML text
    for name in entities_found:
        if name in ENTITY_PATTERNS and name in colors:
            bg, fg, label = colors[name]
            pattern = ENTITY_PATTERNS[name]

            def repl(match):
                matched_val = match.group(0)
                return f'<span style="background-color:{bg}; color:{fg}; padding:2px 4px; border-radius:4px; font-weight:bold; border:1px solid {fg}50;">{matched_val} [{label}]</span>'

            try:
                html_text = re.sub(pattern, repl, html_text, flags=re.IGNORECASE)
            except Exception:
                pass
    return html_text


@st.cache_resource
def load_ai_model():
    if MODEL_DIR.exists():
        try:
            return CamembertClassifier(model_path=str(MODEL_DIR))
        except Exception as e:
            st.warning(f"Impossible de charger le modèle IA ({e}).")
    return None


ai_model = load_ai_model()

# --- État de session ---
if "documents" not in st.session_state:
    st.session_state.documents = {}
if "action_log" not in st.session_state:
    st.session_state.action_log = []
if "transfer_decisions" not in st.session_state:
    st.session_state.transfer_decisions = {}


def level_badge(level: str) -> str:
    color = LEVEL_COLORS.get(level, "#888")
    label = LEVEL_LABELS.get(level, level)
    return f'<span class="level-badge" style="background:{color}">{level} · {label}</span>'


def kpi_card(label: str, value) -> str:
    return f"""<div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
    </div>"""


def build_policy_rows(level: str) -> list[dict]:
    rows = []
    for action in ACTION_LABELS:
        rule = check_action(level, action)
        rows.append({
            "action": ACTION_LABELS[action], "status": "BLOQUÉ" if not rule.allowed else "AUTORISÉ", "reason": rule.message,
        })
    return rows


# ---------------------------------------------------------------------------
# Composants JS réels : impression et copie presse-papiers
# ---------------------------------------------------------------------------

def render_print_button(doc_title: str, text: str, key: str):
    """Bouton qui ouvre la VRAIE boîte de dialogue d'impression du navigateur
    sur le contenu du document (pas la page entière du dashboard)."""
    safe_text = json.dumps(text)
    safe_title = json.dumps(doc_title)
    html = f"""
    <button id="printBtn_{key}" style="
        background:#1F3B57;color:white;border:none;padding:0.5rem 1rem;
        border-radius:6px;cursor:pointer;font-size:0.9rem;width:100%;">
        🖨️ Imprimer
    </button>
    <script>
        document.getElementById("printBtn_{key}").onclick = function() {{
            const w = window.open("", "_blank");
            const content = {safe_text};
            const title = {safe_title};
            w.document.write("<html><head></head><body><h3></h3><pre style='white-space:pre-wrap;font-family:sans-serif;'></pre></body></html>");
            w.document.close();
            w.document.title = title;
            w.document.querySelector("h3").textContent = title;
            w.document.querySelector("pre").textContent = content;
            w.focus();
            setTimeout(function() {{ w.print(); }}, 300);
        }};
    </script>
    """
    components.html(html, height=50)


def render_copy_button(text: str, key: str):
    """Bouton qui copie RÉELLEMENT le texte du document dans le presse-papiers."""
    safe_text = json.dumps(text)
    html = f"""
    <button id="copyBtn_{key}" style="
        background:#1F3B57;color:white;border:none;padding:0.5rem 1rem;
        border-radius:6px;cursor:pointer;font-size:0.9rem;width:100%;">
        📋 Copier le texte
    </button>
    <span id="copyMsg_{key}" style="margin-left:8px;color:#2E7D32;font-size:0.85rem;"></span>
    <script>
        document.getElementById("copyBtn_{key}").onclick = function() {{
            const copy = navigator.clipboard ? navigator.clipboard.writeText({safe_text}) : Promise.reject();
            copy.then(function() {{
                document.getElementById("copyMsg_{key}").innerText = "✅ Copié";
            }}).catch(function() {{
                document.getElementById("copyMsg_{key}").innerText = "Copie refusée par le navigateur";
            }});
        }};
    </script>
    """
    components.html(html, height=50)


def render_share_link(doc_title: str, level: str, key: str):
    """Ouvre un e-mail pré-rempli dans le client de messagerie par défaut
    (lien mailto: réel)."""
    subject = f"Partage document {level} - {doc_title}"
    body = f"Bonjour,\n\nVeuillez trouver ci-joint le document '{doc_title}' (niveau {level}).\n\nCordialement."
    mailto = "mailto:?" + urlencode({"subject": subject, "body": body})
    st.markdown(
        f'<a href="{mailto}" target="_blank" style="text-decoration:none;">'
        f'<button style="background:#1F3B57;color:white;border:none;padding:0.5rem 1rem;'
        f'border-radius:6px;cursor:pointer;font-size:0.9rem;width:100%;">✉️ Partager par e-mail</button></a>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# En-tête
# ---------------------------------------------------------------------------

header_logo, header_text = st.columns([1, 5], vertical_alignment="center")
with header_logo:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), use_container_width=True)
with header_text:
    st.markdown("""<div class="dlp-header">
        <h1>Centre de contrôle DLP</h1>
        <p>COMAR Assurances · Classification, protection et traçabilité des données sensibles</p>
    </div>""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### ⚙️ Statut du moteur")
    if ai_model is not None:
        st.success("🤖 Modèle IA actif\n\nLa classe C1-C4 est décidée uniquement par CamemBERT.")
    else:
        st.error(
            "⚠️ Aucun modèle entraîné trouvé.\n\nMode démonstration (mots-clés) — "
            "à ne pas présenter comme le résultat de l'IA.\n\n"
            "Lancer : `train_camembert.py`"
        )

    st.markdown("### 📎 Formats supportés")
    st.caption("Word (.docx) · PDF (.pdf) · Texte (.txt/.csv/.json) · E-mail (.eml) · XML · ZIP")

    st.markdown("---")
    if st.button("🔄 Réinitialiser les données de la session"):
        st.session_state.documents = {}
        st.session_state.action_log = []
        st.session_state.transfer_decisions = {}
        st.rerun()

tab_analyse, tab_overview, tab_map, tab_m365 = st.tabs([
    "📄 Analyser un document", "📊 Vue d'ensemble", "🗂️ Cartographie des données", "☁️ Trajectoire M365",
])

# ---------------------------------------------------------------------------
# Onglet 1 : Analyse + actions
# ---------------------------------------------------------------------------
with tab_analyse:
    st.markdown('<div class="section-title">Déposer un document ou un e-mail</div>', unsafe_allow_html=True)
    uploaded_file = st.file_uploader(
        "Formats acceptés : Word, PDF, texte, e-mail, XML ou ZIP (archives analysées sans extraction sur disque)",
        type=["docx", "pdf", "txt", "csv", "json", "log", "md", "eml", "xml", "zip"],
    )

    if uploaded_file is not None:
        suffix = Path(uploaded_file.name).suffix
        file_bytes = uploaded_file.getvalue()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            extracted = extract_text(tmp_path)
        except (ValueError, OSError) as exc:
            st.error(f"Analyse impossible : {exc}")
            extracted = None
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        if extracted is None:
            st.stop()
        text = extracted["text"]
        metadata = extracted["metadata"]

        if not text.strip():
            st.warning("Aucun texte exploitable n'a été extrait. Le fichier peut être vide, chiffré ou composé uniquement d'images.")
            st.stop()

        if metadata.get("format") == "zip":
            st.info(
                f"Archive analysée : {len(metadata.get('analysed_files', []))} fichier(s) exploitable(s), "
                f"{len(metadata.get('skipped_files', []))} ignoré(s), {len(metadata.get('extraction_errors', []))} erreur(s)."
            )

        archive_details = []
        if metadata.get("format") == "zip" and metadata.get("analysis_items"):
            classification, archive_details = classify_archive_items(metadata["analysis_items"], ai_model)
        elif ai_model is not None:
            classification = ai_model.predict(text)
        else:
            classification = classify_demo_without_model(text)

        scoring = compute_score(classification)

        doc_id = hashlib.sha256(file_bytes).hexdigest()[:12]
        st.session_state.documents[doc_id] = {
            "id": doc_id,
            "fichier": uploaded_file.name,
            "niveau": scoring.level,
            "score": scoring.score,
            "categorie": scoring.category,
            "confiance": scoring.confidence,
            "alerte_classification": scoring.alert_triggered,
            "texte": text,
            "metadata": metadata,
            "bytes": file_bytes,
            "mime": uploaded_file.type or "application/octet-stream",
            "horodatage": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "archive_details": archive_details,
        }

        st.markdown(level_badge(scoring.level), unsafe_allow_html=True)
        st.write("")

        if metadata.get("est_email", False):
            st.markdown(
                f"""
                <div style="background-color:#E8F4FD; padding:15px; border-radius:8px; border-left:5px solid #29B6F6; margin-bottom:15px;">
                    <h5 style="color:#0288D1; margin:0 0 8px 0;">📧 E-mail Analysé</h5>
                    <p style="margin:2px 0; font-size:0.95rem;"><b>Sujet :</b> {metadata.get('sujet')}</p>
                    <p style="margin:2px 0; font-size:0.95rem;"><b>Expéditeur :</b> {metadata.get('expediteur')}</p>
                    <p style="margin:2px 0; font-size:0.95rem;"><b>Destinataire :</b> {metadata.get('destinataire')}</p>
                    <p style="margin:2px 0; font-size:0.95rem;"><b>Date :</b> {metadata.get('date')}</p>
                </div>
                """,
                unsafe_allow_html=True
            )

        c1, c2, c3 = st.columns(3)
        c1.markdown(kpi_card("Score de risque", f"{scoring.score} / 100"), unsafe_allow_html=True)
        c2.markdown(kpi_card("Catégorie détectée", scoring.category), unsafe_allow_html=True)
        c3.markdown(kpi_card("Confiance IA", f"{scoring.confidence:.0%}" if ai_model else "N/A (démo)"), unsafe_allow_html=True)

        st.write("")
        if scoring.alert_triggered:
            st.error(f"🔴 Alerte de classification : {scoring.reason}")
        else:
            st.info(scoring.reason)

        if classification.safeguards:
            st.warning(
                "Protection renforcée appliquée : " + " · ".join(classification.safeguards)
                + ". La décision reste à valider par le RSSI/DPO en cas de doute."
            )

        if archive_details:
            st.markdown("#### DÃ©tail de l’archive")
            st.caption("Le niveau et la catÃ©gorie affichÃ©s correspondent au fichier le plus sensible ; chaque fichier est analysÃ© sÃ©parÃ©ment.")
            st.dataframe(pd.DataFrame(archive_details), use_container_width=True, hide_index=True)

        if scoring.score > 80:
            st.warning("⚠️ Intervention humaine requise : ce document dépasse le seuil de risque 80/100. Vérifiez la classification et les destinataires avant toute diffusion.")

        policy_rows = build_policy_rows(scoring.level)
        report_pdf = build_document_report_pdf(
            st.session_state.documents[doc_id], policy_rows,
            [item for item in st.session_state.action_log if item["document"] == uploaded_file.name],
        )
        m365 = M365Integration()
        alert_to, alert_cc = m365.resolve_alert_routing(
            category=scoring.category, level=scoring.level, score=scoring.score,
        )
        report_col, email_col = st.columns(2)
        with report_col:
            st.download_button("Télécharger le rapport DLP (PDF)", report_pdf, f"rapport-dlp-{doc_id}.pdf", "application/pdf", use_container_width=True)
        with email_col:
            if alert_to:
                routing_hint = f"Validateur {scoring.category} : **{alert_to[0]}**"
                if alert_cc:
                    routing_hint += f" · Copie RSSI : **{', '.join(alert_cc)}**"
                st.caption(routing_hint)
            if st.button("Envoyer l'alerte et le rapport", key=f"send_alert_{doc_id}", use_container_width=True):
                sent, message = M365Integration().send_dlp_alert(
                    subject=f"[DLP {scoring.level}] {uploaded_file.name} · score {scoring.score}/100",
                    html_body=f"<h2>Alerte DLP COMAR</h2><p>Document : <b>{html.escape(uploaded_file.name)}</b></p><p>Catégorie : <b>{html.escape(scoring.category)}</b></p><p>Niveau : <b>{scoring.level}</b> · Score : <b>{scoring.score}/100</b></p><p>Le rapport PDF détaillé est joint.</p>",
                    report_bytes=report_pdf, report_name=f"rapport-dlp-{doc_id}.pdf",
                    category=scoring.category, level=scoring.level, score=scoring.score,
                )
                (st.success if sent else st.warning)(message)

        with st.expander("Voir le contenu extrait (avec surlignage des risques)"):
            if classification.entities_found:
                highlighted = highlight_entities(text[:4000], classification.entities_found)
                st.markdown(
                    f'<div style="background-color:#F8F9FA; padding:15px; border-radius:8px; '
                    f'border:1px solid #E3E8EC; font-family:monospace; white-space:pre-wrap; '
                    f'font-size:0.9rem; max-height:400px; overflow-y:auto;">{highlighted}</div>',
                    unsafe_allow_html=True
                )
            else:
                st.text(text[:3000])

        st.markdown('<div class="section-title">Actions sur ce document (politique DLP appliquée)</div>', unsafe_allow_html=True)
        st.caption(f"Politique du niveau {scoring.level} : impression {'autorisée' if check_action(scoring.level,'impression').allowed else 'bloquée'}, "
                   f"copie {'autorisée' if check_action(scoring.level,'copie').allowed else 'bloquée'}, "
                   f"téléchargement {'autorisé' if check_action(scoring.level,'telechargement').allowed else 'bloqué'}, "
                   f"partage {'autorisé' if check_action(scoring.level,'partage').allowed else 'bloqué'}.")

        act1, act2, act3, act4 = st.columns(4)

        # --- Imprimer ---
        with act1:
            res = check_action(scoring.level, "impression")
            if res.allowed:
                render_print_button(uploaded_file.name, text, doc_id)
            else:
                st.button("🖨️ Imprimer", disabled=True, key=f"print_disabled_{doc_id}")
                st.caption("🔒 Bloqué")

        # --- Copier ---
        with act2:
            res = check_action(scoring.level, "copie")
            if res.allowed:
                render_copy_button(text, doc_id)
            else:
                st.button("📋 Copier", disabled=True, key=f"copy_disabled_{doc_id}")
                st.caption("🔒 Bloqué")

        # --- Télécharger ---
        with act3:
            res = check_action(scoring.level, "telechargement")
            if res.allowed:
                st.download_button(
                    "⬇️ Télécharger", data=file_bytes, file_name=uploaded_file.name,
                    mime=uploaded_file.type, key=f"dl_{doc_id}", use_container_width=True,
                )
            else:
                st.button("⬇️ Télécharger", disabled=True, key=f"dl_disabled_{doc_id}")
                st.caption("🔒 Bloqué")

        # --- Partager ---
        with act4:
            res = check_action(scoring.level, "partage")
            if res.allowed:
                render_share_link(uploaded_file.name, scoring.level, doc_id)
            else:
                st.button("✉️ Partager", disabled=True, key=f"share_disabled_{doc_id}")
                st.caption("🔒 Bloqué")

        st.write("")
        st.markdown('<div class="section-title">✈️ Simulateur de Transfert (Politique de transfert COMAR)</div>', unsafe_allow_html=True)
        st.caption("Simulez l'envoi de ce document pour valider les règles de transfert (canaux approuvés, destinataires internes/externes, chiffrement).")

        category_validator = m365.get_validation_recipient(scoring.category)
        transfer_alert_to, transfer_alert_cc = m365.resolve_alert_routing(
            category=scoring.category, level=scoring.level, score=scoring.score,
        )

        with st.form(key=f"transfer_form_{doc_id}"):
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                recipient_email = st.text_input(
                    "Adresse e-mail du destinataire",
                    value=category_validator,
                    help=f"Prérempli selon la catégorie détectée ({scoring.category}). Modifiable si le transfert cible un autre interlocuteur.",
                    key=f"recip_{doc_id}",
                )

                default_send = metadata.get("expediteur", "dpo@comar.tn") if metadata.get("est_email", False) else "dpo@comar.tn"
                sender_email = st.text_input("Adresse e-mail de l'expéditeur", value=default_send, key=f"send_{doc_id}")

                justification = st.text_area(
                    "Justification métier",
                    value="",
                    placeholder="Décrivez le besoin opérationnel justifiant ce transfert (contexte, urgence, destinataire concerné…).",
                    help="Obligatoire pour certains transferts externes de documents C3.",
                    key=f"just_{doc_id}",
                    height=80,
                )
            with col_t2:
                channel_opt = st.selectbox(
                    "Canal de transfert",
                    options=[
                        "Teams professionnel",
                        "OneDrive d'entreprise",
                        "Exchange Online (Pro)",
                        "Messagerie personnelle (Gmail, Yahoo...)",
                        "Clé USB non chiffrée",
                        "Messagerie instantanée grand public (WhatsApp, etc.)"
                    ],
                    key=f"chan_{doc_id}"
                )
                is_encrypted = st.checkbox("Chiffrer la pièce jointe / le support", value=False, key=f"enc_{doc_id}")

            if transfer_alert_cc:
                st.caption(
                    f"En cas d'alerte ou de demande de validation, copie RSSI : **{', '.join(transfer_alert_cc)}** "
                    f"(document {scoring.level}, catégorie {scoring.category})."
                )

            submit_transfer = st.form_submit_button("Valider le transfert DLP", use_container_width=True)

            if submit_transfer:
                from policy import check_transfer_policy
                res_transfer = check_transfer_policy(
                    level=scoring.level,
                    sender=sender_email,
                    recipient=recipient_email,
                    channel=channel_opt,
                    is_encrypted=is_encrypted,
                    justification=justification,
                )

                if res_transfer.allowed:
                    st.success(f"{res_transfer.message}\n\n**Justification** : {res_transfer.reason}")
                    st.session_state.action_log.append({
                        "horodatage": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "document": uploaded_file.name,
                        "niveau": scoring.level,
                        "action": f"Partage vers {recipient_email} ({channel_opt})",
                        "resultat": "Autorisé" + (" (Chiffré)" if is_encrypted else ""),
                        "motif": res_transfer.reason,
                    })
                else:
                    st.error(f"{res_transfer.message}\n\n**Motif du blocage** : {res_transfer.reason}")
                    st.session_state.action_log.append({
                        "horodatage": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "document": uploaded_file.name,
                        "niveau": scoring.level,
                        "action": f"Partage vers {recipient_email} ({channel_opt})",
                        "resultat": "Bloqué",
                        "motif": res_transfer.reason,
                    })
                st.session_state.transfer_decisions[doc_id] = {
                    "allowed": res_transfer.allowed, "recipient": recipient_email, "channel": channel_opt,
                    "reason": res_transfer.reason, "encrypted": is_encrypted,
                    "justification": justification,
                }

        decision = st.session_state.transfer_decisions.get(doc_id)
        if decision:
            status_label = "Autorisé par la politique locale" if decision["allowed"] else "Bloqué par la politique locale"
            st.markdown(f"**Dernière décision :** {status_label} · Canal : {decision['channel']} · Destinataire : {decision['recipient']}")
            st.caption(f"Motif : {decision['reason']}")
            if decision["allowed"] and scoring.score <= 80:
                st.success("Pour un environnement réel, effectuez ensuite le partage dans Exchange, Teams, OneDrive ou SharePoint : la politique Purview appliquera la protection côté Microsoft 365.")
            else:
                validator_email = transfer_alert_to[0] if transfer_alert_to else category_validator
                cc_label = f" (copie RSSI : {', '.join(transfer_alert_cc)})" if transfer_alert_cc else ""
                if st.button(f"Demander une validation à {validator_email}{cc_label}", key=f"approval_{doc_id}", use_container_width=True):
                    updated_pdf = build_document_report_pdf(
                        st.session_state.documents[doc_id], policy_rows,
                        [item for item in st.session_state.action_log if item["document"] == uploaded_file.name],
                    )
                    sent, message = M365Integration().send_dlp_alert(
                        subject=f"[Validation DLP] {uploaded_file.name} · {scoring.level} · score {scoring.score}/100",
                        html_body=(
                            f"<h2>Validation DLP requise</h2>"
                            f"<p>Document : <b>{html.escape(uploaded_file.name)}</b></p>"
                            f"<p>Catégorie : <b>{html.escape(scoring.category)}</b></p>"
                            f"<p>Destinataire demandé : <b>{html.escape(decision['recipient'])}</b></p>"
                            f"<p>Canal : <b>{html.escape(decision['channel'])}</b></p>"
                            f"<p>Motif : {html.escape(decision['reason'])}</p>"
                            f"<p>Le document n'est pas transmis par cette demande. Le rapport PDF est joint.</p>"
                        ),
                        report_bytes=updated_pdf, report_name=f"validation-dlp-{doc_id}.pdf",
                        category=scoring.category, level=scoring.level, score=scoring.score,
                        justification=decision.get("justification"),
                    )
                    (st.success if sent else st.warning)(message)

# ---------------------------------------------------------------------------
# Onglet 2 : Vue d'ensemble
# ---------------------------------------------------------------------------
with tab_overview:
    docs = list(st.session_state.documents.values())
    logs = st.session_state.action_log

    if docs:
        total_docs = len(docs)
        nb_par_niveau = {lvl: sum(1 for d in docs if d["niveau"] == lvl) for lvl in ["C1", "C2", "C3", "C4"]}
        nb_alertes = sum(1 for l in logs if l["resultat"] == "Bloqué") + sum(1 for d in docs if d["alerte_classification"])
        nb_bloques = len({(l["document"]) for l in logs if l["resultat"] == "Bloqué"})
        score_moyen = round(sum(d["score"] for d in docs) / total_docs, 1)

        st.markdown('<div class="section-title">Indicateurs clés</div>', unsafe_allow_html=True)
        k1, k2, k3, k4 = st.columns(4)
        k1.markdown(kpi_card("Documents analysés", total_docs), unsafe_allow_html=True)
        k2.markdown(kpi_card("Alertes déclenchées", nb_alertes), unsafe_allow_html=True)
        k3.markdown(kpi_card("Documents bloqués", nb_bloques), unsafe_allow_html=True)
        k4.markdown(kpi_card("Score moyen", f"{score_moyen} / 100"), unsafe_allow_html=True)

        st.write("")
        k5, k6, k7, k8 = st.columns(4)
        k5.markdown(kpi_card("C1 · Public", nb_par_niveau["C1"]), unsafe_allow_html=True)
        k6.markdown(kpi_card("C2 · Interne", nb_par_niveau["C2"]), unsafe_allow_html=True)
        k7.markdown(kpi_card("C3 · Confidentiel", nb_par_niveau["C3"]), unsafe_allow_html=True)
        k8.markdown(kpi_card("C4 · Hautement confid.", nb_par_niveau["C4"]), unsafe_allow_html=True)

        st.write("")
        st.markdown('<div class="section-title">Répartition des documents par niveau</div>', unsafe_allow_html=True)

        col_chart1, col_chart2 = st.columns([2, 1])
        with col_chart1:
            fig = go.Figure(data=[go.Bar(
                x=[f"{lvl} · {LEVEL_LABELS[lvl]}" for lvl in nb_par_niveau],
                y=list(nb_par_niveau.values()),
                marker_color=[LEVEL_COLORS[lvl] for lvl in nb_par_niveau],
                text=list(nb_par_niveau.values()),
                textposition="outside",
            )])
            fig.update_layout(
                height=340, margin=dict(t=20, b=20, l=20, r=20),
                yaxis_title="Nombre de documents", xaxis_title=None,
                plot_bgcolor="white",
            )
            st.plotly_chart(fig, use_container_width=True)
        with col_chart2:
            fig_pie = go.Figure(data=[go.Pie(
                labels=list(nb_par_niveau.keys()),
                values=list(nb_par_niveau.values()),
                marker_colors=[LEVEL_COLORS[lvl] for lvl in nb_par_niveau],
                hole=0.5,
            )])
            fig_pie.update_layout(height=340, margin=dict(t=20, b=20, l=10, r=10), showlegend=True)
            st.plotly_chart(fig_pie, use_container_width=True)

        st.caption(
            "💡 Cette répartition permet au RSSI/DPO d'évaluer en un coup d'œil l'exposition globale "
            "au risque (part de documents C3/C4), de détecter une hausse anormale de documents très "
            "sensibles en circulation, et de prioriser les actions de sensibilisation ou de contrôle "
            "sur les services concernés."
        )

        st.markdown('<div class="section-title">Historique des documents analysés</div>', unsafe_allow_html=True)
        df_docs = pd.DataFrame(docs)[["horodatage", "fichier", "niveau", "score", "categorie", "confiance"]]
        st.dataframe(df_docs, use_container_width=True, hide_index=True)

        if logs:
            st.markdown('<div class="section-title">Journal d\'audit des actions</div>', unsafe_allow_html=True)
            df_logs = pd.DataFrame(logs)[["horodatage", "document", "niveau", "action", "resultat"]]
            st.dataframe(df_logs, use_container_width=True, hide_index=True)

    else:
        st.info("Aucun document analysé pour l'instant. Utilise l'onglet « Analyser un document » pour commencer.")

# ---------------------------------------------------------------------------
# Onglet 3 : Cartographie des données sensibles
# ---------------------------------------------------------------------------
with tab_map:
    st.markdown('<div class="section-title">Catégories de données sensibles</div>', unsafe_allow_html=True)
    df_cat = pd.DataFrame([
        {"Catégorie": cat, "Poids de risque": CATEGORY_RISK_WEIGHT[cat], "Description": desc}
        for cat, desc in CATEGORIES.items()
    ])
    st.dataframe(df_cat, use_container_width=True, hide_index=True)

    st.markdown('<div class="section-title">Référentiel type de document → catégorie → niveau</div>', unsafe_allow_html=True)
    df_types = pd.DataFrame([
        {"Type de document": dt.nom, "Catégorie": dt.categorie, "Niveau attendu": dt.niveau}
        for dt in DOCUMENT_TYPES
    ])
    st.dataframe(df_types, use_container_width=True, hide_index=True)
    st.caption(
        "Ce référentiel sert de base à la génération du dataset d'entraînement. "
        "Il doit être validé avec le RSSI/DPO avant tout déploiement réel."
    )

# ---------------------------------------------------------------------------
# Onglet 4 : préparation M365 / Purview (sans écriture sur le tenant)
# ---------------------------------------------------------------------------
with tab_m365:
    st.markdown('<div class="section-title">Préparation Microsoft 365 / Purview</div>', unsafe_allow_html=True)
    m365 = M365Integration()
    status = m365.get_connection_status()
    if status.mode == "live" and status.connected:
        st.success(status.message)
        st.caption(f"Boîte pilote : {status.user_email} · Tenant : {status.tenant_id}")
    elif status.mode == "error":
        st.error(status.message)
    else:
        st.info(status.message)

    st.caption("Cette application ne crée, n'active ni ne modifie de politique dans le tenant. Toute mise en production doit être validée dans Microsoft Purview.")
    spec = m365.build_purview_policy_spec()
    st.markdown("#### Règles à valider dans Purview")
    st.dataframe(pd.DataFrame(spec["rules"]), use_container_width=True, hide_index=True)
    st.markdown("#### Garde-fous de déploiement")
    for item in spec["deployment_guardrails"]:
        st.markdown(f"- {item}")
    st.download_button(
        "Télécharger le modèle de politique (JSON)",
        data=json.dumps(spec, ensure_ascii=False, indent=2),
        file_name="comar-purview-dlp-pilot.json",
        mime="application/json",
    )

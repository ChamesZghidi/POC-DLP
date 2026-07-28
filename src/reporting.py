"""Génération du rapport DLP PDF par document."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape


def build_document_report_pdf(document: dict, policy_rows: list[dict], events: list[dict]) -> bytes:
    """Construit un rapport PDF autonome, téléchargeable depuis le dashboard."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    styles = getSampleStyleSheet()
    title = ParagraphStyle("DlpTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=19,
                           leading=23, textColor=colors.HexColor("#123C69"), alignment=TA_LEFT)
    heading = ParagraphStyle("DlpHeading", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12,
                             leading=15, textColor=colors.HexColor("#123C69"), spaceBefore=12, spaceAfter=7)
    body = ParagraphStyle("DlpBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=9,
                          leading=12, textColor=colors.HexColor("#1F2937"))
    document_pdf = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                                     topMargin=1.4 * cm, bottomMargin=1.4 * cm)
    story = []
    logo = Path(__file__).resolve().parent.parent / "assets" / "comar_logo.jpg"
    if logo.exists():
        story.append(Image(str(logo), width=3.0 * cm, height=1.1 * cm, kind="proportional"))
    story.extend([Paragraph("Rapport d'analyse DLP", title), Spacer(1, 0.3 * cm)])
    review = "REVUE HUMAINE REQUISE" if document["score"] > 80 else "Analyse terminée"
    overview = [
        ["Document", escape(str(document["fichier"]))], ["Horodatage", escape(str(document["horodatage"]))],
        ["Classification", f"{escape(str(document['niveau']))} - {escape(str(document['categorie']))}"],
        ["Score de risque", f"{escape(str(document['score']))} / 100"], ["Statut", review],
    ]
    table = Table([[Paragraph(f"<b>{key}</b>", body), Paragraph(value, body)] for key, value in overview], colWidths=[4.2 * cm, 12.6 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF1F8")), ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CAD7E3")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([table, Paragraph("Règles DLP appliquées", heading)])
    policy_data = [[Paragraph("Action", body), Paragraph("Décision", body), Paragraph("Explication", body)]]
    for row in policy_rows:
        policy_data.append([Paragraph(escape(row["action"]), body), Paragraph(escape(row["status"]), body), Paragraph(escape(row["reason"]), body)])
    policy_table = Table(policy_data, colWidths=[3.0 * cm, 3.0 * cm, 10.8 * cm], repeatRows=1)
    policy_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123C69")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CAD7E3")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(policy_table)
    if events:
        story.append(Paragraph("Historique des transferts", heading))
        for event in events:
            line = f"{event['horodatage']} - {event['action']} : {event['resultat']}"
            if event.get("motif"):
                line += f". {event['motif']}"
            story.append(Paragraph(escape(line), body))
    if document["score"] > 80:
        story.extend([Paragraph("Action requise", heading), Paragraph("Le score dépasse 80/100. Le RSSI ou le DPO doit valider la classification, le besoin métier et les destinataires avant toute diffusion.", body)])
    document_pdf.build(story)
    return buffer.getvalue()

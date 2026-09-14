"""Rapport annuel complet en PDF : garde + KPI + compte de gestion + statistiques + plan pluriannuel."""
from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, PageBreak, HRFlowable, TableStyle
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie

from app.services.emailer import _date_fr
from app.services.pdf_base import register_fonts, style, table_style, page_margins, fmt_eur
from app.services.compte_gestion import story_compte_gestion

INDIGO = colors.HexColor("#4f46e5")
ROSE = colors.HexColor("#f43f5e")
VERT = colors.HexColor("#059669")
GRIS = colors.HexColor("#64748b")


def _graphique_mensuel(mouvements, annee: int) -> Drawing:
    """Barres mensuelles encaissements (indigo) vs dépenses (rose)."""
    enc = [0.0] * 12
    dep = [0.0] * 12
    for m in mouvements:
        if m.date.year != annee:
            continue
        i = m.date.month - 1
        if m.type == "encaissement":
            enc[i] += m.montant
        else:
            dep[i] += m.montant
    d = Drawing(440, 190)
    chart = VerticalBarChart()
    chart.x = 40
    chart.y = 30
    chart.width = 380
    chart.height = 130
    chart.data = [enc, dep]
    chart.strokeColor = None
    chart.categoryAxis.categoryNames = [f"{i+1:02d}" for i in range(12)]
    chart.categoryAxis.labels.fontName = "DejaVu"
    chart.categoryAxis.labels.fontSize = 7.5
    chart.valueAxis.valueMin = 0
    chart.valueAxis.valueMax = max(1.0, max(max(enc), max(dep)) * 1.15)
    chart.valueAxis.labelTextFormat = "%d"
    chart.valueAxis.labels.fontName = "DejaVu"
    chart.valueAxis.labels.fontSize = 7.5
    chart.bars[0].fillColor = INDIGO
    chart.bars[1].fillColor = ROSE
    chart.bars[0].strokeColor = None
    chart.bars[1].strokeColor = None
    chart.barWidth = 12
    chart.groupSpacing = 4
    chart.barLabelFormat = None
    d.add(chart)
    # Légende
    from reportlab.graphics.shapes import String, Rect
    d.add(Rect(40, 8, 10, 10, fillColor=INDIGO, strokeColor=None))
    d.add(String(55, 10, "Encaissements", fontName="DejaVu", fontSize=8, fillColor=GRIS))
    d.add(Rect(150, 8, 10, 10, fillColor=ROSE, strokeColor=None))
    d.add(String(165, 10, "Dépenses", fontName="DejaVu", fontSize=8, fillColor=GRIS))
    return d


def _graphique_repartition(enc_charges: float, enc_ft: float, dep_charges: float, dep_ft: float) -> Drawing:
    """Donut : répartition des encaissements (charges / fonds de travaux)."""
    d = Drawing(440, 190)
    pie = Pie()
    pie.x = 140
    pie.y = 25
    pie.width = 140
    pie.height = 140
    pie.data = [max(0, enc_charges), max(0, enc_ft)]
    pie.labels = None
    pie.slices[0].fillColor = INDIGO
    pie.slices[1].fillColor = VERT
    pie.slices[0].strokeColor = colors.white
    pie.slices[1].strokeColor = colors.white
    pie.slices[0].strokeWidth = 3
    pie.slices[1].strokeWidth = 3
    # Donut
    pie.slices[0].popout = 0
    from reportlab.graphics.shapes import Circle, String, Rect
    d.add(pie)
    d.add(Circle(140 + 70, 25 + 70, 42, fillColor=colors.white, strokeColor=None))
    # Légende
    d.add(Rect(30, 60, 12, 12, fillColor=INDIGO, strokeColor=None))
    d.add(String(47, 62, f"Charges : {fmt_eur(enc_charges)}", fontName="DejaVu", fontSize=8.5, fillColor=GRIS))
    d.add(Rect(30, 42, 12, 12, fillColor=VERT, strokeColor=None))
    d.add(String(47, 44, f"Fonds de travaux : {fmt_eur(enc_ft)}", fontName="DejaVu", fontSize=8.5, fillColor=GRIS))
    d.add(String(30, 130, f"Dépenses charges : {fmt_eur(dep_charges)}", fontName="DejaVu", fontSize=8, fillColor=ROSE))
    d.add(String(30, 116, f"Dépenses fonds travaux : {fmt_eur(dep_ft)}", fontName="DejaVu", fontSize=8, fillColor=ROSE))
    return d


def generer_rapport_annuel_pdf(copro, exercice, db) -> BytesIO:
    """Rapport annuel complet : garde, KPI, compte de gestion, statistiques, plan pluriannuel de travaux."""
    from app.models.mouvement import Mouvement
    from app.models.travaux import Travaux
    from app.models.lot import Lot

    register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        title=f"Rapport annuel {copro.nom} {exercice.annee}",
        **page_margins(),
    )
    el = []

    mouvements = db.query(Mouvement).filter(Mouvement.exercice_id == exercice.id).all()
    depenses = [m for m in mouvements if m.type == "depense"]
    encaissements = [m for m in mouvements if m.type == "encaissement"]
    enc_charges = sum(m.montant for m in encaissements if m.categorie != "fonds_travaux")
    enc_ft = sum(m.montant for m in encaissements if m.categorie == "fonds_travaux")
    dep_charges = sum(m.montant for m in depenses if m.categorie != "fonds_travaux")
    dep_ft = sum(m.montant for m in depenses if m.categorie == "fonds_travaux")
    budget = sum(b.montant for b in exercice.budget_lines)
    lots = db.query(Lot).filter(Lot.copropriete_id == copro.id).all()

    total_impayes = 0.0
    from app.models.appel import AppelLot
    for lot in lots:
        appels_c = sum(a.montant_charges for a in db.query(AppelLot).filter(AppelLot.lot_id == lot.id).all())
        appels_f = sum(a.montant_fonds_travaux for a in db.query(AppelLot).filter(AppelLot.lot_id == lot.id).all())
        enc_lot = sum(m.montant for m in db.query(Mouvement).filter(Mouvement.lot_id == lot.id, Mouvement.type == "encaissement").all())
        if appels_c + appels_f - enc_lot > 0.005:
            total_impayes += appels_c + appels_f - enc_lot

    # ===== Page de garde =====
    el.append(Spacer(1, 60))
    el.append(Paragraph("RAPPORT ANNUEL", style("titre", fontSize=24)))
    el.append(Paragraph(f"Exercice {exercice.annee}", style("sous_titre", fontSize=14)))
    el.append(Spacer(1, 30))
    el.append(HRFlowable(width="60%", thickness=1.2, color=INDIGO, spaceAfter=24, hAlign="CENTER"))
    infos = [
        ("Copropriété", copro.nom),
        ("Adresse", f"{copro.adresse} {copro.code_postal or ''} {copro.ville or ''}".strip() or "—"),
        ("Régime", f"{len(lots)} lots — syndic bénévole"),
        ("Édité le", _date_fr(date.today())),
    ]
    it = Table([[Paragraph(f"<b>{k}</b>", style("cell")), Paragraph(v, style("cell"))] for k, v in infos],
               colWidths=[70 * 2.835, 100 * 2.835])
    it.setStyle(table_style())
    el.append(it)
    el.append(Spacer(1, 34))

    # KPI
    kpi = [
        ("BUDGET PRÉVISIONNEL", fmt_eur(budget)),
        ("ENCAISSÉ", fmt_eur(enc_charges + enc_ft)),
        ("DÉPENSÉ", fmt_eur(dep_charges + dep_ft)),
        ("SOLDE DE CAISSE", fmt_eur(enc_charges + enc_ft - dep_charges - dep_ft)),
    ]
    kt = Table([[Paragraph(f"<b>{k}</b>", style("th", alignment=0)), Paragraph(f"<b>{v}</b>", style("cell", alignment=2))] for k, v in kpi],
               colWidths=[85 * 2.835, 85 * 2.835])
    kt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#c7d2fe")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c7d2fe")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    el.append(kt)
    el.append(Spacer(1, 14))
    el.append(Paragraph(
        f"Fonds de travaux (encours) : <b>{fmt_eur(enc_ft - dep_ft)}</b> &nbsp;·&nbsp; "
        f"Impayés au {_date_fr(date.today()).lower()} : <b>{fmt_eur(total_impayes)}</b>",
        style("normal", fontSize=9.5),
    ))
    el.append(PageBreak())

    # ===== 1. Compte de gestion =====
    el.append(Paragraph("1. COMPTE DE GESTION", style("titre", fontSize=15)))
    el.append(Paragraph("Présenté en assemblée générale pour approbation (art. 18, loi n°65-557).", style("small", textColor=GRIS)))
    el.append(Spacer(1, 8))
    story_compte_gestion(copro, exercice, db, el)
    el.append(PageBreak())

    # ===== 2. Statistiques =====
    el.append(Paragraph("2. STATISTIQUES DE L'EXERCICE", style("titre", fontSize=15)))
    el.append(Spacer(1, 10))
    el.append(Paragraph("2.1 Trésorerie mensuelle", style("section")))
    el.append(_graphique_mensuel(mouvements, exercice.annee))
    el.append(Paragraph(
        f"Total encaissé : <b>{fmt_eur(enc_charges + enc_ft)}</b> — total dépensé : <b>{fmt_eur(dep_charges + dep_ft)}</b>",
        style("small", textColor=GRIS),
    ))
    el.append(Spacer(1, 16))
    el.append(Paragraph("2.2 Répartition des encaissements", style("section")))
    el.append(_graphique_repartition(enc_charges, enc_ft, dep_charges, dep_ft))
    el.append(PageBreak())

    # ===== 3. Plan pluriannuel de travaux =====
    el.append(Paragraph("3. PLAN PLURIANNUEL DE TRAVAUX", style("titre", fontSize=15)))
    travaux = db.query(Travaux).filter(Travaux.copropriete_id == copro.id).order_by(Travaux.annee, Travaux.id).all()
    if not travaux:
        el.append(Paragraph("Aucun travaux planifié. Le plan pluriannuel de travaux (PPT) se vote en AG "
                            "(art. 14-2 de la loi n°65-557).", style("small", textColor=GRIS)))
    else:
        rows = [[Paragraph("<b>Année</b>", style("th")), Paragraph("<b>Travaux</b>", style("th")),
                 Paragraph("<b>Catégorie</b>", style("th")), Paragraph("<b>Statut</b>", style("th")),
                 Paragraph("<b>Montant estimé</b>", style("th"))]]
        total_ppt = 0.0
        for t in travaux:
            total_ppt += t.montant
            statut_label = {"planifie": "Planifié", "en_cours": "En cours", "realise": "Réalisé"}.get(t.statut, t.statut)
            rows.append([
                Paragraph(str(t.annee), style("cell")),
                Paragraph(t.libelle, style("cell")),
                Paragraph(t.categorie, style("cell")),
                Paragraph(statut_label, style("cell")),
                Paragraph(f"<b>{fmt_eur(t.montant)}</b>", style("cell")),
            ])
        rows.append([Paragraph("", style("cell")), Paragraph("", style("cell")), Paragraph("", style("cell")),
                     Paragraph("<b>Total du plan</b>", style("th")), Paragraph(f"<b>{fmt_eur(total_ppt)}</b>", style("cell"))])
        pt = Table(rows, colWidths=[22 * 2.835, 62 * 2.835, 30 * 2.835, 24 * 2.835, 30 * 2.835])
        pt.setStyle(table_style())
        el.append(pt)
        el.append(Spacer(1, 10))
        objectif_ppt = round(total_ppt * 0.025, 2)
        objectif_budget = round(budget * 0.05, 2)
        el.append(Paragraph(
            f"Si le PPT est voté, la cotisation annuelle minimale au fonds de travaux sera de "
            f"<b>{fmt_eur(objectif_ppt)}</b> (2,5 % du plan) <b>ou</b> <b>{fmt_eur(objectif_budget)}</b> (5 % du budget), "
            "le plus élevé des deux prévalant — contre <b>5 % du budget</b> sans PPT.",
            style("legal"),
        ))

    # ===== Signature =====
    el.append(Spacer(1, 20))
    el.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#94a3b8"), spaceAfter=8))
    ville = copro.ville or ""
    el.append(Paragraph(f"Fait à {ville}, le {_date_fr(date.today())}", style("normal", spaceAfter=24)))
    el.append(Paragraph("Le syndic bénévole", style("normal", spaceAfter=2)))
    el.append(Paragraph("<b>________________________</b>", style("normal", fontSize=10)))

    doc.build(el)
    buf.seek(0)
    return buf

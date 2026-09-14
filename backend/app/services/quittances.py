"""Génération des quittances d'appels de fonds en PDF groupé (une page par lot)."""
from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, HRFlowable, PageBreak,
)

from app.services.emailer import _date_fr
from app.services.pdf_base import register_fonts, style, table_style, page_margins, fmt_eur


def generer_quittances_pdf(copro, exercice, db, lot_ids=None) -> BytesIO:
    """Quittances d'appels de fonds de l'exercice, groupées (une page par lot)."""
    from app.models.appel import AppelFonds, AppelLot
    from app.models.mouvement import Mouvement
    from app.models.lot import Lot
    from app.models.user import User

    register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        title=f"Quittances {copro.nom} {exercice.annee}",
        **page_margins(),
    )

    lots = db.query(Lot).filter(Lot.copropriete_id == copro.id).all()
    if lot_ids:
        lots = [l for l in lots if l.id in lot_ids]
    appels = db.query(AppelFonds).filter(AppelFonds.exercice_id == exercice.id).order_by(AppelFonds.date_emission).all()

    el = []
    for i, lot in enumerate(lots):
        personne = db.query(User).filter(User.id == lot.proprietaire_id).first() if lot.proprietaire_id else None
        proprietaire = f"{personne.prenom} {personne.nom}".strip() if personne else "—"

        el.append(Paragraph("QUITTANCE D'APPELS DE FONDS", style("titre", fontSize=15)))
        el.append(Paragraph(f"Exercice {exercice.annee} — {copro.nom}", style("sous_titre")))

        infos = [
            ("Lot", f"Lot {lot.numero} ({lot.tantiemes}‰)"),
            ("Propriétaire", proprietaire),
            ("Adresse de l'immeuble", f"{copro.adresse} {copro.code_postal or ''} {copro.ville or ''}".strip()),
            ("Date de la quittance", _date_fr(date.today())),
        ]
        t = Table([[Paragraph(f"<b>{k}</b>", style("cell")), Paragraph(str(v), style("cell"))] for k, v in infos],
                  colWidths=[50 * 2.835, 118 * 2.835])
        t.setStyle(table_style())
        el.append(t)
        el.append(Spacer(1, 8))

        # Appels de fonds
        parts = db.query(AppelLot).filter(AppelLot.lot_id == lot.id).all()
        parts_par_appel = {p.appel_id: p for p in parts}
        appels_lot = [a for a in appels if a.id in parts_par_appel]
        el.append(Paragraph("1. APPELS DE FONDS", style("section")))
        rows = [[Paragraph("<b>Échéance</b>", style("th")), Paragraph("<b>Libellé</b>", style("th")),
                 Paragraph("<b>Charges</b>", style("th")), Paragraph("<b>Fonds travaux</b>", style("th")),
                 Paragraph("<b>Total</b>", style("th"))]]
        total_charges = total_ft = 0.0
        for a in appels_lot:
            p = parts_par_appel[a.id]
            total_charges += p.montant_charges
            total_ft += p.montant_fonds_travaux
            rows.append([
                Paragraph((a.date_echeance or a.date_emission).strftime("%d/%m/%Y"), style("cell")),
                Paragraph(a.libelle, style("cell")),
                Paragraph(fmt_eur(p.montant_charges), style("cell")),
                Paragraph(fmt_eur(p.montant_fonds_travaux), style("cell")),
                Paragraph(fmt_eur(p.montant_charges + p.montant_fonds_travaux), style("cell")),
            ])
        rows.append([
            Paragraph("", style("cell")), Paragraph("<b>Total appelé</b>", style("th")),
            Paragraph(fmt_eur(total_charges), style("cell")), Paragraph(fmt_eur(total_ft), style("cell")),
            Paragraph(fmt_eur(total_charges + total_ft), style("cell")),
        ])
        at = Table(rows, colWidths=[30 * 2.835, 62 * 2.835, 30 * 2.835, 30 * 2.835, 26 * 2.835])
        at.setStyle(table_style())
        el.append(at)
        el.append(Spacer(1, 8))

        # Encaissements
        encaissements = db.query(Mouvement).filter(
            Mouvement.lot_id == lot.id, Mouvement.type == "encaissement",
        ).order_by(Mouvement.date).all()
        el.append(Paragraph("2. PAIEMENTS REÇUS", style("section")))
        if not encaissements:
            el.append(Paragraph("Aucun paiement enregistré sur l'exercice.", style("small", textColor=colors.HexColor("#666666"))))
        else:
            rows = [[Paragraph("<b>Date</b>", style("th")), Paragraph("<b>Libellé</b>", style("th")),
                     Paragraph("<b>Catégorie</b>", style("th")), Paragraph("<b>Montant</b>", style("th"))]]
            total_paye = 0.0
            for m in encaissements:
                total_paye += m.montant
                rows.append([
                    Paragraph(m.date.strftime("%d/%m/%Y"), style("cell")),
                    Paragraph(m.libelle, style("cell")),
                    Paragraph("Fonds de travaux" if m.categorie == "fonds_travaux" else "Charges", style("cell")),
                    Paragraph(fmt_eur(m.montant), style("cell")),
                ])
            rows.append([Paragraph("", style("cell")), Paragraph("", style("cell")),
                         Paragraph("<b>Total payé</b>", style("th")), Paragraph(fmt_eur(total_paye), style("cell"))])
            et = Table(rows, colWidths=[30 * 2.835, 62 * 2.835, 40 * 2.835, 26 * 2.835])
            et.setStyle(table_style())
            el.append(et)
        el.append(Spacer(1, 8))

        # Synthèse
        total_appele = total_charges + total_ft
        total_paye = sum(m.montant for m in encaissements)
        solde = total_appele - total_paye
        el.append(Paragraph("3. SYNTHÈSE", style("section")))
        statut_txt = ("QUITTANCÉ — aucun solde restant dû", "#059669") if solde <= 0.005 else \
                     (f"RESTE DÛ : {fmt_eur(solde)}", "#dc2626")
        rows = [
            [Paragraph("Total appelé (charges + fonds travaux)", style("cell")), Paragraph(fmt_eur(total_appele), style("cell"))],
            [Paragraph("Total payé", style("cell")), Paragraph(fmt_eur(total_paye), style("cell"))],
            [Paragraph("<b>Solde</b>", style("th")), Paragraph(f"<b>{fmt_eur(solde)}</b>", style("cell"))],
        ]
        st = Table(rows, colWidths=[130 * 2.835, 38 * 2.835])
        st.setStyle(table_style())
        el.append(st)
        el.append(Spacer(1, 4))
        el.append(Paragraph(
            f"<b><font color='{statut_txt[1]}'>{statut_txt[0]}</font></b>",
            style("normal_bold", fontSize=10),
        ))

        el.append(Spacer(1, 10))
        el.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#94a3b8"), spaceAfter=6))
        el.append(Paragraph(
            "Quittance délivrée conformément à l'article 16 du décret n°67-223 du 17 mars 1967. "
            "Le syndic bénévole se tient à la disposition des copropriétaires pour toute précision.",
            style("legal"),
        ))

        if i < len(lots) - 1:
            el.append(PageBreak())

    doc.build(el)
    buf.seek(0)
    return buf

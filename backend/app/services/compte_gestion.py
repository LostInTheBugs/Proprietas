"""Génération du compte de gestion annuel en PDF (reportlab)."""
from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, HRFlowable,
)

from app.services.emailer import _date_fr
from app.services.pdf_base import register_fonts, style, table_style, page_margins, fmt_eur


def story_compte_gestion(copro, exercice, db, el) -> None:
    """Ajoute le compte de gestion annuel (synthèse, dépenses, annexe, impayés) à un story existant."""
    from app.models.mouvement import Mouvement
    from app.models.appel import AppelLot
    from app.models.lot import Lot
    from app.models.user import User

    mouvements = db.query(Mouvement).filter(Mouvement.exercice_id == exercice.id).all()
    depenses = [m for m in mouvements if m.type == "depense"]
    encaissements = [m for m in mouvements if m.type == "encaissement"]
    enc_charges = sum(m.montant for m in encaissements if m.categorie != "fonds_travaux")
    enc_ft = sum(m.montant for m in encaissements if m.categorie == "fonds_travaux")
    dep_ft = sum(m.montant for m in depenses if m.categorie == "fonds_travaux")
    budget = sum(b.montant for b in exercice.budget_lines)
    lots = db.query(Lot).filter(Lot.copropriete_id == copro.id).all()

    el.append(Paragraph("COMPTE DE GESTION DE L'EXERCICE", style("titre", fontSize=15)))
    el.append(Paragraph(f"Copropriété {copro.nom} — exercice {exercice.annee}", style("sous_titre")))
    if copro.adresse:
        el.append(Paragraph(f"{copro.adresse} {copro.code_postal or ''} {copro.ville or ''}".strip(), style("normal", alignment=1, spaceAfter=8)))

    # 1. Synthèse
    el.append(Paragraph("1. SYNTHÈSE DE L'EXERCICE", style("section")))
    solde = enc_charges + enc_ft - sum(m.montant for m in depenses)
    synthese = [
        ("Budget prévisionnel voté", fmt_eur(budget)),
        ("Appels de fonds encaissés (charges)", fmt_eur(enc_charges)),
        ("Cotisations fonds de travaux encaissées", fmt_eur(enc_ft)),
        ("Dépenses engagées", fmt_eur(sum(m.montant for m in depenses))),
        ("Solde de l'exercice", fmt_eur(solde)),
        ("Fonds de travaux (encours)", fmt_eur(enc_ft - dep_ft)),
    ]
    st = Table([[Paragraph(f"<b>{k}</b>", style("cell")), Paragraph(v, style("cell"))] for k, v in synthese],
               colWidths=[130 * 2.835, 40 * 2.835])
    st.setStyle(table_style())
    el.append(st)
    el.append(Spacer(1, 8))

    # 2. Dépenses détaillées
    el.append(Paragraph("2. DÉTAIL DES DÉPENSES", style("section")))
    if not depenses:
        el.append(Paragraph("Aucune dépense enregistrée sur l'exercice.", style("small", textColor=colors.HexColor("#666666"))))
    else:
        rows = [[Paragraph("<b>Date</b>", style("th")), Paragraph("<b>Libellé</b>", style("th")),
                 Paragraph("<b>Catégorie</b>", style("th")), Paragraph("<b>Montant</b>", style("th"))]]
        for m in sorted(depenses, key=lambda x: (x.date, x.id)):
            rows.append([
                Paragraph(m.date.strftime("%d/%m/%Y"), style("cell")),
                Paragraph(m.libelle, style("cell")),
                Paragraph("Fonds de travaux" if m.categorie == "fonds_travaux" else "Charges", style("cell")),
                Paragraph(f"<b>{fmt_eur(m.montant)}</b>", style("cell")),
            ])
        rows.append([
            Paragraph("", style("cell")), Paragraph("", style("cell")),
            Paragraph("<b>Total dépenses</b>", style("th")),
            Paragraph(f"<b>{fmt_eur(sum(m.montant for m in depenses))}</b>", style("cell")),
        ])
        dt = Table(rows, colWidths=[42 * 2.835, 72 * 2.835, 36 * 2.835, 30 * 2.835])
        dt.setStyle(table_style())
        el.append(dt)
        el.append(Spacer(1, 8))

    # 3. Annexe par lot
    el.append(Paragraph("3. ANNEXE — ÉTAT PAR LOT", style("section")))
    rows = [[Paragraph("<b>Lot</b>", style("th")), Paragraph("<b>Propriétaire</b>", style("th")),
             Paragraph("<b>Appels charges</b>", style("th")), Paragraph("<b>Appels fonds travaux</b>", style("th")),
             Paragraph("<b>Encaissé</b>", style("th")), Paragraph("<b>Solde</b>", style("th"))]]
    for lot in lots:
        appels_c = sum(a.montant_charges for a in db.query(AppelLot).filter(AppelLot.lot_id == lot.id).all())
        appels_f = sum(a.montant_fonds_travaux for a in db.query(AppelLot).filter(AppelLot.lot_id == lot.id).all())
        enc = sum(m.montant for m in db.query(Mouvement).filter(
            Mouvement.lot_id == lot.id, Mouvement.type == "encaissement").all())
        p = db.query(User).filter(User.id == lot.proprietaire_id).first() if lot.proprietaire_id else None
        solde = appels_c + appels_f - enc
        couleur = "#dc2626" if solde > 0.005 else "#059669"
        rows.append([
            Paragraph(f"Lot {lot.numero}", style("cell")),
            Paragraph(f"{p.prenom} {p.nom}".strip() if p else "—", style("cell")),
            Paragraph(fmt_eur(appels_c), style("cell")),
            Paragraph(fmt_eur(appels_f), style("cell")),
            Paragraph(fmt_eur(enc), style("cell")),
            Paragraph(f"<b><font color='{couleur}'>{fmt_eur(solde)}</font></b>", style("cell")),
        ])
    lt = Table(rows, colWidths=[22 * 2.835, 52 * 2.835, 32 * 2.835, 38 * 2.835, 26 * 2.835, 30 * 2.835])
    lt.setStyle(table_style())
    el.append(lt)
    el.append(Spacer(1, 8))

    # 4. Impayés
    impayes = []
    for lot in lots:
        appels_c = sum(a.montant_charges for a in db.query(AppelLot).filter(AppelLot.lot_id == lot.id).all())
        appels_f = sum(a.montant_fonds_travaux for a in db.query(AppelLot).filter(AppelLot.lot_id == lot.id).all())
        enc = sum(m.montant for m in db.query(Mouvement).filter(
            Mouvement.lot_id == lot.id, Mouvement.type == "encaissement").all())
        solde = appels_c + appels_f - enc
        if solde > 0.005:
            impayes.append((lot, solde))
    el.append(Paragraph(f"4. IMPAYÉS AU {_date_fr(date.today()).upper()}", style("section")))
    if not impayes:
        el.append(Paragraph("Aucun impayé : tous les lots sont à jour.", style("small", textColor=colors.HexColor("#059669"))))
    else:
        rows = [[Paragraph("<b>Lot</b>", style("th")), Paragraph("<b>Propriétaire</b>", style("th")),
                 Paragraph("<b>Solde dû</b>", style("th"))]]
        for lot, solde in impayes:
            p = db.query(User).filter(User.id == lot.proprietaire_id).first() if lot.proprietaire_id else None
            rows.append([
                Paragraph(f"Lot {lot.numero}", style("cell")),
                Paragraph(f"{p.prenom} {p.nom}".strip() if p else "—", style("cell")),
                Paragraph(f"<b>{fmt_eur(solde)}</b>", style("cell")),
            ])
        it = Table(rows, colWidths=[22 * 2.835, 120 * 2.835, 38 * 2.835])
        it.setStyle(table_style())
        el.append(it)

    el.append(Spacer(1, 14))
    el.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#94a3b8"), spaceAfter=8))
    ville = copro.ville or ""
    el.append(Paragraph(f"Fait à {ville}, le {_date_fr(date.today())}", style("normal", spaceAfter=24)))
    el.append(Paragraph("Le syndic bénévole", style("normal", spaceAfter=2)))
    el.append(Paragraph("<b>________________________</b>", style("normal", fontSize=10)))
    el.append(Spacer(1, 10))
    el.append(Paragraph(
        "Document présenté à l'assemblée générale pour approbation, conformément à l'article 18 de la loi "
        "n°65-557 du 10 juillet 1965 et à l'article 14 du décret n°67-223 du 17 mars 1967.",
        style("legal"),
    ))


def generer_compte_gestion_pdf(copro, exercice, db) -> BytesIO:
    """Compte de gestion annuel : synthèse, dépenses détaillées, annexe par lot, impayés, fonds de travaux."""
    register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        title=f"Compte de gestion {copro.nom} {exercice.annee}",
        **page_margins(),
    )
    el = []
    story_compte_gestion(copro, exercice, db, el)
    doc.build(el)
    buf.seek(0)
    return buf

"""Génération du compte de gestion annuel en PDF (reportlab)."""
from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, HRFlowable,
)

from app.core.money import D, somme
from app.services.soldes import totaux_lot
from app.services.emailer import _date_fr
from app.services.pdf_base import register_fonts, style, table_style, page_margins, fmt_eur


def story_compte_gestion(copro, exercice, db, el) -> None:
    """Ajoute le compte de gestion annuel (synthèse, dépenses, annexe, impayés) à un story existant."""
    from app.models.mouvement import Mouvement
    from app.models.lot import Lot
    from app.models.user import User

    mouvements = db.query(Mouvement).filter(Mouvement.exercice_id == exercice.id).all()
    # Remboursement d'une avance (catégorie « avance ») : ni une charge ni un produit (services/avances.py).
    depenses = [m for m in mouvements if m.type == "depense" and m.categorie != "avance"]
    encaissements = [m for m in mouvements if m.type == "encaissement"]
    # Encaissements « fonds de travaux » ou « travaux » : réservés au fonds de travaux
    # (même règle que l'imputation du décompte, recouvrement.CATEGORIES_TRAVAUX).
    enc_charges = somme(m.montant for m in encaissements if m.categorie not in ("fonds_travaux", "travaux"))
    enc_ft = somme(m.montant for m in encaissements if m.categorie in ("fonds_travaux", "travaux"))
    dep_ft = somme(m.montant for m in depenses if m.categorie == "fonds_travaux")
    budget = somme(b.montant for b in exercice.budget_lines)
    lots = db.query(Lot).filter(Lot.copropriete_id == copro.id).all()

    el.append(Paragraph("COMPTE DE GESTION DE L'EXERCICE", style("titre", fontSize=15)))
    el.append(Paragraph(f"Copropriété {copro.nom} — exercice {exercice.annee}", style("sous_titre")))
    if copro.adresse:
        el.append(Paragraph(f"{copro.adresse} {copro.code_postal or ''} {copro.ville or ''}".strip(), style("normal", alignment=1, spaceAfter=8)))
    el.append(Paragraph(
        "Synthèse de gestion de l'exercice. Elle ne remplace pas les documents comptables à joindre à la convocation "
        "de l'assemblée appelée à approuver les comptes (décret n° 67-223 du 17 mars 1967, art. 11 ; modèles de "
        "l'arrêté du 14 mars 2005).", style("small", textColor=colors.HexColor("#666666"), spaceAfter=6)))

    # 1. Synthèse
    el.append(Paragraph("1. SYNTHÈSE DE L'EXERCICE", style("section")))
    solde = enc_charges + enc_ft - somme(m.montant for m in depenses)
    synthese = [
        ("Budget prévisionnel voté", fmt_eur(budget)),
        ("Appels de fonds encaissés (charges)", fmt_eur(enc_charges)),
        ("Cotisations fonds de travaux encaissées", fmt_eur(enc_ft)),
        ("Dépenses engagées", fmt_eur(somme(m.montant for m in depenses))),
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
                Paragraph("Fonds de travaux" if m.categorie == "fonds_travaux"
                          else ("Charges générales" if m.cle is None else f"Charges spéciales : {m.cle.nom}"), style("cell")),
                Paragraph(f"<b>{fmt_eur(m.montant)}</b>", style("cell")),
            ])
        rows.append([
            Paragraph("", style("cell")), Paragraph("", style("cell")),
            Paragraph("<b>Total dépenses</b>", style("th")),
            Paragraph(f"<b>{fmt_eur(somme(m.montant for m in depenses))}</b>", style("cell")),
        ])
        dt = Table(rows, colWidths=[42 * 2.835, 72 * 2.835, 36 * 2.835, 30 * 2.835])
        dt.setStyle(table_style())
        el.append(dt)
        el.append(Spacer(1, 8))

    # Charges spéciales (loi 1965, art. 10) : budget et dépenses de chaque clé de répartition.
    from app.services import cles as svc_cles
    budget_cles = svc_cles.budget_par_cle(db, exercice.id)
    dep_cles: dict = {}
    for m in depenses:
        if m.lot_id is None and m.categorie != "fonds_travaux":
            dep_cles[m.cle_id] = dep_cles.get(m.cle_id, 0) + (m.montant or 0)
    if (set(budget_cles) | set(dep_cles)) - {None}:
        from app.models.cle import CleRepartition
        el.append(Paragraph("RÉPARTITION PAR CLÉ (CHARGES SPÉCIALES)", style("section")))
        rows = [[Paragraph(f"<b>{t}</b>", style("th")) for t in ("Clé de répartition", "Budget voté", "Dépenses")]]
        for cle_id in sorted(set(budget_cles) | set(dep_cles), key=lambda k: (k is not None, k or 0)):
            rows.append([Paragraph(svc_cles.nom(db.get(CleRepartition, cle_id) if cle_id else None), style("cell")),
                         Paragraph(fmt_eur(budget_cles.get(cle_id, 0)), style("cell")),
                         Paragraph(fmt_eur(dep_cles.get(cle_id, 0)), style("cell"))])
        ct = Table(rows, colWidths=[90 * 2.835, 45 * 2.835, 45 * 2.835])
        ct.setStyle(table_style())
        el.append(ct)
        el.append(Spacer(1, 8))

    # 3. Annexe par lot : appels et encaissements de CET exercice seulement (le solde cumulé de chaque lot,
    # tous exercices confondus, est celui des impayés, section 4).
    from app.models.appel import AppelFonds, AppelLot
    el.append(Paragraph(f"3. ANNEXE — ÉTAT PAR LOT (EXERCICE {exercice.annee})", style("section")))
    rows = [[Paragraph("<b>Lot</b>", style("th")), Paragraph("<b>Propriétaire</b>", style("th")),
             Paragraph("<b>Appels charges</b>", style("th")), Paragraph("<b>Appels fonds travaux</b>", style("th")),
             Paragraph("<b>Encaissé</b>", style("th")), Paragraph("<b>Solde de l'exercice</b>", style("th"))]]
    parts_ex = (db.query(AppelLot).join(AppelFonds, AppelLot.appel_id == AppelFonds.id)
                .filter(AppelFonds.exercice_id == exercice.id).all())
    for lot in lots:
        appels_c = somme(D(x.montant_charges or 0) for x in parts_ex if x.lot_id == lot.id)
        appels_f = somme(D(x.montant_fonds_travaux or 0) for x in parts_ex if x.lot_id == lot.id)
        enc = somme(D(m.montant or 0) for m in encaissements if m.lot_id == lot.id)
        p = db.query(User).filter(User.id == lot.proprietaire_id).first() if lot.proprietaire_id else None
        solde = appels_c + appels_f - enc
        couleur = "#dc2626" if solde > D("0.005") else "#059669"
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

    # 4. Impayés : solde de chaque lot à ce jour, tous exercices confondus (propriétaire actuel).
    impayes = []
    for lot in lots:
        t = totaux_lot(db, lot)
        appels_c, appels_f, enc = t["appels_charges"], t["appels_fonds"], t["encaisse"]
        solde = appels_c + appels_f - enc
        if solde > D("0.005"):
            p = db.query(User).filter(User.id == lot.proprietaire_id).first() if lot.proprietaire_id else None
            impayes.append((f"Lot {lot.numero}", f"{p.prenom} {p.nom}".strip() if p else "—", solde))
    # Anciens propriétaires : solde arrêté à la vente (services/mutations.py).
    from app.services import mutations as svc_mutations
    for m, du in svc_mutations.dus_vendeurs(db, copro):
        impayes.append((f"Lot {m.lot.numero}", f"{m.vendeur_nom} (vendeur, vente du {m.date_acte:%d/%m/%Y})", du))
    el.append(Paragraph(f"4. IMPAYÉS AU {_date_fr(date.today()).upper()}", style("section")))
    if not impayes:
        el.append(Paragraph("Aucun impayé : tous les lots sont à jour.", style("small", textColor=colors.HexColor("#059669"))))
    else:
        rows = [[Paragraph("<b>Lot</b>", style("th")), Paragraph("<b>Propriétaire</b>", style("th")),
                 Paragraph("<b>Solde dû</b>", style("th"))]]
        for lot_lib, nom, solde in impayes:
            rows.append([
                Paragraph(lot_lib, style("cell")),
                Paragraph(nom, style("cell")),
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

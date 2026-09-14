"""Mise en demeure de payer (PDF) — mentions Service-Public F2603 + article 19-2.

⚠️ Modèle généré automatiquement : à faire valider par un conseil juridique avant
usage réel. Base : Service-Public F2603 (vérifié 02/03/2026) ; article 19-2 de la
loi n° 65-557 du 10 juillet 1965 ; Cass. 3e civ., 18/06/2026, n° 24-19.950 (la mise
en demeure doit préciser la NATURE et le MONTANT de chaque provision réclamée).
"""
from datetime import date
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table

from app.services.emailer import _date_fr
from app.services.pdf_base import fmt_eur, page_margins, register_fonts, style, table_style

ART_19_2_TEXTE = (
    "À défaut du versement à sa date d'exigibilité d'une provision due au titre de "
    "l'article 14-1 de la loi du 10 juillet 1965, et après mise en demeure restée "
    "infructueuse passé un délai de trente jours, les autres provisions non encore "
    "échues ainsi que les sommes restant dues appelées au titre des exercices "
    "précédents après approbation des comptes deviennent immédiatement exigibles."
)


def generer_mise_en_demeure_pdf(copro, lot, proprietaire, lignes, syndic_nom: str) -> BytesIO:
    """PDF de mise en demeure (délai 30 jours, mécanisme de l'article 19-2).

    `lignes` : décompte des provisions ÉCHUES impayées (dicts de recouvrement.appels_lot).
    """
    register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        title=f"Mise en demeure — lot {lot.numero} — {copro.nom}",
        **page_margins(),
    )

    adresse_copro = f"{copro.adresse or ''} {copro.code_postal or ''} {copro.ville or ''}".strip()
    nom_dest = f"{proprietaire.prenom or ''} {proprietaire.nom or ''}".strip() if proprietaire else "—"
    adresse_dest = ((getattr(proprietaire, "adresse", "") or "").strip() if proprietaire else "") or "—"
    total = round(sum(l["restant_du"] for l in lignes), 2)

    el = []
    el.append(Paragraph("MISE EN DEMEURE DE PAYER", style("titre", fontSize=16)))
    el.append(Paragraph(
        "Charges de copropriété impayées — article 19-2 de la loi n° 65-557 du 10 juillet 1965",
        style("sous_titre")))
    el.append(HRFlowable(width="100%", thickness=0.8))
    el.append(Spacer(1, 10))

    infos = [
        ("Syndicat des copropriétaires", copro.nom),
        ("Adresse de la copropriété", adresse_copro or "—"),
        ("Destinataire", nom_dest if adresse_dest == "—" else f"{nom_dest} — {adresse_dest}"),
        ("Lot concerné", f"Lot {lot.numero}" + (f" — {lot.designation}" if lot.designation else "")),
        ("Date", _date_fr(date.today()).split(" ", 1)[-1]),
    ]
    t = Table([[Paragraph(f"<b>{k}</b>", style("cell")), Paragraph(str(v), style("cell"))] for k, v in infos],
              colWidths=[52 * 2.835, 116 * 2.835])
    t.setStyle(table_style())
    el.append(t)
    el.append(Spacer(1, 12))

    el.append(Paragraph("Madame, Monsieur,", style("normal")))
    el.append(Spacer(1, 5))
    intro = (f"En ma qualité de syndic de la copropriété {copro.nom}, je vous mets en demeure "
             f"de me régler, dans un délai de trente (30) jours à compter de la présente, la somme "
             f"de <b>{fmt_eur(total)}</b>, correspondant aux provisions suivantes demeurées impayées "
             f"à leur date d'exigibilité :")
    el.append(Paragraph(intro, style("normal")))
    el.append(Spacer(1, 7))

    rows = [[Paragraph("<b>Exercice</b>", style("th")), Paragraph("<b>Libellé</b>", style("th")),
             Paragraph("<b>Échéance</b>", style("th")), Paragraph("<b>Montant dû</b>", style("th")),
             Paragraph("<b>Restant dû</b>", style("th"))]]
    for l in lignes:
        rows.append([
            Paragraph(str(l.get("exercice") or ""), style("cell")),
            Paragraph(l.get("libelle") or "", style("cell")),
            Paragraph(l["echeance"].strftime("%d/%m/%Y") if l.get("echeance") else "—", style("cell")),
            Paragraph(fmt_eur(l["montant"]), style("cell")),
            Paragraph(fmt_eur(l["restant_du"]), style("cell")),
        ])
    rows.append([
        Paragraph("", style("cell")), Paragraph("<b>Total dû</b>", style("cell")),
        Paragraph("", style("cell")), Paragraph("", style("cell")),
        Paragraph(f"<b>{fmt_eur(total)}</b>", style("cell")),
    ])
    t2 = Table(rows, colWidths=[56, 186, 70, 86, 90], repeatRows=1)
    t2.setStyle(table_style())
    el.append(t2)
    el.append(Spacer(1, 10))

    para = ("Conformément à l'article 19-2 de la loi n° 65-557 du 10 juillet 1965, à défaut de "
            "règlement dans ce délai de trente (30) jours, les autres provisions non encore échues "
            "au titre du budget prévisionnel ainsi que les sommes restant dues appelées au titre "
            "des exercices précédents après approbation des comptes deviendront immédiatement "
            "exigibles. Le syndicat des copropriétaires pourra alors saisir le président du "
            "tribunal judiciaire statuant selon la procédure accélérée au fond pour obtenir votre "
            "condamnation au paiement de l'ensemble des sommes exigibles, sans préjudice des "
            "intérêts et frais.")
    el.append(Paragraph(para, style("normal")))
    el.append(Spacer(1, 6))
    el.append(Paragraph("Texte de l'article 19-2 : « " + ART_19_2_TEXTE + " »", style("legal")))
    el.append(Spacer(1, 6))
    el.append(Paragraph(
        "Des intérêts de retard sont dus au taux légal à compter de la présente mise en demeure. "
        "Les frais de la présente mise en demeure sont à votre charge.", style("normal")))
    el.append(Spacer(1, 6))
    el.append(Paragraph(
        "Si vous avez déjà procédé au règlement, veuillez considérer la présente comme sans objet. "
        "À défaut de paiement, je me verrai contraint de poursuivre la procédure de recouvrement "
        "(tentative de règlement amiable puis, si nécessaire, saisine de la juridiction compétente).",
        style("normal")))
    el.append(Spacer(1, 24))

    ville = (copro.ville or "").strip()
    el.append(Paragraph(f"Fait à {ville}, le {_date_fr(date.today())}." if ville
                        else f"Le {_date_fr(date.today())}.", style("normal")))
    el.append(Spacer(1, 30))
    el.append(Paragraph(f"{syndic_nom or 'Le syndic'}<br/>Syndic de la copropriété {copro.nom}",
                        style("normal")))
    el.append(Spacer(1, 20))
    el.append(Paragraph("Signature :", style("small")))
    doc.build(el)
    buf.seek(0)
    return buf

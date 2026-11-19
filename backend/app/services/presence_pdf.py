"""PDF du pouvoir (à signer) et de la feuille de présence d'une AG (services/presences.py)."""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

from app.models.lot import Lot
from app.services import presences
from app.services.emailer import _date_fr
from app.services.pdf_base import page_margins, register_fonts, style, table_style

_TYPE = {"annuelle": "annuelle", "extraordinaire": "extraordinaire", "consultation_ecrite": "(consultation écrite)"}


def _seance(ag) -> str:
    return (f"l'assemblée générale {_TYPE.get(ag.type_ag, '')} du {_date_fr(ag.date)}"
            + (f" à {ag.heure}" if ag.heure else "") + (f", {ag.lieu}" if ag.lieu else ""))


def _adresse(copro) -> str:
    return " ".join(x for x in (copro.adresse, copro.code_postal, copro.ville) if x)


def pouvoir_pdf(db, ag, copro, reponse) -> BytesIO:
    """Pouvoir (loi du 10 juillet 1965, art. 22) du mandant à son mandataire, à dater et signer."""
    register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=f"Pouvoir AG {copro.nom} {ag.date}", **page_margins())
    mandant, mandataire = reponse.personne, reponse.mandataire
    lots = db.query(Lot).filter(Lot.copropriete_id == copro.id, Lot.proprietaire_id == mandant.id).order_by(Lot.id).all()
    el = [Paragraph("POUVOIR", style("titre")),
          Paragraph(f"Copropriété {escape(copro.nom)}" + (f" — {escape(_adresse(copro))}" if _adresse(copro) else ""),
                    style("sous_titre"))]
    texte = (f"Je soussigné(e) <b>{escape(presences.nom(mandant))}</b>, copropriétaire "
             f"({'lots' if len(lots) > 1 else 'lot'} {escape(', '.join(l.numero for l in lots))}, "
             f"{sum(l.tantiemes or 0 for l in lots)} tantièmes), donne pouvoir à "
             f"<b>{escape(presences.nom(mandataire))}</b>, copropriétaire, de me représenter à "
             f"{escape(_seance(ag))}, de prendre part en mon nom aux délibérations et aux votes sur toutes les "
             "questions inscrites à l'ordre du jour, et de signer la feuille de présence.")
    el += [Paragraph(texte, style("normal", fontSize=10.5, leading=15, spaceAfter=8))]
    principales = sorted((r for r in ag.resolutions if r.second_vote_de_id is None), key=lambda r: (r.numero, r.id))
    if principales:
        el.append(Paragraph("Ordre du jour", style("section")))
        for r in principales:
            el.append(Paragraph(f"{r.numero}. {escape(r.libelle)}", style("normal", spaceAfter=2)))
    el += [
        Spacer(1, 8),
        Paragraph("Le mandataire peut subdéléguer ce pouvoir à une autre personne (loi du 10 juillet 1965, art. 22), "
                  "sauf si je l'interdis ici : ☐ subdélégation interdite.", style("small", spaceAfter=4)),
        Paragraph(f"Désignation enregistrée dans Proprietas le {reponse.repondu_le:%d/%m/%Y à %H:%M}"
                  f" ({ {'lien': 'lien personnel de l’e-mail', 'compte': 'compte du copropriétaire', 'syndic': 'saisie du syndic'}.get(reponse.source, reponse.source)}).",
                  style("small", spaceAfter=14)),
        Table([[Paragraph("Fait à ………………………………, le ……………………", style("normal")),
                Paragraph("Signature du mandant,<br/>précédée de « Bon pour pouvoir »", style("normal"))]],
              colWidths=[85 * mm, 85 * mm], rowHeights=[38 * mm]),
        Spacer(1, 10),
        Paragraph("Rappel (art. 22) : le syndic, son conjoint ou partenaire de PACS, ses ascendants et descendants et "
                  "ses préposés ne peuvent pas recevoir de pouvoir. Un mandataire ne peut pas recevoir plus de trois "
                  "délégations de vote, sauf si ses voix et celles de ses mandants ne dépassent pas 10 % des voix du "
                  "syndicat. Ce pouvoir est à remettre au mandataire ou au syndic avant l'assemblée ; il est annexé "
                  "au procès-verbal.", style("legal")),
    ]
    doc.build(el)
    buf.seek(0)
    return buf


def feuille_presence_pdf(db, ag, copro) -> BytesIO:
    """Feuille de présence (décret n° 67-223 du 17 mars 1967, art. 14), préremplie avec les réponses."""
    register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=f"Feuille de présence AG {copro.nom} {ag.date}", **page_margins())
    e = presences.etat(db, ag)
    el = [Paragraph("FEUILLE DE PRÉSENCE", style("titre")),
          Paragraph(f"Copropriété {escape(copro.nom)} — {escape(_seance(ag))}", style("sous_titre"))]
    rows = [[Paragraph(f"<b>{t}</b>", style("th")) for t in
             ("Copropriétaire", "Lots", "Voix (‰)", "Présence", "Signature")]]
    for l in e["lignes"]:
        presence = {"present": "Présent(e)", "absent": "Absent(e)", "incertain": "—", "": "—"}.get(l["reponse"], "")
        if l["reponse"] == "pouvoir":
            presence = f"Représenté(e) par {l['mandataire_nom']}" + (" (pouvoir signé reçu)" if l["pouvoir_recu_le"] else "")
        rows.append([Paragraph(escape(l["nom"]), style("cell")), Paragraph(escape(", ".join(l["lots"])), style("cell")),
                     Paragraph(f"{l['voix']:g}", style("cell")), Paragraph(escape(presence), style("cell")), ""])
    t = Table(rows, colWidths=[48 * mm, 22 * mm, 18 * mm, 48 * mm, 38 * mm], repeatRows=1)
    t.setStyle(table_style())
    el += [t, Spacer(1, 8),
           Paragraph(f"D'après les réponses enregistrées : {e['totaux']['presents']} présent(s), "
                     f"{e['totaux']['representes']} représenté(s), soit {e['totaux']['voix_presentes_ou_representees']:g} ‰ "
                     "des voix. À compléter et à corriger en séance ; certifiée exacte par le président de séance.",
                     style("small")),
           Spacer(1, 14),
           Paragraph("Le président de séance : ……………………………………", style("normal"))]
    doc.build(el)
    buf.seek(0)
    return buf

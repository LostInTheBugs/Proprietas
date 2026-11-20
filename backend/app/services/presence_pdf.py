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
        if l["reponse"] == "correspondance":
            presence = "Vote par correspondance" + (f" (formulaire reçu le {l['correspondance_recue_le']:%d/%m/%Y})"
                                                    if l.get("correspondance_recue_le") else "")
        rows.append([Paragraph(escape(l["nom"]), style("cell")), Paragraph(escape(", ".join(l["lots"])), style("cell")),
                     Paragraph(f"{l['voix']:g}", style("cell")), Paragraph(escape(presence), style("cell")), ""])
    t = Table(rows, colWidths=[48 * mm, 22 * mm, 18 * mm, 48 * mm, 38 * mm], repeatRows=1)
    t.setStyle(table_style())
    el += [t, Spacer(1, 8),
           Paragraph(f"D'après les réponses enregistrées : {e['totaux']['presents']} présent(s), "
                     f"{e['totaux']['representes']} représenté(s), soit {e['totaux']['voix_presentes_ou_representees']:g} ‰ "
                     f"des voix ; {e['totaux']['correspondances']} vote(s) par correspondance "
                     f"({e['totaux']['voix_correspondance']:g} ‰). À compléter et à corriger en séance ; certifiée exacte par le président de séance.",
                     style("small")),
           Spacer(1, 14),
           Paragraph("Le président de séance : ……………………………………", style("normal"))]
    doc.build(el)
    buf.seek(0)
    return buf


_MAJORITES = {"art24": "art. 24", "art25": "art. 25", "art26": "art. 26", "unanimite": "unanimité"}


def formulaires_correspondance_pdf(db, ag, copro, personnes) -> BytesIO:
    """Formulaire de vote par correspondance (modèle de l'arrêté du 2 juillet 2020), une page par copropriétaire."""
    from reportlab.platypus import PageBreak
    from app.services import correspondance
    register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=f"Vote par correspondance AG {copro.nom} {ag.date}", **page_margins())
    voix, total = presences._parts(db, ag.copropriete_id)
    resolutions = correspondance.resolutions_votables(ag)
    limite = correspondance.date_limite(ag)
    contact = copro.email_expediteur or ""
    el = []
    for i, u in enumerate(personnes):
        if i:
            el.append(PageBreak())
        lots = (db.query(Lot).filter(Lot.copropriete_id == ag.copropriete_id, Lot.proprietaire_id == u.id)
                .order_by(Lot.numero).all())
        part = round(float(voix.get(u.id, 0) / total * 1000), 1) if total else 0
        el += [Paragraph("FORMULAIRE DE VOTE PAR CORRESPONDANCE", style("titre")),
               Paragraph("Loi du 10 juillet 1965, art. 17-1 A ; décret du 17 mars 1967, art. 9 bis ; "
                         "modèle de l'arrêté du 2 juillet 2020", style("sous_titre")),
               Paragraph(f"<b>Syndicat des copropriétaires</b> : {escape(copro.nom)}"
                         + (f", {escape(_adresse(copro))}" if _adresse(copro) else ""), style("normal")),
               Paragraph(f"<b>Assemblée</b> : {escape(_seance(ag))}", style("normal")),
               Paragraph(f"<b>Copropriétaire</b> : {escape(presences.nom(u))}", style("normal")),
               Paragraph(f"<b>Lot(s)</b> : {escape(', '.join(l.numero for l in lots)) or '—'} — "
                         f"<b>voix</b> : {part:g} ‰", style("normal", spaceAfter=6))]
        rows = [[Paragraph(f"<b>{t}</b>", style("th")) for t in ("N°", "Résolution", "Majorité", "Pour", "Contre", "Abstention")]]
        for r in resolutions:
            rows.append([Paragraph(str(r.numero), style("cell")), Paragraph(escape(r.libelle), style("cell")),
                         Paragraph(_MAJORITES.get(r.majorite, r.majorite), style("cell")), "☐", "☐", "☐"])
        t = Table(rows, colWidths=[10 * mm, 98 * mm, 20 * mm, 14 * mm, 14 * mm, 18 * mm], repeatRows=1)
        t.setStyle(table_style())
        el += [t, Spacer(1, 6),
               Paragraph("Cochez une seule case par résolution. Le texte des résolutions est celui de la convocation.",
                         style("small")),
               Spacer(1, 6),
               Paragraph(f"<b>À retourner au syndic au plus tard le {limite:%d/%m/%Y}</b> (trois jours francs avant "
                         "l'assemblée), par courrier"
                         + (f" ou par courrier électronique à {escape(contact)} (reçu à la date d'envoi)" if contact else "")
                         + ".", style("normal")),
               Spacer(1, 10),
               Paragraph("Fait à ……………………………, le ……………………  Signature : ……………………………………", style("normal")),
               Spacer(1, 10),
               Paragraph(
                   "Rappels : un formulaire ne donnant aucun sens précis de vote ou exprimant une abstention est considéré "
                   "comme un vote défavorable (art. 9 bis). Si une résolution est amendée en séance, un vote favorable "
                   "exprimé par correspondance sur cette résolution est assimilé à celui d'un copropriétaire défaillant "
                   "(art. 17-1 A). Le formulaire n'est pas pris en compte si vous êtes présent ou représenté à "
                   "l'assemblée (art. 14-1). Il est mentionné, avec sa date de réception, sur la feuille de présence.",
                   style("legal"))]
    doc.build(el)
    buf.seek(0)
    return buf

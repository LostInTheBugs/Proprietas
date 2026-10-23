"""Génération du procès-verbal d'AG en PDF (reportlab).

Contenu exigé par l'art. 17 du décret n° 67-223 du 17 mars 1967 : pour chaque résolution,
le résultat du vote et les noms et nombre de voix des copropriétaires opposants, abstenus
et défaillants ; signature par le président de séance, le secrétaire et le(s) scrutateur(s).
"""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, HRFlowable, KeepTogether,
)

from app.services.country_rules import calculer_statut_resolution, MAJORITES, poids_de_vote, _num
from app.services.emailer import _date_fr
from app.services.pdf_base import register_fonts, style, table_style, page_margins

_TYPE_LABEL = {
    "annuelle": "Assemblée Générale annuelle",
    "extraordinaire": "Assemblée Générale extraordinaire",
    "consultation_ecrite": "Consultation écrite",
}

_VOIX_LABEL = {"pour": "Pour", "contre": "Contre", "abstention": "Abstention"}

_STATUT_LABEL = {"projet": "Projet", "convoquee": "Convoquée", "terminee": "Terminée"}

# Libellés des listes nominatives (art. 17 du décret de 1967)
_LISTES = (("contre", "Opposants"), ("abstention", "Abstentionnistes"), ("defaillant", "Défaillants"))

# Art. 42 al. 2 de la loi du 10 juillet 1965 (rédaction issue de la loi ELAN du 23 novembre 2018).
_MENTION_ART42 = (
    "Article 42, alinéa 2, de la loi n° 65-557 du 10 juillet 1965 : les actions en contestation des "
    "décisions des assemblées générales doivent, à peine de déchéance, être introduites par les "
    "copropriétaires opposants ou défaillants dans un délai de deux mois à compter de la notification "
    "du procès-verbal d'assemblée, sans ses annexes. Cette notification est réalisée par le syndic "
    "dans le délai d'un mois à compter de la tenue de l'assemblée générale."
)


def votants_nommes(resolution, lots, db) -> dict:
    """Copropriétaires opposants, abstenus et défaillants d'une résolution, avec leurs voix.

    Retourne {"contre": [...], "abstention": [...], "defaillant": [...]}, chaque élément
    étant (nom, [numéros de lots], voix), trié par nom.
    - Les voix sont les poids de vote du décompte (réduction art. 22 al. 2 comprise) :
      leur somme est égale au « contre » / à l'« abstention » de calculer_statut_resolution.
    - Un copropriétaire qui vote différemment selon ses lots apparaît, pour chaque liste,
      avec les seuls lots concernés.
    - Défaillant : aucun de ses lots n'a voté (pas de vote, ou vote « null »).
    """
    from app.models.user import User

    poids = poids_de_vote(lots)
    voix_lot = {v.lot_id: v.voix for v in resolution.votes}
    ids = {l.proprietaire_id for l in lots if l.proprietaire_id}
    noms = {u.id: f"{u.nom} {u.prenom}".strip()
            for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}

    # Regroupement par copropriétaire (même règle que country_rules._membres)
    membres: dict = {}
    for l in lots:
        key = l.proprietaire_id if l.proprietaire_id else f"lot-{l.id}"
        membres.setdefault(key, []).append(l)

    out = {"contre": [], "abstention": [], "defaillant": []}
    for key, ls in membres.items():
        nom = noms.get(key, "Propriétaire non renseigné")
        a_vote = any(voix_lot.get(l.id) in ("pour", "contre", "abstention") for l in ls)
        for cle, choisis in (("contre", [l for l in ls if voix_lot.get(l.id) == "contre"]),
                             ("abstention", [l for l in ls if voix_lot.get(l.id) == "abstention"]),
                             ("defaillant", [] if a_vote else ls)):
            if choisis:
                out[cle].append((nom, [l.numero for l in choisis], _num(sum(poids[l.id] for l in choisis))))
    for cle in out:
        out[cle].sort(key=lambda x: (x[0].lower(), x[1]))
    return out


def _liste_nominative(entrees, unite: str) -> str:
    if not entrees:
        return "aucun"
    return " ; ".join(
        # escape : un nom contenant « & » ou « < » casserait le balisage des Paragraph reportlab.
        f"{escape(nom)} ({'lots' if len(nums) > 1 else 'lot'} {escape(', '.join(nums))}) — {voix}{unite}"
        for nom, nums, voix in entrees
    )


def generer_pv_pdf(copro, ag, db) -> BytesIO:
    """Génère le PV de l'AG au format PDF (retourne un BytesIO)."""
    register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        title=f"PV AG {copro.nom} {ag.date}",
        **page_margins(),
    )

    from app.models.lot import Lot
    lots = db.query(Lot).filter(Lot.copropriete_id == copro.id).all()
    total = sum(l.tantiemes for l in lots) or 1

    el = []
    el.append(Paragraph("PROCÈS-VERBAL D'ASSEMBLÉE GÉNÉRALE", style("titre", fontSize=15)))
    el.append(Paragraph(_TYPE_LABEL.get(ag.type_ag, "Assemblée Générale"), style("sous_titre")))

    el.append(Paragraph(f"<b>Copropriété :</b> {copro.nom}", style("normal", fontSize=10.5)))
    if copro.adresse:
        el.append(Paragraph(f"{copro.adresse} {copro.code_postal or ''} {copro.ville or ''}".strip(), style("normal")))
    el.append(Spacer(1, 6))

    # Informations de séance
    MM = 2.835  # 1 mm en points reportlab
    infos = [
        ("Type de séance", _TYPE_LABEL.get(ag.type_ag, "AG")),
        ("Date", _date_fr(ag.date) + (f" à {ag.heure}" if ag.heure else "")),
        ("Lieu", ag.lieu or "—"),
        ("Statut", _STATUT_LABEL.get(ag.statut, ag.statut)),
    ]
    t = Table([[Paragraph(f"<b>{k}</b>", style("cell")), Paragraph(str(v), style("cell"))] for k, v in infos],
              colWidths=[38 * MM, 130 * MM])
    t.setStyle(table_style())
    el.append(t)
    el.append(Spacer(1, 8))

    # Ordre du jour
    # Chaque second vote (passerelle 25-1 / 26-1) est placé juste après la résolution
    # dont il découle ; il ne figure pas à l'ordre du jour (il n'y était pas inscrit).
    principales = sorted((r for r in ag.resolutions if r.second_vote_de_id is None),
                         key=lambda x: (x.numero, x.id))
    seconds = {r.second_vote_de_id: r for r in ag.resolutions if r.second_vote_de_id is not None}
    resolutions = []
    for r in principales:
        resolutions.append(r)
        if r.id in seconds:
            resolutions.append(seconds[r.id])
    if principales:
        el.append(Paragraph("ORDRE DU JOUR", style("section")))
        for r in principales:
            el.append(Paragraph(f"{r.numero}. {r.libelle}", style("normal", fontSize=9.8, spaceAfter=2)))
        el.append(Spacer(1, 6))

    el.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#94a3b8"), spaceAfter=10))

    # Résolutions détaillées
    el.append(Paragraph("RÉSOLUTIONS ET VOTES", style("section")))
    for r in resolutions:
        el.append(Paragraph(
            f"Résolution {r.numero} — {r.libelle}",
            style("normal_bold", fontSize=10.5, spaceBefore=6, spaceAfter=2),
        ))
        if r.second_vote_de_id is not None:
            article = "25-1" if r.majorite == "art24" else "26-1"
            el.append(Paragraph(
                f"Second vote immédiat de la résolution n° {r.numero}, en application de l'article {article} "
                "de la loi du 10 juillet 1965.",
                style("small", textColor=colors.HexColor("#444444"), spaceAfter=2),
            ))
        if r.texte:
            el.append(Paragraph(r.texte, style("small", textColor=colors.HexColor("#444444"), spaceAfter=2)))
        resultat = calculer_statut_resolution(r, lots, r.votes)
        maj_label = MAJORITES.get(r.majorite, {}).get("label", r.majorite)
        el.append(Paragraph(
            f"<b>Majorité requise :</b> {maj_label}",
            style("small", spaceAfter=3),
        ))

        rows = [[Paragraph("<b>Lot</b>", style("th")), Paragraph("<b>Millièmes</b>", style("th")), Paragraph("<b>Voix</b>", style("th"))]]
        for lot in lots:
            v = next((x for x in r.votes if x.lot_id == lot.id), None)
            if v and v.voix == "pour":
                voix = "<font color='#059669'><b>Pour</b></font>"
            elif v and v.voix == "contre":
                voix = "<font color='#dc2626'><b>Contre</b></font>"
            elif v and v.voix == "abstention":
                voix = "Abstention"
            else:
                voix = "—"
            rows.append([
                Paragraph(f"Lot {lot.numero}", style("cell")),
                Paragraph(str(lot.tantiemes), style("cell")),
                Paragraph(voix, style("cell")),
            ])
        vt = Table(rows, colWidths=[50 * 2.835, 35 * 2.835, 83 * 2.835])
        vt.setStyle(table_style())
        el.append(vt)
        el.append(Spacer(1, 4))

        statut_txt = {
            "adoptee": ("ADOPTÉE", "#059669"),
            "rejetee": ("REJETÉE", "#dc2626"),
            "a_voter": ("À VOTER", "#d97706"),
        }.get(resultat["statut"], (resultat["statut"], "#444444"))
        # Avec la réduction art. 22, les chiffres sont des voix réduites, plus des millièmes.
        u = " voix" if resultat.get("reduction_art22") is not None else "‰"
        el.append(Paragraph(
            f"Pour : <b>{resultat['pour']}{u}</b>  ·  Contre : <b>{resultat['contre']}{u}</b>  ·  "
            f"Abstention : <b>{resultat['abstention']}{u}</b>",
            style("normal", fontSize=9.5, spaceBefore=2),
        ))
        if resultat.get("reduction_art22") is not None:
            somme = sum(l.tantiemes for l in lots)
            el.append(Paragraph(
                f"Réduction art. 22 al. 2 : les voix du copropriétaire majoritaire sont réduites à la somme "
                f"des voix des autres — total de référence {resultat['total']} voix (au lieu de {somme}).",
                style("small", spaceAfter=2),
            ))
        noms = votants_nommes(r, lots, db)
        for cle, libelle in _LISTES:
            el.append(Paragraph(
                f"<b>{libelle} :</b> {_liste_nominative(noms[cle], u)}",
                style("small", spaceAfter=1),
            ))
        if r.majorite == "art26":
            el.append(Paragraph(
                f"Membres pour : {resultat['membres_pour']} / {resultat['nb_membres']} "
                "(majorité des membres du syndicat requise)",
                style("small", spaceAfter=2),
            ))
        el.append(Paragraph(
            f"<b><font color='{statut_txt[1]}'>{statut_txt[0]}</font></b> — {resultat['detail']}",
            style("small", textColor=colors.HexColor("#333333"), spaceAfter=8),
        ))

    el.append(Spacer(1, 14))
    el.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#94a3b8"), spaceAfter=8))
    # Le PV est signé à la fin de la séance (art. 17) : il est daté du jour de l'AG,
    # pas du jour où le PDF est généré.
    jour = _date_fr(ag.date).split(" ", 1)[1]          # « vendredi 20 novembre 2026 » → « 20 novembre 2026 »
    ville = (copro.ville or "").strip()
    fait = f"Fait à {ville}, le {jour}" if ville else f"Fait le {jour}"
    signataires = ("Le président de séance", "Le secrétaire", "Le ou les scrutateurs")
    sig = Table(
        [[Paragraph(f"<b>{s}</b>", style("cell")) for s in signataires],
         [Paragraph("Nom et signature", style("small")) for _ in signataires]],
        colWidths=[56 * MM] * 3, rowHeights=[None, 22 * MM],
    )
    sig.setStyle(table_style())
    # « Fait à … » et les signatures restent sur la même page.
    el.append(KeepTogether([Paragraph(fait, style("normal", spaceAfter=10)), sig]))
    el.append(Spacer(1, 10))
    el.append(Paragraph(_MENTION_ART42, style("legal")))

    doc.build(el)
    buf.seek(0)
    return buf

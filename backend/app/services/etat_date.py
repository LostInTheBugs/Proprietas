"""Documents de la vente d'un lot (demande de Fred, 20/11/2026) : pré-état daté, état daté, projet d'opposition.

- **Pré-état daté** : informations financières à annexer à la promesse de vente (code de la construction et de
  l'habitation, art. L721-2) : charges appelées au vendeur sur les deux exercices précédents et leur règlement ;
  sommes susceptibles d'être dues par l'acquéreur ; état global des impayés de la copropriété et des factures
  non réglées ; part du fonds de travaux attachée au lot et dernière cotisation. Il n'a pas de forme légale
  propre : c'est un relevé, à compléter par les pièces non financières (règlement, PV d'AG…).
- **État daté** (décret n° 67-223 du 17 mars 1967, art. 5), demandé par le notaire avant l'acte : 1) sommes dues
  par le vendeur au syndicat ; 2) sommes dont le syndicat est débiteur envers lui ; 3) sommes qui incomberont à
  l'acquéreur ; annexe : quote-part du lot dans le budget et les appels des deux exercices précédents, procédures.
  Les indications des parties 1 et 2 peuvent être approximatives, sous réserve de l'apurement des comptes.
- **Projet d'opposition** (loi du 10 juillet 1965, art. 20) après l'avis de mutation : montant et causes des
  sommes dues par le vendeur, par exercice, distinguées comme le demande l'art. 5-1 du décret (année courante et
  deux années échues, deux années antérieures, autres). L'opposition se fait par acte de commissaire de justice
  dans les 15 jours de l'avis : ce document la prépare, il ne la remplace pas.

Les calculs reprennent le décompte du lot (recouvrement.ventilation_lot), à une date donnée.
"""
from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table
from sqlalchemy.orm import Session

from app.core.money import D, arrondi, somme
from app.models.appel import AppelFonds, AppelLot
from app.models.exercice import BudgetLine, Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.models.recouvrement import ActeRecouvrement
from app.services import cles, ensembles, recouvrement
from app.services.pdf_base import fmt_eur, page_margins, register_fonts, style, table_style

GRIS = colors.HexColor("#666666")


# ---------------------------------------------------------------- calculs
def _appels(db: Session, ids: list[int]) -> dict[int, AppelFonds]:
    return {a.id: a for a in db.query(AppelFonds).filter(AppelFonds.id.in_(ids))} if ids else {}


def _nature(appel: AppelFonds, annee: int, jour: date) -> str:
    if appel.reprise_etat_id is not None or annee < jour.year:
        return "Charges des exercices antérieurs"
    if appel.regularisation_de_id is not None:
        return "Régularisation des charges"
    return "Provisions exigibles de l'exercice en cours"


def _quote_part_budget(db: Session, copro, ex: Exercice | None, ids: list[int]) -> D:
    if ex is None:
        return D(0)
    budget = arrondi(somme(D(b.montant or 0) for b in db.query(BudgetLine).filter(BudgetLine.exercice_id == ex.id)))
    if budget <= 0:
        return D(0)
    parts = cles.repartir_selon_budget(db, copro.id, ex.id, budget)
    return arrondi(somme(parts.get(i, D(0)) for i in ids))


def _appele(db: Session, ex: Exercice | None, ids: list[int]) -> tuple[D, D]:
    """(charges, fonds de travaux) appelés aux lots sur l'exercice."""
    if ex is None:
        return D(0), D(0)
    parts = (db.query(AppelLot).join(AppelFonds, AppelLot.appel_id == AppelFonds.id)
             .filter(AppelFonds.exercice_id == ex.id, AppelLot.lot_id.in_(ids)).all())
    return (arrondi(somme(D(p.montant_charges or 0) for p in parts)),
            arrondi(somme(D(p.montant_fonds_travaux or 0) for p in parts)))


def situation(db: Session, copro, lot: Lot, jour: date) -> dict:
    """Situation du lot (et de ses annexes) au `jour`, pour le propriétaire actuel."""
    from app.services.mutations import dus_vendeurs
    from app.services.soldes import totaux_lot
    p = ensembles.principal(db, lot)
    membres = ensembles.membres(db, p)
    ids = [l.id for l in membres]
    v = recouvrement.ventilation_lot(db, copro, p)
    appels = _appels(db, [l["appel_id"] for l in v["lignes"]])

    dus, futurs = [], []
    for l in v["lignes"]:
        if l["restant_du"] <= 0:
            continue
        a = appels[l["appel_id"]]
        ligne = {"libelle": l["libelle"], "echeance": l["echeance"], "exercice": l["exercice"],
                 "montant": l["montant"], "restant_du": l["restant_du"], "nature": _nature(a, l["exercice"], jour)}
        (dus if l["echeance"] is None or l["echeance"] <= jour else futurs).append(ligne)
    du = arrondi(somme(x["restant_du"] for x in dus))
    credit = arrondi(v["avance_charges"] + v["avance_travaux"])

    # Provisions non encore appelées de l'exercice en cours : quote-part du budget voté − charges déjà appelées.
    ex_courant = db.query(Exercice).filter(Exercice.copropriete_id == copro.id, Exercice.annee == jour.year).first()
    qp = _quote_part_budget(db, copro, ex_courant, ids)
    appele_c, _ = _appele(db, ex_courant, ids)
    reste_budget = arrondi(max(qp - appele_c, D(0)))

    precedents = []
    for annee in (jour.year - 1, jour.year - 2):
        ex = db.query(Exercice).filter(Exercice.copropriete_id == copro.id, Exercice.annee == annee).first()
        c, f = _appele(db, ex, ids)
        reste = arrondi(somme(l["restant_du"] for l in v["lignes"] if l["exercice"] == annee))
        precedents.append({"annee": annee, "existe": ex is not None, "budget_quote_part": _quote_part_budget(db, copro, ex, ids),
                           "charges_appelees": c, "fonds_appeles": f, "reste_du": reste,
                           "approuve": bool(ex and ex.comptes_approuves_le)})

    # Fonds de travaux du lot : cotisations appelées, moins ce qui en reste dû ; dernière cotisation appelée.
    parts_ft = [(x, appels.get(x["appel_id"])) for x in v["lignes"] if x["fonds"] > 0]
    fonds_verse = arrondi(somme(x["fonds"] for x, _ in parts_ft) - somme(x["restant_du_fonds"] for x, _ in parts_ft))
    derniere = max(parts_ft, key=lambda t: (t[0]["echeance"] or date.min), default=None)

    # Copropriété : impayés de tous les lots (propriétaires actuels) et des vendeurs, factures non réglées.
    impayes = D(0)
    for g in ensembles.ensembles(db, copro.id):
        s = somme(totaux_lot(db, l)["solde"] for l in g)
        impayes += s if s > 0 else D(0)
    impayes = arrondi(impayes + somme(d for _, d in dus_vendeurs(db, copro)))
    fournisseurs = arrondi(somme(D(m.montant or 0) for m in db.query(Mouvement).filter(
        Mouvement.copropriete_id == copro.id, Mouvement.a_payer.is_(True))))

    actes = (db.query(ActeRecouvrement).filter(ActeRecouvrement.lot_id.in_(ids))
             .order_by(ActeRecouvrement.date_envoi).all())
    proprio = p.proprietaire
    return {
        "jour": jour, "lot": p, "membres": membres, "libelle_lots": ensembles.libelle(membres),
        "proprietaire": (proprio.nom_complet or proprio.email) if proprio else "—",
        "dus": dus, "du": du, "credit": credit, "futurs": futurs,
        "futurs_total": arrondi(somme(x["restant_du"] for x in futurs)), "reste_budget": reste_budget,
        "exercice_courant": jour.year if ex_courant else None, "precedents": precedents,
        "fonds_verse": fonds_verse,
        "derniere_cotisation": ({"libelle": derniere[0]["libelle"], "echeance": derniere[0]["echeance"],
                                 "montant": derniere[0]["fonds"], "reste": derniere[0]["restant_du_fonds"]}
                                if derniere else None),
        "impayes_copro": impayes, "dettes_fournisseurs": fournisseurs,
        "actes": [{"type": a.type, "date": a.date_envoi, "libelle": a.libelle} for a in actes],
    }


def categories_opposition(mutation_date: date, lignes: list[dict]) -> list[dict]:
    """Sommes dues par le vendeur réparties comme le demande l'art. 5-1 du décret de 1967."""
    a = mutation_date.year
    cats = [("Année courante et deux dernières années échues", lambda y: y >= a - 2),
            ("Deux années antérieures", lambda y: a - 4 <= y < a - 2),
            ("Années plus anciennes", lambda y: y < a - 4)]
    out = []
    for nom, test in cats:
        ls = [l for l in lignes if test(l["exercice"])]
        out.append({"categorie": nom, "lignes": ls, "total": arrondi(somme(l["restant_du"] for l in ls))})
    return out


# ---------------------------------------------------------------- PDF
def _tableau(lignes: list[list], largeurs: list[float]) -> Table:
    rows = [[Paragraph(f"<b>{c}</b>", style("th")) for c in lignes[0]]]
    rows += [[Paragraph(str(c), style("cell")) for c in l] for l in lignes[1:]]
    t = Table(rows, colWidths=[w * 2.835 for w in largeurs])
    t.setStyle(table_style())
    return t


def _entete(el, copro, titre: str, s: dict, sous_titre: str = ""):
    el.append(Paragraph(titre, style("titre")))
    el.append(Paragraph(sous_titre or f"Copropriété {copro.nom}", style("sous_titre")))
    adresse = " ".join(x for x in (copro.adresse, copro.code_postal, copro.ville) if x)
    infos = [["Copropriété", f"{copro.nom}{(' — ' + adresse) if adresse else ''}"],
             ["Lot(s)", s["libelle_lots"]],
             ["Copropriétaire (vendeur)", s["proprietaire"]],
             ["Situation arrêtée au", s["jour"].strftime("%d/%m/%Y")]]
    t = Table([[Paragraph(f"<b>{k}</b>", style("cell")), Paragraph(v, style("cell"))] for k, v in infos],
              colWidths=[50 * 2.835, 124 * 2.835])
    t.setStyle(table_style("#ffffff"))
    el.append(t)
    el.append(Spacer(1, 6))


def _pied(el, copro):
    el.append(Spacer(1, 10))
    lieu = f"à {copro.ville}, " if copro.ville else ""
    el.append(Paragraph(f"Fait {lieu}le {date.today():%d/%m/%Y}. Le syndic bénévole.", style("normal")))


def _lignes_dues(lignes: list[dict]) -> list[list]:
    return [["Appel", "Nature", "Échéance", "Montant", "Reste dû"]] + [
        [l["libelle"], l["nature"], l["echeance"].strftime("%d/%m/%Y") if l["echeance"] else "—",
         fmt_eur(l["montant"]), fmt_eur(l["restant_du"])] for l in lignes]


def _precedents(s: dict) -> list[list]:
    return [["Exercice", "Quote-part du budget voté", "Charges appelées", "Fonds de travaux appelé", "Reste dû"]] + [
        [str(p["annee"]) + ("" if p["approuve"] else " (comptes non approuvés)"),
         fmt_eur(p["budget_quote_part"]) if p["existe"] else "—", fmt_eur(p["charges_appelees"]),
         fmt_eur(p["fonds_appeles"]), fmt_eur(p["reste_du"])] for p in s["precedents"]]


def _pdf(titre: str, construire) -> BytesIO:
    register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=titre, **page_margins())
    el = []
    construire(el)
    doc.build(el)
    buf.seek(0)
    return buf


def pre_etat_date_pdf(db: Session, copro, lot: Lot, jour: date) -> BytesIO:
    s = situation(db, copro, lot, jour)

    def construire(el):
        _entete(el, copro, "PRÉ-ÉTAT DATÉ", s, "Informations financières à annexer à la promesse de vente "
                                               "(code de la construction et de l'habitation, art. L721-2)")
        el.append(Paragraph("1. Charges des deux exercices précédents", style("section")))
        el.append(Paragraph("Charges appelées au lot pour le budget prévisionnel et hors budget, et ce qui en reste dû.",
                            style("small", textColor=GRIS)))
        el.append(_tableau(_precedents(s), [26, 40, 34, 40, 34]))
        el.append(Paragraph("2. Sommes susceptibles d'être dues par l'acquéreur", style("section")))
        lignes = [["Poste", "Montant"]]
        lignes += [[f"{l['libelle']} (échéance {l['echeance']:%d/%m/%Y})", fmt_eur(l["restant_du"])] for l in s["futurs"]]
        if s["exercice_courant"]:
            lignes.append([f"Provisions de l'exercice {s['exercice_courant']} pas encore appelées (quote-part du budget voté, "
                           "estimation)", fmt_eur(s["reste_budget"])])
        if len(lignes) == 1:
            lignes.append(["Aucun appel émis non échu à cette date", fmt_eur(0)])
        el.append(_tableau(lignes, [134, 40]))
        el.append(Paragraph("3. Sommes dues par le vendeur au syndicat à cette date", style("section")))
        el.append(_tableau([["Poste", "Montant"], ["Appels échus non réglés", fmt_eur(s["du"])],
                            ["Avance ou trop-versé du vendeur (à déduire)", fmt_eur(s["credit"])]], [134, 40]))
        el.append(Paragraph("4. État global de la copropriété", style("section")))
        el.append(_tableau([["Poste", "Montant"],
                            ["Impayés de charges au sein du syndicat (tous les lots, anciens propriétaires compris)",
                             fmt_eur(s["impayes_copro"])],
                            ["Dette vis-à-vis des fournisseurs (factures reçues non réglées)", fmt_eur(s["dettes_fournisseurs"])]],
                           [134, 40]))
        el.append(Paragraph("5. Fonds de travaux", style("section")))
        d = s["derniere_cotisation"]
        el.append(_tableau([["Poste", "Montant"],
                            ["Part du fonds de travaux attachée au lot (cotisations réglées)", fmt_eur(s["fonds_verse"])],
                            ["Dernière cotisation appelée" + (f" ({d['libelle']}, {d['echeance']:%d/%m/%Y}"
                                                              f"{', réglée' if d['reste'] == 0 else ', non réglée'})" if d else ""),
                             fmt_eur(d["montant"]) if d else "—"]], [134, 40]))
        el.append(Spacer(1, 6))
        el.append(Paragraph(
            "À joindre aussi, hors de ce relevé : règlement de copropriété et état descriptif de division, procès-verbaux "
            "des assemblées des trois dernières années, fiche synthétique, carnet d'entretien, notice d'information, "
            "diagnostic technique global ou plan pluriannuel de travaux s'il existe (art. L721-2). Les montants sont "
            "établis d'après la comptabilité tenue dans Proprietas, sous réserve de l'apurement des comptes.",
            style("legal")))
        _pied(el, copro)

    return _pdf(f"Pré-état daté {s['libelle_lots']}", construire)


def etat_date_pdf(db: Session, copro, lot: Lot, jour: date, procedures: str = "") -> BytesIO:
    s = situation(db, copro, lot, jour)

    def construire(el):
        _entete(el, copro, "ÉTAT DATÉ", s, "Décret n° 67-223 du 17 mars 1967, article 5")
        el.append(Paragraph("1re partie — Sommes pouvant rester dues par le copropriétaire cédant au syndicat",
                            style("section")))
        el.append(_tableau(_lignes_dues(s["dus"]) if s["dus"] else [["Poste", "Montant"], ["Aucune somme exigible due", fmt_eur(0)]],
                           [52, 50, 24, 24, 24] if s["dus"] else [134, 40]))
        el.append(Paragraph(f"<b>Total : {fmt_eur(s['du'])}</b>", style("normal", alignment=2)))
        el.append(Paragraph("2e partie — Sommes dont le syndicat pourrait être débiteur envers le copropriétaire cédant",
                            style("section")))
        el.append(_tableau([["Poste", "Montant"], ["Avances et sommes versées en excédent", fmt_eur(s["credit"])]],
                           [134, 40]))
        el.append(Paragraph("3e partie — Sommes qui devraient incomber au nouveau copropriétaire", style("section")))
        lignes = [["Poste", "Montant"]]
        lignes += [[f"Provision non encore exigible : {l['libelle']} (échéance {l['echeance']:%d/%m/%Y})",
                    fmt_eur(l["restant_du"])] for l in s["futurs"]]
        if s["exercice_courant"]:
            lignes.append([f"Provisions du budget {s['exercice_courant']} pas encore appelées (quote-part du lot, estimation)",
                           fmt_eur(s["reste_budget"])])
        if len(lignes) == 1:
            lignes.append(["Aucune provision non exigible connue", fmt_eur(0)])
        el.append(_tableau(lignes, [134, 40]))
        el.append(Paragraph("Annexe — Quote-part du lot dans le budget et les charges des deux exercices précédents",
                            style("section")))
        el.append(_tableau(_precedents(s), [26, 40, 34, 40, 34]))
        el.append(Paragraph("Procédures en cours", style("section")))
        texte = (procedures or "").strip() or "Aucune procédure judiciaire en cours connue du syndic où le syndicat est partie."
        el.append(Paragraph(texte.replace("\n", "<br/>"), style("normal")))
        if s["actes"]:
            el.append(Paragraph("Démarches de recouvrement concernant ce lot : " + " ; ".join(
                f"{a['type']}{(' du ' + a['date'].strftime('%d/%m/%Y')) if a['date'] else ''}" for a in s["actes"]) + ".",
                style("small")))
        el.append(Spacer(1, 6))
        el.append(Paragraph(
            "Les indications des 1re et 2e parties peuvent être approximatives et sont données sous réserve de l'apurement "
            "des comptes (art. 5). À la date de la vente, les provisions exigibles restent dues par le vendeur ; celles qui "
            "deviennent exigibles ensuite, et le solde de la régularisation des comptes approuvés après la vente, "
            "reviennent à l'acquéreur (art. 6-2). Le prix de l'état daté est plafonné à 380 € TTC et à la charge du seul "
            "vendeur.", style("legal")))
        _pied(el, copro)

    return _pdf(f"État daté {s['libelle_lots']}", construire)


def opposition_pdf(db: Session, copro, m) -> tuple[BytesIO, dict]:
    from app.services.mutations import DELAI_OPPOSITION, compte_vendeur
    c = compte_vendeur(db, copro, m)
    lignes = [{"libelle": l["libelle"], "echeance": l["echeance"], "exercice": l["exercice"], "montant": l["montant"],
               "restant_du": l["restant_du"], "nature": "Charges et provisions"} for l in c["lignes"] if l["restant_du"] > 0]
    cats = categories_opposition(m.date_acte, lignes)
    limite = m.avis_mutation_le + timedelta(days=DELAI_OPPOSITION) if m.avis_mutation_le else None

    def construire(el):
        el.append(Paragraph("PROJET D'OPPOSITION AU VERSEMENT DU PRIX", style("titre")))
        el.append(Paragraph("Loi n° 65-557 du 10 juillet 1965, article 20 — à faire signifier par commissaire de justice",
                            style("sous_titre")))
        adresse = " ".join(x for x in (copro.adresse, copro.code_postal, copro.ville) if x)
        infos = [["Syndicat des copropriétaires", f"{copro.nom}{(' — ' + adresse) if adresse else ''}"],
                 ["Lot(s) vendu(s)", ensembles.libelle(ensembles.membres(db, m.lot))],
                 ["Vendeur", m.vendeur_nom or "—"], ["Acquéreur", m.acquereur_nom or "—"],
                 ["Date de la vente", m.date_acte.strftime("%d/%m/%Y")], ["Notaire", m.notaire or "……"],
                 ["Avis de mutation reçu le", m.avis_mutation_le.strftime("%d/%m/%Y") if m.avis_mutation_le else "……"],
                 ["Opposition à signifier au plus tard le", limite.strftime("%d/%m/%Y") if limite else "15 jours après l'avis"]]
        t = Table([[Paragraph(f"<b>{k}</b>", style("cell")), Paragraph(v, style("cell"))] for k, v in infos],
                  colWidths=[58 * 2.835, 116 * 2.835])
        t.setStyle(table_style("#ffffff"))
        el.append(t)
        el.append(Paragraph("Montant et causes de la créance", style("section")))
        for cat in cats:
            el.append(Paragraph(f"<b>{cat['categorie']}</b> : {fmt_eur(cat['total'])}", style("normal")))
            if cat["lignes"]:
                el.append(_tableau([["Appel", "Exercice", "Échéance", "Reste dû"]] + [
                    [l["libelle"], str(l["exercice"]), l["echeance"].strftime("%d/%m/%Y") if l["echeance"] else "—",
                     fmt_eur(l["restant_du"])] for l in cat["lignes"]], [80, 26, 30, 38]))
            el.append(Spacer(1, 4))
        el.append(Paragraph(f"<b>Total réclamé : {fmt_eur(c['du'])}</b>", style("normal", alignment=2)))
        el.append(Spacer(1, 6))
        el.append(Paragraph(
            "À peine de nullité, l'opposition énonce le montant et les causes de la créance et contient élection de domicile "
            "dans le ressort du tribunal judiciaire de la situation de l'immeuble (art. 20). Les créances sont distinguées "
            "comme ci-dessus (décret du 17 mars 1967, art. 5-1) ; les créances garanties par l'hypothèque légale du "
            "syndicat sont à indiquer par le commissaire de justice. Seules les sommes approuvées par l'assemblée ou "
            "exigibles peuvent être réclamées. Élection de domicile : ……", style("legal")))
        _pied(el, copro)

    return _pdf("Projet d'opposition", construire), {"total": c["du"], "categories": cats}

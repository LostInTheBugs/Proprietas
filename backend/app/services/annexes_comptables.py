"""Annexes comptables pour l'approbation des comptes (demande de Fred, 20/11/2026 ; revue Diacamma, point 3).

Les comptes sont présentés à l'assemblée avec cinq annexes (décret n° 2005-240 et arrêté du 14 mars 2005 ; décret
n° 67-223 du 17 mars 1967, art. 11) :
1. état financier à la clôture (trésorerie, créances, dettes, fonds de travaux) ;
2. compte de gestion général : charges et produits, réalisé et budget ;
3. compte de gestion des opérations courantes, par catégorie de charges ;
4. compte de gestion des travaux (art. 14-2) et opérations exceptionnelles ;
5. travaux et opérations exceptionnelles votés non encore clôturés.
Colonnes des comptes de gestion : réalisé N-1, budget N, réalisé N, budget N+1.

Proprietas tient une comptabilité de trésorerie (encaissements et dépenses), ce que permet le décret de 2005 aux
syndicats de moins de 10 lots dont le budget moyen est inférieur à 15 000 € (engagements constatés en fin
d'exercice : ici, les factures reçues non réglées). Les annexes en sont tirées ; elles reprennent les rubriques
des modèles réglementaires, sans prétendre en reproduire la mise en page. Catégories de charges : celles des
dépenses (et des lignes de budget), rapprochées des groupes de comptes de la classe 6 de l'arrêté.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table
from sqlalchemy.orm import Session

from app.core.money import D, arrondi, somme
from app.models.appel import AppelFonds, AppelLot
from app.models.exercice import BudgetLine, Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.models.travaux import Travaux
from app.services import reprise
from app.services.pdf_base import fmt_eur, page_margins, register_fonts, style, table_style

# Opérations courantes : catégorie → libellé (et comptes de l'arrêté du 14 mars 2005 qu'elle regroupe).
GROUPES = {
    "energie": "Eau, électricité, chauffage et combustibles (601 à 603)",
    "entretien": "Nettoyage, maintenance, entretien et petites réparations (611 à 615)",
    "assurance": "Primes d'assurances (616)",
    "charges": "Frais d'administration et honoraires, impôts, taxes et autres charges courantes (62, 63)",
    "autre": "Autres charges : frais financiers et divers (66, 678)",
}
TRAVAUX = ("travaux", "fonds_travaux")       # dépenses de l'annexe 4 (671 à 674)
GRIS = colors.HexColor("#666666")


# ---------------------------------------------------------------- calculs
def _exercice(db: Session, copro_id: int, annee: int) -> Exercice | None:
    return db.query(Exercice).filter(Exercice.copropriete_id == copro_id, Exercice.annee == annee).first()


def _depenses(db: Session, ex: Exercice | None) -> list[Mouvement]:
    if ex is None:
        return []
    return [m for m in db.query(Mouvement).filter(Mouvement.exercice_id == ex.id, Mouvement.type == "depense")
            if m.categorie != "avance"]


def _budget(db: Session, ex: Exercice | None) -> dict[str, D]:
    out = {g: D(0) for g in GROUPES}
    if ex is None:
        return out
    for b in db.query(BudgetLine).filter(BudgetLine.exercice_id == ex.id):
        g = b.categorie if b.categorie in GROUPES else "charges"
        out[g] += D(b.montant or 0)
    return {g: arrondi(v) for g, v in out.items()}


def _realise(db: Session, ex: Exercice | None) -> dict[str, D]:
    out = {g: D(0) for g in list(GROUPES) + list(TRAVAUX)}
    for m in _depenses(db, ex):
        g = m.categorie if m.categorie in out else "autre"
        out[g] += D(m.montant or 0)
    return {g: arrondi(v) for g, v in out.items()}


def _produits(db: Session, ex: Exercice | None) -> dict[str, D]:
    """Appels de l'exercice (provisions, régularisation, fonds de travaux) et produits divers encaissés."""
    out = {"provisions": D(0), "regularisation": D(0), "fonds_travaux": D(0), "divers": D(0)}
    if ex is None:
        return out
    for p, a in (db.query(AppelLot, AppelFonds).join(AppelFonds, AppelLot.appel_id == AppelFonds.id)
                 .filter(AppelFonds.exercice_id == ex.id, AppelFonds.reprise_etat_id.is_(None))):
        cle = "regularisation" if a.regularisation_de_id is not None else "provisions"
        out[cle] += D(p.montant_charges or 0)
        out["fonds_travaux"] += D(p.montant_fonds_travaux or 0)
    for m in db.query(Mouvement).filter(Mouvement.exercice_id == ex.id, Mouvement.type == "encaissement",
                                        Mouvement.lot_id.is_(None)):
        if m.categorie not in TRAVAUX:
            out["divers"] += D(m.montant or 0)
    return {k: arrondi(v) for k, v in out.items()}


def _tresorerie_au(db: Session, copro_id: int, jour: date) -> dict[str, D | None]:
    """Solde de chaque compte bancaire au `jour` d'après la comptabilité (relevé de la base + opérations)."""
    b = reprise.base(db, copro_id)
    sb = reprise.soldes_banque(db, copro_id, b.date) if b is not None else {c: None for c, _ in reprise.COMPTES}
    out = {}
    for compte, _ in reprise.COMPTES:
        depart = sb[compte]
        if depart is not None and jour < b.date:
            out[compte] = None
            continue
        f = reprise._flux(db, copro_id, b.date if depart is not None else None, jour)[compte]
        out[compte] = arrondi(D(depart or 0) + f["encaissement"] - f["depense"])
    return out


def etat_financier(db: Session, copro, jour: date) -> dict:
    """Annexe 1 au `jour` (31/12 de l'exercice) : actif (trésorerie, créances), passif (fonds de travaux, avances
    reçues, fournisseurs) et solde à régulariser qui les équilibre."""
    b = reprise.base(db, copro.id)
    creances, avances = D(0), D(0)
    for lot in db.query(Lot).filter(Lot.copropriete_id == copro.id):
        appels = somme(D(p.montant_charges or 0) + D(p.montant_fonds_travaux or 0)
                       for p, a in db.query(AppelLot, AppelFonds).join(AppelFonds, AppelLot.appel_id == AppelFonds.id)
                       .filter(AppelLot.lot_id == lot.id)
                       if reprise.appel_compte(a, b) and (a.date_echeance or a.date_emission) <= jour)
        recu = somme(D(m.montant or 0) for m in db.query(Mouvement).filter(
            Mouvement.lot_id == lot.id, Mouvement.type == "encaissement", Mouvement.date <= jour)
            if reprise.encaissement_compte(m, b))
        solde = appels - recu
        if solde > 0:
            creances += solde
        else:
            avances += -solde
    fournisseurs = somme(D(m.montant or 0) for m in db.query(Mouvement).filter(
        Mouvement.copropriete_id == copro.id, Mouvement.type == "depense", Mouvement.date <= jour)
        if m.a_payer or (m.paye_le is not None and m.paye_le > jour))
    cotisations = somme(D(p.montant_fonds_travaux or 0)
                        for p, a in db.query(AppelLot, AppelFonds).join(AppelFonds, AppelLot.appel_id == AppelFonds.id)
                        .join(Exercice, AppelFonds.exercice_id == Exercice.id)
                        .filter(Exercice.copropriete_id == copro.id)
                        if (a.date_echeance or a.date_emission) <= jour)
    utilise = somme(D(m.montant or 0) for m in db.query(Mouvement).filter(
        Mouvement.copropriete_id == copro.id, Mouvement.type == "depense", Mouvement.categorie == "fonds_travaux",
        Mouvement.date <= jour))
    tres = _tresorerie_au(db, copro.id, jour)
    actif = [("Compte bancaire du syndicat", tres["syndicat"]), ("Compte du fonds de travaux", tres["fonds_travaux"]),
             ("Copropriétaires débiteurs", arrondi(creances))]
    passif = [("Fonds de travaux (cotisations appelées − dépenses imputées)", arrondi(cotisations - utilise)),
              ("Copropriétaires créditeurs (avances et paiements d'avance)", arrondi(avances)),
              ("Fournisseurs : factures reçues non réglées", arrondi(fournisseurs))]
    total_actif = arrondi(somme(v for _, v in actif if v is not None))
    solde = arrondi(total_actif - somme(v for _, v in passif))
    passif.append(("Excédent (ou insuffisance, si négatif) des provisions sur les charges, à régulariser", solde))
    return {"jour": jour, "actif": actif, "passif": passif, "total_actif": total_actif,
            "total_passif": arrondi(somme(v for _, v in passif)),
            "tresorerie_incomplete": any(v is None for _, v in actif)}


def annexes(db: Session, copro, ex: Exercice) -> dict:
    n = ex.annee
    ex_prec, ex_suiv = _exercice(db, copro.id, n - 1), _exercice(db, copro.id, n + 1)
    real = {n - 1: _realise(db, ex_prec), n: _realise(db, ex)}
    bud = {n: _budget(db, ex), n + 1: _budget(db, ex_suiv)}
    prod = {n - 1: _produits(db, ex_prec), n: _produits(db, ex)}
    courantes = [{"groupe": g, "libelle": lib, "realise_prec": real[n - 1][g], "budget": bud[n][g],
                  "realise": real[n][g], "budget_suiv": bud[n + 1][g]} for g, lib in GROUPES.items()]
    tot = lambda cle: arrondi(somme(l[cle] for l in courantes))     # noqa: E731
    travaux = {k: {"travaux": real[k]["travaux"], "fonds_travaux": real[k]["fonds_travaux"]} for k in (n - 1, n)}
    en_cours = (db.query(Travaux).filter(Travaux.copropriete_id == copro.id, Travaux.annee <= n,
                                         Travaux.statut != "realise").order_by(Travaux.annee, Travaux.id).all())
    return {
        "annee": n, "exercice_prec": ex_prec is not None, "exercice_suiv": ex_suiv is not None,
        "etat_financier": etat_financier(db, copro, date(n, 12, 31)),
        "courantes": courantes,
        "totaux_courantes": {k: tot(k) for k in ("realise_prec", "budget", "realise", "budget_suiv")},
        "travaux": travaux, "produits": prod,
        "en_cours": [{"libelle": t.libelle, "categorie": t.categorie, "annee": t.annee,
                      "montant": arrondi(D(t.montant or 0)), "statut": t.statut} for t in en_cours],
    }


# ---------------------------------------------------------------- PDF
def _t(lignes, largeurs, gras_derniere=False):
    rows = [[Paragraph(f"<b>{c}</b>", style("th")) for c in lignes[0]]]
    for i, l in enumerate(lignes[1:], start=1):
        g = gras_derniere and i == len(lignes) - 1
        rows.append([Paragraph(f"<b>{c}</b>" if g else str(c), style("cell")) for c in l])
    t = Table(rows, colWidths=[w * 2.835 for w in largeurs], repeatRows=1)
    t.setStyle(table_style())
    return t


def _e(v) -> str:
    return "—" if v is None else fmt_eur(v)


def annexes_pdf(db: Session, copro, ex: Exercice) -> BytesIO:
    a = annexes(db, copro, ex)
    n = a["annee"]
    register_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), title=f"Annexes comptables {copro.nom} {n}", **page_margins())
    el = []
    titre = lambda t: el.extend([Paragraph(t, style("titre", fontSize=13)),                       # noqa: E731
                                 Paragraph(f"Copropriété {copro.nom} — exercice {n} (du 1er janvier au 31 décembre {n})",
                                           style("sous_titre"))])
    entetes = ["Rubrique", f"Réalisé {n - 1}", f"Budget voté {n}", f"Réalisé {n}", f"Budget {n + 1}"]
    larg = [118, 36, 36, 36, 36]

    # Annexe 1
    ef = a["etat_financier"]
    titre(f"ANNEXE 1 — ÉTAT FINANCIER AU 31 DÉCEMBRE {n}")
    gauche = [["Actif (ce que le syndicat a ou doit recevoir)", "Montant"]] + [[k, _e(v)] for k, v in ef["actif"]] + \
        [["Total", fmt_eur(ef["total_actif"])]]
    droite = [["Passif (ce que le syndicat doit ou réserve)", "Montant"]] + [[k, fmt_eur(v)] for k, v in ef["passif"]] + \
        [["Total", fmt_eur(ef["total_passif"])]]
    from reportlab.platypus import TableStyle
    cote = Table([[_t(gauche, [92, 34], True), _t(droite, [92, 34], True)]], colWidths=[130 * 2.835, 130 * 2.835])
    cote.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    el.append(cote)
    if ef["tresorerie_incomplete"]:
        el.append(Paragraph("Trésorerie non disponible avant la date du relevé bancaire de départ (Historique).",
                            style("small", textColor=GRIS)))
    el.append(Spacer(1, 4))
    el.append(Paragraph(
        "Trésorerie : relevé bancaire de départ et opérations enregistrées jusqu'au 31 décembre. Créances et avances : "
        "appels échus et paiements reçus à cette date, lot par lot. La dernière ligne du passif équilibre l'état : elle "
        "se régularise lors de l'approbation des comptes (répartition de l'excédent ou de l'insuffisance).",
        style("legal")))

    # Annexe 2
    el.append(PageBreak())
    titre(f"ANNEXE 2 — COMPTE DE GESTION GÉNÉRAL DE L'EXERCICE {n}")
    tc = a["totaux_courantes"]
    tr = {k: arrondi(v["travaux"] + v["fonds_travaux"]) for k, v in a["travaux"].items()}
    p = a["produits"]
    pc = {k: arrondi(p[k]["provisions"] + p[k]["regularisation"] + p[k]["divers"]) for k in p}
    lignes = [entetes,
              ["Charges des opérations courantes", fmt_eur(tc["realise_prec"]), fmt_eur(tc["budget"]), fmt_eur(tc["realise"]),
               fmt_eur(tc["budget_suiv"])],
              ["Charges des travaux (art. 14-2) et opérations exceptionnelles", fmt_eur(tr[n - 1]), "—", fmt_eur(tr[n]), "—"],
              ["Total des charges", fmt_eur(tc["realise_prec"] + tr[n - 1]), fmt_eur(tc["budget"]),
               fmt_eur(tc["realise"] + tr[n]), fmt_eur(tc["budget_suiv"])],
              ["Provisions appelées (opérations courantes)", fmt_eur(p[n - 1]["provisions"]), fmt_eur(tc["budget"]),
               fmt_eur(p[n]["provisions"]), fmt_eur(tc["budget_suiv"])],
              ["Régularisation des charges appelée", fmt_eur(p[n - 1]["regularisation"]), "—", fmt_eur(p[n]["regularisation"]), "—"],
              ["Produits divers (encaissements hors copropriétaires)", fmt_eur(p[n - 1]["divers"]), "—", fmt_eur(p[n]["divers"]), "—"],
              ["Cotisations au fonds de travaux appelées", fmt_eur(p[n - 1]["fonds_travaux"]), "—",
               fmt_eur(p[n]["fonds_travaux"]), "—"],
              ["Résultat des opérations courantes (produits − charges)", fmt_eur(pc[n - 1] - tc["realise_prec"]), "—",
               fmt_eur(pc[n] - tc["realise"]), "—"]]
    el.append(_t(lignes, larg, True))
    if not a["exercice_prec"] or not a["exercice_suiv"]:
        el.append(Paragraph(("" if a["exercice_prec"] else f"Pas d'exercice {n - 1} dans Proprietas. ")
                            + ("" if a["exercice_suiv"] else f"Pas encore de budget {n + 1}."), style("small", textColor=GRIS)))

    # Annexe 3
    el.append(PageBreak())
    titre(f"ANNEXE 3 — COMPTE DE GESTION DES OPÉRATIONS COURANTES DE L'EXERCICE {n}")
    lignes = [["Catégorie de charges"] + entetes[1:]] + [
        [l["libelle"], fmt_eur(l["realise_prec"]), fmt_eur(l["budget"]), fmt_eur(l["realise"]), fmt_eur(l["budget_suiv"])]
        for l in a["courantes"]] + [["Total", fmt_eur(tc["realise_prec"]), fmt_eur(tc["budget"]), fmt_eur(tc["realise"]),
                                     fmt_eur(tc["budget_suiv"])]]
    el.append(_t(lignes, larg, True))
    el.append(Spacer(1, 4))
    el.append(Paragraph("Charges : dépenses de l'exercice (factures réglées ou reçues non réglées), par catégorie ; budget : "
                        "lignes du budget voté, par catégorie. Écart à expliquer en assemblée.", style("legal")))

    # Annexe 4
    el.append(PageBreak())
    titre(f"ANNEXE 4 — COMPTE DE GESTION DES TRAVAUX DE L'ARTICLE 14-2 ET OPÉRATIONS EXCEPTIONNELLES — {n}")
    t = a["travaux"]
    lignes = [["Rubrique", f"Réalisé {n - 1}", f"Réalisé {n}"],
              ["Travaux décidés par l'assemblée (hors budget prévisionnel)", fmt_eur(t[n - 1]["travaux"]), fmt_eur(t[n]["travaux"])],
              ["Dépenses imputées sur le fonds de travaux", fmt_eur(t[n - 1]["fonds_travaux"]), fmt_eur(t[n]["fonds_travaux"])],
              ["Total des charges", fmt_eur(tr[n - 1]), fmt_eur(tr[n])],
              ["Cotisations au fonds de travaux appelées (produits)", fmt_eur(p[n - 1]["fonds_travaux"]), fmt_eur(p[n]["fonds_travaux"])]]
    el.append(_t(lignes, [150, 50, 50]))

    # Annexe 5
    el.append(Spacer(1, 12))
    el.append(Paragraph(f"ANNEXE 5 — TRAVAUX ET OPÉRATIONS EXCEPTIONNELLES VOTÉS NON ENCORE CLÔTURÉS AU 31 DÉCEMBRE {n}",
                        style("titre", fontSize=13)))
    if a["en_cours"]:
        statuts = {"planifie": "votés, non commencés", "en_cours": "en cours"}
        lignes = [["Opération", "Catégorie", "Année", "Montant prévu", "État"]] + [
            [x["libelle"], x["categorie"], str(x["annee"]), fmt_eur(x["montant"]), statuts.get(x["statut"], x["statut"])]
            for x in a["en_cours"]]
        el.append(_t(lignes, [110, 40, 20, 40, 50]))
    else:
        el.append(Paragraph("Aucune opération en cours (page Travaux).", style("normal")))
    el.append(Spacer(1, 10))
    el.append(Paragraph(
        "Annexes établies d'après la comptabilité de trésorerie tenue dans Proprietas (décret n° 2005-240 et arrêté du 14 mars "
        "2005 ; syndicats de moins de 10 lots au budget moyen inférieur à 15 000 € : comptabilité en partie double non "
        "obligatoire, engagements constatés en fin d'exercice). Elles reprennent les rubriques des modèles réglementaires ; "
        "à vérifier avant l'envoi avec la convocation (décret du 17 mars 1967, art. 11).", style("legal")))
    doc.build(el)
    buf.seek(0)
    return buf

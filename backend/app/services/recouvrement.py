"""Recouvrement des impayés : décompte par lot, statut du dossier, calculs.

Principes :
- Décompte : imputation FIFO des encaissements du lot sur les appels les plus
  anciens (pratique usuelle) — chaque appel porte un « restant dû » et un flag
  « échu » (échéance dépassée). Distingue l'arriéré exigible des provisions à échoir.
- Statut : jamais stocké, recalculé à la lecture depuis les actes + le solde.
- Article 19-2 : sommes devenues exigibles = provisions NON échues de l'exercice
  en cours + restants dus des exercices précédents.
"""
import json
from datetime import date

from sqlalchemy.orm import Session

from app.models.appel import AppelFonds, AppelLot
from app.models.copropriete import Copropriete
from app.models.exercice import Exercice
from app.models.mouvement import Mouvement
from app.models.recouvrement import ActeRecouvrement

# Types d'actes créables via l'API (l'activation 19-2 a sa route dédiée).
TYPES_ACTE = ("mise_en_demeure", "frais", "conciliation", "commissaire_justice", "tribunal", "note")
MODES_ENVOI = ("lre", "lrar", "email", "remise")
DELAI_19_2_JOURS = 30

LIBELLES_STATUT = {
    "a_jour": "À jour",
    "en_retard": "Impayé — à relancer",
    "mise_en_demeure": "Mise en demeure — délai en cours",
    "delai_19_2_depasse": "Délai de 30 jours dépassé — 19-2 activable",
    "apres_19_2": "Article 19-2 activé — provisions exigibles",
    "amiable": "Procédure amiable (conciliation)",
    "contentieux": "Procédure judiciaire",
}


def appels_lot(db: Session, copro: Copropriete, lot) -> list[dict]:
    """Décompte du lot : appels triés (échéance puis émission), encaissements imputés FIFO."""
    paires = (
        db.query(AppelLot, AppelFonds, Exercice)
        .join(AppelFonds, AppelLot.appel_id == AppelFonds.id)
        .join(Exercice, AppelFonds.exercice_id == Exercice.id)
        .filter(AppelLot.lot_id == lot.id, Exercice.copropriete_id == copro.id)
        .all()
    )
    paires.sort(key=lambda x: (x[1].date_echeance or x[1].date_emission or date.min, x[1].id))
    encaisse = round(sum((m.montant or 0.0) for m in db.query(Mouvement).filter(
        Mouvement.lot_id == lot.id, Mouvement.type == "encaissement").all()), 2)

    reste = encaisse
    lignes = []
    for part, appel, ex in paires:
        montant = round((part.montant_charges or 0.0) + (part.montant_fonds_travaux or 0.0), 2)
        impute = min(reste, montant)
        reste = round(reste - impute, 2)
        echeance = appel.date_echeance or appel.date_emission
        lignes.append({
            "appel_id": appel.id,
            "exercice_id": ex.id,
            "exercice": ex.annee,
            "libelle": appel.libelle or "",
            "echeance": echeance,
            "charges": round(part.montant_charges or 0.0, 2),
            "fonds": round(part.montant_fonds_travaux or 0.0, 2),
            "montant": montant,
            "restant_du": round(montant - impute, 2),
            "echu": bool(echeance and echeance <= date.today()),
        })
    return lignes


def solde_lot(lignes: list[dict]) -> float:
    """Solde impayé du lot (jamais négatif : un crédit n'est pas une dette)."""
    return round(max(sum(l["restant_du"] for l in lignes), 0.0), 2)


def arriere_echu(lignes: list[dict]) -> float:
    """Provisions échues (exigibles) restant dues."""
    return round(sum(l["restant_du"] for l in lignes if l["echu"]), 2)


def retard_depuis(lignes: list[dict]) -> date | None:
    """Date de la plus ancienne échéance échue restant due (ancienneté du retard)."""
    dates = [l["echeance"] for l in lignes if l["restant_du"] > 0.005 and l["echu"] and l["echeance"]]
    return min(dates) if dates else None


def exercice_courant(db: Session, copro: Copropriete) -> Exercice | None:
    """Exercice en cours (dernier non clôturé), sinon le plus récent."""
    ex = (db.query(Exercice).filter(Exercice.copropriete_id == copro.id, Exercice.cloture.is_(False))
          .order_by(Exercice.annee.desc()).first())
    if ex is None:
        ex = (db.query(Exercice).filter(Exercice.copropriete_id == copro.id)
              .order_by(Exercice.annee.desc()).first())
    return ex


def actes_lot(db: Session, copro: Copropriete, lot) -> list[ActeRecouvrement]:
    return (db.query(ActeRecouvrement)
            .filter(ActeRecouvrement.copropriete_id == copro.id, ActeRecouvrement.lot_id == lot.id)
            .order_by(ActeRecouvrement.date_acte, ActeRecouvrement.id).all())


def details_acte(acte: ActeRecouvrement) -> dict:
    try:
        return json.loads(acte.details_json or "{}")
    except (ValueError, TypeError):
        return {}


def statut_dossier(db: Session, copro: Copropriete, lot, lignes=None, actes=None) -> dict:
    """Statut + calculs du dossier de recouvrement d'un lot."""
    lignes = lignes if lignes is not None else appels_lot(db, copro, lot)
    actes = actes if actes is not None else actes_lot(db, copro, lot)
    solde = solde_lot(lignes)
    echu = arriere_echu(lignes)
    frais = round(sum((a.montant or 0.0) for a in actes if a.type == "frais"), 2)

    md = None
    for a in actes:
        if a.type == "mise_en_demeure":
            md = a  # actes triés par date → le dernier MD gagne
    a_19_2 = any(a.type == "activation_19_2" for a in actes)
    a_conciliation = any(a.type == "conciliation" for a in actes)
    a_justice = any(a.type in ("commissaire_justice", "tribunal") for a in actes)

    statut, md_jours, jours_restants = "a_jour", None, None
    if solde > 0.005:
        if a_justice:
            statut = "contentieux"
        elif a_conciliation:
            statut = "amiable"
        elif a_19_2:
            statut = "apres_19_2"
        elif md is not None and md.date_envoi:
            md_jours = (date.today() - md.date_envoi).days
            if md_jours >= DELAI_19_2_JOURS:
                statut = "delai_19_2_depasse"
            else:
                statut = "mise_en_demeure"
                jours_restants = DELAI_19_2_JOURS - md_jours
        else:
            statut = "en_retard"

    taux = float(copro.taux_legal_retard or 0.0)
    interets = 0.0
    if md is not None and md.date_envoi and solde > 0.005 and taux > 0:
        base = md.montant or echu or solde
        jours = max((date.today() - md.date_envoi).days, 0)
        interets = round(base * (taux / 100.0) * jours / 365.0, 2)

    return {
        "solde": solde,
        "arriere_echu": echu,
        "retard_depuis": retard_depuis(lignes),
        "statut": statut,
        "statut_label": LIBELLES_STATUT[statut],
        "md": md,
        "md_jours": md_jours,
        "jours_restants": jours_restants,
        "frais_total": frais,
        "interets": interets,
        "taux": taux,
        "total_reclame": round(solde + frais, 2),
        "actes": actes,
    }


def breakdown_19_2(db: Session, copro: Copropriete, lot, lignes=None) -> dict:
    """Sommes qui deviennent exigibles au titre de l'article 19-2.

    = provisions NON échues de l'exercice en cours + restants dus des exercices
    précédents (après approbation des comptes — proxy : exercices antérieurs).
    """
    lignes = lignes if lignes is not None else appels_lot(db, copro, lot)
    ex = exercice_courant(db, copro)
    retenues, total = [], 0.0
    for l in lignes:
        if l["restant_du"] <= 0.005:
            continue
        if ex is None:
            continue
        if l["exercice_id"] == ex.id:
            if not l["echu"]:
                retenues.append(l)
                total += l["restant_du"]
        else:
            retenues.append(l)
            total += l["restant_du"]
    return {
        "lignes": retenues,
        "total": round(total, 2),
        "arriere_echu": arriere_echu(lignes),
        "exercice": ex.annee if ex else None,
    }

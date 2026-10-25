"""Recouvrement des impayés : décompte par lot, statut du dossier, calculs.

Principes :
- Décompte : imputation FIFO des encaissements du lot sur les appels les plus
  anciens (pratique usuelle) — chaque appel porte un « restant dû » et un flag
  « échu » (échéance dépassée). Distingue l'arriéré exigible des provisions à échoir.
- Statut : jamais stocké, recalculé à la lecture depuis les actes + le solde.
- Article 19-2 : sommes devenues exigibles = provisions NON échues de l'exercice
  en cours + restants dus des exercices précédents dont les comptes sont approuvés.
"""
import json
from datetime import date, timedelta

from sqlalchemy.orm import Session

from decimal import Decimal

from app.core.money import D, arrondi, somme
from app.models.appel import AppelFonds, AppelLot
from app.models.copropriete import Copropriete
from app.models.exercice import Exercice
from app.models.mouvement import Mouvement
from app.models.recouvrement import ActeRecouvrement

# Types d'actes créables via l'API (l'activation 19-2 a sa route dédiée).
TYPES_ACTE = ("mise_en_demeure", "frais", "conciliation", "commissaire_justice", "tribunal", "note")
# Modes valant notification de la mise en demeure (décret n° 67-223, art. 64 et s., rédaction
# du décret n° 2025-1292) : LRE (règle), LRAR (si la voie postale est demandée, art. 64-1),
# signification par commissaire de justice (toujours possible, CPC art. 651). Un e-mail simple
# n'en fait pas partie ; la remise contre récépissé non plus (art. 64-3 : convocations et avis
# de l'art. 59 seulement) — d'anciennes saisies « remise » restent au journal sans effet.
MODES_ENVOI = ("lre", "lrar", "signification")
DELAI_19_2_JOURS = 30

LIBELLES_STATUT = {
    "a_jour": "À jour",
    "en_retard": "Impayé — à relancer",
    "mise_en_demeure_attente": "Mise en demeure envoyée — date de présentation à saisir",
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
    encaisse = arrondi(somme(D(m.montant or D(0)) for m in db.query(Mouvement).filter(
        Mouvement.lot_id == lot.id, Mouvement.type == "encaissement").all()))

    reste = encaisse
    lignes = []
    for part, appel, ex in paires:
        montant = arrondi((part.montant_charges or D(0)) + (part.montant_fonds_travaux or D(0)))
        impute = min(reste, montant)
        reste = arrondi(reste - impute)
        echeance = appel.date_echeance or appel.date_emission
        lignes.append({
            "appel_id": appel.id,
            "exercice_id": ex.id,
            "exercice": ex.annee,
            "libelle": appel.libelle or "",
            "echeance": echeance,
            "charges": arrondi(part.montant_charges or D(0)),
            "fonds": arrondi(part.montant_fonds_travaux or D(0)),
            "montant": montant,
            "restant_du": arrondi(montant - impute),
            "echu": bool(echeance and echeance <= date.today()),
            "comptes_approuves": ex.comptes_approuves_le is not None,
        })
    return lignes


def solde_lot(lignes: list[dict]) -> Decimal:
    """Solde impayé du lot (jamais négatif : un crédit n'est pas une dette)."""
    return arrondi(max(somme(l["restant_du"] for l in lignes), D(0)))


def arriere_echu(lignes: list[dict]) -> Decimal:
    """Provisions échues (exigibles) restant dues."""
    return arrondi(somme(l["restant_du"] for l in lignes if l["echu"]))


def retard_depuis(lignes: list[dict]) -> date | None:
    """Date de la plus ancienne échéance échue restant due (ancienneté du retard)."""
    dates = [l["echeance"] for l in lignes if l["restant_du"] > D("0.005") and l["echu"] and l["echeance"]]
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
    frais = arrondi(somme(a.montant or D(0) for a in actes if a.type == "frais"))

    md = None
    for a in actes:
        # Seule une mise en demeure NOTIFIÉE (LRE, LRAR, signification) compte ; une ancienne
        # « mise en demeure » par e-mail ou remise reste au journal mais ne fait courir aucun délai.
        if a.type == "mise_en_demeure" and (a.mode_envoi or "") in MODES_ENVOI:
            md = a  # actes triés par date → le dernier MD gagne
    a_19_2 = any(a.type == "activation_19_2" for a in actes)
    a_conciliation = any(a.type == "conciliation" for a in actes)
    a_justice = any(a.type in ("commissaire_justice", "tribunal") for a in actes)

    statut, md_jours, jours_restants, activable_le = "a_jour", None, None, None
    if solde > D("0.005"):
        if a_justice:
            statut = "contentieux"
        elif a_conciliation:
            statut = "amiable"
        elif a_19_2:
            statut = "apres_19_2"
        elif md is not None and md.date_reception is None:
            statut = "mise_en_demeure_attente"
        elif md is not None:
            # Délai de 30 jours du LENDEMAIN de la présentation (J+1) à J+30 : exigible à J+31.
            md_jours = (date.today() - md.date_reception).days
            activable_le = md.date_reception + timedelta(days=DELAI_19_2_JOURS + 1)
            if date.today() >= activable_le:
                statut = "delai_19_2_depasse"
            else:
                statut = "mise_en_demeure"
                jours_restants = (activable_le - date.today()).days
        else:
            statut = "en_retard"

    taux = copro.taux_legal_retard or D(0)
    interets = D(0)
    if md is not None and md.date_reception and solde > D("0.005") and taux > 0:
        # Intérêts au taux légal à compter de la mise en demeure, c'est-à-dire de sa présentation.
        base = md.montant or echu or solde
        jours = max((date.today() - md.date_reception).days, 0)
        interets = arrondi(base * taux / D(100) * D(jours) / D(365))

    return {
        "solde": solde,
        "arriere_echu": echu,
        "retard_depuis": retard_depuis(lignes),
        "statut": statut,
        "statut_label": LIBELLES_STATUT[statut],
        "md": md,
        "md_jours": md_jours,
        "activable_le": activable_le,
        "activable_19_2": activable_le is not None and date.today() >= activable_le,
        "jours_restants": jours_restants,
        "frais_total": frais,
        "interets": interets,
        "taux": taux,
        "total_reclame": arrondi(solde + frais),
        "actes": actes,
    }


def breakdown_19_2(db: Session, copro: Copropriete, lot, lignes=None) -> dict:
    """Sommes qui deviennent exigibles au titre de l'article 19-2.

    = provisions NON échues de l'exercice en cours + restants dus des exercices
    précédents dont les comptes ont été APPROUVÉS par l'AG (exercices.comptes_approuves_le).
    Un exercice précédent non approuvé est exclu et signalé (exercices_non_approuves) :
    ses provisions échues restent dues au titre de l'arriéré, hors 19-2.
    """
    lignes = lignes if lignes is not None else appels_lot(db, copro, lot)
    ex = exercice_courant(db, copro)
    retenues, non_approuves = [], set()
    # Ventilation en 4 parts DISJOINTES (leur somme = solde du lot) : les deux premières forment
    # le total 19-2 ; les deux autres restent dues en dehors du 19-2.
    parts = {"a_echoir": D(0), "precedents_approuves": D(0),
             "echu_courant": D(0), "precedents_non_approuves": D(0)}
    for l in lignes:
        if l["restant_du"] <= D("0.005"):
            continue
        if ex is None:
            continue
        if l["exercice_id"] == ex.id:
            if not l["echu"]:
                retenues.append(l)
                parts["a_echoir"] += l["restant_du"]
            else:
                parts["echu_courant"] += l["restant_du"]
        elif l.get("comptes_approuves"):
            retenues.append(l)
            parts["precedents_approuves"] += l["restant_du"]
        else:
            non_approuves.add(l["exercice"])
            parts["precedents_non_approuves"] += l["restant_du"]
    return {
        "lignes": retenues,
        "total": arrondi(parts["a_echoir"] + parts["precedents_approuves"]),
        "arriere_echu": arriere_echu(lignes),
        "exercice": ex.annee if ex else None,
        "exercices_non_approuves": sorted(non_approuves),
        **{k: arrondi(v) for k, v in parts.items()},
    }

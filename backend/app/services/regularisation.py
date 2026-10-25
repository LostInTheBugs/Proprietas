"""Régularisation des charges après approbation des comptes.

Loi n° 65-557, art. 14-1 : les copropriétaires versent des provisions sur le budget prévisionnel.
Décret n° 67-223, art. 6-2, 3° : « le trop ou moins perçu sur provisions, révélé par
l'approbation des comptes, est porté au crédit ou au débit du compte de celui qui est
copropriétaire lors de l'approbation des comptes » (Cass. 3e civ., 14 avr. 2016, n° 15-14.356).

- Charges réelles : dépenses de l'exercice hors fonds de travaux et hors travaux (financés par
  des appels distincts). Une dépense rattachée à un lot est imputée à ce seul lot ; les autres
  sont réparties aux tantièmes (plus fort reste).
- Provisions : parts « charges » des appels de l'exercice, hors appel de régularisation. Les
  cotisations au fonds de travaux ne sont jamais régularisées (art. 14-2-1 : acquises au syndicat).
- Écart = réel − provisions : complément (> 0) ou crédit (< 0), dans un appel « Régularisation
  des charges » rattaché à l'exercice approuvé. Le lot est celui du propriétaire ACTUEL.
"""
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.money import D, arrondi, somme
from app.models.appel import AppelFonds, AppelLot
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.services.country_rules import repartir_par_tantiemes

CATEGORIES_HORS_CHARGES = ("fonds_travaux", "travaux")


def appel_existant(db: Session, ex) -> AppelFonds | None:
    return db.query(AppelFonds).filter(AppelFonds.regularisation_de_id == ex.id).first()


def calcul(db: Session, ex) -> dict:
    lots = (db.query(Lot).filter(Lot.copropriete_id == ex.copropriete_id)
            .order_by(Lot.id).all())
    depenses = (db.query(Mouvement).filter(Mouvement.exercice_id == ex.id, Mouvement.type == "depense")
                .all())
    courantes = [m for m in depenses if (m.categorie or "autre") not in CATEGORIES_HORS_CHARGES]
    communes = arrondi(somme(D(m.montant or 0) for m in courantes if m.lot_id is None))
    reel = {lot.id: D(0) for lot in lots}
    if lots and communes:
        for p in repartir_par_tantiemes(communes, lots):
            reel[p["lot"].id] += p["montant_charges"]
    for m in courantes:
        if m.lot_id in reel:
            reel[m.lot_id] += D(m.montant or 0)

    provisions = {lot.id: D(0) for lot in lots}
    parts = (db.query(AppelLot).join(AppelFonds, AppelLot.appel_id == AppelFonds.id)
             .filter(AppelFonds.exercice_id == ex.id, AppelFonds.regularisation_de_id.is_(None)).all())
    for p in parts:
        if p.lot_id in provisions:
            provisions[p.lot_id] += D(p.montant_charges or 0)

    lignes = []
    for lot in lots:
        r, pr = arrondi(reel[lot.id]), arrondi(provisions[lot.id])
        lignes.append({"lot_id": lot.id, "lot_numero": lot.numero, "provisions": pr,
                       "charges_reelles": r, "ecart": arrondi(r - pr)})
    existant = appel_existant(db, ex)
    return {
        "exercice_id": ex.id, "annee": ex.annee,
        "approuve": ex.comptes_approuves_le is not None,
        "comptes_approuves_le": ex.comptes_approuves_le,
        "appel_id": existant.id if existant else None,
        "lignes": lignes,
        "total_provisions": arrondi(somme(l["provisions"] for l in lignes)),
        "total_charges_reelles": arrondi(somme(l["charges_reelles"] for l in lignes)),
        "total_ecart": arrondi(somme(l["ecart"] for l in lignes)),
    }


def creer(db: Session, ex, date_echeance: date) -> AppelFonds:
    if ex.comptes_approuves_le is None:
        raise HTTPException(422, "Régularisation impossible avant l'approbation des comptes de "
                                 "l'exercice par l'assemblée générale (décret n° 67-223, art. 6-2).")
    if appel_existant(db, ex) is not None:
        raise HTTPException(409, f"Les charges de l'exercice {ex.annee} sont déjà régularisées.")
    if date_echeance < date.today():
        raise HTTPException(422, "L'échéance de la régularisation ne peut pas être dans le passé.")
    c = calcul(db, ex)
    lignes = [l for l in c["lignes"] if l["ecart"] != Decimal("0")]
    if not lignes:
        raise HTTPException(422, "Aucun écart entre provisions et charges réelles : rien à régulariser.")
    appel = AppelFonds(
        exercice_id=ex.id, regularisation_de_id=ex.id,
        libelle=f"Régularisation des charges {ex.annee}",
        date_emission=date.today(), date_echeance=date_echeance,
        montant_total=c["total_ecart"], inclut_fonds_travaux=False, fonds_travaux_montant=D(0),
    )
    db.add(appel)
    db.flush()
    for l in lignes:
        db.add(AppelLot(appel_id=appel.id, lot_id=l["lot_id"], montant_charges=l["ecart"],
                        montant_fonds_travaux=D(0)))
    return appel

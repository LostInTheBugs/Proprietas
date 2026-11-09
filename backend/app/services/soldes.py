"""Totaux par lot (appels, encaissements, solde) : un seul calcul pour tout l'application.

Le même calcul était recopié dans six écrans (soldes des lots, relances, récapitulatif des comptes,
compte de gestion, rapport annuel). Il est centralisé ici pour qu'une règle commune s'applique
partout de la même façon.
"""
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.money import D, arrondi, somme
from app.models.appel import AppelFonds, AppelLot
from app.models.mouvement import Mouvement


def parts_lot(db: Session, lot) -> list[tuple[AppelLot, AppelFonds]]:
    """Parts d'appels du lot, avec leur appel."""
    return (db.query(AppelLot, AppelFonds).join(AppelFonds, AppelLot.appel_id == AppelFonds.id)
            .filter(AppelLot.lot_id == lot.id).all())


def encaissements_lot(db: Session, lot) -> list[Mouvement]:
    return db.query(Mouvement).filter(Mouvement.lot_id == lot.id, Mouvement.type == "encaissement").all()


def totaux_lot(db: Session, lot) -> dict[str, Decimal]:
    """Appels (charges, fonds de travaux), encaissé et solde du lot (solde > 0 : somme due)."""
    parts = parts_lot(db, lot)
    appels_c = arrondi(somme(D(p.montant_charges or 0) for p, _ in parts))
    appels_f = arrondi(somme(D(p.montant_fonds_travaux or 0) for p, _ in parts))
    encaisse = arrondi(somme(D(m.montant or 0) for m in encaissements_lot(db, lot)))
    return {"appels_charges": appels_c, "appels_fonds": appels_f, "encaisse": encaisse,
            "solde": arrondi(appels_c + appels_f - encaisse)}

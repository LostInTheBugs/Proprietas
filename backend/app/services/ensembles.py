"""Lots non séparables : ensembles « lot principal + annexes ».

Un lot annexe (cave, garage…) porte `lot_principal_id`. Un lot sans rattachement forme à lui seul
un ensemble. Un seul niveau : un lot principal n'est jamais lui-même une annexe.
L'ensemble se suit comme une unité (décompte, recouvrement, relances, tableau de bord, quittances) ;
le détail reste visible lot par lot.
"""
from sqlalchemy.orm import Session

from app.models.lot import Lot


def principal(db: Session, lot: Lot) -> Lot:
    if lot.lot_principal_id:
        p = db.get(Lot, lot.lot_principal_id)
        if p is not None and p.copropriete_id == lot.copropriete_id:
            return p
    return lot


def annexes(db: Session, lot: Lot) -> list[Lot]:
    return (db.query(Lot).filter(Lot.lot_principal_id == lot.id, Lot.copropriete_id == lot.copropriete_id)
            .order_by(Lot.id).all())


def membres(db: Session, lot: Lot) -> list[Lot]:
    """Lots de l'ensemble auquel appartient `lot` : le lot principal d'abord, puis ses annexes."""
    p = principal(db, lot)
    return [p] + annexes(db, p)


def ensembles(db: Session, copro_id: int, lots: list[Lot] | None = None) -> list[list[Lot]]:
    """Tous les ensembles de la copropriété (ordre des lots principaux par numéro)."""
    tous = lots if lots is not None else db.query(Lot).filter(Lot.copropriete_id == copro_id).all()
    par_id = {l.id: l for l in tous}
    groupes: dict[int, list[Lot]] = {}
    for l in sorted(tous, key=lambda x: x.id):
        cle = l.lot_principal_id if l.lot_principal_id in par_id else l.id
        groupes.setdefault(cle, []).append(l)
    resultat = []
    for cle, membres_ in groupes.items():
        p = par_id[cle]
        resultat.append([p] + [m for m in membres_ if m.id != p.id])
    return sorted(resultat, key=lambda g: g[0].numero)


def libelle(lots: list[Lot]) -> str:
    """« Lot 1 » ou « Lot 1 (avec lots 12, 25) »."""
    if len(lots) == 1:
        return f"Lot {lots[0].numero}"
    return f"Lot {lots[0].numero} (avec lot{'s' if len(lots) > 2 else ''} " \
           f"{', '.join(l.numero for l in lots[1:])})"

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user, require_syndic
from app.models.user import User, UserCopro
from app.models.lot import Lot
from app.models.appel import AppelFonds, AppelLot
from app.models.mouvement import Mouvement
from app.core.scoping import get_owned
from app.schemas import LotIn, LotOut, LotSolde, OccupationIn
from app.routes.copro import get_or_create_copro

router = APIRouter(prefix="/api", tags=["lots"])


def _utilisateur_de_la_copro(db: Session, copro, user_id: int) -> User | None:
    """Compte de la copropriété active (isolation multi-copro)."""
    return (db.query(User)
            .join(UserCopro, UserCopro.user_id == User.id)
            .filter(User.id == user_id, UserCopro.copropriete_id == copro.id)
            .first())


def _lots_out(db: Session, copro, lots: list[Lot]) -> list[LotOut]:
    """LotOut enrichi : nom du propriétaire (compte) + occupation.

    `proprietaire_occupant` est DÉRIVÉ de `statut_occupation == "occupant"`
    (le propriétaire le déclare lot par lot — Réglages → Mes lots).
    """
    noms = {}
    ids = {lot.proprietaire_id for lot in lots if lot.proprietaire_id}
    if ids:
        for u in db.query(User).filter(User.id.in_(ids)).all():
            noms[u.id] = f"{u.prenom or ''} {u.nom or ''}".strip()
    resultat = []
    for lot in lots:
        item = LotOut.model_validate(lot)
        item.proprietaire_nom = noms.get(lot.proprietaire_id, "")
        item.proprietaire_occupant = lot.statut_occupation == "occupant"
        resultat.append(item)
    return resultat


@router.get("/lots", response_model=list[LotOut])
def list_lots(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    lots = db.query(Lot).filter(Lot.copropriete_id == copro.id).order_by(Lot.numero).all()
    return _lots_out(db, copro, lots)


@router.post("/lots", response_model=LotOut)
def create_lot(data: LotIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    if data.proprietaire_id is not None and not _utilisateur_de_la_copro(db, copro, data.proprietaire_id):
        raise HTTPException(400, "Propriétaire introuvable dans cette copropriété")
    lot = Lot(copropriete_id=copro.id, **data.model_dump())
    db.add(lot)
    db.commit()
    db.refresh(lot)
    return _lots_out(db, copro, [lot])[0]


@router.put("/lots/{lot_id}", response_model=LotOut)
def update_lot(lot_id: int, data: LotIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    lot = get_owned(db, Lot, lot_id, copro, label="Lot")
    if data.proprietaire_id is not None and not _utilisateur_de_la_copro(db, copro, data.proprietaire_id):
        raise HTTPException(400, "Propriétaire introuvable dans cette copropriété")
    for field, value in data.model_dump().items():
        setattr(lot, field, value)
    db.commit()
    db.refresh(lot)
    return _lots_out(db, copro, [lot])[0]


@router.delete("/lots/{lot_id}")
def delete_lot(lot_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    lot = get_owned(db, Lot, lot_id, copro, label="Lot")
    db.delete(lot)
    db.commit()
    return {"ok": True}


@router.put("/lots/{lot_id}/occupation", response_model=LotOut)
def maj_occupation(lot_id: int, data: OccupationIn, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Occupation d'un lot : le syndic, ou LE PROPRIÉTAIRE pour ses propres lots.

    Chaque copropriétaire déclare ainsi « j'occupe ce lot / loué / vacant »
    depuis Réglages → Mes lots (jamais le nom du locataire — RGPD).
    """
    copro = get_or_create_copro(db, user)
    lot = get_owned(db, Lot, lot_id, copro, label="Lot")
    if user.role != "syndic" and lot.proprietaire_id != user.id:
        raise HTTPException(403, "Seul le propriétaire du lot (ou le syndic) peut régler son occupation")
    lot.statut_occupation = data.statut_occupation
    db.commit()
    db.refresh(lot)
    return _lots_out(db, copro, [lot])[0]


# ---------- Soldes par lot (état daté) ----------
@router.get("/lots/soldes", response_model=list[LotSolde])
def lots_soldes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    lots = db.query(Lot).filter(Lot.copropriete_id == copro.id).all()
    result = []
    for lot in lots:
        appels_charges = sum(a.montant_charges for a in db.query(AppelLot).filter(AppelLot.lot_id == lot.id).all())
        appels_fonds = sum(a.montant_fonds_travaux for a in db.query(AppelLot).filter(AppelLot.lot_id == lot.id).all())
        encaisse = sum(
            m.montant for m in db.query(Mouvement).filter(
                Mouvement.lot_id == lot.id, Mouvement.type == "encaissement"
            ).all()
        )
        result.append(LotSolde(
            lot=lot,
            proprietaire=lot.proprietaire,
            total_appels=round(appels_charges, 2),
            total_appels_fonds=round(appels_fonds, 2),
            total_encaisse=round(encaisse, 2),
            solde=round(appels_charges + appels_fonds - encaisse, 2),
        ))
    return result

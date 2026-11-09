from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.money import D
from app.core.database import get_db
from app.core.deps import get_current_user, require_syndic
from app.models.user import User, UserCopro
from app.models.lot import Lot
from app.models.appel import AppelFonds
from app.services.soldes import totaux_lot
from app.services import ensembles
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


def _controler_rattachement(db: Session, copro, lot: Lot | None, data: LotIn) -> None:
    """Annexe d'un lot principal de la copropriété, sans chaîne ; même propriétaire que lui."""
    pid = data.lot_principal_id
    if pid is None:
        return
    if lot is not None and pid == lot.id:
        raise HTTPException(422, "Un lot ne peut pas être rattaché à lui-même.")
    p = db.query(Lot).filter(Lot.id == pid, Lot.copropriete_id == copro.id).first()
    if p is None:
        raise HTTPException(422, "Lot principal introuvable dans cette copropriété.")
    if p.lot_principal_id:
        raise HTTPException(422, f"Le lot {p.numero} est lui-même rattaché à un autre lot : "
                                 "choisissez le lot principal.")
    if lot is not None and ensembles.annexes(db, lot):
        raise HTTPException(422, f"Le lot {lot.numero} a des annexes : il ne peut pas être rattaché à un autre lot.")
    if data.proprietaire_id is not None and data.proprietaire_id != p.proprietaire_id:
        raise HTTPException(422, f"Un lot rattaché a le même propriétaire que son lot principal (lot {p.numero}).")
    data.proprietaire_id = p.proprietaire_id


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
    _controler_rattachement(db, copro, None, data)
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
    if "lot_principal_id" not in data.model_fields_set:
        data.lot_principal_id = lot.lot_principal_id   # champ absent : rattachement inchangé
    _controler_rattachement(db, copro, lot, data)
    for field, value in data.model_dump().items():
        setattr(lot, field, value)
    # Ensemble non séparable : les annexes suivent le propriétaire du lot principal.
    for annexe in ensembles.annexes(db, lot):
        annexe.proprietaire_id = lot.proprietaire_id
    db.commit()
    db.refresh(lot)
    return _lots_out(db, copro, [lot])[0]


@router.delete("/lots/{lot_id}")
def delete_lot(lot_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    lot = get_owned(db, Lot, lot_id, copro, label="Lot")
    for annexe in ensembles.annexes(db, lot):
        annexe.lot_principal_id = None
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
        t = totaux_lot(db, lot)
        result.append(LotSolde(
            lot=lot,
            proprietaire=lot.proprietaire,
            total_appels=t["appels_charges"],
            total_appels_fonds=t["appels_fonds"],
            total_encaisse=t["encaisse"],
            solde=t["solde"],
        ))
    return result

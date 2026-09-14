from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user, require_syndic
from app.models.user import User, UserCopro
from app.models.lot import Lot
from app.models.personne import Personne
from app.models.appel import AppelFonds, AppelLot
from app.models.mouvement import Mouvement
from app.models.invitation import Invitation
from app.models.relance import Relance
from app.models.recouvrement import ActeRecouvrement
from app.core.scoping import get_owned
from app.schemas import LotIn, LotOut, PersonneIn, PersonneOut, PersonneAvecCompte, LotSolde
from app.routes.copro import get_or_create_copro

router = APIRouter(prefix="/api", tags=["lots"])


# ---------- Personnes ----------
@router.get("/personnes", response_model=list[PersonneAvecCompte])
def list_personnes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Fiches « Lots & occupants » de la copro active.

    Enrichies de `a_un_compte` : un compte utilisateur est-il lié à la fiche ?
    (badge dans l'UI, aucun secret exposé).
    """
    copro = get_or_create_copro(db, user)
    personnes = db.query(Personne).filter(Personne.copropriete_id == copro.id).order_by(Personne.nom).all()
    comptes = {u.personne_id for u in db.query(User)
               .join(UserCopro, UserCopro.user_id == User.id)
               .filter(UserCopro.copropriete_id == copro.id,
                       User.personne_id.isnot(None)).all()}
    resultat = []
    for p in personnes:
        item = PersonneAvecCompte.model_validate(p)
        item.a_un_compte = p.id in comptes
        resultat.append(item)
    return resultat


@router.post("/personnes", response_model=PersonneOut)
def create_personne(data: PersonneIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    p = Personne(copropriete_id=copro.id, **data.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.put("/personnes/{personne_id}", response_model=PersonneOut)
def update_personne(personne_id: int, data: PersonneIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    p = get_owned(db, Personne, personne_id, copro, label="Personne")
    for field, value in data.model_dump().items():
        setattr(p, field, value)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/personnes/{personne_id}")
def delete_personne(personne_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    p = get_owned(db, Personne, personne_id, copro, label="Personne")
    # Historique non supprimable : relances et convocations gardent la personne
    # (FK NOT NULL) — refuser proprement plutôt qu'une erreur d'intégrité.
    if (db.query(Relance).filter(Relance.personne_id == p.id).count()
            or db.query(Invitation).filter(Invitation.personne_id == p.id).count()):
        raise HTTPException(400, "Cette personne a des relances ou des convocations "
                                 "enregistrées (historique conservé) — suppression impossible")
    # Liens (nullable) : le compte utilisateur lié et les actes de recouvrement
    # SURVIVENT à la fiche — le lien est délié. Les lots sont détachés par la
    # relation SQLAlchemy (proprietaire_id / occupant_id → NULL).
    db.query(User).filter(User.personne_id == p.id).update(
        {"personne_id": None}, synchronize_session=False)
    db.query(ActeRecouvrement).filter(ActeRecouvrement.personne_id == p.id).update(
        {"personne_id": None}, synchronize_session=False)
    db.delete(p)
    db.commit()
    return {"ok": True}


# ---------- Lots ----------
@router.get("/lots", response_model=list[LotOut])
def list_lots(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    return db.query(Lot).filter(Lot.copropriete_id == copro.id).order_by(Lot.numero).all()


@router.post("/lots", response_model=LotOut)
def create_lot(data: LotIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    lot = Lot(copropriete_id=copro.id, **data.model_dump())
    db.add(lot)
    db.commit()
    db.refresh(lot)
    return lot


@router.put("/lots/{lot_id}", response_model=LotOut)
def update_lot(lot_id: int, data: LotIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    lot = get_owned(db, Lot, lot_id, copro, label="Lot")
    for field, value in data.model_dump().items():
        setattr(lot, field, value)
    db.commit()
    db.refresh(lot)
    return lot


@router.delete("/lots/{lot_id}")
def delete_lot(lot_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    lot = get_owned(db, Lot, lot_id, copro, label="Lot")
    db.delete(lot)
    db.commit()
    return {"ok": True}


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
            occupant=lot.occupant,
            total_appels=round(appels_charges, 2),
            total_appels_fonds=round(appels_fonds, 2),
            total_encaisse=round(encaisse, 2),
            solde=round(appels_charges + appels_fonds - encaisse, 2),
        ))
    return result

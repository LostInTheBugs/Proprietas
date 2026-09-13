from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user, require_syndic
from app.models.user import User, UserCopro
from app.models.copropriete import Copropriete
from app.schemas import CoproOut, CoproUpdate
from app.services.two_factor import politique_defaut

router = APIRouter(prefix="/api/copro", tags=["copro"])


def get_or_create_copro(db: Session, user: User) -> Copropriete:
    """Copropriété active du user :
    1. copro_id porté par le token JWT (après switch) — accès vérifié via la liaison
    2. sinon : copropriété principale (liaison principale, puis première liaison)
    3. sinon : première copro existante, sinon création (premier login)
    """
    token_copro = getattr(user, "_token_data", None) or {}
    cid = token_copro.get("copro_id")
    if cid:
        lien = (db.query(UserCopro)
                .filter(UserCopro.user_id == user.id, UserCopro.copropriete_id == int(cid))
                .first())
        if lien:
            copro = db.query(Copropriete).filter(Copropriete.id == lien.copropriete_id).first()
            if copro:
                return copro
        raise HTTPException(403, "Accès refusé à cette copropriété")
    # Copro principale
    liens = (db.query(UserCopro).filter(UserCopro.user_id == user.id)
             .order_by(UserCopro.principale.desc(), UserCopro.id).all())
    if liens:
        copro = db.query(Copropriete).filter(Copropriete.id == liens[0].copropriete_id).first()
        if copro:
            return copro
    # Aucune liaison : on ne s'attribue JAMAIS une copropriété existante qui n'est
    # pas liée au compte — elle appartient potentiellement à un autre syndic.
    # Premier login (base vide) : création d'une copropriété neuve, liée au compte.
    copro = Copropriete(nom="Ma copropriété", totp_policy=politique_defaut())
    db.add(copro)
    db.commit()
    db.refresh(copro)
    if not user.copropriete_id:
        user.copropriete_id = copro.id
        db.add(UserCopro(user_id=user.id, copropriete_id=copro.id, principale=True))
        db.commit()
    return copro


@router.get("", response_model=CoproOut)
def get_copro(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return get_or_create_copro(db, user)


@router.put("", response_model=CoproOut)
def update_copro(
    data: CoproUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_syndic),
):
    copro = get_or_create_copro(db, user)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(copro, field, value)
    db.commit()
    db.refresh(copro)
    return copro

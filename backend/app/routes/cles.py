"""Clés de répartition (charges spéciales) : lecture pour tous les comptes, gestion par le syndic (services/cles.py)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user, require_syndic
from app.models.cle import CleRepartition
from app.models.user import User
from app.routes.copro import get_or_create_copro
from app.schemas import CleIn, CleOut
from app.services import cles

router = APIRouter(prefix="/api/cles", tags=["cles"])


def _cle(db: Session, copro_id: int, cle_id: int) -> CleRepartition:
    cle = db.query(CleRepartition).filter(CleRepartition.id == cle_id, CleRepartition.copropriete_id == copro_id).first()
    if cle is None:
        raise HTTPException(404, "Clé introuvable")
    return cle


@router.get("", response_model=list[CleOut])
def lister(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return cles.etat(db, get_or_create_copro(db, user).id)


@router.post("", response_model=list[CleOut])
def creer(data: CleIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    cle = cles.creer(db, copro.id, data)
    audit.enregistrer(db, "cle_creee", user=user, copro_id=copro.id, request=request, detail=cle.nom)
    db.commit()
    return cles.etat(db, copro.id)


@router.put("/{cle_id}", response_model=list[CleOut])
def modifier(cle_id: int, data: CleIn, request: Request, db: Session = Depends(get_db),
             user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    cle = cles.modifier(db, copro.id, _cle(db, copro.id, cle_id), data)
    audit.enregistrer(db, "cle_modifiee", user=user, copro_id=copro.id, request=request, detail=cle.nom)
    db.commit()
    return cles.etat(db, copro.id)


@router.delete("/{cle_id}", response_model=list[CleOut])
def supprimer(cle_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    cle = _cle(db, copro.id, cle_id)
    cles.supprimer(db, cle)
    audit.enregistrer(db, "cle_supprimee", user=user, copro_id=copro.id, request=request, detail=cle.nom)
    db.commit()
    return cles.etat(db, copro.id)

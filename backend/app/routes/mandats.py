"""Mandats du syndic bénévole et du conseil syndical (services/mandats.py)."""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user, require_syndic
from app.models.mandat import Mandat
from app.models.user import User
from app.routes.copro import get_or_create_copro
from app.services import mandats

router = APIRouter(prefix="/api/mandats", tags=["mandats"])


class MandatIn(BaseModel):
    role: str                              # syndic | conseil
    debut: Optional[date] = None           # ou l'AG qui l'a voté (sa date est reprise)
    ag_id: Optional[int] = None
    mois: int
    personne_ids: List[int] = []
    noms: List[str] = []                   # personnes sans compte (mandat passé)


@router.get("")
def situation(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Mandats en cours, historique et alertes ; `personnes` : comptes de la copropriété, à désigner."""
    copro = get_or_create_copro(db, user)
    out = mandats.situation(db, copro.id)
    out["personnes"] = mandats.personnes(db, copro.id)
    return out


@router.post("")
def creer(data: MandatIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    m = mandats.creer(db, copro.id, data.role, data.debut, data.mois, data.personne_ids, data.noms, data.ag_id)
    audit.enregistrer(db, "mandat_saisi", user=user, copro_id=copro.id, request=request,
                      detail=f"{mandats.ROLES[m.role]} du {m.debut:%d/%m/%Y} au {m.fin:%d/%m/%Y}")
    db.commit()
    return {"id": m.id}


@router.delete("/{mandat_id}")
def supprimer(mandat_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    m = db.query(Mandat).filter(Mandat.id == mandat_id, Mandat.copropriete_id == copro.id).first()
    if m is None:
        raise HTTPException(404, "Mandat introuvable")
    if m.resolution_id is not None:
        raise HTTPException(409, "Ce mandat a été voté en AG : il suit la résolution (modifiez-la ou supprimez-la).")
    audit.enregistrer(db, "mandat_supprime", user=user, copro_id=copro.id, request=request,
                      detail=f"{mandats.ROLES[m.role]} du {m.debut:%d/%m/%Y} au {m.fin:%d/%m/%Y}")
    db.delete(m)
    db.commit()
    return {"ok": True}

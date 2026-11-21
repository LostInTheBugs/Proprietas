"""Vote en direct pendant l'AG (services/vote_en_ligne.py)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user, require_syndic
from app.core.scoping import get_owned, get_owned_via
from app.models.ag import AG, Resolution
from app.models.user import User
from app.routes.ag import _resolution_out, calculer_resultat
from app.routes.copro import get_or_create_copro
from app.schemas import ResolutionOut
from app.services import vote_en_ligne

router = APIRouter(prefix="/api", tags=["vote-en-ligne"])


class MonVoteIn(BaseModel):
    voix: str                              # pour | contre | abstention
    lot_ids: Optional[List[int]] = None    # vide : tous ses lots (et ceux de ses mandants)


@router.get("/ag/{ag_id}/vote-en-ligne")
def etat(ag_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ag = get_owned(db, AG, ag_id, get_or_create_copro(db, user), label="AG")
    return vote_en_ligne.etat(db, ag, user)


@router.post("/resolutions/{res_id}/vote-en-ligne/ouvrir", response_model=ResolutionOut)
def ouvrir(res_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    r = get_owned_via(db, Resolution, AG, res_id, copro, "ag_id", label="Résolution")
    vote_en_ligne.ouvrir(db, r)
    audit.enregistrer(db, "vote_en_ligne_ouvert", user=user, copro_id=copro.id, request=request,
                      detail=f"AG du {r.ag.date:%d/%m/%Y}, résolution n° {r.numero} « {r.libelle} »")
    db.commit()
    db.refresh(r)
    return _resolution_out(db, r)


@router.post("/resolutions/{res_id}/vote-en-ligne/clore", response_model=ResolutionOut)
def clore(res_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Clôt le vote et calcule le résultat (majorité de la résolution)."""
    copro = get_or_create_copro(db, user)
    r = get_owned_via(db, Resolution, AG, res_id, copro, "ag_id", label="Résolution")
    vote_en_ligne.clore(r)
    calculer_resultat(db, copro, r)
    audit.enregistrer(db, "vote_en_ligne_clos", user=user, copro_id=copro.id, request=request,
                      detail=f"AG du {r.ag.date:%d/%m/%Y}, résolution n° {r.numero} « {r.libelle} » : {r.statut}")
    db.commit()
    db.refresh(r)
    return _resolution_out(db, r)


@router.put("/resolutions/{res_id}/mon-vote")
def mon_vote(res_id: int, data: MonVoteIn, request: Request, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    r = get_owned_via(db, Resolution, AG, res_id, copro, "ag_id", label="Résolution")
    n = vote_en_ligne.voter(db, r.ag, r, user, data.voix, data.lot_ids)
    audit.enregistrer(db, "vote_en_ligne", user=user, copro_id=copro.id, request=request,
                      detail=f"AG du {r.ag.date:%d/%m/%Y}, résolution n° {r.numero} : {data.voix} ({n} lot(s))")
    db.commit()
    return vote_en_ligne.etat(db, r.ag, user)

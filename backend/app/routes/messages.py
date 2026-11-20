"""Messages groupés du syndic aux copropriétaires (services/messages.py)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_syndic
from app.models.user import User
from app.routes.copro import get_or_create_copro
from app.services import messages

router = APIRouter(prefix="/api/messages", tags=["messages"])


class MessageIn(BaseModel):
    sujet: str
    corps: str
    cible: str = "tous"                 # tous | cle | selection
    cle_id: Optional[int] = None
    ids: List[int] = []


@router.get("")
def historique(db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    return messages.historique(db, get_or_create_copro(db, user))


@router.post("/apercu")
def apercu(data: MessageIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    return messages.apercu(db, get_or_create_copro(db, user), data)


@router.post("")
def envoyer(data: MessageIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    m = messages.envoyer(db, copro, data, user, request)
    db.commit()
    return {"id": m.id, "nb_envoyes": m.nb_envoyes, "erreurs": [x for x in m.erreurs.split("\n") if x]}

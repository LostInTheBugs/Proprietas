"""Vente d'un lot (mutation) : réservée au syndic (services/mutations.py)."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_syndic
from app.models.user import User
from app.routes.copro import get_or_create_copro
from app.schemas import Montant
from app.services import mutations

router = APIRouter(prefix="/api/mutations", tags=["mutations"])


class SuiviIn(BaseModel):
    notaire: str = ""
    notifiee_le: Optional[date] = None        # notification du transfert (décret 1967, art. 6)
    avis_mutation_le: Optional[date] = None   # avis de mutation reçu (loi 1965, art. 20)
    opposition_le: Optional[date] = None
    notes: str = ""


class VenteIn(SuiviIn):
    lot_id: int
    date_acte: date
    acquereur_id: int


class EncaissementVendeurIn(BaseModel):
    date: date
    montant: Montant
    libelle: str = ""


@router.get("")
def lister(db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    return mutations.liste(db, get_or_create_copro(db, user))


@router.post("")
def creer(data: VenteIn, request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    m = mutations.creer(db, copro, data, user, request)
    db.commit()
    return mutations.vue(db, copro, m)


@router.put("/{mutation_id}")
def modifier(mutation_id: int, data: SuiviIn, request: Request, db: Session = Depends(get_db),
             user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    m = mutations.modifier(db, mutations.get(db, copro, mutation_id), data, user, request)
    db.commit()
    return mutations.vue(db, copro, m)


@router.delete("/{mutation_id}")
def annuler(mutation_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    mutations.annuler(db, mutations.get(db, copro, mutation_id), user, request)
    db.commit()
    return {"ok": True}


@router.post("/{mutation_id}/encaissement")
def encaisser(mutation_id: int, data: EncaissementVendeurIn, request: Request, db: Session = Depends(get_db),
              user: User = Depends(require_syndic)):
    """Solde du vendeur reçu après la vente (en général du notaire) : porté à son compte."""
    copro = get_or_create_copro(db, user)
    m = mutations.get(db, copro, mutation_id)
    mutations.encaisser_vendeur(db, copro, m, data.date, data.montant, data.libelle, user, request)
    db.commit()
    return mutations.vue(db, copro, m)

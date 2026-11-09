"""Paiement d'un copropriétaire pour l'ensemble de ses lots : répartition proposée, puis
enregistrement d'un encaissement par lot. Réservé au syndic, audité. Règles : services/paiements.py."""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core import audit
from app.core.database import get_db
from app.core.deps import require_syndic
from app.core.money import LIMITE_MONTANT, decimal_saisi
from app.models.user import User
from app.routes.copro import get_or_create_copro
from app.schemas import MouvementOut, PaiementIn, RepartitionOut
from app.services import paiements as svc

router = APIRouter(prefix="/api/paiements", tags=["paiements"])


@router.get("/repartition", response_model=RepartitionOut)
def repartition(proprietaire_id: int, montant: str, db: Session = Depends(get_db),
                user: User = Depends(require_syndic)):
    try:
        m = decimal_saisi(montant.replace(",", "."), Decimal("0.01"), LIMITE_MONTANT)
    except ValueError:
        raise HTTPException(422, "Montant invalide.") from None
    return svc.repartition(db, get_or_create_copro(db, user), proprietaire_id, m)


@router.post("", response_model=list[MouvementOut])
def enregistrer(data: PaiementIn, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    crees = svc.enregistrer(db, copro, data.proprietaire_id, data.date, data.montant, data.libelle,
                            data.repartition)
    detail = ", ".join(f"{m.libelle.rsplit('—', 1)[-1].strip()} {m.montant:.2f} €" for m in crees)
    audit.enregistrer(db, "paiement_enregistre", user=user, copro_id=copro.id, request=request,
                      detail=f"{data.date:%d/%m/%Y} « {data.libelle} » {data.montant:.2f} € : {detail}")
    db.commit()
    for m in crees:
        db.refresh(m)
    return crees

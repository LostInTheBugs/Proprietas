"""Vente d'un lot (mutation) : réservée au syndic (services/mutations.py)."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
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


def _pdf(contenu, nom: str) -> Response:
    from app.routes.documents import _content_disposition
    return Response(contenu.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": _content_disposition(nom)})


def _jour(jour: Optional[date]) -> date:
    j = jour or date.today()
    if j > date.today():
        raise HTTPException(422, "La situation ne peut pas être arrêtée à une date future.")
    return j


@router.get("/documents/pre-etat-date.pdf")
def pre_etat_date(lot_id: int, request: Request, jour: Optional[date] = None, db: Session = Depends(get_db),
                  user: User = Depends(require_syndic)):
    """Informations financières à annexer à la promesse de vente (CCH, art. L721-2)."""
    from app.core import audit
    from app.services import etat_date
    copro = get_or_create_copro(db, user)
    lot, j = mutations._lot(db, copro, lot_id), _jour(jour)
    pdf = etat_date.pre_etat_date_pdf(db, copro, lot, j)
    audit.enregistrer(db, "pre_etat_date", user=user, copro_id=copro.id, request=request,
                      detail=f"lot {lot.numero} au {j:%d/%m/%Y}")
    db.commit()
    return _pdf(pdf, f"Pre-etat-date_lot_{lot.numero}_{j:%Y-%m-%d}.pdf")


@router.get("/documents/etat-date.pdf")
def etat_date(lot_id: int, request: Request, jour: Optional[date] = None, procedures: str = "",
              db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """État daté demandé par le notaire avant la vente (décret 1967, art. 5)."""
    from app.core import audit
    from app.services import etat_date as svc
    copro = get_or_create_copro(db, user)
    lot, j = mutations._lot(db, copro, lot_id), _jour(jour)
    pdf = svc.etat_date_pdf(db, copro, lot, j, procedures[:2000])
    audit.enregistrer(db, "etat_date", user=user, copro_id=copro.id, request=request,
                      detail=f"lot {lot.numero} au {j:%d/%m/%Y}")
    db.commit()
    return _pdf(pdf, f"Etat-date_lot_{lot.numero}_{j:%Y-%m-%d}.pdf")


@router.get("/{mutation_id}/opposition.pdf")
def opposition(mutation_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Projet d'opposition (loi 1965, art. 20) : montant et causes des sommes dues par le vendeur."""
    from app.core import audit
    from app.services import etat_date
    copro = get_or_create_copro(db, user)
    m = mutations.get(db, copro, mutation_id)
    pdf, resume = etat_date.opposition_pdf(db, copro, m)
    audit.enregistrer(db, "projet_opposition", user=user, copro_id=copro.id, request=request,
                      detail=f"vente du {m.date_acte:%d/%m/%Y} ({m.vendeur_nom}) : {resume['total']:.2f} €")
    db.commit()
    return _pdf(pdf, f"Projet-opposition_{m.date_acte:%Y-%m-%d}.pdf")

"""Connexions des comptes : dernière connexion, historique, déblocage (services/connexions.py).

- `GET  /api/auth/me/connexions` : chacun voit ses propres connexions ;
- `GET  /api/auth/users/{id}/connexions` et `POST /api/auth/users/{id}/debloquer` : syndic, pour
  les comptes de la copropriété active ; administrateur de l'instance, pour tous les comptes ;
- `GET  /api/admin/comptes-bloques` : administrateur de l'instance, comptes bloqués de toutes
  les copropriétés (un syndic bloqué ne peut pas se débloquer lui-même).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, is_instance_admin, require_instance_admin
from app.models.copropriete import Copropriete
from app.models.user import User, UserCopro
from app.routes.copro import get_or_create_copro
from app.schemas import CompteBloqueOut, ConnexionsOut, UserOut
from app.services import connexions

router = APIRouter(prefix="/api", tags=["connexions"])


def _compte_gere(db: Session, user_id: int, current: User) -> User:
    """Le compte, si `current` peut le gérer : administrateur de l'instance, ou syndic de la
    copropriété active à laquelle le compte est rattaché. Sinon 404 (ni 403 : on ne dit pas
    qu'un compte existe ailleurs)."""
    if is_instance_admin(current):
        cible = db.get(User, user_id)
    elif current.role == "syndic":
        copro = get_or_create_copro(db, current)
        cible = (db.query(User).join(UserCopro, UserCopro.user_id == User.id)
                 .filter(User.id == user_id, UserCopro.copropriete_id == copro.id).first())
    else:
        raise HTTPException(403, "Réservé au syndic")
    if not cible:
        raise HTTPException(404, "Utilisateur introuvable")
    return cible


@router.get("/auth/me/connexions", response_model=ConnexionsOut)
def mes_connexions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return connexions.resume(db, user)


@router.get("/auth/users/{user_id}/connexions", response_model=ConnexionsOut)
def connexions_compte(user_id: int, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    return connexions.resume(db, _compte_gere(db, user_id, current))


@router.post("/auth/users/{user_id}/debloquer", response_model=UserOut)
def debloquer_compte(user_id: int, request: Request, db: Session = Depends(get_db),
                     current: User = Depends(get_current_user)):
    cible = _compte_gere(db, user_id, current)
    connexions.debloquer(db, cible, current, request)
    db.refresh(cible)
    return cible


@router.get("/admin/comptes-bloques", response_model=list[CompteBloqueOut])
def comptes_bloques(db: Session = Depends(get_db), user: User = Depends(require_instance_admin)):
    from datetime import datetime
    rows = (db.query(User)
            .filter(or_(User.bloque_definitif_le.isnot(None), User.bloque_jusqua > datetime.now()))
            .order_by(User.email).all())
    resultat = []
    for u in rows:
        noms = [c.nom for c in (db.query(Copropriete).join(UserCopro, UserCopro.copropriete_id == Copropriete.id)
                                .filter(UserCopro.user_id == u.id).order_by(Copropriete.nom).all())]
        resultat.append(CompteBloqueOut(id=u.id, email=u.email, nom=u.nom or "", prenom=u.prenom or "",
                                        bloque=u.bloque, bloque_jusqua=u.bloque_jusqua,
                                        bloque_definitif_le=u.bloque_definitif_le, coproprietes=noms))
    return resultat

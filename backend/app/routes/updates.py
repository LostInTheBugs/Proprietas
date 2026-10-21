"""Version et mises à jour de l'instance.

- `GET /api/version` : public (affichée dans le pied de page, et utile pour superviser).
- `/api/admin/updates*` : réservé aux administrateurs de l'instance.
- `/api/admin/instance-admins*` : liste, ajout et retrait de ces administrateurs.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user, is_instance_admin, require_instance_admin
from app.core.version import VERSION
from app.models.user import User
from app.services import updates

router = APIRouter(prefix="/api", tags=["updates"])


class UpdateSettingsIn(BaseModel):
    check_interval_s: int | None = None
    auto_apply: bool | None = None


@router.get("/version")
def version():
    return {"version": VERSION}


@router.get("/updates/me")
def mon_acces(user: User = Depends(get_current_user)):
    """Le frontend sait s'il doit afficher le panneau (et le bandeau) des mises à jour."""
    return {"instance_admin": is_instance_admin(user)}


@router.get("/admin/updates")
def etat(user: User = Depends(require_instance_admin)):
    return updates.state()


@router.put("/admin/updates/settings")
def reglages(data: UpdateSettingsIn, user: User = Depends(require_instance_admin)):
    try:
        updates.write_settings(data.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return updates.state()


@router.post("/admin/updates/check")
def verifier(user: User = Depends(require_instance_admin)):
    return updates.run_check()


@router.post("/admin/updates/apply")
def appliquer(user: User = Depends(require_instance_admin)):
    st = updates.state()
    if st["mode"] != "server":
        raise HTTPException(400, "Version de bureau : téléchargez la nouvelle version depuis la page de la release")
    if not st["available"]:
        raise HTTPException(400, f"Déjà à jour ({VERSION})")
    if st["request"]:
        raise HTTPException(409, f"Une mise à jour vers {st['request']['version']} est déjà demandée")
    updates.write_request(st["latest"]["version"], user.email)
    return updates.state()


@router.delete("/admin/updates/request")
def annuler(user: User = Depends(require_instance_admin)):
    updates.cancel_request()
    return updates.state()


# ---------------------------------------------------------------- administrateurs de l'instance
class InstanceAdminIn(BaseModel):
    email: str = Field(..., max_length=254)


def _admins(db: Session) -> list[dict]:
    rows = (db.query(User).filter(User.is_instance_admin.is_(True), User.is_demo.isnot(True))
            .order_by(User.id).all())
    return [{"id": u.id, "email": u.email, "prenom": u.prenom or "", "nom": u.nom or ""} for u in rows]


@router.get("/admin/instance-admins")
def lister_admins(db: Session = Depends(get_db), user: User = Depends(require_instance_admin)):
    return _admins(db)


@router.post("/admin/instance-admins")
def ajouter_admin(data: InstanceAdminIn, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require_instance_admin)):
    """Donne les droits d'administration de l'instance à un compte EXISTANT (par son e-mail)."""
    email = data.email.strip().lower()
    cible = db.query(User).filter(func.lower(User.email) == email).first()
    if not cible:
        raise HTTPException(404, "Aucun compte avec cet e-mail : créez d'abord le compte")
    if cible.is_demo:
        raise HTTPException(400, "Le compte de démonstration ne peut pas administrer l'instance")
    if not cible.is_instance_admin:
        cible.is_instance_admin = True
        audit.enregistrer(db, "instance_admin_added", user=user, detail=cible.email, request=request)
        db.commit()
    return _admins(db)


@router.delete("/admin/instance-admins/{user_id}")
def retirer_admin(user_id: int, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require_instance_admin)):
    """Retire les droits. On ne peut pas se les retirer soi-même : il reste donc
    toujours au moins un administrateur (celui qui fait le retrait)."""
    if user_id == user.id:
        raise HTTPException(400, "Vous ne pouvez pas vous retirer vous-même : demandez à un autre administrateur")
    cible = db.get(User, user_id)
    if not cible or not cible.is_instance_admin:
        raise HTTPException(404, "Cet administrateur n'existe pas")
    cible.is_instance_admin = False
    audit.enregistrer(db, "instance_admin_removed", user=user, detail=cible.email, request=request)
    db.commit()
    return _admins(db)

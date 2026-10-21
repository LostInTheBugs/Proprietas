"""Version et mises à jour de l'instance.

- `GET /api/version` : public (affichée dans le pied de page, et utile pour superviser).
- `/api/admin/updates*` : réservé aux administrateurs de l'instance (COPRO_INSTANCE_ADMINS).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

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

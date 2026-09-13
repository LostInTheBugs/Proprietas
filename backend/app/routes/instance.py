"""Profil d'exposition de l'instance : mode de déploiement, URL publique, diagnostic.

Le mode est déclaré par le syndic (« local » | « vps » | « maison ») ; la première
requête vue depuis internet est détectée automatiquement (middleware) pour que
l'exposition ne soit jamais silencieuse. Le diagnostic vérifie l'état RÉEL
(HTTPS, certificat, DNS, en-têtes, rate-limit, couverture 2FA).
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core import audit
from app.core.database import get_db
from app.core.deps import require_syndic
from app.core.httpinfo import requete_https
from app.models.instance import InstanceState
from app.models.user import User
from app.routes.copro import get_or_create_copro
from app.schemas import DiagnosticItem, DiagnosticOut, InstanceOut, InstanceUpdate
from app.services import diagnostic

router = APIRouter(prefix="/api/instance", tags=["instance"])


def get_instance(db: Session) -> InstanceState:
    """Ligne unique d'état de l'instance (créée à la demande)."""
    inst = db.get(InstanceState, 1)
    if not inst:
        inst = InstanceState(id=1)
        db.add(inst)
        db.commit()
        db.refresh(inst)
    return inst


def _items(inst: InstanceState) -> list[DiagnosticItem]:
    try:
        return [DiagnosticItem(**i) for i in json.loads(inst.last_check_json or "[]")]
    except (ValueError, TypeError):
        return []


def _out(inst: InstanceState, request: Request) -> InstanceOut:
    mode = inst.mode or "local"
    return InstanceOut(
        mode=mode,
        public_url=inst.public_url or "",
        first_external_at=inst.first_external_at,
        last_check_at=inst.last_check_at,
        last_check=_items(inst),
        exposed_unprotected=bool(inst.first_external_at) and mode == "local",
        https_active=requete_https(request),
        version=request.app.version,
    )


@router.get("", response_model=InstanceOut)
def statut_instance(request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_syndic)):
    """État d'exposition de l'instance (réservé au syndic)."""
    return _out(get_instance(db), request)


@router.put("", response_model=InstanceOut)
def maj_instance(data: InstanceUpdate, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_syndic)):
    """Déclare où vit l'application et son adresse publique."""
    inst = get_instance(db)
    inst.mode = data.mode
    inst.public_url = (data.public_url or "").strip().rstrip("/")
    audit.enregistrer(db, "instance_updated", user=user,
                      detail=f"mode={inst.mode} url={inst.public_url or '—'}", request=request)
    db.commit()
    db.refresh(inst)
    return _out(inst, request)


@router.post("/diagnostic", response_model=DiagnosticOut)
def lancer_diagnostic(request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require_syndic)):
    """Vérifie que l'exposition est réelle et protégée (état mesuré, pas déclaré)."""
    copro = get_or_create_copro(db, user)
    inst = get_instance(db)
    resultats = diagnostic.lancer_diagnostic(db, copro, inst)
    inst.last_check_at = datetime.now()
    inst.last_check_json = json.dumps(resultats)
    ok = sum(1 for r in resultats if r["statut"] == "ok")
    audit.enregistrer(db, "diagnostic_run", user=user, copro_id=copro.id,
                      detail=f"{ok} ok / {len(resultats)} vérifications", request=request)
    db.commit()
    return DiagnosticOut(checked_at=inst.last_check_at, results=resultats)

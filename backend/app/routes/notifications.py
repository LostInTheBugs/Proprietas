"""Notification du procès-verbal aux opposants et défaillants (syndic seulement)."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core import audit
from app.core.database import get_db
from app.core.deps import require_syndic
from app.core.scoping import get_owned, get_owned_via
from app.models.ag import AG
from app.models.notification import NotificationPV
from app.models.user import User
from app.routes.copro import get_or_create_copro
from app.schemas import NotificationPVIn, NotificationsPVOut
from app.services import notifications_pv as svc
from app.services import voie_postale

router = APIRouter(prefix="/api", tags=["notifications"])


@router.get("/ag/{ag_id}/notifications-pv", response_model=NotificationsPVOut)
def lister(ag_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    ag = get_owned(db, AG, ag_id, get_or_create_copro(db, user), label="AG")
    return svc.etat(db, ag)


@router.post("/ag/{ag_id}/notifications-pv", response_model=NotificationsPVOut)
def preparer(ag_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Établit (ou met à jour) la liste des copropriétaires à qui notifier le PV."""
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    svc.preparer(db, ag)
    audit.enregistrer(db, "notification_pv_preparee", user=user, copro_id=copro.id,
                      detail=f"AG du {ag.date:%d/%m/%Y}", request=request)
    db.commit()
    return svc.etat(db, ag)


@router.put("/notifications-pv/{notif_id}", response_model=NotificationsPVOut)
def saisir(notif_id: int, data: NotificationPVIn, request: Request,
           db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Saisit l'envoi (date, référence LRE/LRAR) et la date de première présentation."""
    copro = get_or_create_copro(db, user)
    n = get_owned_via(db, NotificationPV, AG, notif_id, copro, "ag_id", label="Notification")
    if data.mode not in ("lre", "lrar"):
        raise HTTPException(422, "Mode de notification : lre (lettre recommandée électronique) ou lrar")
    for d, quoi in ((data.date_envoi, "d'envoi"), (data.date_presentation, "de présentation")):
        if d is not None and d > date.today():
            raise HTTPException(422, f"La date {quoi} ne peut pas être dans le futur.")
    if data.date_presentation is not None:
        if data.date_envoi is None:
            raise HTTPException(422, "Saisissez d'abord la date d'envoi.")
        if data.date_presentation < data.date_envoi:
            raise HTTPException(422, "La présentation ne peut pas précéder l'envoi.")
    if n.date_envoi is not None and data.mode != n.mode:
        raise HTTPException(422, "Notification envoyée : son mode ne peut pas être changé. "
                                 "Effacez d'abord la date d'envoi si elle a été saisie par erreur.")
    if n.date_envoi is None:
        # Décret n° 67-223, art. 64, 64-1 et 64-4 : LRE par défaut, LRAR sur demande en vigueur.
        destinataire = db.get(User, n.user_id) if n.user_id else None
        voie_postale.controler_mode(destinataire, data.mode, data.date_envoi or date.today(), n.nom)
    n.mode, n.date_envoi, n.date_presentation = data.mode, data.date_envoi, data.date_presentation
    n.reference = (data.reference or "").strip()[:120]
    audit.enregistrer(db, "notification_pv_saisie", user=user, copro_id=copro.id,
                      detail=f"{n.nom} — {n.mode}, envoi {n.date_envoi}, présentation {n.date_presentation}",
                      request=request)
    db.commit()
    return svc.etat(db, db.get(AG, n.ag_id))

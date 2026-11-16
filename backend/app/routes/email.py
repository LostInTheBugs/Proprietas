from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import require_syndic
from app.models.user import User
from app.models.copropriete import Copropriete
from app.routes.copro import get_or_create_copro
from app.core.config import get_settings
from app.services.emailer import config_smtp, envoyer_email, EmailError
from app.schemas import SmtpConfigIn, SmtpTestResult

router = APIRouter(prefix="/api/smtp", tags=["smtp"])


@router.put("/config")
def update_smtp(
    data: SmtpConfigIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_syndic),
):
    """Met à jour la configuration SMTP (Réglages → Envoi des emails)."""
    copro = get_or_create_copro(db, user)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(copro, field, value)
    db.commit()
    return {"ok": True}


@router.post("/test", response_model=SmtpTestResult)
def test_smtp(
    data: SmtpConfigIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_syndic),
):
    """Envoie un email de test au syndic avec la configuration fournie."""
    copro = get_or_create_copro(db, user)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(copro, field, value)
    cfg = config_smtp(copro)
    destinataire = cfg.email_expediteur if cfg else copro.email_expediteur
    if not destinataire:
        raise HTTPException(400, "Renseignez l'adresse expéditeur")
    try:
        envoyer_email(
            copro,
            destinataire,
            "Test Proprietas",
            "Cet email confirme que la configuration SMTP de Proprietas fonctionne.",
        )
        db.commit()
        detail = "Email de test envoyé avec succès"
        if cfg.source == "instance":
            detail += " (serveur de l'instance)"
        return SmtpTestResult(ok=True, detail=detail)
    except EmailError as e:
        return SmtpTestResult(ok=False, detail=str(e))


@router.get("/instance")
def smtp_instance(db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Serveur d'envoi de l'instance (COPRO_SMTP_*) : est-il réglé, et sert-il à cette copropriété ?
    Le mot de passe et l'identifiant ne sortent jamais."""
    copro = get_or_create_copro(db, user)
    s = get_settings()
    configure = bool(s.smtp_host and s.email_expediteur)
    return {"configure": configure, "utilise": configure and not copro.smtp_host,
            "serveur": s.smtp_host if configure else "", "port": s.smtp_port,
            "expediteur": s.email_expediteur if configure else "", "adresse_publique": s.frontend_url}

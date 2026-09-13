"""Sécurité du compte : double authentification (TOTP) et journal d'audit.

Les routes 2FA vivent sous /api/auth (continuité du login, y compris le flux
d'enrôlement forcé pendant la connexion) ; le journal sous /api/audit, réservé
au syndic pour la copropriété active.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core import audit, crypto
from app.core.database import get_db
from app.core.deps import get_current_user, get_current_user_2fa, require_syndic
from app.core.rate_limit import check_login_allowed, clear_failures, record_failure
from app.core.security import (
    create_access_token,
    create_scoped_token,
    decode_access_token,
    verify_password,
)
from app.models.audit import AuditLog
from app.models.user import User, UserCopro
from app.routes.copro import get_or_create_copro
from app.schemas import (
    AuditOut,
    LoginResponse,
    TwoFactorDisableIn,
    TwoFactorRecoveryIn,
    TwoFactorRecoveryOut,
    TwoFactorSetupOut,
    TwoFactorStatusOut,
    TwoFactorVerifyIn,
    TwoFactorVerifyLoginIn,
    TwoFactorVerifyOut,
)
from app.services import alertes, two_factor

router = APIRouter(prefix="/api/auth", tags=["securite"])
router_audit = APIRouter(prefix="/api/audit", tags=["securite"])

CHALLENGE_MINUTES = 10  # validité du jeton de vérification (2e étape du login)
SETUP_MINUTES = 30      # validité du jeton d'enrôlement forcé


# ---------- État ----------

@router.get("/2fa/status", response_model=TwoFactorStatusOut)
def statut_2fa(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    return TwoFactorStatusOut(
        enabled=bool(user.totp_enabled),
        recovery_codes_left=two_factor.nb_codes_restants(user),
        policy=copro.totp_policy or "off",
        required=two_factor.politique_requise(db, user),
    )


# ---------- Enrôlement ----------

@router.post("/logout-all")
def deconnecter_partout(request: Request, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """« Déconnecter tous mes appareils » : invalide TOUTES les sessions du compte
    (y compris la session courante) en incrémentant la version des jetons."""
    user.token_version = int(user.token_version or 0) + 1
    audit.enregistrer(db, "sessions_revoked", user=user,
                      copro_id=two_factor.copro_principale_id(db, user), request=request)
    db.commit()
    return {"ok": True, "message": "Toutes vos sessions ont été déconnectées."}


@router.post("/2fa/setup", response_model=TwoFactorSetupOut)
def configurer_2fa(db: Session = Depends(get_db), user: User = Depends(get_current_user_2fa)):
    """Génère un secret TOTP en attente + le QR code à scanner (rien n'est actif
    tant que le premier code n'a pas été validé par /2fa/verify)."""
    if user.is_demo:
        raise HTTPException(400, "Compte de démonstration : la double authentification est désactivée.")
    if user.totp_enabled:
        raise HTTPException(400, "La double authentification est déjà activée.")
    secret = two_factor.generer_secret()
    user.totp_secret = crypto.chiffrer_secret(secret)
    db.commit()
    uri = two_factor.otpauth_uri(secret, user.email)
    return TwoFactorSetupOut(
        secret=secret,
        otpauth_uri=uri,
        qr_svg=two_factor.qr_svg_data_uri(uri),
    )


@router.post("/2fa/verify", response_model=TwoFactorVerifyOut)
def verifier_enrolement(req: TwoFactorVerifyIn, request: Request,
                        db: Session = Depends(get_db),
                        user: User = Depends(get_current_user_2fa)):
    """Valide le premier code → active la 2FA et renvoie les codes de secours
    (affichés UNE seule fois). En flux d'enrôlement forcé, délivre aussi le jeton
    d'accès complet pour enchaîner sur l'application."""
    secret = crypto.dechiffrer_secret(user.totp_secret or "")
    if not secret:
        raise HTTPException(400, "Aucun enrôlement en cours — commencez par le scan du QR code.")
    if not two_factor.verifier_code_totp(secret, req.code):
        raise HTTPException(400, "Code invalide. Vérifiez l'heure de votre téléphone et réessayez.")
    user.totp_enabled = True
    codes = two_factor.generer_codes_secours()
    user.recovery_hashes = two_factor.hachages_codes(codes)
    audit.enregistrer(db, "2fa_enabled", user=user,
                      copro_id=two_factor.copro_principale_id(db, user), request=request)
    db.commit()
    out = TwoFactorVerifyOut(recovery_codes=codes)
    if getattr(user, "_token_scope", "") == "2fa_setup":
        out.access_token = create_access_token(user.id, two_factor.copro_principale_id(db, user),
                                               ver=user.token_version or 0)
    return out


# ---------- Connexion (2e étape) ----------

@router.post("/2fa/verify-login", response_model=LoginResponse)
def verifier_connexion(req: TwoFactorVerifyLoginIn, request: Request,
                       db: Session = Depends(get_db)):
    """2e étape du login : code TOTP ou code de secours → jeton d'accès complet."""
    ip = audit.client_ip(request)
    payload = decode_access_token(req.challenge_token or "")
    if not payload or payload.get("scope") != "2fa_challenge":
        raise HTTPException(401, "Session de connexion expirée — reconnectez-vous.")
    try:
        user = db.query(User).filter(User.id == int(payload.get("sub", ""))).first()
    except (TypeError, ValueError):
        user = None
    if not user or not user.totp_enabled:
        raise HTTPException(401, "Session de connexion invalide — reconnectez-vous.")

    # Mêmes compteurs que l'étape mot de passe (email + IP) : pas de contournement.
    check_login_allowed(user.email, ip)
    mode = two_factor.valider_code(user, req.code)
    if not mode:
        record_failure(user.email, ip)
        audit.enregistrer(db, "login_failed", user=user,
                          copro_id=two_factor.copro_principale_id(db, user),
                          detail="code 2FA invalide", request=request)
        db.commit()
        raise HTTPException(401, "Code invalide.")
    clear_failures(user.email, ip)
    if mode == "secours":
        audit.enregistrer(db, "2fa_recovery_used", user=user,
                          copro_id=two_factor.copro_principale_id(db, user), request=request)
        alertes.alerte_evenement(
            db, user, "Un code de secours vient d'être utilisé pour vous connecter.")
    two_factor.finaliser_connexion(db, user, request)  # journal + dernière connexion + alerte
    return LoginResponse(access_token=create_access_token(
        user.id, two_factor.copro_principale_id(db, user), ver=user.token_version or 0))


# ---------- Gestion ----------

@router.post("/2fa/disable")
def desactiver_2fa(req: TwoFactorDisableIn, request: Request,
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Désactive la 2FA — mot de passe ET code TOTP requis."""
    if not user.totp_enabled:
        raise HTTPException(400, "La double authentification n'est pas activée.")
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(400, "Mot de passe incorrect.")
    secret = crypto.dechiffrer_secret(user.totp_secret or "")
    if not (secret and two_factor.verifier_code_totp(secret, req.code)):
        raise HTTPException(400, "Code invalide.")
    user.totp_enabled = False
    user.totp_secret = ""
    user.recovery_hashes = "[]"
    audit.enregistrer(db, "2fa_disabled", user=user,
                      copro_id=two_factor.copro_principale_id(db, user), request=request)
    db.commit()
    alertes.alerte_evenement(
        db, user, "La double authentification vient d'être DÉSACTIVÉE sur votre compte.")
    return {"ok": True}


@router.post("/2fa/recovery-codes", response_model=TwoFactorRecoveryOut)
def regenerer_codes(req: TwoFactorRecoveryIn, request: Request,
                    db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Régénère les codes de secours (invalide les anciens) — mot de passe + code TOTP."""
    if not user.totp_enabled:
        raise HTTPException(400, "La double authentification n'est pas activée.")
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(400, "Mot de passe incorrect.")
    secret = crypto.dechiffrer_secret(user.totp_secret or "")
    if not (secret and two_factor.verifier_code_totp(secret, req.code)):
        raise HTTPException(400, "Code invalide.")
    codes = two_factor.generer_codes_secours()
    user.recovery_hashes = two_factor.hachages_codes(codes)
    audit.enregistrer(db, "2fa_codes_regenerated", user=user,
                      copro_id=two_factor.copro_principale_id(db, user), request=request)
    db.commit()
    return TwoFactorRecoveryOut(recovery_codes=codes)


@router.post("/users/{user_id}/2fa/reset")
def reinitialiser_2fa(user_id: int, request: Request,
                      db: Session = Depends(get_db),
                      current: User = Depends(require_syndic)):
    """Syndic : réinitialise la 2FA d'un compte de SA copropriété (téléphone perdu).
    L'opération est tracée et notifiée par email au compte concerné."""
    if user_id == current.id:
        raise HTTPException(400, "Utilisez « Désactiver » dans vos propres réglages de sécurité.")
    copro = get_or_create_copro(db, current)
    target = (db.query(User)
              .join(UserCopro, UserCopro.user_id == User.id)
              .filter(User.id == user_id, UserCopro.copropriete_id == copro.id)
              .first())
    if not target:
        raise HTTPException(404, "Utilisateur introuvable")
    target.totp_enabled = False
    target.totp_secret = ""
    target.recovery_hashes = "[]"
    audit.enregistrer(db, "2fa_reset", user=current, copro_id=copro.id,
                      detail=f"2FA de {target.email} réinitialisée", request=request)
    db.commit()
    alertes.alerte_evenement(
        db, target,
        f"Votre double authentification a été RÉINITIALISÉE par le syndic ({current.nom})."
        " Vous devrez la réactiver à votre prochaine connexion.")
    return {"ok": True}


# ---------- Journal d'audit ----------

@router_audit.get("", response_model=list[AuditOut])
def journal_audit(limit: int = 50, offset: int = 0, action: str = "",
                  db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Journal d'audit de la copropriété active (le plus récent d'abord).

    Inclut les entrées sans copro (ex. premier enrôlement 2FA, avant que la
    copropriété existe) qui appartiennent à un compte de cette copropriété.
    """
    copro = get_or_create_copro(db, user)
    user_ids = [u.id for u in (db.query(User)
                               .join(UserCopro, UserCopro.user_id == User.id)
                               .filter(UserCopro.copropriete_id == copro.id)
                               .all())]
    q = db.query(AuditLog).filter(
        or_(
            AuditLog.copro_id == copro.id,
            and_(AuditLog.copro_id.is_(None), AuditLog.user_id.in_(user_ids or [-1])),
        )
    )
    if action:
        q = q.filter(AuditLog.action == action)
    return (q.order_by(AuditLog.id.desc())
            .offset(max(0, offset))
            .limit(min(max(1, limit), 200))
            .all())

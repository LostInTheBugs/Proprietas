from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from app.core import audit
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_scoped_token,
    hash_password,
    verify_password,
)
from app.core.deps import get_current_user, require_syndic
from app.models.user import User, UserCopro
from app.models.copropriete import Copropriete
from app.routes.copro import get_or_create_copro
from app.schemas import RegisterRequest, LoginRequest, LoginResponse, TokenResponse, UserOut, UserCreate, CoproCreate, ThemeIn
from app.core.rate_limit import check_login_allowed, record_failure, clear_failures
from app.core.session import jeton_entrant, poser_cookie_session, supprimer_cookie_session
from app.services import two_factor

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=LoginResponse)
def register(req: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Création du premier compte (syndic). Fermé dès qu'un utilisateur non-démo existe."""
    if db.query(User).filter(User.is_demo == False).count() > 0:  # noqa: E712
        raise HTTPException(403, "Inscription fermée : un compte existe déjà")
    user = User(
        email=req.email.lower().strip(),
        password_hash=hash_password(req.password),
        nom=req.nom.strip(),
        role="syndic",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    # La politique par défaut de l'installation peut exiger l'enrôlement immédiat
    # de la double authentification (instance exposée) : l'app enchaîne sur le QR.
    if two_factor.politique_requise(db, user):
        return LoginResponse(
            must_enroll_2fa=True,
            challenge_token=create_scoped_token(user.id, "2fa_setup", minutes=30,
                                                ver=user.token_version or 0),
        )
    token = create_access_token(user.id, ver=user.token_version or 0)
    poser_cookie_session(request, response, token)
    return LoginResponse(access_token=token)


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, response: Response, db: Session = Depends(get_db), request: Request = None):  # noqa: E501
    """Étape 1 : mot de passe. Réponse : jeton complet, ou étape 2FA à poursuivre
    (two_factor_required = code à saisir ; must_enroll_2fa = activation exigée)."""
    ip = audit.client_ip(request)
    check_login_allowed(req.email, ip)
    user = db.query(User).filter(User.email == req.email.lower().strip()).first()
    if not user or not verify_password(req.password, user.password_hash):
        record_failure(req.email, ip)
        audit.enregistrer(
            db, "login_failed", user=user,
            copro_id=two_factor.copro_principale_id(db, user) if user else None,
            detail=req.email.lower().strip(), request=request,
        )
        db.commit()
        raise HTTPException(401, "Email ou mot de passe incorrect")
    clear_failures(req.email, ip)
    # Double authentification (les comptes démo en sont exemptés)
    if user.totp_enabled and not user.is_demo:
        return LoginResponse(
            two_factor_required=True,
            challenge_token=create_scoped_token(user.id, "2fa_challenge",
                                                ver=user.token_version or 0),
        )
    if not user.totp_enabled and two_factor.politique_requise(db, user):
        return LoginResponse(
            must_enroll_2fa=True,
            challenge_token=create_scoped_token(user.id, "2fa_setup", minutes=30,
                                                ver=user.token_version or 0),
        )
    two_factor.finaliser_connexion(db, user, request)  # journal + alerte nouvelle IP
    token = create_access_token(user.id, two_factor.copro_principale_id(db, user),
                                ver=user.token_version or 0)
    poser_cookie_session(request, response, token)
    return LoginResponse(access_token=token)


@router.get("/coproprietes")
def mes_coproprietes(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Liste des copropriétés accessibles + la copro active du token."""
    liens = (db.query(UserCopro).filter(UserCopro.user_id == user.id)
             .order_by(UserCopro.principale.desc(), UserCopro.id).all())
    active = (getattr(user, "_token_data", None) or {}).get("copro_id")
    out = []
    for lien in liens:
        copro = db.query(Copropriete).filter(Copropriete.id == lien.copropriete_id).first()
        if not copro:
            continue
        out.append({
            "id": copro.id,
            "nom": copro.nom,
            "ville": copro.ville or "",
            "principale": bool(lien.principale),
            "active": active is not None and int(active) == copro.id,
        })
    # Fallback : token sans copro_id → active = première liaison
    if active is None and out:
        out[0]["active"] = True
    return out


@router.post("/switch-copro/{copro_id}", response_model=TokenResponse)
def switch_copro(copro_id: int, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Bascule la copropriété active du user (nouveau token avec copro_id)."""
    lien = (db.query(UserCopro)
            .filter(UserCopro.user_id == user.id, UserCopro.copropriete_id == copro_id)
            .first())
    if not lien:
        raise HTTPException(403, "Accès refusé à cette copropriété")
    token = create_access_token(user.id, copro_id, ver=user.token_version or 0)
    poser_cookie_session(request, response, token)
    return TokenResponse(access_token=token)


@router.post("/coproprietes", response_model=TokenResponse)
def creer_copropriete(data: CoproCreate, request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Crée une nouvelle copropriété pour le syndic (devient la copro active)."""
    copro = Copropriete(
        nom=data.nom, adresse=data.adresse, ville=data.ville, code_postal=data.code_postal,
        annee_construction=data.annee_construction,
        totp_policy=two_factor.politique_defaut(),
    )
    db.add(copro)
    db.commit()
    db.refresh(copro)
    db.add(UserCopro(user_id=user.id, copropriete_id=copro.id, principale=True))
    audit.enregistrer(db, "copro_created", user=user, copro_id=copro.id, detail=copro.nom)
    db.commit()
    token = create_access_token(user.id, copro.id, ver=user.token_version or 0)
    poser_cookie_session(request, response, token)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/theme")
def maj_theme(data: ThemeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Préférence d'affichage du compte (clair / sombre / système)."""
    user.theme = data.theme
    db.commit()
    return {"theme": user.theme}


@router.post("/logout")
def logout(response: Response):
    """Ferme la session du navigateur (suppression du cookie).

    Le jeton n'est pas révoqué côté serveur (il expire de lui-même) : pour une
    révocation immédiate de toutes les sessions, utiliser « Déconnecter tous mes
    appareils » (POST /logout-all)."""
    supprimer_cookie_session(response)
    return {"ok": True}


@router.post("/session")
def migrer_session(request: Request, response: Response,
                   user: User = Depends(get_current_user)):
    """Convertit une session à jeton (Bearer hérité) en cookie httpOnly.
    Appelé une fois par le front après la mise à jour — idempotent."""
    poser_cookie_session(request, response, jeton_entrant(request))
    return {"ok": True}


@router.post("/users", response_model=UserOut)
def create_user(req: UserCreate, request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    if db.query(User).filter(User.email == req.email.lower().strip()).first():
        raise HTTPException(400, "Cet email est déjà utilisé")
    # Le compte créé est lié à la copropriété active du syndic
    copro = get_or_create_copro(db, user)
    new_user = User(
        email=req.email.lower().strip(),
        password_hash=hash_password(req.password),
        nom=req.nom.strip(),
        role=req.role,
        copropriete_id=copro.id,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    db.add(UserCopro(user_id=new_user.id, copropriete_id=copro.id, principale=True))
    audit.enregistrer(db, "user_created", user=user, copro_id=copro.id,
                      detail=f"{new_user.email} ({new_user.role})", request=request)
    db.commit()
    return new_user


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Comptes de la copropriété active uniquement (jamais toute l'instance)."""
    copro = get_or_create_copro(db, user)
    return (db.query(User)
            .join(UserCopro, UserCopro.user_id == User.id)
            .filter(UserCopro.copropriete_id == copro.id)
            .order_by(User.nom).all())


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db), current: User = Depends(require_syndic)):
    if user_id == current.id:
        raise HTTPException(400, "Impossible de supprimer son propre compte")
    copro = get_or_create_copro(db, current)
    user = (db.query(User)
            .join(UserCopro, UserCopro.user_id == User.id)
            .filter(User.id == user_id, UserCopro.copropriete_id == copro.id)
            .first())
    if not user:
        raise HTTPException(404, "Utilisateur introuvable")
    audit.enregistrer(db, "user_deleted", user=current, copro_id=copro.id,
                      detail=f"{user.email} ({user.role})", request=request)
    db.delete(user)
    db.commit()
    return {"ok": True}

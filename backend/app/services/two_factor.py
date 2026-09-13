"""Double authentification (TOTP, RFC 6238) — le cœur « sécurité du compte ».

- Secret TOTP stocké CHIFFRÉ en base (app.core.crypto), jamais renvoyé après l'enrôlement.
- 10 codes de secours à usage unique, hachés (HMAC-SHA256) — affichés UNE seule fois.
- Politique par copropriété : off | syndic | all — comptes démo exemptés.
- `finaliser_connexion` : dernière connexion + journal + alerte email (nouvelle IP).

Compatible avec toute application TOTP open source (FreeOTP, Aegis, Google
Authenticator, 1Password…) : aucun service externe, tout vit dans le backend.
"""
import base64
import io
import json
import secrets
from datetime import datetime

import pyotp
import qrcode
import qrcode.image.svg

from app.core import audit, crypto
from app.core.config import get_settings
from app.models.copropriete import Copropriete
from app.models.user import User, UserCopro

RECOVERY_COUNT = 10
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sans I/O/0/1 (ambiguïtés)
POLITIQUES = ("off", "syndic", "all")


# ---------- Enrôlement ----------

def generer_secret() -> str:
    return pyotp.random_base32()


def otpauth_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="Proprietas")


def qr_svg_data_uri(uri: str) -> str:
    """QR code en SVG encodé en base64 — affichable en <img src="data:...">."""
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=10)
    buf = io.BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


# ---------- Vérification ----------

def verifier_code_totp(secret: str, code: str) -> bool:
    """Code à 6 chiffres, fenêtre ±30 s (tolérance d'horloge de 1 pas)."""
    code = (code or "").strip().replace(" ", "")
    if not secret or not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def generer_codes_secours() -> list[str]:
    codes = []
    for _ in range(RECOVERY_COUNT):
        brut = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{brut[:5]}-{brut[5:]}")
    return codes


def hachages_codes(codes: list[str]) -> str:
    return json.dumps([crypto.hacher_code_secours(c) for c in codes])


def nb_codes_restants(user: User) -> int:
    try:
        return len(json.loads(user.recovery_hashes or "[]"))
    except ValueError:
        return 0


def consommer_code_secours(user: User, code: str) -> bool:
    """Vérifie PUIS consomme un code de secours (usage unique) ; met à jour la colonne."""
    try:
        hashes = json.loads(user.recovery_hashes or "[]")
    except ValueError:
        hashes = []
    cible = crypto.hacher_code_secours(code)
    for i, h in enumerate(hashes):
        if secrets.compare_digest(h, cible):
            hashes.pop(i)
            user.recovery_hashes = json.dumps(hashes)
            return True
    return False


def valider_code(user: User, code: str) -> str:
    """Renvoie "" si invalide, sinon « totp » ou « secours » (code consommé)."""
    secret = crypto.dechiffrer_secret(user.totp_secret or "")
    if secret and verifier_code_totp(secret, code):
        return "totp"
    if consommer_code_secours(user, code):
        return "secours"
    return ""


# ---------- Politique 2FA ----------

def politique_requise(db, user: User) -> bool:
    """Le compte est-il soumis à la 2FA au vu des politiques de ses copropriétés ?

    - comptes démo : jamais (« all » ⇒ tout le monde ; « syndic » ⇒ les syndics).
    - compte sans copropriété (tout premier compte d'une instance vierge) :
      politique par défaut de l'installation (COPRO_TOTP_DEFAULT_POLICY).
    """
    if user.is_demo:
        return False
    liens = db.query(UserCopro).filter(UserCopro.user_id == user.id).all()
    if not liens:
        p = politique_defaut()
        return p == "all" or (p == "syndic" and user.role == "syndic")
    for lien in liens:
        copro = db.query(Copropriete).filter(Copropriete.id == lien.copropriete_id).first()
        if not copro:
            continue
        p = copro.totp_policy or "off"
        if p == "all" or (p == "syndic" and user.role == "syndic"):
            return True
    return False


def politique_defaut() -> str:
    p = (get_settings().totp_default_policy or "off").lower()
    return p if p in POLITIQUES else "off"


def copro_principale_id(db, user: User) -> int | None:
    """Id de la copropriété principale du compte (liaison), sinon None."""
    lien = (db.query(UserCopro).filter(UserCopro.user_id == user.id)
            .order_by(UserCopro.principale.desc(), UserCopro.id).first())
    return lien.copropriete_id if lien else None


# ---------- Fin de connexion ----------

def finaliser_connexion(db, user: User, request) -> None:
    """Dernière connexion + entrée d'audit + alerte email si l'IP a changé."""
    from app.services import alertes

    ip = audit.client_ip(request)
    ancienne_ip = user.last_login_ip or ""
    user.last_login_at = datetime.now()
    user.last_login_ip = ip
    user.last_login_ua = ((request.headers.get("user-agent") if request else "") or "")[:250]
    audit.enregistrer(db, "login", user=user,
                      copro_id=copro_principale_id(db, user), request=request)
    db.commit()
    if ip and ip != ancienne_ip:
        alertes.alerte_connexion(db, user, ip)

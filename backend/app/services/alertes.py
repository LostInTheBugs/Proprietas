"""Alertes email de sécurité — best effort, JAMAIS bloquantes.

Envoyées dans un thread dédié (aucun impact sur le temps de réponse du login) :
- « nouvelle connexion » quand l'IP diffère de la précédente ;
- événements sensibles : 2FA désactivée / réinitialisée / code de secours utilisé.

Les réglages SMTP sont figés dans un SimpleNamespace AVANT le thread : aucun
objet SQLAlchemy (lié à une session non thread-safe) ne traverse le thread.
"""
import threading
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.models.copropriete import Copropriete
from app.models.user import User, UserCopro
from app.services.emailer import EmailError, _date_fr, envoyer_email


def _copro_smtp(db: Session, user: User) -> Copropriete | None:
    """Copropriété principale du compte, si son SMTP est configuré — sinon None."""
    lien = (db.query(UserCopro).filter(UserCopro.user_id == user.id)
            .order_by(UserCopro.principale.desc(), UserCopro.id).first())
    if not lien:
        return None
    copro = db.query(Copropriete).filter(Copropriete.id == lien.copropriete_id).first()
    if not copro or not copro.smtp_host or not copro.email_expediteur:
        return None
    return copro


def _cfg_smtp(copro: Copropriete) -> SimpleNamespace:
    return SimpleNamespace(
        smtp_host=copro.smtp_host,
        smtp_port=copro.smtp_port,
        smtp_user=copro.smtp_user,
        smtp_password=copro.smtp_password,
        email_expediteur=copro.email_expediteur,
    )


def _envoyer(cfg, dest: str, sujet: str, corps: str) -> None:
    try:
        envoyer_email(cfg, dest, sujet, corps)
    except EmailError:
        pass  # alerte best effort : jamais d'erreur propagée
    except Exception:
        pass


def _declencher(cfg, dest: str, sujet: str, corps: str) -> None:
    threading.Thread(target=_envoyer, args=(cfg, dest, sujet, corps), daemon=True).start()


def _horodatage() -> str:
    now = datetime.now()
    return f"{_date_fr(now)} à {now.strftime('%H:%M')}"


def alerte_connexion(db: Session, user: User, ip: str) -> None:
    """Email « nouvelle connexion » (appelé uniquement quand l'IP a changé)."""
    copro = _copro_smtp(db, user)
    if not copro:
        return
    corps = (
        f"Bonjour {user.nom},\n\n"
        "Une connexion à votre compte Proprietas vient d'être effectuée.\n\n"
        f"  • Date : {_horodatage()}\n"
        f"  • Adresse IP : {ip}\n\n"
        "Si vous êtes bien à l'origine de cette connexion, aucune action n'est nécessaire.\n"
        "Sinon, changez votre mot de passe dès que possible et prévenez le syndic.\n\n"
        f"— Proprietas — {copro.nom}"
    )
    _declencher(_cfg_smtp(copro), user.email,
                "Proprietas — nouvelle connexion à votre compte", corps)


def alerte_evenement(db: Session, user: User, evenement: str) -> None:
    """Email d'alerte pour un changement de sécurité (2FA désactivée, etc.)."""
    copro = _copro_smtp(db, user)
    if not copro:
        return
    corps = (
        f"Bonjour {user.nom},\n\n"
        f"{evenement}\n\n"
        f"Date : {_horodatage()}\n\n"
        "Si vous n'êtes pas à l'origine de ce changement, changez votre mot de passe "
        "sans délai et contactez le syndic.\n\n"
        f"— Proprietas — {copro.nom}"
    )
    _declencher(_cfg_smtp(copro), user.email,
                "Proprietas — modification de sécurité sur votre compte", corps)

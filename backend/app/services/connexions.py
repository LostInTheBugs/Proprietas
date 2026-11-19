"""Connexions : dernière connexion, historique activable, blocage des comptes après des échecs.

Réglages par copropriété (Réglages → Sécurité, syndic). Un compte rattaché à plusieurs
copropriétés suit la règle la plus stricte :

- **historique** : par défaut, seules la dernière connexion et le dernier échec sont gardés (sur
  le compte). Historique activé : chaque connexion réussie, ratée ou refusée (compte bloqué) est
  aussi écrite dans le journal d'audit (purgé après COPRO_RETENTION_JOURNAL_MOIS).
- **blocage** : au seuil d'échecs d'affilée (puis à chaque multiple), le compte est bloqué
  quelques minutes ; au seuil définitif, il l'est jusqu'à ce qu'un syndic de l'une de ses
  copropriétés ou un administrateur de l'instance le débloque (ou, en secours, la commande
  `python -m app.cli.debloquer`). Les comptes avec double authentification n'y sont soumis
  que si la copropriété le demande ; les comptes de démonstration jamais.

Le compteur d'échecs repart à zéro à chaque connexion réussie. Le blocage, le déblocage et les
alertes sont toujours journalisés, historique activé ou non. Le limiteur en mémoire par
(e-mail, IP) de core/rate_limit.py reste en place, en plus.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException

from app.core import audit
from app.models.audit import AuditLog
from app.models.copropriete import Copropriete
from app.models.user import User, UserCopro

ACTIONS_CONNEXION = ("login", "login_failed", "login_blocked", "account_locked", "account_unlocked")


@dataclass
class Politique:
    historique: bool = False
    blocage: bool = False
    seuil: int = 5
    minutes: int = 15
    seuil_definitif: int = 0          # 0 : jamais de blocage définitif


def _copros(db, user: User) -> list[Copropriete]:
    ids = [l.copropriete_id for l in db.query(UserCopro).filter(UserCopro.user_id == user.id).all()]
    return db.query(Copropriete).filter(Copropriete.id.in_(ids)).all() if ids else []


def politique(db, user: User) -> Politique:
    copros = _copros(db, user)
    p = Politique(historique=any(c.connexions_historique for c in copros))
    soumises = [c for c in copros if c.verrouillage_actif and (not user.totp_enabled or c.verrouillage_avec_2fa)]
    if user.is_demo or not soumises:
        return p
    p.blocage = True
    p.seuil = min(max(1, c.verrouillage_seuil or 5) for c in soumises)
    p.minutes = max(max(1, c.verrouillage_minutes or 15) for c in soumises)
    definitifs = [c.verrouillage_seuil_definitif for c in soumises if (c.verrouillage_seuil_definitif or 0) > 0]
    p.seuil_definitif = min(definitifs) if definitifs else 0
    return p


def _copro_id(db, user: User) -> int | None:
    from app.services.two_factor import copro_principale_id
    return copro_principale_id(db, user)


def _heure(d: datetime) -> str:
    return d.strftime("%H h %M")


def _journaliser(db, user: User, action: str, detail: str, request, pol: Politique | None = None) -> None:
    """Connexion réussie, ratée ou refusée : seulement si l'historique est activé."""
    if (pol or politique(db, user)).historique:
        audit.enregistrer(db, action, user=user, copro_id=_copro_id(db, user), detail=detail, request=request)


def verifier_non_bloque(db, user: User, request) -> None:
    """Refuse (423) la connexion d'un compte bloqué, avant même de regarder le mot de passe."""
    if user.bloque_definitif_le:
        quand = "jusqu'au déblocage"
        message = ("Compte bloqué après trop d'échecs de connexion : demandez au syndic "
                   "(ou à l'administrateur) de le débloquer.")
    elif user.bloque_jusqua and user.bloque_jusqua > datetime.now():
        quand = f"jusqu'à {_heure(user.bloque_jusqua)}"
        message = (f"Compte bloqué après plusieurs échecs de connexion : réessayez après "
                   f"{_heure(user.bloque_jusqua)}.")
    else:
        return
    _journaliser(db, user, "login_blocked", f"bloqué {quand}", request)
    db.commit()
    raise HTTPException(423, message)


def echec(db, user: User, request, detail: str) -> None:
    """Échec (mot de passe ou code) : compteur, dernier échec, historique, blocage éventuel.
    L'appelant fait le commit."""
    from app.services import alertes
    maintenant = datetime.now()
    user.echecs_connexion = (user.echecs_connexion or 0) + 1
    user.dernier_echec_at = maintenant
    pol = politique(db, user)
    _journaliser(db, user, "login_failed", detail, request, pol)
    if not pol.blocage:
        return
    n = user.echecs_connexion
    if pol.seuil_definitif and n >= pol.seuil_definitif:
        user.bloque_definitif_le = maintenant
        audit.enregistrer(db, "account_locked", user=user, copro_id=_copro_id(db, user), request=request,
                          detail=f"bloqué jusqu'au déblocage après {n} échecs d'affilée")
        alertes.alerte_evenement(
            db, user, f"Votre compte a été bloqué après {n} échecs de connexion d'affilée. "
                      "Demandez au syndic de le débloquer. Si ce n'était pas vous, quelqu'un essaie "
                      "peut-être de deviner votre mot de passe : changez-le après le déblocage.")
    elif n % pol.seuil == 0:
        user.bloque_jusqua = maintenant + timedelta(minutes=pol.minutes)
        audit.enregistrer(db, "account_locked", user=user, copro_id=_copro_id(db, user), request=request,
                          detail=f"{n} échecs d'affilée : bloqué jusqu'à {_heure(user.bloque_jusqua)}")
        alertes.alerte_evenement(
            db, user, f"Votre compte est bloqué jusqu'à {_heure(user.bloque_jusqua)} après {n} échecs "
                      "de connexion d'affilée. Si ce n'était pas vous, changez votre mot de passe.")


def succes(db, user: User, request) -> None:
    """Connexion réussie : compteur remis à zéro, historique. L'appelant fait le commit."""
    user.echecs_connexion = 0
    user.bloque_jusqua = None
    _journaliser(db, user, "login", "", request)


def debloquer(db, cible: User, auteur: User | None, request, origine: str = "") -> None:
    """Débloque le compte (syndic, administrateur ou commande serveur) et prévient la personne."""
    from app.services import alertes
    cible.echecs_connexion = 0
    cible.bloque_jusqua = None
    cible.bloque_definitif_le = None
    par = origine or (f"par {auteur.email}" if auteur else "")
    audit.enregistrer(db, "account_unlocked", user=cible, copro_id=_copro_id(db, cible),
                      detail=f"débloqué {par}".strip(), request=request)
    db.commit()
    alertes.alerte_evenement(db, cible, "Votre compte a été débloqué : vous pouvez de nouveau vous connecter.")


def resume(db, user: User, limite: int = 20) -> dict:
    """Dernière connexion, dernier échec, état du blocage et, si l'historique est activé, les
    dernières entrées du journal concernant les connexions de ce compte."""
    pol = politique(db, user)
    entrees = []
    if pol.historique:
        rows = (db.query(AuditLog)
                .filter(AuditLog.user_id == user.id, AuditLog.action.in_(ACTIONS_CONNEXION))
                .order_by(AuditLog.id.desc()).limit(max(1, min(limite, 200))).all())
        entrees = [{"date": r.created_at, "action": r.action, "detail": r.detail or "", "ip": r.ip or "",
                    "navigateur": r.user_agent or ""} for r in rows]
    return {
        "historique": pol.historique,
        "derniere_connexion": user.last_login_at,
        "derniere_ip": user.last_login_ip or "",
        "dernier_echec": user.dernier_echec_at,
        "echecs_d_affilee": user.echecs_connexion or 0,
        "bloque": user.bloque,
        "bloque_jusqua": user.bloque_jusqua if user.bloque == "temporaire" else None,
        "entrees": entrees,
    }

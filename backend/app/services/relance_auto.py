"""Relances automatiques (cron) : envoi planifié des relances d'impayés.

Le scheduler (core/scheduler.py) appelle run_relances_auto() toutes les
30 minutes ; la fonction vérifie pour chaque copropriété active si le moment
est venu (heure exacte, jour selon fréquence) et envoie les relances aux lots
en retard qui n'ont pas été relancés depuis la fréquence choisie.
"""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.money import D
from app.models.copropriete import Copropriete
from app.models.relance import Relance
from app.models.user import User
from app.routes.relances import _etat_lots, envoyer_relance_lot

JOURS_SEMAINE = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def prochaine_relance(copro: Copropriete, maintenant: datetime | None = None) -> datetime | None:
    """Prochaine date/heure d'envoi des relances automatiques (pour l'affichage)."""
    if not copro.relance_auto:
        return None
    maintenant = maintenant or datetime.now()
    heure = copro.relance_heure or "09:00"
    try:
        hh, mm = (int(x) for x in heure.split(":"))
    except (ValueError, AttributeError):
        hh, mm = 9, 0
    for delta in range(0, 32):  # cherche dans le mois qui vient
        jour = (maintenant + timedelta(days=delta)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if jour <= maintenant:
            continue
        if copro.relance_frequence == "hebdo":
            if (jour.weekday() + 1) == (copro.relance_jour or 1):
                return jour
        else:
            if jour.day == (copro.relance_jour or 1):
                return jour
    return None


def _moment_venu(copro: Copropriete, maintenant: datetime) -> bool:
    """True si le tick correspond au créneau configuré (heure exacte + jour)."""
    heure = copro.relance_heure or "09:00"
    if maintenant.strftime("%H:%M") != heure:
        return False
    if copro.relance_frequence == "hebdo":
        return (maintenant.weekday() + 1) == (copro.relance_jour or 1)
    return maintenant.day == (copro.relance_jour or 1)


def _derniere_relance(db: Session, lot_id: int) -> Relance | None:
    return (db.query(Relance)
            .filter(Relance.lot_id == lot_id, Relance.statut == "envoye")
            .order_by(Relance.date_envoi.desc()).first())


def run_relances_auto(db: Session, maintenant: datetime | None = None) -> dict:
    """Exécute les relances automatiques pour toutes les copropriétés actives.

    Retour : {"copros": n, "envoyes": n, "deja_relances": n, "aucun_impaye": n, "sans_email": n, "erreurs": [...]}
    """
    maintenant = maintenant or datetime.now()
    stats = {"copros": 0, "envoyes": 0, "deja_relances": 0, "aucun_impaye": 0, "sans_email": 0, "erreurs": []}
    copros = db.query(Copropriete).filter(Copropriete.relance_auto == True).all()  # noqa: E712
    for copro in copros:
        if not _moment_venu(copro, maintenant):
            continue
        stats["copros"] += 1
        syndic_nom = "Le syndic"
        syndic = (db.query(User).filter(User.copropriete_id == copro.id, User.role == "syndic").first())
        if syndic and syndic.nom:
            syndic_nom = syndic.nom
        delai = timedelta(days=7 if copro.relance_frequence == "hebdo" else 30)
        minimum = copro.relance_minimum or D(0)
        for e in _etat_lots(db, copro):
            if e["solde"] <= max(D("0.005"), minimum):
                continue  # lot à jour ou sous le seuil
            derniere = _derniere_relance(db, e["lot"].id)
            if derniere and (maintenant - derniere.date_envoi) < delai:
                stats["deja_relances"] += 1
                continue
            statut = envoyer_relance_lot(db, copro, e, syndic_nom)
            if statut == "envoye":
                stats["envoyes"] += 1
            elif statut == "sans_email":
                stats["sans_email"] += 1
            else:
                stats["erreurs"].append(f"Lot {e['lot'].numero}")
        db.commit()
    return stats

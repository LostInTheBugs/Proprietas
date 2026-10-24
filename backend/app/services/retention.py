"""Durées de conservation (RGPD, docs/rgpd.md § 5) : purge des journaux.

Appelée chaque jour par le scheduler. Supprime les entrées du journal d'audit plus
anciennes que COPRO_RETENTION_JOURNAL_MOIS, et efface l'IP et le navigateur de la
dernière connexion des comptes qui ne se sont pas connectés depuis (la date reste).
"""
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.audit import AuditLog
from app.models.user import User


def purger_journaux(db: Session, maintenant: datetime | None = None, mois: int | None = None) -> dict:
    mois = get_settings().retention_journal_mois if mois is None else mois
    if mois <= 0:
        return {"audit": 0, "connexions": 0}
    limite = (maintenant or datetime.now()) - timedelta(days=30 * mois)
    audit = db.query(AuditLog).filter(AuditLog.created_at < limite).delete(synchronize_session=False)
    connexions = (db.query(User)
                  .filter(User.last_login_at < limite,
                          or_(User.last_login_ip != "", User.last_login_ua != ""))
                  .update({"last_login_ip": "", "last_login_ua": ""}, synchronize_session=False))
    db.commit()
    return {"audit": audit, "connexions": connexions}

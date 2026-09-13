"""Journal d'audit — trace les actions sensibles (connexions, 2FA, envois, exports).

Colonnes volontairement dénormalisées (email, nom, copro_id SANS clé étrangère) :
le journal est forensique et doit survivre à la suppression d'un compte ou d'une
copropriété. Écriture via `app.core.audit.enregistrer` (jamais bloquante).
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.now, index=True)
    user_id = Column(Integer, nullable=True)
    user_email = Column(String, default="")
    user_nom = Column(String, default="")
    copro_id = Column(Integer, nullable=True, index=True)
    action = Column(String, default="", index=True)  # ex. login, 2fa_enabled, export_quittances
    detail = Column(Text, default="")
    ip = Column(String, default="")
    user_agent = Column(String, default="")

"""Notification du procès-verbal aux copropriétaires opposants et défaillants.

Loi n° 65-557, art. 42 al. 2 : le syndic notifie le PV dans le mois qui suit l'assemblée ;
la notification fait courir le délai de contestation de deux mois. Elle se fait par lettre
recommandée électronique (règle) ou par LRAR pour qui a demandé la voie postale (art. 42-1).
Une ligne par copropriétaire à notifier ; le nom est figé (le compte peut être supprimé).
"""
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String

from app.core.database import Base


class NotificationPV(Base):
    __tablename__ = "notifications_pv"
    id = Column(Integer, primary_key=True)
    ag_id = Column(Integer, ForeignKey("ags.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    nom = Column(String, nullable=False, default="")
    # « opposant », « défaillant » ou « opposant et défaillant », avec les résolutions concernées.
    qualite = Column(String, nullable=False, default="")
    resolutions = Column(String, nullable=False, default="")
    mode = Column(String, nullable=False, default="lre")          # lre | lrar
    date_envoi = Column(Date, nullable=True)
    # Première présentation (LRAR) ou avis électronique (LRE) : le délai de 2 mois court du lendemain.
    date_presentation = Column(Date, nullable=True)
    reference = Column(String, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.now)

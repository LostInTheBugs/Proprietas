"""Supervision : relevés de l'état du serveur et de l'activité, toutes les 5 minutes (services/supervision.py)."""
from sqlalchemy import Column, DateTime, Float, Integer, String

from app.core.database import Base


class MesureServeur(Base):
    __tablename__ = "mesures_serveur"
    id = Column(Integer, primary_key=True)
    instant = Column(DateTime, nullable=False, index=True)
    cpu_pct = Column(Float, nullable=True)          # charge sur 1 min / nombre de cœurs × 100
    memoire_pct = Column(Float, nullable=True)
    disque_pct = Column(Float, nullable=True)
    requetes = Column(Integer, nullable=False, default=0)      # requêtes de l'API depuis le relevé précédent
    erreurs_5xx = Column(Integer, nullable=False, default=0)
    latence_moy_ms = Column(Float, nullable=True)
    latence_p95_ms = Column(Float, nullable=True)
    source = Column(String, nullable=False, default="application")   # hote | application

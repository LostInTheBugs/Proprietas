"""Mandats du syndic bénévole et du conseil syndical (services/mandats.py ; demande de Fred, 21/11/2026).

Une ligne par désignation : rôle, période, membres. Votée en AG (`resolution_id`, recréée à chaque calcul de la
résolution) ou saisie à la main pour le passé (`resolution_id` nul, `ag_id` facultatif).
"""
from sqlalchemy import JSON, Column, Date, ForeignKey, Integer, String

from app.core.database import Base


class Mandat(Base):
    __tablename__ = "mandats"
    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, nullable=False)                     # syndic | conseil
    debut = Column(Date, nullable=False)
    fin = Column(Date, nullable=False)                         # dernier jour du mandat
    # [{"personne_id": int | None, "nom": str}] : compte de la copropriété, ou nom libre (mandat passé).
    membres = Column(JSON, nullable=False, default=list)
    ag_id = Column(Integer, ForeignKey("ags.id", ondelete="SET NULL"), nullable=True)
    resolution_id = Column(Integer, ForeignKey("resolutions.id", ondelete="CASCADE"), nullable=True, index=True)

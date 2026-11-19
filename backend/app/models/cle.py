"""Clés de répartition : charges spéciales (loi n° 65-557, art. 10) — services/cles.py.

Une clé (« Bâtiment A », « Ascenseur », « Garages »…) donne ses propres millièmes aux lots concernés ; les
autres lots n'y participent pas. Sans clé : charges générales, réparties par les tantièmes du lot.
"""
from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class CleRepartition(Base):
    __tablename__ = "cles_repartition"
    __table_args__ = (UniqueConstraint("copropriete_id", "nom", name="uq_cles_repartition_copro_nom"),)
    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False, index=True)
    nom = Column(String, nullable=False)

    lots = relationship("CleLot", back_populates="cle", cascade="all, delete-orphan")


class CleLot(Base):
    __tablename__ = "cles_lots"
    __table_args__ = (UniqueConstraint("cle_id", "lot_id", name="uq_cles_lots_cle_lot"),)
    id = Column(Integer, primary_key=True)
    cle_id = Column(Integer, ForeignKey("cles_repartition.id", ondelete="CASCADE"), nullable=False, index=True)
    lot_id = Column(Integer, ForeignKey("lots.id", ondelete="CASCADE"), nullable=False)
    tantiemes = Column(Integer, nullable=False, default=0)

    cle = relationship("CleRepartition", back_populates="lots")

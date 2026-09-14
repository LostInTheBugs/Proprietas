from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float, Text
from sqlalchemy.orm import relationship
from app.core.database import Base


class Relance(Base):
    """Relance d'impayé envoyée au propriétaire d'un lot."""
    __tablename__ = "relances"

    id = Column(Integer, primary_key=True)
    lot_id = Column(Integer, ForeignKey("lots.id"), nullable=False)
    # NULL possible : la fiche personne a pu être supprimée (RGPD) — l'historique
    # de relance reste attaché au LOT (preuve conservée, nom retiré).
    personne_id = Column(Integer, ForeignKey("personnes.id"), nullable=True)
    date_envoi = Column(DateTime, nullable=False)
    statut = Column(String, default="envoye")
    montant_du = Column(Float, default=0.0)
    message = Column(Text, default="")

    lot = relationship("Lot")
    personne = relationship("Personne")

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float, Text
from sqlalchemy.orm import relationship
from app.core.database import Base


class Relance(Base):
    """Relance d'impayé envoyée au propriétaire d'un lot."""
    __tablename__ = "relances"

    id = Column(Integer, primary_key=True)
    lot_id = Column(Integer, ForeignKey("lots.id"), nullable=False)
    # Propriétaire relancé = un COMPTE UTILISATEUR (la colonne garde son nom
    # historique, la FK pointe users.id). NULL possible : le compte a pu être
    # supprimé (RGPD) — l'historique de relance reste attaché au LOT.
    personne_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    date_envoi = Column(DateTime, nullable=False)
    statut = Column(String, default="envoye")
    montant_du = Column(Float, default=0.0)
    message = Column(Text, default="")

    lot = relationship("Lot")
    personne = relationship("User")

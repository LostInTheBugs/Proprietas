from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from app.core.database import Base


class Invitation(Base):
    """Envoi de convocation à un copropriétaire pour une AG."""
    __tablename__ = "invitations"
    id = Column(Integer, primary_key=True)
    ag_id = Column(Integer, ForeignKey("ags.id"), nullable=False)
    # Copropriétaire convoqué = un COMPTE UTILISATEUR (la colonne garde son nom
    # historique, la FK pointe users.id). NULL possible : le compte a pu être
    # supprimé (RGPD) — l'envoi reste consigné pour l'AG.
    personne_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    date_envoi = Column(DateTime, nullable=False)
    statut = Column(String, default="envoye")  # envoye | erreur
    message = Column(Text, default="")

    ag = relationship("AG", back_populates="invitations")
    personne = relationship("User")

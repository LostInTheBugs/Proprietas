from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base


class Personne(Base):
    """Table HISTORIQUE « Lots & occupants » — remplacée par les comptes
    utilisateurs (modèle « zéro fiche ») : plus aucun code applicatif ne la
    lit ni ne l'écrit ; elle est conservée en base (migrations additives).
    """
    __tablename__ = "personnes"
    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False)
    nom = Column(String, nullable=False)
    prenom = Column(String, default="")
    email = Column(String, default="")
    telephone = Column(String, default="")
    adresse = Column(String, default="")  # adresse postale (mise en demeure)
    est_proprietaire = Column(Boolean, default=True)
    est_occupant = Column(Boolean, default=True)
    notes = Column(String, default="")

    copropriete = relationship("Copropriete", back_populates="personnes")

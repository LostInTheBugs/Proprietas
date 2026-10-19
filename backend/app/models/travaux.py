from sqlalchemy import Column, Integer, Numeric, String, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.core.database import Base


class Travaux(Base):
    """Ligne du plan pluriannuel de travaux (PPT)."""
    __tablename__ = "travaux"

    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False)
    libelle = Column(String, nullable=False)
    categorie = Column(String, default="autres")  # toiture, facade, chauffage, electricite, plomberie, communs, autres
    annee = Column(Integer, nullable=False)
    montant = Column(Numeric(12, 2), default=0.0)
    statut = Column(String, default="planifie")  # planifie, en_cours, realise
    notes = Column(Text, default="")

    copropriete = relationship("Copropriete")

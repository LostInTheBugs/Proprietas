from sqlalchemy import Column, Integer, Numeric, String, ForeignKey, Date
from sqlalchemy.orm import relationship
from app.core.database import Base


class Mouvement(Base):
    __tablename__ = "mouvements"
    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False)
    exercice_id = Column(Integer, ForeignKey("exercices.id"), nullable=False)
    date = Column(Date, nullable=False)
    libelle = Column(String, nullable=False)
    type = Column(String, nullable=False)  # encaissement | depense
    categorie = Column(String, default="autre")
    # categorie: charges | fonds_travaux | travaux | assurance | energie | entretien | autre
    montant = Column(Numeric(12, 2), default=0.0)
    lot_id = Column(Integer, ForeignKey("lots.id"), nullable=True)  # null = copro entière
    appel_id = Column(Integer, ForeignKey("appels_fonds.id"), nullable=True)
    piece_path = Column(String, default="")

    copropriete = relationship("Copropriete")
    exercice = relationship("Exercice", back_populates="mouvements")
    lot = relationship("Lot")
    appel = relationship("AppelFonds")

from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base


class Personne(Base):
    __tablename__ = "personnes"
    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False)
    nom = Column(String, nullable=False)
    prenom = Column(String, default="")
    email = Column(String, default="")
    telephone = Column(String, default="")
    adresse = Column(String, default="")  # adresse postale (mise en demeure)
    # Colonnes historiques (cases « Propriétaire / Occupant » de la fiche) : PLUS
    # utilisées par l'app — « propriétaire » se déduit des lots possédés,
    # l'occupation vit sur le compte utilisateur (users.est_occupant).
    est_proprietaire = Column(Boolean, default=True)
    est_occupant = Column(Boolean, default=True)
    notes = Column(String, default="")

    copropriete = relationship("Copropriete", back_populates="personnes")
    lots_proprietaire = relationship("Lot", foreign_keys="Lot.proprietaire_id", back_populates="proprietaire")
    lots_occupant = relationship("Lot", foreign_keys="Lot.occupant_id", back_populates="occupant")

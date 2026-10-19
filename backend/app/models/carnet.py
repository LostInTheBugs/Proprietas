from sqlalchemy import Column, Integer, Numeric, String, ForeignKey, Date, Text
from sqlalchemy.orm import relationship
from app.core.database import Base


class Entretien(Base):
    __tablename__ = "carnet_entretien"
    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False)
    date = Column(Date, nullable=False)
    type_intervention = Column(String, default="")
    prestataire = Column(String, default="")
    cout = Column(Numeric(12, 2), default=0.0)
    lot_id = Column(Integer, ForeignKey("lots.id"), nullable=True)  # null = parties communes
    description = Column(Text, default="")

    copropriete = relationship("Copropriete", back_populates="entreteins")
    lot = relationship("Lot")

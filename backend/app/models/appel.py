from sqlalchemy import Column, Integer, Numeric, String, ForeignKey, Boolean, Date
from sqlalchemy.orm import relationship
from app.core.database import Base


class AppelFonds(Base):
    __tablename__ = "appels_fonds"
    id = Column(Integer, primary_key=True)
    exercice_id = Column(Integer, ForeignKey("exercices.id"), nullable=False)
    libelle = Column(String, nullable=False)
    date_emission = Column(Date, nullable=False)
    date_echeance = Column(Date, nullable=True)
    montant_total = Column(Numeric(12, 2), default=0.0)
    inclut_fonds_travaux = Column(Boolean, default=False)
    # Montant du fonds de travaux inclus (taux appliqué au montant total)
    fonds_travaux_montant = Column(Numeric(12, 2), default=0.0)
    # Appel de régularisation des charges : exercice régularisé (décret n° 67-223, art. 6-2, 3°).
    # Ses parts peuvent être négatives (trop-perçu crédité au copropriétaire).
    regularisation_de_id = Column(Integer, ForeignKey("exercices.id", ondelete="SET NULL"), nullable=True)

    exercice = relationship("Exercice", back_populates="appels", foreign_keys=[exercice_id])
    parts = relationship("AppelLot", back_populates="appel", cascade="all, delete-orphan")


class AppelLot(Base):
    __tablename__ = "appels_lots"
    id = Column(Integer, primary_key=True)
    appel_id = Column(Integer, ForeignKey("appels_fonds.id"), nullable=False)
    lot_id = Column(Integer, ForeignKey("lots.id"), nullable=False)
    montant_charges = Column(Numeric(12, 2), default=0.0)
    montant_fonds_travaux = Column(Numeric(12, 2), default=0.0)

    appel = relationship("AppelFonds", back_populates="parts")
    lot = relationship("Lot")

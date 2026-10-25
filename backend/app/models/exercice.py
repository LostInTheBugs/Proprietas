from sqlalchemy import Boolean, Column, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import relationship
from app.core.database import Base


class Exercice(Base):
    __tablename__ = "exercices"
    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False)
    annee = Column(Integer, nullable=False, index=True)
    cloture = Column(Boolean, default=False)
    # Date de l'AG qui a approuvé les comptes de l'exercice. La clôture ne vaut PAS approbation :
    # l'art. 19-2 ne vise les restes dus des exercices précédents qu'« après approbation des comptes ».
    comptes_approuves_le = Column(Date, nullable=True)

    copropriete = relationship("Copropriete", back_populates="exercices")
    budget_lines = relationship("BudgetLine", back_populates="exercice", cascade="all, delete-orphan")
    appels = relationship("AppelFonds", back_populates="exercice", cascade="all, delete-orphan",
                          foreign_keys="AppelFonds.exercice_id")
    mouvements = relationship("Mouvement", back_populates="exercice")


class BudgetLine(Base):
    __tablename__ = "budget_lines"
    id = Column(Integer, primary_key=True)
    exercice_id = Column(Integer, ForeignKey("exercices.id"), nullable=False)
    libelle = Column(String, nullable=False)
    montant = Column(Numeric(12, 2), default=0.0)
    # "generale" = répartie entre tous les lots par tantièmes
    # "speciale" = frais spécifiques (répartie entre lots concernés, gérée manuellement)
    type_repartition = Column(String, default="generale")

    exercice = relationship("Exercice", back_populates="budget_lines")

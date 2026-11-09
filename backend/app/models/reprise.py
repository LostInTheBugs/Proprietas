"""Reprise de l'historique : états de fin d'exercice saisis à la mise en place de l'application.

Un état dit, pour chaque lot, ce que le copropriétaire devait au 31 décembre d'une année,
ventilé par exercice d'origine (l'art. 19-2 distingue les exercices approuvés des autres).
L'état validé le plus ancien est la base (il génère les appels « Reprise de solde ») ; les
états validés plus récents sont des points de contrôle (voir services/reprise.py).
"""
from datetime import datetime

from sqlalchemy import (Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String,
                        UniqueConstraint)
from sqlalchemy.orm import relationship

from app.core.database import Base


class EtatReprise(Base):
    __tablename__ = "etats_reprise"
    __table_args__ = (UniqueConstraint("copropriete_id", "date", name="uq_etats_reprise_copro_date"),)

    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)              # toujours un 31 décembre
    valide = Column(Boolean, nullable=False, default=False)
    valide_le = Column(DateTime, nullable=True)
    commentaire = Column(String, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.now)
    # Soldes bancaires à la date de l'état (facultatifs, NULL = non saisi) : compte du syndicat et
    # compte du fonds de travaux. Ils contrôlent les opérations saisies entre deux états et donnent
    # le solde de départ de la trésorerie (base).
    solde_banque = Column(Numeric(12, 2), nullable=True)
    solde_banque_fonds = Column(Numeric(12, 2), nullable=True)

    lignes = relationship("EtatRepriseLigne", back_populates="etat", cascade="all, delete-orphan",
                          order_by="EtatRepriseLigne.id")


class EtatRepriseLigne(Base):
    __tablename__ = "etats_reprise_lignes"
    __table_args__ = (UniqueConstraint("etat_id", "lot_id", "exercice_origine",
                                       name="uq_etats_reprise_lignes_lot_exercice"),)

    id = Column(Integer, primary_key=True)
    etat_id = Column(Integer, ForeignKey("etats_reprise.id", ondelete="CASCADE"), nullable=False, index=True)
    lot_id = Column(Integer, ForeignKey("lots.id"), nullable=False)
    # Copropriétaire à la date de l'état (la dette est personnelle) ; NULL = compte supprimé.
    proprietaire_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    exercice_origine = Column(Integer, nullable=False)
    # Restant dû (négatif = crédit du copropriétaire).
    montant_charges = Column(Numeric(12, 2), nullable=False, default=0)
    montant_fonds_travaux = Column(Numeric(12, 2), nullable=False, default=0)

    etat = relationship("EtatReprise", back_populates="lignes")
    lot = relationship("Lot")

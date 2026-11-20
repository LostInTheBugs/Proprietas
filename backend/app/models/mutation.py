"""Vente d'un lot (mutation) : services/mutations.py (demande de Fred, 20/11/2026).

La mutation porte sur un ensemble (lot principal et ses annexes non séparables). À sa date, le décompte
du lot repart pour l'acquéreur ; ce qui était exigible jusque-là reste au compte du vendeur
(décret n° 67-223 du 17 mars 1967, art. 6-2).
"""
from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String

from sqlalchemy.orm import relationship

from app.core.database import Base


class Mutation(Base):
    __tablename__ = "mutations"
    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False, index=True)
    lot_id = Column(Integer, ForeignKey("lots.id", ondelete="CASCADE"), nullable=False, index=True)  # lot principal
    date_acte = Column(Date, nullable=False)               # date de la vente (acte authentique)
    vendeur_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acquereur_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    vendeur_nom = Column(String, nullable=False, default="")       # gardés si un compte est supprimé
    acquereur_nom = Column(String, nullable=False, default="")
    notaire = Column(String, nullable=False, default="")           # étude, adresse, référence du dossier
    notifiee_le = Column(Date, nullable=True)              # notification du transfert (décret 1967, art. 6)
    avis_mutation_le = Column(Date, nullable=True)         # avis de mutation reçu (loi 1965, art. 20)
    opposition_le = Column(Date, nullable=True)            # opposition formée par le syndic (art. 20)
    notes = Column(String, nullable=False, default="")
    creee_le = Column(DateTime, nullable=False)

    lot = relationship("Lot")
    vendeur = relationship("User", foreign_keys=[vendeur_id])
    acquereur = relationship("User", foreign_keys=[acquereur_id])

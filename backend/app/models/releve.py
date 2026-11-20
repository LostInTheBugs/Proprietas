"""Lignes des relevés bancaires importés (services/releves.py ; demande de Fred, 20/11/2026).

Une ligne = une opération vue par la banque, sur le compte du syndicat ou celui du fonds de travaux.
Le rapprochement y relie les opérations saisies dans Proprietas (`Mouvement.releve_ligne_id`) : une
seule, ou plusieurs (paiement d'un copropriétaire réparti entre ses lots, charges et fonds de travaux).
Une ligne sans équivalent devient une opération à compléter, ou est mise de côté (`ignoree`).
"""
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import relationship

from app.core.database import Base


class LigneReleve(Base):
    __tablename__ = "releve_lignes"
    __table_args__ = (UniqueConstraint("copropriete_id", "compte", "empreinte", name="uq_releve_lignes_empreinte"),)
    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False, index=True)
    compte = Column(String, nullable=False)                 # syndicat | fonds_travaux
    date = Column(Date, nullable=False)
    libelle = Column(String, nullable=False, default="")
    montant = Column(Numeric(12, 2), nullable=False)        # crédit > 0, débit < 0
    # Identifiant de la banque (FITID de l'OFX) ou empreinte date/montant/libellé : un relevé réimporté
    # (ou deux relevés qui se chevauchent) n'ajoute pas deux fois la même opération.
    empreinte = Column(String, nullable=False)
    fichier = Column(String, nullable=False, default="")
    importe_le = Column(DateTime, nullable=False)
    ignoree = Column(Boolean, nullable=False, default=False, server_default=text("false"))

    mouvements = relationship("Mouvement", back_populates="releve_ligne")

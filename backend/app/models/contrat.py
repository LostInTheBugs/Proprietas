from sqlalchemy import Column, Integer, Numeric, String, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base


class Contrat(Base):
    """Contrat de la copropriété (énergie, assurance, entretien…)."""
    __tablename__ = "contrats"

    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False)
    libelle = Column(String, nullable=False)
    type = Column(String, default="autres")  # energie, assurance, entretien, telecom, nettoyage, securite, autres
    reference = Column(String, default="")  # n° de contrat / client
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)  # fournisseur / assureur
    date_debut = Column(String, default="")  # YYYY-MM-DD
    date_fin = Column(String, default="")  # YYYY-MM-DD (échéance, vide = durée indéterminée)
    montant = Column(Numeric(12, 2), default=0.0)
    periode = Column(String, default="annuel")  # mensuel, trimestriel, annuel, ponctuel
    renouvellement_auto = Column(Boolean, default=False)
    notes = Column(Text, default="")

    copropriete = relationship("Copropriete")
    contact = relationship("Contact")

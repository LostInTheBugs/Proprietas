from sqlalchemy import Boolean, Column, Integer, Numeric, String, ForeignKey, Date, text
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
    # Contrat et facture (document) rattachés ; supprimer l'un ou l'autre délie le mouvement.
    contrat_id = Column(Integer, ForeignKey("contrats.id", ondelete="SET NULL"), nullable=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    # Avances (services/avances.py) : personne (compte de la copropriété) qui a payé de sa poche
    # (dépense « payée par »), à qui la copropriété rembourse (dépense de catégorie « avance ») ou dont
    # l'avance est déduite des charges (encaissement sur son lot). hors_banque : n'est pas passé par le
    # compte bancaire de la copropriété (dépense payée par une personne, déduction).
    avance_par_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    hors_banque = Column(Boolean, nullable=False, default=False, server_default=text("false"))

    copropriete = relationship("Copropriete")
    exercice = relationship("Exercice", back_populates="mouvements")
    lot = relationship("Lot")
    appel = relationship("AppelFonds")
    avance_par = relationship("User", foreign_keys=[avance_par_id])

    @property
    def avance_par_nom(self) -> str:
        """Nom de la personne de l'avance (vue Pydantic MouvementOut)."""
        u = self.avance_par
        return (u.nom_complet or u.email) if u is not None else ""

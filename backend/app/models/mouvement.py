from sqlalchemy import Boolean, Column, Integer, Numeric, String, ForeignKey, Date, DateTime, text
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
    # Factures à payer (services/factures.py) : dépense saisie à la date de la facture (charge de
    # l'exercice), pas encore réglée. Réglée plus tard : `paye_le` est la date du paiement, celle que
    # retient la banque. Rappels aux syndics 7 jours avant l'échéance et après elle.
    # Dépense commune répartie par une clé (charges spéciales, services/cles.py) ; NULL : charges générales.
    cle_id = Column(Integer, ForeignKey("cles_repartition.id"), nullable=True)
    a_payer = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    echeance = Column(Date, nullable=True)
    paye_le = Column(Date, nullable=True)
    rappel_avant_le = Column(DateTime, nullable=True)
    rappel_retard_le = Column(DateTime, nullable=True)
    # Rapprochement bancaire (services/releves.py) : ligne du relevé où la banque montre cette opération.
    releve_ligne_id = Column(Integer, ForeignKey("releve_lignes.id", ondelete="SET NULL"), nullable=True, index=True)

    copropriete = relationship("Copropriete")
    exercice = relationship("Exercice", back_populates="mouvements")
    lot = relationship("Lot")
    appel = relationship("AppelFonds")
    avance_par = relationship("User", foreign_keys=[avance_par_id])
    cle = relationship("CleRepartition")
    releve_ligne = relationship("LigneReleve", back_populates="mouvements")

    @property
    def cle_nom(self) -> str:
        """Nom de la clé de répartition (vue Pydantic MouvementOut) ; « » : charges générales."""
        return self.cle.nom if self.cle is not None else ""

    @property
    def avance_par_nom(self) -> str:
        """Nom de la personne de l'avance (vue Pydantic MouvementOut)."""
        u = self.avance_par
        return (u.nom_complet or u.email) if u is not None else ""

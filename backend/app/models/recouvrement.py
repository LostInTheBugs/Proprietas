"""Actes de recouvrement : mise en demeure, frais, article 19-2, étapes amiables/judiciaires.

Journal additif par lot (traçabilité de la procédure). Le statut du dossier n'est
jamais stocké : il est recalculé à la lecture depuis ces actes + le solde du lot
(voir services/recouvrement.py).
"""
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class ActeRecouvrement(Base):
    __tablename__ = "actes_recouvrement"

    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False)
    lot_id = Column(Integer, ForeignKey("lots.id"), nullable=False)
    # Propriétaire concerné = un COMPTE UTILISATEUR (nom historique conservé,
    # FK vers users.id). NULL = compte supprimé (l'acte survit, délié).
    personne_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # mise_en_demeure | frais | activation_19_2 | conciliation | commissaire_justice | tribunal | note
    type = Column(String, nullable=False)
    date_acte = Column(DateTime, default=datetime.now)  # date de saisie dans l'app
    date_envoi = Column(Date, nullable=True)  # date d'envoi / de l'étape (fait générateur)
    mode_envoi = Column(String, default="")  # lre | lrar | email | remise
    reference = Column(String, default="")  # n° de LRE / AR / référence de l'acte
    montant = Column(Float, default=0.0)  # frais : montant ; MD : principal réclamé
    libelle = Column(String, default="")
    details_json = Column(Text, default="")  # snapshot décompte (MD) / lignes (19-2)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    lot = relationship("Lot")
    # foreign_keys explicite : la table a DEUX FK vers users (personne_id,
    # created_by_id) — sans quoi SQLAlchemy ne peut pas choisir la jointure.
    personne = relationship("User", foreign_keys=[personne_id])

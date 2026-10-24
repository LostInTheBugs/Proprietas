from sqlalchemy import Column, Integer, String, ForeignKey, Date, Text, DateTime, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base


class AG(Base):
    __tablename__ = "ags"
    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False)
    date = Column(Date, nullable=False)
    heure = Column(String, default="")  # ex: "18:30"
    type_ag = Column(String, default="annuelle")  # annuelle | extraordinaire | consultation_ecrite
    statut = Column(String, default="projet")  # projet | convoquee | terminee
    lieu = Column(String, default="")
    notes = Column(Text, default="")
    # Rappel automatique de la convocation (cron)
    rappel_jours = Column(Integer, default=21)  # e-mail d'information auto N jours avant (0 = désactivé)
    convocation_envoyee = Column(Boolean, default=False)  # déjà convoquée (manuelle ou auto)

    copropriete = relationship("Copropriete", back_populates="ags")
    resolutions = relationship("Resolution", back_populates="ag", cascade="all, delete-orphan")
    creneaux = relationship("AgCreneau", back_populates="ag", cascade="all, delete-orphan")
    invitations = relationship("Invitation", back_populates="ag", cascade="all, delete-orphan")


class AgCreneau(Base):
    """Créneau de date/heure proposé pour une AG (sondage type Doodle)."""
    __tablename__ = "ag_creneaux"
    id = Column(Integer, primary_key=True)
    ag_id = Column(Integer, ForeignKey("ags.id"), nullable=False)
    debut = Column(DateTime, nullable=False)
    fin = Column(DateTime, nullable=True)

    ag = relationship("AG", back_populates="creneaux")
    votes = relationship("AgCreneauVote", back_populates="creneau", cascade="all, delete-orphan")


class AgCreneauVote(Base):
    __tablename__ = "ag_creneau_votes"
    id = Column(Integer, primary_key=True)
    creneau_id = Column(Integer, ForeignKey("ag_creneaux.id"), nullable=False)
    lot_id = Column(Integer, ForeignKey("lots.id"), nullable=False)
    dispo = Column(Boolean, default=True)

    creneau = relationship("AgCreneau", back_populates="votes")
    lot = relationship("Lot")


class Resolution(Base):
    __tablename__ = "resolutions"
    id = Column(Integer, primary_key=True)
    ag_id = Column(Integer, ForeignKey("ags.id"), nullable=False)
    numero = Column(Integer, default=1)
    libelle = Column(String, nullable=False)
    texte = Column(Text, default="")
    # art24 = majorité des voix exprimées (présents + représentés + correspondance)
    # art25 = majorité des voix de tous les copropriétaires
    # art26 = majorité des 2/3 des voix de tous les copropriétaires
    # unanimite = tous les copropriétaires
    majorite = Column(String, default="art24")
    # Objet de la décision : autre | budget | approbation_comptes. Le budget prévisionnel et
    # l'approbation des comptes sont exclus de la consultation écrite (art. 41-12).
    nature = Column(String, nullable=False, default="autre", server_default="autre")
    statut = Column(String, default="a_voter")  # a_voter | adoptee | rejetee
    # Second vote immédiat (passerelles art. 25-1 / 26-1) : id de la résolution
    # dont celle-ci est le second vote. NULL pour une résolution « normale ».
    second_vote_de_id = Column(Integer, ForeignKey("resolutions.id", ondelete="CASCADE"), nullable=True)

    ag = relationship("AG", back_populates="resolutions")
    votes = relationship("Vote", back_populates="resolution", cascade="all, delete-orphan")


class Vote(Base):
    __tablename__ = "votes"
    id = Column(Integer, primary_key=True)
    resolution_id = Column(Integer, ForeignKey("resolutions.id"), nullable=False)
    lot_id = Column(Integer, ForeignKey("lots.id"), nullable=False)
    voix = Column(String, default="null")  # pour | contre | abstention | null

    resolution = relationship("Resolution", back_populates="votes")
    lot = relationship("Lot")

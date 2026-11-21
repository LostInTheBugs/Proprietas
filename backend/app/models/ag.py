from sqlalchemy import JSON, Column, Integer, String, ForeignKey, Date, Text, DateTime, Boolean, UniqueConstraint, text
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
    # Réunion en ligne (loi n° 65-557, art. 17-1 A) : lien https de la visioconférence (Teams, Zoom, Jitsi…).
    lien_visio = Column(String, nullable=False, default="", server_default="")

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
    # Exercice dont la résolution approuve les comptes (nature « approbation_comptes » seulement).
    exercice_id = Column(Integer, ForeignKey("exercices.id", ondelete="SET NULL"), nullable=True)
    statut = Column(String, default="a_voter")  # a_voter | adoptee | rejetee
    # Second vote immédiat (passerelles art. 25-1 / 26-1) : id de la résolution
    # dont celle-ci est le second vote. NULL pour une résolution « normale ».
    second_vote_de_id = Column(Integer, ForeignKey("resolutions.id", ondelete="CASCADE"), nullable=True)
    # Résolution amendée en séance : un vote « pour » par correspondance compte comme défaillant
    # (loi n° 65-557, art. 17-1 A ; services/correspondance.py).
    amendee = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    # Dépenses d'une partie de l'immeuble ou d'un équipement réparties par une clé : seuls les copropriétaires
    # concernés votent, avec les millièmes de la clé (loi n° 65-557, art. 24, dernier alinéa ; services/cles.py).
    cle_id = Column(Integer, ForeignKey("cles_repartition.id", ondelete="SET NULL"), nullable=True)
    # Désignation du syndic / élection du conseil syndical (nature « syndic » | « conseil ») : durée en mois et
    # comptes désignés ; adoptée, la résolution enregistre le mandat (services/mandats.py).
    mandat_mois = Column(Integer, nullable=True)
    mandat_personnes = Column(JSON, nullable=True)
    # Vote en direct pendant l'AG (services/vote_en_ligne.py) : ouvert par le syndic, puis clos (résultat calculé).
    vote_ouvert_le = Column(DateTime, nullable=True)
    vote_clos_le = Column(DateTime, nullable=True)

    ag = relationship("AG", back_populates="resolutions")
    cle = relationship("CleRepartition")
    votes = relationship("Vote", back_populates="resolution", cascade="all, delete-orphan")


class Vote(Base):
    __tablename__ = "votes"
    id = Column(Integer, primary_key=True)
    resolution_id = Column(Integer, ForeignKey("resolutions.id"), nullable=False)
    lot_id = Column(Integer, ForeignKey("lots.id"), nullable=False)
    voix = Column(String, default="null")  # pour | contre | abstention | null

    resolution = relationship("Resolution", back_populates="votes")
    lot = relationship("Lot")


class AgReponse(Base):
    """Réponse d'un copropriétaire à l'information sur l'AG : présence, absence, pouvoir (services/presences.py).

    Une ligne par copropriétaire et par AG. `mandataire_id` : copropriétaire qui le représente (pouvoir,
    loi n° 65-557, art. 22). `source` : lien de l'e-mail, compte connecté ou saisie du syndic.
    """
    __tablename__ = "ag_reponses"
    __table_args__ = (UniqueConstraint("ag_id", "personne_id", name="uq_ag_reponses_ag_personne"),)
    id = Column(Integer, primary_key=True)
    ag_id = Column(Integer, ForeignKey("ags.id", ondelete="CASCADE"), nullable=False, index=True)
    personne_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reponse = Column(String, nullable=False)          # present | pouvoir | absent | incertain
    mandataire_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    repondu_le = Column(DateTime, nullable=False)
    source = Column(String, nullable=False, default="lien")   # lien | compte | syndic
    pouvoir_recu_le = Column(DateTime, nullable=True)         # pouvoir signé remis au syndic

    personne = relationship("User", foreign_keys=[personne_id])
    mandataire = relationship("User", foreign_keys=[mandataire_id])


class VoteCorrespondance(Base):
    """Vote par correspondance reçu par le syndic (formulaire de l'arrêté du 2 juillet 2020) : une ligne par
    copropriétaire et par résolution (services/correspondance.py)."""
    __tablename__ = "votes_correspondance"
    __table_args__ = (UniqueConstraint("resolution_id", "personne_id", name="uq_votes_correspondance_res_personne"),)
    id = Column(Integer, primary_key=True)
    ag_id = Column(Integer, ForeignKey("ags.id", ondelete="CASCADE"), nullable=False, index=True)
    resolution_id = Column(Integer, ForeignKey("resolutions.id", ondelete="CASCADE"), nullable=False)
    personne_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    voix = Column(String, nullable=False, default="")      # pour | contre | abstention | "" (case non cochée)
    recu_le = Column(Date, nullable=False)                  # date de réception par le syndic

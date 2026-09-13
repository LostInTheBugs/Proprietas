from sqlalchemy import Column, Integer, String, Boolean, Float
from sqlalchemy.orm import relationship
from app.core.database import Base


class Copropriete(Base):
    __tablename__ = "coproprietes"
    id = Column(Integer, primary_key=True)
    nom = Column(String, nullable=False)
    adresse = Column(String, default="")
    ville = Column(String, default="")
    code_postal = Column(String, default="")
    annee_construction = Column(Integer, nullable=True)
    regles_pays = Column(String, default="FR")
    devise = Column(String, default="EUR")
    # Fonds de travaux (obligatoire en France depuis la loi ALUR,
    # plus d'exemption < 10 lots : taux minimum 5 % du budget prévisionnel)
    fonds_travaux_actif = Column(Boolean, default=True)
    fonds_travaux_taux_pct = Column(Float, default=5.0)
    fonds_travaux_compte = Column(String, default="")
    compte_bancaire_separe = Column(String, default="")
    # Envoi des convocations par email
    smtp_host = Column(String, default="")
    smtp_port = Column(Integer, default=587)
    smtp_user = Column(String, default="")
    smtp_password = Column(String, default="")
    email_expediteur = Column(String, default="")
    frontend_url = Column(String, default="")
    # Relances automatiques (cron)
    relance_auto = Column(Boolean, default=False)
    relance_frequence = Column(String, default="hebdo")  # hebdo | mensuel
    relance_jour = Column(Integer, default=1)  # 1-7 (hebdo, lundi=1) ou 1-28 (mensuel)
    relance_heure = Column(String, default="09:00")  # "HH:00" ou "HH:30"
    relance_minimum = Column(Float, default=0.0)  # seuil : ne relancer que les soldes > ce montant
    # Double authentification exigée des comptes : off | syndic | all.
    # Défini à la création de la copropriété (COPRO_TOTP_DEFAULT_POLICY) ;
    # les bases existantes restent en « off » après migration.
    totp_policy = Column(String, default="off")
    # Taux de l'intérêt légal (%) pour les intérêts de retard de recouvrement —
    # arrêté semestriel, saisi par le syndic (jamais deviné par l'app).
    taux_legal_retard = Column(Float, default=0.0)
    notes = Column(String, default="")

    users = relationship("User", back_populates="copropriete")
    lots = relationship("Lot", back_populates="copropriete", cascade="all, delete-orphan")
    personnes = relationship("Personne", back_populates="copropriete", cascade="all, delete-orphan")
    exercices = relationship("Exercice", back_populates="copropriete", cascade="all, delete-orphan")
    ags = relationship("AG", back_populates="copropriete", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="copropriete", cascade="all, delete-orphan")
    entreteins = relationship("Entretien", back_populates="copropriete", cascade="all, delete-orphan")

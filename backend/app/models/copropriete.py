from sqlalchemy import Column, DateTime, Integer, Numeric, String, Boolean, text
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.crypto import TexteChiffre


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
    fonds_travaux_taux_pct = Column(Numeric(7, 4), default=5.0)
    fonds_travaux_compte = Column(String, default="")
    compte_bancaire_separe = Column(String, default="")
    # Envoi des convocations par email
    smtp_host = Column(String, default="")
    smtp_port = Column(Integer, default=587)
    smtp_user = Column(String, default="")
    # Chiffré en base (core.crypto.TexteChiffre) ; le code lit et écrit du clair.
    smtp_password = Column(TexteChiffre, default="")
    email_expediteur = Column(String, default="")
    frontend_url = Column(String, default="")
    # Drive de la copropriété (core/drive.py) : ses fichiers sur un serveur WebDAV. "" = pas de drive.
    drive_type = Column(String, default="")          # "" | webdav | google (drive_password = jeton OAuth)
    drive_url = Column(String, default="")
    drive_user = Column(String, default="")
    drive_password = Column(TexteChiffre, default="")   # chiffré en base, comme le mot de passe SMTP
    drive_dossier = Column(String, default="")       # ex. « Proprietas/Résidence Les Tilleuls »
    # Sauvegarde automatique de la copropriété sur son drive (services/drive_sauvegarde.py).
    drive_sauvegarde_auto = Column(Boolean, default=False)
    drive_sauvegarde_password = Column(TexteChiffre, default="")   # mot de passe des archives, chiffré en base
    drive_sauvegarde_derniere = Column(DateTime, nullable=True)     # dernière sauvegarde réussie
    drive_sauvegarde_tentative = Column(DateTime, nullable=True)    # dernier essai automatique
    drive_sauvegarde_erreur = Column(String, default="")            # raison du dernier échec ("" : aucun)
    # Relances automatiques (cron)
    relance_auto = Column(Boolean, default=False)
    relance_frequence = Column(String, default="hebdo")  # hebdo | mensuel
    relance_jour = Column(Integer, default=1)  # 1-7 (hebdo, lundi=1) ou 1-28 (mensuel)
    relance_heure = Column(String, default="09:00")  # "HH:00" ou "HH:30"
    relance_minimum = Column(Numeric(12, 2), default=0.0)  # seuil : ne relancer que les soldes > ce montant
    # Double authentification exigée des comptes : off | syndic | all.
    # Défini à la création de la copropriété (COPRO_TOTP_DEFAULT_POLICY) ;
    # les bases existantes restent en « off » après migration.
    totp_policy = Column(String, default="off")
    # Connexions (Réglages → Sécurité, services/connexions.py). Par défaut, seule la dernière
    # connexion est gardée ; l'historique garde toutes les connexions réussies et ratées.
    connexions_historique = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    # Blocage après des échecs d'affilée : temporaire au seuil (et à chaque multiple), définitif
    # (jusqu'au déblocage) au seuil définitif (0 : jamais). Les comptes avec double authentification
    # n'y sont soumis que si verrouillage_avec_2fa.
    verrouillage_actif = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    verrouillage_seuil = Column(Integer, nullable=False, default=5, server_default=text("5"))
    verrouillage_minutes = Column(Integer, nullable=False, default=15, server_default=text("15"))
    verrouillage_seuil_definitif = Column(Integer, nullable=False, default=10, server_default=text("10"))
    verrouillage_avec_2fa = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    # Taux de l'intérêt légal (%) pour les intérêts de retard de recouvrement —
    # arrêté semestriel, saisi par le syndic (jamais deviné par l'app).
    taux_legal_retard = Column(Numeric(7, 4), default=0.0)
    notes = Column(String, default="")

    users = relationship("User", back_populates="copropriete")
    lots = relationship("Lot", back_populates="copropriete", cascade="all, delete-orphan")
    exercices = relationship("Exercice", back_populates="copropriete", cascade="all, delete-orphan")
    ags = relationship("AG", back_populates="copropriete", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="copropriete", cascade="all, delete-orphan")
    entreteins = relationship("Entretien", back_populates="copropriete", cascade="all, delete-orphan")

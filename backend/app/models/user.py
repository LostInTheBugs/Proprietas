from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text, text
from sqlalchemy.orm import relationship
from app.core.database import Base


class UserCopro(Base):
    """Liaison user ↔ copropriété (un user peut gérer plusieurs immeubles)."""
    __tablename__ = "user_coproprietes"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False)
    principale = Column(Boolean, default=False)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    prenom = Column(String, default="")
    nom = Column(String, nullable=False)
    role = Column(String, default="membre")  # syndic | membre
    is_demo = Column(Boolean, default=False)  # compte de démonstration (n'ouvre pas/ne ferme pas l'inscription)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=True)
    # Coordonnées du copropriétaire (maintenues par lui-même dans Réglages →
    # Mes informations, ou par le syndic) — l'adresse sert notamment à la mise
    # en demeure. Ces champs vivaient sur la fiche « Lots & occupants » avant
    # le passage au modèle « zéro fiche » (le compte EST la personne).
    adresse = Column(String, default="", server_default="")
    telephone = Column(String, default="", server_default="")
    # Colonne historique : ancien lien vers une fiche « Lots & occupants »
    # (le modèle est passé aux comptes : plus aucun code ne la lit/écrit).
    personne_id = Column(Integer, ForeignKey("personnes.id"), nullable=True)
    # Colonne historique : ancienne case « propriétaire occupant » du compte —
    # l'occupation se règle désormais lot par lot (lots.statut_occupation).
    est_occupant = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    # Double authentification (TOTP, RFC 6238) — secret CHIFFRÉ, codes de secours HACHÉS.
    totp_secret = Column(Text, default="")
    totp_enabled = Column(Boolean, default=False)
    recovery_hashes = Column(Text, default="[]")
    # Version des jetons : incrémentée par « déconnecter tous mes appareils » —
    # les JWT portent la version et sont refusés dès qu'elle ne correspond plus.
    token_version = Column(Integer, default=0)
    # Préférence d'affichage : "light" | "dark" | "system" (voir Réglages → Apparence).
    theme = Column(String, default="system")
    # Dernière connexion (alertes « nouvelle connexion »)
    last_login_at = Column(DateTime, nullable=True)
    last_login_ip = Column(String, default="")
    last_login_ua = Column(String, default="")
    copropriete = relationship("Copropriete", back_populates="users")
    coproprietes = relationship(
        "UserCopro", backref="user", cascade="all, delete-orphan",
        foreign_keys="UserCopro.user_id",
    )

    @property
    def two_factor_enabled(self) -> bool:
        """Vue Pydantic (UserOut) : la 2FA est-elle activée pour ce compte ?"""
        return bool(self.totp_enabled)

    @property
    def nom_complet(self) -> str:
        """Prénom + nom (pour les affichages « humains »)."""
        return f"{self.prenom or ''} {self.nom or ''}".strip()

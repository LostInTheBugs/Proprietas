from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
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
    nom = Column(String, nullable=False)
    role = Column(String, default="membre")  # syndic | membre
    is_demo = Column(Boolean, default=False)  # compte de démonstration (n'ouvre pas/ne ferme pas l'inscription)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=True)
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

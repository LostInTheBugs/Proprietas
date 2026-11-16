from sqlalchemy import Column, Integer, Numeric, String, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.crypto import TexteChiffre


class Smtp(Base):
    __tablename__ = "smtp_server"
    id = Column(Integer, primary_key=True)
    nom = Column(String, nullable=False)
    # Envoi des convocations par email
    smtp_host = Column(String, default="")
    smtp_port = Column(Integer, default=587)
    smtp_user = Column(String, default="")
    # Chiffré en base (core.crypto.TexteChiffre) ; le code lit et écrit du clair.
    smtp_password = Column(TexteChiffre, default="")
    email_expediteur = Column(String, default="")
    frontend_url = Column(String, default="")

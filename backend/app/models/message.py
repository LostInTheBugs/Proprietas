"""Messages groupés du syndic aux copropriétaires (services/messages.py ; demande de Fred, 20/11/2026)."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.core.database import Base


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False, index=True)
    auteur_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    envoye_le = Column(DateTime, nullable=False)
    sujet = Column(String, nullable=False)
    corps = Column(Text, nullable=False, default="")
    cible = Column(String, nullable=False, default="tous")    # tous | cle | selection
    cle_nom = Column(String, nullable=False, default="")       # clé visée (gardée si la clé est supprimée)
    destinataires = Column(Text, nullable=False, default="")  # noms des destinataires, séparés par « ; »
    nb_envoyes = Column(Integer, nullable=False, default=0)
    erreurs = Column(Text, nullable=False, default="")         # « Nom : motif », une par ligne

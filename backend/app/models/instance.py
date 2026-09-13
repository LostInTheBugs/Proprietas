"""État de l'instance : mode d'exposition, URL publique, dernier diagnostic.

Ligne unique (id=1), créée à la demande au premier accès. Distinct de la
copropriété : c'est le niveau « où vit l'application et comment elle est exposée ».
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.database import Base


class InstanceState(Base):
    __tablename__ = "instance_state"
    id = Column(Integer, primary_key=True)
    mode = Column(String, default="local")  # local | vps | maison
    public_url = Column(String, default="")  # ex. https://copro.exemple.fr
    # Première requête vue depuis internet (détection middleware, sans configuration)
    first_external_at = Column(DateTime, nullable=True)
    # Dernier diagnostic d'exposition : date + résultats (JSON, liste d'items)
    last_check_at = Column(DateTime, nullable=True)
    last_check_json = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

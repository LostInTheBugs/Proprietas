from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base


class Lot(Base):
    __tablename__ = "lots"
    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False)
    numero = Column(String, nullable=False)
    designation = Column(String, default="")  # ex: "Appartement T3"
    type = Column(String, default="appartement")  # appartement | cave | parking | commerce | autre
    tantiemes = Column(Integer, default=0)  # millièmes (total = 1000, stocké en millièmes)
    surface_m2 = Column(Float, nullable=True)
    # PROPRIÉTAIRE = un COMPTE UTILISATEUR (modèle « zéro fiche » : les fiches
    # « Lots & occupants » ont été remplacées par les comptes — la colonne
    # garde son nom, la FK pointe désormais users.id).
    proprietaire_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Colonne historique (l'occupant était une fiche personne nommée) — PLUS
    # utilisée : voir statut_occupation (RGPD, aucun nom de locataire).
    occupant_id = Column(Integer, ForeignKey("personnes.id"), nullable=True)
    # Occupation du lot : "" = non renseigné | "occupant" | "loue" | "vacant".
    # « occupant » = le propriétaire occupe son logement (« propriétaire
    # occupant ») — il le déclare pour chacun de ses lots (Réglages → Mes lots).
    statut_occupation = Column(String, nullable=False, default="", server_default="")
    notes = Column(String, default="")
    # Lot non séparable : annexe (cave, garage…) rattachée à un lot principal, vendue et suivie
    # avec lui (services/ensembles.py). NULL = lot séparé.
    lot_principal_id = Column(Integer, ForeignKey("lots.id", ondelete="SET NULL"), nullable=True)

    copropriete = relationship("Copropriete", back_populates="lots")
    proprietaire = relationship("User", foreign_keys=[proprietaire_id])

from sqlalchemy import Column, Integer, String, ForeignKey, Date
from sqlalchemy.orm import relationship
from app.core.database import Base


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    copropriete_id = Column(Integer, ForeignKey("coproprietes.id"), nullable=False)
    categorie = Column(String, default="autre")
    # contrat | assurance | facture | devis | diagnostic | pv | convocation | autre
    libelle = Column(String, nullable=False)
    # Nom du fichier dans le stockage de l'instance, ou chemin relatif au dossier du drive.
    fichier = Column(String, default="")
    # "" : stockage de l'instance (dossier local ou S3) ; "drive" : drive de la copropriété.
    emplacement = Column(String, default="", nullable=False, server_default="")
    # Taille (octets) et empreinte SHA-256 du contenu, relevées au dépôt ou au déplacement : elles
    # permettent de retrouver sur le drive un fichier renommé ou déplacé. Vides pour les anciens documents.
    taille = Column(Integer, nullable=True)
    empreinte = Column(String, nullable=True)
    date_ajout = Column(Date, nullable=False)

    copropriete = relationship("Copropriete", back_populates="documents")

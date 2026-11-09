"""Espace de stockage (Réglages).

- Syndic : place prise par les documents de la copropriété active.
- Administrateur de l'instance : en plus, disque du serveur (total, utilisé, libre), taille de la
  base et place prise par tous les documents de l'instance.
- Stockage S3 : pas d'« espace libre » pour les documents (un bucket n'a pas de taille fixe) ;
  seulement l'espace utilisé. Le disque du serveur reste affiché (base, images Docker).
"""
import os
import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import is_instance_admin, require_syndic
from app.core.stockage import StockageLocal
from app.models.document import Document
from app.models.user import User
from app.routes.copro import get_or_create_copro

router = APIRouter(prefix="/api/stockage", tags=["stockage"])


def _stockage():
    # Même stockage que les documents (les tests et la configuration le remplacent au même endroit).
    from app.routes import documents
    return documents._stockage()


def _taille_base(db: Session) -> int | None:
    """Taille de la base en octets (PostgreSQL : pg_database_size ; SQLite : pages × taille de page)."""
    try:
        if db.get_bind().dialect.name == "postgresql":
            return int(db.execute(text("SELECT pg_database_size(current_database())")).scalar())
        if db.get_bind().dialect.name == "sqlite":
            pages = db.execute(text("PRAGMA page_count")).scalar()
            taille = db.execute(text("PRAGMA page_size")).scalar()
            return int(pages) * int(taille)
    except Exception:  # noqa: BLE001 — information facultative
        return None
    return None


def _disque(st) -> dict | None:
    """Disque du serveur qui porte les documents (local) ou l'application (S3)."""
    chemin = st.dossier if isinstance(st, StockageLocal) else "."
    chemin = chemin if os.path.isdir(chemin) else "."
    try:
        u = shutil.disk_usage(chemin)
    except OSError:
        return None
    return {"total": u.total, "utilise": u.total - u.free, "libre": u.free}


@router.get("")
def espace(db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    st = _stockage()
    resultat = {"stockage": "local" if isinstance(st, StockageLocal) else "s3",
                "documents": {"nombre": 0, "octets": 0, "introuvables": 0},
                "instance": None, "erreur": ""}
    copro = get_or_create_copro(db, user)
    docs = db.query(Document.fichier).filter(Document.copropriete_id == copro.id).all()
    resultat["documents"]["nombre"] = len(docs)
    try:
        for (fichier,) in docs:
            if not fichier:
                continue
            taille = st.taille(fichier)
            if taille is None:
                resultat["documents"]["introuvables"] += 1
            else:
                resultat["documents"]["octets"] += taille
    except Exception as e:  # noqa: BLE001 — stockage injoignable, nom invalide : on l'affiche
        resultat["documents"]["octets"] = None
        resultat["erreur"] = f"Stockage des documents indisponible : {e}"[:300]

    if is_instance_admin(user):
        total = 0
        try:
            for nom in st.lister():
                total += st.taille(nom) or 0
        except Exception as e:  # noqa: BLE001
            total = None
            resultat["erreur"] = resultat["erreur"] or f"Stockage des documents indisponible : {e}"[:300]
        resultat["instance"] = {"disque": _disque(st), "base_octets": _taille_base(db),
                                "documents_octets": total}
    return resultat

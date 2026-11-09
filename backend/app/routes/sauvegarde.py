"""Sauvegarde de la copropriété active : export (archive ZIP) et import (nouvelle copropriété).

Réservé au syndic ; export et import inscrits au journal d'audit. Règles : services/sauvegarde.py.
"""
import os
import tempfile
import unicodedata
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core import audit
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import require_syndic
from app.models.user import User
from app.routes.copro import get_or_create_copro
from app.services import sauvegarde as svc

router = APIRouter(prefix="/api/sauvegarde", tags=["sauvegarde"])
BLOC = 1024 * 1024


def _stockage():
    # Même stockage que les documents (les tests et la configuration le remplacent au même endroit).
    from app.routes import documents
    return documents._stockage()


@router.get("/export")
def exporter(request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    fd, chemin = tempfile.mkstemp(suffix=".zip")
    try:
        with os.fdopen(fd, "wb") as sortie:
            manifest = svc.exporter(db, copro, _stockage(), sortie)
    except Exception:
        os.unlink(chemin)
        raise
    audit.enregistrer(db, "sauvegarde_export", user=user, copro_id=copro.id, request=request,
                      detail=f"{manifest['nb_comptes']} compte(s), {manifest['nb_documents']} document(s)")
    db.commit()
    ascii_ = unicodedata.normalize("NFKD", copro.nom).encode("ascii", "ignore").decode()
    nom = "".join(c if c.isalnum() else "_" for c in ascii_).strip("_") or "copropriete"
    return FileResponse(chemin, media_type="application/zip",
                        filename=f"Sauvegarde_{nom}_{date.today().isoformat()}.zip",
                        background=BackgroundTask(os.unlink, chemin))


@router.post("/import")
async def importer(request: Request, fichier: UploadFile = File(...), db: Session = Depends(get_db),
                   user: User = Depends(require_syndic)):
    max_bytes = int(get_settings().import_max_mb * 1024 * 1024)
    taille = 0
    with tempfile.TemporaryFile() as tmp:
        while bloc := await fichier.read(BLOC):
            taille += len(bloc)
            if taille > max_bytes:
                raise HTTPException(413, f"Sauvegarde trop volumineuse (maximum {get_settings().import_max_mb:g} Mo).")
            tmp.write(bloc)
        tmp.seek(0)
        resultat = svc.importer(db, tmp, user, _stockage())
    audit.enregistrer(db, "sauvegarde_import", user=user, copro_id=resultat["copropriete_id"], request=request,
                      detail=(f"« {resultat['nom']} » : {resultat['comptes_crees']} compte(s) créé(s), "
                              f"{resultat['comptes_existants']} existant(s), {resultat['documents']} document(s)"))
    db.commit()
    return resultat

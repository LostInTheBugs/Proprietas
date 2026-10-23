import os
import uuid
from datetime import date
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_user, require_syndic
from app.models.user import User
from app.models.document import Document
from app.core.scoping import get_owned
from app.routes.copro import get_or_create_copro
from app.schemas import DocumentOut

router = APIRouter(prefix="/api/documents", tags=["documents"])
settings = get_settings()

CATEGORIES = {"contrat", "assurance", "facture", "devis", "diagnostic", "pv", "convocation", "autre"}
# Liste blanche d'extensions acceptées à l'upload (refus des exécutables, etc.)
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx", ".xls", ".xlsx", ".odt", ".ods"}


def _safe_download_name(libelle: str) -> str:
    """Assainit un libellé libre pour l'en-tête Content-Disposition.

    Élimine les caractères de contrôle (CR/LF…) et les guillemets, qui
    permettraient une injection d'en-tête HTTP.
    """
    safe = "".join(c for c in (libelle or "") if c.isprintable() and c not in '"\\')
    return safe.strip() or "document"


def _fichier_path(doc: Document) -> str:
    """Chemin absolu du fichier stocké, garanti sous upload_dir."""
    base = os.path.abspath(settings.upload_dir)
    path = os.path.abspath(os.path.join(base, doc.fichier))
    if not path.startswith(base + os.sep):
        raise HTTPException(404, "Fichier manquant sur le serveur")
    return path


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    return db.query(Document).filter(Document.copropriete_id == copro.id).order_by(Document.date_ajout.desc()).all()


@router.post("", response_model=DocumentOut)
async def upload_document(
    categorie: str = Form("autre"),
    libelle: str = Form(...),
    fichier: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_syndic),
):
    ext = os.path.splitext(fichier.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Type de fichier refusé (autorisé : {', '.join(sorted(ALLOWED_EXTENSIONS))})")
    if len(content) > max_bytes:
        raise HTTPException(413, f"Fichier trop volumineux (maximum {settings.upload_max_mb:g} Mo)")
    if categorie not in CATEGORIES:
        categorie = "autre"
    copro = get_or_create_copro(db, user)
    os.makedirs(settings.upload_dir, exist_ok=True)
    nom_stocke = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(settings.upload_dir, nom_stocke)
    content = await fichier.read()
    max_bytes = int(settings.upload_max_mb * 1024 * 1024)
    with open(path, "wb") as f:
        f.write(content)
    doc = Document(
        copropriete_id=copro.id,
        categorie=categorie,
        libelle=libelle,
        fichier=nom_stocke,
        date_ajout=date.today(),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{doc_id}/download")
def download_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    doc = get_owned(db, Document, doc_id, copro, label="Document")
    path = _fichier_path(doc)
    if not os.path.exists(path):
        raise HTTPException(404, "Fichier manquant sur le serveur")
    return FileResponse(path, filename=_safe_download_name(doc.libelle))


@router.delete("/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    doc = get_owned(db, Document, doc_id, copro, label="Document")
    path = _fichier_path(doc)
    if os.path.exists(path):
        os.remove(path)
    db.delete(doc)
    db.commit()
    return {"ok": True}

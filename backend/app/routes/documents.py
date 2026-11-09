import logging
import mimetypes
import os
import tempfile
import uuid
from datetime import date
from urllib.parse import quote
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import get_current_user, require_syndic
from app.models.user import User
from app.models.document import Document
from app.models.mouvement import Mouvement
from app.core.scoping import get_owned
from app.core.stockage import NomInvalide, StockageIndisponible, StockageLocal, stockage_depuis
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


def _stockage():
    """Stockage configuré (local ou S3). Lu à chaque appel : les tests le remplacent."""
    return stockage_depuis(settings)


def _indisponible(e: StockageIndisponible) -> HTTPException:
    logging.getLogger("uvicorn.error").error("%s", e)
    return HTTPException(503, "Stockage des documents indisponible, réessayez plus tard")


def _content_disposition(nom: str) -> str:
    """Même forme que FileResponse : filename="…" en ASCII, filename*=utf-8'' sinon."""
    q = quote(nom)
    return f"attachment; filename*=utf-8''{q}" if q != nom else f'attachment; filename="{nom}"'


@router.get("", response_model=list[DocumentOut])
def list_documents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    return db.query(Document).filter(Document.copropriete_id == copro.id).order_by(Document.date_ajout.desc()).all()


BLOC_UPLOAD = 1024 * 1024       # 1 Mo


@router.post("", response_model=DocumentOut)
async def upload_document(
    categorie: str = Form("autre"),
    libelle: str = Form(...),
    fichier: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_syndic),
):
    if categorie not in CATEGORIES:
        categorie = "autre"
    ext = os.path.splitext(fichier.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Type de fichier refusé (autorisé : {', '.join(sorted(ALLOWED_EXTENSIONS))})")
    copro = get_or_create_copro(db, user)
    nom_stocke = f"{uuid.uuid4().hex}{ext}"
    # Réception PAR BLOCS dans un fichier temporaire, avec arrêt dès que la limite est
    # franchie : jamais le fichier entier en mémoire (un gros envoi saturait la RAM d'un
    # petit serveur avant d'être refusé), et rien n'atteint le stockage avant d'être accepté.
    max_bytes = int(settings.upload_max_mb * 1024 * 1024)
    taille = 0
    with tempfile.SpooledTemporaryFile(max_size=BLOC_UPLOAD) as tmp:
        while bloc := await fichier.read(BLOC_UPLOAD):
            taille += len(bloc)
            if taille > max_bytes:
                raise HTTPException(413, f"Fichier trop volumineux (maximum {settings.upload_max_mb:g} Mo)")
            tmp.write(bloc)
        tmp.seek(0)
        try:
            _stockage().enregistrer(nom_stocke, tmp)
        except StockageIndisponible as e:
            raise _indisponible(e) from e
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
    stockage = _stockage()
    nom_affiche = _safe_download_name(doc.libelle)
    try:
        if isinstance(stockage, StockageLocal):
            path = stockage.chemin(doc.fichier)
            if not os.path.isfile(path):
                raise HTTPException(404, "Fichier manquant sur le serveur")
            return FileResponse(path, filename=nom_affiche)
        taille = stockage.taille(doc.fichier)
        if taille is None:
            raise HTTPException(404, "Fichier manquant sur le serveur")
        blocs = stockage.lire_par_blocs(doc.fichier)
    except NomInvalide:
        raise HTTPException(404, "Fichier manquant sur le serveur")
    except StockageIndisponible as e:
        raise _indisponible(e) from e
    return StreamingResponse(
        blocs,
        media_type=mimetypes.guess_type(doc.fichier)[0] or "application/octet-stream",
        headers={"Content-Disposition": _content_disposition(nom_affiche),
                 "Content-Length": str(taille)},
    )


@router.delete("/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    doc = get_owned(db, Document, doc_id, copro, label="Document")
    try:
        _stockage().supprimer(doc.fichier)
    except NomInvalide:
        pass                    # nom forgé : aucun fichier légitime à supprimer, la fiche part
    except StockageIndisponible as e:
        raise _indisponible(e) from e
    # Les mouvements rattachés à ce document (facture) restent, déliés.
    db.query(Mouvement).filter(Mouvement.document_id == doc.id).update({Mouvement.document_id: None},
                                                                       synchronize_session=False)
    db.delete(doc)
    db.commit()
    return {"ok": True}

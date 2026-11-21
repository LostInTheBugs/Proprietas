import hashlib
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
from app.core import drive
from app.core.scoping import get_owned
from app.core.stockage import NomInvalide, StockageIndisponible, StockageLocal, stockage_depuis
from app.routes.copro import get_or_create_copro
from app.schemas import DocumentOut
from app.services import drive_fichiers

router = APIRouter(prefix="/api/documents", tags=["documents"])
settings = get_settings()

CATEGORIES = {"contrat", "assurance", "facture", "devis", "diagnostic", "pv", "convocation", "autre"}
# Liste blanche d'extensions acceptées à l'upload (refus des exécutables, etc.)
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx", ".xls", ".xlsx", ".odt", ".ods"}
# Signature des premiers octets de chaque type accepté : le contenu doit correspondre à l'extension (un
# exécutable ou une page HTML renommés en .pdf sont refusés). Office récent et OpenDocument sont des archives
# ZIP ; .doc et .xls, des fichiers OLE2.
_ZIP, _OLE = (b"PK\x03\x04",), (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",)
SIGNATURES = {".pdf": (b"%PDF-",), ".png": (b"\x89PNG\r\n\x1a\n",), ".jpg": (b"\xff\xd8\xff",),
              ".jpeg": (b"\xff\xd8\xff",), ".docx": _ZIP, ".xlsx": _ZIP, ".odt": _ZIP, ".ods": _ZIP,
              ".doc": _OLE, ".xls": _OLE}


def contenu_conforme(ext: str, debut: bytes) -> bool:
    """Les premiers octets du fichier correspondent-ils à son extension ?"""
    return any(debut.startswith(s) for s in SIGNATURES.get(ext, ()))


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


def _drive(copro):
    """Drive de la copropriété s'il est branché (et autorisé sur l'instance), sinon None."""
    if not settings.drive_actif:
        return None
    return drive.stockage_drive(copro, settings.drive_reseau_local)


def stockage_du_document(copro, doc):
    """Où est le fichier de ce document : drive de la copropriété ou stockage de l'instance."""
    if doc.emplacement == "drive":
        st = _drive(copro)
        if st is None:
            raise StockageIndisponible("Ce fichier est sur le drive de la copropriété, qui n'est plus branché.")
        return st
    return _stockage()


def _peut_attendre(db: Session, taille: int) -> bool:
    """Dépôt mettable en attente du drive : option active et plafond de l'instance respecté."""
    plafond = settings.drive_attente_mo * 1024 * 1024
    return plafond > 0 and drive_fichiers.octets_en_attente(db) + taille <= plafond


def _indisponible(e: StockageIndisponible, sur_le_drive: bool = False, attente: bool = False) -> HTTPException:
    logging.getLogger("uvicorn.error").error("%s", e)
    if sur_le_drive:
        # Le message vient de core/drive.py : il ne contient ni mot de passe ni adresse interne.
        suite = (" Le serveur ne peut pas garder ce document en attente (place réservée pleine) : redéposez-le plus tard."
                 if attente and settings.drive_attente_mo > 0 else "")
        return HTTPException(503, f"Drive de la copropriété indisponible : {e}{suite}")
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
    # Réception PAR BLOCS dans un fichier temporaire, avec arrêt dès que la limite est
    # franchie : jamais le fichier entier en mémoire (un gros envoi saturait la RAM d'un
    # petit serveur avant d'être refusé), et rien n'atteint le stockage avant d'être accepté.
    max_bytes = int(settings.upload_max_mb * 1024 * 1024)
    taille = 0
    empreinte = hashlib.sha256()     # avec la taille : retrouver le fichier s'il est renommé sur le drive
    with tempfile.SpooledTemporaryFile(max_size=BLOC_UPLOAD) as tmp:
        while bloc := await fichier.read(BLOC_UPLOAD):
            taille += len(bloc)
            if taille > max_bytes:
                raise HTTPException(413, f"Fichier trop volumineux (maximum {settings.upload_max_mb:g} Mo)")
            empreinte.update(bloc)
            tmp.write(bloc)
        tmp.seek(0)
        if not contenu_conforme(ext, tmp.read(16)):
            raise HTTPException(400, f"Le contenu du fichier ne correspond pas à son extension {ext} : "
                                     "enregistrez-le de nouveau au bon format.")
        tmp.seek(0)
        sur_le_drive = False
        try:
            st = _drive(copro)
            sur_le_drive = st is not None
            if sur_le_drive:
                # Drive branché : c'est là que va le fichier, sous un nom lisible, dans le dossier
                # de sa catégorie (« Factures/2026-11-16 Facture d'électricité.pdf »).
                nom_stocke = st.nom_libre(drive.DOSSIERS[categorie], drive.nom_lisible(date.today(), libelle, ext))
            else:
                st, nom_stocke = _stockage(), f"{uuid.uuid4().hex}{ext}"
            st.enregistrer(nom_stocke, tmp)
            emplacement = "drive" if sur_le_drive else ""
        except StockageIndisponible as e:
            if not (sur_le_drive and _peut_attendre(db, taille)):
                raise _indisponible(e, sur_le_drive, attente=sur_le_drive) from e
            # Drive injoignable : le fichier est gardé sur le serveur et rangé sur le drive dès son retour.
            logging.getLogger("uvicorn.error").warning("Dépôt mis en attente du drive : %s", e)
            tmp.seek(0)
            nom_stocke, emplacement = f"{uuid.uuid4().hex}{ext}", drive_fichiers.ATTENTE
            try:
                _stockage().enregistrer(nom_stocke, tmp)
            except StockageIndisponible as e2:
                raise _indisponible(e2) from e2
    doc = Document(
        copropriete_id=copro.id,
        categorie=categorie,
        libelle=libelle,
        fichier=nom_stocke,
        emplacement=emplacement,
        taille=taille,
        empreinte=empreinte.hexdigest(),
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
    nom_affiche = _safe_download_name(doc.libelle)
    sur_le_drive = doc.emplacement == "drive"
    try:
        stockage = stockage_du_document(copro, doc)
        if isinstance(stockage, StockageLocal):
            path = stockage.chemin(doc.fichier)
            if not os.path.isfile(path):
                raise HTTPException(404, "Fichier manquant sur le serveur")
            return FileResponse(path, filename=nom_affiche)
        taille = stockage.taille(doc.fichier)
        if taille is None:
            raise HTTPException(404, "Fichier introuvable sur le drive : il a été renommé, déplacé ou supprimé."
                                if sur_le_drive else "Fichier manquant sur le serveur")
        blocs = stockage.lire_par_blocs(doc.fichier)
    except NomInvalide:
        raise HTTPException(404, "Fichier manquant sur le serveur")
    except StockageIndisponible as e:
        raise _indisponible(e, sur_le_drive) from e
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
    # Justificatif d'une avance (dépense payée par une personne) : il doit rester (services/avances.py).
    avance = (db.query(Mouvement).filter(Mouvement.document_id == doc.id, Mouvement.avance_par_id.isnot(None),
                                         Mouvement.type == "depense", Mouvement.categorie != "avance").first())
    if avance is not None:
        raise HTTPException(409, f"Ce document justifie l'avance « {avance.libelle} » du {avance.date:%d/%m/%Y} : "
                                 "il ne peut pas être supprimé.")
    try:
        if doc.fichier and doc.emplacement == "drive" and _drive(copro) is None:
            # Aucun drive branché (copropriété restaurée d'une sauvegarde, par exemple) : il n'y a rien
            # à supprimer d'ici, la fiche peut partir ; le fichier, s'il existe, reste sur le drive.
            pass
        elif doc.fichier:
            stockage_du_document(copro, doc).supprimer(doc.fichier)
    except NomInvalide:
        pass                    # nom forgé : aucun fichier légitime à supprimer, la fiche part
    except StockageIndisponible as e:
        # Drive branché mais injoignable : on ne supprime pas la fiche d'un fichier qui resterait.
        raise _indisponible(e, doc.emplacement == "drive") from e
    # Les mouvements rattachés à ce document (facture) restent, déliés.
    db.query(Mouvement).filter(Mouvement.document_id == doc.id).update({Mouvement.document_id: None},
                                                                       synchronize_session=False)
    db.delete(doc)
    db.commit()
    return {"ok": True}

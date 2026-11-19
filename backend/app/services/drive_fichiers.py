"""Fichiers d'une copropriété entre le serveur et son drive (core/drive.py).

- déplacer vers le drive les fichiers déposés avant son branchement, et l'inverse (rapatrier), par
  LOTS : un appel traite quelques fichiers puis rend la main, l'écran recommence tant qu'il en reste ;
- vérifier le drive : fichiers attendus introuvables, fichiers du drive rattachés à aucun document ;
- retrouver un fichier renommé ou déplacé sur le drive, par son contenu (taille + empreinte SHA-256
  relevées au dépôt ou au déplacement), ou le relier à la main ;
- ranger sur le drive les dépôts « en attente » (drive injoignable au moment du dépôt, option
  COPRO_DRIVE_ATTENTE_MO) : le planificateur réessaie toutes les 5 minutes.

Ordre d'un déplacement : copie → contrôle de la taille → fiche mise à jour (commit) → suppression de
l'original. Une panne au milieu ne perd jamais un fichier : au pire il reste un double.
"""
from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import time
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core import drive
from app.core.stockage import BLOC, NomInvalide, StockageIndisponible
from app.models.document import Document

LOT_FICHIERS = 10            # fichiers par appel
LOT_SECONDES = 40            # durée visée d'un appel
RETROUVER_OCTETS = 200 * 1024 * 1024     # volume relu au plus par recherche
ATTENTE = "attente"          # documents.emplacement : sur le serveur, en attente du drive
log = logging.getLogger("uvicorn.error")


def _copier(source, nom: str, tmp) -> tuple[int, str]:
    """Copie le fichier dans `tmp` ; renvoie (taille, empreinte SHA-256)."""
    h, taille = hashlib.sha256(), 0
    for bloc in source.lire_par_blocs(nom):
        h.update(bloc)
        taille += len(bloc)
        tmp.write(bloc)
    tmp.seek(0)
    return taille, h.hexdigest()


def _documents(db: Session, copro, emplacement: str):
    return (db.query(Document).filter(Document.copropriete_id == copro.id, Document.emplacement == emplacement,
                                      Document.fichier != "").order_by(Document.id))


def _transferer(db: Session, copro, source, destination, depuis: str, vers: str, nom_destination) -> dict:
    """Déplace un lot de fichiers de `source` vers `destination` ; bilan du lot et reste à faire."""
    debut = time.monotonic()
    bilan = {"deplaces": 0, "introuvables": [], "restants": 0}
    ignores = set()
    for doc in _documents(db, copro, depuis).all():
        if bilan["deplaces"] >= LOT_FICHIERS or time.monotonic() - debut > LOT_SECONDES:
            break
        ancien = doc.fichier
        try:
            if not source.existe(ancien):
                raise FileNotFoundError(ancien)
            with tempfile.SpooledTemporaryFile(max_size=BLOC) as tmp:
                taille, empreinte = _copier(source, ancien, tmp)
                nouveau = nom_destination(doc)
                destination.enregistrer(nouveau, tmp)
            if destination.taille(nouveau) != taille:
                destination.supprimer(nouveau)
                raise StockageIndisponible(f"Copie incomplète de « {doc.libelle} » : rien n'a été modifié.")
        except (FileNotFoundError, NomInvalide):
            # Fichier absent à l'origine : la fiche reste telle quelle, signalée.
            bilan["introuvables"].append({"id": doc.id, "libelle": doc.libelle})
            ignores.add(doc.id)
            continue
        doc.fichier, doc.emplacement, doc.taille, doc.empreinte = nouveau, vers, taille, empreinte
        db.commit()
        try:
            source.supprimer(ancien)
        except (StockageIndisponible, NomInvalide):
            pass            # un double reste à l'origine : sans conséquence pour l'application
        bilan["deplaces"] += 1
    bilan["restants"] = _documents(db, copro, depuis).filter(Document.id.notin_(ignores or {-1})).count()
    return bilan


def deplacer_vers_drive(db: Session, copro, instance, st_drive) -> dict:
    """Un lot de fichiers du serveur vers le drive, rangés comme les nouveaux dépôts."""
    def nom(doc):
        ext = os.path.splitext(doc.fichier)[1].lower()[:10]
        return st_drive.nom_libre(drive.DOSSIERS.get(doc.categorie, drive.DOSSIERS["autre"]),
                                  drive.nom_lisible(doc.date_ajout, doc.libelle, ext))
    return _transferer(db, copro, instance, st_drive, "", "drive", nom)


def ranger_en_attente(db: Session, copro, instance, st_drive) -> dict:
    """Un lot de dépôts « en attente du drive » (drive injoignable au moment du dépôt) rangés sur le drive."""
    def nom(doc):
        ext = os.path.splitext(doc.fichier)[1].lower()[:10]
        return st_drive.nom_libre(drive.DOSSIERS.get(doc.categorie, drive.DOSSIERS["autre"]),
                                  drive.nom_lisible(doc.date_ajout, doc.libelle, ext))
    return _transferer(db, copro, instance, st_drive, ATTENTE, "drive", nom)


def octets_en_attente(db: Session, copro=None) -> int:
    """Taille des fichiers en attente du drive, pour une copropriété ou pour toute l'instance."""
    q = db.query(func.coalesce(func.sum(Document.taille), 0)).filter(Document.emplacement == ATTENTE)
    if copro is not None:
        q = q.filter(Document.copropriete_id == copro.id)
    return int(q.scalar() or 0)


def run_ranger_en_attente(db: Session) -> dict:
    """Passage du planificateur : range sur leur drive les dépôts en attente, copropriété par copropriété."""
    from app.core.config import get_settings
    from app.models.copropriete import Copropriete
    from app.routes import documents      # stockage de l'instance, au même endroit que les documents
    stats = {"ranges": 0, "en_attente": 0}
    reglages = get_settings()
    ids = [i for (i,) in db.query(Document.copropriete_id).filter(Document.emplacement == ATTENTE).distinct()]
    for copro in db.query(Copropriete).filter(Copropriete.id.in_(ids or [-1])).all():
        try:
            st = drive.stockage_drive(copro, reglages.drive_reseau_local)
            if st is None:
                continue
            for _ in range(100):
                bilan = ranger_en_attente(db, copro, documents._stockage(), st)
                stats["ranges"] += bilan["deplaces"]
                if not bilan["restants"] or not bilan["deplaces"]:
                    break
        except Exception as e:  # noqa: BLE001 — drive toujours injoignable : on réessaiera au prochain passage
            db.rollback()
            log.info("Copropriété %s : dépôts en attente du drive non rangés (%s)", copro.id, e)
    stats["en_attente"] = db.query(Document).filter(Document.emplacement == ATTENTE).count()
    if stats["ranges"]:
        log.info("Dépôts en attente rangés sur le drive : %s", stats)
    return stats


def rapatrier(db: Session, copro, instance, st_drive) -> dict:
    """Un lot de fichiers du drive vers le serveur (avant de débrancher le drive)."""
    def nom(doc):
        return f"{uuid.uuid4().hex}{os.path.splitext(doc.fichier)[1].lower()[:10]}"
    return _transferer(db, copro, st_drive, instance, "drive", "", nom)


def verifier(db: Session, copro, st_drive) -> dict:
    """État du drive : documents dont le fichier manque, fichiers rattachés à aucun document."""
    sur_le_drive = st_drive.lister_arbre()
    docs = _documents(db, copro, "drive").all()
    attendus = {d.fichier for d in docs}
    return {
        "verifies": len(docs),
        "introuvables": [{"id": d.id, "libelle": d.libelle, "categorie": d.categorie, "fichier": d.fichier,
                          "retrouvable": bool(d.empreinte)} for d in docs if d.fichier not in sur_le_drive],
        # Le dossier des sauvegardes (services/drive_sauvegarde.py) n'est pas un dossier de documents.
        "non_rattaches": [{"chemin": c, "taille": t} for c, t in sorted(sur_le_drive.items())
                          if c not in attendus and not c.startswith("Sauvegardes/")],
    }


def _empreinte(st_drive, chemin: str) -> str:
    h = hashlib.sha256()
    for bloc in st_drive.lire_par_blocs(chemin):
        h.update(bloc)
    return h.hexdigest()


def retrouver(db: Session, copro, st_drive) -> dict:
    """Relie chaque document introuvable au fichier du drive qui a exactement son contenu.

    Candidats : fichiers non rattachés de même taille ; le contenu est relu pour comparer l'empreinte.
    Un document n'est relié que si UN SEUL fichier correspond.
    """
    etat = verifier(db, copro, st_drive)
    libres = {f["chemin"]: f["taille"] for f in etat["non_rattaches"]}
    empreintes: dict[str, str] = {}
    budget = RETROUVER_OCTETS
    relies = []
    for doc in _documents(db, copro, "drive").filter(Document.id.in_([i["id"] for i in etat["introuvables"]] or [-1])):
        if not doc.empreinte or doc.taille is None:
            continue
        trouves = []
        for chemin in [c for c, t in libres.items() if t == doc.taille]:
            if chemin not in empreintes:
                if budget < doc.taille:
                    continue
                budget -= doc.taille
                try:
                    empreintes[chemin] = _empreinte(st_drive, chemin)
                except (FileNotFoundError, NomInvalide):
                    empreintes[chemin] = ""
            if empreintes[chemin] == doc.empreinte:
                trouves.append(chemin)
        if len(trouves) == 1:
            relies.append({"id": doc.id, "libelle": doc.libelle, "ancien": doc.fichier, "nouveau": trouves[0]})
            doc.fichier = trouves[0]
            del libres[trouves[0]]
    db.commit()
    return {"relies": relies, **verifier(db, copro, st_drive)}


def relier(db: Session, copro, st_drive, doc: Document, chemin: str) -> None:
    """Rattache à la main un fichier du drive à ce document. ValueError (message pour le syndic) sinon."""
    try:
        drive.valider_chemin(chemin)
    except NomInvalide:
        raise ValueError("Chemin invalide.") from None
    if doc.emplacement != "drive":
        raise ValueError("Ce document n'est pas sur le drive.")
    pris = (db.query(Document).filter(Document.copropriete_id == copro.id, Document.emplacement == "drive",
                                      Document.fichier == chemin, Document.id != doc.id).first())
    if pris:
        raise ValueError(f"Ce fichier est déjà celui du document « {pris.libelle} ».")
    taille = st_drive.taille(chemin)
    if taille is None:
        raise ValueError("Ce fichier n'existe pas sur le drive.")
    # Nouveau contenu de référence : c'est le choix du syndic.
    doc.fichier, doc.taille, doc.empreinte = chemin, taille, _empreinte(st_drive, chemin)
    db.commit()

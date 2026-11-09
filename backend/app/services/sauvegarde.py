"""Sauvegarde d'une copropriété : export en archive ZIP, import dans n'importe quelle instance.

Archive (format « proprietas-copropriete », version 1) :
- `manifest.json` : format, version de l'application, date, nom de la copropriété, comptes ;
- `donnees.json` : { table: [lignes] } pour toutes les tables de la copropriété ;
- `documents/<fichier>` : les fichiers déposés (page Documents).

Export : toutes les données liées à la copropriété active, découvertes par les clés étrangères.
Sont exclus : le journal d'audit (propre à l'instance), l'ancienne table `personnes`, le mot de passe
SMTP (chiffré avec la clé du serveur : à ressaisir), et pour les comptes ce qui est propre à
l'instance (administrateur de l'instance, dernières connexions, version des jetons).

Options d'export (choisies à chaque sauvegarde) :
- mot de passe : archive ZIP chiffrée en AES-256 (WinZip AES), lisible aussi avec 7-Zip / WinRAR ;
- données personnelles : NON par défaut. Sans elles, les comptes deviennent « Compte 1 », « Compte 2 »…
  (e-mail @anonyme.invalid, ni mot de passe, ni téléphone, ni adresse, ni 2FA), et les champs qui
  décrivent des personnes sont vidés (notes des lots, messages des relances et invitations, libellé et
  référence des actes de recouvrement, nom des destinataires des PV, identifiant SMTP) ;
- fichiers des documents : NON par défaut (ils contiennent souvent des noms et adresses) ; les fiches
  des documents restent, sans fichier.
Données personnelles ou fichiers exigent un mot de passe (10 caractères minimum).

Import : crée TOUJOURS une nouvelle copropriété (jamais d'écrasement), avec de nouveaux
identifiants ; chaque référence est renumérotée. Un compte dont l'e-mail existe déjà sur
l'instance est réutilisé tel quel (il est seulement rattaché) ; sinon il est créé avec son mot de
passe (haché). Le secret de double authentification n'est gardé que s'il se déchiffre avec la clé
du serveur (même serveur ou même COPRO_SECRET_KEY) ; sinon la double authentification du compte est
désactivée, à réactiver. Les fichiers reçoivent de nouveaux noms. Colonnes ou tables inconnues
(archive plus récente) : ignorées et signalées.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from datetime import date, datetime
from decimal import Decimal

import pyzipper
from fastapi import HTTPException
from sqlalchemy import Boolean, Date, DateTime, Numeric, select
from sqlalchemy.orm import Session

from app.core.crypto import TexteChiffre, dechiffrer_secret
from app.core.database import Base
from app.core.stockage import NomInvalide, StockageIndisponible
from app.core.version import VERSION

FORMAT = "proprietas-copropriete"
VERSION_FORMAT = 1

# Ordre d'export et d'import : chaque table après celles qu'elle référence.
TABLES = [
    "coproprietes", "users", "user_coproprietes", "contacts", "contrats", "lots", "exercices",
    "budget_lines", "etats_reprise", "etats_reprise_lignes", "appels_fonds", "appels_lots", "documents",
    "mouvements", "ags", "ag_creneaux", "ag_creneau_votes", "resolutions", "votes", "invitations",
    "notifications_pv", "carnet_entretien", "travaux", "relances", "actes_recouvrement",
]
# Lignes d'une table : directement par copropriété, ou par leur parent (colonne → table parente).
PAR_PARENT = {
    "budget_lines": ("exercice_id", "exercices"),
    "appels_fonds": ("exercice_id", "exercices"),
    "appels_lots": ("appel_id", "appels_fonds"),
    "etats_reprise_lignes": ("etat_id", "etats_reprise"),
    "ag_creneaux": ("ag_id", "ags"),
    "ag_creneau_votes": ("creneau_id", "ag_creneaux"),
    "resolutions": ("ag_id", "ags"),
    "votes": ("resolution_id", "resolutions"),
    "invitations": ("ag_id", "ags"),
    "notifications_pv": ("ag_id", "ags"),
    "relances": ("lot_id", "lots"),
}
# Colonnes jamais exportées.
EXCLUES = {
    "coproprietes": {"smtp_password"},
    "users": {"is_instance_admin", "token_version", "last_login_at", "last_login_ip", "last_login_ua",
              "personne_id", "copropriete_id"},
}
TABLES_IGNOREES = {"personnes"}   # clés étrangères vers ces tables : mises à NULL à l'import

MDP_MIN = 10
DOMAINE_ANONYME = "anonyme.invalid"   # comptes « Compte N » d'une sauvegarde sans données personnelles
# Sans données personnelles : champs vidés (ils décrivent des personnes).
VIDES_SANS_DONNEES_PERSONNELLES = {
    "coproprietes": ("smtp_user", "email_expediteur"),
    "lots": ("notes",),
    "relances": ("message",),
    "invitations": ("message",),
    "actes_recouvrement": ("libelle", "reference"),
    "notifications_pv": ("reference",),
}


def est_a_completer(email: str | None) -> bool:
    """Compte issu d'une sauvegarde sans données personnelles, pas encore complété."""
    return (email or "").lower().endswith("@" + DOMAINE_ANONYME)


def _anonymiser(donnees: dict) -> None:
    noms = {}
    for n, u in enumerate(sorted(donnees["users"], key=lambda u: u["id"]), 1):
        noms[u["id"]] = f"Compte {n}"
        u.update(email=f"compte-{n}@{DOMAINE_ANONYME}", prenom="", nom=f"Compte {n}", adresse="",
                 telephone="", password_hash="", totp_secret="", totp_enabled=False, recovery_hashes="[]")
    for table, champs in VIDES_SANS_DONNEES_PERSONNELLES.items():
        for ligne in donnees.get(table) or []:
            for champ in champs:
                if champ in ligne:
                    ligne[champ] = ""
    for ligne in donnees.get("notifications_pv") or []:
        ligne["nom"] = noms.get(ligne.get("user_id"), "")


def _table(nom):
    return Base.metadata.tables[nom]


def _vers_json(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _depuis_json(col, v):
    if v is None:
        return None
    t = col.type
    if isinstance(t, DateTime):
        return datetime.fromisoformat(v)
    if isinstance(t, Date):
        return date.fromisoformat(v)
    if isinstance(t, Numeric):
        return Decimal(str(v))
    if isinstance(t, Boolean):
        return bool(v)
    return v


def _cles(table) -> dict[str, str]:
    """Colonne → table référencée (clés étrangères)."""
    return {fk.parent.name: fk.column.table.name for fk in table.foreign_keys}


# ---------------------------------------------------------------- export
def exporter(db: Session, copro, stockage, sortie, *, mot_de_passe: str = "",
             donnees_personnelles: bool = False, fichiers: bool = False) -> dict:
    """Écrit l'archive dans `sortie` (fichier ouvert en écriture binaire) ; renvoie le manifeste."""
    if (donnees_personnelles or fichiers) and not mot_de_passe:
        raise HTTPException(422, "Les données personnelles et les fichiers des documents ne s'exportent "
                                 "qu'avec un mot de passe.")
    if mot_de_passe and len(mot_de_passe) < MDP_MIN:
        raise HTTPException(422, f"Mot de passe trop court ({MDP_MIN} caractères minimum).")
    cid = copro.id
    lignes: dict[str, list[dict]] = {}
    ids: dict[str, set] = {}
    for nom in TABLES:
        if nom == "users":
            continue      # après coup : comptes rattachés ET comptes cités par les données
        t = _table(nom)
        if nom == "coproprietes":
            cond = t.c.id == cid
        elif nom in PAR_PARENT:
            col, parent = PAR_PARENT[nom]
            cond = t.c[col].in_(ids.get(parent) or {-1})
        else:
            cond = t.c.copropriete_id == cid
        rows = [dict(r._mapping) for r in db.execute(select(t).where(cond).order_by(t.c.id))]
        lignes[nom] = rows
        ids[nom] = {r["id"] for r in rows}
    # Comptes : ceux rattachés à la copropriété et ceux que citent les données.
    users_ids = set()
    for nom, rows in lignes.items():
        for col, cible in _cles(_table(nom)).items():
            if cible == "users":
                users_ids |= {r[col] for r in rows if r.get(col)}
    tu = _table("users")
    lignes["users"] = [dict(r._mapping) for r in db.execute(select(tu).where(tu.c.id.in_(users_ids or {-1})))]

    donnees = {}
    for nom in TABLES:
        exclues = EXCLUES.get(nom, set())
        donnees[nom] = [{k: _vers_json(v) for k, v in r.items() if k not in exclues} for r in lignes[nom]]
    if not donnees_personnelles:
        _anonymiser(donnees)
    if not fichiers:
        for d in donnees["documents"]:
            d["fichier"] = ""

    manifest = {
        "format": FORMAT, "version_format": VERSION_FORMAT, "version_application": VERSION,
        "exporte_le": datetime.now().isoformat(timespec="seconds"),
        "copropriete": copro.nom, "nb_comptes": len(donnees["users"]),
        "nb_documents": len(donnees["documents"]),
        "donnees_personnelles": donnees_personnelles, "fichiers_documents": fichiers,
        "protegee": bool(mot_de_passe),
    }
    options = {"encryption": pyzipper.WZ_AES} if mot_de_passe else {}
    with pyzipper.AESZipFile(sortie, "w", compression=pyzipper.ZIP_DEFLATED, **options) as z:
        if mot_de_passe:
            z.setpassword(mot_de_passe.encode("utf-8"))
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        z.writestr("donnees.json", json.dumps(donnees, ensure_ascii=False))
        for d in donnees["documents"]:
            nom = d.get("fichier") or ""
            try:
                if not nom or not stockage.existe(nom):
                    continue
                with z.open(f"documents/{nom}", "w") as f:
                    for bloc in stockage.lire_par_blocs(nom):
                        f.write(bloc)
            except NomInvalide:
                continue
    return manifest


# ---------------------------------------------------------------- import
def importer(db: Session, contenu: io.BufferedIOBase, importeur, stockage, mot_de_passe: str = "") -> dict:
    try:
        z = pyzipper.AESZipFile(contenu)
        protegee = any(i.flag_bits & 0x1 for i in z.infolist())
        if protegee and not mot_de_passe:
            raise HTTPException(422, "Cette sauvegarde est protégée par un mot de passe : saisissez-le.")
        if mot_de_passe:
            z.setpassword(mot_de_passe.encode("utf-8"))
        manifest = json.loads(z.read("manifest.json"))
        donnees = json.loads(z.read("donnees.json"))
    except RuntimeError:             # pyzipper : mot de passe incorrect
        raise HTTPException(422, "Mot de passe incorrect.")
    except (zipfile.BadZipFile, pyzipper.BadZipFile, KeyError, ValueError):
        raise HTTPException(422, "Ce fichier n'est pas une sauvegarde Proprietas (archive .zip attendue).")
    if manifest.get("format") != FORMAT:
        raise HTTPException(422, "Ce fichier n'est pas une sauvegarde de copropriété Proprietas.")
    if int(manifest.get("version_format", 0)) > VERSION_FORMAT:
        raise HTTPException(422, "Sauvegarde produite par une version plus récente de Proprietas : "
                                 "mettez d'abord cette instance à jour.")
    if len(donnees.get("coproprietes") or []) != 1:
        raise HTTPException(422, "Sauvegarde invalide : elle doit contenir exactement une copropriété.")

    avertissements = []
    inconnues = sorted(set(donnees) - set(TABLES))
    if inconnues:
        avertissements.append(f"Tables ignorées (version plus récente) : {', '.join(inconnues)}.")
    if str(manifest.get("version_application", "")) > VERSION:
        avertissements.append(f"Sauvegarde faite avec la version {manifest.get('version_application')}, "
                              f"plus récente que celle de l'instance ({VERSION}).")

    remap: dict[str, dict[int, int]] = {nom: {} for nom in TABLES}
    differes: list[tuple] = []          # références vers la même table : complétées après coup
    fichiers_ecrits: list[str] = []
    stats = {"comptes_crees": 0, "comptes_existants": 0, "documents": 0, "deuxfa_desactivee": 0,
             "comptes_a_completer": 0}
    # Comptes anonymes : adresse propre à cet import (deux imports de la même sauvegarde ne se mélangent pas).
    jeton = uuid.uuid4().hex[:8]
    colonnes_ignorees = set()
    tu = _table("users")
    try:
        for nom in TABLES:
            t = _table(nom)
            cles = _cles(t)
            for ligne in donnees.get(nom) or []:
                ancien_id = ligne.get("id")
                if nom == "users" and est_a_completer(ligne.get("email")):
                    local = ligne["email"].split("@")[0]
                    ligne = {**ligne, "email": f"{local}.{jeton}@{DOMAINE_ANONYME}"}
                    stats["comptes_a_completer"] += 1
                if nom == "users":
                    existant = db.execute(select(tu.c.id).where(tu.c.email == ligne.get("email"))).first()
                    if existant:
                        remap["users"][ancien_id] = existant[0]
                        stats["comptes_existants"] += 1
                        continue
                valeurs, auto = {}, []
                for k, v in ligne.items():
                    if k == "id":
                        continue
                    if k not in t.c:
                        colonnes_ignorees.add(f"{nom}.{k}")
                        continue
                    col = t.c[k]
                    if isinstance(col.type, TexteChiffre):
                        valeurs[k] = ""
                        continue
                    if k in cles and v is not None:
                        cible = cles[k]
                        if cible in TABLES_IGNOREES or cible not in remap:
                            v = None
                        elif cible == nom:
                            auto.append((k, v))
                            v = None
                        else:
                            v = remap[cible].get(v)
                    valeurs[k] = _depuis_json(col, v)
                if nom == "users":
                    valeurs["copropriete_id"] = remap["coproprietes"].get(
                        next(iter(remap["coproprietes"]), None))
                    valeurs["is_instance_admin"] = False
                    # Secret illisible avec la clé de ce serveur (dechiffrer_secret renvoie "") : 2FA désactivée.
                    if valeurs.get("totp_secret") and not dechiffrer_secret(valeurs["totp_secret"]):
                        valeurs.update(totp_secret="", totp_enabled=False, recovery_hashes="[]")
                        stats["deuxfa_desactivee"] += 1
                    stats["comptes_crees"] += 1
                if nom == "documents" and valeurs.get("fichier"):
                    valeurs["fichier"] = _copier_fichier(z, valeurs["fichier"], stockage, fichiers_ecrits)
                    stats["documents"] += 1
                nouvel_id = db.execute(t.insert().values(**valeurs)).inserted_primary_key[0]
                remap[nom][ancien_id] = nouvel_id
                for k, v in auto:
                    differes.append((nom, nouvel_id, k, v))
        for nom, nid, k, v in differes:
            cible = remap[nom].get(v)
            if cible is not None:
                t = _table(nom)
                db.execute(t.update().where(t.c.id == nid).values(**{k: cible}))
        nouvelle_copro = next(iter(remap["coproprietes"].values()))
        # Nom déjà pris sur l'instance (restauration à côté de l'original) : on le distingue.
        tc = _table("coproprietes")
        nom = donnees["coproprietes"][0].get("nom", "")
        if db.execute(select(tc.c.id).where(tc.c.nom == nom, tc.c.id != nouvelle_copro)).first():
            nom = f"{nom} (importée le {date.today():%d/%m/%Y})"
            db.execute(tc.update().where(tc.c.id == nouvelle_copro).values(nom=nom))
        # L'importeur administre la nouvelle copropriété.
        tuc = _table("user_coproprietes")
        if not db.execute(select(tuc.c.id).where(tuc.c.user_id == importeur.id,
                                                  tuc.c.copropriete_id == nouvelle_copro)).first():
            db.execute(tuc.insert().values(user_id=importeur.id, copropriete_id=nouvelle_copro, principale=False))
        db.flush()
    except Exception:
        for nom in fichiers_ecrits:
            try:
                stockage.supprimer(nom)
            except Exception:
                pass
        raise
    if colonnes_ignorees:
        avertissements.append(f"Colonnes ignorées : {', '.join(sorted(colonnes_ignorees))}.")
    return {"copropriete_id": nouvelle_copro, "nom": nom,
            **stats, "avertissements": avertissements}


def _copier_fichier(z: zipfile.ZipFile, ancien: str, stockage, ecrits: list[str]) -> str:
    """Copie documents/<ancien> sous un nouveau nom ; nom vide si le fichier manque dans l'archive."""
    membre = f"documents/{ancien}"
    if membre not in z.namelist():
        return ""
    ext = os.path.splitext(ancien)[1].lower()[:10]
    nouveau = f"{uuid.uuid4().hex}{ext}"
    try:
        # Copie intermédiaire : le flux d'un membre ZIP ne se rembobine pas (S3 peut relire).
        with z.open(membre) as f, tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as tmp:
            shutil.copyfileobj(f, tmp)
            tmp.seek(0)
            stockage.enregistrer(nouveau, tmp)
    except StockageIndisponible as e:
        raise HTTPException(503, f"Stockage des documents indisponible : {e}") from e
    ecrits.append(nouveau)
    return nouveau


# ---------------------------------------------------------------- comptes à compléter
def fusionner_compte(db: Session, ancien_id: int, nouveau_id: int, copro_id: int) -> None:
    """Le compte anonyme `ancien_id` est en fait le compte existant `nouveau_id` : toutes ses
    références passent au compte existant (lots, PV, actes…), puis le compte anonyme est supprimé."""
    tuc = _table("user_coproprietes")
    for t in Base.metadata.sorted_tables:
        if t.name in ("users", "user_coproprietes"):
            continue
        for fk in t.foreign_keys:
            if fk.column.table.name == "users":
                col = fk.parent.name
                db.execute(t.update().where(t.c[col] == ancien_id).values(**{col: nouveau_id}))
    deja = db.execute(select(tuc.c.id).where(tuc.c.user_id == nouveau_id, tuc.c.copropriete_id == copro_id)).first()
    if not deja:
        db.execute(tuc.insert().values(user_id=nouveau_id, copropriete_id=copro_id, principale=False))
    db.execute(tuc.delete().where(tuc.c.user_id == ancien_id))
    tu = _table("users")
    db.execute(tu.delete().where(tu.c.id == ancien_id))

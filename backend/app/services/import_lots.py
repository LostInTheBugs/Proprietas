"""Import des lots depuis un tableur : CSV, Excel (.xlsx) ou LibreOffice (.ods) — demande de Fred, 20/11/2026.

- Une ligne d'en-tête ; colonnes dans n'importe quel ordre, casse et accents ignorés :
    numero (requis) ; tantiemes (requis) ; designation ; type ; surface ; proprietaire (e-mail d'un compte
    de la copropriété) ; et une colonne par clé de répartition : « clé : Bâtiment A » (ou « cle:Bâtiment A »),
    millièmes du lot pour cette clé (vide ou 0 : non concerné).
- Un lot existant (même numéro) est mis à jour, un nouveau est créé ; les lots absents du fichier ne
  changent pas. Une clé nommée dans l'en-tête est créée si elle n'existe pas ; ses millièmes sont ceux du
  fichier pour les lots du fichier, ceux d'avant pour les autres.
- Refus en bloc : à la moindre erreur, rien n'est écrit ; chaque erreur cite sa ligne (en-tête : ligne 1).
  « Vérifier » (simulation) montre ce qui serait fait, ou la liste des erreurs.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from xml.etree import ElementTree

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.cle import CleLot, CleRepartition
from app.models.lot import Lot
from app.models.user import User, UserCopro
from app.services.country_rules import TYPES_LOT

MAX_LIGNES = 2000
MAX_OCTETS = 5 * 1024 * 1024
CONNUES = {"numero", "tantiemes", "designation", "type", "surface", "proprietaire"}
ALIAS = {"lot": "numero", "n": "numero", "no": "numero", "numero_de_lot": "numero", "milliemes": "tantiemes",
         "quote_part": "tantiemes", "surface_m2": "surface", "email": "proprietaire", "e_mail": "proprietaire",
         "proprietaire_email": "proprietaire"}
PREFIXE_CLE = re.compile(r"^\s*cl[eé]\s*:\s*(.+)$", re.IGNORECASE)


def _cle(texte: str) -> str:
    t = unicodedata.normalize("NFKD", (texte or "").strip().lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return ALIAS.get(t, t)


# ---------------------------------------------------------------- lecture des trois formats
def _csv(contenu: bytes) -> list[list[str]]:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            texte = contenu.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    premiere = texte.splitlines()[0] if texte else ""
    sep = ";" if premiere.count(";") >= premiere.count(",") else ","
    return [row for row in csv.reader(io.StringIO(texte), delimiter=sep)]


def _xlsx(contenu: bytes) -> list[list[str]]:
    from openpyxl import load_workbook
    feuille = load_workbook(io.BytesIO(contenu), read_only=True, data_only=True).worksheets[0]
    lignes = []
    for row in feuille.iter_rows(values_only=True):
        lignes.append(["" if v is None else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))
                       for v in row])
        if len(lignes) > MAX_LIGNES + 1:
            break
    return lignes


_NS = {"table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
       "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
       "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0"}


def _ods(contenu: bytes) -> list[list[str]]:
    """Première feuille d'un .ods (content.xml), sans dépendance : cellules répétées et valeurs numériques."""
    with zipfile.ZipFile(io.BytesIO(contenu)) as z:
        racine = ElementTree.fromstring(z.read("content.xml"))
    table = racine.find(".//table:table", _NS)
    if table is None:
        return []
    t, o = "{%s}" % _NS["table"], "{%s}" % _NS["office"]
    lignes = []
    for row in table.iter(t + "table-row"):
        cellules = []
        for cell in row:
            if cell.tag not in (t + "table-cell", t + "covered-table-cell"):
                continue
            n = min(int(cell.get(t + "number-columns-repeated", "1")), 100)
            valeur = cell.get(o + "value")
            if valeur is None:
                valeur = "\n".join("".join(p.itertext()) for p in cell.findall("text:p", _NS))
            elif cell.get(o + "value-type") == "float" and float(valeur).is_integer():
                valeur = str(int(float(valeur)))
            cellules += [valeur] * n
        repete = min(int(row.get(t + "number-rows-repeated", "1")), 5)
        while cellules and cellules[-1] == "":
            cellules.pop()
        lignes += [cellules] * (repete if cellules else 1)
        if len(lignes) > MAX_LIGNES + 1:
            break
    return lignes


def lire(nom: str, contenu: bytes) -> list[list[str]]:
    if len(contenu) > MAX_OCTETS:
        raise HTTPException(413, "Fichier trop volumineux (5 Mo au plus).")
    nom = (nom or "").lower()
    try:
        if nom.endswith(".xlsx"):
            return _xlsx(contenu)
        if nom.endswith(".ods"):
            return _ods(contenu)
        if nom.endswith((".csv", ".txt")):
            return _csv(contenu)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — fichier abîmé ou d'un autre format
        raise HTTPException(422, f"Fichier illisible ({type(e).__name__}) : enregistrez-le en CSV, .xlsx ou .ods.") from e
    raise HTTPException(422, "Format non pris en charge : CSV, Excel (.xlsx) ou LibreOffice (.ods).")


# ---------------------------------------------------------------- import
def _entier(v: str, ligne: int, nom: str, erreurs: list, requis: bool) -> int | None:
    s = (v or "").strip().replace(" ", "").replace(" ", "")
    if s == "":
        if requis:
            erreurs.append(f"Ligne {ligne} : {nom} manquant.")
        return None if not requis else 0
    try:
        f = float(s.replace(",", "."))
    except ValueError:
        erreurs.append(f"Ligne {ligne} : {nom} « {v} » n'est pas un nombre.")
        return 0
    if f < 0 or not f.is_integer():
        erreurs.append(f"Ligne {ligne} : {nom} « {v} » doit être un entier positif.")
        return 0
    return int(f)


def importer(db: Session, copro_id: int, nom: str, contenu: bytes, simuler: bool) -> dict:
    lignes = [l for l in lire(nom, contenu)]
    while lignes and not any((c or "").strip() for c in lignes[-1]):
        lignes.pop()
    if len(lignes) < 2:
        raise HTTPException(422, "Le fichier doit avoir une ligne d'en-tête et au moins un lot.")
    if len(lignes) > MAX_LIGNES + 1:
        raise HTTPException(422, f"Trop de lignes (au plus {MAX_LIGNES} lots).")
    entete = lignes[0]
    colonnes, cles_col, erreurs = {}, {}, []
    for i, titre in enumerate(entete):
        if not (titre or "").strip():
            continue
        m = PREFIXE_CLE.match(titre)
        if m:
            cles_col[i] = m.group(1).strip()
            continue
        c = _cle(titre)
        if c not in CONNUES:
            erreurs.append(f"Ligne 1 : colonne « {titre} » inconnue (colonnes possibles : numero, tantiemes, "
                           "designation, type, surface, proprietaire, et « clé : Nom de la clé »).")
        elif c in colonnes:
            erreurs.append(f"Ligne 1 : colonne « {titre} » en double.")
        else:
            colonnes[c] = i
    for requise in ("numero", "tantiemes"):
        if requise not in colonnes:
            erreurs.append(f"Ligne 1 : colonne « {requise} » manquante.")
    if erreurs:
        return _refus(erreurs, simuler)

    existants = {l.numero: l for l in db.query(Lot).filter(Lot.copropriete_id == copro_id)}
    comptes = {u.email.lower(): u for u in db.query(User).join(UserCopro, UserCopro.user_id == User.id)
               .filter(UserCopro.copropriete_id == copro_id)}
    vus, lus = set(), []
    for n, row in enumerate(lignes[1:], start=2):
        val = lambda c: (row[colonnes[c]] if c in colonnes and colonnes[c] < len(row) else "") or ""  # noqa: E731
        if not any((c or "").strip() for c in row):
            continue
        numero = val("numero").strip()
        if not numero:
            erreurs.append(f"Ligne {n} : numéro de lot manquant.")
            continue
        if numero in vus:
            erreurs.append(f"Ligne {n} : lot {numero} en double dans le fichier.")
        vus.add(numero)
        tant = _entier(val("tantiemes"), n, "tantièmes", erreurs, True)
        type_ = _cle(val("type")) if val("type").strip() else None
        if type_ is not None and type_ not in TYPES_LOT:
            erreurs.append(f"Ligne {n} : type « {val('type')} » inconnu ({', '.join(TYPES_LOT)}).")
        surface = None
        if val("surface").strip():
            try:
                surface = float(val("surface").replace(",", ".").replace(" ", ""))
                if surface < 0:
                    raise ValueError
            except ValueError:
                erreurs.append(f"Ligne {n} : surface « {val('surface')} » invalide.")
        proprio = None
        if val("proprietaire").strip():
            proprio = comptes.get(val("proprietaire").strip().lower())
            if proprio is None:
                erreurs.append(f"Ligne {n} : aucun compte « {val('proprietaire').strip()} » dans la copropriété "
                               "(créez-le d'abord dans Réglages → Comptes).")
        par_cle = {}
        for i, nom_cle in cles_col.items():
            par_cle[nom_cle] = _entier(row[i] if i < len(row) else "", n, f"millièmes « {nom_cle} »", erreurs, False) or 0
        lus.append({"ligne": n, "numero": numero, "tantiemes": tant, "designation": val("designation").strip(),
                    "type": type_, "surface": surface, "proprietaire": proprio, "cles": par_cle,
                    "existe": numero in existants})
    if erreurs:
        return _refus(erreurs, simuler)

    cles_existantes = {c.nom: c for c in db.query(CleRepartition).filter(CleRepartition.copropriete_id == copro_id)}
    resume = {"erreurs": [], "crees": [l["numero"] for l in lus if not l["existe"]],
              "modifies": [l["numero"] for l in lus if l["existe"]],
              "cles_creees": [c for c in cles_col.values() if c not in cles_existantes],
              "cles_modifiees": [c for c in cles_col.values() if c in cles_existantes],
              "simulation": simuler}
    if simuler:
        return resume

    for l in lus:
        lot = existants.get(l["numero"])
        if lot is None:
            lot = Lot(copropriete_id=copro_id, numero=l["numero"], type=l["type"] or "appartement")
            db.add(lot)
            existants[l["numero"]] = lot
        lot.tantiemes = l["tantiemes"]
        if l["designation"]:
            lot.designation = l["designation"]
        if l["type"]:
            lot.type = l["type"]
        if l["surface"] is not None:
            lot.surface_m2 = l["surface"]
        if l["proprietaire"] is not None:
            lot.proprietaire_id = l["proprietaire"].id
    db.flush()
    for nom_cle in cles_col.values():
        cle = cles_existantes.get(nom_cle)
        if cle is None:
            cle = CleRepartition(copropriete_id=copro_id, nom=nom_cle)
            db.add(cle)
            db.flush()
        for l in lus:
            lot = existants[l["numero"]]
            db.query(CleLot).filter(CleLot.cle_id == cle.id, CleLot.lot_id == lot.id).delete(synchronize_session=False)
            if l["cles"][nom_cle] > 0:
                db.add(CleLot(cle_id=cle.id, lot_id=lot.id, tantiemes=l["cles"][nom_cle]))
    db.flush()
    vides = [c.nom for c in db.query(CleRepartition).filter(CleRepartition.copropriete_id == copro_id)
             if c.nom in cles_col.values() and not db.query(CleLot).filter(CleLot.cle_id == c.id, CleLot.tantiemes > 0).first()]
    if vides:
        db.rollback()
        raise HTTPException(422, " ; ".join(f"La clé « {v} » n'aurait aucun lot avec des millièmes." for v in vides))
    return resume


def _refus(erreurs: list[str], simuler: bool) -> dict:
    """Simulation : la liste des erreurs ; import : refus (rien n'est écrit)."""
    if simuler:
        return {"erreurs": erreurs[:50], "crees": [], "modifies": [], "cles_creees": [], "cles_modifiees": [],
                "simulation": True}
    raise HTTPException(422, "Import refusé, rien n'a été écrit : " + " ; ".join(erreurs[:5])
                        + (f" ; et {len(erreurs) - 5} autre(s) erreur(s)" if len(erreurs) > 5 else ""))


def modele_csv() -> str:
    return ("numero;designation;type;tantiemes;surface;proprietaire;clé : Bâtiment A\n"
            "1;Appartement T3;appartement;250;68,5;marie.dupont@exemple.fr;500\n"
            "2;Appartement T2;appartement;200;45;;500\n"
            "3;Cave;cave;10;;;\n")

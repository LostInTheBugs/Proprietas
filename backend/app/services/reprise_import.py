"""Reprise de l'historique : import CSV d'un état au 31/12, d'appels ou de paiements.

- Une ligne d'en-tête ; colonnes dans n'importe quel ordre, casse et accents ignorés.
    état      : lot ; exercice ; charges ; fonds_travaux        (brouillon à la date donnée)
    appels    : date ; lot ; libelle ; charges ; fonds_travaux   (même date + même libellé = un appel)
    paiements : date ; lot ; montant ; libelle (facultatif)     (encaissements)
- Séparateur « ; » ou « , » (détecté sur l'en-tête), montants à la française (« 1 234,50 »),
  dates JJ/MM/AAAA ou AAAA-MM-JJ, lot désigné par son numéro dans la copropriété.
- L'exercice d'un appel ou d'un paiement est l'année de sa date ; il est créé s'il manque
  (clôturé si l'année est passée).
- Refus en bloc : à la moindre erreur, rien n'est écrit ; chaque erreur cite sa ligne (la ligne
  d'en-tête est la ligne 1). Un appel (même date et même libellé) ou un paiement (même lot, date et
  montant) déjà présent, ou en double dans le fichier, est une erreur : un fichier importé deux fois
  ne compte jamais double.
"""
import csv
import io
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.money import LIMITE_MONTANT, D, arrondi, decimal_saisi, somme
from app.models.appel import AppelFonds, AppelLot
from app.models.exercice import Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.models.reprise import EtatReprise, EtatRepriseLigne
from app.services import reprise

TYPES = ("etat", "appels", "paiements")
COLONNES = {
    "etat": (("lot", "exercice", "charges"), ("fonds_travaux",)),
    "appels": (("date", "lot", "libelle", "charges"), ("fonds_travaux",)),
    "paiements": (("date", "lot", "montant"), ("libelle",)),
}
MAX_LIGNES = 5000
LIBELLE_PAIEMENT = "Paiement importé"


class _Erreur(Exception):
    pass


def _cle(texte: str) -> str:
    t = unicodedata.normalize("NFKD", (texte or "").strip().lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.replace(" ", "_").replace("-", "_")


def _montant(v: str, nom: str, vide_permis: bool = True) -> Decimal:
    s = (v or "").strip().replace(" ", "").replace(" ", "").replace(" ", "")
    s = s.replace("€", "").replace(",", ".")
    if s == "":
        if vide_permis:
            return D("0.00")
        raise _Erreur(f"{nom} manquant")
    try:
        return decimal_saisi(s, Decimal("0.01"), LIMITE_MONTANT)
    except ValueError:
        raise _Erreur(f"{nom} invalide : « {v.strip()} »") from None


def _date(v: str) -> date:
    s = (v or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise _Erreur(f"date invalide : « {s} » (attendu JJ/MM/AAAA)")


def _lire(contenu: str, type_: str) -> tuple[list[tuple[int, dict]], list[dict]]:
    """Lignes (numéro, valeurs par colonne) ou erreurs d'en-tête."""
    texte = (contenu or "").lstrip("﻿")
    premiere = texte.splitlines()[0] if texte.strip() else ""
    if not premiere:
        return [], [{"ligne": 1, "message": "Fichier vide."}]
    sep = ";" if premiere.count(";") >= premiere.count(",") else ","
    lecteur = csv.reader(io.StringIO(texte), delimiter=sep)
    entete = [_cle(c) for c in next(lecteur)]
    obligatoires, _ = COLONNES[type_]
    manquantes = [c for c in obligatoires if c not in entete]
    if manquantes:
        return [], [{"ligne": 1, "message": "Colonne(s) manquante(s) : " + ", ".join(manquantes)
                     + ". En-tête attendu : " + ";".join(obligatoires + COLONNES[type_][1]) + "."}]
    lignes = []
    for num, cellules in enumerate(lecteur, start=2):
        if not any(c.strip() for c in cellules):
            continue
        lignes.append((num, {nom: (cellules[i] if i < len(cellules) else "") for i, nom in enumerate(entete)}))
    if len(lignes) > MAX_LIGNES:
        return [], [{"ligne": 1, "message": f"Plus de {MAX_LIGNES} lignes : découpez le fichier."}]
    return lignes, []


def _exercice(db: Session, copro_id: int, annee: int, crees: dict) -> Exercice:
    if annee in crees:
        return crees[annee]
    ex = db.query(Exercice).filter(Exercice.copropriete_id == copro_id, Exercice.annee == annee).first()
    if ex is None:
        ex = Exercice(copropriete_id=copro_id, annee=annee, cloture=annee < date.today().year)
        db.add(ex)
        db.flush()
    crees[annee] = ex
    return ex


def importer(db: Session, copro, type_: str, contenu: str, simuler: bool, jour: date | None) -> dict:
    if type_ not in TYPES:
        raise HTTPException(422, "Type d'import inconnu (etat, appels ou paiements).")
    if type_ == "etat":
        if jour is None:
            raise HTTPException(422, "Indiquez la date de l'état (31 décembre).")
        reprise.controler_saisie(db, copro.id, jour, [])
        if db.query(EtatReprise).filter(EtatReprise.copropriete_id == copro.id, EtatReprise.date == jour).first():
            raise HTTPException(409, f"Un état au {jour:%d/%m/%Y} existe déjà.")

    lignes, erreurs = _lire(contenu, type_)
    lots = {l.numero.strip(): l for l in db.query(Lot).filter(Lot.copropriete_id == copro.id)}
    b = reprise.base(db, copro.id)
    valides = []
    vus = set()
    for num, v in lignes:
        try:
            numero = (v.get("lot") or "").strip()
            lot = lots.get(numero)
            if lot is None:
                raise _Erreur(f"lot « {numero} » inconnu dans cette copropriété")
            if type_ == "etat":
                try:
                    annee = int((v.get("exercice") or "").strip())
                except ValueError:
                    raise _Erreur(f"exercice invalide : « {v.get('exercice', '').strip()} »") from None
                if not 1900 <= annee <= jour.year:
                    raise _Erreur(f"exercice {annee} invalide pour un état au 31/12/{jour.year}")
                cle = (lot.id, annee)
                if cle in vus:
                    raise _Erreur(f"deuxième ligne pour le lot {numero} et l'exercice {annee}")
                valides.append({"ligne": num, "lot": lot, "exercice": annee, "charges": _montant(v.get("charges"), "charges"),
                                "fonds": _montant(v.get("fonds_travaux"), "fonds_travaux")})
            elif type_ == "appels":
                d = _date(v.get("date"))
                libelle = (v.get("libelle") or "").strip()
                if not libelle:
                    raise _Erreur("libellé manquant")
                cle = (d, libelle, lot.id)
                if cle in vus:
                    raise _Erreur(f"lot {numero} présent deux fois dans l'appel « {libelle} » du {d:%d/%m/%Y}")
                valides.append({"ligne": num, "lot": lot, "date": d, "libelle": libelle,
                                "charges": _montant(v.get("charges"), "charges"),
                                "fonds": _montant(v.get("fonds_travaux"), "fonds_travaux")})
            else:
                d = _date(v.get("date"))
                montant = _montant(v.get("montant"), "montant", vide_permis=False)
                if montant <= 0:
                    raise _Erreur("le montant d'un paiement doit être positif")
                cle = (lot.id, d, montant)
                if cle in vus:
                    raise _Erreur("paiement en double dans le fichier (même lot, date et montant)")
                existe = db.query(Mouvement).filter(
                    Mouvement.copropriete_id == copro.id, Mouvement.type == "encaissement",
                    Mouvement.lot_id == lot.id, Mouvement.date == d).all()
                if any(D(m.montant or 0) == montant for m in existe):
                    raise _Erreur(f"paiement déjà présent : lot {numero}, {d:%d/%m/%Y}, {montant} €")
                valides.append({"ligne": num, "lot": lot, "date": d, "montant": montant,
                                "libelle": (v.get("libelle") or "").strip() or LIBELLE_PAIEMENT})
            vus.add(cle)
        except _Erreur as e:
            erreurs.append({"ligne": num, "message": str(e)})

    groupes: dict[tuple, list] = defaultdict(list)
    if type_ == "appels":
        for l in valides:
            groupes[(l["date"], l["libelle"])].append(l)
        for (d, libelle), membres in groupes.items():
            deja = (db.query(AppelFonds).join(Exercice, AppelFonds.exercice_id == Exercice.id)
                    .filter(Exercice.copropriete_id == copro.id, AppelFonds.date_emission == d,
                            AppelFonds.libelle == libelle).first())
            if deja is not None:
                erreurs.append({"ligne": membres[0]["ligne"],
                                "message": f"appel « {libelle} » du {d:%d/%m/%Y} déjà présent"})

    resume = {"lignes": len(valides)}
    if type_ == "appels":
        resume["appels"] = len(groupes)
        resume["total"] = arrondi(somme(l["charges"] + l["fonds"] for l in valides))
    elif type_ == "paiements":
        resume["paiements"] = len(valides)
        resume["total"] = arrondi(somme(l["montant"] for l in valides))
    else:
        resume["total"] = arrondi(somme(l["charges"] + l["fonds"] for l in valides))
    if type_ != "etat":
        resume["couverts_par_la_base"] = sum(1 for l in valides if b is not None and l["date"] <= b.date)
    erreurs.sort(key=lambda e: e["ligne"])
    sortie = {"simulation": simuler, "type": type_, "resume": resume, "erreurs": erreurs, "etat_id": None}
    if simuler:
        return sortie
    if erreurs:
        detail = " ; ".join(f"ligne {e['ligne']} : {e['message']}" for e in erreurs[:10])
        plus = f" (et {len(erreurs) - 10} autre(s))" if len(erreurs) > 10 else ""
        raise HTTPException(422, f"Rien n'a été importé. {detail}{plus}.")
    if not valides:
        raise HTTPException(422, "Aucune ligne à importer.")

    exercices: dict[int, Exercice] = {}
    if type_ == "etat":
        etat = EtatReprise(copropriete_id=copro.id, date=jour, commentaire="Import CSV")
        etat.lignes = [EtatRepriseLigne(lot_id=l["lot"].id, proprietaire_id=l["lot"].proprietaire_id,
                                        exercice_origine=l["exercice"], montant_charges=l["charges"],
                                        montant_fonds_travaux=l["fonds"]) for l in valides]
        db.add(etat)
        db.flush()
        sortie["etat_id"] = etat.id
    elif type_ == "appels":
        for (d, libelle), membres in sorted(groupes.items()):
            ex = _exercice(db, copro.id, d.year, exercices)
            fonds = arrondi(somme(l["fonds"] for l in membres))
            appel = AppelFonds(exercice_id=ex.id, libelle=libelle, date_emission=d, date_echeance=d,
                               montant_total=arrondi(somme(l["charges"] + l["fonds"] for l in membres)),
                               inclut_fonds_travaux=fonds != 0, fonds_travaux_montant=fonds)
            db.add(appel)
            db.flush()
            for l in membres:
                db.add(AppelLot(appel_id=appel.id, lot_id=l["lot"].id, montant_charges=l["charges"],
                                montant_fonds_travaux=l["fonds"]))
    else:
        for l in valides:
            ex = _exercice(db, copro.id, l["date"].year, exercices)
            db.add(Mouvement(copropriete_id=copro.id, exercice_id=ex.id, date=l["date"], libelle=l["libelle"],
                             type="encaissement", categorie="charges", montant=l["montant"], lot_id=l["lot"].id))
    db.flush()
    return sortie

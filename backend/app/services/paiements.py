"""Paiement d'un copropriétaire pour l'ensemble de ses lots (un virement, plusieurs lots).

- Répartition proposée : les restants dus de tous ses lots (décompte FIFO de recouvrement.appels_lot)
  sont soldés de la plus ancienne échéance à la plus récente ; à échéance égale, dans l'ordre des
  appels puis des lots. Un excédent (avance) va au lot qui a le plus de tantièmes.
- Enregistrement : une part par lot (le syndic peut corriger la proposition), somme = montant reçu ;
  un encaissement « charges » par part non nulle, dans l'exercice de l'année de la date (créé s'il
  manque, clôturé si l'année est passée).
"""
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.money import D, arrondi, somme
from app.models.exercice import Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.services import recouvrement


def lots_du_proprietaire(db: Session, copro, proprietaire_id: int) -> list[Lot]:
    lots = (db.query(Lot).filter(Lot.copropriete_id == copro.id, Lot.proprietaire_id == proprietaire_id)
            .order_by(Lot.id).all())
    if not lots:
        raise HTTPException(422, "Ce copropriétaire n'a aucun lot dans la copropriété.")
    return lots


def repartition(db: Session, copro, proprietaire_id: int, montant: Decimal) -> dict:
    if montant <= 0:
        raise HTTPException(422, "Le montant reçu doit être positif.")
    lots = lots_du_proprietaire(db, copro, proprietaire_id)
    dus = []
    du_par_lot = {}
    for lot in lots:
        lignes = recouvrement.appels_lot(db, copro, lot)
        du_par_lot[lot.id] = recouvrement.solde_lot(lignes)
        for l in lignes:
            if l["restant_du"] > 0:
                dus.append((l["echeance"] or date.min, l["appel_id"], lot.id, l["restant_du"]))
    dus.sort()
    reste = arrondi(montant)
    propose = {lot.id: D(0) for lot in lots}
    for _, _, lot_id, restant in dus:
        if reste <= 0:
            break
        part = min(reste, restant)
        propose[lot_id] += part
        reste = arrondi(reste - part)
    if reste > 0:
        principal = max(lots, key=lambda l: (l.tantiemes or 0, -l.id))
        propose[principal.id] += reste
    return {
        "proprietaire_id": proprietaire_id,
        "montant": arrondi(montant),
        "excedent": reste,
        "lots": [{"lot_id": lot.id, "lot_numero": lot.numero, "du": du_par_lot[lot.id],
                  "propose": arrondi(propose[lot.id])} for lot in lots],
    }


def _exercice(db: Session, copro_id: int, annee: int) -> Exercice:
    ex = db.query(Exercice).filter(Exercice.copropriete_id == copro_id, Exercice.annee == annee).first()
    if ex is None:
        ex = Exercice(copropriete_id=copro_id, annee=annee, cloture=annee < date.today().year)
        db.add(ex)
        db.flush()
    return ex


def enregistrer(db: Session, copro, proprietaire_id: int, jour: date, montant: Decimal, libelle: str,
                parts: list) -> list[Mouvement]:
    if montant <= 0:
        raise HTTPException(422, "Le montant reçu doit être positif.")
    lots = {l.id: l for l in lots_du_proprietaire(db, copro, proprietaire_id)}
    vus = set()
    for p in parts:
        if p.lot_id not in lots:
            raise HTTPException(422, "Un des lots n'appartient pas à ce copropriétaire.")
        if p.lot_id in vus:
            raise HTTPException(422, "Un lot apparaît deux fois dans la répartition.")
        if p.montant < 0:
            raise HTTPException(422, "Une part ne peut pas être négative.")
        vus.add(p.lot_id)
    total = arrondi(somme(p.montant for p in parts))
    if total != arrondi(montant):
        raise HTTPException(422, f"La répartition totalise {total:.2f} € au lieu de {arrondi(montant):.2f} €."
                            .replace(".", ","))
    ex = _exercice(db, copro.id, jour.year)
    libelle = (libelle or "").strip() or "Paiement"
    crees = []
    for p in parts:
        if p.montant == 0:
            continue
        m = Mouvement(copropriete_id=copro.id, exercice_id=ex.id, date=jour,
                      libelle=f"{libelle} — lot {lots[p.lot_id].numero}", type="encaissement",
                      categorie="charges", montant=p.montant, lot_id=p.lot_id)
        db.add(m)
        crees.append(m)
    db.flush()
    return crees

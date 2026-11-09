"""Paiement d'un copropriétaire pour l'ensemble de ses lots (un virement, plusieurs lots).

- Répartition proposée : les restants dus de tous ses lots (recouvrement.ventilation_lot) sont soldés
  de la plus ancienne échéance à la plus récente ; à échéance égale, dans l'ordre des appels puis des
  lots ; dans un appel, charges puis fonds de travaux. Chaque somme est rangée dans sa nature (charges
  ou travaux). Un excédent est une avance sur charges du lot qui a le plus de tantièmes.
- Enregistrement : par lot, une part charges et une part travaux (le syndic peut corriger la
  proposition), total = montant reçu ; un encaissement « charges » et/ou un encaissement « fonds de
  travaux » (réservé à la part fonds de travaux des appels) par lot, dans l'exercice de l'année de la
  date (créé s'il manque, clôturé si l'année est passée).
"""
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.money import D, arrondi, somme
from app.models.exercice import Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.services import ensembles, recouvrement


def lots_du_proprietaire(db: Session, copro, proprietaire_id: int) -> list[Lot]:
    lots = (db.query(Lot).filter(Lot.copropriete_id == copro.id, Lot.proprietaire_id == proprietaire_id)
            .order_by(Lot.id).all())
    if not lots:
        raise HTTPException(422, "Ce copropriétaire n'a aucun lot dans la copropriété.")
    return lots


def repartition(db: Session, copro, proprietaire_id: int, montant: Decimal) -> dict:
    if montant <= 0:
        raise HTTPException(422, "Le montant reçu doit être positif.")
    # Lots non séparables : une seule ligne par ensemble, portée par le lot principal (le décompte
    # de l'ensemble met en commun les paiements de tous ses lots).
    groupes = ensembles.ensembles(db, copro.id, lots_du_proprietaire(db, copro, proprietaire_id))
    lots = [g[0] for g in groupes]
    etiquette = {g[0].id: ensembles.libelle(g).removeprefix("Lot ") for g in groupes}
    dus = []
    ventil = {}
    for lot in lots:
        v = recouvrement.ventilation_lot(db, copro, lot)
        ventil[lot.id] = v
        for l in v["lignes"]:
            for ordre, nature, cle in ((0, "charges", "restant_du_charges"), (1, "travaux", "restant_du_fonds")):
                if l[cle] > 0:
                    dus.append((l["echeance"] or date.min, l["appel_id"], lot.id, ordre, nature, l[cle]))
    dus.sort()
    reste = arrondi(montant)
    propose = {lot.id: {"charges": D(0), "travaux": D(0)} for lot in lots}
    for _, _, lot_id, _, nature, restant in dus:
        if reste <= 0:
            break
        part = min(reste, restant)
        propose[lot_id][nature] += part
        reste = arrondi(reste - part)
    if reste > 0:
        principal = max(lots, key=lambda l: (l.tantiemes or 0, -l.id))
        propose[principal.id]["charges"] += reste
    sortie = []
    for lot in lots:
        v, pr = ventil[lot.id], propose[lot.id]
        sortie.append({
            "lot_id": lot.id, "lot_numero": etiquette[lot.id],
            "du": arrondi(v["du_charges"] + v["du_travaux"]),
            "du_charges": v["du_charges"], "du_travaux": v["du_travaux"],
            "propose": arrondi(pr["charges"] + pr["travaux"]),
            "propose_charges": arrondi(pr["charges"]), "propose_travaux": arrondi(pr["travaux"]),
        })
    return {"proprietaire_id": proprietaire_id, "montant": arrondi(montant), "excedent": reste,
            "lots": sortie}


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
        if p.montant < 0 or p.montant_travaux < 0:
            raise HTTPException(422, "Une part ne peut pas être négative.")
        vus.add(p.lot_id)
    total = arrondi(somme(p.montant + p.montant_travaux for p in parts))
    if total != arrondi(montant):
        raise HTTPException(422, f"La répartition totalise {total:.2f} € au lieu de {arrondi(montant):.2f} €."
                            .replace(".", ","))
    ex = _exercice(db, copro.id, jour.year)
    libelle = (libelle or "").strip() or "Paiement"
    crees = []
    for p in parts:
        numero = lots[p.lot_id].numero
        for montant_part, categorie, suffixe in ((p.montant, "charges", ""),
                                                 (p.montant_travaux, "fonds_travaux", " (travaux)")):
            if montant_part == 0:
                continue
            m = Mouvement(copropriete_id=copro.id, exercice_id=ex.id, date=jour,
                          libelle=f"{libelle} — lot {numero}{suffixe}", type="encaissement",
                          categorie=categorie, montant=montant_part, lot_id=p.lot_id)
            db.add(m)
            crees.append(m)
    db.flush()
    return crees

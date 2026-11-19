"""Clés de répartition : charges spéciales (loi n° 65-557, art. 10 ; demande de Fred, 20/11/2026, issue #65).

- Une clé (« Bâtiment A », « Ascenseur »…) donne ses propres millièmes aux lots concernés (models/cle.py).
  Sans clé : charges générales, par les tantièmes du lot.
- Chaque ligne de budget et chaque dépense commune a sa clé.
- Appel de provisions : réparti comme le budget de l'exercice (choix de Fred) — le montant est d'abord
  partagé entre les clés au prorata de leur budget, puis chaque part entre les lots par sa clé. Un appel
  peut aussi porter sur une seule clé (travaux de l'ascenseur). La cotisation au fonds de travaux reste
  répartie par les tantièmes généraux.
- Régularisation : les dépenses de chaque clé réparties par cette clé (services/regularisation.py).
- Une répartition « entre bâtiments, puis dans le bâtiment » se ramène à une clé aux millièmes recalculés.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal as D
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.money import arrondi, somme, to_money
from app.models.appel import AppelFonds
from app.models.cle import CleLot, CleRepartition
from app.models.exercice import BudgetLine
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.services.country_rules import _plus_fort_reste, repartir_par_tantiemes

GENERALES = "Charges générales"


def nom(cle: CleRepartition | None) -> str:
    return cle.nom if cle is not None else GENERALES


def lots_de(db: Session, copro_id: int, cle_id: int | None) -> list:
    """Lots qui participent, avec leurs millièmes pour cette clé (objets avec .id et .tantiemes)."""
    if cle_id is None:
        return db.query(Lot).filter(Lot.copropriete_id == copro_id).order_by(Lot.id).all()
    return [SimpleNamespace(id=cl.lot_id, tantiemes=cl.tantiemes)
            for cl in db.query(CleLot).filter(CleLot.cle_id == cle_id, CleLot.tantiemes > 0).order_by(CleLot.lot_id)]


def controler(db: Session, copro_id: int, cle_id: int | None) -> CleRepartition | None:
    """La clé, si elle est de la copropriété et a des millièmes ; 422 sinon."""
    if cle_id is None:
        return None
    cle = db.query(CleRepartition).filter(CleRepartition.id == cle_id, CleRepartition.copropriete_id == copro_id).first()
    if cle is None:
        raise HTTPException(422, "Cette clé de répartition n'appartient pas à la copropriété.")
    if not lots_de(db, copro_id, cle.id):
        raise HTTPException(422, f"La clé « {cle.nom} » n'a encore aucun lot avec des millièmes.")
    return cle


def repartir(db: Session, copro_id: int, montant, cle_id: int | None) -> dict[int, D]:
    """{lot_id: montant} : `montant` réparti par la clé (plus fort reste, au centime)."""
    lots = lots_de(db, copro_id, cle_id)
    if not lots or not to_money(montant):
        return {}
    return {p["lot"].id: p["montant_charges"] for p in repartir_par_tantiemes(montant, lots)}


def budget_par_cle(db: Session, exercice_id: int) -> dict[int | None, D]:
    out: dict[int | None, D] = defaultdict(lambda: D(0))
    for b in db.query(BudgetLine).filter(BudgetLine.exercice_id == exercice_id):
        out[b.cle_id] += D(b.montant or 0)
    return {k: v for k, v in out.items() if v > 0}


def repartir_selon_budget(db: Session, copro_id: int, exercice_id: int, montant) -> dict[int, D]:
    """{lot_id: montant} : `montant` partagé entre les clés comme le budget, puis chaque part par sa clé.
    Budget vide ou entièrement en charges générales : tout par les tantièmes généraux (comme avant les clés)."""
    budget = budget_par_cle(db, exercice_id)
    if set(budget) <= {None}:
        return repartir(db, copro_id, montant, None)
    cles = sorted(budget, key=lambda k: (k is not None, k or 0))
    poids = [SimpleNamespace(tantiemes=int(budget[k] * 100)) for k in cles]
    centimes = _plus_fort_reste(to_money(montant) * D(100), poids)
    out: dict[int, D] = defaultdict(lambda: D(0))
    for k, c in zip(cles, centimes):
        for lot_id, m in repartir(db, copro_id, D(c) / D(100), k).items():
            out[lot_id] += m
    return dict(out)


def depenses_reparties(db: Session, copro_id: int, depenses) -> dict[int, D]:
    """Dépenses communes (sans lot) réparties clé par clé : {lot_id: montant}."""
    par_cle: dict[int | None, D] = defaultdict(lambda: D(0))
    for m in depenses:
        if m.lot_id is None:
            par_cle[m.cle_id] += D(m.montant or 0)
    out: dict[int, D] = defaultdict(lambda: D(0))
    for cle_id, total in par_cle.items():
        for lot_id, montant in repartir(db, copro_id, arrondi(total), cle_id).items():
            out[lot_id] += montant
    return dict(out)


# ---------------------------------------------------------------- gestion des clés
def _ecrire_lots(db: Session, copro_id: int, cle: CleRepartition, lignes) -> None:
    ids = {l.id for l in db.query(Lot).filter(Lot.copropriete_id == copro_id)}
    vus = set()
    for l in lignes:
        if l.lot_id not in ids:
            raise HTTPException(422, "Un lot de la clé n'appartient pas à la copropriété.")
        if l.lot_id in vus:
            raise HTTPException(422, "Un lot apparaît deux fois dans la clé.")
        vus.add(l.lot_id)
    if not any(l.tantiemes > 0 for l in lignes):
        raise HTTPException(422, "Donnez des millièmes à au moins un lot.")
    db.query(CleLot).filter(CleLot.cle_id == cle.id).delete(synchronize_session=False)
    for l in lignes:
        if l.tantiemes > 0:
            db.add(CleLot(cle_id=cle.id, lot_id=l.lot_id, tantiemes=l.tantiemes))


def _nom_libre(db: Session, copro_id: int, nom_cle: str, sauf: int | None = None) -> str:
    nom_cle = (nom_cle or "").strip()
    if not nom_cle or nom_cle.lower() == GENERALES.lower():
        raise HTTPException(422, f"Donnez un nom à la clé (autre que « {GENERALES} »).")
    q = db.query(CleRepartition).filter(CleRepartition.copropriete_id == copro_id, CleRepartition.nom == nom_cle)
    if sauf is not None:
        q = q.filter(CleRepartition.id != sauf)
    if q.first():
        raise HTTPException(409, f"Une clé « {nom_cle} » existe déjà.")
    return nom_cle


def creer(db: Session, copro_id: int, data) -> CleRepartition:
    cle = CleRepartition(copropriete_id=copro_id, nom=_nom_libre(db, copro_id, data.nom))
    db.add(cle)
    db.flush()
    _ecrire_lots(db, copro_id, cle, data.lots)
    return cle


def modifier(db: Session, copro_id: int, cle: CleRepartition, data) -> CleRepartition:
    cle.nom = _nom_libre(db, copro_id, data.nom, sauf=cle.id)
    _ecrire_lots(db, copro_id, cle, data.lots)
    return cle


def utilisations(db: Session, cle_id: int) -> dict[str, int]:
    return {"lignes_budget": db.query(BudgetLine).filter(BudgetLine.cle_id == cle_id).count(),
            "appels": db.query(AppelFonds).filter(AppelFonds.cle_id == cle_id).count(),
            "depenses": db.query(Mouvement).filter(Mouvement.cle_id == cle_id).count()}


def supprimer(db: Session, cle: CleRepartition) -> None:
    u = utilisations(db, cle.id)
    if any(u.values()):
        raise HTTPException(409, f"La clé « {cle.nom} » sert encore : {u['lignes_budget']} ligne(s) de budget, "
                                 f"{u['appels']} appel(s), {u['depenses']} dépense(s). Changez-leur de clé d'abord.")
    db.delete(cle)


def etat(db: Session, copro_id: int) -> list[dict]:
    lots = {l.id: l for l in db.query(Lot).filter(Lot.copropriete_id == copro_id)}
    out = []
    for c in db.query(CleRepartition).filter(CleRepartition.copropriete_id == copro_id).order_by(CleRepartition.nom):
        lignes = [cl for cl in c.lots if cl.lot_id in lots]
        out.append({"id": c.id, "nom": c.nom,
                    "total": sum(cl.tantiemes for cl in lignes),
                    "lots": [{"lot_id": cl.lot_id, "lot_numero": lots[cl.lot_id].numero, "tantiemes": cl.tantiemes}
                             for cl in sorted(lignes, key=lambda cl: cl.lot_id)],
                    "utilisations": utilisations(db, c.id)})
    return out


def total_repartition(parts: dict[int, D]) -> D:
    return arrondi(somme(parts.values()))

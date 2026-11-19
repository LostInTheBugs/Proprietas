"""Avances : une personne paie de sa poche une dépense de la copropriété (demande de Fred, 19/11/2026).

Cas d'origine : assurance et EDF impayées, réglées personnellement par le syndic bénévole.

Trois sortes de mouvements portent `avance_par_id` (un compte rattaché à la copropriété) :

| Mouvement | Type, catégorie | Banque | Charges | Dette de la copro envers la personne |
|---|---|---|---|---|
| **avance** : dépense « payée par » la personne | dépense, catégorie habituelle | non | oui | + montant |
| **remboursement** par virement | dépense, catégorie `avance` | oui | non | − montant |
| **déduction** de ses charges | encaissement sur un de ses lots | non | (paiement de ses appels) | − montant |

- une avance a toujours son justificatif (la facture : document rattaché) ; un remboursement ou une
  déduction ne peut pas dépasser ce que la copropriété doit encore à la personne ;
- `hors_banque` : le mouvement n'est pas passé par le compte de la copropriété ; la trésorerie et le
  contrôle des relevés bancaires l'ignorent (services/reprise.py) ;
- la catégorie `avance` n'est ni une charge ni un produit : compte de gestion, régularisation, rapport
  annuel et récapitulatifs l'ignorent (`CATEGORIE`) ;
- un compte à qui la copropriété doit encore de l'argent (ou qui lui en doit) ne peut pas être supprimé.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal as D

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.money import arrondi
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.models.user import User, UserCopro

CATEGORIE = "avance"          # remboursement d'une avance : ni charge ni produit


def nature(type_: str, categorie: str, avance_par_id) -> str:
    """« avance », « remboursement », « deduction », ou « » (mouvement ordinaire)."""
    if avance_par_id is None:
        return ""
    if type_ == "depense":
        return "remboursement" if categorie == CATEGORIE else "avance"
    return "deduction"


def hors_banque(type_: str, categorie: str, avance_par_id) -> bool:
    return nature(type_, categorie, avance_par_id) in ("avance", "deduction")


def _cumuls(mouvements) -> dict[int, dict]:
    out: dict[int, dict] = defaultdict(lambda: {"avance": D(0), "rembourse": D(0), "deduit": D(0)})
    cles = {"avance": "avance", "remboursement": "rembourse", "deduction": "deduit"}
    for type_, categorie, pid, montant in mouvements:
        n = nature(type_, categorie, pid)
        if n:
            out[pid][cles[n]] += D(montant or 0)
    for c in out.values():
        c["reste"] = arrondi(c["avance"] - c["rembourse"] - c["deduit"])
    return out


def _lignes(db: Session, copro_id: int, sauf_id: int | None = None) -> list[tuple]:
    q = db.query(Mouvement.type, Mouvement.categorie, Mouvement.avance_par_id, Mouvement.montant).filter(
        Mouvement.copropriete_id == copro_id, Mouvement.avance_par_id.isnot(None))
    if sauf_id is not None:
        q = q.filter(Mouvement.id != sauf_id)
    return [tuple(r) for r in q.all()]


def restes(db: Session, copro_id: int) -> dict[int, D]:
    """Ce que la copropriété doit encore à chaque personne."""
    return {pid: c["reste"] for pid, c in _cumuls(_lignes(db, copro_id)).items()}


def _nom(u: User | None) -> str:
    return (u.nom_complet or u.email) if u is not None else "compte supprimé"


def controler(db: Session, copro, data, mouvement: Mouvement | None = None) -> bool:
    """Contrôle un mouvement créé ou modifié (`data` : MouvementIn) au regard des avances ; 422 sinon.
    Renvoie la valeur de `hors_banque`."""
    pid = data.avance_par_id
    if data.categorie == CATEGORIE and (data.type != "depense" or pid is None):
        raise HTTPException(422, "Catégorie « avance » : réservée au remboursement d'une avance, une dépense "
                                 "qui indique la personne remboursée.")
    n = nature(data.type, data.categorie, pid)
    if pid is not None:
        personne = (db.query(User).join(UserCopro, UserCopro.user_id == User.id)
                    .filter(User.id == pid, UserCopro.copropriete_id == copro.id).first())
        if personne is None:
            raise HTTPException(422, "Cette personne n'a pas de compte dans la copropriété.")
        if n == "avance" and data.document_id is None:
            raise HTTPException(422, "Une dépense payée par une personne doit avoir son justificatif : rattachez la "
                                     "facture (document), sinon elle ne peut pas être remboursée.")
        if n == "remboursement" and data.lot_id is not None:
            raise HTTPException(422, "Un remboursement d'avance concerne la copropriété entière, pas un lot.")
        if n == "deduction":
            lot = db.query(Lot).filter(Lot.id == data.lot_id, Lot.copropriete_id == copro.id).first() \
                if data.lot_id is not None else None
            if lot is None or lot.proprietaire_id != pid:
                raise HTTPException(422, f"Une avance se déduit des charges d'un lot de {_nom(personne)} : "
                                         "choisissez un de ses lots.")
    # Après ce mouvement, la copropriété ne doit rien de négatif à personne (ni à l'ancienne personne
    # du mouvement, s'il change de personne ou de montant).
    lignes = _lignes(db, copro.id, mouvement.id if mouvement is not None else None)
    avant = _cumuls(lignes)
    cumuls = _cumuls(lignes + ([(data.type, data.categorie, pid, data.montant)] if pid is not None else []))
    for p in {pid, getattr(mouvement, "avance_par_id", None)} - {None}:
        if p in cumuls and cumuls[p]["reste"] < 0:
            dispo = avant[p]["reste"] if p in avant else D(0)
            raise HTTPException(422, f"C'est plus que ce que la copropriété doit à {_nom(db.get(User, p))} "
                                     f"au titre de ses avances (reste dû, sans ce mouvement : {dispo} €).")
    return hors_banque(data.type, data.categorie, pid)


def controler_suppression(db: Session, copro, mouvement: Mouvement) -> None:
    pid = mouvement.avance_par_id
    if pid is None:
        return
    cumuls = _cumuls(_lignes(db, copro.id, mouvement.id))
    if pid in cumuls and cumuls[pid]["reste"] < 0:
        raise HTTPException(409, f"Cette avance a déjà été remboursée ou déduite des charges de "
                                 f"{_nom(mouvement.avance_par)} : supprimez d'abord le remboursement ou la déduction.")


def solde_compte(db: Session, user_id: int) -> D:
    """Somme, toutes copropriétés confondues, de ce qui reste dû à ce compte au titre de ses avances."""
    copros = {c for (c,) in db.query(Mouvement.copropriete_id).filter(Mouvement.avance_par_id == user_id).distinct()}
    return sum((restes(db, c).get(user_id, D(0)) for c in copros), D(0))


def etat(db: Session, copro_id: int, user_id: int | None = None) -> list[dict]:
    """Par personne : avancé, remboursé, déduit, reste dû, ses lots (pour une déduction) et ses mouvements."""
    q = db.query(Mouvement).filter(Mouvement.copropriete_id == copro_id, Mouvement.avance_par_id.isnot(None))
    if user_id is not None:
        q = q.filter(Mouvement.avance_par_id == user_id)
    mouvements = q.order_by(Mouvement.date, Mouvement.id).all()
    cumuls = _cumuls([(m.type, m.categorie, m.avance_par_id, m.montant) for m in mouvements])
    out = []
    for pid, c in cumuls.items():
        u = db.get(User, pid)
        lots = (db.query(Lot).filter(Lot.copropriete_id == copro_id, Lot.proprietaire_id == pid)
                .order_by(Lot.numero).all())
        out.append({
            "personne_id": pid, "nom": _nom(u),
            "avance": arrondi(c["avance"]), "rembourse": arrondi(c["rembourse"]), "deduit": arrondi(c["deduit"]),
            "reste": c["reste"],
            "lots": [{"id": l.id, "numero": l.numero} for l in lots],
            "mouvements": [{"id": m.id, "date": m.date, "libelle": m.libelle, "montant": arrondi(D(m.montant or 0)),
                            "nature": nature(m.type, m.categorie, m.avance_par_id), "exercice_id": m.exercice_id,
                            "document_id": m.document_id}
                           for m in mouvements if m.avance_par_id == pid],
        })
    out.sort(key=lambda e: (-e["reste"], e["nom"]))
    return out

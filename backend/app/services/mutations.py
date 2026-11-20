"""Vente d'un lot (mutation) — demande de Fred, 20/11/2026.

- Le syndic enregistre la vente : lot (avec ses annexes non séparables), date de l'acte, acquéreur (un
  compte de la copropriété), notaire, date de la notification du transfert (décret n° 67-223, art. 6) et
  de l'avis de mutation (loi du 10 juillet 1965, art. 20). Les lots de l'ensemble que possédait le vendeur
  passent à l'acquéreur.
- Coupure du décompte à la date de l'acte (décret 1967, art. 6-2) : les appels exigibles jusqu'à cette date
  (échéance ≤ date de l'acte) et les paiements reçus jusqu'à elle restent au **compte du vendeur** ; les
  appels exigibles après, dont la régularisation des comptes approuvés après la vente (art. 6-2, 3°), sont
  à l'acquéreur, dont le décompte repart de zéro.
- Le solde que doit le vendeur se règle en général sur le prix, par le notaire : « Encaisser le solde du
  vendeur » l'enregistre à son compte, pas à celui de l'acquéreur.
- Avis de mutation (art. 20) : le syndic a 15 jours pour former opposition (par acte de commissaire de
  justice) ; l'échéance est affichée.
- Une vente se corrige (dates, notaire, notes) ou s'annule si c'est la dernière du lot et qu'aucun
  encaissement n'a été porté au compte du vendeur.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core import audit
from app.core.money import D, arrondi, somme
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.models.mutation import Mutation
from app.models.user import User, UserCopro

DELAI_OPPOSITION = 15          # jours, loi du 10 juillet 1965, art. 20


def _nom(u: User | None) -> str:
    return (u.nom_complet or u.email) if u is not None else ""


def du_lot(db: Session, lot: Lot) -> list[Mutation]:
    """Ventes de l'ensemble du lot, de la plus ancienne à la plus récente."""
    from app.services import ensembles
    p = ensembles.principal(db, lot)
    return (db.query(Mutation).filter(Mutation.lot_id == p.id).order_by(Mutation.date_acte, Mutation.id).all())


def derniere(db: Session, lot: Lot) -> Mutation | None:
    ms = du_lot(db, lot)
    return ms[-1] if ms else None


def _echeance(appel) -> date | None:
    return appel.date_echeance or appel.date_emission


class Periode:
    """Ce qui revient à un propriétaire du lot : appels exigibles et paiements de sa période.

    - propriétaire actuel (`mutation=None`) : après la dernière vente ;
    - vendeur d'une vente : depuis la vente précédente (exclue) jusqu'à la date de l'acte (incluse), plus
      les encaissements portés à son compte après la vente.
    """

    def __init__(self, db: Session, lot: Lot, mutation: Mutation | None = None):
        ventes = du_lot(db, lot)
        if mutation is None:
            self.debut, self.fin, self.mutation_id = (ventes[-1].date_acte if ventes else None), None, None
        else:
            precedentes = [v for v in ventes if (v.date_acte, v.id) < (mutation.date_acte, mutation.id)]
            self.debut = precedentes[-1].date_acte if precedentes else None
            self.fin, self.mutation_id = mutation.date_acte, mutation.id

    def appel(self, appel) -> bool:
        j = _echeance(appel)
        if j is None:
            return self.fin is None
        return (self.debut is None or j > self.debut) and (self.fin is None or j <= self.fin)

    def encaissement(self, m: Mouvement) -> bool:
        if m.mutation_id is not None:
            return m.mutation_id == self.mutation_id
        return (self.debut is None or m.date > self.debut) and (self.fin is None or m.date <= self.fin)


# ---------------------------------------------------------------- vente
def _lot(db: Session, copro, lot_id: int) -> Lot:
    from app.services import ensembles
    lot = db.query(Lot).filter(Lot.id == lot_id, Lot.copropriete_id == copro.id).first()
    if lot is None:
        raise HTTPException(404, "Lot introuvable")
    return ensembles.principal(db, lot)


def _compte_de_la_copro(db: Session, copro, user_id: int | None) -> User:
    u = (db.query(User).join(UserCopro, UserCopro.user_id == User.id)
         .filter(User.id == user_id, UserCopro.copropriete_id == copro.id).first()) if user_id else None
    if u is None:
        raise HTTPException(422, "L'acquéreur doit être un compte de la copropriété : créez-lui un compte d'abord "
                                 "(Réglages → Comptes utilisateurs).")
    return u


def _controler_dates(data, date_acte: date) -> None:
    if date_acte > date.today():
        raise HTTPException(422, "La date de l'acte ne peut pas être dans le futur : enregistrez la vente une fois signée.")
    for champ, nom in (("notifiee_le", "la notification"), ("avis_mutation_le", "l'avis de mutation"),
                       ("opposition_le", "l'opposition")):
        v = getattr(data, champ, None)
        if v is not None and v < date_acte:
            raise HTTPException(422, f"La date de {nom} ne peut pas précéder la vente.")
        if v is not None and v > date.today():
            raise HTTPException(422, f"La date de {nom} ne peut pas être dans le futur.")


def creer(db: Session, copro, data, user, request) -> Mutation:
    from app.services import ensembles
    lot = _lot(db, copro, data.lot_id)
    if lot.proprietaire_id is None:
        raise HTTPException(422, "Ce lot n'a pas de propriétaire : indiquez d'abord le vendeur comme propriétaire.")
    vendeur = db.get(User, lot.proprietaire_id)
    acquereur = _compte_de_la_copro(db, copro, data.acquereur_id)
    if acquereur.id == vendeur.id:
        raise HTTPException(422, "L'acquéreur est déjà le propriétaire du lot.")
    _controler_dates(data, data.date_acte)
    prec = derniere(db, lot)
    if prec is not None and data.date_acte <= prec.date_acte:
        raise HTTPException(422, f"Une vente du {prec.date_acte:%d/%m/%Y} est déjà enregistrée : la nouvelle doit être "
                                 "postérieure.")
    m = Mutation(copropriete_id=copro.id, lot_id=lot.id, date_acte=data.date_acte, vendeur_id=vendeur.id,
                 acquereur_id=acquereur.id, vendeur_nom=_nom(vendeur), acquereur_nom=_nom(acquereur),
                 notaire=(data.notaire or "").strip()[:500], notifiee_le=data.notifiee_le,
                 avis_mutation_le=data.avis_mutation_le, opposition_le=data.opposition_le,
                 notes=(data.notes or "").strip()[:2000], creee_le=datetime.now())
    db.add(m)
    transferes = []
    for l in ensembles.membres(db, lot):
        if l.proprietaire_id == vendeur.id:
            l.proprietaire_id = acquereur.id
            l.statut_occupation = ""          # le nouveau propriétaire déclare l'occupation de son lot
            transferes.append(l.numero)
    db.flush()
    audit.enregistrer(db, "lot_vendu", user=user, copro_id=copro.id, request=request,
                      detail=f"lot(s) {', '.join(transferes)} vendu(s) le {m.date_acte:%d/%m/%Y} par {m.vendeur_nom} "
                             f"à {m.acquereur_nom}")
    return m


def modifier(db: Session, m: Mutation, data, user, request) -> Mutation:
    _controler_dates(data, m.date_acte)
    m.notaire = (data.notaire or "").strip()[:500]
    m.notifiee_le, m.avis_mutation_le, m.opposition_le = data.notifiee_le, data.avis_mutation_le, data.opposition_le
    m.notes = (data.notes or "").strip()[:2000]
    audit.enregistrer(db, "vente_modifiee", user=user, copro_id=m.copropriete_id, request=request,
                      detail=f"vente du {m.date_acte:%d/%m/%Y} (lot #{m.lot_id})")
    return m


def annuler(db: Session, m: Mutation, user, request) -> None:
    """Annule une vente saisie par erreur : seulement la dernière du lot, sans encaissement au compte du vendeur."""
    from app.services import ensembles
    if derniere(db, m.lot).id != m.id:
        raise HTTPException(409, "Une vente plus récente de ce lot est enregistrée : annulez-la d'abord.")
    if db.query(Mouvement).filter(Mouvement.mutation_id == m.id).first():
        raise HTTPException(409, "Un encaissement est porté au compte du vendeur : supprimez-le d'abord (Comptes).")
    for l in ensembles.membres(db, m.lot):
        if l.proprietaire_id == m.acquereur_id and m.vendeur_id is not None:
            l.proprietaire_id = m.vendeur_id
    audit.enregistrer(db, "vente_annulee", user=user, copro_id=m.copropriete_id, request=request,
                      detail=f"vente du {m.date_acte:%d/%m/%Y} de {m.vendeur_nom} à {m.acquereur_nom} (lot #{m.lot_id})")
    db.delete(m)
    db.flush()


def get(db: Session, copro, mutation_id: int) -> Mutation:
    m = db.query(Mutation).filter(Mutation.id == mutation_id, Mutation.copropriete_id == copro.id).first()
    if m is None:
        raise HTTPException(404, "Vente introuvable")
    return m


# ---------------------------------------------------------------- compte du vendeur
def compte_vendeur(db: Session, copro, m: Mutation) -> dict:
    """Décompte du vendeur arrêté à la date de l'acte (recouvrement.ventilation_lot sur sa période)."""
    from app.services import recouvrement
    v = recouvrement.ventilation_lot(db, copro, m.lot, periode=Periode(db, m.lot, m))
    du = arrondi(v["du_charges"] + v["du_travaux"])
    avance = arrondi(v["avance_charges"] + v["avance_travaux"])
    encaisse_apres = arrondi(somme(D(x.montant or 0) for x in
                                   db.query(Mouvement).filter(Mouvement.mutation_id == m.id)))
    return {"lignes": [l for l in v["lignes"] if l["restant_du"] != 0], "du": du, "du_charges": v["du_charges"],
            "du_travaux": v["du_travaux"], "avance": avance, "solde": arrondi(du - avance),
            "encaisse_apres_vente": encaisse_apres}


def encaisser_vendeur(db: Session, copro, m: Mutation, jour: date, montant, libelle: str, user, request) -> Mouvement:
    from app.services.paiements import _exercice
    montant = arrondi(D(montant))
    if montant <= 0:
        raise HTTPException(422, "Le montant reçu doit être positif.")
    if jour < m.date_acte:
        raise HTTPException(422, "Avant la vente, enregistrez le paiement comme un paiement ordinaire du vendeur.")
    if jour > date.today():
        raise HTTPException(422, "La date du paiement ne peut pas être dans le futur.")
    du = compte_vendeur(db, copro, m)["du"]
    if montant > du:
        raise HTTPException(422, f"Le vendeur ne doit plus que {du:.2f} € : un paiement plus élevé ne peut pas être porté "
                                 "à son compte.".replace(".", ",", 1))
    ex = _exercice(db, copro.id, jour.year)
    mv = Mouvement(copropriete_id=copro.id, exercice_id=ex.id, date=jour, type="encaissement", categorie="charges",
                   libelle=((libelle or "").strip() or f"Solde du vendeur ({m.vendeur_nom}) — vente du "
                            f"{m.date_acte:%d/%m/%Y}")[:300],
                   montant=montant, lot_id=m.lot_id, mutation_id=m.id)
    db.add(mv)
    db.flush()
    audit.enregistrer(db, "solde_vendeur_encaisse", user=user, copro_id=copro.id, request=request,
                      detail=f"{jour:%d/%m/%Y} {montant:.2f} € au compte de {m.vendeur_nom} (vente du {m.date_acte:%d/%m/%Y})")
    return mv


def vue(db: Session, copro, m: Mutation) -> dict:
    from app.services import ensembles
    c = compte_vendeur(db, copro, m)
    limite = m.avis_mutation_le + timedelta(days=DELAI_OPPOSITION) if m.avis_mutation_le else None
    return {"id": m.id, "lot_id": m.lot_id, "lots": ensembles.libelle(ensembles.membres(db, m.lot)),
            "date_acte": m.date_acte, "vendeur_id": m.vendeur_id, "vendeur_nom": m.vendeur_nom,
            "acquereur_id": m.acquereur_id, "acquereur_nom": m.acquereur_nom, "notaire": m.notaire,
            "notifiee_le": m.notifiee_le, "avis_mutation_le": m.avis_mutation_le, "opposition_le": m.opposition_le,
            "opposition_avant_le": limite, "notes": m.notes, "derniere": derniere(db, m.lot).id == m.id,
            "compte_vendeur": c}


def liste(db: Session, copro) -> list[dict]:
    return [vue(db, copro, m) for m in db.query(Mutation).filter(Mutation.copropriete_id == copro.id)
            .order_by(Mutation.date_acte.desc(), Mutation.id.desc())]

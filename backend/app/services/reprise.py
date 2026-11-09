"""Reprise de l'historique : base, points de contrôle, appels « Reprise de solde ».

- Un état est daté du 31 décembre (exercice = année civile), jamais dans le futur.
- Un état en brouillon n'a aucun effet.
- BASE = l'état validé le plus ancien. Il génère un appel « Reprise de solde au JJ/MM/AAAA » par
  exercice d'origine, émis et échu à sa date, rattaché à cet exercice (pour l'art. 19-2 : restants
  dus des exercices approuvés ou non). Tout appel émis et tout encaissement daté jusqu'à la date
  de la base est COUVERT par elle : il reste visible mais n'entre plus dans les soldes.
- POINT DE CONTRÔLE = un état validé plus récent : pour chaque lot, base + parts des appels émis
  sur la période − encaissements de la période doit lui être égal. Sinon : validation refusée.
- Valider un état plus ancien que la base (remonter d'une année) : tous les états validés plus
  récents doivent tomber juste à partir de lui. Il devient la base, les appels de reprise de
  l'ancienne base sont supprimés et les siens générés. Les soldes ne bougent pas : le contrôle
  garantit que chaque lot devait la même somme à la date de l'ancienne base.
"""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.money import D, arrondi, somme
from app.models.appel import AppelFonds, AppelLot
from app.models.exercice import Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.models.reprise import EtatReprise
from app.models.user import UserCopro
from app.services import ensembles

PREFIXE_LIBELLE = "Reprise de solde"


def base(db: Session, copro_id: int) -> EtatReprise | None:
    return (db.query(EtatReprise)
            .filter(EtatReprise.copropriete_id == copro_id, EtatReprise.valide.is_(True))
            .order_by(EtatReprise.date).first())


def appel_compte(appel: AppelFonds, b: EtatReprise | None) -> bool:
    """L'appel entre-t-il dans les soldes ? (non couvert par la base, ou appel de la base)."""
    if b is None:
        return appel.reprise_etat_id is None
    if appel.reprise_etat_id is not None:
        return appel.reprise_etat_id == b.id
    return appel.date_emission > b.date


def encaissement_compte(m: Mouvement, b: EtatReprise | None) -> bool:
    return b is None or m.date > b.date


def roles(db: Session, copro_id: int) -> tuple[EtatReprise | None, list[EtatReprise]]:
    etats = (db.query(EtatReprise).filter(EtatReprise.copropriete_id == copro_id)
             .order_by(EtatReprise.date).all())
    return base(db, copro_id), etats


def role(etat: EtatReprise, b: EtatReprise | None) -> str:
    if not etat.valide:
        return "brouillon"
    return "base" if b is not None and etat.id == b.id else "point_de_controle"


def _par_lot(etat: EtatReprise) -> dict[int, Decimal]:
    total: dict[int, Decimal] = defaultdict(lambda: D(0))
    for l in etat.lignes:
        total[l.lot_id] += D(l.montant_charges or 0) + D(l.montant_fonds_travaux or 0)
    return total


def controle(db: Session, copro_id: int, depart: EtatReprise, cible: EtatReprise) -> dict:
    """Solde calculé de chaque lot à la date de `cible`, à partir de `depart`, comparé à `cible`."""
    calcule = _par_lot(depart)
    parts = (db.query(AppelLot, AppelFonds).join(AppelFonds, AppelLot.appel_id == AppelFonds.id)
             .join(Exercice, AppelFonds.exercice_id == Exercice.id)
             .filter(Exercice.copropriete_id == copro_id, AppelFonds.reprise_etat_id.is_(None),
                     AppelFonds.date_emission > depart.date, AppelFonds.date_emission <= cible.date)
             .all())
    for p, _ in parts:
        calcule[p.lot_id] += D(p.montant_charges or 0) + D(p.montant_fonds_travaux or 0)
    for m in (db.query(Mouvement).filter(Mouvement.copropriete_id == copro_id,
                                         Mouvement.type == "encaissement", Mouvement.lot_id.isnot(None),
                                         Mouvement.date > depart.date, Mouvement.date <= cible.date)):
        calcule[m.lot_id] -= D(m.montant or 0)
    attendu = _par_lot(cible)
    lots = db.query(Lot).filter(Lot.copropriete_id == copro_id).order_by(Lot.id).all()
    lignes = []
    # Lots non séparables (lot principal + annexes) : comparés ensemble. Le copropriétaire paie
    # souvent l'ensemble sur le lot principal ; lot par lot, on verrait des écarts qui se compensent.
    for groupe in ensembles.ensembles(db, copro_id, lots):
        a = arrondi(somme(attendu[l.id] for l in groupe))
        c = arrondi(somme(calcule[l.id] for l in groupe))
        lignes.append({"lot_id": groupe[0].id, "lot_numero": groupe[0].numero,
                       "libelle": ensembles.libelle(groupe), "annexes": [l.numero for l in groupe[1:]],
                       "attendu": a, "calcule": c, "ecart": arrondi(a - c)})
    ecarts = [l for l in lignes if l["ecart"] != 0]
    return {"date": cible.date, "depart": depart.date, "ok": not ecarts,
            "ecart_total": arrondi(somme(l["ecart"] for l in lignes)), "lignes": lignes}


def paires(db: Session, copro_id: int, etat: EtatReprise) -> list[tuple[EtatReprise, EtatReprise]]:
    """(départ, arrivée) des contrôles qui concernent `etat`."""
    b, etats = roles(db, copro_id)
    if b is not None and etat.date > b.date:
        return [(b, etat)]
    if b is not None and etat.id == b.id:
        depart = etat
    elif b is None or etat.date < b.date:
        depart = etat            # candidat à devenir la base
    else:
        return []
    return [(depart, e) for e in etats if e.valide and e.date > depart.date and e.id != etat.id]


def controles(db: Session, copro_id: int, etat: EtatReprise) -> list[dict]:
    """Contrôles qui conditionnent (ou ont conditionné) la validation de `etat`."""
    return [controle(db, copro_id, d, c) for d, c in paires(db, copro_id, etat)]


# ---------------------------------------------------------------- banque
COMPTES = (("syndicat", "solde_banque"), ("fonds_travaux", "solde_banque_fonds"))


def _compte(m: Mouvement) -> str:
    """Le fonds de travaux a son compte dédié ; tout le reste passe par le compte du syndicat."""
    return "fonds_travaux" if m.categorie == "fonds_travaux" else "syndicat"


def _flux(db: Session, copro_id: int, apres: date | None, jusqu_a: date | None) -> dict:
    """Encaissements et dépenses par compte, datés après `apres` (exclu) et jusqu'à `jusqu_a` (inclus)."""
    q = db.query(Mouvement).filter(Mouvement.copropriete_id == copro_id)
    if apres is not None:
        q = q.filter(Mouvement.date > apres)
    if jusqu_a is not None:
        q = q.filter(Mouvement.date <= jusqu_a)
    flux = {c: {"encaissement": D(0), "depense": D(0)} for c, _ in COMPTES}
    for m in q:
        if m.type in ("encaissement", "depense"):
            flux[_compte(m)][m.type] += D(m.montant or 0)
    return flux


def controle_banque(db: Session, copro_id: int, depart: EtatReprise, cible: EtatReprise) -> list[dict]:
    """Pour chaque compte dont le solde est saisi aux deux dates : départ + encaissements − dépenses
    de la période, comparé au solde saisi. Un écart avertit, il ne bloque pas la validation."""
    flux = _flux(db, copro_id, depart.date, cible.date)
    out = []
    for compte, champ in COMPTES:
        d, saisi = getattr(depart, champ), getattr(cible, champ)
        if d is None or saisi is None:
            continue
        f = flux[compte]
        calcule = arrondi(D(d) + f["encaissement"] - f["depense"])
        ecart = arrondi(D(saisi) - calcule)
        out.append({"compte": compte, "depart": depart.date, "date": cible.date, "solde_depart": arrondi(D(d)),
                    "encaissements": arrondi(f["encaissement"]), "depenses": arrondi(f["depense"]),
                    "calcule": calcule, "saisi": arrondi(D(saisi)), "ecart": ecart, "ok": ecart == 0})
    return out


def controles_banque(db: Session, copro_id: int, etat: EtatReprise) -> list[dict]:
    return [c for d, e in paires(db, copro_id, etat) for c in controle_banque(db, copro_id, d, e)]


def tresorerie(db: Session, copro_id: int) -> dict:
    """Solde actuel de chaque compte : solde saisi dans la base + mouvements datés après elle ; sans
    solde de base pour ce compte, somme de tous ses mouvements (comme avant la reprise)."""
    b = base(db, copro_id)
    out = {}
    for compte, champ in COMPTES:
        depart = getattr(b, champ) if b is not None else None
        f = _flux(db, copro_id, b.date if depart is not None else None, None)[compte]
        out[compte] = arrondi(D(depart or 0) + f["encaissement"] - f["depense"])
    return out


def _message_ecarts(ctrls: list[dict]) -> str:
    morceaux = []
    for c in ctrls:
        if c["ok"]:
            continue
        lots = ", ".join(f"{l['libelle'] if l['annexes'] else 'lot ' + l['lot_numero']} : "
                         f"{l['ecart']:+.2f} €".replace(".", ",")
                         for l in c["lignes"] if l["ecart"] != 0)
        morceaux.append(f"au {c['date']:%d/%m/%Y}, écart sur {lots}")
    return ("Contrôle non concordant " + " ; ".join(morceaux) +
            ". Vérifiez l'état saisi, les appels et les encaissements de la période.")


def supprimer_appels(db: Session, etat: EtatReprise) -> None:
    appels = db.query(AppelFonds).filter(AppelFonds.reprise_etat_id == etat.id).all()
    ids = [a.id for a in appels]
    if ids:
        # Un encaissement rattaché à un appel de reprise est conservé, délié.
        (db.query(Mouvement).filter(Mouvement.appel_id.in_(ids))
         .update({Mouvement.appel_id: None}, synchronize_session=False))
    for a in appels:
        db.delete(a)
    db.flush()


def generer_appels(db: Session, etat: EtatReprise) -> None:
    par_exercice: dict[int, list] = defaultdict(list)
    for l in etat.lignes:
        if D(l.montant_charges or 0) != 0 or D(l.montant_fonds_travaux or 0) != 0:
            par_exercice[l.exercice_origine].append(l)
    for annee in sorted(par_exercice):
        ex = (db.query(Exercice).filter(Exercice.copropriete_id == etat.copropriete_id,
                                        Exercice.annee == annee).first())
        if ex is None:
            ex = Exercice(copropriete_id=etat.copropriete_id, annee=annee, cloture=True)
            db.add(ex)
            db.flush()
        lignes = par_exercice[annee]
        charges = arrondi(somme(D(l.montant_charges or 0) for l in lignes))
        fonds = arrondi(somme(D(l.montant_fonds_travaux or 0) for l in lignes))
        appel = AppelFonds(
            exercice_id=ex.id, reprise_etat_id=etat.id,
            libelle=f"{PREFIXE_LIBELLE} au {etat.date:%d/%m/%Y}, exercice {annee}",
            date_emission=etat.date, date_echeance=etat.date,
            montant_total=arrondi(charges + fonds), inclut_fonds_travaux=fonds != 0,
            fonds_travaux_montant=fonds,
        )
        db.add(appel)
        db.flush()
        for l in lignes:
            db.add(AppelLot(appel_id=appel.id, lot_id=l.lot_id, montant_charges=l.montant_charges,
                            montant_fonds_travaux=l.montant_fonds_travaux))
    db.flush()


def valider(db: Session, copro_id: int, etat: EtatReprise) -> str:
    """Valide l'état ; renvoie son rôle (« base » ou « point_de_controle »)."""
    if etat.valide:
        raise HTTPException(409, f"L'état au {etat.date:%d/%m/%Y} est déjà validé.")
    b = base(db, copro_id)
    ctrls = controles(db, copro_id, etat)
    if any(not c["ok"] for c in ctrls):
        raise HTTPException(422, _message_ecarts(ctrls))
    etat.valide = True
    etat.valide_le = datetime.now()
    if b is None or etat.date < b.date:
        if b is not None:
            supprimer_appels(db, b)
        generer_appels(db, etat)
        return "base"
    return "point_de_controle"


def controler_saisie(db: Session, copro_id: int, jour: date, lignes: list) -> None:
    """Date au 31/12 et passée ; lots de la copropriété ; exercice ≤ année ; pas de doublon."""
    if (jour.month, jour.day) != (12, 31):
        raise HTTPException(422, "Un état de reprise est arrêté au 31 décembre (fin d'exercice).")
    if jour > date.today():
        raise HTTPException(422, "Un état de reprise ne peut pas être daté dans le futur.")
    lots = {l.id for l in db.query(Lot).filter(Lot.copropriete_id == copro_id)}
    membres = {u.user_id for u in db.query(UserCopro).filter(UserCopro.copropriete_id == copro_id)}
    vus = set()
    for l in lignes:
        if l.lot_id not in lots:
            raise HTTPException(422, f"Lot {l.lot_id} inconnu dans cette copropriété.")
        if l.proprietaire_id is not None and l.proprietaire_id not in membres:
            raise HTTPException(422, "Le copropriétaire indiqué n'est pas membre de cette copropriété.")
        if not 1900 <= l.exercice_origine <= jour.year:
            raise HTTPException(422, f"Exercice d'origine {l.exercice_origine} invalide pour un état "
                                     f"au 31/12/{jour.year}.")
        cle = (l.lot_id, l.exercice_origine)
        if cle in vus:
            raise HTTPException(422, f"Deux lignes pour le même lot et l'exercice {l.exercice_origine}.")
        vus.add(cle)

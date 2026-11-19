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
from app.models.reprise import EtatReprise, SoldeBancaire
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
# Comptes bancaires : nom dans les réponses → colonne de SoldeBancaire.
COMPTES = (("syndicat", "solde_syndicat"), ("fonds_travaux", "solde_fonds"))


def _compte(m: Mouvement) -> str:
    """Le fonds de travaux a son compte dédié ; tout le reste passe par le compte du syndicat."""
    return "fonds_travaux" if m.categorie == "fonds_travaux" else "syndicat"


def _flux(db: Session, copro_id: int, apres: date | None, jusqu_a: date | None) -> dict:
    """Encaissements et dépenses par compte, datés après `apres` (exclu) et jusqu'à `jusqu_a` (inclus)."""
    from app.services.factures import date_banque
    q = db.query(Mouvement).filter(Mouvement.copropriete_id == copro_id)
    flux = {c: {"encaissement": D(0), "depense": D(0)} for c, _ in COMPTES}
    for m in q:
        # Avance payée par une personne, déduction de ses charges, facture pas encore réglée : rien n'est
        # passé par la banque. Facture réglée après sa date : la banque la voit à la date du paiement.
        if m.type not in ("encaissement", "depense") or m.hors_banque or m.a_payer:
            continue
        jour = date_banque(m)
        if (apres is not None and jour <= apres) or (jusqu_a is not None and jour > jusqu_a):
            continue
        flux[_compte(m)][m.type] += D(m.montant or 0)
    return flux


def soldes_banque(db: Session, copro_id: int, jour: date) -> dict:
    """Relevé saisi au `jour` (31/12) : {"syndicat": Decimal | None, "fonds_travaux": Decimal | None}."""
    s = (db.query(SoldeBancaire)
         .filter(SoldeBancaire.copropriete_id == copro_id, SoldeBancaire.date == jour).first())
    return {compte: (getattr(s, col) if s is not None else None) for compte, col in COMPTES}


def ecrire_soldes_banque(db: Session, copro_id: int, jour: date, syndicat, fonds) -> dict:
    """Saisit (ou efface, si les deux sont None) le relevé au `jour`. Renvoie l'ancien relevé."""
    avant = soldes_banque(db, copro_id, jour)
    s = (db.query(SoldeBancaire)
         .filter(SoldeBancaire.copropriete_id == copro_id, SoldeBancaire.date == jour).first())
    if syndicat is None and fonds is None:
        if s is not None:
            db.delete(s)
    else:
        if s is None:
            s = SoldeBancaire(copropriete_id=copro_id, date=jour)
            db.add(s)
        s.solde_syndicat, s.solde_fonds = syndicat, fonds
    db.flush()
    return avant


def controle_banque(db: Session, copro_id: int, depart: EtatReprise, cible: EtatReprise) -> list[dict]:
    """Pour chaque compte dont le solde est saisi aux deux dates : départ + encaissements − dépenses
    de la période, comparé au solde saisi. Un écart avertit, il ne bloque pas la validation."""
    flux = _flux(db, copro_id, depart.date, cible.date)
    sd, sc = soldes_banque(db, copro_id, depart.date), soldes_banque(db, copro_id, cible.date)
    out = []
    for compte, _ in COMPTES:
        d, saisi = sd[compte], sc[compte]
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
    sb = soldes_banque(db, copro_id, b.date) if b is not None else {c: None for c, _ in COMPTES}
    out = {}
    for compte, _ in COMPTES:
        depart = sb[compte]
        f = _flux(db, copro_id, b.date if depart is not None else None, None)[compte]
        out[compte] = arrondi(D(depart or 0) + f["encaissement"] - f["depense"])
    # Date du solde bancaire de départ (None : aucun saisi, la trésorerie part de 0).
    out["depuis"] = b.date if b is not None and any(v is not None for v in sb.values()) else None
    return out


def soldes_annuels(db: Session, copro_id: int) -> dict:
    """Une ligne par 1er janvier (relevé au 31/12 de l'année précédente), de la première année utile
    à l'année en cours. Pour chaque compte : relevé, opérations de l'année écoulée, solde calculé
    depuis le point d'ancrage, écart, et écart de l'année (variation à la banque − opérations
    saisies), qui désigne l'année où il manque quelque chose."""
    releves = {s.date: s for s in db.query(SoldeBancaire).filter(SoldeBancaire.copropriete_id == copro_id)}
    etats = db.query(EtatReprise.date).filter(EtatReprise.copropriete_id == copro_id).all()
    premiere = db.query(Mouvement.date).filter(Mouvement.copropriete_id == copro_id).order_by(Mouvement.date).first()
    candidats = ([premiere[0].year] if premiere else []) + [d.year + 1 for d in releves] + [d.year + 1 for (d,) in etats]
    if not candidats:
        return {"ancre": {"date": None, "source": "zero"}, "lignes": []}
    annees = range(min(candidats), date.today().year + 1)

    # Point d'ancrage : base de l'historique avec relevé, sinon le plus ancien relevé, sinon 0.
    b = base(db, copro_id)
    if b is not None and b.date in releves:
        ancre, source = b.date, "base"
    elif releves:
        ancre, source = min(releves), "releve"
    else:
        ancre, source = None, "zero"

    def valeur(s, col):
        v = getattr(s, col) if s is not None else None
        return None if v is None else D(v)

    lignes = []
    for a in annees:
        jour, veille = date(a - 1, 12, 31), date(a - 2, 12, 31)
        annee_ecoulee = _flux(db, copro_id, veille, jour)
        if ancre is None:
            jusque = _flux(db, copro_id, None, jour)
        elif jour >= ancre:
            jusque = _flux(db, copro_id, ancre, jour)
        else:
            jusque = _flux(db, copro_id, jour, ancre)
        ligne = {"annee": a, "date": jour}
        for compte, col in COMPTES:
            base_ancre = valeur(releves.get(ancre), col) if ancre is not None else None
            f = jusque[compte]
            net = f["encaissement"] - f["depense"]
            calcule = D(base_ancre or 0) + (net if ancre is None or jour >= ancre else -net)
            releve = valeur(releves.get(jour), col)
            precedent = valeur(releves.get(veille), col)
            fa = annee_ecoulee[compte]
            ligne[compte] = {
                "releve": arrondi(releve) if releve is not None else None,
                "encaissements": arrondi(fa["encaissement"]), "depenses": arrondi(fa["depense"]),
                "calcule": arrondi(calcule),
                "ecart": arrondi(releve - calcule) if releve is not None else None,
                "ecart_annee": (arrondi((releve - precedent) - (fa["encaissement"] - fa["depense"]))
                                if releve is not None and precedent is not None else None),
            }
        lignes.append(ligne)
    return {"ancre": {"date": ancre, "source": source}, "lignes": lignes}


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

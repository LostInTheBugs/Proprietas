"""Résolutions types d'une AG annuelle (demande de Fred, 20/11/2026).

À la création d'une AG annuelle (ou plus tard, bouton « Résolutions types »), l'application propose les
résolutions habituelles, avec leur majorité (loi n° 65-557 du 10 juillet 1965) et un texte à compléter :

- pré-cochées : bureau de séance (président, scrutateurs, secrétaire — art. 24 ; décret n° 67-223, art. 15) ;
  approbation des comptes de l'exercice écoulé (art. 24, reliée à l'exercice : son adoption l'approuve) ;
  quitus au syndic (art. 24) ; budget prévisionnel de l'exercice suivant (art. 24 ; art. 14-1) ; cotisation au
  fonds de travaux (art. 25 ; art. 14-2) ;
- à cocher si besoin : ajustement du budget de l'exercice en cours (art. 24) ; désignation du syndic bénévole
  (art. 25 ; 3 ans au plus) ; élection du conseil syndical (art. 25) ; seuils de consultation du conseil
  syndical et de mise en concurrence (art. 25 ; art. 21) ; plan pluriannuel de travaux (art. 24 ; art. 14-2).

Les montants connus (dépenses de l'exercice écoulé, budget de l'exercice suivant, taux du fonds de travaux)
sont repris dans les textes ; le reste (« …… ») se complète avant l'envoi de la convocation.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.money import arrondi, somme
from app.models.ag import AG, Resolution
from app.models.exercice import BudgetLine, Exercice
from app.models.mouvement import Mouvement
from app.models.user import User, UserCopro

A_COMPLETER = "……"


def _eur(v) -> str:
    return f"{arrondi(D(v)):,.2f}".replace(",", " ").replace(".", ",") + " €"


def _exercice(db: Session, copro_id: int, annee: int) -> Exercice | None:
    return db.query(Exercice).filter(Exercice.copropriete_id == copro_id, Exercice.annee == annee).first()


def _budget(db: Session, ex: Exercice | None) -> D:
    if ex is None:
        return D(0)
    return arrondi(somme(D(b.montant or 0) for b in db.query(BudgetLine).filter(BudgetLine.exercice_id == ex.id)))


def _syndic(db: Session, copro_id: int) -> str:
    u = (db.query(User).join(UserCopro, UserCopro.user_id == User.id)
         .filter(UserCopro.copropriete_id == copro_id, User.role == "syndic", User.is_demo.isnot(True))
         .order_by(User.id).first())
    return (u.nom_complet or u.email) if u else A_COMPLETER


def modeles(db: Session, copro, jour: date) -> list[dict]:
    """Résolutions types pour une AG annuelle tenue le `jour`."""
    annee = jour.year
    ex_ecoule, ex_courant, ex_suivant = (_exercice(db, copro.id, annee - 1), _exercice(db, copro.id, annee),
                                         _exercice(db, copro.id, annee + 1))
    depenses = (arrondi(somme(D(m.montant or 0) for m in db.query(Mouvement).filter(
        Mouvement.exercice_id == ex_ecoule.id, Mouvement.type == "depense", Mouvement.categorie != "avance")))
        if ex_ecoule else D(0))
    budget_suivant = _budget(db, ex_suivant)
    budget_courant = _budget(db, ex_courant)
    taux = D(copro.fonds_travaux_taux_pct or 5)
    cotisation = arrondi(budget_suivant * taux / 100) if budget_suivant else None

    def m(code, libelle, texte, majorite="art24", nature="autre", coche=True, exercice_id=None, remarque=""):
        return {"code": code, "libelle": libelle, "texte": texte, "majorite": majorite, "nature": nature,
                "coche": coche, "exercice_id": exercice_id, "remarque": remarque}

    out = [
        m("president", "Élection du président de séance",
          f"L'assemblée générale élit en qualité de président(e) de séance : {A_COMPLETER}."),
        m("scrutateurs", "Élection du ou des scrutateurs",
          f"L'assemblée générale élit en qualité de scrutateur(s) : {A_COMPLETER}."),
        m("secretaire", "Désignation du secrétaire de séance",
          "L'assemblée générale désigne en qualité de secrétaire de séance : le syndic "
          "(décret n° 67-223 du 17 mars 1967, art. 15, sauf décision contraire de l'assemblée)."),
    ]
    if ex_ecoule is not None:
        out.append(m("comptes", f"Approbation des comptes de l'exercice {annee - 1}",
                     f"Après avoir pris connaissance des documents comptables joints à la convocation (compte de "
                     f"gestion et annexes), l'assemblée générale approuve les comptes de l'exercice {annee - 1} "
                     f"(du 1er janvier au 31 décembre {annee - 1}), dont les dépenses s'élèvent à {_eur(depenses)}.",
                     nature="approbation_comptes", exercice_id=ex_ecoule.id))
    else:
        out.append(m("comptes", f"Approbation des comptes de l'exercice {annee - 1}", "", nature="approbation_comptes",
                     coche=False, remarque=f"Pas d'exercice {annee - 1} dans Proprietas : créez-le (Comptes) pour "
                                           "proposer cette résolution."))
    out += [
        m("quitus", f"Quitus au syndic pour sa gestion de l'exercice {annee - 1}",
          f"L'assemblée générale donne quitus au syndic pour sa gestion de l'exercice {annee - 1}."),
        m("ajustement", f"Ajustement du budget prévisionnel de l'exercice {annee}",
          f"L'assemblée générale ajuste le budget prévisionnel de l'exercice {annee} à {A_COMPLETER} € "
          + (f"(budget voté : {_eur(budget_courant)})." if budget_courant else "."),
          nature="budget", coche=False),
        m("budget", f"Vote du budget prévisionnel de l'exercice {annee + 1}",
          f"L'assemblée générale approuve le budget prévisionnel de l'exercice {annee + 1} "
          f"(du 1er janvier au 31 décembre {annee + 1}), d'un montant de "
          f"{_eur(budget_suivant) if budget_suivant else A_COMPLETER + ' €'}, détaillé dans le document joint à la "
          "convocation. Les provisions sont appelées le premier jour de chaque trimestre, chacune égale au quart "
          "du budget (loi du 10 juillet 1965, art. 14-1).",
          nature="budget",
          remarque="" if budget_suivant else f"Saisissez le budget de l'exercice {annee + 1} dans Comptes : son montant "
                                             "sera repris ici."),
        m("fonds_travaux", f"Cotisation au fonds de travaux pour l'exercice {annee + 1}",
          f"Conformément à l'article 14-2 de la loi du 10 juillet 1965, l'assemblée générale fixe la cotisation "
          f"annuelle au fonds de travaux de l'exercice {annee + 1} à {taux:g} % du budget prévisionnel, soit "
          f"{_eur(cotisation) if cotisation is not None else A_COMPLETER + ' €'} (au moins 5 % du budget "
          "prévisionnel), appelée avec les provisions.",
          majorite="art25"),
        m("syndic", "Désignation du syndic bénévole",
          f"L'assemblée générale désigne en qualité de syndic non professionnel {_syndic(db, copro.id)}, "
          f"copropriétaire, pour une durée de {A_COMPLETER} mois (36 mois au plus), du {A_COMPLETER} au "
          f"{A_COMPLETER}. Le syndic exerce ses fonctions à titre bénévole.",
          majorite="art25", coche=False, remarque="À l'échéance du mandat du syndic."),
        m("conseil", "Élection des membres du conseil syndical",
          f"L'assemblée générale élit membres du conseil syndical, pour une durée de {A_COMPLETER} an(s) "
          f"(3 ans au plus) : {A_COMPLETER}.",
          majorite="art25", coche=False, remarque="À l'échéance des mandats, ou pour un premier conseil."),
        m("seuil_conseil", "Montant à partir duquel le conseil syndical est consulté",
          f"L'assemblée générale fixe à {A_COMPLETER} € TTC le montant des marchés et contrats à partir duquel la "
          "consultation du conseil syndical est obligatoire (loi du 10 juillet 1965, art. 21).",
          majorite="art25", coche=False, remarque="Une fois, puis seulement pour le changer."),
        m("seuil_concurrence", "Montant à partir duquel une mise en concurrence est obligatoire",
          f"L'assemblée générale fixe à {A_COMPLETER} € TTC le montant des marchés et contrats à partir duquel une "
          "mise en concurrence est obligatoire (loi du 10 juillet 1965, art. 21).",
          majorite="art25", coche=False, remarque="Une fois, puis seulement pour le changer."),
        m("pppt", "Plan pluriannuel de travaux",
          f"L'assemblée générale décide des modalités d'élaboration du projet de plan pluriannuel de travaux "
          f"(loi du 10 juillet 1965, art. 14-2) : {A_COMPLETER}.",
          coche=False),
    ]
    return out


def ajouter(db: Session, copro, ag: AG, codes: list[str]) -> list[Resolution]:
    """Crée les résolutions types choisies, numérotées à la suite des résolutions de l'AG."""
    if ag.type_ag == "consultation_ecrite":
        raise HTTPException(422, "Les résolutions types sont celles d'une assemblée générale, pas d'une consultation écrite.")
    disponibles = {r["code"]: r for r in modeles(db, copro, ag.date)}
    inconnus = [c for c in codes if c not in disponibles]
    if inconnus:
        raise HTTPException(422, f"Résolution type inconnue : {', '.join(inconnus)}.")
    choisies = [disponibles[c] for c in disponibles if c in codes]   # ordre du modèle, pas celui de la demande
    for r in choisies:
        if r["nature"] == "approbation_comptes" and r["exercice_id"] is None:
            raise HTTPException(422, r["remarque"])
    numero = max((r.numero or 0 for r in ag.resolutions), default=0)
    crees = []
    for r in choisies:
        numero += 1
        res = Resolution(ag_id=ag.id, numero=numero, libelle=r["libelle"], texte=r["texte"], majorite=r["majorite"],
                         nature=r["nature"], exercice_id=r["exercice_id"])
        db.add(res)
        crees.append(res)
    db.flush()
    return crees

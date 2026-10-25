"""Moteur de règles par pays — module France (V1).

Références :
- Loi n° 65-557 du 10 juillet 1965 (statut de la copropriété)
- Ordonnance n° 2019-1101 (régime des petites copropriétés, art. 41-8 et suiv.)
- Loi ALUR / ELAN : fonds de travaux obligatoire (plus d'exemption < 10 lots),
  taux minimum 5 % du budget prévisionnel ; avec PPT, au moins 2,5 % du PPT ET au moins 5 % du
  budget (art. 14-2-1) : le plus élevé des deux, pas leur somme.

Majorités (art. 24, 25, 26) :
- art24 : majorité des voix exprimées des copropriétaires présents, représentés
  ou ayant voté par correspondance (les abstentions ne comptent pas).
- art25 : majorité des voix de tous les copropriétaires (> 50 % des millièmes).
- art26 : double majorité — majorité des membres du syndicat représentant au moins
  les 2/3 des voix (les lots sont regroupés par copropriétaire).
- art25-1 : non adopté en art. 25 mais >= 1/3 des voix de tous → second vote art. 24.
- art26-1 : non adopté en art. 26 mais approuvé par la moitié des membres présents,
  représentés ou votant par correspondance, avec >= 1/3 des voix → second vote art. 25.
- unanimite : 100 % des voix de tous les copropriétaires.
- art22 al. 2 : un copropriétaire à > 50 % voit ses voix réduites à la somme
  des voix des autres copropriétaires.
- Régime « 2 copropriétaires » (art. 41-16) : si le nombre de membres
  (copropriétaires distincts) est <= 2, le copropriétaire détenant plus de la moitié des voix peut
  prendre seul les décisions de l'art. 24, et celui détenant au moins 2/3 des
  voix celles de l'art. 25 (budget et approbation des comptes exclus).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR
from fractions import Fraction

from app.core.money import D, arrondi, to_money, somme

MAJORITES = {
    "art24": {
        "label": "Majorité simple (art. 24)",
        "description": "Majorité des voix exprimées des présents, représentés ou ayant voté par correspondance (abstentions exclues).",
    },
    "art25": {
        "label": "Majorité absolue (art. 25)",
        "description": "Majorité des voix de tous les copropriétaires (> 50 % des millièmes).",
    },
    "art26": {
        "label": "Double majorité (art. 26)",
        "description": "Majorité des membres du syndicat représentant au moins les 2/3 des voix.",
    },
    "unanimite": {
        "label": "Unanimité",
        "description": "Tous les copropriétaires doivent voter pour.",
    },
}


def tantiemes_totaux(lots) -> int:
    return sum(l.tantiemes for l in lots) or 1000


def _membres(lots) -> dict:
    """Groupe les lots par propriétaire.

    Retourne un dict {owner_id_or_key: {lots: [...], voix: int}}.
    Un lot sans propriétaire reçoit la clé ``f"lot-{l.id}"``.
    """
    groups: dict[str, list] = {}
    for l in lots:
        key = l.proprietaire_id if l.proprietaire_id else f"lot-{l.id}"
        groups.setdefault(key, []).append(l)
    return {
        key: {"lots": ls, "voix": sum(l.tantiemes for l in ls)}
        for key, ls in groups.items()
    }


def _num(f: Fraction | int):
    """Convertit un Fraction en int ou float arrondi à 2 décimales."""
    if f.denominator == 1:
        return int(f)
    return float(round(f, 2))


def _vote_membre(owner_key, lots_by_member, votes) -> str:
    """Retourne le vote consolidé d'un membre.

    Règle : "pour" si au moins un lot "pour" et aucun "contre".
    "contre" dès qu'un lot est "contre". "abstention" si uniquement abstentions.
    "absent" si aucun vote.
    """
    poids = {l.id: l.tantiemes for l in lots_by_member.get(owner_key, {}).get("lots", [])}
    has_pour = False
    has_contre = False
    has_abstention = False
    for v in votes:
        if v.lot_id in poids:
            if v.voix == "pour":
                has_pour = True
            elif v.voix == "contre":
                has_contre = True
            elif v.voix == "abstention":
                has_abstention = True
    if has_contre:
        return "contre"
    if has_pour:
        return "pour"
    if has_abstention:
        return "abstention"
    return "absent"


def _reduction_art22(lots, membres: dict, total: int) -> tuple[dict, int, object]:
    """Poids de vote de chaque lot, après la réduction de l'art. 22 al. 2.

    Retourne (poids par lot_id en Fraction, total de référence, clé du membre réduit ou None).
    Pas de réduction en régime « 2 copropriétaires » (art. 41-16) : nb de membres <= 2.
    """
    poids = {l.id: Fraction(l.tantiemes) for l in lots}
    if len(membres) <= 2:
        return poids, total, None
    for owner_key, info in membres.items():
        voix = info["voix"]
        if voix * 2 > total:
            # Réduction : poids de chaque lot de ce membre * (total - voix) / voix
            ratio = Fraction(total - voix, voix)
            for l in info["lots"]:
                poids[l.id] = poids[l.id] * ratio
            return poids, 2 * (total - voix), owner_key
    return poids, total, None


def poids_de_vote(lots) -> dict:
    """Poids de vote de chaque lot ({lot_id: Fraction}), réduction art. 22 comprise.

    Mêmes poids que ceux qu'utilise calculer_statut_resolution : le PV s'en sert pour
    indiquer les voix des opposants, abstentionnistes et défaillants (décret 1967, art. 17).
    """
    return _reduction_art22(lots, _membres(lots), tantiemes_totaux(lots))[0]


def calculer_statut_resolution(resolution, lots, votes) -> dict:
    """Calcule le statut d'une résolution selon les règles françaises.

    Retourne un dict : {statut, pour, contre, abstention, total, quorum,
        reduction_art22, nb_membres, membres_pour, regime_deux, detail}
    """
    total = tantiemes_totaux(lots)

    # Regroupement par membre
    membres = _membres(lots)
    nb_membres = len(membres)

    regime_deux = nb_membres <= 2
    reduced_poids, total_ref, reduction_art22 = _reduction_art22(lots, membres, total)

    pour = sum(reduced_poids.get(v.lot_id, 0) for v in votes if v.voix == "pour")
    contre = sum(reduced_poids.get(v.lot_id, 0) for v in votes if v.voix == "contre")
    abst = sum(reduced_poids.get(v.lot_id, 0) for v in votes if v.voix == "abstention")

    # Comptage des membres pour
    membres_pour = 0
    presents = 0
    for owner_key in membres:
        v = _vote_membre(owner_key, membres, votes)
        if v == "pour":
            membres_pour += 1
        if v != "absent":
            presents += 1

    second_vote_possible = None

    if resolution.majorite == "art24":
        exprimes = pour + contre
        quorum = exprimes
        if regime_deux:
            adoptee = pour > total / 2
            detail = "Régime 2 copropriétaires (art. 41-16) : décision prise par le copropriétaire détenant plus de la moitié des voix."
        else:
            adoptee = exprimes > 0 and pour > exprimes / 2
            detail = "Majorité des voix exprimées (art. 24) : pour / (pour + contre) > 50 %."
    elif resolution.majorite == "art25":
        quorum = total_ref
        if regime_deux:
            adoptee = pour >= 2 * total / 3
            detail = "Régime 2 copropriétaires (art. 41-16) : décision prise par le copropriétaire détenant au moins 2/3 des voix."
        else:
            adoptee = pour > Fraction(total_ref, 2)
            detail = "Majorité des voix de tous les copropriétaires (art. 25) : pour > 50 % des millièmes."
            if not adoptee and pour * 3 >= total_ref:
                second_vote_possible = "art24"
                detail += " Passerelle art. 25-1 : second vote immédiat possible à la majorité de l'art. 24."
    elif resolution.majorite == "art26":
        quorum = total_ref
        adoptee = membres_pour * 2 > nb_membres and pour * 3 >= 2 * total_ref
        detail = "Double majorité (art. 26) : majorité des membres du syndicat représentant au moins les 2/3 des voix."
        if not regime_deux and not adoptee and presents > 0 and membres_pour * 2 >= presents and pour * 3 >= total_ref:
            second_vote_possible = "art25"
            detail += " Passerelle art. 26-1 : second vote immédiat possible à la majorité de l'art. 25."
    else:  # unanimite
        quorum = total_ref
        adoptee = pour == total_ref and contre == 0
        detail = "Unanimité requise : tous les copropriétaires doivent voter pour."

    if reduction_art22 is not None:
        detail += " Voix du copropriétaire majoritaire réduites à la somme des voix des autres (art. 22 al. 2)."

    statut = "adoptee" if adoptee else "rejetee"
    return {
        "statut": statut,
        "pour": _num(pour),
        "contre": _num(contre),
        "abstention": _num(abst),
        "total": total_ref,
        "quorum": quorum,
        "reduction_art22": reduction_art22,
        "nb_membres": nb_membres,
        "membres_pour": membres_pour,
        "regime_deux": regime_deux,
        "second_vote_possible": second_vote_possible,
        "detail": detail,
    }


def regles_fonds_travaux(copro) -> dict:
    """Recommandation légale sur le fonds de travaux (France)."""
    taux_min = 5.0
    return {
        "obligatoire": True,
        "taux_minimum_pct": taux_min,
        "texte": (
            "Fonds de travaux obligatoire (loi ALUR, modifiée) dès 10 ans après "
            "réception des travaux, quel que soit le nombre de lots. "
            "Cotisation annuelle minimale : 5 % du budget prévisionnel "
            "Si un plan pluriannuel de travaux (PPT) est adopté : au moins 2,5 % du montant des "
            "travaux du plan et au moins 5 % du budget, soit le plus élevé des deux montants "
            "(art. 14-2-1 ; les deux taux ne s'additionnent pas). "
            "Versement sur compte bancaire séparé, montant voté chaque année en AG "
            "(art. 25, repli art. 24 si 1/3 des voix au premier vote)."
        ),
    }


def _plus_fort_reste(montant: Decimal, lots) -> list[int]:
    """Répartir *montant* (en centimes) entre lots au prorata.

    Retourne une liste d'entiers (centimes) dont la somme est exactement
    montant, avec la méthode du plus fort reste.
    """
    total = tantiemes_totaux(lots)
    if total <= 0 or not lots:
        return []
    parts: list[int] = []
    fractions: list[Decimal] = []
    for lot in lots:
        brut = D(montant) * D(lot.tantiemes) / D(total)
        entier = int(brut.to_integral_value(rounding=ROUND_FLOOR))
        parts.append(entier)
        fractions.append(brut - D(entier))
    n_restes = int(montant) - sum(parts)
    indices_tries = sorted(range(len(fractions)), key=lambda i: fractions[i], reverse=True)
    for idx in indices_tries[:n_restes]:
        parts[idx] += 1
    return parts


def repartir_par_tantiemes(montant, lots, fonds_travaux_taux: Decimal = D(0)) -> list:
    """Répartit un montant entre les lots au prorata des millièmes.

    Retourne une liste de dicts {lot, montant_charges, montant_fonds_travaux?}.
    Méthode du plus fort reste — tout reste en Decimal.
    Le fonds de travaux est arrondi une seule fois, puis réparti.
    """
    montant = to_money(montant)
    fonds_travaux_taux = D(fonds_travaux_taux or 0)
    charges = _plus_fort_reste(montant * D(100), lots)
    parts: list[dict] = []
    for i, lot in enumerate(lots):
        euros = arrondi(D(charges[i]) / D(100))
        parts.append({"lot": lot, "montant_charges": euros})
    if fonds_travaux_taux > D(0):
        fonds_total = _plus_fort_reste(arrondi(montant * fonds_travaux_taux / D(100)) * D(100), lots)
        for i, p in enumerate(parts):
            p["montant_fonds_travaux"] = arrondi(D(fonds_total[i]) / D(100))
    return parts


# ---------------------------------------------------------------- petite copropriété (art. 41-8)
# Loi n° 65-557, art. 41-8 : régime simplifié si la copropriété compte au plus 5 lots à usage
# de logements, de bureaux ou de commerces, OU si son budget prévisionnel moyen sur une période
# de 3 exercices consécutifs est inférieur à 15 000 €.
TYPES_LOT = ("appartement", "maison", "bureau", "commerce", "cave", "parking", "annexe", "autre")
# Annexes : ne comptent pas parmi les lots principaux. « autre » compte, par prudence : le régime
# simplifié allège les règles (comptabilité, consultation écrite), mieux vaut ne pas l'appliquer à tort.
TYPES_LOT_ANNEXES = ("cave", "parking", "annexe")
PETITE_COPRO_MAX_LOTS = 5
PETITE_COPRO_SEUIL_BUDGET = Decimal("15000")


def nb_lots_principaux(lots) -> int:
    """Nombre de lots à usage de logements, de bureaux ou de commerces (annexes exclues)."""
    return sum(1 for lot in lots if (lot.type or "") not in TYPES_LOT_ANNEXES)


def budget_moyen_3_exercices(budgets: dict) -> Decimal | None:
    """Moyenne du budget prévisionnel sur les 3 derniers exercices CONSÉCUTIFS.

    `budgets` = {année: total du budget prévisionnel}, pour les seuls exercices qui ont un
    budget (> 0). On part de la dernière année budgétée N : N-1 et N-2 doivent l'être aussi.
    Sinon None : le critère du budget n'est pas rempli (et non une moyenne de 0 ou sur 2 ans).
    """
    annees = sorted((a for a, m in budgets.items() if m and m > 0), reverse=True)
    if not annees:
        return None
    n = annees[0]
    if not all(a in budgets and budgets[a] > 0 for a in (n - 1, n - 2)):
        return None
    return arrondi(somme(budgets[a] for a in (n, n - 1, n - 2)) / 3)


def regime_petite_copro(lots, budgets: dict) -> dict:
    """Art. 41-8 : {"petite": bool, "nb_lots_principaux": int, "budget_moyen": Decimal | None}."""
    principaux = nb_lots_principaux(lots)
    moyen = budget_moyen_3_exercices(budgets)
    petite = principaux <= PETITE_COPRO_MAX_LOTS or (moyen is not None and moyen < PETITE_COPRO_SEUIL_BUDGET)
    return {"petite": petite, "nb_lots_principaux": principaux, "budget_moyen": moyen}


# ---------------------------------------------------------------- consultation écrite (art. 41-12)
# Loi n° 65-557, art. 41-12 : dans une petite copropriété, les décisions peuvent être prises sans
# assemblée générale, par consultation écrite, à l'UNANIMITÉ des voix de tous les copropriétaires ;
# sauf le vote du budget prévisionnel et l'approbation des comptes.
TYPES_AG = ("annuelle", "extraordinaire", "consultation_ecrite")
NATURES_RESOLUTION = {
    "autre": "Autre décision",
    "budget": "Vote du budget prévisionnel",
    "approbation_comptes": "Approbation des comptes",
}
NATURES_EXCLUES_CONSULTATION = ("budget", "approbation_comptes")


def refus_consultation_ecrite(majorite: str, nature: str) -> str | None:
    """Motif de refus d'une résolution en consultation écrite (None si elle est conforme)."""
    if nature in NATURES_EXCLUES_CONSULTATION:
        return (f"{NATURES_RESOLUTION[nature]} : impossible par consultation écrite (art. 41-12 de la loi "
                "du 10 juillet 1965). Réunissez une assemblée générale.")
    if majorite != "unanimite":
        return ("Consultation écrite : la décision exige l'unanimité des voix de tous les "
                "copropriétaires (art. 41-12 de la loi du 10 juillet 1965).")
    return None

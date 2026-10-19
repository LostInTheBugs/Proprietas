"""Moteur de règles par pays — module France (V1).

Références :
- Loi n° 65-557 du 10 juillet 1965 (statut de la copropriété)
- Ordonnance n° 2019-1101 (régime des petites copropriétés, art. 41-8 et suiv.)
- Loi ALUR / ELAN : fonds de travaux obligatoire (plus d'exemption < 10 lots),
  taux minimum 5 % du budget prévisionnel (ou 2,5 % du PPT + 5 % budget avec PPT).

Majorités (art. 24, 25, 26) :
- art24 : majorité des voix exprimées des copropriétaires présents, représentés
  ou ayant voté par correspondance (les abstentions ne comptent pas).
- art25 : majorité des voix de tous les copropriétaires (> 50 % des millièmes).
- art26 : majorité des 2/3 des voix de tous les copropriétaires.
- unanimite : 100 % des voix de tous les copropriétaires.
- art22 al. 2 : un copropriétaire à > 50 % voit ses voix réduites à la somme
  des voix des autres copropriétaires.
- Régime « 2 copropriétaires » (art. 41-16) : si le nombre de copropriétaires
  distincts est <= 2, le copropriétaire détenant plus de la moitié des voix peut
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


def nb_coproprietaires(lots) -> int:
    """Nombre de copropriétaires distincts (par lot avec propriétaire)."""
    owners = {l.proprietaire_id for l in lots if l.proprietaire_id}
    return len(owners)


def _membres(lots) -> dict:
    """Groupe les lots par propriétaire.

    Retourne un dict {owner_id_or_key: {lots: [...], voix: int}}.
    Un lot sans propriétaire reçoit la clé ``f"lot-{l.id}"``.
    """
    groups: dict[str, list[Lot]] = {}
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


def calculer_statut_resolution(resolution, lots, votes) -> dict:
    """Calcule le statut d'une résolution selon les règles françaises.

    Retourne un dict : {statut, pour, contre, abstention, total, quorum,
        reduction_art22, nb_membres, membres_pour, regime_deux, detail}
    """
    total = tantiemes_totaux(lots)

    # Regroupement par membre
    membres = _membres(lots)
    nb_membres = len(membres)

    # Poids en Fraction pour précision exacte
    poids = {l.id: Fraction(l.tantiemes) for l in lots}

    # Recherche d'un membre majoritaire (art. 22 al. 2)
    reduction_art22 = None
    total_ref = total
    reduced_poids = dict(poids)

    nb_owners = nb_coproprietaires(lots)
    regime_deux = nb_owners <= 2

    if not regime_deux:
        for owner_key, info in membres.items():
            voix = info["voix"]
            if voix * 2 > total:
                # Réduction : poids de chaque lot de ce membre * (total - voix) / voix
                ratio = Fraction(total - voix, voix)
                for l in info["lots"]:
                    reduced_poids[l.id] = poids[l.id] * ratio
                total_ref = 2 * (total - voix)
                reduction_art22 = owner_key
                break

    pour = sum(reduced_poids.get(v.lot_id, 0) for v in votes if v.voix == "pour")
    contre = sum(reduced_poids.get(v.lot_id, 0) for v in votes if v.voix == "contre")
    abst = sum(reduced_poids.get(v.lot_id, 0) for v in votes if v.voix == "abstention")

    # Comptage des membres pour
    membres_pour = 0
    for owner_key in membres:
        if _vote_membre(owner_key, membres, votes) == "pour":
            membres_pour += 1

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
        quorum = total
        if regime_deux:
            adoptee = pour >= 2 * total / 3
            detail = "Régime 2 copropriétaires (art. 41-16) : décision prise par le copropriétaire détenant au moins 2/3 des voix."
        else:
            adoptee = pour > Fraction(total_ref, 2)
            detail = "Majorité des voix de tous les copropriétaires (art. 25) : pour > 50 % des millièmes."
            if reduction_art22 is not None:
                detail += " Voix du copropriétaire majoritaire réduites à la somme des voix des autres (art. 22 al. 2)."
    elif resolution.majorite == "art26":
        quorum = total
        adoptee = membres_pour * 2 > nb_membres and pour * 3 >= 2 * total_ref
        detail = "Double majorité (art. 26) : majorité des membres du syndicat représentant au moins les 2/3 des voix."
    else:  # unanimite
        quorum = total
        adoptee = pour == total_ref and contre == 0
        detail = "Unanimité requise : tous les copropriétaires doivent voter pour."

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
            "(ou 2,5 % du plan pluriannuel de travaux + 5 % du budget si PPT voté). "
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

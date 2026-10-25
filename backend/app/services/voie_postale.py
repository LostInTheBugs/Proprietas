"""Voie électronique / voie postale des notifications et mises en demeure.

Décret n° 67-223 du 17 mars 1967, rédaction du décret n° 2025-1292 du 22 décembre 2025 :
- art. 64 : la voie électronique (lettre recommandée électronique ou prestataire qualifié)
  est la règle ;
- art. 64-1 : « par exception », la LRAR, lorsque le copropriétaire a demandé à recevoir
  les notifications par voie postale ;
- art. 64-4 : la demande prend effet le neuvième jour suivant sa réception par le syndic,
  ou le jour même si elle est formulée en assemblée générale.

users.notification_postale_depuis contient la DATE D'EFFET de la demande. Pendant les neuf
jours qui suivent la réception, la LRE reste valable, et la LRAR (demandée) l'est aussi.
"""
from datetime import date, timedelta

from fastapi import HTTPException

DELAI_EFFET_JOURS = 9


def date_effet(recue_le: date, en_assemblee: bool = False) -> date:
    return recue_le if en_assemblee else recue_le + timedelta(days=DELAI_EFFET_JOURS)


def modes_admis(user, jour: date) -> tuple[str, ...]:
    """Modes valables pour notifier `user` à la date `jour`."""
    if user is None or not user.notification_postale:
        return ("lre",)
    effet = user.notification_postale_depuis
    if effet is None or effet <= jour:
        return ("lrar",)
    return ("lre", "lrar")


def controler_mode(user, mode: str, jour: date, nom: str) -> None:
    """Lève une 422 si `mode` n'est pas valable pour notifier `user` le `jour` donné.
    Sans destinataire connu (lot sans propriétaire, compte supprimé), rien n'est contrôlé."""
    if user is None or mode in modes_admis(user, jour):
        return
    if mode == "lrar":
        raise HTTPException(422, f"{nom} n'a pas demandé la voie postale : la notification se fait par "
                                 "lettre recommandée électronique (décret n° 67-223, art. 64 et 64-1).")
    effet = user.notification_postale_depuis
    quand = f" (en vigueur depuis le {effet:%d/%m/%Y})" if effet else ""
    raise HTTPException(422, f"{nom} a demandé la voie postale{quand} : notification par LRAR "
                             "obligatoire (loi n° 65-557, art. 42-1 ; décret, art. 64-1 et 64-4).")

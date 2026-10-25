"""Notification du procès-verbal (loi n° 65-557, art. 42 al. 2 et 42-1).

- Qui : les copropriétaires OPPOSANTS ou DÉFAILLANTS à au moins une résolution votée
  (l'abstention n'est pas une opposition). Un lot sans propriétaire ne peut pas être notifié :
  il est signalé.
- Comment : lettre recommandée électronique (règle) ; LRAR si le copropriétaire a demandé
  la voie postale (users.notification_postale).
- Quand : dans le mois qui suit l'assemblée. La notification fait courir le délai de
  contestation de deux mois, à compter du lendemain de la première présentation (LRAR) ou de
  l'avis électronique (LRE). Les dates calculées ici sont INDICATIVES (report d'un délai qui
  expire un samedi, un dimanche ou un jour férié : non géré).
"""
from calendar import monthrange
from datetime import date

from sqlalchemy.orm import Session

from app.models.lot import Lot
from app.models.notification import NotificationPV
from app.models.copropriete import Copropriete
from app.models.user import User
from app.services import delais, voie_postale


def ajouter_mois(d: date, n: int) -> date:
    """Même quantième n mois plus tard (le 31/01 + 1 mois → le 28 ou 29/02)."""
    an, mois = divmod(d.month - 1 + n, 12)
    an, mois = d.year + an, mois + 1
    return date(an, mois, min(d.day, monthrange(an, mois)[1]))


def _libelle(r) -> str:
    return f"{r.numero} (second vote)" if r.second_vote_de_id is not None else str(r.numero)


def destinataires(db: Session, ag) -> tuple[list[dict], list[str]]:
    """(copropriétaires à notifier, numéros des lots sans propriétaire concernés)."""
    lots = db.query(Lot).filter(Lot.copropriete_id == ag.copropriete_id).all()
    membres: dict = {}
    for lot in lots:
        membres.setdefault(lot.proprietaire_id, []).append(lot)
    # Seules les résolutions effectivement votées (au moins un vote exprimé) comptent.
    votees = [r for r in sorted(ag.resolutions, key=lambda x: (x.numero, x.second_vote_de_id or 0))
              if any(v.voix in ("pour", "contre", "abstention") for v in r.votes)]
    sortie, sans_proprietaire = [], []
    for user_id, ls in membres.items():
        opposant, defaillant = [], []
        for r in votees:
            voix = {v.lot_id: v.voix for v in r.votes}
            if any(voix.get(l.id) == "contre" for l in ls):
                opposant.append(_libelle(r))
            elif not any(voix.get(l.id) in ("pour", "contre", "abstention") for l in ls):
                defaillant.append(_libelle(r))
        if not (opposant or defaillant):
            continue
        if user_id is None:
            sans_proprietaire += [l.numero for l in ls]
            continue
        user = db.get(User, user_id)
        qualite = " et ".join(q for q, liste in (("opposant", opposant), ("défaillant", defaillant)) if liste)
        detail = " ; ".join(f"{q} : {', '.join(liste)}"
                            for q, liste in (("opposant", opposant), ("défaillant", defaillant)) if liste)
        sortie.append({"user": user, "nom": f"{user.nom} {user.prenom}".strip() if user else "",
                       "qualite": qualite, "resolutions": detail})
    sortie.sort(key=lambda d: d["nom"].lower())
    return sortie, sorted(sans_proprietaire)


def preparer(db: Session, ag) -> None:
    """Crée ou met à jour la liste. Une notification déjà envoyée n'est jamais modifiée ;
    une ligne non envoyée dont le copropriétaire n'est plus concerné est retirée."""
    existantes = {n.user_id: n for n in db.query(NotificationPV).filter(NotificationPV.ag_id == ag.id).all()}
    cibles, _ = destinataires(db, ag)
    vus = set()
    for c in cibles:
        user = c["user"]
        vus.add(user.id)
        n = existantes.get(user.id)
        if n is None:
            n = NotificationPV(ag_id=ag.id, user_id=user.id)
            db.add(n)
        if n.date_envoi is None:
            n.nom, n.qualite, n.resolutions = c["nom"], c["qualite"], c["resolutions"]
            n.mode = "lrar" if user.notification_postale else "lre"
    for user_id, n in existantes.items():
        if user_id not in vus and n.date_envoi is None:
            db.delete(n)
    db.commit()


def etat(db: Session, ag) -> dict:
    _, sans_proprietaire = destinataires(db, ag)
    # Envoi dans le mois : obligation du syndic, NON reportée (prudence).
    limite = ajouter_mois(ag.date, 1)
    copro = db.get(Copropriete, ag.copropriete_id)
    am = delais.est_alsace_moselle(copro.code_postal if copro else "")
    items = []
    for n in (db.query(NotificationPV).filter(NotificationPV.ag_id == ag.id)
              .order_by(NotificationPV.nom).all()):
        user = db.get(User, n.user_id) if n.user_id else None
        items.append({
            "id": n.id, "user_id": n.user_id, "nom": n.nom, "qualite": n.qualite,
            "resolutions": n.resolutions, "mode": n.mode, "date_envoi": n.date_envoi,
            "date_presentation": n.date_presentation, "reference": n.reference,
            # Contestation (2 mois) : fin reportée au premier jour ouvrable (CPC, art. 642).
            "fin_contestation": (delais.reporter(ajouter_mois(n.date_presentation, 2), am)
                                 if n.date_presentation else None),
            "en_retard": n.date_envoi is None and date.today() > limite,
            "voie_postale_demandee": bool(user and user.notification_postale),
            "modes_admis": list(voie_postale.modes_admis(user, date.today())) if user else ["lre", "lrar"],
        })
    return {"limite_envoi": limite, "sans_proprietaire": sans_proprietaire, "items": items}

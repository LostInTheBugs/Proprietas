"""Messages groupés du syndic aux copropriétaires (demande de Fred, 20/11/2026, revue de Perplexity).

- Destinataires : tous les copropriétaires, ceux d'une clé de répartition (lots qui y ont des millièmes), ou une
  sélection ; seulement les comptes qui ont une adresse e-mail. Un e-mail par personne : personne ne voit
  l'adresse des autres.
- Personnalisation : {prenom}, {nom}, {lots} sont remplacés pour chacun.
- C'est une **information** : une convocation ou une notification officielle passe par lettre recommandée
  (électronique ou papier). Le pied du message le rappelle.
- « Aperçu » montre les destinataires et le message du premier ; l'envoi est tracé (historique, journal d'audit).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core import audit
from app.models.cle import CleLot, CleRepartition
from app.models.lot import Lot
from app.models.message import Message
from app.models.user import User
from app.services import presences

MAX_SUJET = 200
MAX_CORPS = 10000
MAX_DESTINATAIRES = 300


def _lots(db: Session, copro_id: int, u: User) -> list[Lot]:
    return (db.query(Lot).filter(Lot.copropriete_id == copro_id, Lot.proprietaire_id == u.id)
            .order_by(Lot.numero).all())


def destinataires(db: Session, copro, cible: str, cle_id: int | None, ids: list[int]) -> tuple[list[User], str]:
    tous = presences.coproprietaires(db, copro.id)
    cle_nom = ""
    if cible == "tous":
        choisis = tous
    elif cible == "cle":
        cle = db.query(CleRepartition).filter(CleRepartition.id == cle_id,
                                              CleRepartition.copropriete_id == copro.id).first() if cle_id else None
        if cle is None:
            raise HTTPException(422, "Choisissez une clé de répartition de la copropriété.")
        cle_nom = cle.nom
        lots = {cl.lot_id for cl in db.query(CleLot).filter(CleLot.cle_id == cle.id, CleLot.tantiemes > 0)}
        proprios = {l.proprietaire_id for l in db.query(Lot).filter(Lot.id.in_(lots))} if lots else set()
        choisis = [u for u in tous if u.id in proprios]
    elif cible == "selection":
        voulus = set(ids or [])
        if not voulus or not voulus <= {u.id for u in tous}:
            raise HTTPException(422, "Choisissez des copropriétaires de la copropriété.")
        choisis = [u for u in tous if u.id in voulus]
    else:
        raise HTTPException(422, "Destinataires inconnus : tous, une clé ou une sélection.")
    return choisis, cle_nom


def personnaliser(texte: str, u: User, lots: list[Lot]) -> str:
    return (texte.replace("{prenom}", u.prenom or "").replace("{nom}", u.nom or "")
            .replace("{lots}", ", ".join(l.numero for l in lots)))


def pied(copro) -> str:
    return (f"\n\n—\nMessage d'information du syndic de la copropriété « {copro.nom} », envoyé avec Proprietas. "
            "Ce n'est pas une convocation ni une notification officielle (lettre recommandée).")


def _controler(sujet: str, corps: str) -> tuple[str, str]:
    sujet, corps = (sujet or "").strip(), (corps or "").strip()
    if not sujet or not corps:
        raise HTTPException(422, "Le sujet et le message sont obligatoires.")
    if len(sujet) > MAX_SUJET or len(corps) > MAX_CORPS:
        raise HTTPException(422, f"Sujet : {MAX_SUJET} caractères au plus ; message : {MAX_CORPS}.")
    return sujet, corps


def apercu(db: Session, copro, data) -> dict:
    sujet, corps = _controler(data.sujet, data.corps)
    choisis, cle_nom = destinataires(db, copro, data.cible, data.cle_id, data.ids)
    avec = [u for u in choisis if (u.email or "").strip()]
    exemple = avec[0] if avec else None
    return {"destinataires": [{"id": u.id, "nom": presences.nom(u), "email": bool((u.email or "").strip())} for u in choisis],
            "sans_email": [presences.nom(u) for u in choisis if not (u.email or "").strip()],
            "cle_nom": cle_nom,
            "exemple": ({"pour": presences.nom(exemple), "sujet": personnaliser(sujet, exemple, _lots(db, copro.id, exemple)),
                         "corps": personnaliser(corps, exemple, _lots(db, copro.id, exemple)) + pied(copro)}
                        if exemple else None)}


def envoyer(db: Session, copro, data, user, request) -> Message:
    from app.services.emailer import EmailError, config_smtp, envoyer_email
    sujet, corps = _controler(data.sujet, data.corps)
    if config_smtp(copro) is None:
        raise HTTPException(422, "Aucun serveur d'envoi : renseignez-le dans Réglages → Envoi des e-mails.")
    choisis, cle_nom = destinataires(db, copro, data.cible, data.cle_id, data.ids)
    avec = [u for u in choisis if (u.email or "").strip()]
    if not avec:
        raise HTTPException(422, "Aucun destinataire n'a d'adresse e-mail.")
    if len(avec) > MAX_DESTINATAIRES:
        raise HTTPException(422, f"{MAX_DESTINATAIRES} destinataires au plus par message.")
    envoyes, erreurs = 0, []
    for u in avec:
        lots = _lots(db, copro.id, u)
        try:
            envoyer_email(copro, u.email.strip(), personnaliser(sujet, u, lots), personnaliser(corps, u, lots) + pied(copro))
            envoyes += 1
        except EmailError as e:
            erreurs.append(f"{presences.nom(u)} : {e}")
    m = Message(copropriete_id=copro.id, auteur_id=user.id, envoye_le=datetime.now(), sujet=sujet, corps=corps,
                cible=data.cible, cle_nom=cle_nom, destinataires="; ".join(presences.nom(u) for u in avec),
                nb_envoyes=envoyes, erreurs="\n".join(erreurs))
    db.add(m)
    db.flush()
    audit.enregistrer(db, "message_groupe", user=user, copro_id=copro.id, request=request,
                      detail=f"« {sujet} » : {envoyes} envoyé(s)" + (f", {len(erreurs)} échec(s)" if erreurs else ""))
    return m


def historique(db: Session, copro) -> list[dict]:
    return [{"id": m.id, "envoye_le": m.envoye_le, "sujet": m.sujet, "corps": m.corps, "cible": m.cible,
             "cle_nom": m.cle_nom, "destinataires": [x for x in m.destinataires.split("; ") if x],
             "nb_envoyes": m.nb_envoyes, "erreurs": [x for x in m.erreurs.split("\n") if x]}
            for m in db.query(Message).filter(Message.copropriete_id == copro.id).order_by(Message.envoye_le.desc()).limit(100)]

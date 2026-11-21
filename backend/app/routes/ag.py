import html
import secrets
from datetime import date, datetime
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.deps import get_current_user, require_syndic
from app.models.user import User
from app.models.lot import Lot
from app.models.ag import AG, AgReponse, Resolution, Vote, AgCreneau, AgCreneauVote
from app.models.invitation import Invitation
from app.models.copropriete import Copropriete
from app.models.exercice import Exercice
from app.core.scoping import get_owned, get_owned_via
from app.routes.copro import get_or_create_copro
from app.services.country_rules import calculer_statut_resolution, refus_consultation_ecrite, MAJORITES
from app.services.regime import regime_copro
from app.core import audit
from app.services import presences
from app.routes.documents import _content_disposition
from app.services.emailer import (envoyer_email, convocation_sujet, convocation_texte, pv_email_texte,
                                  EmailError, adresse_publique)
from app.services.pv_pdf import generer_pv_pdf
from app.schemas import (
    ModeleResolutionOut, ResolutionsTypesIn,
    MaReponseOut, PersonneCourteOut, PresenceIn, PresencesOut, ReponseAgIn,
    AGIn, AGOut, ResolutionIn, ResolutionOut, VoteIn, VoteOut, ResolutionResult,
    CreneauIn, CreneauOut, CreneauVoteIn, CreneauVoteOut,
    InvitationOut, InvitationsResult,
)

router = APIRouter(prefix="/api", tags=["ag"])


def _resolution_out(db: Session, r: Resolution) -> ResolutionOut:
    from app.services import cles
    copro_id = r.ag.copropriete_id if r.ag else None
    lots, votes = cles.votants(db, copro_id, r) if copro_id else ([], [])
    resultat = calculer_statut_resolution(r, lots, votes)
    return ResolutionOut(
        id=r.id, ag_id=r.ag_id, numero=r.numero, libelle=r.libelle,
        texte=r.texte, majorite=r.majorite, nature=r.nature or "autre", exercice_id=r.exercice_id,
        statut=r.statut,
        second_vote_de_id=r.second_vote_de_id, amendee=bool(r.amendee), cle_id=r.cle_id,
        cle_nom=r.cle.nom if r.cle is not None else "",
        mandat_mois=r.mandat_mois, mandat_personnes=r.mandat_personnes,
        votes=[VoteOut.model_validate(v) for v in r.votes],
        resultat=ResolutionResult(**resultat),
    )


def _ag_out(db: Session, ag: AG) -> AGOut:
    return AGOut(
        id=ag.id, date=ag.date, heure=ag.heure, type_ag=ag.type_ag, statut=ag.statut,
        lieu=ag.lieu, notes=ag.notes,
        rappel_jours=ag.rappel_jours or 0, convocation_envoyee=bool(ag.convocation_envoyee),
        lien_visio=ag.lien_visio or "",
        resolutions=[_resolution_out(db, r) for r in sorted(ag.resolutions, key=lambda x: x.numero)],
    )


def _creneau_out(db: Session, c: AgCreneau) -> CreneauOut:
    votes = []
    copro_id = c.ag.copropriete_id if c.ag else None
    for v in c.votes:
        lot = (db.query(Lot)
               .filter(Lot.id == v.lot_id,
                       Lot.copropriete_id == copro_id if copro_id else Lot.id == v.lot_id)
               .first())
        votes.append(CreneauVoteOut(
            id=v.id, lot_id=v.lot_id,
            lot_numero=lot.numero if lot else f"#{v.lot_id}",
            dispo=v.dispo,
        ))
    return CreneauOut(id=c.id, debut=c.debut, fin=c.fin, votes=votes)


CONSULTATION = "consultation_ecrite"


def _exiger_petite_copro(db: Session, copro: Copropriete) -> None:
    """Consultation écrite : réservée aux petites copropriétés (art. 41-8 et 41-12)."""
    regime = regime_copro(db, copro.id)
    if regime["petite"]:
        return
    budget = ("non disponible (moins de 3 exercices consécutifs budgétés)" if regime["budget_moyen"] is None
              else f"{regime['budget_moyen']} €")
    raise HTTPException(422, "La consultation écrite est réservée aux petites copropriétés (art. 41-8 et 41-12 "
                             f"de la loi du 10 juillet 1965) : {regime['nb_lots_principaux']} lots de logements, "
                             f"bureaux ou commerces (5 au plus), budget moyen sur 3 exercices : {budget} "
                             "(moins de 15 000 €). Réunissez une assemblée générale.")


def _cle_resolution(db: Session, copro: Copropriete, data: ResolutionIn) -> int | None:
    """Clé d'une résolution : de la copropriété, avec des millièmes ; jamais pour le budget ni les comptes,
    qui concernent tous les copropriétaires."""
    if data.cle_id is None:
        return None
    if data.nature in ("budget", "approbation_comptes"):
        raise HTTPException(422, "Le budget et l'approbation des comptes sont votés par tous les copropriétaires : "
                                 "pas de clé de répartition pour ces résolutions.")
    from app.services import cles
    return cles.controler(db, copro.id, data.cle_id).id


def _controler_resolution(ag: AG, majorite: str, nature: str) -> None:
    if ag.type_ag == CONSULTATION:
        motif = refus_consultation_ecrite(majorite, nature)
        if motif:
            raise HTTPException(422, motif)


def _mandat_resolution(db: Session, copro: Copropriete, data: ResolutionIn, valeurs: dict) -> None:
    """Désignation du syndic / élection du conseil : durée et comptes contrôlés (services/mandats.py) ; effacés
    pour les autres résolutions."""
    from app.services import mandats
    if data.nature in mandats.ROLES:
        mandats.controler(db, copro.id, data.nature, data.mandat_mois, data.mandat_personnes)
        valeurs["mandat_personnes"] = list(data.mandat_personnes) if data.mandat_personnes else None
    else:
        valeurs["mandat_mois"] = valeurs["mandat_personnes"] = None


def _exercice_approuve(db: Session, copro: Copropriete, data: ResolutionIn) -> int | None:
    """Exercice d'une résolution « approbation des comptes » (obligatoire) ; None pour les autres."""
    if data.nature != "approbation_comptes":
        return None
    if data.exercice_id is None:
        raise HTTPException(422, "Approbation des comptes : choisissez l'exercice dont les comptes sont approuvés.")
    return get_owned(db, Exercice, data.exercice_id, copro, label="Exercice").id


def _reporter_approbation(db: Session, r: Resolution) -> None:
    """Résolution « approbation des comptes » : reporte le résultat du vote sur l'exercice.

    Adoptée → comptes approuvés à la date de l'AG (et exercice clôturé). Recalculée rejetée →
    on retire l'approbation seulement si elle venait de cette AG (même date).
    """
    if r.nature != "approbation_comptes" or not r.exercice_id:
        return
    ex = db.get(Exercice, r.exercice_id)
    if ex is None or ex.copropriete_id != r.ag.copropriete_id:
        return
    if r.statut == "adoptee":
        ex.comptes_approuves_le = r.ag.date
        ex.cloture = True
    elif ex.comptes_approuves_le == r.ag.date:
        ex.comptes_approuves_le = None


@router.get("/majorites")
def majorites():
    """Description des majorités légales (module France)."""
    return MAJORITES


@router.get("/ag/modele-annuelle", response_model=list[ModeleResolutionOut])
def modele_annuelle(jour: date, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Résolutions types d'une AG annuelle tenue le `jour` (services/modele_ag.py)."""
    from app.services import modele_ag
    return modele_ag.modeles(db, get_or_create_copro(db, user), jour)


@router.post("/ag/{ag_id}/resolutions-types", response_model=list[ResolutionOut])
def ajouter_resolutions_types(ag_id: int, data: ResolutionsTypesIn, db: Session = Depends(get_db),
                              user: User = Depends(require_syndic)):
    from app.services import modele_ag
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    crees = modele_ag.ajouter(db, copro, ag, data.codes)
    db.commit()
    return [_resolution_out(db, r) for r in crees]


@router.get("/ag", response_model=list[AGOut])
def list_ag(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    ags = db.query(AG).filter(AG.copropriete_id == copro.id).order_by(AG.date.desc()).all()
    return [_ag_out(db, ag) for ag in ags]


@router.post("/ag", response_model=AGOut)
def create_ag(data: AGIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    if data.type_ag == CONSULTATION:
        _exiger_petite_copro(db, copro)
    ag = AG(copropriete_id=copro.id, **data.model_dump())
    db.add(ag)
    db.commit()
    db.refresh(ag)
    return _ag_out(db, ag)


def _approbations_de(db: Session, ag: AG) -> list[Exercice]:
    """Exercices dont les comptes ont été approuvés par une résolution adoptée de cette AG (à sa date)."""
    out = []
    for r in ag.resolutions:
        if r.nature == "approbation_comptes" and r.statut == "adoptee" and r.exercice_id:
            ex = db.get(Exercice, r.exercice_id)
            if ex is not None and ex.copropriete_id == ag.copropriete_id and ex.comptes_approuves_le == ag.date:
                out.append(ex)
    return out


@router.put("/ag/{ag_id}", response_model=AGOut)
def update_ag(ag_id: int, data: AGIn, request: Request, db: Session = Depends(get_db),
              user: User = Depends(require_syndic)):
    """Correction d'une AG (date, heure, type, statut, lieu, notes, e-mail automatique). Une approbation des comptes
    votée à cette AG suit sa nouvelle date."""
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    approuves = _approbations_de(db, ag)
    avant = f"{ag.type_ag} du {ag.date:%d/%m/%Y}"
    if data.type_ag == CONSULTATION and ag.type_ag != CONSULTATION:
        # Transformation en consultation écrite : régime et résolutions déjà saisies contrôlés.
        # Une consultation existante reste modifiable (on ne bloque pas l'existant).
        _exiger_petite_copro(db, copro)
        for r in ag.resolutions:
            motif = refus_consultation_ecrite(r.majorite, r.nature or "autre")
            if motif:
                raise HTTPException(422, f"Résolution n° {r.numero} : {motif}")
    for field, value in data.model_dump().items():
        setattr(ag, field, value)
    for ex in approuves:
        ex.comptes_approuves_le = ag.date
    from app.services import mandats
    for r in ag.resolutions:
        mandats.synchroniser(db, r)                # un mandat voté commence le jour de l'AG
    audit.enregistrer(db, "ag_modifiee", user=user, copro_id=copro.id, request=request,
                      detail=f"{avant} → {ag.type_ag} du {ag.date:%d/%m/%Y}")
    db.commit()
    db.refresh(ag)
    return _ag_out(db, ag)


@router.delete("/ag/{ag_id}")
def delete_ag(ag_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Supprime une AG saisie par erreur (ou d'essai) avec tout ce qui en dépend : résolutions et votes, créneaux,
    e-mails d'information, réponses et pouvoirs, votes par correspondance, notifications du PV. Une approbation
    des comptes votée à cette AG est retirée de l'exercice."""
    from app.models.ag import VoteCorrespondance
    from app.models.notification import NotificationPV
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    retirees = [ex.annee for ex in _approbations_de(db, ag)]
    for ex in _approbations_de(db, ag):
        ex.comptes_approuves_le = None
    # Lignes rattachées à l'AG sans relation ORM : supprimées explicitement (SQLite n'applique pas toujours
    # les ON DELETE CASCADE).
    db.query(VoteCorrespondance).filter(VoteCorrespondance.ag_id == ag.id).delete(synchronize_session=False)
    db.query(AgReponse).filter(AgReponse.ag_id == ag.id).delete(synchronize_session=False)
    db.query(NotificationPV).filter(NotificationPV.ag_id == ag.id).delete(synchronize_session=False)
    from app.services import mandats
    mandats.retirer_ag(db, ag)
    for r in list(ag.resolutions):
        if r.second_vote_de_id is not None:
            db.delete(r)
    db.flush()
    db.expire(ag)
    detail = (f"{ag.type_ag} du {ag.date:%d/%m/%Y} ({len(ag.resolutions)} résolution(s))"
              + (f" ; approbation des comptes {', '.join(map(str, retirees))} retirée" if retirees else ""))
    db.delete(ag)
    audit.enregistrer(db, "ag_supprimee", user=user, copro_id=copro.id, request=request, detail=detail)
    db.commit()
    return {"ok": True, "approbations_retirees": retirees}


# ---------- Résolutions ----------
@router.post("/ag/{ag_id}/resolutions", response_model=ResolutionOut)
def add_resolution(ag_id: int, data: ResolutionIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    if data.majorite not in MAJORITES:
        raise HTTPException(400, f"Majorité inconnue : {data.majorite}")
    _controler_resolution(ag, data.majorite, data.nature)
    valeurs = data.model_dump()
    valeurs["exercice_id"] = _exercice_approuve(db, copro, data)
    valeurs["cle_id"] = _cle_resolution(db, copro, data)
    _mandat_resolution(db, copro, data, valeurs)
    r = Resolution(ag_id=ag.id, **valeurs)
    db.add(r)
    db.commit()
    db.refresh(r)
    return _resolution_out(db, r)


@router.put("/resolutions/{res_id}", response_model=ResolutionOut)
def update_resolution(res_id: int, data: ResolutionIn, request: Request, effacer_votes: bool = False,
                      db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Correction d'une résolution. Libellé, texte, numéro : le résultat est gardé. Objet, exercice approuvé, majorité
    ou clé : ce qui a été voté n'est plus la même décision — le résultat est effacé (« à voter », à recalculer) et
    une approbation des comptes reportée par cette résolution est retirée de l'exercice. Les votes saisis sont gardés
    (cas courant : erreur de saisie corrigée, puis recalcul) ; `effacer_votes=true` les supprime, en séance et par
    correspondance, et remet aussi le résultat à voter (revue de ChatGPT/Codex sur la 2026.11.056, choix de Fred)."""
    from app.models.ag import VoteCorrespondance
    copro = get_or_create_copro(db, user)
    r = get_owned_via(db, Resolution, AG, res_id, copro, "ag_id", label="Résolution")
    if data.majorite not in MAJORITES:
        raise HTTPException(400, f"Majorité inconnue : {data.majorite}")
    _controler_resolution(r.ag, data.majorite, data.nature)
    valeurs = data.model_dump()
    valeurs["exercice_id"] = _exercice_approuve(db, copro, data)
    valeurs["cle_id"] = _cle_resolution(db, copro, data)
    _mandat_resolution(db, copro, data, valeurs)
    decisif = any(getattr(r, k) != valeurs[k] for k in ("nature", "exercice_id", "majorite", "cle_id", "mandat_mois",
                                                         "mandat_personnes"))
    if (decisif or effacer_votes) and r.statut != "a_voter":
        if db.query(Resolution).filter(Resolution.second_vote_de_id == r.id).first():
            raise HTTPException(409, "Cette résolution a un second vote : supprimez-le avant de changer l'objet, l'exercice, "
                                     "la majorité ou la clé.")
        retirees = [ex.annee for ex in _approbations_de(db, r.ag) if ex.id == r.exercice_id and r.statut == "adoptee"]
        for ex in _approbations_de(db, r.ag):
            if ex.id == r.exercice_id and r.statut == "adoptee":
                ex.comptes_approuves_le = None
        audit.enregistrer(db, "resolution_modifiee", user=user, copro_id=copro.id, request=request,
                          detail=f"n° {r.numero} « {r.libelle} » : résultat effacé ({r.statut})"
                                 + (f", approbation des comptes {', '.join(map(str, retirees))} retirée" if retirees else "")
                                 + (", votes effacés" if effacer_votes else ""))
        r.statut = "a_voter"
    elif effacer_votes:
        audit.enregistrer(db, "resolution_modifiee", user=user, copro_id=copro.id, request=request,
                          detail=f"n° {r.numero} « {r.libelle} » : votes effacés")
    if effacer_votes:
        db.query(Vote).filter(Vote.resolution_id == r.id).delete(synchronize_session=False)
        db.query(VoteCorrespondance).filter(VoteCorrespondance.resolution_id == r.id).delete(synchronize_session=False)
    for field, value in valeurs.items():
        setattr(r, field, value)
    from app.services import mandats
    mandats.synchroniser(db, r)
    db.commit()
    db.refresh(r)
    return _resolution_out(db, r)


@router.delete("/resolutions/{res_id}")
def delete_resolution(res_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    from app.models.ag import VoteCorrespondance
    copro = get_or_create_copro(db, user)
    r = get_owned_via(db, Resolution, AG, res_id, copro, "ag_id", label="Résolution")
    if r.statut == "adoptee":
        for ex in _approbations_de(db, r.ag):
            if ex.id == r.exercice_id:
                ex.comptes_approuves_le = None
    ids = [r.id] + [e.id for e in db.query(Resolution).filter(Resolution.second_vote_de_id == r.id)]
    db.query(VoteCorrespondance).filter(VoteCorrespondance.resolution_id.in_(ids)).delete(synchronize_session=False)
    from app.models.mandat import Mandat
    db.query(Mandat).filter(Mandat.resolution_id.in_(ids)).delete(synchronize_session=False)
    for enfant in db.query(Resolution).filter(Resolution.second_vote_de_id == r.id).all():
        db.delete(enfant)
    db.delete(r)
    db.commit()
    return {"ok": True}


# ---------- Votes ----------
@router.post("/resolutions/{res_id}/votes", response_model=VoteOut)
def set_vote(res_id: int, data: VoteIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    r = get_owned_via(db, Resolution, AG, res_id, copro, "ag_id", label="Résolution")
    lot = get_owned(db, Lot, data.lot_id, copro, label="Lot")
    if data.voix not in ("pour", "contre", "abstention", "null"):
        raise HTTPException(400, "Voix invalide")
    vote = db.query(Vote).filter(Vote.resolution_id == res_id, Vote.lot_id == data.lot_id).first()
    if vote:
        vote.voix = data.voix
    else:
        vote = Vote(resolution_id=res_id, lot_id=data.lot_id, voix=data.voix)
        db.add(vote)
    db.commit()
    db.refresh(vote)
    return vote


@router.post("/resolutions/{res_id}/calculer", response_model=ResolutionOut)
def calculer(res_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Recalcule le statut d'une résolution selon la majorité légale (module FR)."""
    copro = get_or_create_copro(db, user)
    r = get_owned_via(db, Resolution, AG, res_id, copro, "ag_id", label="Résolution")
    from app.services import correspondance
    correspondance.appliquer(db, r.ag, r)          # votes par correspondance des absents (art. 17-1 A)
    db.refresh(r)
    from app.services import cles
    lots, votes = cles.votants(db, copro.id, r)
    resultat = calculer_statut_resolution(r, lots, votes)
    r.statut = resultat["statut"]
    _reporter_approbation(db, r)
    from app.services import mandats
    mandats.synchroniser(db, r)
    db.commit()
    db.refresh(r)
    return _resolution_out(db, r)


@router.post("/resolutions/{res_id}/second-vote", response_model=ResolutionOut)
def second_vote(res_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Passerelles art. 25-1 / 26-1 : crée la résolution du second vote immédiat."""
    copro = get_or_create_copro(db, user)
    r = get_owned_via(db, Resolution, AG, res_id, copro, "ag_id", label="Résolution")
    from app.services import correspondance
    correspondance.appliquer(db, r.ag, r)          # votes par correspondance des absents (art. 17-1 A)
    db.refresh(r)
    from app.services import cles
    lots, votes = cles.votants(db, copro.id, r)
    resultat = calculer_statut_resolution(r, lots, votes)
    majorite = resultat["second_vote_possible"]
    if majorite is None:
        raise HTTPException(400, "Aucun second vote possible pour cette résolution")
    if db.query(Resolution).filter(Resolution.second_vote_de_id == r.id).first():
        raise HTTPException(409, "Le second vote de cette résolution existe déjà")
    article = "art. 25-1" if majorite == "art24" else "art. 26-1"
    r.statut = resultat["statut"]
    sv = Resolution(ag_id=r.ag_id, numero=r.numero, texte=r.texte, majorite=majorite,
                    nature=r.nature or "autre", exercice_id=r.exercice_id, cle_id=r.cle_id,
                    mandat_mois=r.mandat_mois, mandat_personnes=r.mandat_personnes,
                    libelle=f"{r.libelle} — second vote ({article})", second_vote_de_id=r.id)
    db.add(sv)
    db.commit()
    db.refresh(sv)
    return _resolution_out(db, sv)


# ---------- Réunion en ligne ----------
@router.post("/ag/{ag_id}/lien-jitsi", response_model=AGOut)
def lien_jitsi(ag_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Crée (ou remplace) le lien de visioconférence de l'AG : une salle Jitsi au nom difficile à deviner,
    sur le serveur réglé pour l'instance (COPRO_JITSI_URL, meet.jit.si par défaut)."""
    from app.core.config import get_settings
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    ag.lien_visio = f"{get_settings().jitsi_url.rstrip('/')}/Proprietas-{secrets.token_hex(12)}"
    audit.enregistrer(db, "ag_lien_visio", user=user, copro_id=copro.id, request=request,
                      detail=f"AG du {ag.date:%d/%m/%Y} : lien Jitsi créé")
    db.commit()
    db.refresh(ag)
    return _ag_out(db, ag)


# ---------- Sondage de dates (type Doodle) ----------
@router.get("/ag/{ag_id}/creneaux", response_model=list[CreneauOut])
def list_creneaux(ag_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    creneaux = db.query(AgCreneau).filter(AgCreneau.ag_id == ag.id).order_by(AgCreneau.debut).all()
    return [_creneau_out(db, c) for c in creneaux]


@router.post("/ag/{ag_id}/creneaux", response_model=CreneauOut)
def add_creneau(ag_id: int, data: CreneauIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    if data.fin and data.fin <= data.debut:
        raise HTTPException(400, "La fin doit être après le début")
    c = AgCreneau(ag_id=ag.id, debut=data.debut, fin=data.fin)
    db.add(c)
    db.commit()
    db.refresh(c)
    return _creneau_out(db, c)


@router.delete("/creneaux/{creneau_id}")
def delete_creneau(creneau_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    copro = get_or_create_copro(db, user)
    c = get_owned_via(db, AgCreneau, AG, creneau_id, copro, "ag_id", label="Créneau")
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.post("/creneaux/{creneau_id}/votes", response_model=CreneauVoteOut)
def set_creneau_vote(creneau_id: int, data: CreneauVoteIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Le syndic saisit la disponibilité d'un lot pour un créneau."""
    copro = get_or_create_copro(db, user)
    c = get_owned_via(db, AgCreneau, AG, creneau_id, copro, "ag_id", label="Créneau")
    lot = get_owned(db, Lot, data.lot_id, copro, label="Lot")
    vote = db.query(AgCreneauVote).filter(
        AgCreneauVote.creneau_id == creneau_id,
        AgCreneauVote.lot_id == data.lot_id,
    ).first()
    if vote:
        vote.dispo = data.dispo
    else:
        vote = AgCreneauVote(creneau_id=creneau_id, lot_id=data.lot_id, dispo=data.dispo)
        db.add(vote)
    db.commit()
    db.refresh(vote)
    lot_row = db.query(Lot).filter(Lot.id == vote.lot_id).first()
    return CreneauVoteOut(
        id=vote.id, lot_id=vote.lot_id,
        lot_numero=lot_row.numero if lot_row else "",
        dispo=vote.dispo,
    )


@router.post("/ag/{ag_id}/choisir-creneau/{creneau_id}", response_model=AGOut)
def choisir_creneau(ag_id: int, creneau_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Fixe la date/heure de l'AG sur le créneau retenu et passe l'AG en 'convoquée'."""
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    c = db.query(AgCreneau).filter(AgCreneau.id == creneau_id, AgCreneau.ag_id == ag.id).first()
    if not c:
        raise HTTPException(404, "Créneau introuvable pour cette AG")
    ag.date = c.debut.date()
    ag.heure = c.debut.strftime("%H:%M")
    ag.statut = "convoquee"
    db.commit()
    db.refresh(ag)
    return _ag_out(db, ag)


# ---------- E-mails d'information sur l'AG (pas une convocation régulière) ----------
@router.get("/ag/{ag_id}/invitations", response_model=list[InvitationOut])
def list_invitations(ag_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    invs = db.query(Invitation).filter(Invitation.ag_id == ag.id).order_by(Invitation.date_envoi.desc()).all()
    out = []
    for i in invs:
        personne = db.query(User).filter(User.id == i.personne_id).first()
        out.append(InvitationOut(
            id=i.id,
            personne_nom=f"{personne.prenom} {personne.nom}".strip() if personne else "?",
            personne_email=personne.email if personne else "",
            date_envoi=i.date_envoi,
            statut=i.statut,
            message=i.message,
            confirme_le=i.confirme_le,
        ))
    return out


def envoyer_convocations(db: Session, ag: AG, copro: Copropriete, syndic_nom: str, marquer_envoyee: bool = True) -> InvitationsResult:
    """E-mail d'INFORMATION sur l'AG aux propriétaires ayant une adresse (pas une notification)."""
    lots = db.query(Lot).filter(Lot.copropriete_id == copro.id).all()
    proprietaires = {}
    for lot in lots:
        if lot.proprietaire_id:
            proprietaires[lot.proprietaire_id] = True
    personnes = db.query(User).filter(User.id.in_(list(proprietaires.keys()))).all() if proprietaires else []

    sujet = convocation_sujet(copro, ag)
    base = adresse_publique(copro).rstrip("/")

    envoyes = 0
    sans_email = 0
    erreurs = []
    for p in personnes:
        if not p.email:
            sans_email += 1
            continue
        # Lien personnel « J'ai bien reçu ce message » (seulement si l'adresse publique est connue).
        jeton = secrets.token_urlsafe(24)
        lien = f"{base}/api/ag/confirmation/{jeton}" if base else ""
        corps = convocation_texte(copro, ag, ag.resolutions, syndic_nom, lien_confirmation=lien)
        try:
            envoyer_email(copro, p.email, sujet, corps)
            statut = "envoye"
            message = ""
        except EmailError as e:
            statut = "erreur"
            message = str(e)
            erreurs.append(f"{p.nom}: {e}")
        inv = Invitation(
            ag_id=ag.id, personne_id=p.id,
            date_envoi=datetime.now(), statut=statut, message=message,
            jeton=jeton if statut == "envoye" and lien else None,
        )
        db.add(inv)
        if statut == "envoye":
            envoyes += 1
    if marquer_envoyee:
        ag.convocation_envoyee = True
    db.commit()
    return InvitationsResult(envoyes=envoyes, sans_email=sans_email, erreurs=erreurs)


def _page(titre: str, texte: str, formulaire: str = "") -> HTMLResponse:
    """Petite page autonome (sans script : CSP stricte), lisible sur téléphone."""
    return HTMLResponse(
        "<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(titre)}</title><style>body{{font-family:system-ui,sans-serif;max-width:32rem;"
        "margin:3rem auto;padding:0 1rem;color:#1e293b}h1{font-size:1.25rem}button{font-size:1rem;"
        "padding:.6rem 1.2rem;border:0;border-radius:.5rem;background:#4f46e5;color:#fff;cursor:pointer}"
        "label{display:block;margin:.5rem 0}select{font-size:1rem;padding:.4rem;max-width:100%}"
        ".note{font-size:.85rem;color:#475569}.erreur{color:#b91c1c}a{color:#4f46e5}"
        "</style></head><body>"
        f"<h1>{html.escape(titre)}</h1><p>{html.escape(texte)}</p>{formulaire}</body></html>")


def _invitation_du_jeton(db: Session, jeton: str):
    inv = db.query(Invitation).filter(Invitation.jeton == jeton).first() if len(jeton) >= 20 else None
    if inv is None:
        return None, None, None
    ag = db.get(AG, inv.ag_id)
    copro = db.get(Copropriete, ag.copropriete_id) if ag else None
    return inv, ag, copro


def _quoi(ag, copro) -> str:
    return f"l'assemblée du {ag.date.strftime('%d/%m/%Y')}" + (f" à {ag.heure}" if ag.heure else "") + f" — {copro.nom}"


def _formulaire_reponse(db: Session, ag, personne, reponse, erreur: str = "") -> str:
    """Formulaire de réponse (sans script) : quatre choix, et le mandataire en cas de pouvoir."""
    actuelle = reponse.reponse if reponse else ""
    choix = "".join(
        f'<label><input type="radio" name="reponse" value="{k}"{" checked" if k == actuelle else ""} required> '
        f'{html.escape(v + (" à…" if k == "pouvoir" else ""))}</label>' for k, v in presences.reponses_possibles(ag).items())
    options = "".join(
        f'<option value="{u.id}"{" selected" if reponse and reponse.mandataire_id == u.id else ""}>'
        f'{html.escape(presences.nom(u))}</option>' for u in presences.mandataires_possibles(db, ag.copropriete_id, personne))
    return ((f'<p class="erreur">{html.escape(erreur)}</p>' if erreur else "")
            + f'<form method="post">{choix}'
            f'<label>Pouvoir à : <select name="mandataire_id"><option value="">— choisir un copropriétaire —</option>'
            f'{options}</select></label>'
            '<p class="note">Le syndic, son conjoint ou partenaire, ses parents et ses employés ne peuvent pas recevoir de '
            'pouvoir ; un copropriétaire ne peut pas en recevoir plus de trois, sauf s\'il reste sous 10 % des voix '
            '(loi du 10 juillet 1965, art. 22). Vous pourrez changer d\'avis jusqu\'à l\'ouverture de l\'assemblée.</p>'
            '<button type="submit">Envoyer ma réponse</button></form>')


def _resume_reponse(r) -> str:
    if r is None:
        return ""
    texte = (presences.REPONSES.get(r.reponse) or "J'ai voté par correspondance") \
        + (f" à {presences.nom(r.mandataire)}" if r.reponse == "pouvoir" else "")
    return f"{texte} (le {r.repondu_le:%d/%m/%Y à %H:%M})"


def _reponse_de(db: Session, ag, personne_id):
    return db.query(AgReponse).filter(AgReponse.ag_id == ag.id, AgReponse.personne_id == personne_id).first()


def _lien_pouvoir(jeton: str, r) -> str:
    if r is None or r.reponse != "pouvoir":
        return ""
    return (f'<p><a href="/api/ag/confirmation/{html.escape(jeton)}/pouvoir">Télécharger le pouvoir (PDF)</a> : '
            f'datez-le, signez-le et remettez-le à {html.escape(presences.nom(r.mandataire))} ou au syndic avant '
            "l'assemblée.</p>")


@router.get("/ag/confirmation/{jeton}", response_class=HTMLResponse, include_in_schema=False)
def confirmation_page(jeton: str, db: Session = Depends(get_db)):
    """Page du lien de l'e-mail : le copropriétaire répond (présent, pouvoir, absent, ne sait pas). Rien n'est
    enregistré à l'ouverture (GET) : les antivirus et aperçus qui ouvrent les liens seuls ne répondent pas à sa place."""
    inv, ag, copro = _invitation_du_jeton(db, jeton)
    if inv is None:
        return _page("Lien inconnu", "Ce lien de confirmation n'est pas valable (ou plus valable).")
    personne = db.get(User, inv.personne_id) if inv.personne_id else None
    r = _reponse_de(db, ag, inv.personne_id)
    if personne is None or not presences.reponses_ouvertes(ag) or \
            personne not in presences.coproprietaires(db, ag.copropriete_id):
        texte = f"Information sur {_quoi(ag, copro)}." + (f" Votre réponse : {_resume_reponse(r)}." if r else "")
        return _page("Assemblée générale", texte + " Il n'est plus possible de répondre en ligne : contactez le syndic.",
                     _lien_pouvoir(jeton, r))
    texte = f"Information sur {_quoi(ag, copro)}. " + (f"Votre réponse : {_resume_reponse(r)}. Vous pouvez la changer."
                                                         if r else "Serez-vous présent(e) ?")
    return _page("Votre réponse", texte, _lien_pouvoir(jeton, r) + _formulaire_reponse(db, ag, personne, r))


@router.post("/ag/confirmation/{jeton}", response_class=HTMLResponse, include_in_schema=False)
def confirmation(jeton: str, reponse: str = Form(""), mandataire_id: str = Form(""), db: Session = Depends(get_db)):
    inv, ag, copro = _invitation_du_jeton(db, jeton)
    if inv is None:
        return _page("Lien inconnu", "Ce lien de confirmation n'est pas valable (ou plus valable).")
    if not inv.confirme_le:
        inv.confirme_le = datetime.now()          # répondre, c'est aussi confirmer la réception
        db.commit()
    personne = db.get(User, inv.personne_id) if inv.personne_id else None
    if not reponse:                               # bouton des liens envoyés avant la 2026.11.042
        return _page("Merci", "La réception est confirmée : le syndic en est informé. "
                              "La convocation officielle vous parvient par lettre recommandée.")
    if personne is None or not presences.reponses_ouvertes(ag):
        return _page("Assemblée générale", "Il n'est plus possible de répondre en ligne : contactez le syndic.")
    try:
        r = presences.repondre(db, ag, personne, reponse, int(mandataire_id) if mandataire_id.isdigit() else None, "lien")
    except HTTPException as e:
        db.rollback()
        return _page("Votre réponse", f"Information sur {_quoi(ag, copro)}.",
                     _formulaire_reponse(db, ag, personne, _reponse_de(db, ag, personne.id), str(e.detail)))
    db.commit()
    return _page("Merci", f"Réponse enregistrée : {_resume_reponse(r)}. Le syndic en est informé ; vous pouvez la "
                          "changer avec le même lien jusqu'à l'ouverture de l'assemblée.", _lien_pouvoir(jeton, r))


@router.get("/ag/confirmation/{jeton}/pouvoir", include_in_schema=False)
def pouvoir_du_lien(jeton: str, db: Session = Depends(get_db)):
    inv, ag, copro = _invitation_du_jeton(db, jeton)
    r = _reponse_de(db, ag, inv.personne_id) if inv is not None else None
    if r is None or r.reponse != "pouvoir":
        raise HTTPException(404, "Pas de pouvoir enregistré.")
    return _pdf_pouvoir(db, ag, copro, r)


def _pdf_pouvoir(db: Session, ag, copro, r) -> Response:
    from app.services.presence_pdf import pouvoir_pdf
    nom_fichier = f"pouvoir-ag-{ag.date}.pdf"
    return Response(pouvoir_pdf(db, ag, copro, r).getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'})


# ---------- Présence et pouvoirs (services/presences.py) ----------
@router.get("/ag/{ag_id}/presences", response_model=PresencesOut)
def lire_presences(ag_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    ag = get_owned(db, AG, ag_id, get_or_create_copro(db, user), label="AG")
    return presences.etat(db, ag)


@router.put("/ag/{ag_id}/presences/{personne_id}", response_model=PresencesOut)
def saisir_presence(ag_id: int, personne_id: int, data: PresenceIn, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require_syndic)):
    """Le syndic saisit ou corrige une réponse (téléphone, courrier, séance), à tout moment."""
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    personne = db.get(User, personne_id)
    if personne is None or personne not in presences.coproprietaires(db, copro.id):
        raise HTTPException(404, "Copropriétaire introuvable")
    r = _reponse_de(db, ag, personne.id)
    if r is None or r.reponse != data.reponse or r.mandataire_id != data.mandataire_id:
        r = presences.repondre(db, ag, personne, data.reponse, data.mandataire_id, "syndic")
    if data.pouvoir_recu is not None:
        if r.reponse != "pouvoir":
            raise HTTPException(422, "Pas de pouvoir pour ce copropriétaire.")
        r.pouvoir_recu_le = (r.pouvoir_recu_le or datetime.now()) if data.pouvoir_recu else None
    audit.enregistrer(db, "ag_presence", user=user, copro_id=copro.id, request=request,
                      detail=f"AG du {ag.date:%d/%m/%Y} — {presences.nom(personne)} : {_resume_reponse(r)}"
                             + (" — pouvoir signé reçu" if r.pouvoir_recu_le else ""))
    db.commit()
    return presences.etat(db, ag)


def _ma_reponse(db: Session, ag, user: User) -> MaReponseOut:
    r = _reponse_de(db, ag, user.id)
    mandants = [x.personne for x in db.query(AgReponse).filter(
        AgReponse.ag_id == ag.id, AgReponse.reponse == "pouvoir", AgReponse.mandataire_id == user.id)]
    return MaReponseOut(
        ouvert=presences.reponses_ouvertes(ag),
        coproprietaire=user in presences.coproprietaires(db, ag.copropriete_id),
        reponse=r.reponse if r else "", repondu_le=r.repondu_le if r else None,
        mandataire_id=r.mandataire_id if r and r.reponse == "pouvoir" else None,
        mandataire_nom=presences.nom(r.mandataire) if r and r.reponse == "pouvoir" else "",
        mandataires=[PersonneCourteOut(id=u.id, nom=presences.nom(u))
                     for u in presences.mandataires_possibles(db, ag.copropriete_id, user)],
        mandats=[PersonneCourteOut(id=u.id, nom=presences.nom(u)) for u in mandants if u is not None])


@router.get("/ag/{ag_id}/ma-reponse", response_model=MaReponseOut)
def lire_ma_reponse(ag_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ag = get_owned(db, AG, ag_id, get_or_create_copro(db, user), label="AG")
    return _ma_reponse(db, ag, user)


@router.put("/ag/{ag_id}/ma-reponse", response_model=MaReponseOut)
def repondre_moi(ag_id: int, data: ReponseAgIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ag = get_owned(db, AG, ag_id, get_or_create_copro(db, user), label="AG")
    if not presences.reponses_ouvertes(ag):
        raise HTTPException(409, "L'assemblée est ouverte : votre réponse ne peut plus changer en ligne ; "
                                 "voyez le syndic.")
    presences.repondre(db, ag, user, data.reponse, data.mandataire_id, "compte")
    db.commit()
    return _ma_reponse(db, ag, user)


@router.get("/ag/{ag_id}/pouvoirs/{personne_id}")
def telecharger_pouvoir(ag_id: int, personne_id: int, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """Le pouvoir en PDF : pour le syndic, le mandant et son mandataire."""
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    r = _reponse_de(db, ag, personne_id)
    if r is None or r.reponse != "pouvoir":
        raise HTTPException(404, "Pas de pouvoir enregistré pour ce copropriétaire.")
    if user.role != "syndic" and user.id not in (r.personne_id, r.mandataire_id):
        raise HTTPException(403, "Réservé au syndic, au copropriétaire et à son mandataire.")
    return _pdf_pouvoir(db, ag, copro, r)


@router.get("/ag/{ag_id}/feuille-presence")
def telecharger_feuille_presence(ag_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    from app.services.presence_pdf import feuille_presence_pdf
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    return Response(feuille_presence_pdf(db, ag, copro).getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="feuille-presence-ag-{ag.date}.pdf"'})


# ---------- Vote par correspondance (services/correspondance.py) ----------
class CorrespondanceIn(BaseModel):
    recu_le: date
    votes: dict[int, str] = {}


class AmendeeIn(BaseModel):
    amendee: bool


@router.get("/ag/{ag_id}/correspondance")
def lire_correspondance(ag_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    from app.services import correspondance
    copro = get_or_create_copro(db, user)
    return correspondance.etat(db, get_owned(db, AG, ag_id, copro, label="AG"))


@router.put("/ag/{ag_id}/correspondance/{personne_id}")
def saisir_correspondance(ag_id: int, personne_id: int, data: CorrespondanceIn, request: Request,
                          db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Formulaire de vote par correspondance reçu : date de réception et votes, résolution par résolution."""
    from app.services import correspondance
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    correspondance.enregistrer(db, ag, personne_id, data.recu_le, data.votes, user, request)
    db.commit()
    return correspondance.etat(db, ag)


@router.delete("/ag/{ag_id}/correspondance/{personne_id}")
def retirer_correspondance(ag_id: int, personne_id: int, request: Request, db: Session = Depends(get_db),
                           user: User = Depends(require_syndic)):
    from app.services import correspondance
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    correspondance.supprimer(db, ag, personne_id, user, request)
    db.commit()
    return correspondance.etat(db, ag)


@router.put("/resolutions/{res_id}/amendee", response_model=ResolutionOut)
def marquer_amendee(res_id: int, data: AmendeeIn, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Résolution amendée en séance : les votes « pour » par correspondance deviennent défaillants."""
    from app.services import correspondance
    copro = get_or_create_copro(db, user)
    r = get_owned_via(db, Resolution, AG, res_id, copro, "ag_id", label="Résolution")
    r.amendee = data.amendee
    correspondance.appliquer(db, r.ag, r)
    db.commit()
    db.refresh(r)
    return _resolution_out(db, r)


@router.get("/ag/{ag_id}/formulaires-correspondance.pdf")
def formulaires_correspondance(ag_id: int, personne_id: int | None = None, db: Session = Depends(get_db),
                               user: User = Depends(get_current_user)):
    """Formulaires de vote par correspondance à joindre à la convocation : tous (syndic) ou le sien
    (copropriétaire)."""
    from app.services.presence_pdf import formulaires_correspondance_pdf
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    if ag.type_ag == "consultation_ecrite":
        raise HTTPException(422, "Une consultation écrite n'a pas de vote par correspondance.")
    tous = presences.coproprietaires(db, copro.id)
    if user.role != "syndic":
        personne_id = user.id
    personnes = [u for u in tous if personne_id is None or u.id == personne_id]
    if not personnes:
        raise HTTPException(404, "Aucun copropriétaire à qui adresser ce formulaire.")
    pdf = formulaires_correspondance_pdf(db, ag, copro, personnes)
    return Response(pdf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="vote-par-correspondance-ag-{ag.date}.pdf"'})


@router.post("/ag/{ag_id}/invitations", response_model=InvitationsResult)
def envoyer_invitations(ag_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """E-mail d'INFORMATION sur l'AG aux propriétaires ayant une adresse (pas une notification)."""
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    return envoyer_convocations(db, ag, copro, user.nom or "Le syndic")


# ---------- Procès-verbal PDF ----------
@router.get("/ag/{ag_id}/pv")
def telecharger_pv(ag_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Génère et télécharge le procès-verbal de l'AG en PDF."""
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")
    pdf = generer_pv_pdf(copro, ag, db)
    nom = f"PV_AG_{ag.date.strftime('%Y-%m-%d')}_{copro.nom.replace(' ', '_')}.pdf"
    return Response(
        content=pdf.getvalue(),
        media_type="application/pdf",
        # Nom accentué (« Résidence… ») : filename*=utf-8'' (un en-tête HTTP n'accepte que le latin-1).
        headers={"Content-Disposition": _content_disposition(nom)},
    )


@router.post("/ag/{ag_id}/pv/envoyer", response_model=InvitationsResult)
def envoyer_pv(ag_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Envoie le PV en PDF (pièce jointe) à tous les propriétaires ayant un email."""
    copro = get_or_create_copro(db, user)
    ag = get_owned(db, AG, ag_id, copro, label="AG")

    pdf = generer_pv_pdf(copro, ag, db)
    nom_fichier = f"PV_AG_{ag.date.strftime('%Y-%m-%d')}.pdf"

    lots = db.query(Lot).filter(Lot.copropriete_id == copro.id).all()
    proprietaires = {lot.proprietaire_id for lot in lots if lot.proprietaire_id}
    personnes = db.query(User).filter(User.id.in_(proprietaires)).all() if proprietaires else []

    type_label = _TYPE_AG_LABEL.get(ag.type_ag, "l'assemblée générale")
    corps = pv_email_texte(copro, ag, user.nom or "Le syndic")
    sujet = f"Information : PV de {type_label} — {copro.nom} ({ag.date.strftime('%d/%m/%Y')})"

    envoyes = 0
    sans_email = 0
    erreurs = []
    for p in personnes:
        if not p.email:
            sans_email += 1
            continue
        try:
            envoyer_email(copro, p.email, sujet, corps, [(nom_fichier, pdf.getvalue(), "application/pdf")])
            envoyes += 1
        except EmailError as e:
            erreurs.append(f"{p.nom}: {e}")
    return InvitationsResult(envoyes=envoyes, sans_email=sans_email, erreurs=erreurs)


_TYPE_AG_LABEL = {
    "annuelle": "l'assemblée générale annuelle",
    "extraordinaire": "l'assemblée générale extraordinaire",
    "consultation_ecrite": "la consultation écrite",
}

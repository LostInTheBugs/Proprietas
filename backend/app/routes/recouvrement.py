"""Recouvrement : dossiers par lot, mise en demeure PDF, actes, article 19-2.

Toutes les routes sont réservées au syndic (procédure interne sensible).
Le statut du dossier est calculé à la lecture (services/recouvrement.py).
"""
import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core import audit
from app.core.database import get_db
from app.core.deps import require_syndic
from app.models.copropriete import Copropriete
from app.models.lot import Lot
from app.models.recouvrement import ActeRecouvrement
from app.models.relance import Relance
from app.models.user import User
from app.routes.copro import get_or_create_copro
from app.schemas import (
    DecompteLigne,
    Mise19_2Out,
    RecouvrementActeIn,
    RecouvrementActeOut,
    RecouvrementDossierOut,
    RecouvrementLotOut,
    RelanceOut,
)
from app.services import recouvrement as svc
from app.services.md_pdf import generer_mise_en_demeure_pdf

router = APIRouter(prefix="/api/recouvrement", tags=["recouvrement"])

LIBELLES_TYPE = {
    "mise_en_demeure": "Mise en demeure",
    "frais": "Frais de recouvrement",
    "activation_19_2": "Activation de l'article 19-2",
    "conciliation": "Procédure amiable (conciliation)",
    "commissaire_justice": "Commissaire de justice",
    "tribunal": "Saisine du tribunal",
    "note": "Note",
}


def _lot_ou_404(db: Session, copro: Copropriete, lot_id: int) -> Lot:
    lot = db.query(Lot).filter(Lot.id == lot_id, Lot.copropriete_id == copro.id).first()
    if not lot:
        raise HTTPException(404, "Lot introuvable")
    return lot


def _proprio(db: Session, lot: Lot) -> User | None:
    """Propriétaire du lot = compte utilisateur (modèle « zéro fiche »)."""
    return db.query(User).filter(User.id == lot.proprietaire_id).first() if lot.proprietaire_id else None


def _nom(p: User | None) -> str:
    return f"{p.prenom} {p.nom}".strip() if p else "—"


def _acte_out(db: Session, a: ActeRecouvrement) -> RecouvrementActeOut:
    auteur = ""
    if a.created_by_id:
        u = db.query(User).filter(User.id == a.created_by_id).first()
        if u:
            auteur = u.nom or u.email or ""
    return RecouvrementActeOut(
        id=a.id, type=a.type, date_acte=a.date_acte, date_envoi=a.date_envoi,
        mode_envoi=a.mode_envoi or "", reference=a.reference or "",
        montant=a.montant or 0.0, libelle=a.libelle or LIBELLES_TYPE.get(a.type, a.type),
        auteur=auteur,
    )


def _ligne_out(l: dict) -> DecompteLigne:
    return DecompteLigne(
        exercice=l.get("exercice"), libelle=l.get("libelle") or "", echeance=l.get("echeance"),
        charges=l.get("charges") or 0.0, fonds=l.get("fonds") or 0.0,
        montant=l.get("montant") or 0.0, restant_du=l.get("restant_du") or 0.0,
        echu=bool(l.get("echu")),
    )


def _snapshot(lignes: list[dict]) -> str:
    def conv(v):
        return v.isoformat() if hasattr(v, "isoformat") else v
    return json.dumps([{k: conv(v) for k, v in l.items()} for l in lignes])


def _conditions_19_2(d: dict) -> None:
    if d["md"] is None or (d["md_jours"] if d["md_jours"] is not None else -1) < svc.DELAI_19_2_JOURS:
        raise HTTPException(
            400, "Article 19-2 : une mise en demeure restée infructueuse pendant 30 jours est requise.")


@router.get("", response_model=list[RecouvrementLotOut])
def liste(db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """État des dossiers de recouvrement, par lot."""
    copro = get_or_create_copro(db, user)
    out = []
    for lot in db.query(Lot).filter(Lot.copropriete_id == copro.id).order_by(Lot.numero).all():
        d = svc.statut_dossier(db, copro, lot)
        p = _proprio(db, lot)
        out.append(RecouvrementLotOut(
            lot_id=lot.id, lot_numero=lot.numero,
            personne_id=p.id if p else None, personne_nom=_nom(p),
            personne_email=p.email if p else "",
            solde=d["solde"], retard_depuis=d["retard_depuis"], statut=d["statut"],
            statut_label=d["statut_label"],
            md_date=d["md"].date_envoi if d["md"] else None,
            md_jours=d["md_jours"], jours_restants=d["jours_restants"],
            frais_total=d["frais_total"], interets=d["interets"], total_reclame=d["total_reclame"],
        ))
    return out


@router.get("/lot/{lot_id}", response_model=RecouvrementDossierOut)
def dossier(lot_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Dossier complet d'un lot : décompte, actes, relances, calculs."""
    copro = get_or_create_copro(db, user)
    lot = _lot_ou_404(db, copro, lot_id)
    lignes = svc.appels_lot(db, copro, lot)
    d = svc.statut_dossier(db, copro, lot, lignes=lignes)
    p = _proprio(db, lot)
    relances = (db.query(Relance).filter(Relance.lot_id == lot.id)
                .order_by(Relance.date_envoi.desc()).limit(30).all())
    return RecouvrementDossierOut(
        lot_id=lot.id, lot_numero=lot.numero,
        personne_nom=_nom(p), personne_email=p.email if p else "",
        personne_adresse=(getattr(p, "adresse", "") or "") if p else "",
        solde=d["solde"], arriere_echu=d["arriere_echu"], retard_depuis=d["retard_depuis"],
        statut=d["statut"], statut_label=d["statut_label"],
        md_date=d["md"].date_envoi if d["md"] else None,
        md_jours=d["md_jours"], jours_restants=d["jours_restants"],
        frais_total=d["frais_total"], interets=d["interets"], taux_legal=d["taux"],
        total_reclame=d["total_reclame"],
        decompte=[_ligne_out(l) for l in lignes],
        actes=[_acte_out(db, a) for a in d["actes"]],
        relances=[RelanceOut(
            id=r.id, lot_id=r.lot_id, lot_numero=lot.numero, personne_nom=_nom(p),
            personne_email=p.email if p else "", date_envoi=r.date_envoi,
            statut=r.statut, montant_du=r.montant_du or 0.0, message=r.message or "",
        ) for r in relances],
    )


@router.get("/lot/{lot_id}/mise-en-demeure.pdf")
def mise_en_demeure_pdf(lot_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """PDF de mise en demeure (délai 30 jours, article 19-2) — provisions échues impayées."""
    copro = get_or_create_copro(db, user)
    lot = _lot_ou_404(db, copro, lot_id)
    lignes = [l for l in svc.appels_lot(db, copro, lot) if l["restant_du"] > 0.005 and l["echu"]]
    if not lignes:
        raise HTTPException(400, "Aucune provision échue impayée : la mise en demeure n'est pas justifiée.")
    buf = generer_mise_en_demeure_pdf(copro, lot, _proprio(db, lot), lignes, user.nom or "")
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="mise-en-demeure-lot-{lot.numero}.pdf"'},
    )


@router.post("/lot/{lot_id}/acte", response_model=RecouvrementActeOut)
def creer_acte(lot_id: int, data: RecouvrementActeIn, request: Request,
               db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Enregistre un acte du dossier (mise en demeure, frais, étapes amiables/judiciaires, note)."""
    copro = get_or_create_copro(db, user)
    lot = _lot_ou_404(db, copro, lot_id)
    if data.type not in svc.TYPES_ACTE:
        raise HTTPException(422, "Type d'acte invalide")
    if data.type == "frais" and (data.montant or 0) <= 0:
        raise HTTPException(422, "Montant des frais requis")
    if data.type == "mise_en_demeure":
        if not data.date_envoi:
            raise HTTPException(422, "Date d'envoi requise pour la mise en demeure")
        if (data.mode_envoi or "") not in svc.MODES_ENVOI:
            raise HTTPException(422, "Mode d'envoi requis (lre | lrar | email | remise)")

    lignes = svc.appels_lot(db, copro, lot)
    montant = round(data.montant or 0.0, 2)
    details = ""
    if data.type == "mise_en_demeure":
        echu = [l for l in lignes if l["restant_du"] > 0.005 and l["echu"]]
        if not echu:
            raise HTTPException(400, "Aucune provision échue impayée : mise en demeure sans objet.")
        montant = round(sum(l["restant_du"] for l in echu), 2)
        details = _snapshot(echu)

    acte = ActeRecouvrement(
        copropriete_id=copro.id, lot_id=lot.id, personne_id=lot.proprietaire_id,
        type=data.type, date_envoi=data.date_envoi,
        mode_envoi=data.mode_envoi if data.type == "mise_en_demeure" else "",
        reference=data.reference or "", montant=montant, libelle=data.libelle or "",
        details_json=details, created_by_id=user.id,
    )
    db.add(acte)
    detail = f"Lot {lot.numero} — {LIBELLES_TYPE.get(data.type, data.type)}"
    if montant:
        detail += f" — {montant:.2f} €"
    if data.date_envoi and data.type == "mise_en_demeure":
        detail += f" (envoyée le {data.date_envoi:%d/%m/%Y}, {data.mode_envoi})"
    audit.enregistrer(db, "recouvrement_acte", user=user, copro_id=copro.id, request=request, detail=detail)
    db.commit()
    db.refresh(acte)
    return _acte_out(db, acte)


@router.delete("/acte/{acte_id}")
def supprimer_acte(acte_id: int, request: Request,
                   db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Supprime un acte saisi par erreur (tracé dans le journal d'audit)."""
    copro = get_or_create_copro(db, user)
    acte = db.query(ActeRecouvrement).filter(
        ActeRecouvrement.id == acte_id, ActeRecouvrement.copropriete_id == copro.id).first()
    if not acte:
        raise HTTPException(404, "Acte introuvable")
    lot = db.query(Lot).filter(Lot.id == acte.lot_id).first()
    audit.enregistrer(
        db, "recouvrement_acte_supprime", user=user, copro_id=copro.id, request=request,
        detail=(f"Lot {lot.numero if lot else acte.lot_id} — "
                f"{LIBELLES_TYPE.get(acte.type, acte.type)} du {acte.date_acte:%d/%m/%Y}"))
    db.delete(acte)
    db.commit()
    return {"ok": True}


@router.get("/lot/{lot_id}/19-2", response_model=Mise19_2Out)
def apercu_19_2(lot_id: int, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Aperçu des sommes devenues exigibles au titre de l'article 19-2."""
    copro = get_or_create_copro(db, user)
    lot = _lot_ou_404(db, copro, lot_id)
    lignes = svc.appels_lot(db, copro, lot)
    d = svc.statut_dossier(db, copro, lot, lignes=lignes)
    _conditions_19_2(d)
    b = svc.breakdown_19_2(db, copro, lot, lignes=lignes)
    return Mise19_2Out(
        lignes=[_ligne_out(l) for l in b["lignes"]], total=b["total"],
        arriere_echu=b["arriere_echu"], exercice=b["exercice"],
    )


@router.post("/lot/{lot_id}/19-2", response_model=Mise19_2Out)
def activer_19_2(lot_id: int, request: Request,
                 db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Enregistre l'exigibilité immédiate des provisions (art. 19-2) — décision du syndic, tracée."""
    copro = get_or_create_copro(db, user)
    lot = _lot_ou_404(db, copro, lot_id)
    lignes = svc.appels_lot(db, copro, lot)
    d = svc.statut_dossier(db, copro, lot, lignes=lignes)
    _conditions_19_2(d)
    b = svc.breakdown_19_2(db, copro, lot, lignes=lignes)
    if b["total"] <= 0.005:
        raise HTTPException(400, "Aucune provision future à rendre exigible.")
    acte = ActeRecouvrement(
        copropriete_id=copro.id, lot_id=lot.id, personne_id=lot.proprietaire_id,
        type="activation_19_2", date_envoi=date.today(), montant=b["total"],
        libelle="Article 19-2 — provisions rendues immédiatement exigibles",
        details_json=_snapshot(b["lignes"]), created_by_id=user.id,
    )
    db.add(acte)
    audit.enregistrer(
        db, "recouvrement_19_2", user=user, copro_id=copro.id, request=request,
        detail=f"Lot {lot.numero} — {b['total']:.2f} € deviennent exigibles (article 19-2)")
    db.commit()
    db.refresh(acte)
    return Mise19_2Out(
        lignes=[_ligne_out(l) for l in b["lignes"]], total=b["total"],
        arriere_echu=b["arriere_echu"], exercice=b["exercice"],
    )

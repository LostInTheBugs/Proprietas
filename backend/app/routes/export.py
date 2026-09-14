import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session
from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user, require_syndic
from app.models.user import User
from app.models.lot import Lot
from app.models.exercice import Exercice
from app.models.appel import AppelFonds, AppelLot
from app.models.mouvement import Mouvement
from app.routes.copro import get_or_create_copro
from app.routes.relances import _etat_lots
from app.services.compte_gestion import generer_compte_gestion_pdf
from app.services.quittances import generer_quittances_pdf
from app.services.rapport_annuel import generer_rapport_annuel_pdf
from app.services.emailer import envoyer_email, situation_texte, EmailError
from app.schemas import InvitationsResult

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/rapport-annuel/{exercice_id}")
def rapport_annuel(exercice_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Rapport annuel complet en PDF : garde + KPI + compte de gestion + statistiques + PPT."""
    from app.models.copropriete import Copropriete
    copro = get_or_create_copro(db, user)
    ex = db.query(Exercice).filter(Exercice.id == exercice_id, Exercice.copropriete_id == copro.id).first()
    if not ex:
        raise HTTPException(404, "Exercice introuvable")
    pdf = generer_rapport_annuel_pdf(copro, ex, db)
    audit.enregistrer(db, "export_rapport_annuel", user=user, copro_id=copro.id,
                      detail=f"Exercice {ex.annee}", request=request)
    db.commit()
    nom = f"Rapport_annuel_{ex.annee}_{copro.nom.replace(' ', '_')}.pdf"
    return Response(
        content=pdf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


@router.get("/compte-gestion/{exercice_id}")
def compte_gestion(exercice_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Compte de gestion annuel en PDF (présenté en AG pour approbation)."""
    from app.models.copropriete import Copropriete
    copro = get_or_create_copro(db, user)
    ex = db.query(Exercice).filter(Exercice.id == exercice_id, Exercice.copropriete_id == copro.id).first()
    if not ex:
        raise HTTPException(404, "Exercice introuvable")
    pdf = generer_compte_gestion_pdf(copro, ex, db)
    audit.enregistrer(db, "export_compte_gestion", user=user, copro_id=copro.id,
                      detail=f"Exercice {ex.annee}", request=request)
    db.commit()
    nom = f"Compte_de_gestion_{ex.annee}_{copro.nom.replace(' ', '_')}.pdf"
    return Response(
        content=pdf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


@router.get("/quittances/{exercice_id}")
def quittances(exercice_id: int, request: Request, lot_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Quittances d'appels de fonds de l'exercice, groupées en un PDF (une page par lot).

    - lot_id absent : toutes les quittances de l'exercice
    - lot_id présent : quittance d'un seul lot
    """
    copro = get_or_create_copro(db, user)
    ex = db.query(Exercice).filter(Exercice.id == exercice_id, Exercice.copropriete_id == copro.id).first()
    if not ex:
        raise HTTPException(404, "Exercice introuvable")
    pdf = generer_quittances_pdf(copro, ex, db, lot_ids={lot_id} if lot_id else None)
    audit.enregistrer(db, "export_quittances", user=user, copro_id=copro.id,
                      detail=f"Exercice {ex.annee}" + (f", lot {lot_id}" if lot_id else ""),
                      request=request)
    db.commit()
    suffixe = f"_lot{lot_id}" if lot_id else ""
    nom = f"Quittances_{ex.annee}{suffixe}_{copro.nom.replace(' ', '_')}.pdf"
    return Response(
        content=pdf.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


@router.post("/situation-fonds")
def envoyer_situation_fonds(request: Request, db: Session = Depends(get_db), user: User = Depends(require_syndic)):
    """Envoie à chaque copropriétaire la situation du fonds de travaux et de son lot."""
    from app.models.exercice import Exercice, BudgetLine
    from app.models.copropriete import Copropriete
    copro = get_or_create_copro(db, user)
    ex = (db.query(Exercice)
          .filter(Exercice.copropriete_id == copro.id, Exercice.cloture == False)
          .order_by(Exercice.annee.desc()).first())
    if not ex:
        ex = (db.query(Exercice).filter(Exercice.copropriete_id == copro.id)
              .order_by(Exercice.annee.desc()).first())
    if not ex:
        raise HTTPException(404, "Aucun exercice — créez d'abord l'exercice en cours dans l'onglet Comptes")

    budget = sum(b.montant for b in db.query(BudgetLine).filter(BudgetLine.exercice_id == ex.id).all())
    objectif_ft = round(budget * 0.05, 2)
    ft_encaisse = round(sum(m.montant for m in db.query(Mouvement).filter(
        Mouvement.type == "encaissement", Mouvement.categorie == "fonds_travaux").all()), 2)
    ft_depense = round(sum(m.montant for m in db.query(Mouvement).filter(
        Mouvement.type == "depense", Mouvement.categorie == "fonds_travaux").all()), 2)
    ft_encours = round(ft_encaisse - ft_depense, 2)

    envoye, sans_email, erreurs = 0, 0, []
    for e in _etat_lots(db, copro):
        p = e["personne"]
        if not p or not p.email:
            sans_email += 1
            continue
        sujet = f"Situation du fonds de travaux — {copro.nom}"
        corps = situation_texte(
            copro, p.prenom, e["lot"].numero, e["solde"],
            ft_encaisse, ft_depense, ft_encours, objectif_ft,
            user.nom or "le syndic",
        )
        try:
            envoyer_email(copro, p.email, sujet, corps)
            envoye += 1
        except EmailError as err:
            erreurs.append(f"{p.prenom} {p.nom}: {err}")
    audit.enregistrer(db, "situation_fonds", user=user, copro_id=copro.id,
                      detail=f"{envoye} envoi(s), {sans_email} sans email", request=request)
    db.commit()
    return InvitationsResult(envoyes=envoye, sans_email=sans_email, erreurs=erreurs)


def _csv(data: list[list], headers: list[str]) -> StreamingResponse:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(headers)
    writer.writerows(data)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=export.csv"},
    )


@router.get("/registre")
def export_registre(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Données utiles pour la déclaration au registre des copropriétés
    (registre.coproprietes.gouv.fr)."""
    copro = get_or_create_copro(db, user)
    audit.enregistrer(db, "export_registre", user=user, copro_id=copro.id,
                      detail=copro.nom, request=request)
    db.commit()
    lots = db.query(Lot).filter(Lot.copropriete_id == copro.id).all()
    rows = []
    for lot in lots:
        prop = lot.proprietaire
        rows.append([
            copro.nom, copro.adresse, copro.code_postal, copro.ville,
            lot.numero, lot.type, lot.tantiemes,
            prop.nom if prop else "", prop.prenom if prop else "",
            prop.email if prop else "",
        ])
    return _csv(rows, [
        "Copro", "Adresse", "Code postal", "Ville", "Lot", "Type",
        "Millièmes", "Propriétaire nom", "Propriétaire prénom", "Email",
    ])


@router.get("/compte-gestion")
def export_compte_gestion(request: Request, exercice_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Grand livre comptable de l'exercice en CSV (dates, appels par lot, mouvements, totaux)."""
    copro = get_or_create_copro(db, user)
    audit.enregistrer(db, "export_csv", user=user, copro_id=copro.id,
                      detail=f"Exercice {exercice_id or 'dernier'}", request=request)
    db.commit()
    ex = None
    if exercice_id:
        ex = db.query(Exercice).filter(Exercice.id == exercice_id, Exercice.copropriete_id == copro.id).first()
    if not ex:
        ex = db.query(Exercice).filter(Exercice.copropriete_id == copro.id).order_by(Exercice.annee.desc()).first()
    if not ex:
        return _csv([], ["Date", "Libellé", "Lot", "Catégorie", "Débit (€)", "Crédit (€)"])
    rows = []
    total_debit = 0.0
    total_credit = 0.0

    def ligne(date, libelle, lot, categorie, debit, credit):
        nonlocal total_debit, total_credit
        rows.append([date, libelle, lot, categorie,
                     f"{debit:.2f}".replace(".", ",") if debit else "",
                     f"{credit:.2f}".replace(".", ",") if credit else ""])
        total_debit += debit or 0
        total_credit += credit or 0

    # Appels de fonds (une ligne par lot)
    appels = db.query(AppelFonds).filter(AppelFonds.exercice_id == ex.id).order_by(AppelFonds.date_echeance, AppelFonds.id).all()
    for appel in appels:
        for part in appel.parts:
            lot = db.query(Lot).filter(Lot.id == part.lot_id).first()
            label = appel.libelle or "Appel de fonds"
            ligne(appel.date_echeance.strftime("%d/%m/%Y") if appel.date_echeance else "",
                  f"{label} — charges", f"lot {lot.numero}" if lot else "",
                  "appel charges", part.montant_charges, 0)
            if part.montant_fonds_travaux > 0:
                ligne(appel.date_echeance.strftime("%d/%m/%Y") if appel.date_echeance else "",
                      f"{label} — fonds de travaux", f"lot {lot.numero}" if lot else "",
                      "appel fonds travaux", part.montant_fonds_travaux, 0)

    # Mouvements (dépenses et encaissements)
    mouvements = db.query(Mouvement).filter(Mouvement.exercice_id == ex.id).order_by(Mouvement.date, Mouvement.id).all()
    for m in mouvements:
        lot = db.query(Lot).filter(Lot.id == m.lot_id).first() if m.lot_id else None
        cat = "fonds de travaux" if m.categorie == "fonds_travaux" else "charges"
        if m.type == "depense":
            ligne(m.date.strftime("%d/%m/%Y"), m.libelle, f"lot {lot.numero}" if lot else "copro",
                  f"dépense {cat}", m.montant, 0)
        else:
            ligne(m.date.strftime("%d/%m/%Y"), m.libelle, f"lot {lot.numero}" if lot else "copro",
                  f"encaissement {cat}", 0, m.montant)

    rows.append(["TOTAL", "", "", "", f"{total_debit:.2f}".replace(".", ","), f"{total_credit:.2f}".replace(".", ",")])
    rows.append(["", "Solde (débits − crédits)", "", "", "",
                 f"{(total_debit - total_credit):.2f}".replace(".", ",")])
    return _csv(rows, ["Date", "Libellé", "Lot", "Catégorie", "Débit (€)", "Crédit (€)"])

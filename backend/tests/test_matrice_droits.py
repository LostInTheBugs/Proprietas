"""Matrice des droits : toutes les routes de l'API, avec chaque type de compte (avis de Perplexity relayé par Fred,
21/11/2026 : « prouver par une matrice de tests d'autorisation générée automatiquement »).

Pour chaque route déclarée (méthode + chemin) :
1. **Routes publiques** : la liste des routes sans authentification est figée ci-dessous. Une nouvelle route
   publique fait échouer le test tant qu'elle n'y est pas ajoutée, sciemment.
2. **Non connecté**, puis **jeton de double authentification** (portée limitée) : 401 partout ailleurs.
3. **Copropriétaire** : 403 sur toutes les routes réservées au syndic ou à l'administrateur ; les routes où il
   écrit lui-même sont figées dans une liste (chacune contrôle ensuite le propriétaire de l'objet).
4. **Syndic qui n'administre pas l'instance** : 403 sur les routes de l'administrateur.
5. **Syndic d'une autre copropriété**, avec les identifiants des objets de la copropriété A : jamais de succès
   (2xx), et aucune ligne de la copropriété A n'est modifiée ni supprimée.
"""
import hashlib
import json
import re
from datetime import date, datetime, timedelta

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import text

from app.core import deps
from app.core.security import create_access_token, create_scoped_token
from app.main import app
from tests.conftest import _make_membre, auth

AUTH = {deps.get_current_user, deps.require_syndic, deps.require_instance_admin}
SYNDIC = {deps.require_syndic, deps.require_instance_admin}

# Sans authentification, et pourquoi.
PUBLIQUES = {
    ("GET", "/api/health"), ("GET", "/api/version"),                          # supervision
    ("POST", "/api/auth/login"), ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/register"),                                            # premier compte seulement
    ("POST", "/api/auth/2fa/verify-login"),                                    # jeton de défi dans le corps
    ("POST", "/api/auth/2fa/setup"), ("POST", "/api/auth/2fa/verify"),         # jeton d'enrôlement (2fa_setup)
    ("GET", "/api/ag/confirmation/{jeton}"), ("POST", "/api/ag/confirmation/{jeton}"),
    ("GET", "/api/ag/confirmation/{jeton}/pouvoir"),                           # lien personnel de l'e-mail
    ("GET", "/api/drive/google/retour"),                                       # retour OAuth (state signé)
    ("GET", "/api/majorites"), ("GET", "/api/travaux/categories"), ("GET", "/api/travaux/statuts"),
    ("GET", "/api/contacts/types"), ("GET", "/api/contacts/categories"),
    ("GET", "/api/contrats/types"), ("GET", "/api/contrats/periodes"),         # listes de référence
}
# Écritures permises au copropriétaire (connecté, sans être syndic) ; la route contrôle l'objet.
ECRITURES_COPROPRIETAIRE = {
    ("POST", "/api/auth/switch-copro/{copro_id}"), ("PUT", "/api/auth/me"), ("PUT", "/api/auth/me/voie-postale"),
    ("POST", "/api/auth/theme"), ("POST", "/api/auth/session"), ("POST", "/api/auth/logout-all"),
    ("POST", "/api/auth/2fa/disable"), ("POST", "/api/auth/2fa/recovery-codes"),
    ("PUT", "/api/lots/{lot_id}/occupation"),                  # ses propres lots
    ("PUT", "/api/ag/{ag_id}/ma-reponse"), ("PUT", "/api/resolutions/{res_id}/mon-vote"),
    ("POST", "/api/auth/users/{user_id}/debloquer"),           # contrôlé par _compte_gere (syndic ou admin)
}
# Tables modifiées par les requêtes elles-mêmes (journal, connexions) : hors de l'empreinte.
HORS_EMPREINTE = {"audit_logs", "connexions", "alembic_version"}


def _deps(dependant, acc=None):
    acc = set() if acc is None else acc
    if dependant.call:
        acc.add(dependant.call)
    for d in dependant.dependencies:
        _deps(d, acc)
    return acc


ROUTES = sorted(((m, r.path, r) for r in app.routes if isinstance(r, APIRoute) for m in r.methods),
                key=lambda x: (x[1], x[0]))


def _role(route) -> str:
    d = _deps(route.dependant)
    if deps.require_instance_admin in d:
        return "admin"
    if deps.require_syndic in d:
        return "syndic"
    return "connecte" if d & AUTH else "public"


# ---------------------------------------------------------------- données de la copropriété A
@pytest.fixture
def objets(db, copro_a, syndic_a):
    """Un objet de chaque sorte dans la copropriété A ; paramètre de chemin → identifiant."""
    from app.models.ag import AG, AgCreneau, AgReponse, Resolution
    from app.models.appel import AppelFonds, AppelLot
    from app.models.carnet import Entretien
    from app.models.cle import CleLot, CleRepartition
    from app.models.contact import Contact
    from app.models.contrat import Contrat
    from app.models.document import Document
    from app.models.exercice import BudgetLine, Exercice
    from app.models.lot import Lot
    from app.models.mandat import Mandat
    from app.models.mouvement import Mouvement
    from app.models.mutation import Mutation
    from app.models.notification import NotificationPV
    from app.models.recouvrement import ActeRecouvrement
    from app.models.releve import LigneReleve
    from app.models.reprise import EtatReprise
    from app.models.travaux import Travaux
    m = _make_membre(db, "proprietaire.a@test.fr", copro_a)
    c = copro_a.id
    lot = Lot(copropriete_id=c, numero="1", tantiemes=500, proprietaire_id=m.id)
    ex = Exercice(copropriete_id=c, annee=date.today().year)
    ag = AG(copropriete_id=c, date=date.today() + timedelta(days=30))
    db.add_all([lot, ex, ag])
    db.flush()
    res = Resolution(ag_id=ag.id, numero=1, libelle="Ravalement")
    appel = AppelFonds(exercice_id=ex.id, libelle="T1", date_emission=date.today(), date_echeance=date.today(),
                       montant_total=100)
    cle = CleRepartition(copropriete_id=c, nom="Escalier")
    o = {
        "lot_id": lot, "exercice_id": ex, "ag_id": ag, "res_id": res, "appel_id": appel, "cle_id": cle,
        "contact_id": Contact(copropriete_id=c, nom="Plombier"),
        "contrat_id": Contrat(copropriete_id=c, libelle="Assurance"),
        "entretien_id": Entretien(copropriete_id=c, date=date.today(), description="Contrôle"),
        "travaux_id": Travaux(copropriete_id=c, libelle="Toiture", annee=date.today().year),
        "mutation_id": Mutation(copropriete_id=c, lot_id=lot.id, date_acte=date.today(), vendeur_id=m.id,
                                creee_le=datetime.now()),
        "ligne_id": LigneReleve(copropriete_id=c, compte="syndicat", date=date.today(), montant=10, empreinte="x", importe_le=datetime.now()),
        "acte_id": ActeRecouvrement(copropriete_id=c, lot_id=lot.id, type="mise_en_demeure", date_envoi=date.today()),
        "etat_id": EtatReprise(copropriete_id=c, date=date(date.today().year - 1, 12, 31)),
        "line_id": BudgetLine(exercice_id=ex.id, libelle="Entretien", montant=100),
        "mouvement_id": Mouvement(copropriete_id=c, exercice_id=ex.id, date=date.today(), libelle="Virement",
                                  type="encaissement", categorie="charges", montant=50, lot_id=lot.id),
        "doc_id": Document(copropriete_id=c, categorie="facture", libelle="Facture", fichier="inexistant.pdf", date_ajout=date.today()),
        "creneau_id": AgCreneau(ag_id=ag.id, debut=datetime.now() + timedelta(days=20)),
        "notif_id": NotificationPV(ag_id=ag.id, user_id=m.id, nom="Membre"),
        "mandat_id": Mandat(copropriete_id=c, role="conseil", debut=date.today(), fin=date.today(), membres=[]),
    }
    db.add_all(list(o.values()))
    db.flush()
    db.add_all([AppelLot(appel_id=appel.id, lot_id=lot.id, montant_charges=100, montant_fonds_travaux=0),
                CleLot(cle_id=cle.id, lot_id=lot.id, tantiemes=100),
                AgReponse(ag_id=ag.id, personne_id=m.id, reponse="present", repondu_le=datetime.now())])
    db.commit()
    ids = {k: v.id for k, v in o.items()}
    ids.update(user_id=m.id, personne_id=m.id, copro_id=c, jeton="x" * 32)
    return ids, m


def _chemin(path: str, ids: dict) -> str:
    def remplacer(mt):
        assert mt.group(1) in ids, f"paramètre {mt.group(1)} sans objet de test : à ajouter dans la fixture"
        return str(ids[mt.group(1)])
    return re.sub(r"{(\w+)}", remplacer, path)


def _exemple(schema: dict, defs: dict, profondeur=0):
    """Valeur plausible pour un schéma JSON (corps de requête), pour dépasser la validation quand c'est possible."""
    if "$ref" in schema:
        return _exemple(defs[schema["$ref"].split("/")[-1]], defs, profondeur)
    for cle in ("anyOf", "oneOf", "allOf"):
        if cle in schema:
            options = [s for s in schema[cle] if s.get("type") != "null"] or schema[cle]
            return _exemple(options[0], defs, profondeur)
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema and schema["default"] is not None:
        return schema["default"]
    t = schema.get("type")
    if t == "object" and profondeur < 4:
        return {k: _exemple(v, defs, profondeur + 1) for k, v in schema.get("properties", {}).items()
                if k in schema.get("required", [])}
    if t == "array":
        return []
    if t == "integer":
        return max(1, int(schema.get("minimum", 1)))
    if t == "number":
        return 1
    if t == "boolean":
        return False
    if t == "string":
        fmt = schema.get("format")
        return {"date": str(date.today()), "date-time": datetime.now().isoformat(timespec="seconds"),
                "email": "x@exemple.fr"}.get(fmt, "x")
    return None


def _corps(route):
    if route.body_field is None:
        return None
    try:
        from pydantic import TypeAdapter
        schema = TypeAdapter(route.body_field.field_info.annotation).json_schema()
        return _exemple(schema, schema.get("$defs", {}))
    except Exception:  # noqa: BLE001 — corps de type particulier (formulaire, fichier) : vide
        return {}


def _appel(client, methode, chemin, route, headers):
    corps = _corps(route)
    return client.request(methode, chemin, headers=headers, **({"json": corps} if corps is not None else {}))


def _empreinte(db, copro_id: int) -> str:
    """Contenu de toutes les tables (hors journal et connexions) : toute écriture le change."""
    h = hashlib.sha256()
    for (nom,) in db.execute(text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")):
        if nom in HORS_EMPREINTE:
            continue
        for ligne in db.execute(text(f'SELECT * FROM "{nom}" ORDER BY 1')):
            h.update(json.dumps([str(x) for x in ligne]).encode())
    return h.hexdigest()


# ---------------------------------------------------------------- 1. inventaire figé
def test_routes_publiques_et_ecritures_du_coproprietaire_figees():
    publiques = {(m, p) for m, p, r in ROUTES if _role(r) == "public"}
    assert publiques == PUBLIQUES, f"nouvelles : {publiques - PUBLIQUES} ; disparues : {PUBLIQUES - publiques}"
    ecritures = {(m, p) for m, p, r in ROUTES if _role(r) == "connecte" and m != "GET"}
    assert ecritures == ECRITURES_COPROPRIETAIRE, \
        f"nouvelles : {ecritures - ECRITURES_COPROPRIETAIRE} ; disparues : {ECRITURES_COPROPRIETAIRE - ecritures}"


# ---------------------------------------------------------------- 2. non connecté, jeton 2FA
def test_non_connecte_et_jeton_2fa_refuses(client, db, syndic_a, objets):
    ids, _ = objets
    defi = create_scoped_token(syndic_a.id, "2fa_challenge", minutes=5)
    erreurs = []
    for m, p, r in ROUTES:
        if (m, p) in PUBLIQUES:
            continue
        chemin = _chemin(p, ids)
        client.cookies.clear()
        for nom, headers in (("non connecté", {}), ("jeton 2FA", auth(defi))):
            code = _appel(client, m, chemin, r, headers).status_code
            if code != 401:
                erreurs.append(f"{nom} : {m} {p} → {code}")
    assert not erreurs, "\n".join(erreurs)


# ---------------------------------------------------------------- 3. et 4. rôles
def test_coproprietaire_et_syndic_non_admin(client, db, copro_a, syndic_a, token_a, objets):
    ids, membre = objets
    t_membre = create_access_token(membre.id, copro_a.id)
    erreurs = []
    for m, p, r in ROUTES:
        role = _role(r)
        if role in ("syndic", "admin"):
            code = _appel(client, m, _chemin(p, ids), r, auth(t_membre)).status_code
            if code != 403:
                erreurs.append(f"copropriétaire : {m} {p} → {code}")
        if role == "admin":
            code = _appel(client, m, _chemin(p, ids), r, auth(token_a)).status_code
            if code != 403:
                erreurs.append(f"syndic non administrateur : {m} {p} → {code}")
    assert not erreurs, "\n".join(erreurs)


# ---------------------------------------------------------------- 5. autre copropriété
def test_syndic_d_une_autre_copropriete(client, db, copro_a, syndic_b, token_b, objets):
    ids, _ = objets
    avant = _empreinte(db, copro_a.id)
    erreurs = []
    for m, p, r in ROUTES:
        if "{" not in p or (m, p) in PUBLIQUES or p.startswith("/api/auth/switch-copro"):
            continue
        rep = _appel(client, m, _chemin(p, ids), r, auth(token_b))
        if 200 <= rep.status_code < 300:
            erreurs.append(f"{m} {p} → {rep.status_code}")
    db.expire_all()
    assert not erreurs, "\n".join(erreurs)
    assert _empreinte(db, copro_a.id) == avant, "des données de la copropriété A ont changé"
    # Changer de copropriété vers une copropriété dont on n'est pas membre : refusé.
    assert client.post(f"/api/auth/switch-copro/{copro_a.id}", headers=auth(token_b)).status_code in (403, 404)

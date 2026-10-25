"""Voie postale par copropriétaire et notification du PV (loi n° 65-557, art. 42 al. 2 et 42-1).

- La notification par voie électronique (LRE) est la règle ; la LRAR papier est due au
  copropriétaire qui a demandé la voie postale. Ce choix est enregistré sur le compte (par
  lui-même, ou par le syndic s'il l'a reçu par courrier), avec sa date.
- Le PV est notifié aux OPPOSANTS et DÉFAILLANTS (l'abstention n'est pas une opposition),
  dans le mois qui suit l'assemblée ; le délai de contestation de deux mois court à compter du
  lendemain de la première présentation (LRAR) ou de l'avis électronique (LRE).
- Le syndic prépare la liste, puis saisit pour chacun la date d'envoi, la référence et la date
  de présentation ; l'application indique la fin (indicative) du délai de contestation.
"""
from datetime import date, timedelta

import pytest

from app.core.security import create_access_token
from app.models.ag import AG, Resolution, Vote
from app.models.lot import Lot
from tests.conftest import _make_membre, auth

AUJOURDHUI = date.today()


def ajouter_mois(d, n):
    from app.services.notifications_pv import ajouter_mois as f   # module créé par le correctif
    return f(d, n)


def _membre(db, copro, email, prenom, nom):
    u = _make_membre(db, email, copro)
    u.prenom, u.nom = prenom, nom
    db.commit()
    return u


@pytest.fixture()
def seance(db, copro_a):
    """Dupont (lots 1, 2), Martin (lot 3), Bernard (lot 4), lot 5 sans propriétaire.
    Résolution 1 : Dupont pour, Martin CONTRE, Bernard et lot 5 absents.
    Résolution 2 : Dupont ABSTENTION, Martin pour, Bernard et lot 5 absents."""
    dupont = _membre(db, copro_a, "dupont@test.fr", "Jean", "Dupont")
    martin = _membre(db, copro_a, "martin@test.fr", "Claire", "Martin")
    bernard = _membre(db, copro_a, "bernard@test.fr", "Luc", "Bernard")
    owners = (dupont, dupont, martin, bernard, None)
    lots = [Lot(copropriete_id=copro_a.id, numero=str(i + 1), tantiemes=200,
                proprietaire_id=o.id if o else None) for i, o in enumerate(owners)]
    db.add_all(lots)
    ag = AG(copropriete_id=copro_a.id, date=AUJOURDHUI - timedelta(days=10), type_ag="annuelle")
    db.add(ag)
    db.flush()
    r1 = Resolution(ag_id=ag.id, numero=1, libelle="Ravalement", majorite="art24")
    r2 = Resolution(ag_id=ag.id, numero=2, libelle="Budget", majorite="art24")
    db.add_all([r1, r2])
    db.flush()
    for r, voix in ((r1, ("pour", "pour", "contre")), (r2, ("abstention", "abstention", "pour"))):
        db.add_all([Vote(resolution_id=r.id, lot_id=l.id, voix=v) for l, v in zip(lots, voix)])
    db.commit()
    return {"ag": ag, "dupont": dupont, "martin": martin, "bernard": bernard, "r1": r1}


def _preparer(client, token_a, ag):
    r = client.post(f"/api/ag/{ag.id}/notifications-pv", headers=auth(token_a))
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- liste des destinataires
def test_opposants_et_defaillants_seulement(client, token_a, seance):
    d = _preparer(client, token_a, seance["ag"])
    assert [(i["nom"], i["qualite"]) for i in d["items"]] == [
        ("Bernard Luc", "défaillant"), ("Martin Claire", "opposant")]
    assert d["items"][0]["resolutions"] == "défaillant : 1, 2"
    assert d["items"][1]["resolutions"] == "opposant : 1"
    assert d["sans_proprietaire"] == ["5"]                      # signalé, non notifiable
    assert d["limite_envoi"] == ajouter_mois(seance["ag"].date, 1).isoformat()


def test_abstention_n_est_pas_une_opposition(client, token_a, seance):
    noms = [i["nom"] for i in _preparer(client, token_a, seance["ag"])["items"]]
    assert "Dupont Jean" not in noms


def test_resolution_sans_aucun_vote_ignoree(client, token_a, db, copro_a, seance):
    ag = AG(copropriete_id=copro_a.id, date=AUJOURDHUI, type_ag="annuelle")
    db.add(ag)
    db.flush()
    db.add(Resolution(ag_id=ag.id, numero=1, libelle="Pas encore votée", majorite="art24"))
    db.commit()
    assert _preparer(client, token_a, ag)["items"] == []


# ---------------------------------------------------------------- voie postale
def test_le_coproprietaire_demande_la_voie_postale(client, db, copro_a, seance):
    tok = create_access_token(seance["bernard"].id, copro_a.id)
    r = client.put("/api/auth/me/voie-postale", json={"postale": True}, headers=auth(tok))
    assert r.status_code == 200, r.text
    assert r.json()["notification_postale"] is True
    # Art. 64-4 du décret : la demande prend effet le 9e jour suivant sa réception.
    assert r.json()["notification_postale_depuis"] == (AUJOURDHUI + timedelta(days=9)).isoformat()
    r = client.put("/api/auth/me/voie-postale", json={"postale": False}, headers=auth(tok))
    assert r.json()["notification_postale"] is False and r.json()["notification_postale_depuis"] is None


def test_mode_lrar_pour_qui_a_demande_la_voie_postale(client, token_a, seance):
    r = client.put(f"/api/auth/users/{seance['bernard'].id}/voie-postale", json={"postale": True},
                   headers=auth(token_a))
    assert r.status_code == 200, r.text
    modes = {i["nom"]: i["mode"] for i in _preparer(client, token_a, seance["ag"])["items"]}
    assert modes == {"Bernard Luc": "lrar", "Martin Claire": "lre"}


def test_syndic_ne_modifie_pas_un_compte_d_une_autre_copro(client, token_a, db, copro_b):
    autre = _make_membre(db, "autre@test.fr", copro_b)
    r = client.put(f"/api/auth/users/{autre.id}/voie-postale", json={"postale": True}, headers=auth(token_a))
    assert r.status_code == 404


# ---------------------------------------------------------------- saisie de l'envoi et délais
def _saisir(client, token_a, notif_id, **corps):
    return client.put(f"/api/notifications-pv/{notif_id}", json={"mode": "lre", **corps}, headers=auth(token_a))


def test_saisie_envoi_et_fin_du_delai_de_contestation(client, token_a, seance):
    item = _preparer(client, token_a, seance["ag"])["items"][1]
    envoi, presentation = AUJOURDHUI - timedelta(days=3), AUJOURDHUI - timedelta(days=2)
    r = _saisir(client, token_a, item["id"], date_envoi=envoi.isoformat(),
                date_presentation=presentation.isoformat(), reference="LRE-123")
    assert r.status_code == 200, r.text
    saisi = next(i for i in r.json()["items"] if i["id"] == item["id"])
    assert saisi["reference"] == "LRE-123"
    from app.services.delais import reporter   # fin reportée au premier jour ouvrable (CPC 642)
    assert saisi["fin_contestation"] == reporter(ajouter_mois(presentation, 2)).isoformat()


@pytest.mark.parametrize("corps", [
    {"date_envoi": (AUJOURDHUI + timedelta(days=1)).isoformat()},                       # futur
    {"date_presentation": (AUJOURDHUI - timedelta(days=1)).isoformat()},                # sans envoi
    {"date_envoi": AUJOURDHUI.isoformat(),
     "date_presentation": (AUJOURDHUI - timedelta(days=1)).isoformat()},                 # avant l'envoi
    {"mode": "email"},                                                                    # mode invalide
])
def test_saisies_incoherentes_refusees(client, token_a, seance, corps):
    item = _preparer(client, token_a, seance["ag"])["items"][0]
    assert _saisir(client, token_a, item["id"], **corps).status_code == 422


def test_notification_envoyee_jamais_modifiee_par_une_nouvelle_preparation(client, token_a, db, seance):
    items = _preparer(client, token_a, seance["ag"])["items"]
    bernard, martin = items[0], items[1]
    _saisir(client, token_a, bernard["id"], date_envoi=AUJOURDHUI.isoformat())
    # Bernard demande ensuite la voie postale ; Martin finit par voter « pour » (vote corrigé).
    client.put(f"/api/auth/users/{seance['bernard'].id}/voie-postale", json={"postale": True},
               headers=auth(token_a))
    vote = db.query(Vote).filter(Vote.resolution_id == seance["r1"].id, Vote.voix == "contre").one()
    vote.voix = "pour"
    db.commit()
    d = _preparer(client, token_a, seance["ag"])
    assert [(i["nom"], i["mode"]) for i in d["items"]] == [("Bernard Luc", "lre")]   # envoyée : figée


def test_retard_signale_apres_un_mois(client, token_a, db, seance):
    seance["ag"].date = AUJOURDHUI - timedelta(days=45)
    db.commit()
    assert all(i["en_retard"] for i in _preparer(client, token_a, seance["ag"])["items"])


def test_reserve_au_syndic(client, db, copro_a, seance):
    tok = create_access_token(seance["martin"].id, copro_a.id)
    assert client.get(f"/api/ag/{seance['ag'].id}/notifications-pv", headers=auth(tok)).status_code == 403


def test_ajouter_mois_fin_de_mois():
    assert ajouter_mois(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert ajouter_mois(date(2026, 11, 30), 2) == date(2027, 1, 30)


# ---------------------------------------------------------------- mode : voie postale et envoi figé
def _voie_postale(client, token_a, user, postale=True, recue_le=None):
    corps = {"postale": postale, **({"recue_le": recue_le.isoformat()} if recue_le else {})}
    r = client.put(f"/api/auth/users/{user.id}/voie-postale", json=corps, headers=auth(token_a))
    assert r.status_code == 200, r.text


def _item(d, nom):
    return next(i for i in d["items"] if i["nom"] == nom)


def test_lre_refusee_si_la_voie_postale_est_demandee(client, token_a, seance):
    """Art. 42-1 : le copropriétaire qui a demandé la voie postale ne peut pas être notifié par LRE."""
    _voie_postale(client, token_a, seance["bernard"], recue_le=AUJOURDHUI - timedelta(days=10))  # en vigueur
    bernard = _item(_preparer(client, token_a, seance["ag"]), "Bernard Luc")
    assert bernard["voie_postale_demandee"] is True
    r = _saisir(client, token_a, bernard["id"], mode="lre", date_envoi=AUJOURDHUI.isoformat())
    assert r.status_code == 422
    assert "voie postale" in r.json()["detail"]


def test_lrar_refusee_sans_demande(client, token_a, seance):
    """Décret, art. 64 et 64-1 (rédaction 2025-1292) : la LRAR n'est valable que « par exception »,
    pour le copropriétaire qui a demandé la voie postale."""
    martin = _item(_preparer(client, token_a, seance["ag"]), "Martin Claire")
    assert martin["voie_postale_demandee"] is False
    r = _saisir(client, token_a, martin["id"], mode="lrar", date_envoi=AUJOURDHUI.isoformat())
    assert r.status_code == 422


def test_mode_d_une_notification_envoyee_fige(client, token_a, seance):
    # Demande de voie postale reçue aujourd'hui : pendant 9 jours, LRE et LRAR sont admises.
    _voie_postale(client, token_a, seance["martin"])
    martin = _item(_preparer(client, token_a, seance["ag"]), "Martin Claire")
    assert _saisir(client, token_a, martin["id"], mode="lre", date_envoi=AUJOURDHUI.isoformat()).status_code == 200
    r = _saisir(client, token_a, martin["id"], mode="lrar", date_envoi=AUJOURDHUI.isoformat())
    assert r.status_code == 422
    assert "envoyée" in r.json()["detail"]
    # Correction volontaire en deux temps : effacer la date d'envoi, puis changer le mode.
    assert _saisir(client, token_a, martin["id"], mode="lre").status_code == 200
    assert _saisir(client, token_a, martin["id"], mode="lrar").status_code == 200


def test_envoi_lre_anterieur_a_la_demande_reste_saisissable(client, token_a, seance):
    """Envoyée par LRE avant que le copropriétaire demande la voie postale : on peut encore saisir
    la première présentation, sans changer le mode."""
    bernard = _item(_preparer(client, token_a, seance["ag"]), "Bernard Luc")
    envoi = AUJOURDHUI - timedelta(days=2)
    assert _saisir(client, token_a, bernard["id"], mode="lre", date_envoi=envoi.isoformat()).status_code == 200
    _voie_postale(client, token_a, seance["bernard"])
    r = _saisir(client, token_a, bernard["id"], mode="lre", date_envoi=envoi.isoformat(),
                date_presentation=AUJOURDHUI.isoformat())
    assert r.status_code == 200, r.text

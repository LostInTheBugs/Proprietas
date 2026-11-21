"""Réunion en ligne : lien de visioconférence de l'AG (demande de Fred, 21/11/2026).

- un lien https sur l'AG (Teams, Zoom, Jitsi…), ou un lien Jitsi (meet.jit.si) créé en un clic, difficile à deviner ;
- le lien figure dans l'e-mail d'information ; le copropriétaire peut répondre « en visioconférence » ;
- participer par visioconférence vaut présence (loi n° 65-557, art. 17-1 A) : feuille de présence, totaux, PV ;
  un formulaire de vote par correspondance est alors écarté ;
- résolution type : moyens de participation par visioconférence (décret n° 67-223, art. 13-1).
"""
import io
from datetime import date

from pypdf import PdfReader

from tests.conftest import auth
from tests.test_ag_presences import _ag, _immeuble, _repondre, envois  # noqa: F401 (fixture)


def _texte(contenu):
    return " ".join(" ".join(p.extract_text() for p in PdfReader(io.BytesIO(contenu)).pages).split())


def test_lien_de_visio(client, db, copro_a, syndic_a, token_a, token_b):
    marie, = _immeuble(db, copro_a, syndic_a, [500])
    ag_id = _ag(client, token_a)
    ag = client.get("/api/ag", headers=auth(token_a)).json()[0]
    assert ag["lien_visio"] == ""
    corps = {"date": ag["date"], "heure": ag["heure"]}
    for mauvais in ("http://visio.exemple.fr/salle", "javascript:alert(1)", "https://" + "a" * 600):
        r = client.put(f"/api/ag/{ag_id}", json={**corps, "lien_visio": mauvais}, headers=auth(token_a))
        assert r.status_code == 422, mauvais
    r = client.put(f"/api/ag/{ag_id}", json={**corps, "lien_visio": " https://teams.exemple.fr/salle/42 "},
                   headers=auth(token_a))
    assert r.status_code == 200 and r.json()["lien_visio"] == "https://teams.exemple.fr/salle/42"
    # Lien Jitsi créé par l'application : salle propre à l'AG, difficile à deviner.
    r = client.post(f"/api/ag/{ag_id}/lien-jitsi", headers=auth(token_a))
    assert r.status_code == 200, r.text
    lien = r.json()["lien_visio"]
    assert lien.startswith("https://meet.jit.si/Proprietas-") and len(lien.rsplit("-", 1)[1]) >= 20
    assert client.post(f"/api/ag/{ag_id}/lien-jitsi", headers=auth(token_a)).json()["lien_visio"] != lien
    from app.core.security import create_access_token
    t_marie = create_access_token(marie.id, copro_a.id)
    assert client.get("/api/ag", headers=auth(t_marie)).json()[0]["lien_visio"].startswith("https://meet.jit.si/")
    assert client.post(f"/api/ag/{ag_id}/lien-jitsi", headers=auth(t_marie)).status_code == 403
    assert client.post(f"/api/ag/{ag_id}/lien-jitsi", headers=auth(token_b)).status_code == 404


def test_presence_en_visio(client, db, copro_a, syndic_a, token_a, envois):
    marie, paul = _immeuble(db, copro_a, syndic_a, [450, 450])
    ag_id = _ag(client, token_a)
    # Sans lien : pas de réponse « visio ».
    assert _repondre(client, ag_id, marie, copro_a, reponse="visio").status_code == 422
    client.post(f"/api/ag/{ag_id}/lien-jitsi", headers=auth(token_a))
    lien = client.get("/api/ag", headers=auth(token_a)).json()[0]["lien_visio"]
    # E-mail d'information : le lien de la réunion ; page de réponse : le choix « visioconférence ».
    client.post(f"/api/ag/{ag_id}/invitations", headers=auth(token_a))
    corps = next(c for d, c in envois if d == "c1@exemple.fr")
    assert lien in corps and "visioconférence" in corps
    confirmation = next(l for l in corps.splitlines() if "/api/ag/confirmation/" in l).removeprefix("https://copro.exemple.fr")
    assert 'value="visio"' in client.get(confirmation).text
    # Marie vote par correspondance puis répond « en visio » : son formulaire est écarté.
    r1 = client.post(f"/api/ag/{ag_id}/resolutions", json={"libelle": "Ravalement"}, headers=auth(token_a)).json()["id"]
    client.put(f"/api/ag/{ag_id}/correspondance/{marie.id}", json={"recu_le": str(date.today()), "votes": {r1: "pour"}},
               headers=auth(token_a))
    assert _repondre(client, ag_id, marie, copro_a, reponse="visio").status_code == 200
    assert _repondre(client, ag_id, paul, copro_a, reponse="present").status_code == 200
    p = client.get(f"/api/ag/{ag_id}/presences", headers=auth(token_a)).json()
    assert p["totaux"]["presents"] == 2 and p["totaux"]["visio"] == 1
    assert p["totaux"]["voix_presentes_ou_representees"] == 900.0          # 450 + 450 sur 1 000 (le syndic a 100)
    e = client.get(f"/api/ag/{ag_id}/correspondance", headers=auth(token_a)).json()
    assert [f["ecarte"] for f in e["formulaires"]] == [True]
    t = _texte(client.get(f"/api/ag/{ag_id}/feuille-presence", headers=auth(token_a)).content)
    assert "Présent(e) en visioconférence" in t
    t = _texte(client.get(f"/api/ag/{ag_id}/pv", headers=auth(token_a)).content)
    assert "2 copropriétaire(s) présent(s), dont 1 par visioconférence," in t


def test_resolution_type_visio(client, db, copro_a, syndic_a, token_a):
    modele = {x["code"]: x for x in client.get(f"/api/ag/modele-annuelle?jour={date.today()}",
                                                headers=auth(token_a)).json()}
    v = modele["visio"]
    assert v["coche"] is False and v["majorite"] == "art24" and "13-1" in v["texte"]

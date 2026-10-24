"""Surface des lots : la seule colonne Float restante (lots.surface_m2).

- En entrée : NaN, Infinity, valeurs négatives ou absurdes refusées (422) ; arrondi à 0,01 m².
  Avant, NaN/Infinity étaient acceptés et stockés tels quels (PostgreSQL les accepte).
- En lecture : une valeur non finie déjà en base ne doit pas faire planter la liste des
  lots (« Out of range float values are not JSON compliant » → 500) : elle sort en null.
"""
import json

import pytest

from app.models.lot import Lot
from tests.conftest import auth


def _post(client, token_a, surface, raw=False):
    corps = {"numero": "A1", "tantiemes": 100, "surface_m2": surface}
    if raw:   # NaN / Infinity ne sont pas du JSON standard
        return client.post("/api/lots", content=json.dumps(corps),
                           headers={**auth(token_a), "Content-Type": "application/json"})
    return client.post("/api/lots", json=corps, headers=auth(token_a))


@pytest.mark.parametrize("valeur", [float("nan"), float("inf"), float("-inf")])
def test_surface_non_finie_refusee(client, token_a, valeur):
    assert _post(client, token_a, valeur, raw=True).status_code == 422


@pytest.mark.parametrize("valeur", [-5, 1e6, True, "grand"])
def test_surface_hors_limites_ou_invalide_refusee(client, token_a, valeur):
    assert _post(client, token_a, valeur).status_code == 422


def test_surface_arrondie_et_null_accepte(client, token_a):
    r = _post(client, token_a, 48.456)
    assert r.status_code == 200, r.text
    assert r.json()["surface_m2"] == 48.46
    r = client.post("/api/lots", json={"numero": "A2", "tantiemes": 100, "surface_m2": None},
                    headers=auth(token_a))
    assert r.status_code == 200 and r.json()["surface_m2"] is None


def test_valeur_non_finie_deja_en_base_lue_comme_null(client, token_a, db, copro_a):
    db.add(Lot(copropriete_id=copro_a.id, numero="Z9", tantiemes=10, surface_m2=float("inf")))
    db.commit()
    r = client.get("/api/lots", headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert [l["surface_m2"] for l in r.json() if l["numero"] == "Z9"] == [None]

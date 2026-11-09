"""Lots non séparables : un lot annexe (cave, garage) rattaché à un lot principal.

Règles retenues :
- rattachement saisi sur le lot annexe (`lot_principal_id`) : lot principal de la même copropriété,
  qui n'est pas lui-même une annexe ; un lot qui a des annexes ne peut pas devenir une annexe ;
- l'annexe a toujours le propriétaire du lot principal : un autre propriétaire est refusé, et changer
  le propriétaire du lot principal change celui de ses annexes ;
- un lot sans rattachement reste séparé (rien ne change) ;
- l'ensemble se suit comme une seule unité : décompte commun (tous les appels et tous les paiements
  des lots de l'ensemble), une ligne et un dossier de recouvrement, une relance, une ligne au tableau
  de bord, une proposition de paiement, une quittance ; le détail reste visible lot par lot.
"""
from datetime import date

from app.models.appel import AppelFonds, AppelLot
from app.models.exercice import Exercice
from app.models.lot import Lot
from app.models.mouvement import Mouvement
from app.models.recouvrement import ActeRecouvrement
from tests.conftest import _make_membre, auth

Y = date.today().year


def _copro(db, copro):
    """Martin : lot 1 (appartement) + lot 12 (cave) + lot 25 (garage). Petit : lot 2 (appartement).
    Appel T1 (15/01) : lot 1 = 300, lot 12 = 30, lot 25 = 20, lot 2 = 200. Martin paie 320 sur le lot 1."""
    martin = _make_membre(db, "martin@test.fr", copro)
    petit = _make_membre(db, "petit@test.fr", copro)
    lots = {}
    for numero, designation, typ, tant, proprio in (("1", "Appartement T3", "appartement", 500, martin),
                                                    ("12", "Cave", "cave", 20, martin),
                                                    ("25", "Garage", "parking", 30, martin),
                                                    ("2", "Appartement T2", "appartement", 450, petit)):
        lots[numero] = Lot(copropriete_id=copro.id, numero=numero, designation=designation, type=typ,
                           tantiemes=tant, proprietaire_id=proprio.id)
        db.add(lots[numero])
    ex = Exercice(copropriete_id=copro.id, annee=Y, cloture=False)
    db.add(ex)
    db.flush()
    a = AppelFonds(exercice_id=ex.id, libelle="Provisions T1", date_emission=date(Y, 1, 5),
                   date_echeance=date(Y, 1, 15), montant_total=550)
    db.add(a)
    db.flush()
    for numero, montant in (("1", 300), ("12", 30), ("25", 20), ("2", 200)):
        db.add(AppelLot(appel_id=a.id, lot_id=lots[numero].id, montant_charges=montant, montant_fonds_travaux=0))
    db.add(Mouvement(copropriete_id=copro.id, exercice_id=ex.id, date=date(Y, 1, 20), libelle="Virement",
                     type="encaissement", categorie="charges", montant=320, lot_id=lots["1"].id))
    db.commit()
    return martin, petit, lots, ex


def _corps(lot, **champs):
    base = {"numero": lot.numero, "designation": lot.designation, "type": lot.type, "tantiemes": lot.tantiemes,
            "proprietaire_id": lot.proprietaire_id, "statut_occupation": "", "notes": "", "lot_principal_id": None}
    return {**base, **champs}


def _rattacher(client, token, lot, principal):
    return client.put(f"/api/lots/{lot.id}", json=_corps(lot, lot_principal_id=principal.id), headers=auth(token))


def _ensemble(client, token, lots):
    for n in ("12", "25"):
        r = _rattacher(client, token, lots[n], lots["1"])
        assert r.status_code == 200, r.text


# ---------- Rattachement ----------
def test_rattacher_une_cave(client, db, copro_a, syndic_a, token_a):
    _, _, lots, _ = _copro(db, copro_a)
    r = _rattacher(client, token_a, lots["12"], lots["1"])
    assert r.status_code == 200, r.text
    assert r.json()["lot_principal_id"] == lots["1"].id
    # Détacher : lot_principal_id = null.
    r = client.put(f"/api/lots/{lots['12'].id}", json=_corps(lots["12"]), headers=auth(token_a))
    assert r.json()["lot_principal_id"] is None


def test_rattachements_refuses(client, db, copro_a, copro_b, syndic_a, token_a):
    _, petit, lots, _ = _copro(db, copro_a)
    autre = Lot(copropriete_id=copro_b.id, numero="9", tantiemes=10)
    db.add(autre)
    db.commit()
    # À lui-même, à un lot d'une autre copropriété, à un lot d'un autre propriétaire.
    assert _rattacher(client, token_a, lots["12"], lots["12"]).status_code == 422
    assert _rattacher(client, token_a, lots["12"], autre).status_code == 422
    assert _rattacher(client, token_a, lots["12"], lots["2"]).status_code == 422
    # Pas de chaîne : une annexe ne peut pas être principale, un principal ne devient pas annexe.
    assert _rattacher(client, token_a, lots["12"], lots["1"]).status_code == 200
    assert _rattacher(client, token_a, lots["25"], lots["12"]).status_code == 422
    assert _rattacher(client, token_a, lots["1"], lots["25"]).status_code == 422


def test_proprietaire_de_l_annexe_suit_le_principal(client, db, copro_a, syndic_a, token_a):
    martin, petit, lots, _ = _copro(db, copro_a)
    _ensemble(client, token_a, lots)
    # Une annexe ne peut pas avoir un autre propriétaire que son lot principal.
    r = client.put(f"/api/lots/{lots['12'].id}",
                   json=_corps(lots["12"], proprietaire_id=petit.id, lot_principal_id=lots["1"].id),
                   headers=auth(token_a))
    assert r.status_code == 422
    # Vente de l'ensemble : changer le propriétaire du lot principal change celui des annexes.
    r = client.put(f"/api/lots/{lots['1'].id}", json=_corps(lots["1"], proprietaire_id=petit.id), headers=auth(token_a))
    assert r.status_code == 200, r.text
    db.expire_all()
    assert {db.get(Lot, lots[n].id).proprietaire_id for n in ("1", "12", "25")} == {petit.id}


def test_supprimer_le_lot_principal_detache_les_annexes(client, db, copro_a, syndic_a, token_a):
    principal = Lot(copropriete_id=copro_a.id, numero="40", tantiemes=1)
    db.add(principal)
    db.flush()
    annexe = Lot(copropriete_id=copro_a.id, numero="41", tantiemes=1, lot_principal_id=principal.id)
    db.add(annexe)
    db.commit()
    assert client.delete(f"/api/lots/{principal.id}", headers=auth(token_a)).status_code == 200
    db.expire_all()
    assert db.get(Lot, annexe.id).lot_principal_id is None


# ---------- Recouvrement ----------
def test_decompte_commun_a_l_ensemble(client, db, copro_a, syndic_a, token_a):
    _, _, lots, _ = _copro(db, copro_a)
    # Sans rattachement : le lot 1 a trop payé, la cave et le garage restent dus.
    avant = {l["lot_numero"]: l["solde"] for l in client.get("/api/recouvrement", headers=auth(token_a)).json()}
    assert avant == {"1": 0, "12": 30, "2": 200, "25": 20}
    _ensemble(client, token_a, lots)
    liste = client.get("/api/recouvrement", headers=auth(token_a)).json()
    lignes = {l["lot_numero"]: l for l in liste}
    # Une seule ligne pour l'ensemble (lot principal), annexes indiquées ; 350 appelés − 320 payés = 30.
    assert set(lignes) == {"1", "2"}
    assert lignes["1"]["solde"] == 30
    assert [a["numero"] for a in lignes["1"]["annexes"]] == ["12", "25"]
    d = client.get(f"/api/recouvrement/lot/{lots['1'].id}", headers=auth(token_a)).json()
    assert len(d["decompte"]) == 3 and all("— lot " in l["libelle"] for l in d["decompte"])
    assert d["solde"] == 30


def test_dossier_d_une_annexe_renvoie_l_ensemble(client, db, copro_a, syndic_a, token_a):
    _, _, lots, _ = _copro(db, copro_a)
    _ensemble(client, token_a, lots)
    d = client.get(f"/api/recouvrement/lot/{lots['12'].id}", headers=auth(token_a)).json()
    assert d["lot_id"] == lots["1"].id and d["solde"] == 30
    r = client.post(f"/api/recouvrement/lot/{lots['25'].id}/acte",
                    json={"type": "note", "libelle": "Appel téléphonique"}, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert db.query(ActeRecouvrement).one().lot_id == lots["1"].id


def test_relance_par_ensemble(client, db, copro_a, syndic_a, token_a):
    _, _, lots, _ = _copro(db, copro_a)
    _ensemble(client, token_a, lots)
    etat = {e["lot_numero"]: e for e in client.get("/api/relances", headers=auth(token_a)).json()}
    assert set(etat) == {"1", "2"}
    assert etat["1"]["solde"] == 30 and etat["1"]["encaisse"] == 320 and etat["1"]["appels_charges"] == 350


# ---------- Tableau de bord, paiement, quittances ----------
def test_tableau_de_bord_par_ensemble(client, db, copro_a, syndic_a, token_a):
    _, _, lots, _ = _copro(db, copro_a)
    _ensemble(client, token_a, lots)
    recap = client.get("/api/recap", headers=auth(token_a)).json()
    ens = {e["lot"]["numero"]: e for e in recap["ensembles"]}
    assert set(ens) == {"1", "2"}
    assert [a["numero"] for a in ens["1"]["annexes"]] == ["12", "25"]
    assert (ens["1"]["appels_charges"], ens["1"]["encaisse"], ens["1"]["solde"]) == (350, 320, 30)
    # Le détail par lot reste disponible.
    assert len(recap["lots"]) == 4


def test_paiement_propose_par_ensemble(client, db, copro_a, syndic_a, token_a):
    martin, _, lots, _ = _copro(db, copro_a)
    _ensemble(client, token_a, lots)
    r = client.get(f"/api/paiements/repartition?proprietaire_id={martin.id}&montant=30", headers=auth(token_a))
    assert r.status_code == 200, r.text
    [l] = r.json()["lots"]
    assert l["lot_id"] == lots["1"].id and l["du"] == 30 and l["propose"] == 30


def test_quittance_par_ensemble(client, db, copro_a, syndic_a, token_a):
    from app.models.copropriete import Copropriete
    from app.services.quittances import generer_quittances_pdf

    _, _, lots, ex = _copro(db, copro_a)
    _ensemble(client, token_a, lots)
    db.expire_all()
    buf = generer_quittances_pdf(db.get(Copropriete, copro_a.id), db.get(Exercice, ex.id), db)
    from pypdf import PdfReader
    texte = "\n".join(p.extract_text() for p in PdfReader(buf).pages)
    # Deux quittances : l'ensemble de Martin (lots 1, 12, 25) et le lot 2.
    assert texte.count("QUITTANCE D'APPELS DE FONDS") == 2
    assert "Lot 1" in texte and "Lot 12" in texte and "Lot 25" in texte
    # L'ensemble : 350 appelés, 320 payés, 30 restant dus.
    assert "30,00" in texte and "320,00" in texte and "350,00" in texte


def test_modifier_sans_le_champ_garde_le_rattachement(client, db, copro_a, syndic_a, token_a):
    _, _, lots, _ = _copro(db, copro_a)
    _ensemble(client, token_a, lots)
    corps = _corps(lots["12"], designation="Cave n° 12")
    del corps["lot_principal_id"]
    r = client.put(f"/api/lots/{lots['12'].id}", json=corps, headers=auth(token_a))
    assert r.status_code == 200, r.text
    assert r.json()["lot_principal_id"] == lots["1"].id and r.json()["designation"] == "Cave n° 12"

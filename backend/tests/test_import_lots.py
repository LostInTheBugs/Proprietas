"""Import des lots depuis un tableur : CSV, Excel (.xlsx), LibreOffice (.ods) (demande de Fred, 20/11/2026).

- en-tête libre (ordre, casse, accents) : numero et tantiemes requis ; designation, type, surface, proprietaire
  (e-mail d'un compte) ; « clé : Nom » pour les millièmes d'une clé de répartition ;
- lot existant (même numéro) mis à jour, nouveau créé ; « Vérifier » (simulation) n'écrit rien ;
- refus en bloc à la moindre erreur, chaque erreur cite sa ligne.
"""
import io
import zipfile

from openpyxl import Workbook

from app.models.cle import CleLot, CleRepartition
from app.models.lot import Lot
from tests.conftest import _make_membre, auth

CSV = ("Numéro;Désignation;Type;Tantièmes;Surface;Propriétaire;clé : Bâtiment A\n"
       "1;Appartement T3;appartement;300;68,5;marie@exemple.fr;500\n"
       "2;Appartement T2;Appartement;300;45;;500\n"
       "3;Cave;cave;400;;;\n")


def _envoyer(client, token, nom, contenu, simuler):
    return client.post("/api/lots/import", files={"fichier": (nom, contenu, "application/octet-stream")},
                       data={"simuler": "true" if simuler else "false"}, headers=auth(token))


def _ods(lignes) -> bytes:
    """Petit .ods (content.xml) : une feuille, des cellules texte ou nombre, une cellule répétée."""
    def cellule(v):
        if isinstance(v, (int, float)):
            return (f'<table:table-cell office:value-type="float" office:value="{v}"><text:p>{v}</text:p>'
                    '</table:table-cell>')
        if v == "":
            return '<table:table-cell table:number-columns-repeated="2"/>'
        return f'<table:table-cell office:value-type="string"><text:p>{v}</text:p></table:table-cell>'
    rows = "".join("<table:table-row>" + "".join(cellule(v) for v in l) + "</table:table-row>" for l in lignes)
    contenu = ('<?xml version="1.0" encoding="UTF-8"?><office:document-content '
               'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
               'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
               'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:spreadsheet>'
               f'<table:table table:name="Lots">{rows}</table:table></office:spreadsheet></office:body>'
               '</office:document-content>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        z.writestr("content.xml", contenu)
    return buf.getvalue()


def test_csv_verifier_puis_importer(client, db, copro_a, syndic_a, token_a):
    marie = _make_membre(db, "marie@exemple.fr", copro_a)
    db.add(Lot(copropriete_id=copro_a.id, numero="2", tantiemes=1, designation="Ancien"))
    db.commit()
    r = _envoyer(client, token_a, "lots.csv", CSV.encode(), True)
    assert r.status_code == 200, r.text
    assert r.json() == {"erreurs": [], "crees": ["1", "3"], "modifies": ["2"], "cles_creees": ["Bâtiment A"],
                        "cles_modifiees": [], "simulation": True}
    assert db.query(Lot).count() == 1                                    # simulation : rien d'écrit
    r = _envoyer(client, token_a, "lots.csv", CSV.encode(), False)
    assert r.status_code == 200, r.text
    db.expire_all()
    lots = {l.numero: l for l in db.query(Lot).filter(Lot.copropriete_id == copro_a.id)}
    assert (lots["1"].tantiemes, lots["1"].surface_m2, lots["1"].proprietaire_id) == (300, 68.5, marie.id)
    assert (lots["2"].tantiemes, lots["2"].designation, lots["2"].type) == (300, "Appartement T2", "appartement")
    assert lots["3"].type == "cave"
    cle = db.query(CleRepartition).filter(CleRepartition.nom == "Bâtiment A").one()
    assert {(cl.lot_id, cl.tantiemes) for cl in db.query(CleLot).filter(CleLot.cle_id == cle.id)} == \
        {(lots["1"].id, 500), (lots["2"].id, 500)}


def test_xlsx(client, db, copro_a, syndic_a, token_a):
    wb = Workbook()
    ws = wb.active
    ws.append(["numero", "tantiemes", "designation"])
    ws.append([1, 600, "Appartement"])
    ws.append(["2B", 400.0, None])
    buf = io.BytesIO()
    wb.save(buf)
    r = _envoyer(client, token_a, "lots.xlsx", buf.getvalue(), False)
    assert r.status_code == 200, r.text
    assert sorted((l.numero, l.tantiemes) for l in db.query(Lot)) == [("1", 600), ("2B", 400)]


def test_ods(client, db, copro_a, syndic_a, token_a):
    contenu = _ods([["Lot", "Millièmes", "", "Type"], [1, 700, "", "appartement"], ["2", 300, "", "parking"]])
    r = _envoyer(client, token_a, "lots.ods", contenu, False)
    assert r.status_code == 200, r.text
    assert sorted((l.numero, l.tantiemes, l.type) for l in db.query(Lot)) == [("1", 700, "appartement"),
                                                                             ("2", 300, "parking")]


def test_erreurs_par_ligne_et_refus_en_bloc(client, db, copro_a, syndic_a, token_a):
    mauvais = ("numero;tantiemes;type;proprietaire\n"
               "1;300;appartement;\n"
               "2;abc;;\n"
               "1;100;;\n"
               "4;100;chateau;inconnu@exemple.fr\n")
    r = _envoyer(client, token_a, "lots.csv", mauvais.encode(), True)
    erreurs = r.json()["erreurs"]
    assert any(e.startswith("Ligne 3 : tantièmes « abc »") for e in erreurs)
    assert any(e.startswith("Ligne 4 : lot 1 en double") for e in erreurs)
    assert any(e.startswith("Ligne 5 : type « chateau »") for e in erreurs)
    assert any("Ligne 5 : aucun compte « inconnu@exemple.fr »" in e for e in erreurs)
    r = _envoyer(client, token_a, "lots.csv", mauvais.encode(), False)
    assert r.status_code == 422 and "rien n'a été écrit" in r.json()["detail"]
    assert db.query(Lot).count() == 0
    # En-tête : colonne inconnue, colonne requise absente.
    r = _envoyer(client, token_a, "lots.csv", "numero;milliardaire\n1;2\n".encode(), True)
    assert any("colonne « milliardaire » inconnue" in e for e in r.json()["erreurs"])
    assert any("colonne « tantiemes » manquante" in e for e in r.json()["erreurs"])


def test_formats_et_droits(client, db, copro_a, syndic_a, token_a):
    assert _envoyer(client, token_a, "lots.pdf", b"%PDF", True).status_code == 422
    assert _envoyer(client, token_a, "lots.xlsx", b"pas un classeur", True).status_code == 422
    membre = _make_membre(db, "m@exemple.fr", copro_a)
    from app.core.security import create_access_token
    assert _envoyer(client, create_access_token(membre.id, copro_a.id), "lots.csv", CSV.encode(), True).status_code == 403
    modele = client.get("/api/lots/import/modele.csv", headers=auth(token_a))
    assert modele.status_code == 200 and "clé : Bâtiment A" in modele.content.decode("utf-8-sig")
    # Le modèle s'importe tel quel (sans les propriétaires, qui n'existent pas ici).
    texte = "\n".join(";".join(c if i != 5 else "" for i, c in enumerate(l.split(";")))
                      for l in modele.content.decode("utf-8-sig").splitlines())
    assert _envoyer(client, token_a, "modele.csv", texte.encode(), True).json()["erreurs"] == []

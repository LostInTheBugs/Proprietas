"""Stockage des documents : dossier local ou bucket compatible S3 (issue #11).

Le S3 est simulé par moto (aucun réseau) : ce sont les vrais appels boto3 qui sont testés.
"""
import io
import os
from datetime import date

import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.cli import migrer_stockage as mig
from app.core import config as config_mod
from app.core import stockage as stk
from app.models.document import Document
from app.routes import documents as docs
from tests.conftest import auth

BUCKET = "proprietas-test"


@pytest.fixture()
def s3(monkeypatch):
    """Bucket S3 simulé, client sans réseau ni vrais identifiants."""
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        client = stk.client_s3(region="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield stk.StockageS3(client, BUCKET, "documents/")


def _cles(s3):
    r = s3.client.list_objects_v2(Bucket=BUCKET)
    return sorted(o["Key"] for o in r.get("Contents", []))


# ---------- noms stockés ----------
@pytest.mark.parametrize("nom", ["", ".", "..", "../x.pdf", "a/b.pdf", "a\\b.pdf", ".cache", "x\x00.pdf"])
def test_nom_invalide_refuse(nom, tmp_path, s3):
    with pytest.raises(stk.NomInvalide):
        stk.StockageLocal(str(tmp_path)).chemin(nom)
    with pytest.raises(stk.NomInvalide):
        s3.cle(nom)


def test_noms_de_l_application_acceptes():
    assert stk.valider_nom("3f2a9c.pdf") == "3f2a9c.pdf"
    assert stk.valider_nom("demo_autre_Règlement_de_copropr.pdf")   # jeu de démo (accent)


# ---------- local ----------
def test_local_cycle_complet(tmp_path):
    st = stk.StockageLocal(str(tmp_path / "up"))
    contenu = os.urandom(2_500_000)
    st.enregistrer("a.pdf", io.BytesIO(contenu))
    assert st.existe("a.pdf") and st.taille("a.pdf") == len(contenu)
    assert b"".join(st.lire_par_blocs("a.pdf")) == contenu
    assert list(st.lister()) == ["a.pdf"]
    st.supprimer("a.pdf")
    st.supprimer("a.pdf")                                   # idempotent
    assert not st.existe("a.pdf") and st.taille("a.pdf") is None


def test_local_erreur_pendant_l_ecriture_ne_laisse_rien(tmp_path):
    class Casse(io.BytesIO):
        def read(self, n=-1):
            if self.tell() >= 1024 * 1024:
                raise OSError("disque plein")
            return super().read(n)
    st = stk.StockageLocal(str(tmp_path))
    with pytest.raises(OSError):
        st.enregistrer("b.pdf", Casse(b"x" * 3_000_000))
    assert os.listdir(tmp_path) == []                       # ni b.pdf ni b.pdf.part


def test_local_verifier_ecriture(tmp_path):
    stk.StockageLocal(str(tmp_path / "neuf")).verifier_ecriture()     # crée le dossier
    assert os.listdir(tmp_path / "neuf") == []                        # sonde supprimée
    fichier = tmp_path / "pas-un-dossier"
    fichier.write_bytes(b"")
    with pytest.raises(stk.StockageIndisponible, match="COPRO_UPLOAD_DIR"):
        stk.StockageLocal(str(fichier)).verifier_ecriture()


# ---------- S3 ----------
def test_s3_cycle_complet_sous_le_prefixe(s3):
    contenu = os.urandom(9 * 1024 * 1024)                   # > 8 Mo : envoi multipart
    s3.enregistrer("c.pdf", io.BytesIO(contenu))
    assert _cles(s3) == ["documents/c.pdf"]
    assert s3.existe("c.pdf") and s3.taille("c.pdf") == len(contenu)
    blocs = list(s3.lire_par_blocs("c.pdf"))
    assert b"".join(blocs) == contenu and all(len(b) <= stk.BLOC for b in blocs)
    assert list(s3.lister()) == ["c.pdf"]
    s3.supprimer("c.pdf")
    s3.supprimer("c.pdf")                                   # idempotent
    assert _cles(s3) == [] and s3.taille("c.pdf") is None


def test_s3_verifier_ecriture(s3):
    s3.verifier_ecriture()
    assert _cles(s3) == []                                  # sonde supprimée
    absent = stk.StockageS3(s3.client, "bucket-inexistant", "documents/")
    with pytest.raises(stk.StockageIndisponible, match="bucket-inexistant"):
        absent.verifier_ecriture()
    with pytest.raises(stk.StockageIndisponible):
        absent.enregistrer("d.pdf", io.BytesIO(b"x"))


# ---------- configuration ----------
@pytest.mark.parametrize("env,message", [
    ({"COPRO_STOCKAGE": "ftp"}, "COPRO_STOCKAGE invalide"),
    ({"COPRO_STOCKAGE": "s3"}, "COPRO_S3_BUCKET"),
])
def test_configuration_refusee(monkeypatch, env, message):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    config_mod.get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match=message):
            config_mod.get_settings()
    finally:
        config_mod.get_settings.cache_clear()


def test_stockage_depuis_les_reglages(monkeypatch, s3):
    reglages = docs.settings.model_copy(update={"stockage": "s3", "s3_bucket": BUCKET,
                                                "s3_region": "us-east-1"})
    st = stk.stockage_depuis(reglages)
    assert isinstance(st, stk.StockageS3) and st.bucket == BUCKET and st.prefixe == "documents/"
    assert stk.stockage_depuis(reglages) is st                       # client créé une fois
    assert isinstance(stk.stockage_depuis(docs.settings), stk.StockageLocal)


def test_demarrage_refuse_si_stockage_inutilisable(monkeypatch):
    def refus(self):
        raise stk.StockageIndisponible("bucket introuvable")
    monkeypatch.setattr(stk.StockageLocal, "verifier_ecriture", refus)
    from app.main import app
    with pytest.raises(stk.StockageIndisponible, match="bucket introuvable"):
        with TestClient(app):
            pass


# ---------- routes en mode S3 ----------
@pytest.fixture()
def route_s3(monkeypatch, s3):
    monkeypatch.setattr(docs, "_stockage", lambda: s3)
    return s3


def _envoyer(client, token, contenu, nom="doc.pdf", libelle="Assurance 2026"):
    return client.post("/api/documents", data={"categorie": "assurance", "libelle": libelle},
                       files={"fichier": (nom, contenu, "application/pdf")}, headers=auth(token))


def _locaux():
    d = docs.settings.upload_dir
    return set(os.listdir(d)) if os.path.isdir(d) else set()


def test_route_upload_telechargement_suppression_s3(client, token_a, route_s3):
    avant = _locaux()
    contenu = os.urandom(1_500_000)
    r = _envoyer(client, token_a, contenu, libelle="Contrat été")
    assert r.status_code == 200, r.text
    doc = r.json()
    assert _cles(route_s3) == [f"documents/{doc['fichier']}"]
    assert _locaux() == avant                               # rien dans le dossier local
    r = client.get(f"/api/documents/{doc['id']}/download", headers=auth(token_a))
    assert r.status_code == 200 and r.content == contenu
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-length"] == str(len(contenu))
    assert r.headers["content-disposition"] == "attachment; filename*=utf-8''Contrat%20%C3%A9t%C3%A9"
    r = client.delete(f"/api/documents/{doc['id']}", headers=auth(token_a))
    assert r.status_code == 200
    assert _cles(route_s3) == []


def test_route_trop_volumineux_rien_dans_le_bucket(client, token_a, route_s3, monkeypatch):
    monkeypatch.setattr(docs.settings, "upload_max_mb", 1.5)
    r = _envoyer(client, token_a, b"x" * 2_000_000)
    assert r.status_code == 413
    assert _cles(route_s3) == []


def test_route_isolation_et_objet_absent(client, token_a, token_b, route_s3):
    doc = _envoyer(client, token_a, b"%PDF-1.4 a").json()
    assert client.get(f"/api/documents/{doc['id']}/download", headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/documents/{doc['id']}", headers=auth(token_b)).status_code == 404
    route_s3.supprimer(doc["fichier"])                      # objet perdu côté bucket
    r = client.get(f"/api/documents/{doc['id']}/download", headers=auth(token_a))
    assert r.status_code == 404 and r.json()["detail"] == "Fichier manquant sur le serveur"


def test_route_nom_forge_404_en_s3(client, db, copro_a, token_a, route_s3):
    doc = Document(copropriete_id=copro_a.id, categorie="autre", libelle="Évasion",
                   fichier="../../etc/passwd", date_ajout=date.today())
    db.add(doc)
    db.commit()
    assert client.get(f"/api/documents/{doc.id}/download", headers=auth(token_a)).status_code == 404


def test_route_bucket_indisponible_503(client, token_a, route_s3, monkeypatch):
    monkeypatch.setattr(route_s3, "bucket", "bucket-inexistant")
    r = _envoyer(client, token_a, b"%PDF-1.4 a")
    assert r.status_code == 503
    assert "indisponible" in r.json()["detail"]
    assert "bucket-inexistant" not in r.json()["detail"]   # le détail technique reste dans les logs


# ---------- migration des documents existants ----------
def test_migration_local_vers_s3(tmp_path, s3):
    local = stk.StockageLocal(str(tmp_path))
    local.enregistrer("un.pdf", io.BytesIO(b"1" * 10))
    local.enregistrer("deux.pdf", io.BytesIO(os.urandom(3_000_000)))
    local.enregistrer("orphelin.pdf", io.BytesIO(b"pas en base"))
    noms = ["absent.pdf", "deux.pdf", "un.pdf"]             # tels que lus en base

    b = mig.copier(noms, local, s3, simulation=True)
    assert (b.copies, b.deja_presents, b.manquants, b.erreurs) == (2, 0, ["absent.pdf"], [])
    assert _cles(s3) == []                                  # simulation : rien d'écrit

    b = mig.copier(noms, local, s3)
    assert (b.copies, b.deja_presents, b.manquants, b.erreurs) == (2, 0, ["absent.pdf"], [])
    assert _cles(s3) == ["documents/deux.pdf", "documents/un.pdf"]   # orphelin non copié
    assert b"".join(s3.lire_par_blocs("deux.pdf")) == b"".join(local.lire_par_blocs("deux.pdf"))
    assert sorted(local.lister()) == ["deux.pdf", "orphelin.pdf", "un.pdf"]   # source intacte

    b = mig.copier(noms, local, s3)                         # relance : rien à refaire
    assert (b.copies, b.deja_presents) == (0, 2)
    assert b.ligne() == "Bilan : 0 copié(s), 2 déjà présent(s), 1 manquant(s) à la source, 0 erreur(s)"


def test_migration_recopie_un_objet_tronque_et_signale_un_nom_forge(tmp_path, s3):
    local = stk.StockageLocal(str(tmp_path))
    local.enregistrer("un.pdf", io.BytesIO(b"1" * 10))
    s3.enregistrer("un.pdf", io.BytesIO(b"1" * 4))          # copie précédente interrompue
    b = mig.copier(["un.pdf", "../x.pdf"], local, s3)
    assert b.copies == 1 and s3.taille("un.pdf") == 10
    assert len(b.erreurs) == 1 and "nom refusé" in b.erreurs[0]


def test_migration_s3_vers_local(tmp_path, s3):
    s3.enregistrer("un.pdf", io.BytesIO(b"contenu"))
    local = stk.StockageLocal(str(tmp_path))
    b = mig.copier(["un.pdf"], s3, local)
    assert b.copies == 1 and b"".join(local.lire_par_blocs("un.pdf")) == b"contenu"


def test_commande_migration_sans_bucket(monkeypatch, capsys):
    monkeypatch.setattr(config_mod, "get_settings",
                        lambda: docs.settings.model_copy(update={"s3_bucket": ""}))
    assert mig.main(["--simulation"]) == 2
    assert "COPRO_S3_BUCKET" in capsys.readouterr().err

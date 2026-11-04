"""Stockage des fichiers déposés (documents) : dossier local ou service compatible S3.

Choix par `COPRO_STOCKAGE` :
- « local » (défaut) : dossier `COPRO_UPLOAD_DIR`, comme avant ;
- « s3 » : bucket `COPRO_S3_BUCKET` sur AWS ou tout service compatible (Clever Cloud
  Cellar, OVH, Scaleway, MinIO…) via `COPRO_S3_ENDPOINT_URL`.

La base ne garde que le NOM du fichier (`documents.fichier`) : passer de l'un à l'autre
ne touche pas la base, il suffit de copier les fichiers (app/cli/migrer_stockage.py).

boto3 n'est importé qu'en mode S3 : une instance locale ne le charge jamais en mémoire.
"""
from __future__ import annotations

import os
import uuid
from functools import lru_cache
from typing import BinaryIO, Iterator, Protocol

BLOC = 1024 * 1024              # 1 Mo : lecture et écriture par blocs, jamais tout en mémoire


class StockageIndisponible(RuntimeError):
    """Le stockage refuse l'opération (droits, bucket absent, réseau, identifiants…)."""


class NomInvalide(ValueError):
    """Nom de fichier stocké refusé : il pourrait sortir du dossier ou du préfixe."""


def valider_nom(nom: str) -> str:
    """Un nom stocké est un nom SIMPLE : ni séparateur, ni « . » / « .. », ni nom caché.

    Les noms produits par l'application (uuid + extension, ou ceux du jeu de démo) passent ;
    une valeur forgée en base (« ../../etc/passwd ») est refusée, en local comme en S3.
    """
    if (not nom or "/" in nom or "\\" in nom or "\x00" in nom
            or nom.startswith(".") or len(nom) > 255):
        raise NomInvalide(nom)
    return nom


class Stockage(Protocol):
    def enregistrer(self, nom: str, flux: BinaryIO) -> None: ...
    def existe(self, nom: str) -> bool: ...
    def taille(self, nom: str) -> int | None: ...
    def lire_par_blocs(self, nom: str) -> Iterator[bytes]: ...
    def supprimer(self, nom: str) -> None: ...
    def lister(self) -> Iterator[str]: ...
    def verifier_ecriture(self) -> None: ...


class StockageLocal:
    """Fichiers dans un dossier du serveur (comportement historique)."""

    def __init__(self, dossier: str):
        self.dossier = dossier

    def chemin(self, nom: str) -> str:
        """Chemin absolu, garanti SOUS le dossier (double garde : nom simple + abspath)."""
        base = os.path.abspath(self.dossier)
        path = os.path.abspath(os.path.join(base, valider_nom(nom)))
        if not path.startswith(base + os.sep):
            raise NomInvalide(nom)
        return path

    def enregistrer(self, nom: str, flux: BinaryIO) -> None:
        """Écrit dans « <nom>.part » puis renomme : jamais de fichier à moitié écrit sous
        son vrai nom, et rien ne reste en cas d'erreur."""
        path = self.chemin(nom)
        os.makedirs(self.dossier, exist_ok=True)
        tmp = path + ".part"
        try:
            with open(tmp, "wb") as f:
                while bloc := flux.read(BLOC):
                    f.write(bloc)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def existe(self, nom: str) -> bool:
        return os.path.isfile(self.chemin(nom))

    def taille(self, nom: str) -> int | None:
        path = self.chemin(nom)
        return os.path.getsize(path) if os.path.isfile(path) else None

    def lire_par_blocs(self, nom: str) -> Iterator[bytes]:
        with open(self.chemin(nom), "rb") as f:
            while bloc := f.read(BLOC):
                yield bloc

    def supprimer(self, nom: str) -> None:
        path = self.chemin(nom)
        if os.path.exists(path):
            os.remove(path)

    def lister(self) -> Iterator[str]:
        if not os.path.isdir(self.dossier):
            return
        for nom in sorted(os.listdir(self.dossier)):
            if not nom.startswith(".") and not nom.endswith(".part") \
                    and os.path.isfile(os.path.join(self.dossier, nom)):
                yield nom

    def verifier_ecriture(self) -> None:
        sonde = os.path.join(self.dossier, f".verif-ecriture-{uuid.uuid4().hex}")
        try:
            os.makedirs(self.dossier, exist_ok=True)
            with open(sonde, "wb") as f:
                f.write(b"ok")
            os.remove(sonde)
        except OSError as e:
            raise StockageIndisponible(
                f"Dossier des documents non inscriptible ({self.dossier}) : {e}. "
                "Vérifiez COPRO_UPLOAD_DIR et les droits du dossier.") from e


class StockageS3:
    """Objets dans un bucket S3 (ou compatible), sous un préfixe (« documents/ » par défaut)."""

    def __init__(self, client, bucket: str, prefixe: str = ""):
        self.client = client
        self.bucket = bucket
        self.prefixe = prefixe

    def cle(self, nom: str) -> str:
        return self.prefixe + valider_nom(nom)

    def _erreur(self, action: str, e: Exception) -> StockageIndisponible:
        return StockageIndisponible(f"Stockage S3 ({self.bucket}) : {action} impossible : {e}")

    def enregistrer(self, nom: str, flux: BinaryIO) -> None:
        # upload_fileobj envoie par parties (multipart au-delà de 8 Mo) : mémoire bornée.
        cle = self.cle(nom)     # HORS du try : un NomInvalide ne doit pas devenir « S3 indisponible »
        try:
            self.client.upload_fileobj(flux, self.bucket, cle)
        except Exception as e:  # noqa: BLE001 — botocore lève des types variés
            raise self._erreur("écriture", e) from e

    def _tete(self, nom: str) -> dict | None:
        from botocore.exceptions import ClientError
        cle = self.cle(nom)
        try:
            return self.client.head_object(Bucket=self.bucket, Key=cle)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise self._erreur("lecture", e) from e
        except Exception as e:  # noqa: BLE001
            raise self._erreur("lecture", e) from e

    def existe(self, nom: str) -> bool:
        return self._tete(nom) is not None

    def taille(self, nom: str) -> int | None:
        tete = self._tete(nom)
        return None if tete is None else int(tete["ContentLength"])

    def lire_par_blocs(self, nom: str) -> Iterator[bytes]:
        # GetObject AVANT de rendre l'itérateur : une erreur remonte ici (réponse 503 propre),
        # pas au milieu d'un téléchargement dont les en-têtes sont déjà partis.
        cle = self.cle(nom)
        try:
            corps = self.client.get_object(Bucket=self.bucket, Key=cle)["Body"]
        except Exception as e:  # noqa: BLE001
            raise self._erreur("lecture", e) from e

        def blocs() -> Iterator[bytes]:
            try:
                yield from corps.iter_chunks(BLOC)
            finally:
                corps.close()
        return blocs()

    def supprimer(self, nom: str) -> None:
        cle = self.cle(nom)
        try:
            # DeleteObject sur une clé absente répond 204 : suppression idempotente.
            self.client.delete_object(Bucket=self.bucket, Key=cle)
        except Exception as e:  # noqa: BLE001
            raise self._erreur("suppression", e) from e

    def lister(self) -> Iterator[str]:
        try:
            pages = self.client.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix=self.prefixe)
            for page in pages:
                for obj in page.get("Contents", []):
                    nom = obj["Key"][len(self.prefixe):]
                    if nom and "/" not in nom:
                        yield nom
        except Exception as e:  # noqa: BLE001
            raise self._erreur("liste", e) from e

    def verifier_ecriture(self) -> None:
        """Écrit, relit puis supprime un petit objet : identifiants, bucket et droits
        vérifiés AU DÉMARRAGE, plutôt qu'au premier document déposé."""
        cle = f"{self.prefixe}.verif-ecriture-{uuid.uuid4().hex}"
        try:
            self.client.put_object(Bucket=self.bucket, Key=cle, Body=b"ok")
            lu = self.client.get_object(Bucket=self.bucket, Key=cle)["Body"].read()
            self.client.delete_object(Bucket=self.bucket, Key=cle)
        except Exception as e:  # noqa: BLE001
            raise StockageIndisponible(
                f"Stockage S3 inutilisable (bucket « {self.bucket} ») : {e}. Vérifiez "
                "COPRO_S3_BUCKET, COPRO_S3_ENDPOINT_URL et les identifiants.") from e
        if lu != b"ok":
            raise StockageIndisponible(f"Stockage S3 ({self.bucket}) : relecture incohérente")


def client_s3(endpoint_url: str = "", region: str = "", access_key_id: str = "",
              secret_access_key: str = ""):
    """Client boto3. Identifiants vides : chaîne standard d'AWS (variables AWS_*, rôle…)."""
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url or None,
        region_name=region or None,
        aws_access_key_id=access_key_id or None,
        aws_secret_access_key=secret_access_key or None,
        # Adressage « path » : accepté partout (MinIO, Cellar…), sans DNS par bucket.
        # Sommes de contrôle seulement quand l'API l'exige : depuis botocore 1.36, l'envoi
        # se fait par défaut en « aws-chunked » (CRC32 en fin de flux, SANS Content-Length),
        # ce que refusent les services compatibles S3 hors AWS (Clever Cloud Cellar :
        # MissingContentLength, issue #42). Réglage recommandé pour ces services.
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3},
                      request_checksum_calculation="when_required",
                      response_checksum_validation="when_required"),
    )


@lru_cache
def _stockage_s3(bucket: str, prefixe: str, endpoint_url: str, region: str,
                 access_key_id: str, secret_access_key: str) -> StockageS3:
    return StockageS3(client_s3(endpoint_url, region, access_key_id, secret_access_key),
                      bucket, prefixe)


def stockage_depuis(settings) -> Stockage:
    """Le stockage décrit par ces réglages (client S3 créé une seule fois)."""
    if settings.stockage == "s3":
        return _stockage_s3(settings.s3_bucket, settings.s3_prefix, settings.s3_endpoint_url,
                            settings.s3_region, settings.s3_access_key_id,
                            settings.s3_secret_access_key)
    return StockageLocal(settings.upload_dir)

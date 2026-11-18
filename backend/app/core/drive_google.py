"""Google Drive comme drive d'une copropriété (voir core/drive.py pour le principe).

⚠ Écrit d'après la documentation de Google et vérifié sur un faux serveur ; pas encore essayé sur le
vrai service (il faut l'application OAuth de l'instance : COPRO_GOOGLE_CLIENT_ID / _SECRET).

Même interface que `StockageWebDAV` : les noms sont des chemins relatifs au dossier du drive
(« Factures/2026-11-16 Facture.pdf »). Google Drive, lui, ne connaît que des identifiants : chaque
chemin est résolu dossier par dossier (`files.list` : nom + parent), avec un cache le temps d'une requête.

Autorisation : OAuth 2.0 (application web), portée `drive.file` — Proprietas ne voit et ne touche QUE les
fichiers et dossiers qu'il a créés. Conséquences : un fichier renommé ou déplacé dans Google Drive reste
visible (on peut le retrouver par son contenu) ; un fichier déposé à la main dans Google Drive ne l'est pas.
Le jeton de renouvellement est gardé chiffré en base (colonne du mot de passe du drive).

Suppression : mise à la corbeille de Google Drive (récupérable 30 jours), sauf le fichier témoin.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import BinaryIO, Iterator
from urllib.parse import urlencode

import httpx

from app.core import drive
from app.core.stockage import BLOC, StockageIndisponible

AUTORISATION = "https://accounts.google.com/o/oauth2/v2/auth"
JETON = "https://oauth2.googleapis.com/token"
REVOCATION = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/drive/v3"
ENVOI = "https://www.googleapis.com/upload/drive/v3/files"
PORTEE = "https://www.googleapis.com/auth/drive.file"
DOSSIER = "application/vnd.google-apps.folder"

_jetons: dict[str, tuple[str, float]] = {}      # empreinte du jeton de renouvellement → (jeton d'accès, échéance)


def _client() -> httpx.Client:
    return httpx.Client(transport=drive.TRANSPORT, follow_redirects=False, timeout=httpx.Timeout(60, connect=10))


def _post_jeton(champs: dict) -> dict:
    """Appel du serveur de jetons ; StockageIndisponible avec un message pour le syndic."""
    try:
        with _client() as client:
            r = client.post(JETON, data=champs)
    except httpx.HTTPError as e:
        raise StockageIndisponible(f"Google injoignable ({type(e).__name__}).") from e
    try:
        corps = r.json()
    except ValueError:
        corps = {}
    if r.status_code != 200:
        if corps.get("error") == "invalid_grant":
            raise StockageIndisponible("L'autorisation Google a expiré ou a été retirée : reconnectez Google Drive "
                                       "dans Réglages → Sauvegarde et stockage.")
        if corps.get("error") in ("invalid_client", "unauthorized_client"):
            raise StockageIndisponible("Google refuse l'application de cette instance (COPRO_GOOGLE_CLIENT_ID / "
                                       "COPRO_GOOGLE_CLIENT_SECRET).")
        raise StockageIndisponible(f"Google refuse la connexion (code {r.status_code}).")
    return corps


def adresse_autorisation(client_id: str, retour: str, etat: str) -> str:
    """Adresse où envoyer le syndic pour qu'il autorise Proprietas sur son Google Drive."""
    return AUTORISATION + "?" + urlencode({
        "client_id": client_id, "redirect_uri": retour, "response_type": "code", "scope": PORTEE,
        "access_type": "offline", "prompt": "consent", "state": etat})


def echanger_code(client_id: str, client_secret: str, code: str, retour: str) -> str:
    """Jeton de renouvellement obtenu en échange du code de retour."""
    corps = _post_jeton({"client_id": client_id, "client_secret": client_secret, "code": code,
                         "grant_type": "authorization_code", "redirect_uri": retour})
    if not corps.get("refresh_token"):
        raise StockageIndisponible("Google n'a pas donné d'autorisation durable : recommencez la connexion.")
    if PORTEE not in (corps.get("scope") or PORTEE).split():
        raise StockageIndisponible("L'accès aux fichiers n'a pas été accordé : recommencez en cochant la case de Google Drive.")
    return corps["refresh_token"]


def oublier(jeton: str) -> None:
    """Oublie le jeton d'accès gardé en mémoire pour ce jeton de renouvellement."""
    _jetons.pop(hashlib.sha256(jeton.encode()).hexdigest(), None)


def revoquer(jeton: str) -> None:
    """Retire l'autorisation chez Google. Attention : Google la retire pour le compte entier (tous les jetons
    accordés à cette application par ce compte), pas seulement pour ce jeton. Sans effet si Google ne répond pas."""
    try:
        with _client() as client:
            client.post(REVOCATION, data={"token": jeton})
    except httpx.HTTPError:
        pass
    oublier(jeton)


def _q(texte: str) -> str:
    """Valeur entre apostrophes d'une recherche Drive."""
    return "'" + texte.replace("\\", "\\\\").replace("'", "\\'") + "'"


class StockageGoogleDrive:
    """Fichiers sous `dossier` du Google Drive autorisé. Les noms sont des chemins relatifs."""

    def __init__(self, client_id: str, client_secret: str, jeton_renouvellement: str, dossier: str):
        self.client_id, self.client_secret, self.renouvellement = client_id, client_secret, jeton_renouvellement
        self.dossier = drive.valider_chemin(dossier)
        self._dossiers: dict[tuple[str, ...], str] = {}       # chemin de dossier → identifiant

    # --- jeton d'accès
    def _jeton(self) -> str:
        cle = hashlib.sha256(self.renouvellement.encode()).hexdigest()
        connu = _jetons.get(cle)
        if connu and connu[1] > time.time() + 60:
            return connu[0]
        corps = _post_jeton({"client_id": self.client_id, "client_secret": self.client_secret,
                             "grant_type": "refresh_token", "refresh_token": self.renouvellement})
        _jetons[cle] = (corps["access_token"], time.time() + int(corps.get("expires_in") or 3600))
        return corps["access_token"]

    def _requete(self, client: httpx.Client, methode: str, adresse: str, attendus: tuple[int, ...] = (200,), **kw):
        entetes = {"Authorization": f"Bearer {self._jeton()}", **kw.pop("headers", {})}
        try:
            r = client.request(methode, adresse, headers=entetes, **kw)
        except httpx.HTTPError as e:
            raise StockageIndisponible(f"Google Drive injoignable ({type(e).__name__}) : réessayez plus tard ; les fichiers déjà rangés ne sont pas perdus.") from e
        self._controler(r, attendus)
        return r

    @staticmethod
    def _controler(r: httpx.Response, attendus: tuple[int, ...]) -> None:
        if r.status_code in attendus:
            return
        try:
            raison = r.json()["error"]["errors"][0]["reason"]
        except (ValueError, KeyError, IndexError, TypeError):
            raison = ""
        if r.status_code == 401:
            raise StockageIndisponible("Google refuse l'autorisation : reconnectez Google Drive dans Réglages.")
        if raison in ("storageQuotaExceeded", "teamDriveFileLimitExceeded"):
            raise StockageIndisponible("Le Google Drive est plein (quota atteint).")
        if r.status_code in (403, 429) and "ateLimit" in raison:
            raise StockageIndisponible("Google Drive limite le nombre de demandes : réessayez dans une minute.")
        raise StockageIndisponible(f"Réponse inattendue de Google Drive (code {r.status_code}"
                                   + (f", {raison}" if raison else "") + ").")

    # --- chemins → identifiants
    def _lister(self, client: httpx.Client, q: str, champs: str = "id,name,mimeType,size") -> Iterator[dict]:
        page = None
        while True:
            params = {"q": q, "fields": f"nextPageToken,files({champs})", "pageSize": "1000", "spaces": "drive",
                      "orderBy": "createdTime"}
            if page:
                params["pageToken"] = page
            corps = self._requete(client, "GET", f"{API}/files", params=params).json()
            yield from corps.get("files") or []
            page = corps.get("nextPageToken")
            if not page:
                return

    def _dossier(self, client: httpx.Client, segments: list[str], creer: bool) -> str | None:
        """Identifiant du dossier `segments` (depuis la racine de « Mon Drive ») ; créé si demandé."""
        parent = "root"
        for n, nom in enumerate(segments, 1):
            cle = tuple(segments[:n])
            if cle not in self._dossiers:
                q = f"{_q(parent)} in parents and name = {_q(nom)} and mimeType = {_q(DOSSIER)} and trashed = false"
                trouve = next(self._lister(client, q, "id"), None)
                if trouve is None:
                    if not creer:
                        return None
                    trouve = self._requete(client, "POST", f"{API}/files", params={"fields": "id"},
                                           json={"name": nom, "mimeType": DOSSIER, "parents": [parent]}).json()
                self._dossiers[cle] = trouve["id"]
            parent = self._dossiers[cle]
        return parent

    def _fichier(self, client: httpx.Client, chemin: str) -> dict | None:
        """Le fichier `chemin` (id, taille) ; None s'il n'existe pas."""
        segments = self.dossier + drive.valider_chemin(chemin)
        parent = self._dossier(client, segments[:-1], creer=False)
        if parent is None:
            return None
        q = f"{_q(parent)} in parents and name = {_q(segments[-1])} and mimeType != {_q(DOSSIER)} and trashed = false"
        return next(self._lister(client, q, "id,size"), None)

    def _envoyer(self, client: httpx.Client, parent: str, nom: str, taille: int, contenu) -> str:
        """Envoi « reprenable » en une requête ; renvoie l'identifiant du fichier créé."""
        r = self._requete(client, "POST", ENVOI, params={"uploadType": "resumable", "fields": "id"},
                          json={"name": nom, "parents": [parent]},
                          headers={"X-Upload-Content-Type": "application/octet-stream",
                                   "X-Upload-Content-Length": str(taille)})
        session = r.headers.get("location")
        if not session:
            raise StockageIndisponible("Google Drive n'a pas ouvert l'envoi du fichier.")
        r = self._requete(client, "PUT", session, (200, 201), content=contenu,
                          headers={"Content-Length": str(taille), "Content-Type": "application/octet-stream"})
        return r.json().get("id", "")

    # --- interface de stockage (voir core/drive.StockageWebDAV)
    def nom_libre(self, dossier: str, nom: str) -> str:
        base, point, ext = nom.rpartition(".")
        if not point:
            base, ext = nom, ""
        with _client() as client:
            for n in range(1, 200):
                candidat = f"{dossier}/{nom if n == 1 else f'{base} ({n}){point}{ext}'}"
                if self._fichier(client, candidat) is None:
                    return candidat
        raise StockageIndisponible("Trop de fichiers du même nom sur le drive.")

    def enregistrer(self, nom: str, flux: BinaryIO) -> None:
        segments = self.dossier + drive.valider_chemin(nom)
        flux.seek(0, 2)
        taille = flux.tell()
        flux.seek(0)

        def blocs() -> Iterator[bytes]:
            while bloc := flux.read(BLOC):
                yield bloc

        with _client() as client:
            parent = self._dossier(client, segments[:-1], creer=True)
            ancien = self._fichier(client, nom)
            self._envoyer(client, parent, segments[-1], taille, blocs())
            if ancien:                      # même chemin : le nouveau remplace l'ancien
                self._requete(client, "PATCH", f"{API}/files/{ancien['id']}", json={"trashed": True})

    def existe(self, nom: str) -> bool:
        return self.taille(nom) is not None

    def taille(self, nom: str) -> int | None:
        with _client() as client:
            f = self._fichier(client, nom)
        return None if f is None else int(f.get("size") or 0)

    def lire_par_blocs(self, nom: str) -> Iterator[bytes]:
        def blocs() -> Iterator[bytes]:
            with _client() as client:
                f = self._fichier(client, nom)
                if f is None:
                    raise FileNotFoundError(nom)
                try:
                    with client.stream("GET", f"{API}/files/{f['id']}", params={"alt": "media"},
                                       headers={"Authorization": f"Bearer {self._jeton()}"}) as r:
                        if r.status_code != 200:
                            r.read()
                        self._controler(r, (200,))
                        yield from r.iter_bytes(BLOC)
                except httpx.HTTPError as e:
                    raise StockageIndisponible(f"Google Drive injoignable ({type(e).__name__}) : réessayez plus tard ; les fichiers déjà rangés ne sont pas perdus.") from e
        return blocs()

    def supprimer(self, nom: str) -> None:
        """Met le fichier à la corbeille de Google Drive (rien à faire s'il n'existe plus)."""
        with _client() as client:
            f = self._fichier(client, nom)
            if f:
                self._requete(client, "PATCH", f"{API}/files/{f['id']}", (200, 404), json={"trashed": True})

    def lister_arbre(self, profondeur: int = 4, maximum: int = 5000) -> dict[str, int]:
        """Tous les fichiers créés par Proprietas sous le dossier du drive : { chemin relatif: taille }."""
        fichiers: dict[str, int] = {}
        with _client() as client:
            racine = self._dossier(client, self.dossier, creer=False)
            a_voir = [(racine, "", 0)] if racine else []
            while a_voir:
                ident, prefixe, niveau = a_voir.pop()
                for f in self._lister(client, f"{_q(ident)} in parents and trashed = false"):
                    if f["name"].startswith("."):
                        continue
                    chemin = prefixe + f["name"]
                    if f.get("mimeType") == DOSSIER:
                        if niveau + 1 < profondeur:
                            a_voir.append((f["id"], chemin + "/", niveau + 1))
                        continue
                    fichiers.setdefault(chemin, int(f.get("size") or 0))
                    if len(fichiers) > maximum:
                        raise StockageIndisponible(f"Plus de {maximum} fichiers dans le dossier du drive.")
        return fichiers

    def verifier_ecriture(self) -> None:
        """Crée le dossier du drive, y écrit un fichier témoin, le relit et le supprime (définitivement)."""
        with _client() as client:
            parent = self._dossier(client, self.dossier, creer=True)
            ident = self._envoyer(client, parent, f".proprietas-essai-{uuid.uuid4().hex[:12]}.txt", 2, b"ok")
            try:
                lu = self._requete(client, "GET", f"{API}/files/{ident}", params={"alt": "media"}).content
            finally:
                self._requete(client, "DELETE", f"{API}/files/{ident}", (200, 204, 404))
        if lu != b"ok":
            raise StockageIndisponible("Google Drive ne rend pas ce qu'on y écrit (relecture incohérente).")

    def compte(self) -> str:
        """Adresse du compte Google autorisé (affichée dans Réglages)."""
        with _client() as client:
            corps = self._requete(client, "GET", f"{API}/about", params={"fields": "user(emailAddress,displayName)"}).json()
        return (corps.get("user") or {}).get("emailAddress") or (corps.get("user") or {}).get("displayName") or ""

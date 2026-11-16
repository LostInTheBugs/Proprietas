"""Drive d'une copropriété : ses fichiers rangés sur un serveur WebDAV (Nextcloud, ownCloud,
Synology, NAS…), dans une arborescence lisible.

    <dossier du drive>/Factures/2026-11-16 Facture d'électricité.pdf
    (dossier proposé : « Proprietas/<nom de la copropriété> »)

Le drive est le stockage PRINCIPAL des fichiers déposés tant qu'il est branché : rien n'est gardé
sur le serveur. `documents.emplacement` vaut « drive » et `documents.fichier` est le chemin relatif
au dossier du drive ; les autres documents restent dans le stockage de l'instance (local ou S3).

Garde-fous :
- l'adresse est saisie par un syndic et appelée par le serveur : seules http(s) sont admises, jamais
  de redirection suivie, et les adresses de la machine elle-même (boucle locale), de lien local
  (169.254.x.x : métadonnées des hébergeurs) ou réservées sont refusées ; le réseau privé (192.168…,
  cas du NAS à la maison) est admis sauf COPRO_DRIVE_RESEAU_LOCAL=false ;
- un chemin ne sort jamais du dossier du drive (ni « .. », ni chemin absolu) ;
- les réponses XML du serveur sont bornées et sans DTD.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import uuid
from types import SimpleNamespace
from typing import BinaryIO, Iterator
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree

import httpx

from app.core.stockage import BLOC, NomInvalide, StockageIndisponible

# Dossier de chaque catégorie de document (voir routes/documents.CATEGORIES).
DOSSIERS = {
    "contrat": "Contrats", "assurance": "Assurances", "facture": "Factures", "devis": "Devis",
    "diagnostic": "Diagnostics", "pv": "PV", "convocation": "Convocations", "autre": "Autres",
}
RACINE = "Proprietas"
INTERDITS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')     # refusés par Windows, donc par les clients de synchro
MAX_XML = 1024 * 1024
TRANSPORT = None                # remplacé par les tests (httpx.MockTransport)


class AdresseRefusee(ValueError):
    """Adresse de drive que le serveur ne doit pas appeler."""


# ---------------------------------------------------------------- noms et chemins
def assainir(texte: str, defaut: str = "document", longueur: int = 120) -> str:
    """Nom de fichier ou de dossier lisible et accepté partout (Windows compris)."""
    propre = " ".join(INTERDITS.sub(" ", texte or "").split()).strip(". ")
    return propre[:longueur].strip(". ") or defaut


def dossier_propose(nom_copro: str) -> str:
    return f"{RACINE}/{assainir(nom_copro, 'Copropriété')}"


def nom_lisible(jour, libelle: str, extension: str) -> str:
    """« 2026-11-16 Facture d'électricité.pdf » : classé par date, lisible sans l'application."""
    return f"{jour.isoformat()} {assainir(libelle)}{extension}"


def valider_chemin(chemin: str) -> list[str]:
    """Segments d'un chemin RELATIF sûr ; NomInvalide s'il pourrait sortir du dossier."""
    if not chemin or len(chemin) > 1000 or chemin.startswith("/") or "\\" in chemin:
        raise NomInvalide(chemin)
    segments = chemin.split("/")
    for s in segments:
        if not s or s in (".", "..") or INTERDITS.search(s):
            raise NomInvalide(chemin)
    return segments


# ---------------------------------------------------------------- adresse
def verifier_adresse(url: str, reseau_local: bool = True) -> str:
    """Adresse normalisée (sans « / » final), ou AdresseRefusee."""
    u = urlsplit((url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise AdresseRefusee("L'adresse du drive doit commencer par https:// (ou http:// sur un réseau local).")
    if u.username or u.password:
        raise AdresseRefusee("L'adresse ne doit pas contenir l'identifiant ni le mot de passe.")
    if u.query or u.fragment:
        raise AdresseRefusee("L'adresse ne doit contenir ni « ? » ni « # ».")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80),
                                   type=socket.SOCK_STREAM)
    except OSError as e:
        raise AdresseRefusee(f"Serveur introuvable : {u.hostname}.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise AdresseRefusee("Cette adresse désigne le serveur lui-même ou une adresse réservée : refusée.")
        if ip.is_private and not reseau_local:
            raise AdresseRefusee("Les adresses du réseau local sont désactivées sur cette instance.")
    return url.strip().rstrip("/")


# ---------------------------------------------------------------- WebDAV
class StockageWebDAV:
    """Fichiers sous `url`/`dossier` d'un serveur WebDAV. Les noms sont des chemins relatifs."""

    def __init__(self, url: str, utilisateur: str, mot_de_passe: str, dossier: str):
        self.url = url.rstrip("/")
        self.auth = (utilisateur, mot_de_passe) if utilisateur else None
        self.dossier = valider_chemin(dossier)

    # --- bas niveau
    def _client(self) -> httpx.Client:
        return httpx.Client(auth=self.auth, transport=TRANSPORT, follow_redirects=False,
                            timeout=httpx.Timeout(60, connect=10))

    def _adresse(self, segments: list[str]) -> str:
        return self.url + "/" + "/".join(quote(s, safe="") for s in segments)

    def adresse(self, chemin: str) -> str:
        return self._adresse(self.dossier + valider_chemin(chemin))

    def _requete(self, client: httpx.Client, methode: str, adresse: str, attendus: tuple[int, ...], **kw):
        try:
            r = client.request(methode, adresse, **kw)
        except httpx.HTTPError as e:
            raise StockageIndisponible(f"Drive injoignable ({type(e).__name__}).") from e
        self._controler(r, attendus)
        return r

    @staticmethod
    def _controler(r: httpx.Response, attendus: tuple[int, ...]) -> None:
        if r.status_code in attendus:
            return
        if r.status_code in (401, 403):
            raise StockageIndisponible("Le drive refuse l'identifiant ou le mot de passe.")
        if r.status_code in (301, 302, 303, 307, 308):
            raise StockageIndisponible("Le drive renvoie vers une autre adresse "
                                       f"({r.headers.get('location', '?')[:200]}) : saisissez l'adresse finale.")
        if r.status_code == 507:
            raise StockageIndisponible("Le drive est plein (quota atteint).")
        raise StockageIndisponible(f"Réponse inattendue du drive (code {r.status_code}).")

    def _creer_dossiers(self, client: httpx.Client, segments: list[str]) -> None:
        """Crée chaque niveau ; 405 = le dossier existe déjà."""
        for n in range(1, len(segments) + 1):
            self._requete(client, "MKCOL", self._adresse(segments[:n]), (201, 405))

    def _taille(self, client: httpx.Client, adresse: str) -> int | None:
        """Taille d'un FICHIER ; None s'il n'existe pas (ou si c'est un dossier)."""
        r = self._requete(client, "PROPFIND", adresse, (207, 404), headers={"Depth": "0"})
        if r.status_code == 404:
            return None
        if len(r.content) > MAX_XML or b"<!DOCTYPE" in r.content or b"<!ENTITY" in r.content:
            raise StockageIndisponible("Réponse du drive illisible.")
        try:
            racine = ElementTree.fromstring(r.content)
        except ElementTree.ParseError as e:
            raise StockageIndisponible("Réponse du drive illisible.") from e
        if racine.find(".//{DAV:}collection") is not None:
            return None
        taille = racine.findtext(".//{DAV:}getcontentlength")
        return int(taille) if taille and taille.isdigit() else 0

    # --- interface de stockage (voir core/stockage.Stockage)
    def nom_libre(self, dossier: str, nom: str) -> str:
        """Chemin « dossier/nom » encore libre : « nom (2).pdf », « nom (3).pdf »… si besoin."""
        base, point, ext = nom.rpartition(".")
        if not point:
            base, ext = nom, ""
        with self._client() as client:
            for n in range(1, 200):
                candidat = f"{dossier}/{nom if n == 1 else f'{base} ({n}){point}{ext}'}"
                r = self._requete(client, "PROPFIND", self.adresse(candidat), (207, 404), headers={"Depth": "0"})
                if r.status_code == 404:
                    return candidat
        raise StockageIndisponible("Trop de fichiers du même nom sur le drive.")

    def enregistrer(self, nom: str, flux: BinaryIO) -> None:
        segments = self.dossier + valider_chemin(nom)
        flux.seek(0, 2)
        taille = flux.tell()
        flux.seek(0)

        def blocs() -> Iterator[bytes]:
            while bloc := flux.read(BLOC):
                yield bloc

        with self._client() as client:
            self._creer_dossiers(client, segments[:-1])
            # Longueur annoncée : certains serveurs refusent un envoi « par morceaux ».
            self._requete(client, "PUT", self._adresse(segments), (200, 201, 204), content=blocs(),
                          headers={"Content-Length": str(taille), "Content-Type": "application/octet-stream"})

    def existe(self, nom: str) -> bool:
        return self.taille(nom) is not None

    def taille(self, nom: str) -> int | None:
        with self._client() as client:
            return self._taille(client, self.adresse(nom))

    def lire_par_blocs(self, nom: str) -> Iterator[bytes]:
        adresse = self.adresse(nom)

        def blocs() -> Iterator[bytes]:
            with self._client() as client:
                try:
                    with client.stream("GET", adresse) as r:
                        if r.status_code == 404:
                            raise FileNotFoundError(nom)
                        self._controler(r, (200,))
                        yield from r.iter_bytes(BLOC)
                except httpx.HTTPError as e:
                    raise StockageIndisponible(f"Drive injoignable ({type(e).__name__}).") from e
        return blocs()

    def supprimer(self, nom: str) -> None:
        with self._client() as client:
            self._requete(client, "DELETE", self.adresse(nom), (200, 204, 404))

    def verifier_ecriture(self) -> None:
        """Crée le dossier du drive, y écrit un fichier témoin, le relit et le supprime."""
        temoin = self.dossier + [f".proprietas-essai-{uuid.uuid4().hex[:12]}.txt"]
        adresse = self._adresse(temoin)
        with self._client() as client:
            self._creer_dossiers(client, self.dossier)
            self._requete(client, "PUT", adresse, (200, 201, 204), content=b"ok", headers={"Content-Length": "2"})
            try:
                lu = self._requete(client, "GET", adresse, (200,)).content
            finally:
                self._requete(client, "DELETE", adresse, (200, 204, 404))
        if lu != b"ok":
            raise StockageIndisponible("Le drive ne rend pas ce qu'on y écrit (relecture incohérente).")


# ---------------------------------------------------------------- copropriété
def reglages(copro) -> SimpleNamespace | None:
    """Réglages du drive de la copropriété, ou None s'il n'est pas branché."""
    if getattr(copro, "drive_type", "") != "webdav" or not copro.drive_url or not copro.drive_dossier:
        return None
    return SimpleNamespace(url=copro.drive_url, utilisateur=copro.drive_user or "",
                           mot_de_passe=copro.drive_password or "", dossier=copro.drive_dossier)


def stockage_drive(copro, reseau_local: bool = True) -> StockageWebDAV | None:
    """Le drive de la copropriété, prêt à servir, ou None s'il n'est pas branché."""
    r = reglages(copro)
    if r is None:
        return None
    try:
        verifier_adresse(r.url, reseau_local)
        return StockageWebDAV(r.url, r.utilisateur, r.mot_de_passe, r.dossier)
    except (AdresseRefusee, NomInvalide) as e:
        raise StockageIndisponible(f"Réglages du drive invalides : {e}") from e

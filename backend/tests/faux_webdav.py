"""Faux serveur WebDAV en mémoire (httpx.MockTransport), au comportement relevé sur Nextcloud 34 et
ownCloud 10.16 (tâche 57) : MKCOL 201 / 405 si le dossier existe / 409 si le parent manque, PUT 201
puis 204, PROPFIND 207 / 404, GET 200 / 404, DELETE 204 / 404, 401 sans le bon mot de passe."""
import base64
from urllib.parse import unquote

import httpx

BASE = "/remote.php/dav/files/syndic"
URL = "https://cloud.exemple.fr" + BASE


class FauxWebDAV:
    def __init__(self, utilisateur="syndic", mot_de_passe="secret-drive"):
        self.attendu = "Basic " + base64.b64encode(f"{utilisateur}:{mot_de_passe}".encode()).decode()
        self.dossiers = {""}
        self.fichiers: dict[str, bytes] = {}
        self.requetes: list[tuple[str, str]] = []
        self.entetes: list[dict] = []
        self.panne = False          # serveur injoignable
        self.plein = False          # quota atteint
        self.redirige = False

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._repondre)

    def chemins(self) -> list[str]:
        return sorted(self.fichiers)

    def _repondre(self, requete: httpx.Request) -> httpx.Response:
        if self.panne:
            raise httpx.ConnectError("connexion refusée", request=requete)
        chemin = unquote(requete.url.raw_path.decode().split("?")[0])
        assert chemin.startswith(BASE), chemin
        chemin = chemin[len(BASE):].strip("/")
        self.requetes.append((requete.method, chemin))
        self.entetes.append(dict(requete.headers))
        if self.redirige:
            return httpx.Response(301, headers={"Location": "https://ailleurs.exemple.fr/"})
        if requete.headers.get("authorization") != self.attendu:
            return httpx.Response(401)
        parent = chemin.rpartition("/")[0]
        m = requete.method
        if m == "MKCOL":
            if chemin in self.dossiers:
                return httpx.Response(405)
            if parent not in self.dossiers:
                return httpx.Response(409)
            self.dossiers.add(chemin)
            return httpx.Response(201)
        if m == "PUT":
            if self.plein:
                return httpx.Response(507)
            if parent not in self.dossiers:
                return httpx.Response(409)
            code = 204 if chemin in self.fichiers else 201
            self.fichiers[chemin] = requete.read()
            return httpx.Response(code)
        if m == "PROPFIND":
            if chemin in self.fichiers:
                corps = (f'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:"><d:response><d:propstat><d:prop>'
                         f'<d:getcontentlength>{len(self.fichiers[chemin])}</d:getcontentlength><d:resourcetype/>'
                         f'</d:prop></d:propstat></d:response></d:multistatus>')
                return httpx.Response(207, content=corps.encode())
            if chemin in self.dossiers:
                corps = ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:"><d:response><d:propstat><d:prop>'
                         '<d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat></d:response>'
                         '</d:multistatus>')
                return httpx.Response(207, content=corps.encode())
            return httpx.Response(404)
        if m == "GET":
            if chemin in self.fichiers:
                return httpx.Response(200, content=self.fichiers[chemin])
            return httpx.Response(404)
        if m == "DELETE":
            if chemin in self.fichiers:
                del self.fichiers[chemin]
                return httpx.Response(204)
            return httpx.Response(404)
        return httpx.Response(405)

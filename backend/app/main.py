import math
import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from app.core.config import get_settings
from app.core.version import VERSION
from app.core.database import SessionLocal
from app.core.httpinfo import est_externe, requete_https
from app.models.instance import InstanceState
from app.routes import auth, copro, lots, comptes, ag, documents, carnet, export, email, relances, travaux, consolide, contacts, contrats, securite, instance, recouvrement, updates

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.upload_dir, exist_ok=True)
    # Les migrations sont gérées par Alembic (`alembic upgrade head`),
    # étape explicite au démarrage du conteneur / en dev — pas ici :
    # un démarrage qui migre est dangereux quand plusieurs conteneurs
    # démarrent en même temps (voir README, section Déploiement).
    from app.core.scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Proprietas", version=VERSION, lifespan=lifespan)


def _json_fini(o):
    """NaN / ±Infinity → texte : ces valeurs ne sont pas du JSON valide."""
    if isinstance(o, float) and not math.isfinite(o):
        return str(o)
    if isinstance(o, dict):
        return {k: _json_fini(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_fini(v) for v in o]
    return o


# Marge pour l'enveloppe multipart (autres champs, en-têtes de parties) au-delà du fichier.
_MARGE_UPLOAD = 1024 * 1024


@app.middleware("http")
async def _limite_taille_upload(request: Request, call_next):
    """Refuse d'emblée (413) un upload dont le Content-Length dépasse déjà la limite :
    le corps n'est ni lu ni mis en tampon. La route recontrôle pendant la copie
    (Content-Length absent ou mensonger)."""
    if request.method == "POST" and request.url.path == "/api/documents":
        longueur = request.headers.get("content-length", "")
        limite_mo = documents.settings.upload_max_mb      # même source que la route
        if longueur.isdigit() and int(longueur) > int(limite_mo * 1024 * 1024) + _MARGE_UPLOAD:
            return JSONResponse(status_code=413,
                                content={"detail": f"Requête trop volumineuse (maximum {limite_mo:g} Mo)"})
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def _erreur_validation(request: Request, exc: RequestValidationError):
    """Même réponse 422 que FastAPI, mais sans planter quand la valeur refusée est NaN ou
    Infinity : le gestionnaire par défaut renvoie la valeur saisie (`input`) et l'encodage
    JSON échouait → 500 au lieu de 422."""
    return JSONResponse(status_code=422, content={"detail": _json_fini(jsonable_encoder(exc.errors()))})

# CORS : en dev (SQLite) on autorise le serveur Vite ; en prod le frontend est
# servi par le même backend, donc liste vide par défaut (configurable via
# COPRO_CORS_ORIGINS, JSON : '["https://app.example.fr"]'). allow_credentials
# nécessaire au cookie de session en dev (Vite 5173 → API 8000).
origins = settings.cors_origins
if not origins and settings.is_sqlite:
    origins = ["http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth, copro, lots, comptes, ag, documents, carnet, export, email, relances, travaux, consolide, contacts, contrats, securite, instance, recouvrement, updates):
    app.include_router(r.router)
app.include_router(securite.router_audit)


# ---------- En-têtes de sécurité (tous les modes de déploiement) ----------
# Tout est servi par l'application elle-même : CSP stricte sauf /docs (Swagger
# charge ses assets depuis un CDN). style-src 'unsafe-inline' : barres de
# progression en styles inline dans le frontend.
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


@app.middleware("http")
async def entetes_securite(request: Request, call_next):
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    if not request.url.path.startswith("/docs"):
        h.setdefault("Content-Security-Policy", _CSP)
    if requete_https(request):
        h.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


# ---------- Exposition internet : jamais silencieuse ----------
@app.middleware("http")
async def detecter_acces_externe(request: Request, call_next):
    """Note la PREMIÈRE requête vue depuis internet : l'application ne peut pas
    être exposée sans que son propriétaire puisse le savoir (bandeau + assistant)."""
    if est_externe(request):
        try:
            with SessionLocal() as s:
                inst = s.get(InstanceState, 1)
                if inst is None:
                    inst = InstanceState(id=1)
                    s.add(inst)
                if not inst.first_external_at:
                    inst.first_external_at = datetime.now()
                    s.commit()
        except Exception:
            pass  # la détection ne bloque JAMAIS la requête
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.app_name}


# Frontend statique (build Vite) servi par le backend en production,
# avec fallback SPA pour les routes profondes (refresh sur /ag, /comptes…)
if settings.frontend_dist and os.path.isdir(settings.frontend_dist):
    dist = settings.frontend_dist

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        base = os.path.abspath(dist)
        full = os.path.abspath(os.path.join(base, full_path))
        if os.path.isfile(full) and full.startswith(base):
            # Les fichiers Vite ont un hash de contenu dans leur nom → cache long.
            cache = "public, max-age=31536000, immutable" if full_path.startswith("assets/") else "no-cache"
            return FileResponse(full, headers={"Cache-Control": cache})
        index = os.path.join(base, "index.html")
        if os.path.isfile(index):
            # index.html jamais mis en cache : le navigateur récupère toujours le
            # dernier bundle (évite les boucles/bugs liés à un ancien JS).
            return FileResponse(index, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
        raise HTTPException(404, "Not Found")

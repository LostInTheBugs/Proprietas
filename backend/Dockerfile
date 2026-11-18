# ===== Stage 1 : build du frontend (Node 20) =====
FROM node:20-alpine AS frontend-build
WORKDIR /src/frontend

# package.json + lock d'abord : le cache npm est réutilisé tant que les deps
# ne changent pas.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build   # inclut tsc -b (typecheck)

# ===== Stage 2 : backend Python 3.11 =====
FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/alembic.ini .
COPY backend/alembic ./alembic

# Bundle frontend produit par le stage 1 — stratégie de cache conservée :
# app/main.py sert les assets hashés en `immutable` et index.html en `no-store`.
COPY --from=frontend-build /src/frontend/dist ./frontend_dist

RUN mkdir -p /app/uploads

EXPOSE 8000
# Migration explicite au démarrage (Alembic, idempotent) puis serveur. Pendant la migration,
# /api/health répond déjà (phase « migration ») et le journal dit où elle en est (app/demarrage.py).
CMD ["python", "-m", "app.demarrage"]

/**
 * Client API — session par cookie httpOnly (P3).
 *
 * Le navigateur ne stocke plus le jeton : il vit dans un cookie `HttpOnly` posé
 * par le serveur à la connexion. Un éventuel jeton hérité (localStorage des
 * versions précédentes) est migré en cookie au premier chargement
 * (POST /auth/session), puis effacé. Le header Bearer et `?token=` restent
 * acceptés côté serveur pour l'API, la CLI et les scripts.
 */
const TOKEN_KEY = "copro_token";

/** Jeton hérité (transition) — le cookie de session est invisible du JS. */
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

let migration: Promise<void> | null = null;

/** Convertit une éventuelle session à jeton héritée en cookie de session. */
function migrerSessionLegacy(): Promise<void> {
  if (!migration) {
    migration = (async () => {
      const legacy = localStorage.getItem(TOKEN_KEY);
      if (!legacy) return;
      try {
        const res = await fetch("/api/auth/session", {
          method: "POST",
          headers: { Authorization: `Bearer ${legacy}` },
          credentials: "include",
        });
        if (res.ok) localStorage.removeItem(TOKEN_KEY); // session désormais en cookie
      } catch {
        /* réseau : nouvelle tentative au prochain chargement */
      }
    })();
  }
  return migration;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  await migrerSessionLegacy();
  const headers: Record<string, string> = {};
  const legacy = localStorage.getItem(TOKEN_KEY);
  if (legacy) headers["Authorization"] = `Bearer ${legacy}`;
  let payload: BodyInit | undefined;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch("/api" + path, { method, headers, body: payload, credentials: "include" });
  if (res.status === 401) {
    clearToken();
    // Ne pas recharger si on est déjà sur la page de login (évite la boucle
    // de rechargement quand /auth/me répond 401 sans session).
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new Error("Non authentifié");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

/** POST avec jeton explicite, SANS redirection 401 — étapes 2FA de la connexion
 *  (jeton de challenge/enrôlement) et assistants. */
export async function postAuthStep<T>(path: string, body: unknown, token?: string): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch("/api" + path, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    credentials: "include",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export async function uploadDocument(categorie: string, libelle: string, file: File) {
  const form = new FormData();
  form.append("categorie", categorie);
  form.append("libelle", libelle);
  form.append("fichier", file);
  const headers: Record<string, string> = {};
  const legacy = localStorage.getItem(TOKEN_KEY);
  if (legacy) headers["Authorization"] = `Bearer ${legacy}`;
  const res = await fetch("/api/documents", {
    method: "POST",
    headers,
    body: form,
    credentials: "include",
  });
  if (!res.ok) throw new Error("Upload échoué");
  return res.json();
}

import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api, clearToken, setToken } from "../api";
import { useUser } from "../auth";
import type { Copro } from "../types";

const NAV = [
  { to: "/", label: "Tableau de bord", icon: "▦" },
  { to: "/lots", label: "Lots & occupants", icon: "⌂" },
  { to: "/comptes", label: "Comptes", icon: "€" },
  { to: "/ag", label: "Assemblées", icon: "🗳" },
  { to: "/documents", label: "Documents", icon: "▤" },
  { to: "/contacts", label: "Contacts", icon: "👥" },
  { to: "/contrats", label: "Contrats", icon: "📄" },
  { to: "/carnet", label: "Carnet d'entretien", icon: "🔧" },
  { to: "/relances", label: "Relances", icon: "📧" },
  { to: "/travaux", label: "Travaux", icon: "🔨" },
  { to: "/consolide", label: "Consolidé", icon: "🗂" },
  { to: "/securite", label: "Sécurité", icon: "🔐" },
  { to: "/settings", label: "Réglages", icon: "⚙" },
];

interface CoproLien {
  id: number;
  nom: string;
  ville: string;
  principale: boolean;
  active: boolean;
}

export default function Layout() {
  const { user } = useUser();
  const [copros, setCopros] = useState<CoproLien[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [creation, setCreation] = useState(false);
  const [nvNom, setNvNom] = useState("");
  const [nvVille, setNvVille] = useState("");
  const [busy, setBusy] = useState(false);
  const [alerteExposition, setAlerteExposition] = useState(false);
  const nav = useNavigate();

  useEffect(() => {
    api.get<CoproLien[]>("/auth/coproprietes").then(setCopros).catch(() => {});
  }, []);

  useEffect(() => {
    // Bandeau « exposition internet non déclarée » — réservé au syndic (seul à pouvoir agir).
    if (user?.role !== "syndic") return;
    api.get<{ exposed_unprotected: boolean }>("/instance")
      .then((i) => setAlerteExposition(!!i.exposed_unprotected))
      .catch(() => {});
  }, [user?.role]);

  const active = copros.find((c) => c.active);

  async function switcher(id: number) {
    setBusy(true);
    try {
      const r = await api.post<{ access_token: string }>(`/auth/switch-copro/${id}`);
      setToken(r.access_token);
      window.location.reload();
    } catch {
      setBusy(false);
    }
  }

  async function creer() {
    if (!nvNom.trim() || busy) return;
    setBusy(true);
    try {
      const r = await api.post<{ access_token: string }>("/auth/coproprietes", {
        nom: nvNom.trim(),
        ville: nvVille.trim(),
      });
      setToken(r.access_token);
      window.location.reload();
    } catch (e) {
      setBusy(false);
      alert(e instanceof Error ? e.message : "Erreur");
    }
  }

  function logout() {
    clearToken();
    nav("/login");
  }

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="relative px-5 py-4">
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            className="flex w-full items-center gap-2.5 text-left"
            title="Changer de copropriété"
          >
            <img src="/proprietas-icon.png" alt="" className="h-9 w-auto shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-bold text-slate-800">Proprietas</p>
              <p className="truncate text-xs text-slate-500">{active?.nom ?? "…"}</p>
            </div>
            <span className="text-xs text-slate-400">▾</span>
          </button>
          {menuOpen && (
            <div className="absolute left-3 right-3 top-[4.2rem] z-20 rounded-xl border border-slate-200 bg-white p-2 shadow-lg">
              {copros.map((c) => (
                <button
                  key={c.id}
                  onClick={() => switcher(c.id)}
                  className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm ${
                    c.active ? "bg-indigo-50 font-medium text-indigo-700" : "text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  <span className="w-4 text-center">🏢</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{c.nom}</span>
                    {c.ville && <span className="block truncate text-xs text-slate-400">{c.ville}</span>}
                  </span>
                  {c.active && <span className="text-xs text-indigo-500">✓</span>}
                </button>
              ))}
              {user?.role === "syndic" && !creation && (
                <button
                  onClick={() => setCreation(true)}
                  className="mt-1 flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm text-slate-500 hover:bg-slate-50"
                >
                  <span className="w-4 text-center">＋</span> Nouvelle copropriété
                </button>
              )}
              {creation && (
                <div className="mt-1 space-y-1.5 rounded-lg border border-dashed border-slate-300 p-2">
                  <input
                    autoFocus
                    value={nvNom}
                    onChange={(e) => setNvNom(e.target.value)}
                    placeholder="Nom (ex. Résidence Les Tilleuls)"
                    className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-sm outline-none focus:border-indigo-400"
                  />
                  <input
                    value={nvVille}
                    onChange={(e) => setNvVille(e.target.value)}
                    placeholder="Ville (optionnel)"
                    className="w-full rounded-lg border border-slate-200 px-2 py-1.5 text-sm outline-none focus:border-indigo-400"
                  />
                  <div className="flex gap-1.5">
                    <button
                      onClick={creer}
                      disabled={busy || !nvNom.trim()}
                      className="flex-1 rounded-lg bg-indigo-600 px-2 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                    >
                      {busy ? "…" : "Créer"}
                    </button>
                    <button
                      onClick={() => setCreation(false)}
                      className="rounded-lg bg-slate-100 px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-200"
                    >
                      Annuler
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
        <nav className="flex-1 space-y-0.5 px-3 py-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-indigo-50 text-indigo-700"
                    : "text-slate-600 hover:bg-slate-50 hover:text-slate-800"
                }`
              }
            >
              <span className="w-5 text-center text-base leading-none">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-100 px-5 py-3.5">
          <p className="truncate text-sm font-medium text-slate-700">{user?.nom ?? "…"}</p>
          <p className="truncate text-xs text-slate-500">
            {user ? (user.role === "syndic" ? "Syndic bénévole" : "Copropriétaire") : "…"}
          </p>
          <button onClick={logout} className="mt-2 text-xs font-medium text-slate-500 hover:text-red-600">
            Se déconnecter
          </button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        {alerteExposition && (
          <div className="border-b border-amber-200 bg-amber-50 px-8 py-2 text-sm text-amber-800">
            ⚠️ Cette application est joignable depuis internet sans que les protections aient été
            vérifiées.{" "}
            <NavLink to="/securite" className="font-medium underline hover:text-amber-900">
              Ouvrir Sécurité → Accès depuis internet
            </NavLink>
          </div>
        )}
        <main className="flex-1 overflow-x-hidden px-8 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

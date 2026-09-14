import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, postAuthStep } from "../api";
import type { LoginResponse } from "../types";
import TwoFactorWizard from "../components/TwoFactorWizard";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [prenom, setPrenom] = useState("");
  const [nom, setNom] = useState("");
  const [mode, setMode] = useState<"login" | "register">("login");
  // Étape 2FA : « creds » (mot de passe) → « totp » (code) ou « setup » (enrôlement exigé)
  const [etape, setEtape] = useState<"creds" | "totp" | "setup">("creds");
  const [challenge, setChallenge] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();

  function entrer() {
    // La session vit dans un cookie httpOnly posé par le serveur : un simple
    // rechargement suffit (le UserProvider relit /auth/me avec le cookie).
    window.location.href = "/";
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = mode === "login"
        ? await api.post<LoginResponse>("/auth/login", { email, password })
        : await api.post<LoginResponse>("/auth/register", { email, password, nom, prenom });
      if (res.access_token) {
        entrer();
        return;
      }
      if (res.challenge_token) {
        setChallenge(res.challenge_token);
        setEtape(res.must_enroll_2fa ? "setup" : "totp");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    } finally {
      setBusy(false);
    }
  }

  async function validerCode(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await postAuthStep<LoginResponse>("/auth/2fa/verify-login", {
        challenge_token: challenge,
        code,
      });
      if (res.access_token) entrer();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    } finally {
      setBusy(false);
    }
  }

  function retourCreds() {
    setEtape("creds");
    setChallenge("");
    setCode("");
    setError("");
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <img src="/proprietas-icon.png" alt="" className="mx-auto mb-2 h-16 w-auto" />
          <h1 className="text-xl font-bold text-slate-800">Proprietas</h1>
          <p className="mt-1 text-sm text-slate-500">Gestion de copropriété pour syndics bénévoles</p>
        </div>

        {etape === "creds" && (
          <form onSubmit={submit} className="space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex rounded-lg bg-slate-100 p-1 text-sm font-medium">
              {(["login", "register"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={`flex-1 rounded-md py-1.5 transition-colors ${
                    mode === m ? "bg-white text-slate-800 shadow-sm" : "text-slate-500 hover:text-slate-700"
                  }`}
                >
                  {m === "login" ? "Connexion" : "Premier compte (syndic)"}
                </button>
              ))}
            </div>
            {mode === "register" && (
              <div className="grid grid-cols-2 gap-3">
                <label className="block text-sm">
                  <span className="mb-1 block font-medium text-slate-600">Prénom</span>
                  <input
                    value={prenom}
                    onChange={(e) => setPrenom(e.target.value)}
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    placeholder="Marie"
                  />
                </label>
                <label className="block text-sm">
                  <span className="mb-1 block font-medium text-slate-600">Nom</span>
                  <input
                    value={nom}
                    onChange={(e) => setNom(e.target.value)}
                    required
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                    placeholder="Dupont"
                  />
                </label>
              </div>
            )}
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-slate-600">Email</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                placeholder="vous@exemple.fr"
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-slate-600">Mot de passe</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={6}
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                placeholder="••••••••"
              />
            </label>
            {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-lg bg-indigo-600 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-indigo-700 disabled:opacity-50"
            >
              {busy ? "…" : mode === "login" ? "Se connecter" : "Créer le compte syndic"}
            </button>
            {mode === "register" && (
              <p className="text-xs leading-relaxed text-slate-500">
                Le premier compte créé est le syndic. L'inscription est ensuite fermée — les autres comptes sont créés
                par le syndic dans les réglages.
              </p>
            )}
          </form>
        )}

        {etape === "totp" && (
          <form onSubmit={validerCode} className="space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <p className="text-sm leading-relaxed text-slate-600">
              Saisissez le code affiché par votre application d'authentification pour{" "}
              <span className="font-medium text-slate-800">{email}</span>.
            </p>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-slate-600">Code de connexion</span>
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
                autoFocus
                autoComplete="one-time-code"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-center font-mono text-base tracking-widest focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                placeholder="123456"
              />
            </label>
            <p className="text-xs leading-relaxed text-slate-500">
              Téléphone perdu ? Saisissez l'un de vos codes de secours à la place du code à 6 chiffres.
            </p>
            {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
            <button
              type="submit"
              disabled={busy || !code.trim()}
              className="w-full rounded-lg bg-indigo-600 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-indigo-700 disabled:opacity-50"
            >
              {busy ? "…" : "Se connecter"}
            </button>
            <button
              type="button"
              onClick={retourCreds}
              className="w-full text-xs font-medium text-slate-500 hover:text-slate-700"
            >
              ← Revenir à la saisie du mot de passe
            </button>
          </form>
        )}

        {etape === "setup" && (
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <TwoFactorWizard
              token={challenge}
              intro={`La double authentification est exigée pour le compte ${email} (politique de la copropriété ou accès depuis internet). Activez-la maintenant : elle ne prend qu'une minute et ne vous sera plus redemandée.`}
              onDone={(tok) => tok && entrer()}
              onCancel={retourCreds}
            />
          </div>
        )}
      </div>
    </div>
  );
}

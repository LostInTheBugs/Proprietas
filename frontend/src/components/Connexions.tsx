import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Button, Card, Input } from "./ui";
import type { CompteBloque, Connexions, Copro, User } from "../types";

/** Connexions : dernière connexion, historique (si activé), blocage des comptes. */

export const LIBELLES_CONNEXION: Record<string, string> = {
  login: "Connexion",
  login_failed: "Échec de connexion",
  login_blocked: "Connexion refusée (compte bloqué)",
  account_locked: "Compte bloqué",
  account_unlocked: "Compte débloqué",
};

export function dateHeure(d?: string | null): string {
  return d ? new Date(d).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—";
}

function heure(d?: string | null): string {
  return d ? new Date(d).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) : "";
}

/** Badge d'état d'un compte bloqué (rien s'il ne l'est pas). */
export function BadgeBlocage({ u }: { u: Pick<User, "bloque" | "bloque_jusqua"> }) {
  if (u.bloque === "definitif") return <Badge color="red">Bloqué</Badge>;
  if (u.bloque === "temporaire") return <Badge color="amber">Bloqué jusqu'à {heure(u.bloque_jusqua)}</Badge>;
  return null;
}

/** Résumé et liste des connexions d'un compte. */
export function DetailConnexions({ c }: { c: Connexions }) {
  return (
    <div className="space-y-2 text-sm">
      <p className="text-slate-600">
        Dernière connexion : <span className="font-medium text-slate-800">{dateHeure(c.derniere_connexion)}</span>
        {c.derniere_ip && <span className="text-slate-500"> ({c.derniere_ip})</span>}
        {" · "}dernier échec : <span className="font-medium text-slate-800">{dateHeure(c.dernier_echec)}</span>
        {c.echecs_d_affilee > 0 && (
          <span className="text-slate-500"> ({c.echecs_d_affilee} échec{c.echecs_d_affilee > 1 ? "s" : ""} d'affilée)</span>
        )}
      </p>
      {!c.historique ? (
        <p className="text-xs text-slate-500">
          L'historique complet n'est pas activé : seules la dernière connexion et le dernier échec sont gardés.
        </p>
      ) : c.entrees.length === 0 ? (
        <p className="text-xs text-slate-500">Aucune connexion enregistrée depuis l'activation de l'historique.</p>
      ) : (
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
          {c.entrees.map((e, i) => (
            <li key={i} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-3 py-1.5">
              <span className="w-28 shrink-0 text-xs tabular-nums text-slate-500">{dateHeure(e.date)}</span>
              <span
                className={
                  e.action === "login"
                    ? "text-slate-700"
                    : e.action === "account_unlocked"
                      ? "text-emerald-700"
                      : "font-medium text-red-700"
                }
              >
                {LIBELLES_CONNEXION[e.action] ?? e.action}
              </span>
              {e.detail && <span className="text-xs text-slate-500">{e.detail}</span>}
              {e.ip && <span className="ml-auto text-xs text-slate-400">{e.ip}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** « Sessions et appareils » : mes propres connexions. */
export function MesConnexions() {
  const [c, setC] = useState<Connexions | null>(null);
  useEffect(() => {
    api.get<Connexions>("/auth/me/connexions").then(setC).catch(() => {});
  }, []);
  if (!c) return null;
  return (
    <div className="border-t border-slate-100 pt-3">
      <p className="mb-2 text-sm font-medium text-slate-700">Mes connexions</p>
      <DetailConnexions c={c} />
    </div>
  );
}

/** Réglages de la copropriété (syndic) : historique et blocage. */
export function PolitiqueConnexionsCard({ copro, onSaved }: { copro: Copro | null; onSaved: (c: Copro) => void }) {
  const [historique, setHistorique] = useState(false);
  const [actif, setActif] = useState(false);
  const [seuil, setSeuil] = useState("5");
  const [minutes, setMinutes] = useState("15");
  const [definitif, setDefinitif] = useState("10");
  const [avec2fa, setAvec2fa] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!copro) return;
    setHistorique(!!copro.connexions_historique);
    setActif(!!copro.verrouillage_actif);
    setSeuil(String(copro.verrouillage_seuil ?? 5));
    setMinutes(String(copro.verrouillage_minutes ?? 15));
    setDefinitif(String(copro.verrouillage_seuil_definitif ?? 10));
    setAvec2fa(!!copro.verrouillage_avec_2fa);
  }, [copro]);

  async function enregistrer(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const maj = await api.put<Copro>("/copro", {
        connexions_historique: historique,
        verrouillage_actif: actif,
        verrouillage_seuil: Number(seuil),
        verrouillage_minutes: Number(minutes),
        verrouillage_seuil_definitif: Number(definitif),
        verrouillage_avec_2fa: avec2fa,
      });
      onSaved(maj);
      setMessage("Réglages des connexions enregistrés.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Connexions : historique et blocage">
      <form onSubmit={enregistrer} className="space-y-4 text-sm">
        <label className="flex items-start gap-2 text-slate-700">
          <input type="checkbox" className="mt-1" checked={historique} onChange={(e) => setHistorique(e.target.checked)} />
          <span>
            Garder l'historique complet des connexions (réussies, ratées, refusées)
            <span className="block text-xs text-slate-500">
              Sinon, seules la dernière connexion et le dernier échec de chaque compte sont gardés. L'historique va dans
              le journal d'audit et suit sa durée de conservation (12 mois par défaut).
            </span>
          </span>
        </label>

        <label className="flex items-start gap-2 text-slate-700">
          <input type="checkbox" className="mt-1" checked={actif} onChange={(e) => setActif(e.target.checked)} />
          <span>
            Bloquer un compte après des échecs de connexion d'affilée
            <span className="block text-xs text-slate-500">
              Le compteur repart à zéro à chaque connexion réussie. La personne est prévenue par e-mail.
            </span>
          </span>
        </label>

        {actif && (
          <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
            <div className="flex flex-wrap gap-3">
              <div className="w-44">
                <Input label="Blocage temporaire après" type="number" min={1} max={100} value={seuil}
                  onChange={(e) => setSeuil(e.target.value)} required />
                <span className="text-xs text-slate-500">échecs (puis à chaque multiple)</span>
              </div>
              <div className="w-44">
                <Input label="Durée du blocage" type="number" min={1} max={1440} value={minutes}
                  onChange={(e) => setMinutes(e.target.value)} required />
                <span className="text-xs text-slate-500">minutes</span>
              </div>
              <div className="w-44">
                <Input label="Blocage définitif après" type="number" min={0} max={1000} value={definitif}
                  onChange={(e) => setDefinitif(e.target.value)} required />
                <span className="text-xs text-slate-500">échecs (0 : jamais)</span>
              </div>
            </div>
            <p className="text-xs leading-relaxed text-slate-500">
              Un compte bloqué définitivement le reste jusqu'à ce qu'un syndic le débloque (ci-dessous) ou l'administrateur
              de l'instance.
            </p>
            <label className="flex items-start gap-2 text-slate-700">
              <input type="checkbox" className="mt-1" checked={avec2fa} onChange={(e) => setAvec2fa(e.target.checked)} />
              <span>
                Bloquer aussi les comptes qui ont la double authentification
                <span className="block text-xs text-slate-500">
                  Par défaut, non : leur mot de passe seul ne suffit pas à entrer, et le blocage permettrait à n'importe qui
                  de les empêcher de se connecter.
                </span>
              </span>
            </label>
          </div>
        )}

        <p className="text-xs leading-relaxed text-slate-500">
          Un compte rattaché à plusieurs copropriétés suit la règle la plus stricte. Les comptes de démonstration ne sont
          jamais bloqués.
        </p>
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={busy || !copro}>{busy ? "…" : "Enregistrer"}</Button>
          {message && <span className="text-emerald-700">{message}</span>}
          {error && <span className="text-red-700">{error}</span>}
        </div>
      </form>
    </Card>
  );
}

/** Réglages → Serveur (administrateur de l'instance) : comptes bloqués de toutes les copropriétés. */
export function ComptesBloquesCard() {
  const [comptes, setComptes] = useState<CompteBloque[] | null>(null);
  const [error, setError] = useState("");
  function charger() {
    api.get<CompteBloque[]>("/admin/comptes-bloques").then(setComptes).catch(() => {});
  }
  useEffect(charger, []);
  if (comptes === null) return null;

  async function debloquer(c: CompteBloque) {
    setError("");
    try {
      await api.post(`/auth/users/${c.id}/debloquer`);
      charger();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    }
  }

  return (
    <Card title="Comptes bloqués">
      <div className="space-y-3 text-sm">
        <p className="text-xs text-slate-500">
          Comptes bloqués après des échecs de connexion, dans toutes les copropriétés de l'instance. En dernier recours,
          depuis le serveur : <code>python -m app.cli.debloquer adresse@exemple.fr</code>.
        </p>
        {comptes.length === 0 ? (
          <p className="text-slate-500">Aucun compte bloqué.</p>
        ) : (
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
            {comptes.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                <span>
                  {[c.prenom, c.nom].filter(Boolean).join(" ") || c.email}{" "}
                  <span className="text-xs text-slate-500">{c.email}</span>
                  {c.coproprietes.length > 0 && (
                    <span className="block text-xs text-slate-500">{c.coproprietes.join(", ")}</span>
                  )}
                </span>
                <span className="flex items-center gap-2">
                  <BadgeBlocage u={c} />
                  <Button variant="secondary" onClick={() => debloquer(c)}>Débloquer</Button>
                </span>
              </li>
            ))}
          </ul>
        )}
        {error && <p className="text-xs text-red-600">{error}</p>}
      </div>
    </Card>
  );
}

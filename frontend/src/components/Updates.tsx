import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../api";
import { Badge, Button, Card, Input, Modal, Select } from "./ui";

export interface ReleaseInfo { version: string; published_at: string; url: string; notes: string }
export interface UpdateState {
  current: string;
  mode: "server" | "desktop";
  latest: ReleaseInfo | null;
  available: boolean;
  changes: ReleaseInfo[];
  check: { last_at: number; error: string };
  request: { version: string; at: number; by: string } | null;
  applier: { installed: boolean; seen_at: number; result: string; applied: string; applied_at: number; backup: string };
  settings: { check_interval_s: number; auto_apply: boolean };
}

const INTERVALLES: [number, string][] = [
  [3600, "Toutes les heures"], [21600, "Toutes les 6 heures"], [43200, "Toutes les 12 heures"],
  [86400, "Une fois par jour"], [0, "Jamais (désactivé)"],
];

const quand = (ts: number) => (ts ? new Date(ts * 1000).toLocaleString("fr-FR") : "jamais");
const jour = (iso: string) => (iso ? new Date(iso).toLocaleDateString("fr-FR") : "");

/** Version installée (pied de la barre latérale). Publique : aucune connexion requise. */
export function VersionTag() {
  const [v, setV] = useState("");
  useEffect(() => { api.get<{ version: string }>("/version").then((r) => setV(r.version)).catch(() => {}); }, []);
  return v ? <p className="mt-2 text-[11px] text-slate-400">Proprietas {v}</p> : null;
}

/** Hook commun : l'utilisateur est-il administrateur de l'instance ? Si oui, état des mises à jour. */
function useUpdates() {
  const [admin, setAdmin] = useState(false);
  const [st, setSt] = useState<UpdateState | null>(null);
  useEffect(() => {
    api.get<{ instance_admin: boolean }>("/updates/me").then((r) => {
      setAdmin(r.instance_admin);
      if (r.instance_admin) api.get<UpdateState>("/admin/updates").then(setSt).catch(() => {});
    }).catch(() => {});
  }, []);
  return { admin, st, setSt };
}

/** Bandeau en haut de page, visible des seuls administrateurs de l'instance. */
export function UpdatesBanner() {
  const { st } = useUpdates();
  if (!st?.available || !st.latest) return null;
  return (
    <div className="border-b border-indigo-200 bg-indigo-50 px-8 py-2 text-sm text-indigo-800">
      🆕 Proprietas {st.latest.version} est disponible (installée : {st.current}).{" "}
      <NavLink to="/settings" className="font-medium underline hover:text-indigo-900">
        Réglages → Mises à jour
      </NavLink>
    </div>
  );
}

/** Panneau « Mises à jour » de la page Réglages. */
export function UpdatesCard() {
  const { admin, st, setSt } = useUpdates();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showChanges, setShowChanges] = useState(false);
  if (!admin || !st) return null;

  async function call(fn: () => Promise<UpdateState>) {
    setBusy(true); setError("");
    try { setSt(await fn()); } catch (e) { setError(e instanceof Error ? e.message : "Erreur"); }
    finally { setBusy(false); }
  }
  const reglages = (v: Partial<UpdateState["settings"]>) => call(() => api.put<UpdateState>("/admin/updates/settings", v));
  const applicateurActif = st.applier.installed && Date.now() / 1000 - st.applier.seen_at < 180;

  return (
    <Card title="Mises à jour" action={
      <Button variant="secondary" disabled={busy} onClick={() => call(() => api.post<UpdateState>("/admin/updates/check"))}>
        Vérifier maintenant
      </Button>
    }>
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span>Version installée : <b>{st.current}</b></span>
          {st.available && st.latest
            ? <Badge color="indigo">{st.latest.version} disponible</Badge>
            : st.latest && <Badge color="green">à jour</Badge>}
        </div>
        <p className="text-xs text-slate-500">
          Dernière vérification : {quand(st.check.last_at)}
          {st.check.error && <span className="block text-red-600">Échec : {st.check.error}</span>}
        </p>

        {st.available && (
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => setShowChanges(true)}>
              Voir les changements ({st.changes.length} version{st.changes.length > 1 ? "s" : ""})
            </Button>
            {st.mode === "server" && !st.request && (
              <Button disabled={busy || !applicateurActif}
                onClick={() => call(() => api.post<UpdateState>("/admin/updates/apply"))}>
                Mettre à jour vers {st.latest?.version}
              </Button>
            )}
            {st.mode === "desktop" && st.latest && (
              <a href={st.latest.url} target="_blank" rel="noreferrer"
                className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700">
                Télécharger {st.latest.version}
              </a>
            )}
          </div>
        )}

        {st.request && (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Mise à jour vers <b>{st.request.version}</b> demandée par {st.request.by} le {quand(st.request.at)} :
            l'applicateur du serveur va sauvegarder la base puis redémarrer l'application (quelques minutes).{" "}
            <button className="font-medium underline" disabled={busy}
              onClick={() => call(() => api.del<UpdateState>("/admin/updates/request"))}>Annuler</button>
          </p>
        )}

        {st.mode === "server" && (
          <p className="text-xs text-slate-500">
            Applicateur du serveur :{" "}
            {applicateurActif
              ? <span className="text-emerald-600">actif</span>
              : <span className="text-red-600">{st.applier.installed ? `inactif depuis ${quand(st.applier.seen_at)}` : "non installé (voir README, section Mises à jour)"}</span>}
            {st.applier.result && <> · dernier résultat : {st.applier.result}</>}
            {st.applier.applied && <> ({st.applier.applied}, {quand(st.applier.applied_at)})</>}
            {st.applier.backup && <span className="block">Dernière sauvegarde : {st.applier.backup}</span>}
          </p>
        )}

        <div className="grid gap-3 border-t border-slate-100 pt-3 sm:grid-cols-2">
          <Select label="Vérification automatique" value={st.settings.check_interval_s} disabled={busy}
            onChange={(e) => reglages({ check_interval_s: Number(e.target.value) })}>
            {INTERVALLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </Select>
          {st.mode === "server" && (
            <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-600">
              <input type="checkbox" checked={st.settings.auto_apply} disabled={busy}
                onChange={(e) => reglages({ auto_apply: e.target.checked })} />
              Appliquer automatiquement les nouvelles versions (sauvegarde de la base avant chaque mise à jour)
            </label>
          )}
        </div>
        {error && <p className="text-xs text-red-600">{error}</p>}
      </div>

      <Modal open={showChanges} wide title={`Changements depuis ${st.current}`} onClose={() => setShowChanges(false)}>
        <div className="space-y-5">
          {st.changes.map((r) => (
            <div key={r.version}>
              <p className="text-sm font-semibold text-slate-800">
                {r.version} <span className="font-normal text-slate-500">· {jour(r.published_at)}</span>{" "}
                {r.url && <a href={r.url} target="_blank" rel="noreferrer" className="text-xs text-indigo-600 underline">sur GitHub</a>}
              </p>
              <pre className="mt-1 whitespace-pre-wrap font-sans text-xs text-slate-600">{r.notes || "(pas de notes)"}</pre>
            </div>
          ))}
        </div>
      </Modal>
    </Card>
  );
}

interface InstanceAdmin { id: number; email: string; prenom: string; nom: string }

/** Panneau « Administrateurs de l'instance » (Réglages) : qui peut piloter les mises à jour.
 *  Mode serveur uniquement ; en version de bureau, le syndic local est l'administrateur. */
export function InstanceAdminsCard({ myId }: { myId?: number }) {
  const { admin, st } = useUpdates();
  const [admins, setAdmins] = useState<InstanceAdmin[]>([]);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (admin && st?.mode === "server")
      api.get<InstanceAdmin[]>("/admin/instance-admins").then(setAdmins).catch(() => {});
  }, [admin, st?.mode]);
  if (!admin || st?.mode !== "server") return null;

  async function call(fn: () => Promise<InstanceAdmin[]>) {
    setBusy(true); setError("");
    try { setAdmins(await fn()); setEmail(""); } catch (e) { setError(e instanceof Error ? e.message : "Erreur"); }
    finally { setBusy(false); }
  }

  return (
    <Card title="Administrateurs de l'instance">
      <div className="space-y-3 text-sm">
        <p className="text-xs text-slate-500">
          Ils pilotent les mises à jour de l'application, pour toutes les copropriétés de cette instance.
          C'est distinct du rôle de syndic.
        </p>
        <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200">
          {admins.map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-2 px-3 py-2">
              <span>
                {[a.prenom, a.nom].filter(Boolean).join(" ") || a.email}{" "}
                <span className="text-xs text-slate-500">{a.email}</span>
                {a.id === myId && <span className="ml-1 text-xs text-slate-400">(vous)</span>}
              </span>
              {a.id !== myId && (
                <button className="text-xs font-medium text-red-600 underline disabled:opacity-50" disabled={busy}
                  onClick={() => call(() => api.del<InstanceAdmin[]>(`/admin/instance-admins/${a.id}`))}>
                  Retirer
                </button>
              )}
            </li>
          ))}
        </ul>
        <form className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => { e.preventDefault(); if (email.trim()) call(() => api.post<InstanceAdmin[]>("/admin/instance-admins", { email })); }}>
          <div className="min-w-[16rem] flex-1">
            <Input label="Ajouter un administrateur (e-mail d'un compte existant)" type="email" value={email}
              onChange={(e) => setEmail(e.target.value)} placeholder="prenom.nom@exemple.fr" />
          </div>
          <Button type="submit" disabled={busy || !email.trim()}>Ajouter</Button>
        </form>
        {error && <p className="text-xs text-red-600">{error}</p>}
      </div>
    </Card>
  );
}

import { useEffect, useState } from "react";
import { api, clearToken, getToken } from "../api";
import { useUser } from "../auth";
import { Badge, Button, Card, Empty, Input, Select } from "../components/ui";
import TwoFactorWizard from "../components/TwoFactorWizard";
import type { AuditEntry, Copro, DiagnosticItem, InstanceOut, TwoFactorStatus, User } from "../types";

const LIBELLES_ACTIONS: Record<string, string> = {
  login: "Connexion",
  login_failed: "Échec de connexion",
  "2fa_enabled": "Double authentification activée",
  "2fa_disabled": "Double authentification désactivée",
  "2fa_reset": "Réinitialisation 2FA (par le syndic)",
  "2fa_recovery_used": "Code de secours utilisé",
  "2fa_codes_regenerated": "Codes de secours régénérés",
  user_created: "Compte créé",
  user_updated: "Compte modifié",
  user_deleted: "Compte supprimé",
  copro_created: "Copropriété créée",
  instance_updated: "Profil d'accès mis à jour",
  diagnostic_run: "Diagnostic d'exposition lancé",
  sessions_revoked: "Sessions révoquées (déconnexion globale)",
  recouvrement_acte: "Acte de recouvrement enregistré",
  recouvrement_19_2: "Article 19-2 activé (exigibilité immédiate)",
  recouvrement_acte_supprime: "Acte de recouvrement supprimé",
  relance_envoyee: "Relance envoyée",
  situation_fonds: "Situation du fonds envoyée",
  export_rapport_annuel: "Export rapport annuel",
  export_compte_gestion: "Export compte de gestion",
  export_quittances: "Export quittances",
  export_csv: "Export CSV (grand livre)",
  export_registre: "Export registre",
};

const MODES = [
  { value: "local", label: "Réseau local uniquement (ou ordinateur personnel)" },
  { value: "vps", label: "Sur un serveur (VPS), accessible depuis internet" },
  { value: "maison", label: "Chez moi, exposée depuis ma connexion" },
];

const ICONES_STATUT: Record<string, string> = {
  ok: "✅",
  attention: "⚠️",
  echec: "❌",
  ignore: "➖",
};

export default function Securite() {
  const { user: me } = useUser();
  const isSyndic = me?.role === "syndic";

  const [statut, setStatut] = useState<TwoFactorStatus | null>(null);
  const [copro, setCopro] = useState<Copro | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [auditFini, setAuditFini] = useState(false);
  const [wizard, setWizard] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  // Formulaires « désactiver » / « régénérer les codes »
  const [montreDesactiver, setMontreDesactiver] = useState(false);
  const [montreRegenerer, setMontreRegenerer] = useState(false);
  const [pwd, setPwd] = useState("");
  const [code, setCode] = useState("");
  const [nouveauxCodes, setNouveauxCodes] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);

  // Accès depuis internet (syndic)
  const [inst, setInst] = useState<InstanceOut | null>(null);
  const [mode, setMode] = useState("local");
  const [urlPublique, setUrlPublique] = useState("");
  const [instBusy, setInstBusy] = useState(false);
  const [diagBusy, setDiagBusy] = useState(false);
  const [revokeBusy, setRevokeBusy] = useState(false);

  function flash(msg: string) {
    setMessage(msg);
    setError("");
  }

  function chargerStatut() {
    api.get<TwoFactorStatus>("/auth/2fa/status").then(setStatut).catch(() => {});
  }

  function chargerUsers() {
    api.get<User[]>("/auth/users").then(setUsers).catch(() => {});
  }

  function chargerAudit(offset = 0) {
    api.get<AuditEntry[]>(`/audit?limit=50&offset=${offset}`).then((rows) => {
      setAudit((prev) => (offset === 0 ? rows : [...prev, ...rows]));
      setAuditFini(rows.length < 50);
    }).catch(() => {});
  }

  function chargerInstance() {
    api.get<InstanceOut>("/instance").then((i) => {
      setInst(i);
      setMode(i.mode);
      setUrlPublique(i.public_url);
    }).catch(() => {});
  }

  useEffect(() => {
    chargerStatut();
    api.get<Copro>("/copro").then(setCopro).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!isSyndic) return;
    chargerUsers();
    chargerAudit(0);
    chargerInstance();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSyndic]);

  function resetFormulaires() {
    setPwd("");
    setCode("");
    setMontreDesactiver(false);
    setMontreRegenerer(false);
  }

  function apresChangement() {
    chargerStatut();
    if (isSyndic) chargerAudit(0);
  }

  async function desactiver(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.post("/auth/2fa/disable", { password: pwd, code });
      resetFormulaires();
      flash("Double authentification désactivée.");
      apresChangement();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    } finally {
      setBusy(false);
    }
  }

  async function regenerer(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api.post<{ recovery_codes: string[] }>("/auth/2fa/recovery-codes", {
        password: pwd,
        code,
      });
      resetFormulaires();
      setNouveauxCodes(res.recovery_codes);
      flash("Nouveaux codes de secours générés.");
      apresChangement();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    } finally {
      setBusy(false);
    }
  }

  async function changerPolitique(valeur: string) {
    setMessage("");
    setError("");
    try {
      const maj = await api.put<Copro>("/copro", { totp_policy: valeur });
      setCopro(maj);
      flash("Politique de double authentification enregistrée.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    }
  }

  async function resetUser(u: User) {
    if (
      !confirm(
        `Réinitialiser la double authentification de ${u.email} ?\n\n` +
          "Le compte devra la réactiver à sa prochaine connexion (téléphone perdu)."
      )
    )
      return;
    try {
      await api.post(`/auth/users/${u.id}/2fa/reset`);
      flash(`Double authentification de ${u.email} réinitialisée.`);
      chargerUsers();
      chargerAudit(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    }
  }

  async function revoquerSessions() {
    const suffixe = statut?.enabled
      ? " Vous vous reconnecterez avec votre mot de passe et votre code de double authentification."
      : " Vous vous reconnecterez avec votre mot de passe.";
    if (
      !confirm(
        "Déconnecter TOUS vos appareils ?\n\n" +
          "Toutes vos sessions actives seront fermées, y compris celle-ci." + suffixe
      )
    )
      return;
    setRevokeBusy(true);
    setError("");
    try {
      await api.post("/auth/logout-all");
      await api.post("/auth/logout").catch(() => {});
      clearToken(); // nettoyage d'un éventuel jeton hérité
      window.location.href = "/login";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
      setRevokeBusy(false);
    }
  }

  async function sauverInstance() {
    setInstBusy(true);
    setMessage("");
    setError("");
    try {
      const maj = await api.put<InstanceOut>("/instance", { mode, public_url: urlPublique });
      setInst(maj);
      flash("Profil d'accès enregistré.");
      if (isSyndic) chargerAudit(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    } finally {
      setInstBusy(false);
    }
  }

  async function lancerDiagnostic() {
    setDiagBusy(true);
    setMessage("");
    setError("");
    try {
      await api.post<{ checked_at: string; results: DiagnosticItem[] }>("/instance/diagnostic");
      chargerInstance();
      flash("Diagnostic terminé.");
      if (isSyndic) chargerAudit(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    } finally {
      setDiagBusy(false);
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-lg font-bold text-slate-800">Sécurité</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Double authentification, comptes et journal d'activité de la copropriété.
        </p>
      </div>

      {message && <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{message}</p>}
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <Card title="Ma double authentification (2FA)">
        {wizard ? (
          <TwoFactorWizard
            token={getToken() ?? ""}
            intro={`Activez la double authentification pour le compte ${me?.email ?? ""} avec une application d'authentification (FreeOTP, Aegis, Google Authenticator…).`}
            onDone={() => {
              setWizard(false);
              flash("Double authentification activée. Conservez vos codes de secours en lieu sûr.");
              apresChangement();
            }}
            onCancel={() => setWizard(false)}
          />
        ) : !statut ? (
          <p className="text-sm text-slate-500">…</p>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-3 text-sm">
              <span className="text-slate-600">État :</span>
              {statut.enabled ? (
                <Badge color="green">Activée — codes de secours restants : {statut.recovery_codes_left}</Badge>
              ) : statut.required ? (
                <Badge color="amber">Exigée pour votre compte — à activer</Badge>
              ) : (
                <Badge color="slate">Non activée</Badge>
              )}
            </div>
            <p className="text-sm leading-relaxed text-slate-600">
              La double authentification ajoute un code à 6 chiffres (application FreeOTP, Aegis, Google
              Authenticator…) en plus du mot de passe, à chaque connexion. Fortement recommandée dès que
              l'application est accessible depuis internet.
            </p>

            {statut.enabled ? (
              <>
                {nouveauxCodes ? (
                  <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3">
                    <p className="text-sm text-amber-800">
                      Nouveaux codes de secours — notez-les maintenant, ils ne seront plus affichés :
                    </p>
                    <div className="grid grid-cols-2 gap-1.5 font-mono text-sm text-slate-800">
                      {nouveauxCodes.map((c) => (
                        <span key={c} className="select-all">
                          {c}
                        </span>
                      ))}
                    </div>
                    <Button variant="secondary" onClick={() => setNouveauxCodes(null)}>
                      J'ai noté mes codes
                    </Button>
                  </div>
                ) : montreRegenerer || montreDesactiver ? (
                  <form onSubmit={montreRegenerer ? regenerer : desactiver} className="space-y-3">
                    <div className="flex flex-wrap gap-3">
                      <div className="w-56">
                        <Input
                          label="Mot de passe"
                          type="password"
                          value={pwd}
                          onChange={(e) => setPwd(e.target.value)}
                          required
                          autoFocus
                        />
                      </div>
                      <div className="w-56">
                        <Input
                          label="Code actuel (application)"
                          value={code}
                          onChange={(e) => setCode(e.target.value)}
                          required
                          placeholder="123456"
                        />
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <Button type="submit" variant={montreDesactiver ? "danger" : "primary"} disabled={busy}>
                        {montreRegenerer ? "Régénérer les codes" : "Désactiver la 2FA"}
                      </Button>
                      <Button type="button" variant="secondary" onClick={resetFormulaires}>
                        Annuler
                      </Button>
                    </div>
                  </form>
                ) : (
                  <div className="flex gap-2">
                    <Button variant="secondary" onClick={() => setMontreRegenerer(true)}>
                      Régénérer les codes de secours
                    </Button>
                    <Button variant="secondary" onClick={() => setMontreDesactiver(true)}>
                      Désactiver
                    </Button>
                  </div>
                )}
              </>
            ) : (
              <Button onClick={() => setWizard(true)}>Activer la double authentification</Button>
            )}

            {statut.required && (
              <p className="text-xs text-amber-700">
                {statut.enabled
                  ? "Cette copropriété exige la double authentification pour votre rôle : ne la désactivez qu'en cas de nécessité."
                  : "D'après la politique de votre copropriété, vous serez invité à l'activer lors de votre prochaine connexion."}
              </p>
            )}
          </div>
        )}
      </Card>

      <Card title="Sessions et appareils">
        <div className="space-y-3">
          <p className="text-sm leading-relaxed text-slate-600">
            Si vous perdez un appareil ou doutez de sa sécurité, cette action ferme immédiatement
            toutes vos sessions, sur tous vos appareils (y compris celle-ci).
          </p>
          <Button variant="secondary" onClick={revoquerSessions} disabled={revokeBusy}>
            {revokeBusy ? "…" : "Déconnecter tous mes appareils"}
          </Button>
        </div>
      </Card>

      {isSyndic && (
        <>
          <Card title="Accès depuis internet">
            <div className="space-y-4">
              {inst?.exposed_unprotected && (
                <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
                  ⚠️ Cette application est joignable depuis internet (première requête externe
                  le{" "}
                  {inst.first_external_at
                    ? new Date(inst.first_external_at).toLocaleString("fr-FR")
                    : "—"}
                  ) mais elle n'est pas déclarée comme exposée. Vérifiez la configuration ci-dessous.
                </p>
              )}
              <div className="space-y-1.5 text-sm">
                <p className="font-medium text-slate-600">Où est installée cette application ?</p>
                {MODES.map((m) => (
                  <label key={m.value} className="flex items-center gap-2 text-slate-600">
                    <input
                      type="radio"
                      name="mode-instance"
                      value={m.value}
                      checked={mode === m.value}
                      onChange={() => setMode(m.value)}
                    />
                    {m.label}
                  </label>
                ))}
              </div>

              {mode !== "local" && (
                <>
                  <Input
                    label="Adresse publique (URL)"
                    value={urlPublique}
                    onChange={(e) => setUrlPublique(e.target.value)}
                    placeholder="https://copro.exemple.fr"
                  />
                  <div className="space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
                    <p className="font-medium text-slate-700">
                      {mode === "vps" ? "Sur un serveur (VPS) :" : "Depuis chez vous :"}
                    </p>
                    <p>
                      1. Pointez votre domaine vers{" "}
                      {mode === "vps"
                        ? "ce serveur"
                        : "votre connexion — ou utilisez un tunnel, recommandé"},
                      {" "}(record DNS de type A).
                    </p>
                    <p>2. Activez le profil internet (proxy TLS automatique) :</p>
                    <CommandeCopiable texte="docker compose --profile internet up -d --build" />
                    <p className="text-xs leading-relaxed text-slate-500">
                      3. Renseignez l'URL ci-dessus, enregistrez, puis lancez le diagnostic.
                    </p>
                    {mode === "maison" && (
                      <p className="text-xs leading-relaxed text-slate-500">
                        Hébergement maison : préférez un tunnel (Cloudflare Tunnel, Tailscale) à
                        l'ouverture de ports sur votre box — voir « Hébergement maison » dans le README.
                      </p>
                    )}
                  </div>
                </>
              )}

              <div className="flex flex-wrap gap-2">
                <Button onClick={sauverInstance} disabled={instBusy || !inst}>
                  {instBusy ? "…" : "Enregistrer"}
                </Button>
                <Button
                  variant="secondary"
                  onClick={lancerDiagnostic}
                  disabled={diagBusy || !inst || mode === "local"}
                >
                  {diagBusy ? "Diagnostic en cours… (≈ 30 s)" : "Lancer le diagnostic"}
                </Button>
              </div>

              {inst?.last_check && inst.last_check.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-xs text-slate-500">
                    Dernier diagnostic :{" "}
                    {inst.last_check_at ? new Date(inst.last_check_at).toLocaleString("fr-FR") : ""}
                  </p>
                  {inst.last_check.map((it) => (
                    <div key={it.id} className="flex flex-wrap items-baseline gap-x-2 text-sm">
                      <span aria-hidden="true">{ICONES_STATUT[it.statut] ?? "➖"}</span>
                      <span className="font-medium text-slate-700">{it.label}</span>
                      {it.detail && <span className="text-slate-500">— {it.detail}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Card>

          <Card title="Politique de double authentification">
            <div className="space-y-3">
              <Select
                label="Exigence pour cette copropriété"
                value={copro?.totp_policy ?? "off"}
                onChange={(e) => changerPolitique(e.target.value)}
                disabled={!copro}
              >
                <option value="off">Désactivée pour tout le monde</option>
                <option value="syndic">Obligatoire pour le syndic</option>
                <option value="all">Obligatoire pour tous les comptes</option>
              </Select>
              <p className="text-sm leading-relaxed text-slate-600">
                « Obligatoire » signifie que le compte devra activer la 2FA à sa prochaine connexion —
                chaque personne garde la maîtrise de son enrôlement, rien n'est imposé à son insu. Les
                comptes de démonstration sont toujours exemptés.
              </p>
            </div>
          </Card>

          <Card title="Comptes et double authentification">
            {users.length === 0 ? (
              <Empty text="Aucun compte pour cette copropriété." />
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="pb-2">Compte</th>
                    <th className="pb-2">Rôle</th>
                    <th className="pb-2">2FA</th>
                    <th className="pb-2"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {users.map((u) => (
                    <tr key={u.id}>
                      <td className="py-2.5">
                        <p className="font-medium text-slate-800">{u.nom}</p>
                        <p className="text-xs text-slate-500">{u.email}</p>
                      </td>
                      <td className="py-2.5 text-slate-600">
                        {u.role === "syndic" ? "Syndic" : "Copropriétaire"}
                      </td>
                      <td className="py-2.5">
                        {u.two_factor_enabled ? (
                          <Badge color="green">Activée</Badge>
                        ) : (
                          <Badge color="slate">Non</Badge>
                        )}
                      </td>
                      <td className="py-2.5 text-right">
                        {u.two_factor_enabled && u.id !== me?.id && (
                          <Button variant="ghost" onClick={() => resetUser(u)}>
                            Réinitialiser
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="mt-3 text-xs leading-relaxed text-slate-500">
              « Réinitialiser » : le compte devra réactiver sa 2FA à la prochaine connexion (utile si la
              personne a perdu son téléphone). L'opération est tracée dans le journal et notifiée par email.
            </p>
          </Card>

          <Card title="Journal d'audit">
            {audit.length === 0 ? (
              <Empty text="Aucune activité enregistrée pour cette copropriété." />
            ) : (
              <div className="space-y-1.5">
                {audit.map((e) => (
                  <div
                    key={e.id}
                    className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b border-slate-50 pb-1.5 text-sm last:border-0"
                  >
                    <span className="w-36 shrink-0 text-xs tabular-nums text-slate-500">
                      {new Date(e.created_at).toLocaleString("fr-FR")}
                    </span>
                    <span className="font-medium text-slate-700">{LIBELLES_ACTIONS[e.action] ?? e.action}</span>
                    <span className="text-slate-500">
                      {e.user_email}
                      {e.detail ? ` — ${e.detail}` : ""}
                    </span>
                    {e.ip && <span className="ml-auto text-xs text-slate-400">{e.ip}</span>}
                  </div>
                ))}
                {!auditFini && (
                  <div className="pt-2">
                    <Button variant="secondary" onClick={() => chargerAudit(audit.length)}>
                      Afficher plus
                    </Button>
                  </div>
                )}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

function CommandeCopiable({ texte }: { texte: string }) {
  const [copie, setCopie] = useState(false);
  return (
    <div className="flex items-center gap-2 rounded-lg bg-slate-900 px-3 py-2">
      <code className="flex-1 overflow-x-auto whitespace-nowrap text-xs text-slate-100">{texte}</code>
      <button
        type="button"
        className="shrink-0 text-xs font-medium text-slate-300 hover:text-white"
        onClick={() => {
          navigator.clipboard?.writeText(texte);
          setCopie(true);
          setTimeout(() => setCopie(false), 1500);
        }}
      >
        {copie ? "✓ copié" : "copier"}
      </button>
    </div>
  );
}

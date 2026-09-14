import { useEffect, useState } from "react";
import { api } from "../api";
import { useUser } from "../auth";
import type { Copro, Personne, User } from "../types";
import { Button, Card, Input, Modal, Select, Badge } from "../components/ui";
import { applyTheme, getStoredTheme, normalizeTheme, type Theme } from "../theme";

export default function Settings() {
  const { user: me } = useUser();
  const isSyndic = me?.role === "syndic";
  const [copro, setCopro] = useState<Copro | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [personnes, setPersonnes] = useState<Personne[]>([]);
  // null = fermé ; { } = création ; { user } = édition de la fiche
  const [modal, setModal] = useState<null | { user?: User }>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [smtpTest, setSmtpTest] = useState<{ ok: boolean; detail: string } | null>(null);
  const [smtpBusy, setSmtpBusy] = useState(false);
  // Nouveau mot de passe SMTP (le mot de passe actuel n'est jamais renvoyé par le backend)
  const [smtpPassword, setSmtpPassword] = useState("");
  const [prochaineDate, setProchaineDate] = useState<string | null>(null);
  // Thème d'affichage (préférence personnelle, conservée sur le compte)
  const [choixTheme, setChoixTheme] = useState<Theme>(getStoredTheme());
  useEffect(() => {
    if (me?.theme) setChoixTheme(normalizeTheme(me.theme));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me?.theme]);

  async function loadComptes() {
    const [u, p] = await Promise.all([api.get<User[]>("/auth/users"), api.get<Personne[]>("/personnes")]);
    setUsers(u);
    setPersonnes(p);
  }

  async function supprimerCompte(u: User) {
    if (!confirm(`Supprimer le compte de ${u.email} ? (tracé dans le journal d'audit)`)) return;
    try {
      await api.del(`/auth/users/${u.id}`);
      await loadComptes();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    }
  }

  function changerTheme(t: Theme) {
    setChoixTheme(t);
    applyTheme(t);
    api.post("/auth/theme", { theme: t }).catch(() => {});
  }

  useEffect(() => {
    api.get<Copro>("/copro").then((c) => {
      setCopro(c);
      if (c.relance_auto) {
        api.get<{ prochaine: string | null }>("/relances/prochaine").then((r) => setProchaineDate(r.prochaine ? new Date(r.prochaine).toLocaleString("fr-FR", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }) : null)).catch(() => {});
      }
    }).catch(() => {});
    loadComptes().catch(() => {});
  }, []);

  async function saveCopro() {
    if (!copro) return;
    setSaved(false);
    setError("");
    try {
      const updated = await api.put<Copro>("/copro", {
        nom: copro.nom, adresse: copro.adresse, ville: copro.ville,
        code_postal: copro.code_postal, annee_construction: copro.annee_construction,
        fonds_travaux_actif: copro.fonds_travaux_actif,
        fonds_travaux_taux_pct: copro.fonds_travaux_taux_pct,
        fonds_travaux_compte: copro.fonds_travaux_compte,
        compte_bancaire_separe: copro.compte_bancaire_separe,
        notes: copro.notes,
      });
      setCopro(updated);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    }
  }

  async function saveRelanceAuto() {
    if (!copro) return;
    setSaved(false);
    setError("");
    try {
      const updated = await api.put<Copro>("/copro", {
        relance_auto: copro.relance_auto,
        relance_frequence: copro.relance_frequence,
        relance_jour: copro.relance_jour,
        relance_heure: copro.relance_heure,
        relance_minimum: copro.relance_minimum,
      });
      setCopro(updated);
      setSaved(true);
      const r = await api.get<{ prochaine: string | null }>("/relances/prochaine");
      setProchaineDate(r.prochaine ? new Date(r.prochaine).toLocaleString("fr-FR", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }) : null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    }
  }

  async function saveSmtp() {
    if (!copro) return;
    setSaved(false);
    setError("");
    try {
      const payload: Record<string, unknown> = {
        smtp_host: copro.smtp_host, smtp_port: copro.smtp_port,
        smtp_user: copro.smtp_user,
        email_expediteur: copro.email_expediteur, frontend_url: copro.frontend_url,
      };
      // Le mot de passe n'est jamais renvoyé par le backend : champ « nouveau
      // mot de passe » — vide = conserver l'existant.
      if (smtpPassword.trim()) payload.smtp_password = smtpPassword.trim();
      await api.put("/smtp/config", payload);
      setSmtpPassword("");
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    }
  }

  async function testSmtp() {
    if (!copro) return;
    setSmtpBusy(true);
    setSmtpTest(null);
    try {
      const payload: Record<string, unknown> = {
        smtp_host: copro.smtp_host, smtp_port: copro.smtp_port,
        smtp_user: copro.smtp_user,
        email_expediteur: copro.email_expediteur, frontend_url: copro.frontend_url,
      };
      if (smtpPassword.trim()) payload.smtp_password = smtpPassword.trim();
      const res = await api.post<{ ok: boolean; detail: string }>("/smtp/test", payload);
      setSmtpTest(res);
    } catch (e) {
      setSmtpTest({ ok: false, detail: e instanceof Error ? e.message : "Erreur" });
    } finally {
      setSmtpBusy(false);
    }
  }

  if (!copro) return null;

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-800">Réglages</h1>
        <p className="text-sm text-slate-500">Copropriété, fonds de travaux et comptes utilisateurs</p>
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {saved && <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">Modifications enregistrées ✓</p>}

      <Card title="Apparence">
        <div className="flex flex-wrap gap-2">
          {[
            ["system", "Système"],
            ["light", "Clair"],
            ["dark", "Sombre"],
          ].map(([value, label]) => (
            <Button
              key={value}
              variant={choixTheme === value ? "primary" : "secondary"}
              onClick={() => changerTheme(value as Theme)}
            >
              {label}
            </Button>
          ))}
        </div>
        <p className="mt-2 text-xs text-slate-500">
          « Système » suit le réglage clair / sombre de l'appareil. La préférence est conservée sur votre compte.
        </p>
      </Card>

      <Card title="Copropriété">
        <div className="space-y-3">
          <Input label="Nom" value={copro.nom} onChange={(e) => setCopro({ ...copro, nom: e.target.value })} />
          <Input label="Adresse" value={copro.adresse} onChange={(e) => setCopro({ ...copro, adresse: e.target.value })} />
          <div className="grid grid-cols-3 gap-3">
            <Input label="Code postal" value={copro.code_postal} onChange={(e) => setCopro({ ...copro, code_postal: e.target.value })} />
            <Input label="Ville" className="col-span-2" value={copro.ville} onChange={(e) => setCopro({ ...copro, ville: e.target.value })} />
          </div>
          <Input
            label="Année de construction"
            type="number"
            value={copro.annee_construction ?? ""}
            onChange={(e) => setCopro({ ...copro, annee_construction: e.target.value ? Number(e.target.value) : null })}
          />
          <Input label="Compte bancaire séparé (syndicat)" value={copro.compte_bancaire_separe} onChange={(e) => setCopro({ ...copro, compte_bancaire_separe: e.target.value })} placeholder="IBAN / référence" />
          {isSyndic && <Button onClick={saveCopro}>Enregistrer</Button>}
        </div>
      </Card>

      <Card title="Fonds de travaux">
        <div className="space-y-3">
          <p className="rounded-lg bg-indigo-50 px-3 py-2 text-xs leading-relaxed text-indigo-800">
            <b>Obligation légale (France)</b> : fonds de travaux obligatoire dès 10 ans après réception des travaux,
            quel que soit le nombre de lots. Cotisation annuelle minimale : 5 % du budget prévisionnel
            (ou 2,5 % du plan pluriannuel de travaux + 5 % du budget si PPT voté). Versement sur compte séparé,
            montant voté chaque année en AG.
          </p>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={copro.fonds_travaux_actif}
              onChange={(e) => setCopro({ ...copro, fonds_travaux_actif: e.target.checked })}
            />
            Fonds de travaux actif (inclus dans les appels de fonds)
          </label>
          <div className="grid grid-cols-2 gap-3">
            <Input
              label="Taux (%)"
              type="number"
              step="0.5"
              value={copro.fonds_travaux_taux_pct}
              onChange={(e) => setCopro({ ...copro, fonds_travaux_taux_pct: Number(e.target.value) })}
            />
            <Input label="Compte dédié" value={copro.fonds_travaux_compte} onChange={(e) => setCopro({ ...copro, fonds_travaux_compte: e.target.value })} placeholder="IBAN / référence" />
          </div>
          {isSyndic && <Button onClick={saveCopro}>Enregistrer</Button>}
        </div>
      </Card>

      <Card title="Envoi des emails (convocations AG)">
        <div className="space-y-3">
          <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
            Utilisé pour envoyer les convocations aux assemblées générales. Exemples : Gmail
            (<code className="text-slate-700">smtp.gmail.com:587</code> + mot de passe d'application), votre hébergeur,
            ou un serveur mailcow.
          </p>
          <div className="grid grid-cols-3 gap-3">
            <Input label="Serveur SMTP" value={copro.smtp_host} onChange={(e) => setCopro({ ...copro, smtp_host: e.target.value })} placeholder="smtp.example.fr" className="col-span-2" />
            <Input label="Port" type="number" value={copro.smtp_port} onChange={(e) => setCopro({ ...copro, smtp_port: Number(e.target.value) })} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Utilisateur" value={copro.smtp_user} onChange={(e) => setCopro({ ...copro, smtp_user: e.target.value })} placeholder="compte@example.fr" />
            <Input label="Nouveau mot de passe" type="password" value={smtpPassword} onChange={(e) => setSmtpPassword(e.target.value)} placeholder="Laisser vide pour conserver" autoComplete="new-password" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Input label="Expéditeur" value={copro.email_expediteur} onChange={(e) => setCopro({ ...copro, email_expediteur: e.target.value })} placeholder="syndic@votre-domaine.fr" />
            <Input label="Adresse publique de l'app" value={copro.frontend_url} onChange={(e) => setCopro({ ...copro, frontend_url: e.target.value })} placeholder="https://proprietas.cloudfr.net" />
          </div>
          {isSyndic && (
            <div className="flex gap-2">
              <Button onClick={saveSmtp}>Enregistrer la configuration</Button>
              <Button variant="secondary" onClick={testSmtp} disabled={smtpBusy}>
                {smtpBusy ? "Envoi…" : "Envoyer un email de test"}
              </Button>
            </div>
          )}
          {smtpTest && (
            <p className={`rounded-lg px-3 py-2 text-sm ${smtpTest.ok ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
              {smtpTest.ok ? "✓ " : "✗ "}{smtpTest.detail}
            </p>
          )}
        </div>
      </Card>

      <Card title="Relances automatiques (cron)">
        <div className="space-y-3">
          <p className="rounded-lg bg-indigo-50 px-3 py-2 text-xs leading-relaxed text-indigo-800">
            Le serveur envoie tout seul les relances aux lots en retard, à la fréquence choisie.
            Un lot n'est relancé que s'il est en retard <b>et</b> n'a pas déjà été relancé depuis
            la dernière période. Il faut configurer l'envoi des emails (SMTP) ci-dessus.
          </p>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={copro.relance_auto}
              onChange={(e) => setCopro({ ...copro, relance_auto: e.target.checked })}
            />
            Activer les relances automatiques
          </label>
          <div className="grid grid-cols-3 gap-3">
            <Select
              label="Fréquence"
              value={copro.relance_frequence}
              onChange={(e) => setCopro({ ...copro, relance_frequence: e.target.value })}
            >
              <option value="hebdo">Hebdomadaire</option>
              <option value="mensuel">Mensuelle</option>
            </Select>
            {copro.relance_frequence === "hebdo" ? (
              <Select label="Jour de la semaine" value={String(copro.relance_jour)} onChange={(e) => setCopro({ ...copro, relance_jour: Number(e.target.value) })}>
                <option value="1">Lundi</option>
                <option value="2">Mardi</option>
                <option value="3">Mercredi</option>
                <option value="4">Jeudi</option>
                <option value="5">Vendredi</option>
                <option value="6">Samedi</option>
                <option value="7">Dimanche</option>
              </Select>
            ) : (
              <Input
                label="Jour du mois (1-28)"
                type="number"
                min={1}
                max={28}
                value={copro.relance_jour}
                onChange={(e) => setCopro({ ...copro, relance_jour: Math.min(28, Math.max(1, Number(e.target.value) || 1)) })}
              />
            )}
            <Select
              label="Heure"
              value={copro.relance_heure}
              onChange={(e) => setCopro({ ...copro, relance_heure: e.target.value })}
            >
              {Array.from({ length: 24 }, (_, h) => [0, 30].map((m) => (
                <option key={`${h}-${m}`} value={`${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`}>
                  {`${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`}
                </option>
              )))}
            </Select>
          </div>
          <Input
            label="Seuil de relance (€) — ne relancer que si le solde dépasse ce montant"
            type="number"
            step="1"
            min={0}
            value={copro.relance_minimum}
            onChange={(e) => setCopro({ ...copro, relance_minimum: Number(e.target.value) || 0 })}
          />
          {prochaineDate && (
            <p className="text-xs text-slate-500">
              ⏰ Prochaine relance automatique : <b className="text-slate-700">{prochaineDate}</b>
            </p>
          )}
          {isSyndic && <Button onClick={saveRelanceAuto}>Enregistrer</Button>}
        </div>
      </Card>

      {me?.role === "syndic" && (
        <Card
          title="Comptes utilisateurs"
          action={<Button onClick={() => setModal({})}>+ Ajouter</Button>}
        >
          <div className="space-y-2">
            {users.map((u) => {
              const liee = personnes.find((p) => p.id === u.personne_id);
              return (
                <div key={u.id} className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-2">
                  <div>
                    <p className="text-sm font-medium text-slate-800">
                      {[u.prenom, u.nom].filter(Boolean).join(" ")}
                      {u.id === me?.id && <span className="ml-2 text-xs font-normal text-slate-500">(vous)</span>}
                    </p>
                    <p className="text-xs text-slate-500">
                      {u.email}
                      {liee && <span className="ml-2 text-slate-400">🔗 {[liee.prenom, liee.nom].filter(Boolean).join(" ")}</span>}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge color={u.role === "syndic" ? "indigo" : "slate"}>
                      {u.role === "syndic" ? "Syndic" : "Copropriétaire"}
                    </Badge>
                    <button
                      onClick={() => setModal({ user: u })}
                      className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-indigo-600 hover:bg-indigo-50"
                    >
                      Modifier
                    </button>
                    {u.id !== me?.id && (
                      <button
                        onClick={() => supprimerCompte(u)}
                        className="ml-1 rounded-lg px-2.5 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"
                      >
                        Supprimer
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
            <p className="pt-1 text-xs text-slate-500">
              Les copropriétaires peuvent consulter la situation de la copropriété. Seul le syndic peut modifier.
            </p>
          </div>
        </Card>
      )}

      {modal && (
        <UserModal
          item={modal.user}
          personnes={personnes}
          isSelf={modal.user?.id === me?.id}
          onClose={() => setModal(null)}
          onSaved={async () => { setModal(null); await loadComptes(); }}
          onError={setError}
        />
      )}
    </div>
  );
}

function UserModal({ item, personnes, isSelf, onClose, onSaved, onError }: {
  item?: User; personnes: Personne[]; isSelf?: boolean;
  onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const [f, setF] = useState({
    prenom: item?.prenom ?? "",
    nom: item?.nom ?? "",
    email: item?.email ?? "",
    role: item?.role ?? "membre",
    personne_id: item?.personne_id != null ? String(item.personne_id) : "",
    password: "",
  });
  const set = (k: keyof typeof f, v: string) => setF((prev) => ({ ...prev, [k]: v }));
  // Fiches déjà liées à un autre compte exclues (un compte par personne) ;
  // celle du compte en cours d'édition reste sélectionnable.
  const disponibles = personnes.filter((p) => p.id === item?.personne_id || !p.a_un_compte);

  function choisirPersonne(id: string) {
    const p = personnes.find((x) => String(x.id) === id);
    setF((prev) => ({
      ...prev,
      personne_id: id,
      // La fiche sert de modèle : les champs restent modifiables ensuite.
      prenom: p?.prenom || prev.prenom,
      nom: p?.nom || prev.nom,
      email: p?.email || prev.email,
    }));
  }

  async function save() {
    if (!f.email.trim() || !f.nom.trim()) {
      onError("L'email et le nom sont requis");
      return;
    }
    if (!item && f.password.length < 6) {
      onError("Le mot de passe initial doit contenir au moins 6 caractères");
      return;
    }
    try {
      const payload = {
        email: f.email, nom: f.nom, prenom: f.prenom, role: f.role,
        personne_id: f.personne_id === "" ? null : Number(f.personne_id),
        password: f.password || null, // vide = mot de passe conservé (édition)
      };
      if (item) await api.put(`/auth/users/${item.id}`, payload);
      else await api.post("/auth/users", payload);
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }

  return (
    <Modal open title={item ? "Modifier l'utilisateur" : "Nouvel utilisateur"} onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Input label="Prénom" value={f.prenom} onChange={(e) => set("prenom", e.target.value)} placeholder="Jean" />
          <Input label="Nom" value={f.nom} onChange={(e) => set("nom", e.target.value)} placeholder="Dupont" />
        </div>
        <Input label="Email" type="email" value={f.email} onChange={(e) => set("email", e.target.value)} />
        <Select
          label="Rôle"
          value={f.role}
          onChange={(e) => set("role", e.target.value)}
          disabled={isSelf}
        >
          <option value="membre">Copropriétaire (consultation)</option>
          <option value="syndic">Syndic</option>
        </Select>
        {isSelf && (
          <p className="text-xs text-slate-500">Vous ne pouvez pas modifier votre propre rôle.</p>
        )}
        <Select label="Fiche liée (Lots & occupants)" value={f.personne_id} onChange={(e) => choisirPersonne(e.target.value)}>
          <option value="">— Aucune —</option>
          {disponibles.map((p) => {
            const qualites = [p.est_proprietaire ? "propriétaire" : "", p.est_occupant ? "occupant" : ""].filter(Boolean).join(" · ");
            return (
              <option key={p.id} value={p.id}>
                {[p.prenom, p.nom].filter(Boolean).join(" ")}{qualites ? ` — ${qualites}` : ""}
              </option>
            );
          })}
        </Select>
        <p className="text-xs text-slate-500">
          Relie le compte à une personne de « Lots & occupants » : prénom, nom et email se préremplissent à la sélection.
        </p>
        <Input
          label={item ? "Nouveau mot de passe (laisser vide pour conserver)" : "Mot de passe initial"}
          type="password"
          value={f.password}
          onChange={(e) => set("password", e.target.value)}
          minLength={6}
          autoComplete="new-password"
        />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>{item ? "Enregistrer" : "Créer"}</Button>
        </div>
      </div>
    </Modal>
  );
}

import { useEffect, useState } from "react";
import { api, getToken } from "../api";
import { Button, Card, Input } from "./ui";

interface ResultatImport {
  copropriete_id: number;
  nom: string;
  comptes_crees: number;
  comptes_existants: number;
  comptes_a_completer: number;
  documents: number;
  deuxfa_desactivee: number;
  avertissements: string[];
}

const MDP_MIN = 10;

function entetes(): Record<string, string> {
  const jeton = getToken();   // session héritée (transition) ; sinon cookie de session
  return jeton ? { Authorization: `Bearer ${jeton}` } : {};
}

async function erreurDe(res: Response, defaut: string): Promise<Error> {
  const data = await res.json().catch(() => ({}));
  return new Error(typeof data.detail === "string" ? data.detail : defaut);
}

/** Sauvegarde de la copropriété active : export (archive ZIP, protégée ou non) et import (nouvelle copropriété). */
export function SauvegardeCard() {
  // Export : sans données personnelles par défaut ; elles (et les fichiers) exigent un mot de passe.
  const [mdp, setMdp] = useState("");
  const [mdp2, setMdp2] = useState("");
  const [perso, setPerso] = useState(false);
  const [fichiers, setFichiers] = useState(false);
  const [export_, setExport] = useState({ busy: false, erreur: "" });
  // Import
  const [fichier, setFichier] = useState<File | null>(null);
  const [mdpImport, setMdpImport] = useState("");
  const [busy, setBusy] = useState(false);
  const [erreur, setErreur] = useState("");
  const [resultat, setResultat] = useState<ResultatImport | null>(null);

  const protegee = mdp.length > 0;
  const mdpTropCourt = protegee && mdp.length < MDP_MIN;
  const mdpDifferent = protegee && mdp !== mdp2;
  const exportImpossible = mdpTropCourt || mdpDifferent || ((perso || fichiers) && !protegee);

  useEffect(() => {        // sans mot de passe : ni données personnelles, ni fichiers
    if (!protegee) { setPerso(false); setFichiers(false); }
  }, [protegee]);

  async function telecharger() {
    setExport({ busy: true, erreur: "" });
    try {
      const res = await fetch("/api/sauvegarde/export", {
        method: "POST", credentials: "include",
        headers: { ...entetes(), "Content-Type": "application/json" },
        body: JSON.stringify({ mot_de_passe: mdp, donnees_personnelles: perso, fichiers }),
      });
      if (!res.ok) throw await erreurDe(res, "Sauvegarde impossible");
      const nom = /filename="?([^";]+)"?/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? "Sauvegarde.zip";
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = nom;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      setExport({ busy: false, erreur: "" });
    } catch (e) {
      setExport({ busy: false, erreur: e instanceof Error ? e.message : "Sauvegarde impossible" });
    }
  }

  async function importer() {
    if (!fichier) return;
    setBusy(true);
    setErreur("");
    setResultat(null);
    try {
      const form = new FormData();
      form.append("fichier", fichier);
      form.append("mot_de_passe", mdpImport);
      const res = await fetch("/api/sauvegarde/import", {
        method: "POST", body: form, credentials: "include", headers: entetes(),
      });
      if (!res.ok) throw await erreurDe(res, "Import impossible");
      setResultat(await res.json() as ResultatImport);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Import impossible");
    } finally {
      setBusy(false);
    }
  }

  async function ouvrir(id: number, versComptes: boolean) {
    await api.post(`/auth/switch-copro/${id}`);
    window.location.href = versComptes ? "/settings?onglet=utilisateurs" : "/";
  }

  return (
    <Card title="Sauvegarde de la copropriété">
      <div className="space-y-4 text-sm">
        <div className="space-y-3">
          <p className="text-slate-600">
            Une archive (.zip) avec les données de cette copropriété : lots, comptes, exercices, appels, mouvements,
            AG, recouvrement, historique, contrats et fiches des documents. Le mot de passe SMTP n'y figure jamais.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Input label={`Mot de passe (facultatif, ${MDP_MIN} caractères min.)`} type="password" autoComplete="new-password"
              value={mdp} onChange={(e) => setMdp(e.target.value)} />
            <Input label="Confirmer le mot de passe" type="password" autoComplete="new-password" disabled={!protegee}
              value={mdp2} onChange={(e) => setMdp2(e.target.value)} />
          </div>
          {mdpTropCourt && <p className="text-xs text-amber-700">Au moins {MDP_MIN} caractères.</p>}
          {!mdpTropCourt && mdpDifferent && mdp2 && <p className="text-xs text-amber-700">Les deux mots de passe diffèrent.</p>}
          <fieldset className="space-y-2" disabled={!protegee}>
            <label className={`flex items-start gap-2 ${protegee ? "" : "opacity-50"}`}>
              <input type="checkbox" className="mt-0.5" checked={perso} onChange={(e) => setPerso(e.target.checked)} />
              <span>
                <b>Inclure les données personnelles</b> (noms, e-mails, téléphones, adresses, mots de passe des comptes).
                <span className="block text-xs text-slate-500">
                  Sans elles, les comptes deviennent « Compte 1 », « Compte 2 »… : leurs informations seront à
                  ressaisir après l'import (Réglages → Utilisateurs).
                </span>
              </span>
            </label>
            <label className={`flex items-start gap-2 ${protegee ? "" : "opacity-50"}`}>
              <input type="checkbox" className="mt-0.5" checked={fichiers} onChange={(e) => setFichiers(e.target.checked)} />
              <span>
                <b>Inclure les fichiers des documents</b> (factures, PV, contrats : ils contiennent souvent des noms
                et des adresses).
              </span>
            </label>
            {!protegee && (
              <p className="text-xs text-slate-500">
                Données personnelles et fichiers : seulement dans une sauvegarde protégée par un mot de passe.
              </p>
            )}
          </fieldset>
          {protegee && (
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
              Archive chiffrée (AES-256), lisible aussi avec 7-Zip ou WinRAR. Notez le mot de passe en lieu sûr :
              sans lui, la sauvegarde est perdue.
            </p>
          )}
          <p className="text-xs text-slate-500">
            Les textes libres (libellés des mouvements, notes des AG, des contrats et des travaux) sont gardés tels
            quels : évitez d'y écrire des données personnelles.
          </p>
          <Button onClick={telecharger} disabled={exportImpossible || export_.busy}>
            {export_.busy ? "Préparation…" : "⬇ Télécharger la sauvegarde"}
          </Button>
          {export_.erreur && <p className="rounded-lg bg-red-50 px-3 py-2 text-red-700">{export_.erreur}</p>}
        </div>
        <div className="border-t border-slate-100 pt-4">
          <p className="mb-2 text-slate-600">
            Restaurer une sauvegarde (changement de serveur, panne) : elle est importée comme une
            <b> nouvelle copropriété</b> de cette instance, sans rien écraser. Les comptes existants (même
            e-mail) sont réutilisés, les autres sont recréés.
          </p>
          <div className="space-y-2">
            <input type="file" accept=".zip,application/zip" className="block text-sm text-slate-600"
              onChange={(e) => { setFichier(e.target.files?.[0] ?? null); setResultat(null); setErreur(""); }} />
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[14rem] flex-1">
                <Input label="Mot de passe de la sauvegarde (si elle est protégée)" type="password"
                  autoComplete="off" value={mdpImport} onChange={(e) => setMdpImport(e.target.value)} />
              </div>
              <Button variant="secondary" disabled={!fichier || busy} onClick={importer}>
                {busy ? "Import en cours…" : "Importer"}
              </Button>
            </div>
          </div>
          {erreur && <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-red-700">{erreur}</p>}
          {resultat && (
            <div className="mt-2 space-y-1 rounded-lg bg-emerald-50 px-3 py-2 text-emerald-800">
              <p>
                « {resultat.nom} » importée : {resultat.comptes_crees} compte(s) créé(s),{" "}
                {resultat.comptes_existants} compte(s) existant(s) rattaché(s), {resultat.documents} fichier(s).
              </p>
              {resultat.comptes_a_completer > 0 && (
                <p className="text-amber-800">
                  Sauvegarde sans données personnelles : {resultat.comptes_a_completer} compte(s) « Compte N » à
                  compléter (nom, e-mail…) dans Réglages → Utilisateurs de la copropriété importée.
                </p>
              )}
              {resultat.deuxfa_desactivee > 0 && (
                <p>{resultat.deuxfa_desactivee} compte(s) devront réactiver leur double authentification.</p>
              )}
              {resultat.avertissements.map((a, i) => <p key={i} className="text-amber-700">{a}</p>)}
              <Button onClick={() => ouvrir(resultat.copropriete_id, resultat.comptes_a_completer > 0)}>
                {resultat.comptes_a_completer > 0 ? "Ouvrir et compléter les comptes" : "Ouvrir la copropriété importée"}
              </Button>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

interface CompteACompleter { id: number; nom: string; role: string; lots: string[] }

/** Comptes « Compte N » d'une sauvegarde importée sans données personnelles : à compléter. */
export function ComptesACompleterCard({ onChanged }: { onChanged?: () => void }) {
  const [comptes, setComptes] = useState<CompteACompleter[]>([]);
  const [edite, setEdite] = useState<number | null>(null);
  const [f, setF] = useState({ prenom: "", nom: "", email: "", telephone: "", adresse: "", password: "" });
  const [message, setMessage] = useState("");
  const [erreur, setErreur] = useState("");

  const charger = () => api.get<CompteACompleter[]>("/sauvegarde/comptes-a-completer").then(setComptes).catch(() => {});
  useEffect(() => { charger(); }, []);
  if (comptes.length === 0 && !message) return null;

  async function enregistrer(c: CompteACompleter) {
    setErreur("");
    try {
      const r = await api.put<{ fusionne: boolean }>(`/sauvegarde/comptes-a-completer/${c.id}`,
        { ...f, password: f.password || null });
      setMessage(r.fusionne
        ? `${c.nom} : cet e-mail a déjà un compte sur ce serveur, ${c.nom} y a été rattaché.`
        : `${c.nom} complété.`);
      setEdite(null);
      await charger();
      onChanged?.();
    } catch (e) { setErreur(e instanceof Error ? e.message : "Erreur"); }
  }

  return (
    <Card title={`Comptes à compléter (${comptes.length})`}>
      <div className="space-y-3 text-sm">
        <p className="text-slate-600">
          Cette copropriété vient d'une sauvegarde sans données personnelles. Remettez les informations de chaque
          compte. Si l'e-mail saisi a déjà un compte sur ce serveur, les deux sont réunis.
        </p>
        {message && <p className="rounded-lg bg-emerald-50 px-3 py-2 text-emerald-800">{message}</p>}
        {comptes.map((c) => (
          <div key={c.id} className="rounded-lg border border-slate-100 px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <span>
                <b>{c.nom}</b> · {c.role === "syndic" ? "Syndic" : "Copropriétaire"}
                {c.lots.length > 0 && <span className="text-slate-500"> · lot(s) {c.lots.join(", ")}</span>}
              </span>
              {edite !== c.id && (
                <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => {
                  setEdite(c.id); setErreur("");
                  setF({ prenom: "", nom: "", email: "", telephone: "", adresse: "", password: "" });
                }}>Compléter</Button>
              )}
            </div>
            {edite === c.id && (
              <div className="mt-3 space-y-2">
                <div className="grid gap-2 sm:grid-cols-2">
                  <Input label="Prénom" value={f.prenom} onChange={(e) => setF({ ...f, prenom: e.target.value })} />
                  <Input label="Nom" value={f.nom} onChange={(e) => setF({ ...f, nom: e.target.value })} />
                  <Input label="E-mail" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
                  <Input label="Téléphone" value={f.telephone} onChange={(e) => setF({ ...f, telephone: e.target.value })} />
                </div>
                <Input label="Adresse" value={f.adresse} onChange={(e) => setF({ ...f, adresse: e.target.value })} />
                <Input label="Mot de passe (facultatif, sinon à définir plus tard)" type="password" autoComplete="new-password"
                  value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
                {erreur && <p className="rounded-lg bg-red-50 px-3 py-2 text-red-700">{erreur}</p>}
                <div className="flex justify-end gap-2">
                  <Button variant="secondary" onClick={() => setEdite(null)}>Annuler</Button>
                  <Button disabled={!f.email || !f.nom} onClick={() => enregistrer(c)}>Enregistrer</Button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

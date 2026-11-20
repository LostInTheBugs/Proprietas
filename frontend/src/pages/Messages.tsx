import { useEffect, useState } from "react";
import { api } from "../api";
import { fmtDateTime } from "../types";
import { Badge, Button, Card, Empty, Input, Select } from "../components/ui";
import { useCles } from "../components/Cles";

/** Messages groupés du syndic aux copropriétaires : information par e-mail, un envoi par personne. */

interface Personne { personne_id: number; nom: string }
interface Apercu {
  destinataires: { id: number; nom: string; email: boolean }[]; sans_email: string[]; cle_nom: string;
  exemple: { pour: string; sujet: string; corps: string } | null;
}
interface Envoi {
  id: number; envoye_le: string; sujet: string; corps: string; cible: string; cle_nom: string;
  destinataires: string[]; nb_envoyes: number; erreurs: string[];
}

export default function Messages() {
  const [cles] = useCles();
  const [personnes, setPersonnes] = useState<Personne[]>([]);
  const [historique, setHistorique] = useState<Envoi[]>([]);
  const [sujet, setSujet] = useState("");
  const [corps, setCorps] = useState("Bonjour {prenom},\n\n");
  const [cible, setCible] = useState("tous");
  const [cleId, setCleId] = useState("");
  const [ids, setIds] = useState<number[]>([]);
  const [apercu, setApercu] = useState<Apercu | null>(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  const charger = () => { api.get<Envoi[]>("/messages").then(setHistorique).catch(() => {}); };
  useEffect(() => {
    charger();
    // Copropriétaires : la liste des présences d'AG n'est pas toujours là ; on part des lots.
    api.get<{ proprietaire_id: number | null; proprietaire_nom?: string }[]>("/lots").then((lots) => {
      const m = new Map<number, string>();
      lots.forEach((l) => { if (l.proprietaire_id != null) m.set(l.proprietaire_id, l.proprietaire_nom || `Compte #${l.proprietaire_id}`); });
      setPersonnes([...m.entries()].map(([personne_id, nom]) => ({ personne_id, nom })).sort((a, b) => a.nom.localeCompare(b.nom)));
    }).catch(() => {});
  }, []);

  const corpsRequete = () => ({ sujet, corps, cible, cle_id: cible === "cle" && cleId ? Number(cleId) : null,
    ids: cible === "selection" ? ids : [] });

  async function voir() {
    setError(""); setInfo("");
    try { setApercu(await api.post<Apercu>("/messages/apercu", corpsRequete())); }
    catch (e) { setError(e instanceof Error ? e.message : "Erreur"); }
  }
  async function envoyer() {
    if (!apercu) return;
    const n = apercu.destinataires.filter((d) => d.email).length;
    if (!confirm(`Envoyer ce message à ${n} copropriétaire(s) ?`)) return;
    setBusy(true); setError("");
    try {
      const r = await api.post<{ nb_envoyes: number; erreurs: string[] }>("/messages", corpsRequete());
      setInfo(`${r.nb_envoyes} message(s) envoyé(s)` + (r.erreurs.length ? ` ; échec pour : ${r.erreurs.join(" ; ")}` : "."));
      setApercu(null); setSujet(""); setCorps("Bonjour {prenom},\n\n"); charger();
    } catch (e) { setError(e instanceof Error ? e.message : "Erreur"); } finally { setBusy(false); }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-800">Messages aux copropriétaires</h1>
        <p className="text-sm text-slate-500">
          Information par e-mail (travaux, coupure, rappel…), un envoi par personne : personne ne voit l'adresse des autres.
          Une convocation ou une notification officielle passe par lettre recommandée.
        </p>
      </div>
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {info && <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{info}</p>}

      <Card title="Nouveau message">
        <div className="space-y-3 text-sm">
          <div className="grid gap-3 sm:grid-cols-2">
            <Select label="Destinataires" value={cible} onChange={(e) => { setCible(e.target.value); setApercu(null); }}>
              <option value="tous">Tous les copropriétaires</option>
              {cles.length > 0 && <option value="cle">Les copropriétaires d'une clé de répartition</option>}
              <option value="selection">Une sélection</option>
            </Select>
            {cible === "cle" && (
              <Select label="Clé" value={cleId} onChange={(e) => { setCleId(e.target.value); setApercu(null); }}>
                <option value="">— Choisir —</option>
                {cles.map((c) => <option key={c.id} value={c.id}>{c.nom}</option>)}
              </Select>
            )}
          </div>
          {cible === "selection" && (
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {personnes.map((p) => (
                <label key={p.personne_id} className="flex items-center gap-1.5 text-slate-700">
                  <input type="checkbox" checked={ids.includes(p.personne_id)}
                    onChange={(e) => { setApercu(null); setIds(e.target.checked ? [...ids, p.personne_id] : ids.filter((x) => x !== p.personne_id)); }} />
                  {p.nom}
                </label>
              ))}
            </div>
          )}
          <Input label="Sujet" value={sujet} onChange={(e) => { setSujet(e.target.value); setApercu(null); }} />
          <label className="block">
            <span className="mb-1 block font-medium text-slate-600">Message</span>
            <textarea value={corps} rows={8} onChange={(e) => { setCorps(e.target.value); setApercu(null); }}
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500" />
          </label>
          <p className="text-xs text-slate-500">
            Remplacés pour chacun : <code>{"{prenom}"}</code>, <code>{"{nom}"}</code>, <code>{"{lots}"}</code>. Un pied rappelle
            qu'il s'agit d'une information.
          </p>
          {apercu && (
            <div className="space-y-2 rounded-lg border border-slate-200 p-3">
              <p className="text-xs text-slate-600">
                {apercu.destinataires.filter((d) => d.email).length} destinataire(s) :{" "}
                {apercu.destinataires.filter((d) => d.email).map((d) => d.nom).join(", ")}
              </p>
              {apercu.sans_email.length > 0 && (
                <p className="text-xs text-amber-700">Sans adresse e-mail (non prévenus) : {apercu.sans_email.join(", ")}</p>
              )}
              {apercu.exemple && (
                <div className="rounded bg-slate-50 p-2 text-xs text-slate-700">
                  <p className="mb-1 text-slate-500">Exemple, pour {apercu.exemple.pour} :</p>
                  <p className="font-semibold">{apercu.exemple.sujet}</p>
                  <pre className="whitespace-pre-wrap font-sans">{apercu.exemple.corps}</pre>
                </div>
              )}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={voir} disabled={!sujet.trim() || !corps.trim()}>Aperçu</Button>
            <Button onClick={envoyer} disabled={!apercu || busy || !apercu.destinataires.some((d) => d.email)}>Envoyer</Button>
          </div>
        </div>
      </Card>

      <Card title="Messages envoyés">
        {historique.length === 0 ? <Empty text="Aucun message envoyé." /> : (
          <ul className="divide-y divide-slate-100 text-sm">
            {historique.map((m) => (
              <li key={m.id} className="space-y-1 py-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-slate-500">{fmtDateTime(m.envoye_le)}</span>
                  <span className="font-medium text-slate-800">{m.sujet}</span>
                  <Badge color="slate">{m.cible === "cle" ? `clé ${m.cle_nom}` : m.cible === "selection" ? "sélection" : "tous"}</Badge>
                  <Badge color={m.erreurs.length ? "amber" : "green"}>{m.nb_envoyes} envoyé(s){m.erreurs.length ? `, ${m.erreurs.length} échec(s)` : ""}</Badge>
                </div>
                <p className="text-xs text-slate-500">À : {m.destinataires.join(", ")}</p>
                {m.erreurs.length > 0 && <p className="text-xs text-amber-700">{m.erreurs.join(" ; ")}</p>}
                <details className="text-xs text-slate-600"><summary className="cursor-pointer">Message</summary>
                  <pre className="mt-1 whitespace-pre-wrap font-sans">{m.corps}</pre></details>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { fmtDate } from "../types";
import type { AG } from "../types";
import { Badge, Button, Card, Input, Modal, Select } from "./ui";

/** Mandats du syndic bénévole et du conseil syndical : en cours, historique, échéance (3 ans au plus). */

export interface Membre { personne_id: number | null; nom: string }
export interface Mandat {
  id: number; role: string; debut: string; fin: string; membres: Membre[];
  ag_id: number | null; ag_date: string | null; resolution_id: number | null; resolution_numero: number | null;
  manuel: boolean;
}
interface Role { libelle: string; etat: "en_cours" | "bientot" | "echu" | "aucun"; actuel: Mandat | null; historique: Mandat[] }
export interface Mandats {
  syndic: Role; conseil: Role; alertes: string[]; personnes: { id: number; nom: string }[];
}

export function useMandats(): [Mandats | null, () => void] {
  const [m, setM] = useState<Mandats | null>(null);
  const charger = useCallback(() => { api.get<Mandats>("/mandats").then(setM).catch(() => {}); }, []);
  useEffect(() => { charger(); }, [charger]);
  return [m, charger];
}

const ETATS: Record<Role["etat"], { texte: string; couleur: "green" | "amber" | "red" | "slate" }> = {
  en_cours: { texte: "en cours", couleur: "green" },
  bientot: { texte: "bientôt échu", couleur: "amber" },
  echu: { texte: "échu", couleur: "red" },
  aucun: { texte: "aucun mandat", couleur: "slate" },
};

function origine(m: Mandat) {
  if (m.resolution_numero != null && m.ag_date) return `résolution n° ${m.resolution_numero} de l'AG du ${fmtDate(m.ag_date)}`;
  if (m.ag_date) return `AG du ${fmtDate(m.ag_date)} (saisi à la main)`;
  return "saisi à la main";
}

/** Rappel du tableau de bord : mandats bientôt échus ou échus. */
export function MandatsAlerte() {
  const [m] = useMandats();
  if (!m || m.alertes.length === 0) return null;
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
      {m.alertes.map((a) => <p key={a}>{a}</p>)}
    </div>
  );
}

export function MandatsCard({ isSyndic, ags, rev = 0 }: { isSyndic: boolean; ags: AG[]; rev?: number }) {
  const [m, charger] = useMandats();
  const [ajout, setAjout] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (rev) charger(); }, [rev, charger]);
  if (!m) return null;

  async function supprimer(id: number) {
    if (!confirm("Supprimer ce mandat saisi à la main ?")) return;
    try { await api.del(`/mandats/${id}`); charger(); }
    catch (e) { setError(e instanceof Error ? e.message : "Erreur"); }
  }

  return (
    <Card title="Syndic et conseil syndical" action={isSyndic &&
      <Button variant="secondary" onClick={() => setAjout(true)}>+ Mandat passé</Button>}>
      {error && <p className="mb-2 rounded bg-red-50 px-2 py-1 text-xs text-red-700">{error}</p>}
      <div className="grid gap-4 sm:grid-cols-2 text-sm">
        {(["syndic", "conseil"] as const).map((role) => {
          const r = m[role];
          const e = ETATS[r.etat];
          return (
            <div key={role} className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-medium text-slate-800">{r.libelle}</span>
                <Badge color={e.couleur}>{e.texte}</Badge>
              </div>
              {r.actuel ? (
                <>
                  <p className="text-slate-700">{r.actuel.membres.map((x) => x.nom || "—").join(", ")}</p>
                  <p className="text-xs text-slate-500">
                    Du {fmtDate(r.actuel.debut)} au {fmtDate(r.actuel.fin)} · {origine(r.actuel)}
                  </p>
                </>
              ) : (
                <p className="text-xs text-slate-500">
                  {r.historique.length ? `Dernier mandat terminé le ${fmtDate(r.historique[0].fin)}.` : "Aucun mandat enregistré."}
                </p>
              )}
              {r.historique.length > 0 && (
                <details className="text-xs text-slate-600">
                  <summary className="cursor-pointer">Historique ({r.historique.length})</summary>
                  <ul className="mt-1 space-y-0.5">
                    {r.historique.map((h) => (
                      <li key={h.id} className="flex items-center gap-2">
                        <span>{fmtDate(h.debut)} → {fmtDate(h.fin)} : {h.membres.map((x) => x.nom || "—").join(", ")} ({origine(h)})</span>
                        {isSyndic && h.manuel && (
                          <button className="text-red-600 hover:underline" onClick={() => supprimer(h.id)}>supprimer</button>
                        )}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Mandats de trois ans au plus (décret du 17 mars 1967, art. 22 et 28). Une résolution « Désignation du syndic » ou
        « Élection du conseil syndical » adoptée enregistre le mandat ; un mandat plus ancien se saisit à la main.
      </p>
      {ajout && <MandatModal mandats={m} ags={ags} onClose={() => setAjout(false)}
        onSaved={() => { setAjout(false); charger(); }} />}
    </Card>
  );
}

function MandatModal({ mandats, ags, onClose, onSaved }: {
  mandats: Mandats; ags: AG[]; onClose: () => void; onSaved: () => void;
}) {
  const [role, setRole] = useState("syndic");
  const [agId, setAgId] = useState("");
  const [debut, setDebut] = useState("");
  const [mois, setMois] = useState("36");
  const [ids, setIds] = useState<number[]>([]);
  const [noms, setNoms] = useState("");
  const [error, setError] = useState("");
  const passees = ags.filter((a) => a.date <= new Date().toISOString().slice(0, 10));

  async function save() {
    setError("");
    try {
      await api.post("/mandats", {
        role, ag_id: agId ? Number(agId) : null, debut: agId ? null : debut || null, mois: Number(mois),
        personne_ids: ids, noms: noms.split(/[,;\n]/).map((n) => n.trim()).filter(Boolean),
      });
      onSaved();
    } catch (e) { setError(e instanceof Error ? e.message : "Erreur"); }
  }
  const coche = (id: number, oui: boolean) =>
    setIds(role === "syndic" ? (oui ? [id] : []) : oui ? [...ids, id] : ids.filter((x) => x !== id));

  return (
    <Modal open title="Mandat passé" onClose={onClose}>
      <div className="space-y-3 text-sm">
        {error && <p className="rounded bg-red-50 px-2 py-1 text-xs text-red-700">{error}</p>}
        <div className="grid gap-3 sm:grid-cols-2">
          <Select label="Rôle" value={role} onChange={(e) => { setRole(e.target.value); setIds([]); }}>
            <option value="syndic">Syndic bénévole</option>
            <option value="conseil">Conseil syndical</option>
          </Select>
          <Input label="Durée (mois, 36 au plus)" type="number" min={1} max={36} value={mois}
            onChange={(e) => setMois(e.target.value)} />
          <Select label="Voté à l'AG" value={agId} onChange={(e) => setAgId(e.target.value)}>
            <option value="">— AG absente de l'application —</option>
            {passees.map((a) => <option key={a.id} value={a.id}>AG du {fmtDate(a.date)}</option>)}
          </Select>
          {!agId && <Input label="Début du mandat" type="date" value={debut} onChange={(e) => setDebut(e.target.value)} />}
        </div>
        <div>
          <span className="mb-1 block font-medium text-slate-600">{role === "syndic" ? "Syndic" : "Membres"}</span>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {mandats.personnes.map((p) => (
              <label key={p.id} className="flex items-center gap-1.5 text-slate-700">
                <input type={role === "syndic" ? "radio" : "checkbox"} name="mandat-personne" checked={ids.includes(p.id)}
                  onChange={(e) => coche(p.id, e.target.checked)} />
                {p.nom}
              </label>
            ))}
          </div>
        </div>
        <Input label="Personnes sans compte (noms séparés par des virgules)" value={noms}
          onChange={(e) => setNoms(e.target.value)} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save} disabled={!mois || (!agId && !debut)}>Enregistrer</Button>
        </div>
      </div>
    </Modal>
  );
}

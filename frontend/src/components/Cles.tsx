import { useEffect, useState } from "react";
import { api } from "../api";
import type { Lot } from "../types";
import { Badge, Button, Card, Input, Modal } from "./ui";

/** Clés de répartition (charges spéciales, loi du 10 juillet 1965, art. 10). */

export interface Cle {
  id: number;
  nom: string;
  total: number;
  lots: { lot_id: number; lot_numero: string; tantiemes: number }[];
  utilisations: { lignes_budget?: number; appels?: number; depenses?: number };
}

export const GENERALES = "Charges générales";

export function useCles(): [Cle[], () => void] {
  const [cles, setCles] = useState<Cle[]>([]);
  const charger = () => { api.get<Cle[]>("/cles").then(setCles).catch(() => {}); };
  useEffect(charger, []);
  return [cles, charger];
}

/** Liste « Charges générales » + clés, pour un <Select>. */
export function OptionsCles({ cles }: { cles: Cle[] }) {
  return (<>
    <option value="">{GENERALES} (tous les lots, tantièmes généraux)</option>
    {cles.map((c) => <option key={c.id} value={c.id}>{c.nom} ({c.lots.length} lot{c.lots.length > 1 ? "s" : ""})</option>)}
  </>);
}

/** Page Lots : les clés, leurs lots et millièmes ; création et modification par le syndic. */
export function ClesCard({ lots, isSyndic, onError }: { lots: Lot[]; isSyndic: boolean; onError: (e: string) => void }) {
  const [cles, charger] = useCles();
  const [modal, setModal] = useState<null | { cle?: Cle }>(null);
  if (!isSyndic && cles.length === 0) return null;

  async function supprimer(c: Cle) {
    if (!confirm(`Supprimer la clé « ${c.nom} » ?`)) return;
    try { await api.del(`/cles/${c.id}`); charger(); } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }

  return (
    <Card title="Clés de répartition (charges spéciales)"
      action={isSyndic ? <Button variant="secondary" className="px-2.5 py-1.5 text-xs" onClick={() => setModal({})}>+ Nouvelle clé</Button> : undefined}>
      <p className="mb-3 text-xs leading-relaxed text-slate-500">
        Les charges générales se répartissent entre tous les lots par leurs tantièmes. Une clé (« Bâtiment A », « Ascenseur »,
        « Garages »…) répartit certaines charges entre les seuls lots concernés, avec leurs propres millièmes (loi du 10 juillet
        1965, art. 10). Chaque ligne de budget et chaque dépense commune choisit sa clé ; les appels de provisions suivent le
        budget, clé par clé.
      </p>
      {cles.length === 0 ? (
        <p className="text-sm text-slate-500">Aucune clé : toutes les charges sont générales.</p>
      ) : (
        <ul className="divide-y divide-slate-100 text-sm">
          {cles.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-2 py-2">
              <span className="font-medium text-slate-800">{c.nom}</span>
              <span className="text-xs text-slate-500">
                {c.lots.map((l) => `lot ${l.lot_numero} : ${l.tantiemes}`).join(" · ")} — total {c.total}
              </span>
              {(c.utilisations.lignes_budget || c.utilisations.depenses || c.utilisations.appels) ? (
                <Badge color="indigo">utilisée</Badge>
              ) : null}
              {isSyndic && (
                <span className="ml-auto flex gap-1">
                  <Button variant="ghost" onClick={() => setModal({ cle: c })}>Modifier</Button>
                  <Button variant="ghost" onClick={() => supprimer(c)}>Supprimer</Button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {modal && (
        <CleModal cle={modal.cle} lots={lots} onClose={() => setModal(null)}
          onSaved={() => { setModal(null); charger(); }} onError={onError} />
      )}
    </Card>
  );
}

function CleModal({ cle, lots, onClose, onSaved, onError }: {
  cle?: Cle; lots: Lot[]; onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const [nom, setNom] = useState(cle?.nom ?? "");
  const [valeurs, setValeurs] = useState<Record<number, string>>(() =>
    Object.fromEntries(lots.map((l) => [l.id, String(cle?.lots.find((x) => x.lot_id === l.id)?.tantiemes ?? "")])));
  const total = Object.values(valeurs).reduce((s, v) => s + (Number(v) || 0), 0);
  async function save() {
    const corps = { nom, lots: lots.map((l) => ({ lot_id: l.id, tantiemes: Number(valeurs[l.id]) || 0 })) };
    try {
      if (cle) await api.put(`/cles/${cle.id}`, corps); else await api.post("/cles", corps);
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  return (
    <Modal open title={cle ? `Clé « ${cle.nom} »` : "Nouvelle clé de répartition"} onClose={onClose}>
      <div className="space-y-3 text-sm">
        <Input label="Nom" value={nom} onChange={(e) => setNom(e.target.value)} placeholder="Bâtiment A, Ascenseur, Garages…" />
        <p className="text-xs text-slate-500">Millièmes de chaque lot pour cette clé ; vide ou 0 : le lot ne participe pas.</p>
        <div className="max-h-72 overflow-y-auto rounded-lg border border-slate-200">
          <table className="w-full">
            <tbody className="divide-y divide-slate-100">
              {lots.map((l) => (
                <tr key={l.id}>
                  <td className="px-3 py-1.5 text-slate-700">Lot {l.numero}{l.designation ? ` — ${l.designation}` : ""}
                    <span className="block text-xs text-slate-400">{l.tantiemes} tantièmes généraux</span></td>
                  <td className="w-32 px-3 py-1.5">
                    <input type="number" min={0} className="w-full rounded border border-slate-300 px-2 py-1 text-right"
                      value={valeurs[l.id] ?? ""} onChange={(e) => setValeurs({ ...valeurs, [l.id]: e.target.value })} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-slate-600">Total : <strong>{total}</strong></span>
          <Button variant="ghost" onClick={() => setValeurs(Object.fromEntries(lots.map((l) => [l.id, String(l.tantiemes)])))}>
            Reprendre les tantièmes généraux
          </Button>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save} disabled={!nom.trim() || total <= 0}>{cle ? "Enregistrer" : "Créer"}</Button>
        </div>
      </div>
    </Modal>
  );
}

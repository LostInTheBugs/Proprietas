import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Button } from "./ui";

/** Vote en direct pendant l'AG : la résolution ouverte par le syndic, le vote de chacun, le décompte. */

interface MonLot { lot_id: number; numero: string; au_titre: string; tantiemes: number; voix: string | null }
interface Etat {
  resolution: { id: number; numero: number; libelle: string; texte: string; majorite: string } | null;
  peut_voter: boolean;
  mes_lots: MonLot[];
  decompte: { pour: number; contre: number; abstention: number; total: number; votants: number } | null;
}

const LIBELLES: Record<string, string> = { pour: "Pour", contre: "Contre", abstention: "Abstention" };
const COULEURS: Record<string, string> = {
  pour: "bg-emerald-600 hover:bg-emerald-700", contre: "bg-red-600 hover:bg-red-700", abstention: "bg-slate-500 hover:bg-slate-600",
};

/** `seance` : l'AG a lieu aujourd'hui ou a eu lieu (sinon rien n'est interrogé). */
export function useVoteEnDirect(agId: number, seance: boolean): [Etat | null, (e: Etat) => void, () => void] {
  const [etat, setEtat] = useState<Etat | null>(null);
  const charger = useCallback(() => {
    if (seance) api.get<Etat>(`/ag/${agId}/vote-en-ligne`).then(setEtat).catch(() => {});
  }, [agId, seance]);
  useEffect(() => {
    charger();
    if (!seance) return;
    const t = window.setInterval(charger, 3000);        // décompte en direct
    return () => window.clearInterval(t);
  }, [charger, seance]);
  return [etat, setEtat, charger];
}

export function VoteEnDirect({ agId, seance, onError }: { agId: number; seance: boolean; onError: (e: string) => void }) {
  const [etat, setEtat] = useVoteEnDirect(agId, seance);
  const [busy, setBusy] = useState(false);
  if (!etat || !etat.resolution) return null;
  const r = etat.resolution;
  const d = etat.decompte;
  const plusieurs = etat.mes_lots.length > 1;

  async function voter(voix: string, lot_ids?: number[]) {
    setBusy(true);
    try { setEtat(await api.put<Etat>(`/resolutions/${r.id}/mon-vote`, { voix, lot_ids: lot_ids ?? null })); }
    catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
    finally { setBusy(false); }
  }

  return (
    <div className="space-y-3 rounded-lg border-2 border-indigo-300 bg-indigo-50/50 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge color="indigo">Vote en cours</Badge>
        <span className="font-semibold text-slate-800">Résolution {r.numero} — {r.libelle}</span>
      </div>
      {r.texte && <p className="text-xs text-slate-600">{r.texte}</p>}

      {etat.peut_voter && etat.mes_lots.length > 0 ? (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2">
            {Object.keys(LIBELLES).map((v) => (
              <button key={v} disabled={busy} onClick={() => voter(v)}
                className={`rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50 ${COULEURS[v]}`}>
                {LIBELLES[v]}{plusieurs ? " (tous mes lots)" : ""}
              </button>
            ))}
          </div>
          <ul className="space-y-1 text-xs text-slate-700">
            {etat.mes_lots.map((l) => (
              <li key={l.lot_id} className="flex flex-wrap items-center gap-2">
                <span>Lot {l.numero}{l.au_titre ? ` (${l.au_titre})` : ""} · {l.tantiemes} millièmes :</span>
                <b>{l.voix ? LIBELLES[l.voix] : "pas encore voté"}</b>
                {plusieurs && (
                  <select className="rounded border border-slate-300 bg-white px-1 py-0.5" value="" disabled={busy}
                    onChange={(e) => e.target.value && voter(e.target.value, [l.lot_id])}>
                    <option value="">changer pour ce lot…</option>
                    {Object.entries(LIBELLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                )}
              </li>
            ))}
          </ul>
          <p className="text-xs text-slate-500">Vous pouvez changer votre vote jusqu'à la clôture par le syndic.</p>
        </div>
      ) : (
        <p className="text-xs text-slate-500">
          {etat.peut_voter ? "Aucun de vos lots ne vote cette résolution."
            : "Pour voter en ligne, soyez indiqué(e) présent(e) ou en visioconférence (« Ma réponse »)."}
        </p>
      )}

      {d && (
        <div>
          <p className="text-xs text-slate-600">
            Décompte en direct : <b className="text-emerald-700">{d.pour} pour</b> · <b className="text-red-700">{d.contre} contre</b> ·{" "}
            {d.abstention} abstention ({d.votants} lot(s) ont voté, sur {d.total} millièmes)
          </p>
          <div className="mt-1 flex h-2 overflow-hidden rounded-full bg-slate-200">
            <div className="bg-emerald-500" style={{ width: `${d.total ? (d.pour / d.total) * 100 : 0}%` }} />
            <div className="bg-red-400" style={{ width: `${d.total ? (d.contre / d.total) * 100 : 0}%` }} />
            <div className="bg-slate-400" style={{ width: `${d.total ? (d.abstention / d.total) * 100 : 0}%` }} />
          </div>
        </div>
      )}
    </div>
  );
}

/** Syndic : ouvrir ou clore le vote en ligne d'une résolution. */
export function BoutonVoteEnLigne({ resolutionId, etat, onChanged, onError }: {
  resolutionId: number; etat: string; onChanged: () => void; onError: (e: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  async function action(quoi: "ouvrir" | "clore") {
    if (quoi === "clore" && !confirm("Clore le vote ? Le résultat sera calculé avec les votes enregistrés.")) return;
    setBusy(true);
    try { await api.post(`/resolutions/${resolutionId}/vote-en-ligne/${quoi}`); onChanged(); }
    catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
    finally { setBusy(false); }
  }
  return etat === "ouvert"
    ? <Button className="px-2 py-1 text-xs" disabled={busy} onClick={() => action("clore")}>Clore le vote</Button>
    : <Button variant="secondary" className="px-2 py-1 text-xs" disabled={busy} onClick={() => action("ouvrir")}>
        {etat === "clos" ? "Rouvrir le vote en ligne" : "Ouvrir le vote en ligne"}
      </Button>;
}

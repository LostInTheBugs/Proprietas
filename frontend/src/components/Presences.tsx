import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Button, Select } from "./ui";

/** AG : réponse des copropriétaires (présent, pouvoir, absent, ne sait pas) et pouvoirs (loi 1965, art. 22). */

export const REPONSES: [string, string][] = [
  ["present", "Je serai présent(e)"],
  ["pouvoir", "Je ne serai pas présent(e) et je donne pouvoir à…"],
  ["absent", "Je ne serai pas présent(e)"],
  ["incertain", "Je ne sais pas encore"],
];
const COURT: Record<string, string> = { present: "Présent", pouvoir: "Représenté", absent: "Absent", incertain: "Incertain", "": "Sans réponse" };
const COULEUR: Record<string, "green" | "indigo" | "slate" | "amber" | "red"> = {
  present: "green", pouvoir: "indigo", absent: "slate", incertain: "amber", "": "slate",
};

interface Personne { id: number; nom: string }
interface MaReponse {
  ouvert: boolean; coproprietaire: boolean; reponse: string; mandataire_id: number | null; mandataire_nom: string;
  repondu_le: string | null; mandataires: Personne[]; mandats: Personne[];
}
interface Ligne {
  personne_id: number; nom: string; lots: string[]; voix: number; reponse: string; repondu_le: string | null;
  source: string; mandataire_id: number | null; mandataire_nom: string; mandataire_absent: boolean;
  pouvoir_recu_le: string | null; mandats: number; peut_recevoir_pouvoir: boolean;
}
interface Presences {
  ouvert: boolean; lignes: Ligne[];
  totaux: { presents: number; representes: number; absents: number; incertains: number; sans_reponse: number;
    voix_presentes_ou_representees: number };
}

const RAPPEL_ART22 = "Le syndic, son conjoint ou partenaire, ses parents et ses employés ne peuvent pas recevoir de pouvoir ; "
  + "un copropriétaire ne peut pas en recevoir plus de trois, sauf s'il reste sous 10 % des voix (loi du 10 juillet 1965, art. 22).";

/** Le copropriétaire connecté : sa réponse, et les pouvoirs qu'il a reçus. */
export function MaReponseAg({ agId, onError }: { agId: number; onError: (e: string) => void }) {
  const [m, setM] = useState<MaReponse | null>(null);
  const [reponse, setReponse] = useState("");
  const [mandataire, setMandataire] = useState("");
  const [busy, setBusy] = useState(false);
  const afficher = (x: MaReponse) => { setM(x); setReponse(x.reponse); setMandataire(x.mandataire_id ? String(x.mandataire_id) : ""); };
  useEffect(() => { api.get<MaReponse>(`/ag/${agId}/ma-reponse`).then(afficher).catch(() => {}); }, [agId]);
  if (!m || !m.coproprietaire) return null;

  async function envoyer() {
    setBusy(true);
    try {
      afficher(await api.put<MaReponse>(`/ag/${agId}/ma-reponse`,
        { reponse, mandataire_id: reponse === "pouvoir" && mandataire ? Number(mandataire) : null }));
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
    finally { setBusy(false); }
  }

  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <p className="mb-2 text-sm font-semibold text-slate-700">🙋 Ma réponse</p>
      {m.reponse && (
        <p className="mb-2 text-sm text-slate-600">
          Réponse enregistrée : <Badge color={COULEUR[m.reponse]}>{COURT[m.reponse]}</Badge>
          {m.reponse === "pouvoir" && <> — pouvoir à <strong>{m.mandataire_nom}</strong>{" "}
            (<PouvoirLien agId={agId} />)</>}
        </p>
      )}
      {m.ouvert ? (
        <div className="space-y-2 text-sm">
          {REPONSES.map(([k, l]) => (
            <label key={k} className="flex items-center gap-2 text-slate-700">
              <input type="radio" name={`reponse-${agId}`} checked={reponse === k} onChange={() => setReponse(k)} />
              {l}
            </label>
          ))}
          {reponse === "pouvoir" && (
            <>
              <Select label="Pouvoir à" value={mandataire} onChange={(e) => setMandataire(e.target.value)}>
                <option value="">— choisir un copropriétaire —</option>
                {m.mandataires.map((p) => <option key={p.id} value={p.id}>{p.nom}</option>)}
              </Select>
              <p className="text-xs text-slate-500">{RAPPEL_ART22} Une fois enregistré, téléchargez le pouvoir, signez-le et
                remettez-le à votre mandataire ou au syndic.</p>
            </>
          )}
          <Button onClick={envoyer} disabled={busy || !reponse || (reponse === "pouvoir" && !mandataire)}>
            {m.reponse ? "Modifier ma réponse" : "Envoyer ma réponse"}
          </Button>
        </div>
      ) : (
        <p className="text-xs text-slate-500">L'assemblée est ouverte : votre réponse ne change plus en ligne.</p>
      )}
      {m.mandats.length > 0 && (
        <p className="mt-2 text-xs text-slate-600">
          Vous représentez : {m.mandats.map((p, i) => (
            <span key={p.id}>{i > 0 && ", "}{p.nom} (<a className="text-indigo-600 hover:underline"
              href={`/api/ag/${agId}/pouvoirs/${p.id}`}>pouvoir</a>)</span>
          ))}.
        </p>
      )}
    </div>
  );
}

/** Lien vers son propre pouvoir (l'identifiant du compte connecté vient de /auth/me). */
function PouvoirLien({ agId }: { agId: number }) {
  const [id, setId] = useState<number | null>(null);
  useEffect(() => { api.get<{ id: number }>("/auth/me").then((u) => setId(u.id)).catch(() => {}); }, []);
  return id ? <a className="text-indigo-600 hover:underline" href={`/api/ag/${agId}/pouvoirs/${id}`}>pouvoir à signer (PDF)</a> : null;
}

/** Syndic : réponses de tous les copropriétaires, pouvoirs, feuille de présence. */
export function PresencesSyndic({ agId, onError }: { agId: number; onError: (e: string) => void }) {
  const [p, setP] = useState<Presences | null>(null);
  const charger = useCallback(() => { api.get<Presences>(`/ag/${agId}/presences`).then(setP).catch(() => {}); }, [agId]);
  useEffect(charger, [charger]);
  if (!p || p.lignes.length === 0) return null;

  async function saisir(l: Ligne, champs: Partial<{ reponse: string; mandataire_id: number | null; pouvoir_recu: boolean }>) {
    const corps = { reponse: l.reponse || "incertain", mandataire_id: l.mandataire_id, ...champs };
    if (corps.reponse === "pouvoir" && !corps.mandataire_id) {
      setP({ ...p!, lignes: p!.lignes.map((x) => (x.personne_id === l.personne_id ? { ...x, reponse: "pouvoir" } : x)) });
      return;                                          // attend le choix du mandataire
    }
    if (corps.reponse !== "pouvoir") corps.mandataire_id = null;
    try {
      setP(await api.put<Presences>(`/ag/${agId}/presences/${l.personne_id}`, corps));
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); charger(); }
  }

  const t = p.totaux;
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-slate-700">🙋 Présences et pouvoirs</p>
        <a href={`/api/ag/${agId}/feuille-presence`}
          className="rounded-lg bg-slate-100 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200">
          📄 Feuille de présence (PDF)
        </a>
      </div>
      <p className="mb-2 text-xs text-slate-600">
        <strong>{t.presents}</strong> présent(s) · <strong>{t.representes}</strong> représenté(s) · {t.absents} absent(s) ·{" "}
        {t.incertains} incertain(s) · {t.sans_reponse} sans réponse — présents ou représentés :{" "}
        <strong>{t.voix_presentes_ou_representees.toLocaleString("fr-FR")} ‰</strong> des voix.
        {!p.ouvert && " L'assemblée est ouverte : vous tenez la feuille de présence ici."}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="py-1.5 pr-2">Copropriétaire</th>
              <th className="py-1.5 pr-2">Voix (‰)</th>
              <th className="py-1.5 pr-2">Réponse</th>
              <th className="py-1.5 pr-2">Pouvoir à</th>
              <th className="py-1.5" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {p.lignes.map((l) => (
              <tr key={l.personne_id}>
                <td className="py-1.5 pr-2">
                  <span className="font-medium text-slate-800">{l.nom}</span>
                  <span className="block text-xs text-slate-500">
                    lot{l.lots.length > 1 ? "s" : ""} {l.lots.join(", ")}
                    {l.mandats > 0 && ` · représente ${l.mandats} copropriétaire(s)`}
                  </span>
                </td>
                <td className="py-1.5 pr-2 tabular-nums">{l.voix.toLocaleString("fr-FR")}</td>
                <td className="py-1.5 pr-2">
                  <select className="rounded border border-slate-300 bg-white px-1.5 py-1 text-xs" value={l.reponse}
                    onChange={(e) => saisir(l, { reponse: e.target.value })}>
                    <option value="" disabled>Sans réponse</option>
                    {Object.entries(COURT).filter(([k]) => k).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                  {l.source === "syndic" && <span className="ml-1 text-xs text-slate-400" title="Saisi par le syndic">✎</span>}
                </td>
                <td className="py-1.5 pr-2">
                  {l.reponse === "pouvoir" && (
                    <select className="rounded border border-slate-300 bg-white px-1.5 py-1 text-xs" value={l.mandataire_id ?? ""}
                      onChange={(e) => saisir(l, { reponse: "pouvoir", mandataire_id: e.target.value ? Number(e.target.value) : null })}>
                      <option value="">— choisir —</option>
                      {p.lignes.filter((x) => x.personne_id !== l.personne_id && x.peut_recevoir_pouvoir).map((x) => (
                        <option key={x.personne_id} value={x.personne_id}>{x.nom}</option>
                      ))}
                    </select>
                  )}
                  {l.mandataire_absent && <span className="block text-xs text-amber-700">le mandataire ne sera pas présent</span>}
                </td>
                <td className="py-1.5 text-right whitespace-nowrap text-xs">
                  {l.reponse === "pouvoir" && l.mandataire_id && (<>
                    <label className="mr-2 inline-flex items-center gap-1 text-slate-600">
                      <input type="checkbox" checked={!!l.pouvoir_recu_le} onChange={(e) => saisir(l, { pouvoir_recu: e.target.checked })} />
                      signé reçu
                    </label>
                    <a className="text-indigo-600 hover:underline" href={`/api/ag/${agId}/pouvoirs/${l.personne_id}`}>PDF</a>
                  </>)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-slate-500">{RAPPEL_ART22} Les copropriétaires répondent par le lien de l'e-mail ou
        depuis leur compte, jusqu'à l'ouverture de l'assemblée ; vous pouvez corriger à tout moment.</p>
    </div>
  );
}

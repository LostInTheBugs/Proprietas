import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Badge, Card } from "../components/ui";

interface Immeuble {
  id: number;
  nom: string;
  ville: string;
  principale: boolean;
  lots: number;
  budget: number;
  encaisse: number;
  depense: number;
  solde: number;
  impayes: number;
  nb_lots_retard: number;
  ft_encours: number;
  relance_auto: boolean;
  prochaine_ag: string | null;
  prochaine_ag_heure: string;
}

interface AgProchaine {
  ag_id: number;
  copro_id: number;
  copro_nom: string;
  date: string;
  heure: string;
  type: string;
  statut: string;
}

interface Consolide {
  immeubles: Immeuble[];
  totaux: {
    immeubles: number;
    lots: number;
    budget: number;
    encaisse: number;
    depense: number;
    solde: number;
    impayes: number;
    ft_encours: number;
  };
  ags_prochaines: AgProchaine[];
}

const EUR = (v: number) =>
  `${v.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;

const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
const fmtDate = (iso: string) => {
  const d = new Date(iso + "T00:00:00");
  return `${d.getDate()} ${MOIS[d.getMonth()]} ${d.getFullYear()}`;
};

export default function Consolide() {
  const [data, setData] = useState<Consolide | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const nav = useNavigate();

  useEffect(() => {
    api.get<Consolide>("/consolide").then(setData).catch(() => {});
  }, []);

  async function ouvrir(id: number) {
    setBusyId(id);
    try {
      await api.post(`/auth/switch-copro/${id}`);
      window.location.href = "/";
    } catch {
      setBusyId(null);
    }
  }

  if (!data) return <p className="p-8 text-sm text-slate-500">Chargement…</p>;

  const t = data.totaux;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-800">Vue consolidée</h1>
        <p className="text-sm text-slate-500">
          {t.immeubles} immeuble{t.immeubles > 1 ? "s" : ""} · {t.lots} lots — exercice courant
        </p>
      </div>

      {/* KPI globaux */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card title="Budget total">
          <p className="text-lg font-bold text-slate-800">{EUR(t.budget)}</p>
          <p className="text-xs text-slate-400">tous immeubles confondus</p>
        </Card>
        <Card title="Encaissé">
          <p className="text-lg font-bold text-emerald-600">{EUR(t.encaisse)}</p>
          <p className="text-xs text-slate-400">dont fonds travaux : {EUR(t.ft_encours)} d'encours</p>
        </Card>
        <Card title="Dépensé">
          <p className="text-lg font-bold text-rose-600">{EUR(t.depense)}</p>
          <p className="text-xs text-slate-400">solde de caisse : {EUR(t.solde)}</p>
        </Card>
        <Card title="Impayés">
          <p className={`text-lg font-bold ${t.impayes > 0.005 ? "text-amber-600" : "text-slate-800"}`}>
            {EUR(t.impayes)}
          </p>
          <p className="text-xs text-slate-400">à relancer</p>
        </Card>
      </div>

      {/* Tableau par immeuble */}
      <Card title="Par immeuble">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2 font-medium">Immeuble</th>
                <th className="px-3 py-2 text-right font-medium">Lots</th>
                <th className="px-3 py-2 text-right font-medium">Budget</th>
                <th className="px-3 py-2 text-right font-medium">Encaissé</th>
                <th className="px-3 py-2 text-right font-medium">Dépensé</th>
                <th className="px-3 py-2 text-right font-medium">Impayés</th>
                <th className="px-3 py-2 text-right font-medium">Fonds trav.</th>
                <th className="px-3 py-2 font-medium">Prochaine AG</th>
                <th className="px-3 py-2 font-medium">Relances</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {data.immeubles.map((i) => (
                <tr key={i.id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="px-3 py-2.5">
                    <span className="font-medium text-slate-800">{i.nom}</span>
                    {i.ville && <span className="block text-xs text-slate-400">{i.ville}</span>}
                  </td>
                  <td className="px-3 py-2.5 text-right text-slate-600">{i.lots}</td>
                  <td className="px-3 py-2.5 text-right text-slate-600">{EUR(i.budget)}</td>
                  <td className="px-3 py-2.5 text-right text-emerald-600">{EUR(i.encaisse)}</td>
                  <td className="px-3 py-2.5 text-right text-rose-600">{EUR(i.depense)}</td>
                  <td className="px-3 py-2.5 text-right">
                    {i.impayes > 0.005 ? (
                      <span className="font-medium text-amber-600">
                        {EUR(i.impayes)}
                        {i.nb_lots_retard > 0 && <span className="text-xs text-slate-400"> ({i.nb_lots_retard})</span>}
                      </span>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right text-slate-600">{EUR(i.ft_encours)}</td>
                  <td className="px-3 py-2.5">
                    {i.prochaine_ag ? (
                      <span className="text-slate-700">
                        {fmtDate(i.prochaine_ag)}
                        {i.prochaine_ag_heure && <span className="text-xs text-slate-400"> à {i.prochaine_ag_heure}</span>}
                      </span>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    {i.relance_auto ? <Badge color="green">Auto</Badge> : <span className="text-slate-300">—</span>}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <button
                      onClick={() => ouvrir(i.id)}
                      disabled={busyId === i.id}
                      className="rounded-lg bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                    >
                      {busyId === i.id ? "…" : "Ouvrir"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Prochaines AG */}
      <Card title="Prochaines assemblées générales">
        {data.ags_prochaines.length === 0 ? (
          <p className="text-sm text-slate-400">Aucune AG planifiée.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {data.ags_prochaines.map((ag) => (
              <li key={ag.ag_id} className="flex items-center gap-3 py-2">
                <span className="w-24 shrink-0 text-sm font-medium text-slate-700">{fmtDate(ag.date)}</span>
                {ag.heure && <span className="w-14 shrink-0 text-xs text-slate-400">{ag.heure}</span>}
                <span className="min-w-0 flex-1 truncate text-sm text-slate-600">
                  {ag.copro_nom}
                  <span className="ml-1 text-xs text-slate-400">
                    {ag.type === "extraordinaire" ? "AG extraordinaire" : ag.type === "consultation_ecrite" ? "Consultation écrite" : "AG annuelle"}
                  </span>
                </span>
                <Badge color={ag.statut === "convoquee" ? "indigo" : "amber"}>
                  {ag.statut === "convoquee" ? "Convoquée" : "Projet"}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

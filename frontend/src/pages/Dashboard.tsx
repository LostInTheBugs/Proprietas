import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useUser } from "../auth";
import type { Recap, Mouvement, Travaux, InvitationsResult } from "../types";
import { fmtEUR, fmtDate } from "../types";
import { Card, Stat, Badge, Empty } from "../components/ui";

const MOIS_COURTS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

export default function Dashboard() {
  const { user } = useUser();
  const isSyndic = user?.role === "syndic";
  const [recap, setRecap] = useState<Recap | null>(null);
  const [mouvements, setMouvements] = useState<Mouvement[]>([]);
  const [travaux, setTravaux] = useState<Travaux[]>([]);
  const [envoiSituation, setEnvoiSituation] = useState<InvitationsResult | null>(null);
  const [busySituation, setBusySituation] = useState(false);

  const load = useCallback(async () => {
    const r = await api.get<Recap>("/recap");
    setRecap(r);
    if (r.exercice_id) {
      try {
        const [m, t] = await Promise.all([
          api.get<Mouvement[]>(`/exercices/${r.exercice_id}/mouvements`),
          api.get<Travaux[]>("/travaux"),
        ]);
        setMouvements(m);
        setTravaux(t);
      } catch { /* non bloquant */ }
    }
  }, []);
  useEffect(() => { load().catch(() => {}); }, [load]);

  if (!recap || recap.annee === 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-xl font-bold text-slate-800">Tableau de bord</h1>
        <Empty text="Aucun exercice pour le moment. Créez l'exercice en cours dans l'onglet Comptes, puis ajoutez le budget prévisionnel et les appels de fonds." />
      </div>
    );
  }

  const tauxRecouvrement = recap.budget_previsionnel > 0 ? (recap.encaisse / recap.budget_previsionnel) * 100 : 0;
  const impayes = recap.lots.filter((l) => l.solde > 0.01);
  const totalImpayes = impayes.reduce((s, l) => s + l.solde, 0);

  // Trésorerie mensuelle (exercice = année civile)
  const mois = Array.from({ length: 12 }, (_, i) => ({
    encaisse: mouvements.filter((m) => m.type === "encaissement" && new Date(m.date).getMonth() === i)
      .reduce((s, m) => s + m.montant, 0),
    depense: mouvements.filter((m) => m.type === "depense" && new Date(m.date).getMonth() === i)
      .reduce((s, m) => s + m.montant, 0),
  }));
  const maxMensuel = Math.max(1, ...mois.map((m) => Math.max(m.encaisse, m.depense)));

  // Fonds de travaux
  const ftEncaisse = mouvements.filter((m) => m.type === "encaissement" && m.categorie === "fonds_travaux")
    .reduce((s, m) => s + m.montant, 0);
  const ftDepense = mouvements.filter((m) => m.type === "depense" && m.categorie === "fonds_travaux")
    .reduce((s, m) => s + m.montant, 0);
  const objectifFt = recap.budget_previsionnel * 0.05;
  const ftPct = objectifFt > 0 ? Math.min(100, (ftEncaisse / objectifFt) * 100) : 0;

  // PPT par année
  const parAnnee = travaux.reduce<Record<number, number>>((acc, t) => {
    acc[t.annee] = (acc[t.annee] ?? 0) + t.montant;
    return acc;
  }, {});
  const annees = Object.keys(parAnnee).map(Number).sort();
  const maxAnnee = Math.max(1, ...annees.map((a) => parAnnee[a]));
  const anneeCourante = new Date().getFullYear();

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Tableau de bord</h1>
          <p className="text-sm text-slate-500">Exercice {recap.annee}</p>
        </div>
        <Link
          to="/comptes"
          className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700"
        >
          Gérer les comptes
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Budget prévisionnel" value={fmtEUR(recap.budget_previsionnel)} />
        <Stat label="Encaissé" value={fmtEUR(recap.encaisse)} sub={`${tauxRecouvrement.toFixed(0)} % du budget`} accent />
        <Stat label="Dépensé" value={fmtEUR(recap.depense)} sub={`Solde en caisse : ${fmtEUR(recap.solde_caisse)}`} />
        <Stat label="Fonds de travaux" value={fmtEUR(recap.fonds_travaux_encaisse)} sub="Cotisations encaissées" />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Trésorerie mensuelle */}
        <Card
          title="Trésorerie mensuelle"
          action={
            <div className="flex items-center gap-3 text-xs text-slate-500">
              <span className="flex items-center gap-1.5">
                <span className="inline-block h-2.5 w-2.5 rounded-sm bg-indigo-600" /> Encaissements
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block h-2.5 w-2.5 rounded-sm bg-rose-500" /> Dépenses
              </span>
            </div>
          }
        >
          {mouvements.length === 0 ? (
            <Empty text="Aucun mouvement sur l'exercice — le graphique apparaîtra dès les premiers encaissements ou dépenses." />
          ) : (
            <div>
              <svg viewBox="0 0 560 190" className="w-full" role="img" aria-label="Trésorerie mensuelle">
                {/* ligne de base */}
                <line x1="0" y1="160" x2="560" y2="160" className="chart-axis" strokeWidth="1" />
                {[0, 1, 2, 3].map((i) => (
                  <line key={i} x1="0" y1={160 - i * 38} x2="560" y2={160 - i * 38} className="chart-grid" strokeWidth="1" />
                ))}
                {mois.map((m, i) => {
                  const x = 12 + i * 44;
                  const hE = (m.encaisse / maxMensuel) * 120;
                  const hD = (m.depense / maxMensuel) * 120;
                  return (
                    <g key={i}>
                      <rect x={x} y={160 - hE} width="16" height={hE} rx="2" fill="#4f46e5" opacity={hE > 0 ? 1 : 0.25}>
                        <title>{`${fmtEUR(m.encaisse)} encaissés en ${new Date(2026, i, 1).toLocaleDateString("fr-FR", { month: "long" })}`}</title>
                      </rect>
                      <rect x={x + 19} y={160 - hD} width="16" height={hD} rx="2" fill="#f43f5e" opacity={hD > 0 ? 1 : 0.25}>
                        <title>{`${fmtEUR(m.depense)} dépensés en ${new Date(2026, i, 1).toLocaleDateString("fr-FR", { month: "long" })}`}</title>
                      </rect>
                      <text x={x + 17} y="177" textAnchor="middle" fontSize="10" fill="#94a3b8">{MOIS_COURTS[i]}</text>
                    </g>
                  );
                })}
              </svg>
              <div className="mt-1 flex items-center justify-between text-xs text-slate-500">
                <span>
                  Total encaissé : <b className="text-indigo-700">{fmtEUR(mois.reduce((s, m) => s + m.encaisse, 0))}</b>
                </span>
                <span>
                  Total dépensé : <b className="text-rose-600">{fmtEUR(mois.reduce((s, m) => s + m.depense, 0))}</b>
                </span>
              </div>
            </div>
          )}
        </Card>

        {/* Fonds de travaux + PPT */}
        <div className="space-y-6">
          <Card
            title="Fonds de travaux — progression"
            action={
              isSyndic ? (
                <button
                  onClick={async () => {
                    setBusySituation(true);
                    setEnvoiSituation(null);
                    try {
                      const res = await api.post<InvitationsResult>("/export/situation-fonds");
                      setEnvoiSituation(res);
                    } finally {
                      setBusySituation(false);
                    }
                  }}
                  disabled={busySituation}
                  className="rounded-lg bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
                  title="Envoyer la situation du fonds de travaux à tous les copropriétaires"
                >
                  {busySituation ? "Envoi…" : "✉️ Envoyer la situation"}
                </button>
              ) : undefined
            }
          >
            {envoiSituation && (
              <p className="mb-2 rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
                ✅ {envoiSituation.envoyes} email(s) envoyé(s)
                {envoiSituation.sans_email > 0 && ` · ${envoiSituation.sans_email} sans email`}
                {envoiSituation.erreurs.length > 0 && ` · ${envoiSituation.erreurs.length} erreur(s)`}
              </p>
            )}
            <div className="mb-2 flex items-end justify-between">
              <div>
                <p className="text-2xl font-bold text-indigo-700">{fmtEUR(ftEncaisse)}</p>
                <p className="text-xs text-slate-500">
                  encaissé · objectif annuel minimal : {fmtEUR(objectifFt)} (5 % du budget)
                </p>
              </div>
              <p className="text-sm font-semibold text-slate-600">{ftPct.toFixed(0)} %</p>
            </div>
            <div className="h-3 w-full overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 transition-all"
                style={{ width: `${ftPct}%` }}
              />
            </div>
            <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
              <span>
                Dépensé depuis le fonds : <b className="text-slate-700">{fmtEUR(ftDepense)}</b>
              </span>
              <span>
                Encours : <b className={ftEncaisse - ftDepense >= 0 ? "text-emerald-600" : "text-red-600"}>{fmtEUR(ftEncaisse - ftDepense)}</b>
              </span>
            </div>
          </Card>

          <Card title="Plan pluriannuel de travaux" action={
            travaux.length > 0 ? (
              <span className="text-xs font-semibold text-slate-500">
                Total : {fmtEUR(annees.reduce((s, a) => s + parAnnee[a], 0))}
              </span>
            ) : undefined
          }>
            {annees.length === 0 ? (
              <Empty text="Aucun travaux planifié — ajoutez-les dans l'onglet Travaux pour visualiser l'échéancier ici." />
            ) : (
              <div className="space-y-2.5">
                {annees.map((a) => {
                  const pct = (parAnnee[a] / maxAnnee) * 100;
                  const enCours = a <= anneeCourante;
                  return (
                    <div key={a}>
                      <div className="mb-1 flex items-center justify-between text-xs">
                        <span className="font-medium text-slate-600">
                          {a} {enCours ? "· en cours" : ""}
                        </span>
                        <span className="tabular-nums font-semibold text-slate-700">{fmtEUR(parAnnee[a])}</span>
                      </div>
                      <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
                        <div
                          className={`h-full rounded-full ${enCours ? "bg-amber-500" : "bg-indigo-500"}`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Situation par lot (état daté)">
          {recap.lots.length === 0 ? (
            <Empty text="Aucun lot — créez les lots dans l'onglet Lots & occupants." />
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="pb-2 font-medium">Lot</th>
                  <th className="pb-2 text-right font-medium">Appels</th>
                  <th className="pb-2 text-right font-medium">Payé</th>
                  <th className="pb-2 text-right font-medium">Solde</th>
                  <th className="pb-2 text-right font-medium" />
                </tr>
              </thead>
              <tbody>
                {recap.lots.map((l) => (
                  <tr key={l.lot.id} className="border-b border-slate-50 last:border-0">
                    <td className="py-2.5">
                      <span className="font-medium text-slate-800">Lot {l.lot.numero}</span>
                      {l.lot.designation && <span className="ml-2 text-xs text-slate-500">{l.lot.designation}</span>}
                    </td>
                    <td className="py-2.5 text-right tabular-nums text-slate-600">
                      {fmtEUR(l.appels_charges + l.appels_fonds)}
                    </td>
                    <td className="py-2.5 text-right tabular-nums text-slate-600">{fmtEUR(l.encaisse)}</td>
                    <td className="py-2.5 text-right">
                      {Math.abs(l.solde) < 0.01 ? (
                        <span className="font-medium text-emerald-600">À jour</span>
                      ) : l.solde > 0 ? (
                        <span className="font-semibold text-red-600">{fmtEUR(l.solde)}</span>
                      ) : (
                        <span className="font-medium text-emerald-600">{fmtEUR(l.solde)}</span>
                      )}
                    </td>
                    <td className="py-2.5 text-right">
                      <a
                        href={`/api/export/quittances/${recap.exercice_id}?lot_id=${l.lot.id}`}
                        className="rounded-lg px-2 py-1 text-xs font-medium text-slate-500 hover:bg-slate-100 hover:text-indigo-600"
                        title="Quittance du lot en PDF"
                      >
                        🧾 Quittance
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="Impayés">
          {impayes.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-6 text-center">
              <span className="text-3xl">✅</span>
              <p className="text-sm text-slate-600">Tous les lots sont à jour.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {impayes.map((l) => (
                <div key={l.lot.id} className="flex items-center justify-between rounded-lg bg-red-50/60 px-3 py-2.5">
                  <div>
                    <p className="text-sm font-medium text-slate-800">Lot {l.lot.numero}</p>
                    <p className="text-xs text-slate-500">
                      {l.appels_charges + l.appels_fonds > 0
                        ? `${((l.encaisse / (l.appels_charges + l.appels_fonds)) * 100).toFixed(0)} % payé`
                        : "aucun appel"}
                    </p>
                  </div>
                  <span className="text-sm font-bold text-red-600">{fmtEUR(l.solde)}</span>
                </div>
              ))}
              <p className="pt-1 text-sm text-slate-600">
                Total des impayés : <span className="font-bold text-red-600">{fmtEUR(totalImpayes)}</span>
              </p>
            </div>
          )}
        </Card>
      </div>

      {recap.appels_en_cours > 0 && (
        <div className="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <Badge color="amber">{recap.appels_en_cours}</Badge>
          <span>appel(s) de fonds émis avec une date d'échéance définie sur l'exercice {recap.annee}.</span>
        </div>
      )}
    </div>
  );
}

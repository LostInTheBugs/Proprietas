import { useEffect, useState } from "react";
import { api, uploadDocument } from "../api";
import { useUser } from "../auth";
import type { Exercice, BudgetLine, Appel, Mouvement, Recap, Lot, Regularisation, Repartition, Contrat,
  Document as DocumentFichier } from "../types";
import { fmtEUR, fmtDate } from "../types";
import { Button, Card, Input, Modal, Select, Badge, Empty } from "../components/ui";
import { TableMouvements } from "../components/TableMouvements";

export default function Comptes() {
  const { user } = useUser();
  const isSyndic = user?.role === "syndic";
  const [exercices, setExercices] = useState<Exercice[]>([]);
  const [exId, setExId] = useState<number | null>(null);
  const [budget, setBudget] = useState<BudgetLine[]>([]);
  const [appels, setAppels] = useState<Appel[]>([]);
  const [mouvements, setMouvements] = useState<Mouvement[]>([]);
  const [lots, setLots] = useState<Lot[]>([]);
  const [contrats, setContrats] = useState<Contrat[]>([]);
  const [documents, setDocuments] = useState<DocumentFichier[]>([]);
  const [recap, setRecap] = useState<Recap | null>(null);
  const [modal, setModal] = useState<null | "exercice" | "budget" | "appel" | "mouvement" | "paiement">(null);
  const [mouvementEdite, setMouvementEdite] = useState<Mouvement | null>(null);
  const [budgetEdite, setBudgetEdite] = useState<BudgetLine | null>(null);
  const [reclassement, setReclassement] = useState<Reclassement | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Exercice[]>("/exercices").then((list) => {
      setExercices(list);
      if (list.length > 0) {
        const courant = list.find((e) => !e.cloture) ?? list[0];
        setExId(courant.id);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!exId) return;
    api.get<BudgetLine[]>(`/exercices/${exId}/budget`).then(setBudget).catch(() => {});
    api.get<Appel[]>(`/exercices/${exId}/appels`).then(setAppels).catch(() => {});
    api.get<Mouvement[]>(`/exercices/${exId}/mouvements`).then(setMouvements).catch(() => {});
    api.get<Lot[]>("/lots").then(setLots).catch(() => {});
    api.get<Contrat[]>("/contrats").then(setContrats).catch(() => {});
    api.get<DocumentFichier[]>("/documents").then(setDocuments).catch(() => {});
    api.get<Recap>("/recap").then(setRecap).catch(() => {});
  }, [exId]);

  const totalBudget = budget.reduce((s, b) => s + b.montant, 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Comptes</h1>
          <p className="text-sm text-slate-500">
            {recap?.regime_petite_copro
              ? "Comptabilité simplifiée (régime petite copropriété, art. 41-8)"
              : "Comptabilité (régime général de la loi du 10 juillet 1965)"}
          </p>
          {recap && (
            <p className="text-xs text-slate-400">
              Art. 41-8 : {recap.nb_lots_principaux} lot(s) de logements, bureaux ou commerces (seuil : 5 au plus) ·
              budget moyen sur 3 exercices consécutifs :{" "}
              {recap.budget_moyen_3_exercices === null
                ? "non disponible"
                : fmtEUR(recap.budget_moyen_3_exercices)}{" "}
              (seuil : moins de 15 000 €)
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {exercices.length > 0 && (
            <Select value={exId ?? ""} onChange={(e) => setExId(Number(e.target.value))} className="w-40">
              {exercices.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.annee} {e.cloture ? "(clôturé)" : ""}
                </option>
              ))}
            </Select>
          )}
          {exId && (
            <div className="flex items-center gap-2">
              <a
                href={`/api/export/quittances/${exId}`}
                className="rounded-lg bg-slate-100 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200"
                title="Télécharger les quittances de tous les lots en PDF"
              >
                🧾 Quittances (PDF)
              </a>
              <a
                href={`/api/export/compte-gestion/${exId}`}
                className="rounded-lg bg-slate-100 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200"
                title="Télécharger le compte de gestion de l'exercice en PDF"
              >
                📊 Compte de gestion (PDF)
              </a>
              <a
                href={`/api/export/rapport-annuel/${exId}`}
                className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700"
                title="Rapport annuel complet : garde + compte de gestion + statistiques + plan de travaux (PDF)"
              >
                📑 Rapport annuel (PDF)
              </a>
              <a
                href={`/api/export/compte-gestion?exercice_id=${exId}`}
                className="rounded-lg bg-slate-100 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-200"
                title="Grand livre comptable de l'exercice au format CSV (Excel)"
              >
                📥 CSV
              </a>
            </div>
          )}
          {isSyndic && (
            <>
              <Button onClick={() => setModal("exercice")}>+ Exercice</Button>
              <Button onClick={() => setModal("budget")} disabled={!exId}>+ Ligne budget</Button>
              <Button onClick={() => setModal("appel")} disabled={!exId}>+ Appel de fonds</Button>
              <Button variant="secondary" onClick={() => setModal("mouvement")} disabled={!exId}>
                + Mouvement
              </Button>
              <Button variant="secondary" onClick={() => setModal("paiement")} disabled={lots.length === 0}>
                + Paiement copropriétaire
              </Button>
            </>
          )}
        </div>
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {exId && (() => {
        const ex = exercices.find((e) => e.id === exId);
        return ex ? (
          <>
            <ExerciceStatut key={ex.id} ex={ex} isSyndic={isSyndic} onError={setError}
              onSaved={(maj) => setExercices((l) => l.map((e) => (e.id === maj.id ? maj : e)))} />
            {isSyndic && ex.comptes_approuves_le && (
              <RegularisationPanel key={`reg-${ex.id}-${ex.comptes_approuves_le}`} exId={ex.id} onError={setError}
                onCreated={() => api.get<Appel[]>(`/exercices/${ex.id}/appels`).then(setAppels).catch(() => {})} />
            )}
          </>
        ) : null;
      })()}

      {!exId ? (
        <Empty text="Aucun exercice. Créez l'exercice de l'année en cours pour commencer." />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Budget prévisionnel</p>
              <p className="mt-1.5 text-2xl font-bold tabular-nums text-slate-800">{fmtEUR(totalBudget)}</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Encaissé</p>
              <p className="mt-1.5 text-2xl font-bold tabular-nums text-emerald-600">{fmtEUR(recap?.encaisse ?? 0)}</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Dépensé</p>
              <p className="mt-1.5 text-2xl font-bold tabular-nums text-slate-800">{fmtEUR(recap?.depense ?? 0)}</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Solde en caisse</p>
              <p className="mt-1.5 text-2xl font-bold tabular-nums text-indigo-600">{fmtEUR(recap?.solde_caisse ?? 0)}</p>
            </div>
          </div>

          <div className="grid gap-6 xl:grid-cols-2">
            <Card title="Budget prévisionnel">
              {budget.length === 0 ? (
                <Empty text="Aucune ligne de budget. Ajoutez les postes prévus (entretien, assurance, énergie…)." />
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
                      <th className="pb-2 font-medium">Poste</th>
                      <th className="pb-2 text-right font-medium">Montant</th>
                      <th className="pb-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {budget.map((b) => (
                      <tr key={b.id} className="border-b border-slate-50 last:border-0">
                        <td className="py-2.5 text-slate-700">{b.libelle}</td>
                        <td className="py-2.5 text-right tabular-nums text-slate-700">{fmtEUR(b.montant)}</td>
                        <td className="py-2.5 text-right">
                          {isSyndic && (
                            <>
                              <Button variant="ghost" className="px-2 py-1 text-xs"
                                onClick={() => setBudgetEdite(b)}>
                                Modifier
                              </Button>
                              <Button
                                variant="ghost"
                                className="px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                                onClick={async () => { await api.del(`/budget/${b.id}`); refresh(); }}
                              >
                                Suppr.
                              </Button>
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                    <tr>
                      <td className="py-2.5 font-semibold text-slate-800">Total</td>
                      <td className="py-2.5 text-right font-bold tabular-nums text-slate-800">{fmtEUR(totalBudget)}</td>
                      <td />
                    </tr>
                  </tbody>
                </table>
              )}
            </Card>

            <Card title="Appels de fonds">
              {appels.length === 0 ? (
                <Empty text="Aucun appel de fonds. Les appels sont répartis automatiquement entre les lots au prorata des millièmes." />
              ) : (
                <div className="space-y-3">
                  {appels.map((a) => (
                    <div key={a.id} className="rounded-lg border border-slate-200 p-3">
                      <div className="flex items-start justify-between">
                        <div>
                          <p className="font-medium text-slate-800">{a.libelle}</p>
                          <p className="text-xs text-slate-500">
                            Émis le {fmtDate(a.date_emission)}
                            {a.date_echeance && <> · échéance {fmtDate(a.date_echeance)}</>}
                          </p>
                        </div>
                        <div className="text-right">
                          <p className="font-bold tabular-nums text-slate-800">{fmtEUR(a.montant_total)}</p>
                          {a.inclut_fonds_travaux && (
                            <p className="text-xs text-indigo-600">dont fonds travaux {fmtEUR(a.fonds_travaux_montant)}</p>
                          )}
                        </div>
                      </div>
                      <div className="mt-2 grid grid-cols-2 gap-1 text-xs sm:grid-cols-4">
                        {a.parts.map((p) => (
                          <div key={p.id} className="rounded bg-slate-50 px-2 py-1.5">
                            <span className="font-medium text-slate-600">Lot {p.lot_numero}</span>
                            <span className="block tabular-nums text-slate-700">{fmtEUR(p.montant_charges)}</span>
                            {p.montant_fonds_travaux > 0 && (
                              <span className="text-indigo-600">+ {fmtEUR(p.montant_fonds_travaux)} FT</span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>

          <Card
            title={`Mouvements (encaissements & dépenses) — ${recap ? fmtEUR(recap.encaisse - recap.depense) : ""}`}
            action={
              <a href={`/api/export/compte-gestion`} className="text-xs font-medium text-indigo-600 hover:text-indigo-700">
                Export compte de gestion ↓
              </a>
            }
          >
            {(() => {
              const annee = exercices.find((e) => e.id === exId)?.annee;
              const hors = mouvements.filter((m) => annee && Number(m.date.slice(0, 4)) !== annee);
              if (!isSyndic || hors.length === 0) return null;
              return (
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
                  <span>{hors.length} mouvement(s) daté(s) d'une autre année que l'exercice {annee}.</span>
                  <Button variant="secondary" className="px-2 py-1 text-xs" onClick={async () => {
                    try {
                      setReclassement(await api.post<Reclassement>(`/exercices/${exId}/mouvements/reclasser`, { simuler: true }));
                    } catch (e) { setError(e instanceof Error ? e.message : "Erreur"); }
                  }}>Les déplacer vers l'exercice de leur année…</Button>
                </div>
              );
            })()}
            <TableMouvements mouvements={mouvements} exercices={exercices} exId={exId} lots={lots} contrats={contrats}
              documents={documents} isSyndic={isSyndic} onEdit={setMouvementEdite}
              onDelete={async (m) => { await api.del(`/mouvements/${m.id}`); refresh(); }}
              onChanged={refresh} onError={setError} />
          </Card>
        </>
      )}

      {modal === "exercice" && (
        <ExerciceModal onClose={() => setModal(null)} onSaved={(id) => { setModal(null); refresh(); setExId(id); }} onError={setError} />
      )}
      {modal === "budget" && exId && (
        <BudgetModal exId={exId} onClose={() => setModal(null)} onSaved={() => { setModal(null); refresh(); }} onError={setError} />
      )}
      {modal === "appel" && exId && (
        <AppelModal exId={exId} lots={lots} onClose={() => setModal(null)} onSaved={() => { setModal(null); refresh(); }} onError={setError} />
      )}
      {modal === "mouvement" && exId && (
        <MouvementModal exId={exId} exercices={exercices} lots={lots} contrats={contrats} documents={documents}
          onClose={() => setModal(null)} onSaved={() => { setModal(null); refresh(); }} onError={setError} />
      )}
      {modal === "paiement" && (
        <PaiementModal lots={lots} onClose={() => setModal(null)}
          onSaved={() => { setModal(null); refresh(); }} onError={setError} />
      )}
      {mouvementEdite && exId && (
        <MouvementModal exId={exId} exercices={exercices} lots={lots} contrats={contrats} documents={documents}
          initial={mouvementEdite} onClose={() => setMouvementEdite(null)}
          onSaved={() => { setMouvementEdite(null); refresh(); }} onError={setError} />
      )}
      {reclassement && exId && (
        <Modal open title="Déplacer vers l'exercice de leur année" onClose={() => setReclassement(null)}>
          <div className="space-y-3 text-sm">
            <p className="text-slate-600">
              Ces mouvements sont datés d'une autre année que l'exercice affiché. Chacun sera rangé dans l'exercice
              de l'année de sa date (créé s'il n'existe pas encore).
            </p>
            <table className="w-full">
              <tbody>
                {reclassement.mouvements.map((m) => (
                  <tr key={m.id} className="border-b border-slate-50 last:border-0">
                    <td className="py-1 text-slate-600">{fmtDate(m.date)}</td>
                    <td className="py-1">{m.libelle}</td>
                    <td className="py-1 text-right tabular-nums">{m.type === "encaissement" ? "+" : "−"}{fmtEUR(m.montant)}</td>
                    <td className="py-1 pl-2 text-right text-slate-500">→ {m.vers}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setReclassement(null)}>Annuler</Button>
              <Button onClick={async () => {
                try {
                  await api.post(`/exercices/${exId}/mouvements/reclasser`, { simuler: false });
                  setReclassement(null);
                  refresh();
                } catch (e) { setError(e instanceof Error ? e.message : "Erreur"); setReclassement(null); }
              }}>Déplacer {reclassement.mouvements.length} mouvement(s)</Button>
            </div>
          </div>
        </Modal>
      )}
      {budgetEdite && exId && (
        <BudgetModal exId={exId} initial={budgetEdite} onClose={() => setBudgetEdite(null)}
          onSaved={() => { setBudgetEdite(null); refresh(); }} onError={setError} />
      )}
    </div>
  );

  async function refresh() {
    if (!exId) return;
    setBudget(await api.get(`/exercices/${exId}/budget`));
    setAppels(await api.get(`/exercices/${exId}/appels`));
    setMouvements(await api.get(`/exercices/${exId}/mouvements`));
    setRecap(await api.get("/recap"));
    setDocuments(await api.get("/documents"));
    setContrats(await api.get("/contrats"));
  }
}

// Clôture et approbation des comptes : deux étapes distinctes. L'art. 19-2 ne vise les restes
// dus des exercices précédents qu'« après approbation des comptes » par l'assemblée générale.
function ExerciceStatut({ ex, isSyndic, onSaved, onError }: {
  ex: Exercice; isSyndic: boolean; onSaved: (e: Exercice) => void; onError: (e: string) => void;
}) {
  const [cloture, setCloture] = useState(ex.cloture);
  const [approuve, setApprouve] = useState(ex.comptes_approuves_le ?? "");
  async function save() {
    try {
      onError("");
      onSaved(await api.put<Exercice>(`/exercices/${ex.id}`, {
        annee: ex.annee, cloture, comptes_approuves_le: approuve || null,
      }));
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  const resume = ex.comptes_approuves_le
    ? `Comptes ${ex.annee} approuvés par l'AG le ${fmtDate(ex.comptes_approuves_le)}`
    : ex.cloture ? `Exercice ${ex.annee} clôturé — comptes non encore approuvés` : `Exercice ${ex.annee} en cours`;
  return (
    <div className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm">
      <p className="flex-1 text-slate-600">{resume}</p>
      {isSyndic && (
        <>
          <label className="flex items-center gap-2 text-slate-600">
            <input type="checkbox" checked={cloture} onChange={(e) => setCloture(e.target.checked)} />
            Clôturé
          </label>
          <Input label="Comptes approuvés par l'AG le" type="date" value={approuve}
            onChange={(e) => setApprouve(e.target.value)} disabled={!cloture} />
          <Button variant="secondary" onClick={save}>Enregistrer</Button>
        </>
      )}
    </div>
  );
}

/** Régularisation des charges : écart par lot entre provisions et charges réelles, une fois
 *  les comptes approuvés (loi art. 14-1 ; décret art. 6-2, 3° : porté au compte du
 *  copropriétaire à la date de l'approbation). */
function RegularisationPanel({ exId, onError, onCreated }: {
  exId: number; onError: (e: string) => void; onCreated: () => void;
}) {
  const [reg, setReg] = useState<Regularisation | null>(null);
  const [echeance, setEcheance] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() + 30); return d.toISOString().slice(0, 10);
  });
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.get<Regularisation>(`/exercices/${exId}/regularisation`).then(setReg).catch(() => {});
  }, [exId]);
  async function creer() {
    setBusy(true);
    try {
      setReg(await api.post<Regularisation>(`/exercices/${exId}/regularisation`, { date_echeance: echeance }));
      onCreated();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
    finally { setBusy(false); }
  }
  if (!reg) return null;
  return (
    <Card title={`Régularisation des charges ${reg.annee}`}>
      <p className="mb-2 text-xs text-slate-500">
        Charges réelles (dépenses hors fonds de travaux et hors travaux, réparties aux tantièmes ; une dépense
        rattachée à un lot reste à ce lot) comparées aux provisions appelées. Le complément est appelé, le
        trop-perçu est crédité au copropriétaire actuel (décret du 17 mars 1967, art. 6-2). Le fonds de travaux
        n'est pas régularisé.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-500">
              <th className="py-1">Lot</th><th className="py-1 text-right">Provisions</th>
              <th className="py-1 text-right">Charges réelles</th><th className="py-1 text-right">Écart</th>
            </tr>
          </thead>
          <tbody>
            {reg.lignes.map((l) => (
              <tr key={l.lot_id} className="border-t border-slate-100">
                <td className="py-1">Lot {l.lot_numero}</td>
                <td className="py-1 text-right tabular-nums">{fmtEUR(l.provisions)}</td>
                <td className="py-1 text-right tabular-nums">{fmtEUR(l.charges_reelles)}</td>
                <td className={`py-1 text-right tabular-nums ${l.ecart > 0 ? "text-red-700" : l.ecart < 0 ? "text-emerald-700" : ""}`}>
                  {l.ecart > 0 ? `+${fmtEUR(l.ecart)} à appeler` : l.ecart < 0 ? `${fmtEUR(l.ecart)} crédité` : "—"}
                </td>
              </tr>
            ))}
            <tr className="border-t border-slate-200 font-medium">
              <td className="py-1">Total</td>
              <td className="py-1 text-right tabular-nums">{fmtEUR(reg.total_provisions)}</td>
              <td className="py-1 text-right tabular-nums">{fmtEUR(reg.total_charges_reelles)}</td>
              <td className="py-1 text-right tabular-nums">{fmtEUR(reg.total_ecart)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      {reg.appel_id ? (
        <p className="mt-2 text-xs text-emerald-700">Régularisation enregistrée (appel « Régularisation des charges {reg.annee} »).</p>
      ) : (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <Input label="Échéance du complément" type="date" value={echeance} onChange={(e) => setEcheance(e.target.value)} />
          <Button disabled={busy || !echeance} onClick={creer}>Enregistrer la régularisation</Button>
        </div>
      )}
    </Card>
  );
}

function ExerciceModal({ onClose, onSaved, onError }: { onClose: () => void; onSaved: (id: number) => void; onError: (e: string) => void }) {
  const [annee, setAnnee] = useState(String(new Date().getFullYear()));
  async function save() {
    try {
      const ex = await api.post<Exercice>("/exercices", { annee: Number(annee) });
      onSaved(ex.id);
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  return (
    <Modal open title="Nouvel exercice" onClose={onClose}>
      <div className="space-y-3">
        <Input label="Année" type="number" value={annee} onChange={(e) => setAnnee(e.target.value)} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>Créer</Button>
        </div>
      </div>
    </Modal>
  );
}

function BudgetModal({ exId, initial, onClose, onSaved, onError }: {
  exId: number; initial?: BudgetLine; onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const [libelle, setLibelle] = useState(initial?.libelle ?? "");
  const [montant, setMontant] = useState(initial ? String(initial.montant) : "");
  async function save() {
    try {
      const corps = { libelle, montant: Number(montant), type_repartition: initial?.type_repartition ?? "generale" };
      if (initial) await api.put(`/budget/${initial.id}`, corps);
      else await api.post(`/exercices/${exId}/budget`, corps);
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  return (
    <Modal open title={initial ? "Modifier la ligne de budget" : "Ligne de budget"} onClose={onClose}>
      <div className="space-y-3">
        <Input label="Poste" value={libelle} onChange={(e) => setLibelle(e.target.value)} placeholder="Entretien courant" />
        <Input label="Montant (€)" type="number" step="0.01" value={montant} onChange={(e) => setMontant(e.target.value)} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>{initial ? "Enregistrer" : "Ajouter"}</Button>
        </div>
      </div>
    </Modal>
  );
}

function AppelModal({ exId, lots, onClose, onSaved, onError }: { exId: number; lots: Lot[]; onClose: () => void; onSaved: () => void; onError: (e: string) => void }) {
  const [libelle, setLibelle] = useState("");
  const [montant, setMontant] = useState("");
  const [dateEmission, setDateEmission] = useState(new Date().toISOString().slice(0, 10));
  const [dateEcheance, setDateEcheance] = useState("");
  const [ft, setFt] = useState(true);
  async function save() {
    try {
      await api.post(`/exercices/${exId}/appels`, {
        libelle, montant_total: Number(montant), date_emission: dateEmission,
        date_echeance: dateEcheance || null, inclut_fonds_travaux: ft,
      });
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  return (
    <Modal open title="Appel de fonds" onClose={onClose}>
      <div className="space-y-3">
        <Input label="Libellé" value={libelle} onChange={(e) => setLibelle(e.target.value)} placeholder="Appel 1er trimestre 2026" />
        <Input label="Montant total (€)" type="number" step="0.01" value={montant} onChange={(e) => setMontant(e.target.value)} />
        <div className="grid grid-cols-2 gap-3">
          <Input label="Date d'émission" type="date" value={dateEmission} onChange={(e) => setDateEmission(e.target.value)} />
          <Input label="Échéance" type="date" value={dateEcheance} onChange={(e) => setDateEcheance(e.target.value)} />
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={ft} onChange={(e) => setFt(e.target.checked)} />
          Inclure la cotisation fonds de travaux (5 % du montant)
        </label>
        <p className="text-xs leading-relaxed text-slate-500">
          Le montant sera réparti automatiquement entre les {lots.length} lots au prorata des millièmes.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>Créer l'appel</Button>
        </div>
      </div>
    </Modal>
  );
}

function MouvementModal({ exId, exercices, lots, contrats, documents, initial, onClose, onSaved, onError }: {
  exId: number; exercices: Exercice[]; lots: Lot[]; contrats: Contrat[]; documents: DocumentFichier[];
  initial?: Mouvement; onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const [contratId, setContratId] = useState(initial?.contrat_id != null ? String(initial.contrat_id) : "");
  const [documentId, setDocumentId] = useState(initial?.document_id != null ? String(initial.document_id) : "");
  const [fichier, setFichier] = useState<File | null>(null);
  // Factures d'abord, puis les autres documents (les plus récents en tête).
  const docsTries = [...documents].sort((a, b) =>
    Number(b.categorie === "facture") - Number(a.categorie === "facture") || b.date_ajout.localeCompare(a.date_ajout));
  const [exerciceId, setExerciceId] = useState(String(initial?.exercice_id ?? exId));
  const [date, setDate] = useState(initial?.date ?? new Date().toISOString().slice(0, 10));
  const [libelle, setLibelle] = useState(initial?.libelle ?? "");
  // Par défaut une dépense (facture) : c'est la saisie la plus courante.
  const [type, setType] = useState(initial?.type ?? "depense");
  const [categorie, setCategorie] = useState(initial?.categorie ?? "charges");
  const [montant, setMontant] = useState(initial ? String(initial.montant) : "");
  const [lotId, setLotId] = useState(initial?.lot_id != null ? String(initial.lot_id) : "");
  async function save() {
    try {
      // Nouveau fichier joint : déposé dans Documents (catégorie facture), puis rattaché.
      let docId = documentId === "" ? null : Number(documentId);
      if (fichier) {
        const doc = await uploadDocument("facture", libelle || fichier.name, fichier);
        docId = doc.id;
      }
      const corps = {
        date, libelle, type, categorie, montant: Number(montant),
        lot_id: lotId === "" ? null : Number(lotId),
        appel_id: initial?.appel_id ?? null,
        exercice_id: Number(exerciceId),
        contrat_id: contratId === "" ? null : Number(contratId),
        document_id: docId,
      };
      if (initial) await api.put(`/mouvements/${initial.id}`, corps);
      else await api.post(`/exercices/${exerciceId}/mouvements`, corps);
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  return (
    <Modal open title={initial ? "Modifier le mouvement" : "Nouveau mouvement"} onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Input label="Date" type="date" value={date} onChange={(e) => {
            setDate(e.target.value);
            // Nouveau mouvement : l'exercice suit l'année de la date, s'il existe.
            const ex = exercices.find((x) => x.annee === Number(e.target.value.slice(0, 4)));
            if (!initial && ex) setExerciceId(String(ex.id));
          }} />
          <Select label="Exercice" value={exerciceId} onChange={(e) => setExerciceId(e.target.value)}>
            {exercices.map((ex) => <option key={ex.id} value={ex.id}>{ex.annee}</option>)}
          </Select>
        </div>
        {(() => {
          const annee = exercices.find((ex) => String(ex.id) === exerciceId)?.annee;
          return annee && date && Number(date.slice(0, 4)) !== annee ? (
            <p className="text-xs text-amber-700">
              La date est en {date.slice(0, 4)}, mais l'exercice choisi est {annee}. Vérifiez l'exercice.
            </p>
          ) : null;
        })()}
        <Input label="Libellé" value={libelle} onChange={(e) => setLibelle(e.target.value)} placeholder="Virement lot 2 / Facture EDF" />
        <div className="grid grid-cols-2 gap-3">
          <Select label="Type" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="depense">Dépense</option>
            <option value="encaissement">Encaissement</option>
          </Select>
          <Select label="Catégorie" value={categorie} onChange={(e) => setCategorie(e.target.value)}>
            <option value="charges">Charges</option>
            <option value="fonds_travaux">Fonds de travaux</option>
            <option value="travaux">Travaux</option>
            <option value="assurance">Assurance</option>
            <option value="energie">Énergie</option>
            <option value="entretien">Entretien</option>
            <option value="autre">Autre</option>
          </Select>
        </div>
        {type === "encaissement" && (
          <p className="text-xs text-slate-500">
            Catégorie « Fonds de travaux » ou « Travaux » : le versement ne paie que la part fonds de travaux des
            appels, et un excédent reste une avance travaux. Toute autre catégorie paie d'abord les charges.
          </p>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Input label="Montant (€)" type="number" step="0.01" value={montant} onChange={(e) => setMontant(e.target.value)} />
          <Select label="Lot (paiement ou dépense d'un seul lot)" value={lotId} onChange={(e) => setLotId(e.target.value)}>
            <option value="">Copro entière</option>
            {lots.map((l) => <option key={l.id} value={l.id}>Lot {l.numero}</option>)}
          </Select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Select label="Contrat" value={contratId} onChange={(e) => setContratId(e.target.value)}>
            <option value="">— aucun —</option>
            {contrats.map((c) => <option key={c.id} value={c.id}>{c.libelle}</option>)}
          </Select>
          <Select label="Facture (document)" value={documentId} disabled={!!fichier}
            onChange={(e) => setDocumentId(e.target.value)}>
            <option value="">— aucune —</option>
            {docsTries.map((d) => (
              <option key={d.id} value={d.id}>{d.libelle}{d.categorie !== "facture" ? ` (${d.categorie})` : ""}</option>
            ))}
          </Select>
        </div>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-600">ou joindre un nouveau fichier (PDF, image…)</span>
          <input type="file" className="block w-full text-sm text-slate-600"
            onChange={(e) => setFichier(e.target.files?.[0] ?? null)} />
          {fichier && (
            <span className="mt-1 block text-xs text-slate-500">
              Il sera rangé dans Documents (catégorie Facture) et rattaché à ce mouvement.
            </span>
          )}
        </label>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>Enregistrer</Button>
        </div>
      </div>
    </Modal>
  );
}

/** Un virement d'un copropriétaire réparti entre tous ses lots (plus ancienne échéance d'abord). */
function PaiementModal({ lots, onClose, onSaved, onError }: {
  lots: Lot[]; onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const proprietaires = Array.from(
    new Map(lots.filter((l) => l.proprietaire_id != null)
      .map((l) => [l.proprietaire_id as number, l.proprietaire_nom || `Compte #${l.proprietaire_id}`])).entries(),
  ).sort((a, b) => a[1].localeCompare(b[1]));
  const [proprietaireId, setProprietaireId] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [montant, setMontant] = useState("");
  const [libelle, setLibelle] = useState("Virement");
  const [rep, setRep] = useState<Repartition | null>(null);
  const [parts, setParts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const montantNum = Number(montant.replace(",", "."));
  useEffect(() => {
    setRep(null);
    if (!proprietaireId || !(montantNum > 0)) return;
    const t = setTimeout(() => {
      api.get<Repartition>(`/paiements/repartition?proprietaire_id=${proprietaireId}&montant=${montantNum}`)
        .then((r) => {
          setRep(r);
          setParts(Object.fromEntries(r.lots.flatMap((l) => [
            [`${l.lot_id}-c`, String(l.propose_charges)], [`${l.lot_id}-t`, String(l.propose_travaux)],
          ])));
        })
        .catch((e) => onError(e instanceof Error ? e.message : "Erreur"));
    }, 300);
    return () => clearTimeout(t);
  }, [proprietaireId, montantNum]);

  const valeur = (cle: string) => Number((parts[cle] ?? "0").replace(",", ".")) || 0;
  const total = rep
    ? Math.round(rep.lots.reduce((s, l) => s + valeur(`${l.lot_id}-c`) + valeur(`${l.lot_id}-t`), 0) * 100) / 100
    : 0;
  const juste = rep !== null && Math.abs(total - montantNum) < 0.005;

  async function save() {
    if (!rep) return;
    setBusy(true);
    try {
      await api.post("/paiements", {
        proprietaire_id: Number(proprietaireId), date, montant: montantNum, libelle,
        repartition: rep.lots.map((l) => ({
          lot_id: l.lot_id, montant: valeur(`${l.lot_id}-c`), montant_travaux: valeur(`${l.lot_id}-t`),
        })),
      });
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); } finally { setBusy(false); }
  }

  return (
    <Modal open title="Paiement d'un copropriétaire (tous ses lots)" onClose={onClose}>
      <div className="space-y-3">
        <Select label="Copropriétaire" value={proprietaireId} onChange={(e) => setProprietaireId(e.target.value)}>
          <option value="">— Choisir —</option>
          {proprietaires.map(([id, nom]) => (
            <option key={id} value={id}>
              {nom} (lots {lots.filter((l) => l.proprietaire_id === id).map((l) => l.numero).join(", ")})
            </option>
          ))}
        </Select>
        <div className="grid grid-cols-2 gap-3">
          <Input label="Date de réception" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <Input label="Montant reçu (€)" inputMode="decimal" value={montant} placeholder="0,00"
            onChange={(e) => setMontant(e.target.value)} />
        </div>
        <Input label="Libellé" value={libelle} onChange={(e) => setLibelle(e.target.value)} placeholder="Virement" />

        {rep && (
          <div className="rounded-lg border border-slate-200 p-3">
            <p className="mb-2 text-xs text-slate-500">
              Répartition proposée : les sommes dues sont soldées de la plus ancienne échéance à la plus récente
              {rep.excedent > 0 ? `, et l'excédent de ${fmtEUR(rep.excedent)} est porté en avance sur charges du lot principal` : ""}.
              Vous pouvez la corriger : la colonne « Travaux » est réservée au fonds de travaux (une avance travaux
              ne paiera jamais des charges).
            </p>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500">
                  <th className="py-1">Lot</th><th className="py-1 text-right">Dû charges</th>
                  <th className="py-1 text-right">Dû travaux</th><th className="py-1 text-right">Charges</th>
                  <th className="py-1 text-right">Travaux</th>
                </tr>
              </thead>
              <tbody>
                {rep.lots.map((l) => (
                  <tr key={l.lot_id}>
                    <td className="py-1">Lot {l.lot_numero}</td>
                    <td className="py-1 text-right tabular-nums text-slate-600">{fmtEUR(l.du_charges)}</td>
                    <td className="py-1 text-right tabular-nums text-slate-600">{fmtEUR(l.du_travaux)}</td>
                    {(["c", "t"] as const).map((n) => (
                      <td key={n} className="py-1 pl-2 text-right">
                        <input inputMode="decimal"
                          className="w-24 rounded-lg border border-slate-300 bg-white px-2 py-1 text-right text-sm tabular-nums"
                          value={parts[`${l.lot_id}-${n}`] ?? ""}
                          onChange={(e) => setParts((p) => ({ ...p, [`${l.lot_id}-${n}`]: e.target.value }))} />
                      </td>
                    ))}
                  </tr>
                ))}
                <tr>
                  <td className="py-1 font-semibold" colSpan={4}>Total</td>
                  <td className={`py-1 text-right font-semibold tabular-nums ${juste ? "text-slate-800" : "text-red-700"}`}>
                    {fmtEUR(total)}
                  </td>
                </tr>
              </tbody>
            </table>
            {!juste && (
              <p className="mt-1 text-xs text-red-700">Le total des parts doit être égal au montant reçu ({fmtEUR(montantNum || 0)}).</p>
            )}
          </div>
        )}
        <p className="text-xs text-slate-500">
          Un encaissement est enregistré par lot et par nature (charges, fonds de travaux), dans l'exercice de
          l'année de la date.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save} disabled={!juste || busy}>Enregistrer le paiement</Button>
        </div>
      </div>
    </Modal>
  );
}

interface Reclassement {
  simulation: boolean;
  mouvements: { id: number; date: string; libelle: string; type: string; montant: number; vers: number }[];
}

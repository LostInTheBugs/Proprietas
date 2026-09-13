import { useEffect, useState } from "react";
import { api } from "../api";
import { useUser } from "../auth";
import type { Exercice, BudgetLine, Appel, Mouvement, Recap, Lot } from "../types";
import { fmtEUR, fmtDate } from "../types";
import { Button, Card, Input, Modal, Select, Badge, Empty } from "../components/ui";

export default function Comptes() {
  const { user } = useUser();
  const isSyndic = user?.role === "syndic";
  const [exercices, setExercices] = useState<Exercice[]>([]);
  const [exId, setExId] = useState<number | null>(null);
  const [budget, setBudget] = useState<BudgetLine[]>([]);
  const [appels, setAppels] = useState<Appel[]>([]);
  const [mouvements, setMouvements] = useState<Mouvement[]>([]);
  const [lots, setLots] = useState<Lot[]>([]);
  const [recap, setRecap] = useState<Recap | null>(null);
  const [modal, setModal] = useState<null | "exercice" | "budget" | "appel" | "mouvement">(null);
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
            </>
          )}
        </div>
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

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
                            <Button
                              variant="ghost"
                              className="px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                              onClick={async () => { await api.del(`/budget/${b.id}`); refresh(); }}
                            >
                              Suppr.
                            </Button>
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
            {mouvements.length === 0 ? (
              <Empty text="Aucun mouvement. Enregistrez les virements reçus des copropriétaires et les factures payées." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
                      <th className="pb-2 font-medium">Date</th>
                      <th className="pb-2 font-medium">Libellé</th>
                      <th className="pb-2 font-medium">Lot</th>
                      <th className="pb-2 font-medium">Catégorie</th>
                      <th className="pb-2 text-right font-medium">Montant</th>
                      <th className="pb-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {mouvements.map((m) => {
                      const lot = lots.find((l) => l.id === m.lot_id);
                      return (
                        <tr key={m.id} className="border-b border-slate-50 last:border-0">
                          <td className="py-2 whitespace-nowrap text-slate-600">{fmtDate(m.date)}</td>
                          <td className="py-2 text-slate-700">{m.libelle}</td>
                          <td className="py-2 text-slate-600">{lot ? `Lot ${lot.numero}` : "—"}</td>
                          <td className="py-2"><Badge>{m.categorie}</Badge></td>
                          <td className={`py-2 text-right font-semibold tabular-nums ${m.type === "encaissement" ? "text-emerald-600" : "text-slate-700"}`}>
                            {m.type === "encaissement" ? "+" : "−"}{fmtEUR(m.montant)}
                          </td>
                          <td className="py-2.5 text-right">
                            {isSyndic && (
                              <Button
                                variant="ghost"
                                className="px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                                onClick={async () => { await api.del(`/mouvements/${m.id}`); refresh(); }}
                              >
                                Suppr.
                              </Button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
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
        <MouvementModal exId={exId} lots={lots} onClose={() => setModal(null)} onSaved={() => { setModal(null); refresh(); }} onError={setError} />
      )}
    </div>
  );

  async function refresh() {
    if (!exId) return;
    setBudget(await api.get(`/exercices/${exId}/budget`));
    setAppels(await api.get(`/exercices/${exId}/appels`));
    setMouvements(await api.get(`/exercices/${exId}/mouvements`));
    setRecap(await api.get("/recap"));
  }
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

function BudgetModal({ exId, onClose, onSaved, onError }: { exId: number; onClose: () => void; onSaved: () => void; onError: (e: string) => void }) {
  const [libelle, setLibelle] = useState("");
  const [montant, setMontant] = useState("");
  async function save() {
    try {
      await api.post(`/exercices/${exId}/budget`, { libelle, montant: Number(montant) });
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  return (
    <Modal open title="Ligne de budget" onClose={onClose}>
      <div className="space-y-3">
        <Input label="Poste" value={libelle} onChange={(e) => setLibelle(e.target.value)} placeholder="Entretien courant" />
        <Input label="Montant (€)" type="number" step="0.01" value={montant} onChange={(e) => setMontant(e.target.value)} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>Ajouter</Button>
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

function MouvementModal({ exId, lots, onClose, onSaved, onError }: { exId: number; lots: Lot[]; onClose: () => void; onSaved: () => void; onError: (e: string) => void }) {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [libelle, setLibelle] = useState("");
  const [type, setType] = useState("encaissement");
  const [categorie, setCategorie] = useState("charges");
  const [montant, setMontant] = useState("");
  const [lotId, setLotId] = useState("");
  async function save() {
    try {
      await api.post(`/exercices/${exId}/mouvements`, {
        date, libelle, type, categorie, montant: Number(montant),
        lot_id: lotId === "" ? null : Number(lotId),
      });
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  return (
    <Modal open title="Nouveau mouvement" onClose={onClose}>
      <div className="space-y-3">
        <Input label="Date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        <Input label="Libellé" value={libelle} onChange={(e) => setLibelle(e.target.value)} placeholder="Virement lot 2 / Facture EDF" />
        <div className="grid grid-cols-2 gap-3">
          <Select label="Type" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="encaissement">Encaissement</option>
            <option value="depense">Dépense</option>
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
        <div className="grid grid-cols-2 gap-3">
          <Input label="Montant (€)" type="number" step="0.01" value={montant} onChange={(e) => setMontant(e.target.value)} />
          <Select label="Lot (si paiement individuel)" value={lotId} onChange={(e) => setLotId(e.target.value)}>
            <option value="">Copro entière</option>
            {lots.map((l) => <option key={l.id} value={l.id}>Lot {l.numero}</option>)}
          </Select>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>Enregistrer</Button>
        </div>
      </div>
    </Modal>
  );
}

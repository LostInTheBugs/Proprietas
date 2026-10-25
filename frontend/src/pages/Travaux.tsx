import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useUser } from "../auth";
import type { Travaux } from "../types";
import { fmtEUR } from "../types";
import { Button, Card, Input, Modal, Select, Badge, Empty } from "../components/ui";

const CATEGORIES: Record<string, string> = {
  toiture: "Toiture / couverture",
  facade: "Façade / ravalement",
  chauffage: "Chauffage / climatisation",
  electricite: "Électricité",
  plomberie: "Plomberie / sanitaire",
  ascenseur: "Ascenseur",
  securite: "Sécurité / incendie",
  communs: "Parties communes",
  autres: "Autres",
};

const STATUTS: Record<string, { label: string; color: "amber" | "indigo" | "green" }> = {
  planifie: { label: "Planifié", color: "amber" },
  en_cours: { label: "En cours", color: "indigo" },
  realise: { label: "Réalisé", color: "green" },
};

export default function TravauxPage() {
  const { user } = useUser();
  const isSyndic = user?.role === "syndic";
  const [travaux, setTravaux] = useState<Travaux[]>([]);
  const [budget, setBudget] = useState(0);
  const [modal, setModal] = useState<null | Travaux | "new">(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [t, r] = await Promise.all([
      api.get<Travaux[]>("/travaux"),
      api.get<{ budget_previsionnel: number }>("/recap"),
    ]);
    setTravaux(t);
    setBudget(r.budget_previsionnel ?? 0);
  }, []);
  useEffect(() => { load().catch(() => {}); }, [load]);

  const total = travaux.reduce((s, t) => s + t.montant, 0);
  const parAnnee = travaux.reduce<Record<number, number>>((acc, t) => {
    acc[t.annee] = (acc[t.annee] ?? 0) + t.montant;
    return acc;
  }, {});
  const cotisationPpt = total * 0.025;
  const cotisationBudget = budget * 0.05;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Plan pluriannuel de travaux</h1>
          <p className="text-sm text-slate-500">Prévision des travaux à venir et financement par le fonds de travaux</p>
        </div>
        {isSyndic && <Button onClick={() => setModal("new")}>+ Ajouter un travaux</Button>}
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {/* Synthèse financière */}
      {travaux.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Card title="Montant total du plan">
            <p className="text-2xl font-bold text-slate-800">{fmtEUR(total)}</p>
            <p className="mt-1 text-xs text-slate-500">
              {Object.entries(parAnnee)
                .sort((a, b) => Number(a[0]) - Number(b[0]))
                .map(([annee, montant]) => `${annee} : ${fmtEUR(montant)}`)
                .join(" · ")}
            </p>
          </Card>
          <Card title="Cotisation annuelle minimale (PPT voté)">
            <p className="text-2xl font-bold text-indigo-700">{fmtEUR(Math.max(cotisationPpt, cotisationBudget))}</p>
            <p className="mt-1 text-xs text-slate-500">
              Le plus élevé de : 2,5 % du plan ({fmtEUR(cotisationPpt)}) et 5 % du budget prévisionnel ({fmtEUR(cotisationBudget)})
            </p>
          </Card>
          <Card title="Sans PPT (règle par défaut)">
            <p className="text-2xl font-bold text-slate-800">{fmtEUR(cotisationBudget)}</p>
            <p className="mt-1 text-xs text-slate-500">5 % du budget prévisionnel ({fmtEUR(budget)})</p>
          </Card>
        </div>
      )}

      <Card title="Planning des travaux">
        {travaux.length === 0 ? (
          <Empty text="Aucun travaux planifié. Ajoutez les travaux à prévoir (toiture, façade, chaudière…) pour construire votre plan pluriannuel." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2 font-medium">Année</th>
                  <th className="px-3 py-2 font-medium">Travaux</th>
                  <th className="px-3 py-2 font-medium">Catégorie</th>
                  <th className="px-3 py-2 text-right font-medium">Montant estimé</th>
                  <th className="px-3 py-2 font-medium">Statut</th>
                  {isSyndic && <th className="px-3 py-2" />}
                </tr>
              </thead>
              <tbody>
                {travaux.map((t) => (
                  <tr key={t.id} className="border-b border-slate-50 last:border-0">
                    <td className="px-3 py-2 font-semibold text-slate-700">{t.annee}</td>
                    <td className="px-3 py-2 text-slate-700">
                      {t.libelle}
                      {t.notes && <span className="block text-xs text-slate-400">{t.notes}</span>}
                    </td>
                    <td className="px-3 py-2 text-slate-500">{CATEGORIES[t.categorie] ?? t.categorie}</td>
                    <td className="px-3 py-2 text-right font-medium tabular-nums text-slate-700">{fmtEUR(t.montant)}</td>
                    <td className="px-3 py-2">
                      <Badge color={STATUTS[t.statut]?.color ?? "amber"}>{STATUTS[t.statut]?.label ?? t.statut}</Badge>
                    </td>
                    {isSyndic && (
                      <td className="px-3 py-2 text-right">
                        <button onClick={() => setModal(t)} className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-indigo-600 hover:bg-indigo-50">
                          Modifier
                        </button>
                        <button
                          onClick={async () => {
                            await api.del(`/travaux/${t.id}`);
                            load();
                          }}
                          className="ml-1 rounded-lg px-2.5 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"
                        >
                          Supprimer
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
          <b>Règle légale (France)</b> : le plan pluriannuel de travaux (PPT) se vote en assemblée générale. S'il est
          adopté, la cotisation annuelle au fonds de travaux doit atteindre <b>au moins 2,5 % du montant du plan
          et au moins 5 % du budget prévisionnel</b> : le minimum est le plus élevé des deux, les taux ne
          s'additionnent pas (loi du 10 juillet 1965, art. 14-2-1 ; service-public.fr, F34026). Le fonds de travaux sert à financer
          ces travaux ; pour les petites copropriétés (≤ 5 lots de logements, bureaux ou commerces, régime 41-8) le PPT reste facultatif mais recommandé.
        </p>
      </Card>

      {modal && (
        <TravauxModal
          travaux={modal === "new" ? null : modal}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); load(); }}
          onError={setError}
        />
      )}
    </div>
  );
}

function TravauxModal({ travaux, onClose, onSaved, onError }: {
  travaux: Travaux | null; onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const [libelle, setLibelle] = useState(travaux?.libelle ?? "");
  const [categorie, setCategorie] = useState(travaux?.categorie ?? "autres");
  const [annee, setAnnee] = useState(String(travaux?.annee ?? new Date().getFullYear() + 1));
  const [montant, setMontant] = useState(String(travaux?.montant ?? ""));
  const [statut, setStatut] = useState(travaux?.statut ?? "planifie");
  const [notes, setNotes] = useState(travaux?.notes ?? "");

  async function save() {
    try {
      const body = {
        libelle,
        categorie,
        annee: Number(annee),
        montant: Number(montant) || 0,
        statut,
        notes,
      };
      if (travaux) await api.put(`/travaux/${travaux.id}`, body);
      else await api.post("/travaux", body);
      onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Erreur");
    }
  }

  return (
    <Modal open title={travaux ? "Modifier le travaux" : "Ajouter des travaux au plan"} onClose={onClose}>
      <div className="space-y-3">
        <Input label="Intitulé des travaux" value={libelle} onChange={(e) => setLibelle(e.target.value)} placeholder="Ex : Réfection de la toiture" />
        <div className="grid grid-cols-2 gap-3">
          <Select label="Catégorie" value={categorie} onChange={(e) => setCategorie(e.target.value)}>
            {Object.entries(CATEGORIES).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </Select>
          <Select label="Statut" value={statut} onChange={(e) => setStatut(e.target.value)}>
            {Object.entries(STATUTS).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </Select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Input label="Année prévue" type="number" value={annee} onChange={(e) => setAnnee(e.target.value)} />
          <Input label="Montant estimé (€)" type="number" step="100" value={montant} onChange={(e) => setMontant(e.target.value)} />
        </div>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-600">Notes (optionnel)</span>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </label>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save} disabled={!libelle.trim()}>Enregistrer</Button>
        </div>
      </div>
    </Modal>
  );
}

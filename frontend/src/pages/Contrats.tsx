import { useEffect, useState } from "react";
import { api } from "../api";
import { useUser } from "../auth";
import type { Contrat, Contact } from "../types";
import { fmtEUR } from "../types";
import { Button, Card, Input, Modal, Select, Badge, Empty } from "../components/ui";

const TYPES: Record<string, string> = {
  energie: "Énergie (électricité, gaz)",
  assurance: "Assurance",
  entretien: "Entretien / maintenance",
  telecom: "Télécom / internet",
  nettoyage: "Nettoyage",
  securite: "Sécurité / alarme",
  eau: "Eau / assainissement",
  autres: "Autres",
};

const PERIODES: Record<string, string> = {
  mensuel: "Mensuel",
  trimestriel: "Trimestriel",
  annuel: "Annuel",
  ponctuel: "Ponctuel",
};

const STATUTS: Record<string, { label: string; color: "green" | "amber" | "red" }> = {
  actif: { label: "Actif", color: "green" },
  expire_bientot: { label: "Expire bientôt", color: "amber" },
  expire: { label: "Expiré", color: "red" },
};

function dateFr(d: string): string {
  if (!d) return "—";
  const [y, m, j] = d.split("-");
  return `${j}/${m}/${y}`;
}

export default function Contrats() {
  const { user } = useUser();
  const isSyndic = user?.role === "syndic";
  const [contrats, setContrats] = useState<Contrat[]>([]);
  const [modal, setModal] = useState<null | { type: "contrat"; item?: Contrat }>(null);
  const [error, setError] = useState("");

  async function load() {
    setContrats(await api.get<Contrat[]>("/contrats"));
  }
  useEffect(() => { load().catch(() => {}); }, []);

  const nbExpire = contrats.filter((c) => c.statut === "expire").length;
  const nbBientot = contrats.filter((c) => c.statut === "expire_bientot").length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Contrats</h1>
          <p className="text-sm text-slate-500">
            Contrats de la copropriété (énergie, assurance, entretien…) et leurs échéances
          </p>
        </div>
        {isSyndic && <Button onClick={() => setModal({ type: "contrat" })}>+ Ajouter un contrat</Button>}
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {contrats.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Card title="Contrats actifs">
            <p className="text-2xl font-bold text-emerald-600">{contrats.length - nbExpire - nbBientot}</p>
          </Card>
          <Card title="Échéances ≤ 60 jours">
            <p className="text-2xl font-bold text-amber-600">{nbBientot}</p>
          </Card>
          <Card title="Expirés">
            <p className="text-2xl font-bold text-red-600">{nbExpire}</p>
          </Card>
        </div>
      )}

      <Card title="Liste des contrats (les plus urgents d'abord)">
        {contrats.length === 0 ? (
          <Empty text="Aucun contrat. Ajoutez vos contrats (EDF, assurance de l'immeuble, contrat d'entretien de la chaudière…) pour suivre les échéances." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2 font-medium">Contrat</th>
                  <th className="px-3 py-2 font-medium">Type</th>
                  <th className="px-3 py-2 font-medium">Fournisseur / assureur</th>
                  <th className="px-3 py-2 text-right font-medium">Montant</th>
                  <th className="px-3 py-2 font-medium">Échéance</th>
                  <th className="px-3 py-2 font-medium">Statut</th>
                  {isSyndic && <th className="px-3 py-2" />}
                </tr>
              </thead>
              <tbody>
                {contrats.map((c) => (
                  <tr key={c.id} className="border-b border-slate-50 last:border-0">
                    <td className="px-3 py-2 text-slate-700">
                      {c.libelle}
                      {c.reference && <span className="block text-xs text-slate-400">Réf. {c.reference}</span>}
                    </td>
                    <td className="px-3 py-2 text-slate-500">{TYPES[c.type] ?? c.type}</td>
                    <td className="px-3 py-2 text-slate-600">{c.contact_nom || "—"}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-700">
                      {c.montant > 0 ? `${fmtEUR(c.montant)} ${PERIODES[c.periode] ? `/ ${PERIODES[c.periode].toLowerCase()}` : ""}` : "—"}
                      {(c.nb_mouvements ?? 0) > 0 && (
                        <span className="block text-xs text-slate-500">
                          payé en {new Date().getFullYear()} : {fmtEUR(c.depenses_annee ?? 0)} ({c.nb_mouvements} mouvement{(c.nb_mouvements ?? 0) > 1 ? "s" : ""})
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 tabular-nums text-slate-700">
                      {dateFr(c.date_fin)}
                      {c.renouvellement_auto && <span className="block text-xs text-slate-400">renouvellement auto.</span>}
                    </td>
                    <td className="px-3 py-2">
                      <Badge color={STATUTS[c.statut]?.color ?? "green"}>
                        {STATUTS[c.statut]?.label ?? c.statut}
                        {c.statut === "expire_bientot" && c.jours_restants !== null
                          ? ` (J-${c.jours_restants})`
                          : c.statut === "expire" && c.jours_restants !== null
                            ? ` (J+${Math.abs(c.jours_restants)})`
                            : ""}
                      </Badge>
                    </td>
                    {isSyndic && (
                      <td className="px-3 py-2 text-right">
                        <button onClick={() => setModal({ type: "contrat", item: c })} className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-indigo-600 hover:bg-indigo-50">
                          Modifier
                        </button>
                        <button
                          onClick={async () => {
                            await api.del(`/contrats/${c.id}`);
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
      </Card>

      {modal?.type === "contrat" && (
        <ContratModal
          item={modal.item}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); load(); }}
          onError={setError}
        />
      )}
    </div>
  );
}

function ContratModal({ item, onClose, onSaved, onError }: {
  item?: Contrat; onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [f, setF] = useState({
    libelle: item?.libelle ?? "",
    type: item?.type ?? "energie",
    reference: item?.reference ?? "",
    contact_id: item?.contact_id ?? "",
    date_debut: item?.date_debut ?? "",
    date_fin: item?.date_fin ?? "",
    montant: item?.montant ?? 0,
    periode: item?.periode ?? "annuel",
    renouvellement_auto: item?.renouvellement_auto ?? false,
    notes: item?.notes ?? "",
  });
  const set = (k: string, v: unknown) => setF((p) => ({ ...p, [k]: v }));

  useEffect(() => {
    api.get<Contact[]>("/contacts").then(setContacts).catch(() => {});
  }, []);

  async function save() {
    try {
      const body = { ...f, contact_id: f.contact_id === "" ? null : Number(f.contact_id), montant: Number(f.montant) };
      if (item) await api.put(`/contrats/${item.id}`, body);
      else await api.post("/contrats", body);
      onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Erreur");
    }
  }

  return (
    <Modal open title={item ? `Modifier ${item.libelle}` : "Nouveau contrat"} onClose={onClose}>
      <div className="space-y-3">
        <Input label="Libellé" value={f.libelle} onChange={(e) => set("libelle", e.target.value)} required placeholder="Contrat électricité parties communes" />
        <div className="grid grid-cols-2 gap-3">
          <Select label="Type" value={f.type} onChange={(e) => set("type", e.target.value)}>
            {Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
          <Select label="Fournisseur / assureur" value={f.contact_id} onChange={(e) => set("contact_id", e.target.value)}>
            <option value="">— aucun —</option>
            {contacts.map((c) => <option key={c.id} value={c.id}>{c.nom}</option>)}
          </Select>
        </div>
        <Input label="Référence (n° de contrat / client)" value={f.reference} onChange={(e) => set("reference", e.target.value)} />
        <div className="grid grid-cols-2 gap-3">
          <Input label="Début" type="date" value={f.date_debut} onChange={(e) => set("date_debut", e.target.value)} />
          <Input label="Fin (échéance)" type="date" value={f.date_fin} onChange={(e) => set("date_fin", e.target.value)} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Input label="Montant (€)" type="number" value={f.montant} onChange={(e) => set("montant", e.target.value)} />
          <Select label="Période" value={f.periode} onChange={(e) => set("periode", e.target.value)}>
            {Object.entries(PERIODES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={f.renouvellement_auto} onChange={(e) => set("renouvellement_auto", e.target.checked)} />
          Renouvellement automatique (à la date de fin)
        </label>
        <Input label="Notes" value={f.notes} onChange={(e) => set("notes", e.target.value)} />
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>Enregistrer</Button>
        </div>
      </div>
    </Modal>
  );
}

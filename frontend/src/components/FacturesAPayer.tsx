import { useEffect, useState } from "react";
import { api } from "../api";
import type { FactureAPayer, User } from "../types";
import { fmtDate, fmtEUR } from "../types";
import { Button, Card, Input, Modal, Select } from "./ui";

/** Tableau de bord du syndic : factures saisies « à payer », en retard en rouge, et « Marquer payée ». */
export function FacturesAPayerCard() {
  const [liste, setListe] = useState<FactureAPayer[] | null>(null);
  const [comptes, setComptes] = useState<User[]>([]);
  const [choisie, setChoisie] = useState<FactureAPayer | null>(null);
  const [error, setError] = useState("");
  function charger() { api.get<FactureAPayer[]>("/factures-a-payer").then(setListe).catch(() => {}); }
  useEffect(() => {
    charger();
    api.get<User[]>("/auth/users").then(setComptes).catch(() => {});
  }, []);
  if (!liste || liste.length === 0) return null;
  const retard = liste.filter((f) => f.en_retard).length;
  const total = liste.reduce((s, f) => s + f.montant, 0);
  return (
    <Card title={`Factures à payer — ${fmtEUR(total)}`}>
      {retard > 0 && (
        <p className="mb-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800">
          <strong>{retard}</strong> facture(s) en retard de paiement.
        </p>
      )}
      <ul className="divide-y divide-slate-100 text-sm">
        {liste.map((f) => (
          <li key={f.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
            <span className="min-w-0 flex-1">
              <span className="font-medium text-slate-800">{f.libelle}</span>
              {f.document_id && (
                <a className="ml-2 text-xs text-indigo-600 hover:underline" href={`/api/documents/${f.document_id}/download`}>📎 facture</a>
              )}
              <span className={`block text-xs ${f.en_retard ? "font-medium text-red-700" : "text-slate-500"}`}>
                Facture du {fmtDate(f.date)}{f.echeance ? ` — échéance le ${fmtDate(f.echeance)}` : " — sans échéance"}
                {f.en_retard ? " (en retard)" : ""}
              </span>
            </span>
            <span className="font-semibold tabular-nums text-slate-800">{fmtEUR(f.montant)}</span>
            <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setChoisie(f)}>Marquer payée</Button>
          </li>
        ))}
      </ul>
      {error && <p className="mt-2 text-xs text-red-700">{error}</p>}
      {choisie && (
        <PayerModal f={choisie} comptes={comptes} onClose={() => setChoisie(null)}
          onSaved={() => { setChoisie(null); setError(""); charger(); }} onError={setError} />
      )}
    </Card>
  );
}

function PayerModal({ f, comptes, onClose, onSaved, onError }: {
  f: FactureAPayer; comptes: User[]; onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [par, setPar] = useState("");
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true);
    try {
      await api.post(`/mouvements/${f.id}/payer`, { date, avance_par_id: par === "" ? null : Number(par) });
      onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Erreur");
      onClose();
    }
  }
  return (
    <Modal open title={`Marquer payée : ${f.libelle}`} onClose={onClose}>
      <div className="space-y-3 text-sm">
        <Select label="Payée par" value={par} onChange={(e) => setPar(e.target.value)}>
          <option value="">Le compte de la copropriété</option>
          {comptes.map((c) => <option key={c.id} value={c.id}>{[c.prenom, c.nom].filter(Boolean).join(" ") || c.email} (de sa poche : avance)</option>)}
        </Select>
        {par === "" ? (
          <Input label="Date du paiement" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        ) : (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
            La facture devient une avance de cette personne, à lui rembourser ou à déduire de ses charges (Comptes → Avances
            à régler). Justificatif obligatoire : la facture doit être rattachée à la dépense.
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save} disabled={busy}>Enregistrer</Button>
        </div>
      </div>
    </Modal>
  );
}

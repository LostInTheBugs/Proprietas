import { useEffect, useState } from "react";
import { api } from "../api";
import type { AvancePersonne } from "../types";
import { fmtDate, fmtEUR } from "../types";
import { Button, Card, Input, Modal, Select } from "./ui";

/** Avances : ce que la copropriété doit aux personnes qui ont payé une dépense pour elle, et leur règlement
 *  (remboursement par virement, ou déduction de leurs charges). Une avance se saisit comme une dépense,
 *  avec « Payée par ». */
export function AvancesCard({ exId, cle, onChanged, onError }: {
  exId: number; cle: unknown; onChanged: () => void; onError: (e: string) => void;
}) {
  const [etat, setEtat] = useState<AvancePersonne[] | null>(null);
  const [reglement, setReglement] = useState<{ p: AvancePersonne; mode: "rembourser" | "deduire" } | null>(null);
  useEffect(() => {
    api.get<AvancePersonne[]>("/avances").then(setEtat).catch(() => {});
  }, [cle]);
  if (!etat || etat.length === 0) return null;
  return (
    <Card title="Avances à régler">
      <p className="mb-3 text-xs leading-relaxed text-slate-500">
        Dépenses payées de leur poche par un copropriétaire ou le syndic (saisies avec « Payée par ») : elles comptent dans
        les charges, mais ne sont pas sorties de la banque. La copropriété les règle par un virement (« Rembourser ») ou en
        les déduisant des charges de la personne (« Déduire de ses charges »).
      </p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
            <th className="pb-2">Personne</th>
            <th className="pb-2 text-right">Avancé</th>
            <th className="pb-2 text-right">Remboursé</th>
            <th className="pb-2 text-right">Déduit</th>
            <th className="pb-2 text-right">Reste dû</th>
            <th className="pb-2" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {etat.map((p) => (
            <tr key={p.personne_id}>
              <td className="py-2 font-medium text-slate-800">{p.nom}</td>
              <td className="py-2 text-right tabular-nums">{fmtEUR(p.avance)}</td>
              <td className="py-2 text-right tabular-nums">{fmtEUR(p.rembourse)}</td>
              <td className="py-2 text-right tabular-nums">{fmtEUR(p.deduit)}</td>
              <td className={`py-2 text-right font-semibold tabular-nums ${p.reste > 0 ? "text-amber-700" : "text-emerald-700"}`}>
                {fmtEUR(p.reste)}
              </td>
              <td className="py-2 text-right whitespace-nowrap">
                {p.reste > 0 && (<>
                  <Button variant="ghost" onClick={() => setReglement({ p, mode: "rembourser" })}>Rembourser</Button>
                  {p.lots.length > 0 && (
                    <Button variant="ghost" onClick={() => setReglement({ p, mode: "deduire" })}>Déduire de ses charges</Button>
                  )}
                </>)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {reglement && (
        <ReglementModal exId={exId} p={reglement.p} mode={reglement.mode} onClose={() => setReglement(null)}
          onSaved={() => { setReglement(null); onChanged(); }} onError={onError} />
      )}
    </Card>
  );
}

function ReglementModal({ exId, p, mode, onClose, onSaved, onError }: {
  exId: number; p: AvancePersonne; mode: "rembourser" | "deduire"; onClose: () => void; onSaved: () => void;
  onError: (e: string) => void;
}) {
  const rembourser = mode === "rembourser";
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [montant, setMontant] = useState(String(p.reste));
  const [lotId, setLotId] = useState(p.lots[0] ? String(p.lots[0].id) : "");
  const [libelle, setLibelle] = useState(rembourser ? `Remboursement de l'avance de ${p.nom}` : `Avance de ${p.nom} déduite des charges`);
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true);
    try {
      await api.post(`/exercices/${exId}/mouvements`, rembourser
        ? { date, libelle, type: "depense", categorie: "avance", montant: Number(montant), avance_par_id: p.personne_id }
        : { date, libelle, type: "encaissement", categorie: "charges", montant: Number(montant), lot_id: Number(lotId),
            avance_par_id: p.personne_id });
      onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Erreur");
      setBusy(false);
    }
  }
  return (
    <Modal open title={rembourser ? `Rembourser ${p.nom}` : `Déduire l'avance des charges de ${p.nom}`} onClose={onClose}>
      <div className="space-y-3 text-sm">
        <p className="text-slate-600">
          {rembourser
            ? "Virement depuis le compte de la copropriété : il sort de la banque, mais ce n'est pas une nouvelle charge."
            : "La somme est portée au crédit de son compte de copropriétaire et paie ses appels de fonds ; rien ne passe par la banque."}
          {" "}Reste dû : <strong>{fmtEUR(p.reste)}</strong>.
        </p>
        <ul className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-600">
          {p.mouvements.filter((m) => m.nature === "avance").map((m) => (
            <li key={m.id}>
              {fmtDate(m.date)} — {m.libelle} — {fmtEUR(m.montant)}{" "}
              {m.document_id && <a className="text-indigo-600 hover:underline" href={`/api/documents/${m.document_id}/download`}>📎 justificatif</a>}
            </li>
          ))}
        </ul>
        <div className="grid grid-cols-2 gap-3">
          <Input label="Date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <Input label="Montant (€)" type="number" step="0.01" value={montant} onChange={(e) => setMontant(e.target.value)} />
        </div>
        {!rembourser && (
          <Select label="Lot" value={lotId} onChange={(e) => setLotId(e.target.value)}>
            {p.lots.map((l) => <option key={l.id} value={l.id}>Lot {l.numero}</option>)}
          </Select>
        )}
        <Input label="Libellé" value={libelle} onChange={(e) => setLibelle(e.target.value)} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save} disabled={busy || !(Number(montant) > 0)}>{rembourser ? "Enregistrer le remboursement" : "Déduire"}</Button>
        </div>
      </div>
    </Modal>
  );
}

/** Tableau de bord : ce que la copropriété doit au compte connecté (ses avances). */
export function MesAvances() {
  const [etat, setEtat] = useState<AvancePersonne[]>([]);
  useEffect(() => {
    api.get<AvancePersonne[]>("/avances/moi").then(setEtat).catch(() => {});
  }, []);
  const moi = etat[0];
  if (!moi) return null;
  return (
    <Card title="Mes avances à la copropriété">
      <p className="text-sm text-slate-600">
        Vous avez payé {fmtEUR(moi.avance)} de dépenses pour la copropriété ; {fmtEUR(moi.rembourse)} vous ont été remboursés
        et {fmtEUR(moi.deduit)} déduits de vos charges.{" "}
        {moi.reste > 0
          ? <>La copropriété vous doit encore <strong>{fmtEUR(moi.reste)}</strong>.</>
          : <>Tout est réglé.</>}
      </p>
    </Card>
  );
}

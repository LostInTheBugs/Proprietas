import { useEffect, useState } from "react";
import { api } from "../api";
import type { Lot, User } from "../types";
import { fmtDate, fmtEUR } from "../types";
import { Badge, Button, Card, Input, Modal, Select } from "./ui";

/** Vente d'un lot (mutation) : lots transférés à l'acquéreur, compte du vendeur arrêté à la date de l'acte
 * (décret 1967, art. 6-2), suivi de la notification (art. 6) et de l'avis de mutation (loi 1965, art. 20). */

interface Vente {
  id: number; lot_id: number; lots: string; date_acte: string; vendeur_nom: string; acquereur_nom: string;
  notaire: string; notifiee_le: string | null; avis_mutation_le: string | null; opposition_le: string | null;
  opposition_avant_le: string | null; notes: string; derniere: boolean;
  compte_vendeur: { du: number; avance: number; solde: number; encaisse_apres_vente: number;
                    lignes: { libelle: string; echeance: string; restant_du: number }[] };
}

const nomCompte = (u: User) => `${u.prenom} ${u.nom}`.trim() || u.email;

export function VentesCard({ lots, comptes, onChange, onError }: {
  lots: Lot[]; comptes: User[]; onChange: () => void; onError: (e: string) => void;
}) {
  const [ventes, setVentes] = useState<Vente[]>([]);
  const [modal, setModal] = useState<null | { vente?: Vente }>(null);
  const [encaisser, setEncaisser] = useState<Vente | null>(null);
  const charger = () => { api.get<Vente[]>("/mutations").then(setVentes).catch(() => {}); };
  useEffect(charger, []);
  const apres = () => { charger(); onChange(); };

  async function annuler(v: Vente) {
    if (!confirm(`Annuler la vente du ${fmtDate(v.date_acte)} (${v.lots}) ? Les lots reviennent à ${v.vendeur_nom}.`)) return;
    try { await api.del(`/mutations/${v.id}`); apres(); } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }

  const aujourdhui = new Date().toISOString().slice(0, 10);
  return (
    <Card title="Ventes de lots"
      action={<Button variant="secondary" className="px-2.5 py-1.5 text-xs" onClick={() => setModal({})}>+ Enregistrer une vente</Button>}>
      <p className="mb-3 text-xs leading-relaxed text-slate-500">
        À la date de l'acte, les lots passent à l'acquéreur et son décompte repart de zéro. Ce qui était exigible jusque-là
        (et les paiements reçus jusque-là) reste au compte du vendeur (décret du 17 mars 1967, art. 6-2) ; son solde se règle
        en général par le notaire sur le prix. Avis de mutation reçu : 15 jours pour former opposition par acte de commissaire
        de justice (loi du 10 juillet 1965, art. 20).
      </p>
      {ventes.length === 0 ? (
        <p className="text-sm text-slate-500">Aucune vente enregistrée.</p>
      ) : (
        <ul className="divide-y divide-slate-100 text-sm">
          {ventes.map((v) => {
            const c = v.compte_vendeur;
            const delai = v.opposition_avant_le && !v.opposition_le && c.du > 0 ? v.opposition_avant_le : null;
            return (
              <li key={v.id} className="space-y-1 py-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-slate-800">{v.lots}</span>
                  <span className="text-slate-600">vendu le {fmtDate(v.date_acte)} par {v.vendeur_nom || "—"} à {v.acquereur_nom || "—"}</span>
                  {c.du > 0 ? <Badge color="amber">vendeur : {fmtEUR(c.du)} dû</Badge>
                    : c.avance > 0 ? <Badge color="indigo">dû au vendeur : {fmtEUR(c.avance)}</Badge>
                    : <Badge color="green">compte vendeur soldé</Badge>}
                  {delai && <Badge color={delai < aujourdhui ? "slate" : "red"}>opposition avant le {fmtDate(delai)}</Badge>}
                  {v.opposition_le && <Badge color="slate">opposition le {fmtDate(v.opposition_le)}</Badge>}
                </div>
                <p className="text-xs text-slate-500">
                  {v.notaire ? `Notaire : ${v.notaire} · ` : ""}
                  notification (art. 6) : {v.notifiee_le ? fmtDate(v.notifiee_le) : "non reçue"} ·
                  avis de mutation (art. 20) : {v.avis_mutation_le ? fmtDate(v.avis_mutation_le) : "non reçu"}
                  {c.encaisse_apres_vente > 0 && ` · ${fmtEUR(c.encaisse_apres_vente)} encaissés au compte du vendeur depuis la vente`}
                </p>
                {c.lignes.length > 0 && (
                  <ul className="pl-4 text-xs text-slate-600">
                    {c.lignes.map((l, i) => <li key={i}>{l.libelle} (échéance {fmtDate(l.echeance)}) : {fmtEUR(l.restant_du)}</li>)}
                  </ul>
                )}
                <div className="flex flex-wrap gap-1">
                  <Button variant="ghost" className="text-xs" onClick={() => setModal({ vente: v })}>Suivi</Button>
                  {c.du > 0 && <Button variant="ghost" className="text-xs" onClick={() => setEncaisser(v)}>Encaisser le solde du vendeur</Button>}
                  {v.derniere && <Button variant="ghost" className="text-xs" onClick={() => annuler(v)}>Annuler la vente</Button>}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {modal && (
        <VenteModal vente={modal.vente} lots={lots} comptes={comptes} onClose={() => setModal(null)}
          onSaved={() => { setModal(null); apres(); }} onError={onError} />
      )}
      {encaisser && (
        <EncaissementModal vente={encaisser} onClose={() => setEncaisser(null)}
          onSaved={() => { setEncaisser(null); apres(); }} onError={onError} />
      )}
    </Card>
  );
}

function VenteModal({ vente, lots, comptes, onClose, onSaved, onError }: {
  vente?: Vente; lots: Lot[]; comptes: User[]; onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const vendables = lots.filter((l) => l.proprietaire_id != null && !l.lot_principal_id);
  const [lotId, setLotId] = useState("");
  const [dateActe, setDateActe] = useState(new Date().toISOString().slice(0, 10));
  const [acquereurId, setAcquereurId] = useState("");
  const [notaire, setNotaire] = useState(vente?.notaire ?? "");
  const [notifiee, setNotifiee] = useState(vente?.notifiee_le ?? "");
  const [avis, setAvis] = useState(vente?.avis_mutation_le ?? "");
  const [opposition, setOpposition] = useState(vente?.opposition_le ?? "");
  const [notes, setNotes] = useState(vente?.notes ?? "");
  const lot = lots.find((l) => String(l.id) === lotId);
  const acquereurs = comptes.filter((u) => u.id !== lot?.proprietaire_id);

  async function save() {
    const suivi = { notaire, notifiee_le: notifiee || null, avis_mutation_le: avis || null,
                    opposition_le: opposition || null, notes };
    try {
      if (vente) await api.put(`/mutations/${vente.id}`, suivi);
      else await api.post("/mutations", { ...suivi, lot_id: Number(lotId), date_acte: dateActe, acquereur_id: Number(acquereurId) });
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }

  return (
    <Modal open title={vente ? `Vente du ${fmtDate(vente.date_acte)} — ${vente.lots}` : "Enregistrer la vente d'un lot"} onClose={onClose}>
      <div className="space-y-3 text-sm">
        {!vente && (
          <>
            <Select label="Lot vendu (avec ses annexes)" value={lotId} onChange={(e) => setLotId(e.target.value)}>
              <option value="">— Choisir —</option>
              {vendables.map((l) => <option key={l.id} value={l.id}>Lot {l.numero} — {l.proprietaire_nom || "?"}</option>)}
            </Select>
            <div className="grid grid-cols-2 gap-3">
              <Input label="Date de l'acte" type="date" value={dateActe} onChange={(e) => setDateActe(e.target.value)} />
              <Select label="Acquéreur" value={acquereurId} onChange={(e) => setAcquereurId(e.target.value)}>
                <option value="">— Choisir —</option>
                {acquereurs.map((u) => <option key={u.id} value={u.id}>{nomCompte(u)}</option>)}
              </Select>
            </div>
            <p className="text-xs text-slate-500">L'acquéreur doit avoir un compte : créez-le d'abord dans Réglages → Comptes utilisateurs.</p>
          </>
        )}
        <Input label="Notaire (étude, référence)" value={notaire} onChange={(e) => setNotaire(e.target.value)} />
        <div className="grid grid-cols-3 gap-3">
          <Input label="Notification (art. 6)" type="date" value={notifiee} onChange={(e) => setNotifiee(e.target.value)} />
          <Input label="Avis de mutation" type="date" value={avis} onChange={(e) => setAvis(e.target.value)} />
          <Input label="Opposition formée" type="date" value={opposition} onChange={(e) => setOpposition(e.target.value)} />
        </div>
        <Input label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save} disabled={!vente && (!lotId || !acquereurId || !dateActe)}>{vente ? "Enregistrer" : "Enregistrer la vente"}</Button>
        </div>
      </div>
    </Modal>
  );
}

function EncaissementModal({ vente, onClose, onSaved, onError }: {
  vente: Vente; onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [montant, setMontant] = useState(String(vente.compte_vendeur.du));
  const [libelle, setLibelle] = useState(`Solde du vendeur (${vente.vendeur_nom}) — notaire`);
  async function save() {
    try {
      await api.post(`/mutations/${vente.id}/encaissement`, { date, montant: Number(montant.replace(",", ".")), libelle });
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  return (
    <Modal open title="Encaisser le solde du vendeur" onClose={onClose}>
      <div className="space-y-3 text-sm">
        <p className="text-xs text-slate-600">
          Porté au compte de {vente.vendeur_nom} (vente du {fmtDate(vente.date_acte)}), pas au décompte de l'acquéreur.
          Il doit encore {fmtEUR(vente.compte_vendeur.du)}.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <Input label="Date de réception" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <Input label="Montant (€)" inputMode="decimal" value={montant} onChange={(e) => setMontant(e.target.value)} />
        </div>
        <Input label="Libellé" value={libelle} onChange={(e) => setLibelle(e.target.value)} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>Encaisser</Button>
        </div>
      </div>
    </Modal>
  );
}

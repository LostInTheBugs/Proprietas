import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { NotificationPV, NotificationsPV } from "../types";
import { fmtDate } from "../types";
import { Badge, Button, Input, Select } from "./ui";

/** Notification du procès-verbal aux opposants et défaillants (loi 1965, art. 42 al. 2).
 *  LRE par défaut, LRAR pour qui a demandé la voie postale (art. 42-1). Le syndic envoie les
 *  recommandés chez son prestataire ou à La Poste, puis saisit ici les dates et références. */
export default function NotificationsPVPanel({ agId, onError }: { agId: number; onError: (e: string) => void }) {
  const [etat, setEtat] = useState<NotificationsPV | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setEtat(await api.get<NotificationsPV>(`/ag/${agId}/notifications-pv`));
  }, [agId]);
  useEffect(() => { load().catch(() => {}); }, [load]);

  async function preparer() {
    setBusy(true);
    try {
      setEtat(await api.post<NotificationsPV>(`/ag/${agId}/notifications-pv`));
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
    finally { setBusy(false); }
  }

  if (!etat) return null;
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-slate-700">
          Notification du procès-verbal — à envoyer avant le {fmtDate(etat.limite_envoi)}
        </p>
        <Button variant="secondary" className="px-2.5 py-1.5 text-xs" disabled={busy} onClick={preparer}>
          {etat.items.length > 0 ? "Mettre à jour la liste" : "Préparer la liste"}
        </Button>
      </div>
      <p className="mb-2 text-xs text-slate-500">
        À notifier : les copropriétaires opposants ou défaillants (l'abstention n'est pas une opposition),
        par lettre recommandée électronique, ou par LRAR s'ils ont demandé la voie postale (la demande prend
        effet le 9e jour suivant sa réception, le jour même si elle est faite en assemblée). Le délai de
        contestation de deux mois court à compter du lendemain de la première présentation (LRAR) ou de
        l'avis électronique (LRE) ; une fin de délai tombant un samedi, un dimanche ou un jour férié est
        reportée au premier jour ouvrable (code de procédure civile, art. 642) — dates de fin indicatives.
      </p>
      {etat.sans_proprietaire.length > 0 && (
        <p className="mb-2 text-xs text-amber-700">
          Lot(s) {etat.sans_proprietaire.join(", ")} concerné(s) sans propriétaire renseigné : impossible à notifier.
        </p>
      )}
      <div className="space-y-2">
        {etat.items.map((n) => (
          <LigneNotification key={n.id} n={n} onSaved={setEtat} onError={onError} />
        ))}
      </div>
    </div>
  );
}

function LigneNotification({ n, onSaved, onError }: {
  n: NotificationPV; onSaved: (e: NotificationsPV) => void; onError: (e: string) => void;
}) {
  const [f, setF] = useState({
    mode: n.mode, date_envoi: n.date_envoi ?? "", date_presentation: n.date_presentation ?? "",
    reference: n.reference,
  });
  const envoyee = n.date_envoi !== null;
  async function save() {
    try {
      onSaved(await api.put<NotificationsPV>(`/notifications-pv/${n.id}`, {
        mode: f.mode, reference: f.reference,
        date_envoi: f.date_envoi || null, date_presentation: f.date_presentation || null,
      }));
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  return (
    <div className="rounded border border-slate-100 p-2 text-xs">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <span className="font-medium text-slate-800">{n.nom}</span>
        <span className="text-slate-500">{n.resolutions}</span>
        {n.voie_postale_demandee && <Badge color="amber">voie postale demandée</Badge>}
        {n.en_retard && <Badge color="red">hors délai d'un mois</Badge>}
        {n.fin_contestation && (
          <span className="ml-auto text-slate-500">Contestation possible jusqu'au {fmtDate(n.fin_contestation)} (indicatif, reporté au jour ouvrable)</span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Select value={f.mode} disabled={envoyee} onChange={(e) => setF({ ...f, mode: e.target.value })}
          title={envoyee ? "Notification envoyée : mode figé (effacez la date d'envoi pour corriger)" : undefined}>
          <option value="lre" disabled={!envoyee && !n.modes_admis.includes("lre")}>LRE (électronique)</option>
          <option value="lrar" disabled={!envoyee && !n.modes_admis.includes("lrar")}>LRAR (papier, sur demande)</option>
        </Select>
        <Input type="date" value={f.date_envoi} onChange={(e) => setF({ ...f, date_envoi: e.target.value })} />
        <Input type="date" value={f.date_presentation} onChange={(e) => setF({ ...f, date_presentation: e.target.value })} />
        <Input placeholder="Référence" value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} />
        <Button variant="secondary" className="px-2.5 py-1.5 text-xs" onClick={save}>Enregistrer</Button>
      </div>
      <p className="mt-1 text-[11px] text-slate-400">Mode · date d'envoi · date de première présentation / avis électronique · référence</p>
    </div>
  );
}

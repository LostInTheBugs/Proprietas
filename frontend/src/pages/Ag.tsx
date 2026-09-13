import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useUser } from "../auth";
import type { AG, Lot, Resolution, Majorite, Creneau, Invitation, InvitationsResult } from "../types";
import { fmtDate, fmtDateTime, toLocalInput } from "../types";
import { Button, Card, Input, Modal, Select, Badge, Empty } from "../components/ui";

export default function Ag() {
  const { user } = useUser();
  const isSyndic = user?.role === "syndic";
  const [ags, setAgs] = useState<AG[]>([]);
  const [lots, setLots] = useState<Lot[]>([]);
  const [majorites, setMajorites] = useState<Record<string, Majorite>>({});
  const [modal, setModal] = useState<null | { type: "ag" } | { type: "resolution"; agId: number }>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [a, l, m] = await Promise.all([
      api.get<AG[]>("/ag"),
      api.get<Lot[]>("/lots"),
      api.get<Record<string, Majorite>>("/majorites"),
    ]);
    setAgs(a);
    setLots(l);
    setMajorites(m);
  }, []);
  useEffect(() => { load().catch(() => {}); }, [load]);

  const total = lots.reduce((s, l) => s + l.tantiemes, 0);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Assemblées générales</h1>
          <p className="text-sm text-slate-500">
            Sondage de dates, convocations par email, votes et majorités légales
          </p>
        </div>
        {isSyndic && <Button onClick={() => setModal({ type: "ag" })}>+ Nouvelle AG</Button>}
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {ags.length === 0 ? (
        <Empty text="Aucune assemblée. Créez la prochaine AG : proposez des dates, envoyez les convocations, suivez les votes." />
      ) : (
        ags.map((ag) => (
          <Card
            key={ag.id}
            title={
              <span className="flex items-center gap-2">
                {ag.type_ag === "consultation_ecrite" ? "Consultation écrite" : ag.type_ag === "extraordinaire" ? "AG extraordinaire" : "AG annuelle"}
                <span className="text-slate-400">·</span>
                {fmtDate(ag.date)}
                {ag.heure && <span className="font-normal text-slate-400">à {ag.heure}</span>}
                {ag.lieu && <span className="font-normal text-slate-400">· {ag.lieu}</span>}
              </span>
            }
            action={
              <div className="flex items-center gap-2">
                <Badge color={ag.statut === "terminee" ? "green" : ag.statut === "convoquee" ? "indigo" : "amber"}>
                  {ag.statut === "terminee" ? "Terminée" : ag.statut === "convoquee" ? "Convoquée" : "Projet"}
                </Badge>
                {ag.rappel_jours > 0 && !ag.convocation_envoyee && ag.statut !== "terminee" && (
                  <Badge color="indigo">⏰ Convocation auto J-{ag.rappel_jours}</Badge>
                )}
                {ag.convocation_envoyee && (
                  <Badge color="green">📨 Convocation envoyée</Badge>
                )}
                {isSyndic && (
                  <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setModal({ type: "resolution", agId: ag.id })}>
                    + Résolution
                  </Button>
                )}
              </div>
            }
          >
            <div className="space-y-5">
              {ag.resolutions.length === 0 ? (
                <Empty text="Aucune résolution à l'ordre du jour." />
              ) : (
                <div className="space-y-4">
                  {ag.resolutions.map((r) => (
                    <ResolutionCard key={r.id} r={r} lots={lots} total={total} majorites={majorites} isSyndic={isSyndic} onChanged={load} onError={setError} />
                  ))}
                </div>
              )}
              <AgExtras agId={ag.id} ag={ag} lots={lots} isSyndic={isSyndic} onAgChanged={load} onError={setError} />
            </div>
          </Card>
        ))
      )}

      {modal?.type === "ag" && <AgModal onClose={() => setModal(null)} onSaved={() => { setModal(null); load(); }} onError={setError} />}
      {modal?.type === "resolution" && (
        <ResolutionModal agId={modal.agId} majorites={majorites} onClose={() => setModal(null)} onSaved={() => { setModal(null); load(); }} onError={setError} />
      )}
    </div>
  );
}

// ---------- Sondage de dates + invitations ----------
function AgExtras({ agId, ag, lots, isSyndic, onAgChanged, onError }: {
  agId: number; ag: AG; lots: Lot[]; isSyndic: boolean;
  onAgChanged: () => void; onError: (e: string) => void;
}) {
  const [creneaux, setCreneaux] = useState<Creneau[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [creneauModal, setCreneauModal] = useState(false);
  const [envoiInfo, setEnvoiInfo] = useState<InvitationsResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyPv, setBusyPv] = useState(false);

  const load = useCallback(async () => {
    const [c, i] = await Promise.all([
      api.get<Creneau[]>(`/ag/${agId}/creneaux`),
      api.get<Invitation[]>(`/ag/${agId}/invitations`),
    ]);
    setCreneaux(c);
    setInvitations(i);
  }, [agId]);
  useEffect(() => { load().catch(() => {}); }, [load]);

  async function voteCreneau(creneauId: number, lotId: number, dispo: boolean) {
    try {
      await api.post(`/creneaux/${creneauId}/votes`, { lot_id: lotId, dispo });
      load();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }

  async function choisir(creneauId: number) {
    try {
      await api.post(`/ag/${agId}/choisir-creneau/${creneauId}`);
      load();
      onAgChanged();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }

  async function envoyerInvitations() {
    setBusy(true);
    setEnvoiInfo(null);
    try {
      const res = await api.post<InvitationsResult>(`/ag/${agId}/invitations`);
      setEnvoiInfo(res);
      load();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setBusy(false);
    }
  }

  async function envoyerPv() {
    setBusyPv(true);
    setEnvoiInfo(null);
    try {
      const res = await api.post<InvitationsResult>(`/ag/${agId}/pv/envoyer`);
      setEnvoiInfo(res);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setBusyPv(false);
    }
  }

  if (creneaux.length === 0 && invitations.length === 0 && !isSyndic) return null;

  return (
    <div className="space-y-4 border-t border-slate-100 pt-4">
      {/* Sondage de dates */}
      {creneaux.length > 0 && (
        <div>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-semibold text-slate-700">📅 Sondage de dates — disponibilités par lot</p>
            {isSyndic && (
              <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setCreneauModal(true)}>
                + Créneau
              </Button>
            )}
          </div>
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2 font-medium">Lot</th>
                  {creneaux.map((c) => {
                    const dispo = c.votes.filter((v) => v.dispo).length;
                    return (
                      <th key={c.id} className="px-3 py-2 text-center font-medium">
                        <span className="block whitespace-nowrap">{fmtDateTime(c.debut)}</span>
                        <span className={`block text-[11px] font-bold ${dispo === lots.length ? "text-emerald-600" : dispo > 0 ? "text-amber-600" : "text-slate-400"}`}>
                          {dispo}/{lots.length} dispo
                        </span>
                      </th>
                    );
                  })}
                  {isSyndic && <th className="px-2 py-2" />}
                </tr>
              </thead>
              <tbody>
                {lots.map((lot) => (
                  <tr key={lot.id} className="border-b border-slate-50 last:border-0">
                    <td className="px-3 py-2 font-medium text-slate-700">Lot {lot.numero}</td>
                    {creneaux.map((c) => {
                      const v = c.votes.find((x) => x.lot_id === lot.id);
                      const dispo = v?.dispo ?? false;
                      return (
                        <td key={c.id} className="px-3 py-2 text-center">
                          {isSyndic ? (
                            <button
                              onClick={() => voteCreneau(c.id, lot.id, !dispo)}
                              className={`inline-flex h-6 w-6 items-center justify-center rounded-md text-xs font-bold transition-colors ${
                                dispo ? "bg-emerald-500 text-white" : "bg-slate-100 text-slate-400 hover:bg-slate-200"
                              }`}
                              title={dispo ? "Disponible — cliquer pour retirer" : "Indisponible — cliquer pour marquer dispo"}
                            >
                              {dispo ? "✓" : "·"}
                            </button>
                          ) : (
                            <span className={`inline-flex h-6 w-6 items-center justify-center rounded-md text-xs font-bold ${dispo ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-400"}`}>
                              {dispo ? "✓" : "·"}
                            </span>
                          )}
                        </td>
                      );
                    })}
                    {isSyndic && <td className="px-2 py-2 text-right" />}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {isSyndic && (
            <div className="mt-2 flex flex-wrap gap-2">
              {creneaux.map((c) => {
                const dispo = c.votes.filter((v) => v.dispo).length;
                return (
                  <span key={c.id} className="inline-flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1 text-xs ring-1 ring-slate-200">
                    {fmtDateTime(c.debut)}
                    <button
                      onClick={() => choisir(c.id)}
                      className="font-semibold text-indigo-600 hover:text-indigo-700"
                      title="Retenir ce créneau pour l'AG"
                    >
                      Choisir
                    </button>
                    <button
                      onClick={async () => { await api.del(`/creneaux/${c.id}`); load(); }}
                      className="text-slate-400 hover:text-red-600"
                      title="Supprimer ce créneau"
                    >
                      ✕
                    </button>
                    <span className={dispo === lots.length ? "font-bold text-emerald-600" : "font-medium text-slate-500"}>
                      {dispo}/{lots.length}
                    </span>
                  </span>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Invitations */}
      {(isSyndic || invitations.length > 0) && (
        <div>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-slate-700">✉️ Convocations et procès-verbal</p>
            <div className="flex items-center gap-2">
              <a
                href={`/api/ag/${agId}/pv`}
                className="rounded-lg bg-slate-100 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200"
                title="Télécharger le procès-verbal en PDF"
              >
                📄 PV (PDF)
              </a>
              {isSyndic && (
                <Button variant="secondary" className="px-2.5 py-1.5 text-xs" disabled={busy} onClick={envoyerInvitations}>
                  {busy ? "Envoi…" : invitations.length > 0 ? "Renvoyer les convocations" : "Envoyer les convocations"}
                </Button>
              )}
              {isSyndic && (
                <Button variant="secondary" className="px-2.5 py-1.5 text-xs" disabled={busyPv} onClick={envoyerPv}>
                  {busyPv ? "Envoi…" : "✉️ Envoyer le PV"}
                </Button>
              )}
            </div>
          </div>
          {envoiInfo && (
            <p className="mb-2 rounded-lg bg-indigo-50 px-3 py-2 text-xs text-indigo-800">
              {envoiInfo.envoyes} email(s) envoyé(s)
              {envoiInfo.sans_email > 0 && ` · ${envoiInfo.sans_email} propriétaire(s) sans adresse email`}
              {envoiInfo.erreurs.length > 0 && (
                <span className="block text-red-700">Échecs : {envoiInfo.erreurs.join(" · ")}</span>
              )}
            </p>
          )}
          {invitations.length > 0 && (
            <ul className="space-y-1 text-xs text-slate-500">
              {invitations.slice(0, 10).map((i) => (
                <li key={i.id} className="flex items-center gap-2">
                  <span className="font-medium text-slate-700">{i.personne_nom}</span>
                  <span className="text-slate-400">({i.personne_email})</span>
                  <span className="ml-auto">{fmtDateTime(i.date_envoi)}</span>
                  {i.statut === "envoye" ? <Badge color="green">envoyé</Badge> : <Badge color="red">erreur</Badge>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {creneauModal && (
        <CreneauModal onClose={() => setCreneauModal(false)} onSaved={() => { setCreneauModal(false); load(); }} onError={onError} agId={agId} />
      )}
    </div>
  );
}

function CreneauModal({ agId, onClose, onSaved, onError }: {
  agId: number; onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const [debut, setDebut] = useState(toLocalInput(new Date(Date.now() + 7 * 86400000)));
  const [fin, setFin] = useState("");
  async function save() {
    try {
      await api.post(`/ag/${agId}/creneaux`, {
        debut: new Date(debut).toISOString(),
        fin: fin ? new Date(fin).toISOString() : null,
      });
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  return (
    <Modal open title="Proposer un créneau" onClose={onClose}>
      <div className="space-y-3">
        <Input label="Date et heure de début" type="datetime-local" value={debut} onChange={(e) => setDebut(e.target.value)} />
        <Input label="Fin (optionnel)" type="datetime-local" value={fin} onChange={(e) => setFin(e.target.value)} />
        <p className="text-xs text-slate-500">Proposez plusieurs créneaux : les copropriétaires indiqueront leurs disponibilités.</p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>Ajouter</Button>
        </div>
      </div>
    </Modal>
  );
}

function ResolutionCard({ r, lots, total, majorites, isSyndic, onChanged, onError }: {
  r: Resolution; lots: Lot[]; total: number; majorites: Record<string, Majorite>;
  isSyndic: boolean; onChanged: () => void; onError: (e: string) => void;
}) {
  const res = r.resultat;
  const pct = total > 0 ? (res ? (res.pour / total) * 100 : 0) : 0;
  const majorite = majorites[r.majorite];

  async function vote(lotId: number, voix: string) {
    try {
      await api.post(`/resolutions/${r.id}/votes`, { lot_id: lotId, voix });
      await api.post(`/resolutions/${r.id}/calculer`);
      onChanged();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }

  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium text-slate-800">
            <span className="mr-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs font-bold text-slate-500">Résolution {r.numero}</span>
            {r.libelle}
          </p>
          <p className="mt-0.5 text-xs text-slate-500">{majorite?.label ?? r.majorite} · {majorite?.description ?? ""}</p>
          {r.texte && <p className="mt-1 text-xs text-slate-500">{r.texte}</p>}
        </div>
        <div className="flex items-center gap-2">
          {r.statut === "a_voter" && <Badge color="amber">À voter</Badge>}
          {r.statut === "adoptee" && <Badge color="green">Adoptée</Badge>}
          {r.statut === "rejetee" && <Badge color="red">Rejetée</Badge>}
        </div>
      </div>

      {res && (
        <div className="mt-3">
          <div className="flex items-center gap-3 text-xs text-slate-500">
            <span>
              Pour : <b className="text-emerald-600 tabular-nums">{res.pour}‰</b>
            </span>
            <span>
              Contre : <b className="text-red-600 tabular-nums">{res.contre}‰</b>
            </span>
            <span>
              Abstention : <b className="tabular-nums">{res.abstention}‰</b>
            </span>
            <span className="ml-auto font-medium">{pct.toFixed(0)} % des millièmes pour</span>
          </div>
          <div className="mt-1.5 flex h-2 overflow-hidden rounded-full bg-slate-100">
            <div className="bg-emerald-500" style={{ width: `${(res.pour / total) * 100}%` }} />
            <div className="bg-red-400" style={{ width: `${(res.contre / total) * 100}%` }} />
            <div className="bg-slate-300" style={{ width: `${(res.abstention / total) * 100}%` }} />
          </div>
          {res.regime_deux && (
            <p className="mt-1.5 text-xs font-medium text-indigo-600">ℹ {res.detail}</p>
          )}
        </div>
      )}

      {isSyndic && (
        <div className="mt-3 grid grid-cols-2 gap-1.5 sm:grid-cols-4 lg:grid-cols-6">
          {lots.map((lot) => {
            const v = r.votes.find((x) => x.lot_id === lot.id);
            const current = v?.voix ?? "null";
            return (
              <div key={lot.id} className="rounded border border-slate-200 p-1.5">
                <p className="mb-1 text-center text-xs font-semibold text-slate-600">
                  Lot {lot.numero} <span className="font-normal text-slate-500">({lot.tantiemes}‰)</span>
                </p>
                <div className="grid grid-cols-3 gap-0.5 text-center">
                  {(["pour", "contre", "abstention"] as const).map((voix) => (
                    <button
                      key={voix}
                      onClick={() => vote(lot.id, voix)}
                      className={`rounded py-1 text-[11px] font-medium transition-colors ${
                        current === voix
                          ? voix === "pour"
                            ? "bg-emerald-500 text-white"
                            : voix === "contre"
                              ? "bg-red-500 text-white"
                              : "bg-slate-400 text-white"
                          : "bg-slate-50 text-slate-500 hover:bg-slate-100"
                      }`}
                    >
                      {voix === "pour" ? "Pour" : voix === "contre" ? "Contre" : "Abst."}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function AgModal({ onClose, onSaved, onError }: { onClose: () => void; onSaved: () => void; onError: (e: string) => void }) {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [heure, setHeure] = useState("");
  const [typeAg, setTypeAg] = useState("annuelle");
  const [statut, setStatut] = useState("projet");
  const [lieu, setLieu] = useState("");
  const [rappelJours, setRappelJours] = useState("15");
  async function save() {
    try {
      await api.post("/ag", { date, heure, type_ag: typeAg, statut, lieu, notes: "", rappel_jours: Number(rappelJours) || 0 });
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  return (
    <Modal open title="Nouvelle assemblée" onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Input label="Date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <Input label="Heure (si déjà fixée)" type="time" value={heure} onChange={(e) => setHeure(e.target.value)} />
        </div>
        <Select label="Type" value={typeAg} onChange={(e) => setTypeAg(e.target.value)}>
          <option value="annuelle">AG annuelle</option>
          <option value="extraordinaire">AG extraordinaire</option>
          <option value="consultation_ecrite">Consultation écrite (unanimité)</option>
        </Select>
        <Select label="Statut" value={statut} onChange={(e) => setStatut(e.target.value)}>
          <option value="projet">Projet</option>
          <option value="convoquee">Convoquée</option>
          <option value="terminee">Terminée</option>
        </Select>
        <Input label="Lieu" value={lieu} onChange={(e) => setLieu(e.target.value)} placeholder="Chez M. Durand" />
        <Input
          label="Envoi automatique de la convocation (jours avant l'AG, 0 = désactivé)"
          type="number"
          min={0}
          max={90}
          value={rappelJours}
          onChange={(e) => setRappelJours(e.target.value)}
        />
        <p className="text-xs text-slate-500">
          ⏰ Le serveur enverra les convocations par email <b>{rappelJours === "0" || !rappelJours ? "— désactivé" : `${rappelJours} jours avant`}</b> l'AG.
          Délai légal : 15 jours minimum (art. 9 décret n°67-223).
        </p>
        {typeAg !== "consultation_ecrite" && (
          <p className="text-xs text-slate-500">
            Astuce : laissez la date à définir et proposez plusieurs créneaux dans le sondage ci-dessous — l'AG se mettra à jour automatiquement quand vous en choisirez un.
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>Créer</Button>
        </div>
      </div>
    </Modal>
  );
}

function ResolutionModal({ agId, majorites, onClose, onSaved, onError }: {
  agId: number; majorites: Record<string, Majorite>; onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const [numero, setNumero] = useState("1");
  const [libelle, setLibelle] = useState("");
  const [texte, setTexte] = useState("");
  const [majorite, setMajorite] = useState("art24");
  async function save() {
    try {
      await api.post(`/ag/${agId}/resolutions`, { numero: Number(numero), libelle, texte, majorite });
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  return (
    <Modal open title="Nouvelle résolution" onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          <Input label="N°" type="number" value={numero} onChange={(e) => setNumero(e.target.value)} />
          <Select label="Majorité requise" value={majorite} onChange={(e) => setMajorite(e.target.value)} className="col-span-2">
            {Object.entries(majorites).map(([k, m]) => (
              <option key={k} value={k}>{m.label}</option>
            ))}
          </Select>
        </div>
        <Input label="Libellé" value={libelle} onChange={(e) => setLibelle(e.target.value)} placeholder="Approbation des comptes de l'exercice précédent" />
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-600">Texte détaillé (optionnel)</span>
          <textarea
            value={texte}
            onChange={(e) => setTexte(e.target.value)}
            rows={3}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </label>
        {majorite && majorites[majorite] && (
          <p className="text-xs text-slate-500">{majorites[majorite].description}</p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>Ajouter</Button>
        </div>
      </div>
    </Modal>
  );
}

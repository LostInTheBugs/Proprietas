import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useUser } from "../auth";
import type { AG, Lot, Resolution, Majorite, Creneau, Invitation, InvitationsResult, Recap, Exercice } from "../types";
import { fmtDate, fmtDateTime, toLocalInput } from "../types";
import { Button, Card, Input, Modal, Select, Badge, Empty } from "../components/ui";
import NotificationsPVPanel from "../components/NotificationsPV";
import { CorrespondanceSyndic, MaReponseAg, PresencesSyndic } from "../components/Presences";
import { ListeModele, ResolutionsTypesModal, useModele } from "../components/ResolutionsTypes";
import { useCles } from "../components/Cles";
import { MandatsCard, useMandats } from "../components/Mandats";
export default function Ag() {
  const { user } = useUser();
  const isSyndic = user?.role === "syndic";
  const [types, setTypes] = useState<{ agId: number; jour: string } | null>(null);   // résolutions types
  const [ags, setAgs] = useState<AG[]>([]);
  const [lots, setLots] = useState<Lot[]>([]);
  const [majorites, setMajorites] = useState<Record<string, Majorite>>({});
  const [modal, setModal] = useState<null | { type: "ag"; ag?: AG } | { type: "resolution"; agId: number; resolution?: Resolution }>(null);
  const [error, setError] = useState("");
  const [revMandats, setRevMandats] = useState(0);   // recharge les mandats après un vote ou une modification

  const load = useCallback(async () => {
    setRevMandats((n) => n + 1);
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

  async function supprimerAg(ag: AG) {
    const quoi = `${ag.type_ag === "consultation_ecrite" ? "la consultation écrite" : "l'AG"} du ${fmtDate(ag.date)}`;
    if (!confirm(`Supprimer ${quoi} ? Ses ${ag.resolutions.length} résolution(s), les votes, les réponses et pouvoirs, les `
      + "votes par correspondance et le sondage de dates seront supprimés. Une approbation des comptes votée à cette AG "
      + "sera retirée de l'exercice. C'est définitif.")) return;
    try { await api.del(`/ag/${ag.id}`); setError(""); load(); }
    catch (e) { setError(e instanceof Error ? e.message : "Erreur"); }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Assemblées générales</h1>
          <p className="text-sm text-slate-500">
            Sondage de dates, e-mails d'information, votes et majorités légales
          </p>
        </div>
        {isSyndic && <Button onClick={() => setModal({ type: "ag" })}>+ Nouvelle AG</Button>}
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <MandatsCard isSyndic={isSyndic} ags={ags} rev={revMandats} />

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
                  <Badge color="indigo">⏰ E-mail d'information auto J-{ag.rappel_jours}</Badge>
                )}
                {ag.convocation_envoyee && (
                  <Badge color="green">📨 Information envoyée par e-mail</Badge>
                )}
                {isSyndic && ag.type_ag !== "consultation_ecrite" && (
                  <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setTypes({ agId: ag.id, jour: ag.date })}>
                    Résolutions types
                  </Button>
                )}
                {isSyndic && (
                  <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setModal({ type: "resolution", agId: ag.id })}>
                    + Résolution
                  </Button>
                )}
                {isSyndic && (
                  <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setModal({ type: "ag", ag })}>
                    Modifier
                  </Button>
                )}
                {isSyndic && (
                  <Button variant="ghost" className="px-2 py-1 text-xs text-red-600" onClick={() => supprimerAg(ag)}>
                    Supprimer
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
                    <ResolutionCard key={r.id} r={r} lots={lots} total={total} majorites={majorites} isSyndic={isSyndic}
                      aUnSecondVote={ag.resolutions.some((x) => x.second_vote_de_id === r.id)}
                      onEdit={() => setModal({ type: "resolution", agId: ag.id, resolution: r })}
                      onChanged={load} onError={setError} />
                  ))}
                </div>
              )}
              <AgExtras agId={ag.id} ag={ag} lots={lots} isSyndic={isSyndic} onAgChanged={load} onError={setError} />
            </div>
          </Card>
        ))
      )}

      {types && (
        <ResolutionsTypesModal agId={types.agId} jour={types.jour} onClose={() => setTypes(null)}
          onSaved={() => { setTypes(null); load(); }} onError={setError} />
      )}
      {modal?.type === "ag" && <AgModal initial={modal.ag} onClose={() => setModal(null)} onSaved={() => { setModal(null); load(); }} onError={setError} />}
      {modal?.type === "resolution" && (
        <ResolutionModal agId={modal.agId} initial={modal.resolution} majorites={majorites}
          consultation={ags.find((a) => a.id === modal.agId)?.type_ag === "consultation_ecrite"} onClose={() => setModal(null)} onSaved={() => { setModal(null); load(); }} onError={setError} />
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
  const [revPresences, setRevPresences] = useState(0);   // recharge les présences après un vote par correspondance

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

  if (creneaux.length === 0 && invitations.length === 0 && !isSyndic)
    return ag.type_ag !== "consultation_ecrite" ? <MaReponseAg agId={agId} onError={onError} /> : null;

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
            <p className="text-sm font-semibold text-slate-700">✉️ Information par e-mail et procès-verbal</p>
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
                  {busy ? "Envoi…" : invitations.length > 0 ? "Renvoyer l'information" : "Informer par e-mail"}
                </Button>
              )}
              {isSyndic && (
                <Button variant="secondary" className="px-2.5 py-1.5 text-xs" disabled={busyPv} onClick={envoyerPv}>
                  {busyPv ? "Envoi…" : "✉️ Envoyer le PV (information)"}
                </Button>
              )}
            </div>
          </div>
          <p className="mb-2 text-xs text-slate-500">
            Ces e-mails sont une <b>information</b>. La convocation régulière (au moins 21 jours avant
            l'assemblée) et la notification du procès-verbal aux opposants et défaillants se font par
            lettre recommandée électronique (par défaut), par lettre recommandée avec avis de réception
            pour les copropriétaires qui ont demandé la voie postale ou, pour la convocation, par remise
            contre récépissé (loi n° 65-557, art. 42-1 ; décret n° 67-223, art. 9 et 64 et suivants).
          </p>
          {envoiInfo && (
            <p className="mb-2 rounded-lg bg-indigo-50 px-3 py-2 text-xs text-indigo-800">
              {envoiInfo.envoyes} email(s) envoyé(s)
              {envoiInfo.sans_email > 0 && ` · ${envoiInfo.sans_email} propriétaire(s) sans adresse email`}
              {envoiInfo.erreurs.length > 0 && (
                <span className="block text-red-700">Échecs : {envoiInfo.erreurs.join(" · ")}</span>
              )}
            </p>
          )}
          {invitations.length > 0 && (() => {
            const envois = invitations.filter((i) => i.statut === "envoye");
            const confirmes = envois.filter((i) => i.confirme_le);
            return envois.length > 0 && (
              <p className="text-xs text-slate-600">
                Réception confirmée par <strong>{confirmes.length}</strong> destinataire(s) sur {envois.length}
                <span className="text-slate-400"> (lien « J'ai bien reçu ce message » de l'e-mail ; ce n'est pas un accusé de réception de recommandé)</span>
              </p>
            );
          })()}
          {invitations.length > 0 && (
            <ul className="space-y-1 text-xs text-slate-500">
              {invitations.slice(0, 10).map((i) => (
                <li key={i.id} className="flex items-center gap-2">
                  <span className="font-medium text-slate-700">{i.personne_nom}</span>
                  <span className="text-slate-400">({i.personne_email})</span>
                  <span className="ml-auto">{fmtDateTime(i.date_envoi)}</span>
                  {i.statut === "envoye" ? <Badge color="green">envoyé</Badge> : <Badge color="red">erreur</Badge>}
                  {i.statut === "envoye" && (i.confirme_le
                    ? <span title={`Réception confirmée le ${fmtDateTime(i.confirme_le)}`}><Badge color="indigo">reçu ✓</Badge></span>
                    : <Badge color="slate">non confirmé</Badge>)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {ag.type_ag !== "consultation_ecrite" && <MaReponseAg agId={agId} onError={onError} />}
      {isSyndic && ag.type_ag !== "consultation_ecrite" && <PresencesSyndic key={revPresences} agId={agId} onError={onError} />}
      {isSyndic && ag.type_ag !== "consultation_ecrite" && (
        <CorrespondanceSyndic agId={agId} resolutions={ag.resolutions}
          onChanged={() => { setRevPresences((x) => x + 1); load(); }} onError={onError} />
      )}

      {isSyndic && ag.resolutions.length > 0 && <NotificationsPVPanel agId={agId} onError={onError} />}

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

function ResolutionCard({ r, lots, total, majorites, isSyndic, aUnSecondVote, onEdit, onChanged, onError }: {
  r: Resolution; lots: Lot[]; total: number; majorites: Record<string, Majorite>;
  isSyndic: boolean; aUnSecondVote: boolean; onEdit: () => void; onChanged: () => void; onError: (e: string) => void;
}) {
  async function supprimer() {
    if (!confirm(`Supprimer la résolution n° ${r.numero} « ${r.libelle} » et ses votes ?`)) return;
    try { await api.del(`/resolutions/${r.id}`); onChanged(); } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  const [cles] = useCles();
  // Résolution sur une clé (art. 24, dernier alinéa) : seuls les lots de la clé votent, avec ses millièmes.
  const cle = r.cle_id != null ? cles.find((c) => c.id === r.cle_id) : undefined;
  const votants = cle
    ? lots.filter((l) => cle.lots.some((x) => x.lot_id === l.id))
        .map((l) => ({ ...l, tantiemes: cle.lots.find((x) => x.lot_id === l.id)?.tantiemes ?? 0 }))
    : lots;
  const res = r.resultat;
  // Base de calcul : le total de référence du moteur (réduit par l'art. 22 le cas échéant).
  const base = res && res.total > 0 ? res.total : total;
  const pct = base > 0 ? (res ? (res.pour / base) * 100 : 0) : 0;
  const majorite = majorites[r.majorite];

  async function secondVote() {
    try {
      await api.post(`/resolutions/${r.id}/second-vote`);
      onChanged();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }

  async function amender(amendee: boolean) {
    try {
      await api.put(`/resolutions/${r.id}/amendee`, { amendee });
      await api.post(`/resolutions/${r.id}/calculer`);
      onChanged();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }

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
          <p className="mt-0.5 text-xs text-slate-500">
            {r.nature && r.nature !== "autre" && <b>{NATURES[r.nature] ?? r.nature} · </b>}
            {majorite?.label ?? r.majorite} · {majorite?.description ?? ""}
          </p>
          {r.texte && <p className="mt-1 text-xs text-slate-500">{r.texte}</p>}
        </div>
        <div className="flex items-center gap-2">
          {r.second_vote_de_id !== null && <Badge color="indigo">Second vote</Badge>}
          {r.amendee && <Badge color="amber">Amendée en séance</Badge>}
          {r.cle_id != null && <Badge color="indigo">Clé : {r.cle_nom || cle?.nom || "?"}</Badge>}
          {r.statut === "a_voter" && <Badge color="amber">À voter</Badge>}
          {r.statut === "adoptee" && <Badge color="green">Adoptée</Badge>}
          {r.statut === "rejetee" && <Badge color="red">Rejetée</Badge>}
          {isSyndic && r.second_vote_de_id === null && (
            <Button variant="ghost" className="px-2 py-1 text-xs" onClick={onEdit}>Modifier</Button>
          )}
          {isSyndic && (
            <Button variant="ghost" className="px-2 py-1 text-xs text-red-600" onClick={supprimer}>Supprimer</Button>
          )}
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
            <div className="bg-emerald-500" style={{ width: `${(res.pour / base) * 100}%` }} />
            <div className="bg-red-400" style={{ width: `${(res.contre / base) * 100}%` }} />
            <div className="bg-slate-300" style={{ width: `${(res.abstention / base) * 100}%` }} />
          </div>
          {r.majorite === "art26" && (
            <p className="mt-1.5 text-xs text-slate-600">
              Membres pour : <b className="tabular-nums">{res.membres_pour} / {res.nb_membres}</b> (majorité des membres requise)
            </p>
          )}
          <p className={`mt-1.5 text-xs ${res.regime_deux || res.reduction_art22 !== null ? "font-medium text-indigo-600" : "text-slate-500"}`}>
            ℹ {res.detail}
          </p>
          {isSyndic && res.second_vote_possible && !aUnSecondVote && (
            <Button variant="secondary" className="mt-2 px-2.5 py-1.5 text-xs" onClick={secondVote}>
              Procéder au second vote ({res.second_vote_possible === "art24" ? "art. 24" : "art. 25"})
            </Button>
          )}
        </div>
      )}

      {isSyndic && r.second_vote_de_id === null && (
        <label className="mt-2 flex items-center gap-2 text-xs text-slate-600">
          <input type="checkbox" checked={!!r.amendee} onChange={(e) => amender(e.target.checked)} />
          Amendée en séance (les votes « pour » par correspondance comptent comme défaillants, art. 17-1 A)
        </label>
      )}
      {isSyndic && (
        <div className="mt-3 grid grid-cols-2 gap-1.5 sm:grid-cols-4 lg:grid-cols-6">
          {votants.map((lot) => {
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

// Objet de la résolution : le budget prévisionnel et l'approbation des comptes sont exclus de la
// consultation écrite (art. 41-12 de la loi du 10 juillet 1965).
const NATURES: Record<string, string> = {
  autre: "Autre décision",
  budget: "Vote du budget prévisionnel",
  approbation_comptes: "Approbation des comptes",
  syndic: "Désignation du syndic",
  conseil: "Élection du conseil syndical",
};
const HORS_CONSULTATION = ["budget", "approbation_comptes"];

function AgModal({ initial, onClose, onSaved, onError }: {
  initial?: AG; onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const [date, setDate] = useState(initial?.date ?? new Date().toISOString().slice(0, 10));
  const [heure, setHeure] = useState(initial?.heure ?? "");
  const [typeAg, setTypeAg] = useState(initial?.type_ag ?? "annuelle");
  const [statut, setStatut] = useState(initial?.statut ?? "projet");
  const [lieu, setLieu] = useState(initial?.lieu ?? "");
  const [rappelJours, setRappelJours] = useState(initial ? String(initial.rappel_jours) : "21");
  // AG annuelle : résolutions types (pré-cochées : celles de chaque année) — à la création seulement.
  const [modele, choix, setChoix] = useModele(typeAg === "annuelle" && !initial ? date : "");
  // Consultation écrite réservée aux petites copropriétés (art. 41-8 et 41-12) : null = inconnu.
  const [petite, setPetite] = useState<boolean | null>(null);
  useEffect(() => {
    api.get<Recap>("/recap").then((r) => setPetite(r.regime_petite_copro)).catch(() => setPetite(null));
  }, []);
  async function save() {
    try {
      const corps = { date, heure, type_ag: typeAg, statut, lieu, notes: initial?.notes ?? "", rappel_jours: Number(rappelJours) || 0 };
      if (initial) { await api.put(`/ag/${initial.id}`, corps); onSaved(); return; }
      const ag = await api.post<{ id: number }>("/ag", corps);
      if (typeAg === "annuelle" && choix.size > 0) await api.post(`/ag/${ag.id}/resolutions-types`, { codes: [...choix] });
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  return (
    <Modal open title={initial ? "Modifier l'assemblée" : "Nouvelle assemblée"} onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Input label="Date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <Input label="Heure (si déjà fixée)" type="time" value={heure} onChange={(e) => setHeure(e.target.value)} />
        </div>
        <Select label="Type" value={typeAg} onChange={(e) => setTypeAg(e.target.value)}>
          <option value="annuelle">AG annuelle</option>
          <option value="extraordinaire">AG extraordinaire</option>
          <option value="consultation_ecrite" disabled={petite === false}>Consultation écrite (unanimité)</option>
        </Select>
        {petite === false && (
          <p className="text-xs text-slate-500">
            La consultation écrite est réservée aux petites copropriétés (art. 41-8 et 41-12 de la loi du
            10 juillet 1965) : voir le détail du régime sur la page Comptes.
          </p>
        )}
        {typeAg === "consultation_ecrite" && (
          <p className="text-xs text-slate-500">
            Décisions à l'unanimité des voix de tous les copropriétaires. Le budget prévisionnel et
            l'approbation des comptes ne peuvent pas être décidés par consultation écrite.
          </p>
        )}
        {typeAg === "annuelle" && !initial && modele.length > 0 && (
          <div>
            <p className="mb-1 text-sm font-medium text-slate-600">Résolutions types à l'ordre du jour</p>
            <ListeModele modele={modele} choix={choix} onChange={setChoix} />
            <p className="mt-1 text-xs text-slate-500">Textes à compléter (« …… ») avant la convocation ; tout reste modifiable.</p>
          </div>
        )}
        <Select label="Statut" value={statut} onChange={(e) => setStatut(e.target.value)}>
          <option value="projet">Projet</option>
          <option value="convoquee">Convoquée</option>
          <option value="terminee">Terminée</option>
        </Select>
        <Input label="Lieu" value={lieu} onChange={(e) => setLieu(e.target.value)} placeholder="Chez M. Durand" />
        <Input
          label="E-mail d'information automatique (jours avant l'AG : 0 = désactivé, sinon 21 à 90)"
          type="number"
          min={0}
          max={90}
          value={rappelJours}
          onChange={(e) => setRappelJours(e.target.value)}
        />
        <p className="text-xs text-slate-500">
          ⏰ Le serveur enverra un e-mail d'information <b>{rappelJours === "0" || !rappelJours ? "— désactivé" : `${rappelJours} jours avant`}</b> l'AG.
          Délai légal de convocation : 21 jours minimum (art. 9 du décret n° 67-223). Cet e-mail ne remplace
          pas la convocation régulière (lettre recommandée électronique par défaut, LRAR si le copropriétaire a
          demandé la voie postale, ou remise contre récépissé).
        </p>
        {typeAg !== "consultation_ecrite" && (
          <p className="text-xs text-slate-500">
            Astuce : laissez la date à définir et proposez plusieurs créneaux dans le sondage ci-dessous — l'AG se mettra à jour automatiquement quand vous en choisirez un.
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>{initial ? "Enregistrer" : "Créer"}</Button>
        </div>
      </div>
    </Modal>
  );
}

function ResolutionModal({ agId, initial, majorites, consultation, onClose, onSaved, onError }: {
  agId: number; initial?: Resolution; majorites: Record<string, Majorite>; consultation: boolean;
  onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const [numero, setNumero] = useState(initial ? String(initial.numero) : "1");
  const [libelle, setLibelle] = useState(initial?.libelle ?? "");
  const [texte, setTexte] = useState(initial?.texte ?? "");
  // Consultation écrite : unanimité imposée (art. 41-12).
  const [majorite, setMajorite] = useState(initial?.majorite ?? (consultation ? "unanimite" : "art24"));
  const [nature, setNature] = useState(initial?.nature ?? "autre");
  // Approbation des comptes : l'exercice approuvé (reporté sur l'exercice si la résolution est adoptée).
  const [exercices, setExercices] = useState<Exercice[]>([]);
  const [exerciceId, setExerciceId] = useState(initial?.exercice_id != null ? String(initial.exercice_id) : "");
  const [cles] = useCles();
  const [cleId, setCleId] = useState(initial?.cle_id != null ? String(initial.cle_id) : "");
  const [effacerVotes, setEffacerVotes] = useState(false);
  const [mandats] = useMandats();
  const [mandatMois, setMandatMois] = useState(initial?.mandat_mois != null ? String(initial.mandat_mois) : "36");
  const [mandatIds, setMandatIds] = useState<number[]>(initial?.mandat_personnes ?? []);
  const estMandat = nature === "syndic" || nature === "conseil";
  useEffect(() => {
    api.get<Exercice[]>("/exercices").then(setExercices).catch(() => {});
  }, []);
  async function save() {
    try {
      const corps = {
        numero: Number(numero), libelle, texte, majorite, nature,
        exercice_id: nature === "approbation_comptes" && exerciceId ? Number(exerciceId) : null,
        cle_id: nature === "autre" && cleId ? Number(cleId) : null,
        mandat_mois: estMandat && mandatMois ? Number(mandatMois) : null,
        mandat_personnes: estMandat && mandatIds.length ? mandatIds : null,
      };
      if (initial) await api.put(`/resolutions/${initial.id}${effacerVotes ? "?effacer_votes=true" : ""}`, corps);
      else await api.post(`/ag/${agId}/resolutions`, corps);
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  return (
    <Modal open title={initial ? `Modifier la résolution n° ${initial.numero}` : "Nouvelle résolution"} onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          <Input label="N°" type="number" value={numero} onChange={(e) => setNumero(e.target.value)} />
          <Select label="Majorité requise" value={majorite} onChange={(e) => setMajorite(e.target.value)} className="col-span-2"
            disabled={consultation}>
            {Object.entries(majorites).map(([k, m]) => (
              <option key={k} value={k}>{m.label}</option>
            ))}
          </Select>
        </div>
        <Select label="Objet" value={nature} onChange={(e) => setNature(e.target.value)}>
          {Object.entries(NATURES).map(([k, l]) => (
            <option key={k} value={k} disabled={consultation && HORS_CONSULTATION.includes(k)}>{l}</option>
          ))}
        </Select>
        {nature === "approbation_comptes" && (
          <Select label="Exercice dont les comptes sont approuvés" value={exerciceId}
            onChange={(e) => setExerciceId(e.target.value)}>
            <option value="">— choisir —</option>
            {exercices.map((e) => (
              <option key={e.id} value={e.id}>{e.annee}{e.comptes_approuves_le ? " (déjà approuvés)" : ""}</option>
            ))}
          </Select>
        )}
        {estMandat && (
          <div className="space-y-2 rounded-lg border border-slate-200 p-2">
            <Input label="Durée du mandat (mois, 36 au plus)" type="number" min={1} max={36} value={mandatMois}
              onChange={(e) => setMandatMois(e.target.value)} />
            <span className="block text-sm font-medium text-slate-600">{nature === "syndic" ? "Syndic désigné" : "Membres élus"}</span>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
              {(mandats?.personnes ?? []).map((p) => (
                <label key={p.id} className="flex items-center gap-1.5 text-slate-700">
                  <input type={nature === "syndic" ? "radio" : "checkbox"} name="resolution-mandat" checked={mandatIds.includes(p.id)}
                    onChange={(e) => setMandatIds(nature === "syndic" ? (e.target.checked ? [p.id] : [])
                      : e.target.checked ? [...mandatIds, p.id] : mandatIds.filter((x) => x !== p.id))} />
                  {p.nom}
                </label>
              ))}
            </div>
            <p className="text-xs text-slate-500">
              Adoptée, la résolution enregistre le mandat à partir du jour de l'AG (carte « Syndic et conseil syndical »).
              Sans durée ou sans personne, rien n'est enregistré.
            </p>
          </div>
        )}
        {nature === "autre" && cles.length > 0 && (
          <Select label="Votants" value={cleId} onChange={(e) => setCleId(e.target.value)}>
            <option value="">Tous les copropriétaires (tantièmes généraux)</option>
            {cles.map((c) => <option key={c.id} value={c.id}>Seuls les lots de la clé « {c.nom} » (ses millièmes)</option>)}
          </Select>
        )}
        {nature === "autre" && cleId && (
          <p className="text-xs text-slate-500">
            Dépenses d'une partie de l'immeuble ou d'un équipement : si le règlement de copropriété le prévoit, seuls les
            copropriétaires qui y participent votent, avec leurs millièmes de la clé (loi du 10 juillet 1965, art. 24,
            dernier alinéa).
          </p>
        )}
        {consultation && (
          <p className="text-xs text-slate-500">
            Consultation écrite : unanimité de tous les copropriétaires ; le budget prévisionnel et
            l'approbation des comptes exigent une assemblée générale (art. 41-12).
          </p>
        )}
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
        {initial && initial.statut !== "a_voter" && (
          <p className="rounded bg-amber-50 px-2 py-1 text-xs text-amber-800">
            Résolution déjà votée : corriger le libellé ou le texte garde le résultat ; changer l'objet, l'exercice, la
            majorité ou la clé l'efface (à recalculer) et retire une approbation des comptes qu'elle avait reportée. Les
            votes saisis sont gardés et comptent au recalcul, sauf si vous cochez la case ci-dessous.
          </p>
        )}
        {initial && (
          <label className="flex items-center gap-2 text-xs text-slate-700">
            <input type="checkbox" checked={effacerVotes} onChange={(e) => setEffacerVotes(e.target.checked)} />
            Effacer aussi les votes saisis (en séance et par correspondance) : ils seront à ressaisir.
          </label>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>{initial ? "Enregistrer" : "Ajouter"}</Button>
        </div>
      </div>
    </Modal>
  );
}

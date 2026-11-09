import { useEffect, useState } from "react";
import { api } from "../api";
import type { Controle, EtatReprise, EtatRepriseDetail, Lot } from "../types";
import { fmtDate, fmtEUR } from "../types";
import { Badge, Button, Card, Empty, Input } from "../components/ui";

/**
 * Reprise de l'historique (tâche 32) : ce que chaque copropriétaire devait au 31 décembre d'une
 * année, par lot et par exercice d'origine. L'état validé le plus ancien est la base ; les états
 * validés plus récents sont des points de contrôle. Règles : backend/app/services/reprise.py.
 */

interface LigneSaisie {
  cle: number;
  lot_id: number | "";
  exercice_origine: string;
  montant_charges: string;
  montant_fonds_travaux: string;
}

const ROLE: Record<EtatReprise["role"], { label: string; color: "indigo" | "green" | "slate" }> = {
  base: { label: "Base", color: "indigo" },
  point_de_controle: { label: "Point de contrôle", color: "green" },
  brouillon: { label: "Brouillon", color: "slate" },
};

let compteur = 0;
const nouvelleCle = () => ++compteur;

/** « 1 234,50 » → « 1234.50 » ; vide → « 0 ». */
function montantSaisi(v: string): string {
  const s = v.replace(/[\s  ]/g, "").replace(",", ".");
  return s === "" || s === "-" ? "0" : s;
}

function versSaisie(d: EtatRepriseDetail): LigneSaisie[] {
  return d.lignes.map((l) => ({
    cle: nouvelleCle(),
    lot_id: l.lot_id,
    exercice_origine: String(l.exercice_origine),
    montant_charges: String(l.montant_charges),
    montant_fonds_travaux: String(l.montant_fonds_travaux),
  }));
}

export default function Historique() {
  const [etats, setEtats] = useState<EtatReprise[]>([]);
  const [lots, setLots] = useState<Lot[]>([]);
  const [ouvert, setOuvert] = useState<EtatRepriseDetail | null>(null);
  const [creation, setCreation] = useState(false);
  const [error, setError] = useState("");

  async function charger() {
    try {
      setEtats(await api.get<EtatReprise[]>("/reprise/etats"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    }
  }

  useEffect(() => {
    charger();
    api.get<Lot[]>("/lots").then(setLots).catch(() => {});
  }, []);

  async function ouvrir(id: number) {
    setError("");
    setCreation(false);
    try {
      setOuvert(await api.get<EtatRepriseDetail>(`/reprise/etats/${id}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    }
  }

  function fermer() {
    setOuvert(null);
    setCreation(false);
    charger();
  }

  const base = etats.find((e) => e.role === "base");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Historique</h1>
          <p className="text-sm text-slate-500">Reprise des soldes des copropriétaires au 31 décembre</p>
        </div>
        {!creation && !ouvert && (
          <Button onClick={() => { setError(""); setCreation(true); }}>+ Nouvel état</Button>
        )}
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <Card title="Comment ça marche">
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-600">
          <li>
            Un <b>état</b> indique ce que chaque copropriétaire devait au 31 décembre d'une année, par lot et par
            exercice d'origine. Un montant négatif est un crédit (trop-perçu).
          </li>
          <li>
            L'état validé le plus ancien est la <b>base</b> : il crée les appels « Reprise de solde », et tout ce qui
            est daté jusqu'à sa date (appels, encaissements) n'entre plus dans les soldes, pour ne jamais compter deux fois.
          </li>
          <li>
            Un état validé plus récent est un <b>point de contrôle</b> : la base, plus les appels, moins les
            encaissements saisis entre les deux dates, doit retomber exactement sur lui, lot par lot.
          </li>
          <li>
            Pour <b>remonter d'une année</b>, saisissez les appels et encaissements de l'année dans Comptes, puis validez
            l'état au 31 décembre précédent : il devient la base si tous les contrôles tombent juste.
          </li>
          <li>Un état validé ne se modifie plus : une correction passe par un appel ou un encaissement.</li>
        </ul>
      </Card>

      {creation && (
        <EditeurEtat
          lots={lots}
          anneeDefaut={base ? Number(base.date.slice(0, 4)) - 1 : new Date().getFullYear() - 1}
          onAnnuler={() => setCreation(false)}
          onEnregistre={(d) => { setCreation(false); setOuvert(d); charger(); }}
          onError={setError}
        />
      )}

      {ouvert && (
        <DetailEtat
          key={`${ouvert.id}-${ouvert.valide}`}
          etat={ouvert}
          lots={lots}
          onMaj={(d) => { setOuvert(d); charger(); }}
          onFermer={fermer}
          onError={setError}
        />
      )}

      {!creation && !ouvert && (
        <Card title="États saisis">
          {etats.length === 0 ? (
            <Empty text="Aucun état. Commencez par l'état au 31 décembre du dernier exercice clos." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="pb-2 font-medium">Au</th>
                    <th className="pb-2 font-medium">Rôle</th>
                    <th className="pb-2 text-right font-medium">Charges</th>
                    <th className="pb-2 text-right font-medium">Fonds de travaux</th>
                    <th className="pb-2 pl-6 font-medium">Contrôle</th>
                    <th className="pb-2" />
                  </tr>
                </thead>
                <tbody>
                  {[...etats].reverse().map((e) => (
                    <tr key={e.id} className="border-b border-slate-50 last:border-0">
                      <td className="py-2.5 font-medium text-slate-800">{fmtDate(e.date)}</td>
                      <td className="py-2.5"><Badge color={ROLE[e.role].color}>{ROLE[e.role].label}</Badge></td>
                      <td className="py-2.5 text-right tabular-nums">{fmtEUR(e.total_charges)}</td>
                      <td className="py-2.5 text-right tabular-nums">{fmtEUR(e.total_fonds_travaux)}</td>
                      <td className="py-2.5 pl-6">
                        {e.controle_ok === null ? (
                          <span className="text-slate-400">—</span>
                        ) : e.controle_ok ? (
                          <Badge color="green">Concordant</Badge>
                        ) : (
                          <Badge color="red">Écart</Badge>
                        )}
                      </td>
                      <td className="py-2.5 text-right">
                        <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => ouvrir(e.id)}>
                          {e.valide ? "Voir" : "Modifier"}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

function EditeurEtat({ lots, anneeDefaut, initial, onAnnuler, onEnregistre, onError }: {
  lots: Lot[];
  anneeDefaut: number;
  initial?: EtatRepriseDetail;
  onAnnuler: () => void;
  onEnregistre: (d: EtatRepriseDetail) => void;
  onError: (e: string) => void;
}) {
  const [annee, setAnnee] = useState(initial ? initial.date.slice(0, 4) : String(anneeDefaut));
  const [commentaire, setCommentaire] = useState(initial?.commentaire ?? "");
  const [lignes, setLignes] = useState<LigneSaisie[]>(initial ? versSaisie(initial) : []);
  const [busy, setBusy] = useState(false);

  function maj(cle: number, champ: keyof LigneSaisie, valeur: string) {
    setLignes((ls) => ls.map((l) => (l.cle === cle
      ? { ...l, [champ]: champ === "lot_id" ? (valeur === "" ? "" : Number(valeur)) : valeur }
      : l)));
  }

  function uneLigneParLot() {
    const presents = new Set(lignes.map((l) => `${l.lot_id}-${l.exercice_origine}`));
    const ajout = lots
      .filter((lot) => !presents.has(`${lot.id}-${annee}`))
      .map((lot) => ({ cle: nouvelleCle(), lot_id: lot.id, exercice_origine: annee,
                       montant_charges: "", montant_fonds_travaux: "" }));
    setLignes((ls) => [...ls, ...ajout]);
  }

  async function enregistrer() {
    if (lignes.some((l) => l.lot_id === "")) {
      onError("Choisissez le lot de chaque ligne.");
      return;
    }
    setBusy(true);
    onError("");
    const corps = {
      date: `${annee}-12-31`,
      commentaire,
      lignes: lignes.map((l) => ({
        lot_id: l.lot_id,
        exercice_origine: Number(l.exercice_origine),
        montant_charges: montantSaisi(l.montant_charges),
        montant_fonds_travaux: montantSaisi(l.montant_fonds_travaux),
      })),
    };
    try {
      onEnregistre(initial
        ? await api.put<EtatRepriseDetail>(`/reprise/etats/${initial.id}`, corps)
        : await api.post<EtatRepriseDetail>("/reprise/etats", corps));
    } catch (e) {
      onError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={initial ? `Modifier l'état au 31/12/${initial.date.slice(0, 4)} (brouillon)` : "Nouvel état (brouillon)"}>
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Input label="État au 31 décembre de l'année" type="number" min={1900} value={annee}
          onChange={(e) => setAnnee(e.target.value)} />
        <div className="sm:col-span-2">
          <Input label="Commentaire (source : relevé de l'ancien syndic, etc.)" value={commentaire}
            onChange={(e) => setCommentaire(e.target.value)} />
        </div>
      </div>
      <p className="mb-2 text-xs text-slate-500">
        Une ligne par lot et par exercice d'origine : le restant dû à cette date (négatif = crédit). L'exercice
        d'origine permet à l'article 19-2 de distinguer les exercices dont les comptes sont approuvés.
      </p>
      {lignes.length === 0 ? (
        <Empty text="Aucune ligne. « Une ligne par lot » prépare une ligne par lot pour l'exercice de l'état." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="py-1">Lot</th>
                <th className="py-1">Exercice d'origine</th>
                <th className="py-1 text-right">Charges dues</th>
                <th className="py-1 text-right">Fonds de travaux dû</th>
                <th className="py-1" />
              </tr>
            </thead>
            <tbody>
              {lignes.map((l) => (
                <tr key={l.cle}>
                  <td className="py-1 pr-2">
                    <select className="w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm"
                      value={l.lot_id} onChange={(e) => maj(l.cle, "lot_id", e.target.value)}>
                      <option value="">—</option>
                      {lots.map((lot) => (
                        <option key={lot.id} value={lot.id}>
                          Lot {lot.numero}{lot.proprietaire_nom ? ` — ${lot.proprietaire_nom}` : ""}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="py-1 pr-2">
                    <input type="number" className="w-24 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm"
                      value={l.exercice_origine} onChange={(e) => maj(l.cle, "exercice_origine", e.target.value)} />
                  </td>
                  <td className="py-1 pr-2">
                    <input inputMode="decimal" placeholder="0,00"
                      className="w-28 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-right text-sm tabular-nums"
                      value={l.montant_charges} onChange={(e) => maj(l.cle, "montant_charges", e.target.value)} />
                  </td>
                  <td className="py-1 pr-2">
                    <input inputMode="decimal" placeholder="0,00"
                      className="w-28 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-right text-sm tabular-nums"
                      value={l.montant_fonds_travaux} onChange={(e) => maj(l.cle, "montant_fonds_travaux", e.target.value)} />
                  </td>
                  <td className="py-1 text-right">
                    <Button variant="ghost" className="px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                      onClick={() => setLignes((ls) => ls.filter((x) => x.cle !== l.cle))}>✕</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="secondary" onClick={uneLigneParLot} disabled={lots.length === 0}>Une ligne par lot</Button>
        <Button variant="secondary" onClick={() => setLignes((ls) => [...ls, { cle: nouvelleCle(), lot_id: "",
          exercice_origine: annee, montant_charges: "", montant_fonds_travaux: "" }])}>+ Ligne</Button>
        <span className="flex-1" />
        <Button variant="ghost" onClick={onAnnuler}>Annuler</Button>
        <Button onClick={enregistrer} disabled={busy}>Enregistrer le brouillon</Button>
      </div>
    </Card>
  );
}

function TableControle({ c }: { c: Controle }) {
  return (
    <div className="rounded-lg border border-slate-200 p-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm font-medium text-slate-700">
          Du {fmtDate(c.depart)} au {fmtDate(c.date)}
        </p>
        {c.ok ? <Badge color="green">Concordant</Badge> : <Badge color="red">Écart {fmtEUR(c.ecart_total)}</Badge>}
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-500">
            <th className="py-1">Lot</th>
            <th className="py-1 text-right">État saisi</th>
            <th className="py-1 text-right">Calculé</th>
            <th className="py-1 text-right">Écart</th>
          </tr>
        </thead>
        <tbody>
          {c.lignes.map((l) => (
            <tr key={l.lot_id} className={l.ecart !== 0 ? "bg-red-50" : ""}>
              <td className="py-1">Lot {l.lot_numero}</td>
              <td className="py-1 text-right tabular-nums">{fmtEUR(l.attendu)}</td>
              <td className="py-1 text-right tabular-nums">{fmtEUR(l.calcule)}</td>
              <td className={`py-1 text-right tabular-nums ${l.ecart !== 0 ? "font-semibold text-red-700" : "text-slate-400"}`}>
                {fmtEUR(l.ecart)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DetailEtat({ etat, lots, onMaj, onFermer, onError }: {
  etat: EtatRepriseDetail;
  lots: Lot[];
  onMaj: (d: EtatRepriseDetail) => void;
  onFermer: () => void;
  onError: (e: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [edition, setEdition] = useState(false);

  async function action(f: () => Promise<void>) {
    setBusy(true);
    onError("");
    try { await f(); } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); } finally { setBusy(false); }
  }

  if (edition) {
    return (
      <EditeurEtat lots={lots} anneeDefaut={Number(etat.date.slice(0, 4))} initial={etat}
        onAnnuler={() => setEdition(false)} onEnregistre={(d) => { setEdition(false); onMaj(d); }} onError={onError} />
    );
  }

  const nomLot = (id: number) => {
    const lot = lots.find((l) => l.id === id);
    return lot ? `Lot ${lot.numero}${lot.proprietaire_nom ? ` — ${lot.proprietaire_nom}` : ""}` : `Lot ${id}`;
  };

  return (
    <Card
      title={<>État au {fmtDate(etat.date)} <Badge color={ROLE[etat.role].color}>{ROLE[etat.role].label}</Badge></>}
      action={<Button variant="ghost" onClick={onFermer}>← Retour</Button>}
    >
      {etat.commentaire && <p className="mb-3 text-sm text-slate-600">{etat.commentaire}</p>}
      {etat.lignes.length === 0 ? (
        <Empty text="Aucune ligne." />
      ) : (
        <table className="mb-4 w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="pb-2 font-medium">Lot</th>
              <th className="pb-2 font-medium">Exercice d'origine</th>
              <th className="pb-2 text-right font-medium">Charges</th>
              <th className="pb-2 text-right font-medium">Fonds de travaux</th>
            </tr>
          </thead>
          <tbody>
            {etat.lignes.map((l) => (
              <tr key={l.id} className="border-b border-slate-50 last:border-0">
                <td className="py-2 text-slate-700">{nomLot(l.lot_id)}</td>
                <td className="py-2 text-slate-700">{l.exercice_origine}</td>
                <td className="py-2 text-right tabular-nums">{fmtEUR(l.montant_charges)}</td>
                <td className="py-2 text-right tabular-nums">{fmtEUR(l.montant_fonds_travaux)}</td>
              </tr>
            ))}
            <tr>
              <td className="py-2 font-semibold text-slate-800" colSpan={2}>Total</td>
              <td className="py-2 text-right font-bold tabular-nums">{fmtEUR(etat.total_charges)}</td>
              <td className="py-2 text-right font-bold tabular-nums">{fmtEUR(etat.total_fonds_travaux)}</td>
            </tr>
          </tbody>
        </table>
      )}

      {etat.controles.length > 0 && (
        <div className="mb-4 space-y-3">
          <p className="text-sm font-semibold text-slate-700">
            {etat.valide ? "Contrôles" : "Contrôles qui conditionnent la validation"}
          </p>
          {etat.controles.map((c) => <TableControle key={`${c.depart}-${c.date}`} c={c} />)}
        </div>
      )}

      {!etat.valide && (
        <>
          <p className="mb-3 text-xs text-slate-500">
            {etat.controles.length === 0
              ? "Validé, cet état deviendra la base : les appels « Reprise de solde » seront créés."
              : etat.role === "brouillon" && etat.controles.some((c) => c.depart === etat.date)
                ? "Validé, cet état deviendra la nouvelle base si tous les contrôles sont concordants."
                : "Validé, cet état deviendra un point de contrôle s'il est concordant."}{" "}
            La validation est définitive.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" disabled={busy} onClick={() => setEdition(true)}>Modifier</Button>
            <Button variant="danger" disabled={busy} onClick={() => action(async () => {
              await api.del(`/reprise/etats/${etat.id}`);
              onFermer();
            })}>Supprimer le brouillon</Button>
            <span className="flex-1" />
            <Button disabled={busy || etat.controles.some((c) => !c.ok)} onClick={() => action(async () => {
              onMaj(await api.post<EtatRepriseDetail>(`/reprise/etats/${etat.id}/valider`));
            })}>Valider l'état</Button>
          </div>
        </>
      )}
    </Card>
  );
}

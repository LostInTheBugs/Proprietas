import { useEffect, useState } from "react";
import { api } from "../api";
import type { Controle, EtatReprise, EtatRepriseDetail, ImportReprise, Lot } from "../types";
import { fmtDate, fmtEUR } from "../types";
import { Badge, Button, Card, Empty, Input, Select } from "../components/ui";

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

/** « Lot 1 — Martin », « Lot 1 (avec lot 12) — Martin », « Lot 12 — annexe du lot 1 ». */
function nomLot(lots: Lot[], id: number | ""): string {
  const lot = lots.find((l) => l.id === id);
  if (!lot) return id === "" ? "—" : `Lot ${id}`;
  const principal = lot.lot_principal_id ? lots.find((l) => l.id === lot.lot_principal_id) : undefined;
  if (principal) return `Lot ${lot.numero} — annexe du lot ${principal.numero}`;
  const annexes = lots.filter((l) => l.lot_principal_id === lot.id).map((l) => l.numero);
  const avec = annexes.length ? ` (avec lot${annexes.length > 1 ? "s" : ""} ${annexes.join(", ")})` : "";
  return `Lot ${lot.numero}${avec}${lot.proprietaire_nom ? ` — ${lot.proprietaire_nom}` : ""}`;
}

/** Lot principal ou lot seul (pas une annexe rattachée à un lot de la liste). */
const estPrincipal = (lots: Lot[], lot: Lot) => !lot.lot_principal_id || !lots.some((l) => l.id === lot.lot_principal_id);

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
          <li>
            <b>Lots non séparables</b> (cave, garage rattachés à un lot principal, voir Lots) : une seule ligne
            pour l'ensemble suffit, sur le lot principal, et les contrôles se font par ensemble. Un copropriétaire
            qui paie tout sur son appartement ne crée donc pas d'écart entre l'appartement et la cave.
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

      {!creation && !ouvert && (
        <ImportCsv
          anneeDefaut={base ? Number(base.date.slice(0, 4)) - 1 : new Date().getFullYear() - 1}
          onImporte={(etatId) => { charger(); if (etatId) ouvrir(etatId); }}
          onError={setError}
        />
      )}
    </div>
  );
}

const FORMATS: Record<ImportReprise["type"], { label: string; entete: string; exemple: string; aide: string }> = {
  etat: {
    label: "État au 31 décembre (brouillon)",
    entete: "lot;exercice;charges;fonds_travaux",
    exemple: "1;2024;120,50;15\n3;2023;-30;0",
    aide: "Une ligne par lot et par exercice d'origine : le restant dû (négatif = crédit). Crée un brouillon, à vérifier puis valider.",
  },
  appels: {
    label: "Appels de fonds",
    entete: "date;lot;libelle;charges;fonds_travaux",
    exemple: "01/03/2025;1;Provisions T1;450,00;22,50\n01/03/2025;2;Provisions T1;350,00;17,50",
    aide: "Une ligne par lot ; les lignes de même date et même libellé forment un seul appel.",
  },
  paiements: {
    label: "Paiements (encaissements)",
    entete: "date;lot;montant;libelle",
    exemple: "10/03/2025;1;472,50;Virement\n12/03/2025;2;367,50;",
    aide: "Une ligne par paiement reçu ; le libellé est facultatif.",
  },
};

/** Lit le fichier en UTF-8, ou en Windows-1252 (export Excel) si l'UTF-8 est invalide. */
async function lireFichier(f: File): Promise<string> {
  const octets = await f.arrayBuffer();
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(octets);
  } catch {
    return new TextDecoder("windows-1252").decode(octets);
  }
}

function ImportCsv({ anneeDefaut, onImporte, onError }: {
  anneeDefaut: number;
  onImporte: (etatId: number | null) => void;
  onError: (e: string) => void;
}) {
  const [type, setType] = useState<ImportReprise["type"]>("etat");
  const [annee, setAnnee] = useState(String(anneeDefaut));
  const [fichier, setFichier] = useState<{ nom: string; contenu: string } | null>(null);
  const [verif, setVerif] = useState<ImportReprise | null>(null);
  const [fait, setFait] = useState("");
  const [busy, setBusy] = useState(false);
  const format = FORMATS[type];

  function corps(simuler: boolean) {
    return { type, contenu: fichier?.contenu ?? "", simuler, ...(type === "etat" ? { date: `${annee}-12-31` } : {}) };
  }

  async function envoyer(simuler: boolean) {
    setBusy(true);
    onError("");
    setFait("");
    try {
      const r = await api.post<ImportReprise>("/reprise/import", corps(simuler));
      if (simuler) {
        setVerif(r);
      } else {
        setVerif(null);
        setFichier(null);
        setFait(`Import terminé : ${r.resume.lignes} ligne(s).`);
        onImporte(r.etat_id);
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setBusy(false);
    }
  }

  const r = verif?.resume;
  return (
    <Card title="Importer un fichier CSV">
      <div className="grid gap-3 sm:grid-cols-3">
        <Select label="Contenu du fichier" value={type}
          onChange={(e) => { setType(e.target.value as ImportReprise["type"]); setVerif(null); }}>
          {(Object.keys(FORMATS) as ImportReprise["type"][]).map((t) => (
            <option key={t} value={t}>{FORMATS[t].label}</option>
          ))}
        </Select>
        {type === "etat" && (
          <Input label="État au 31 décembre de l'année" type="number" min={1900} value={annee}
            onChange={(e) => { setAnnee(e.target.value); setVerif(null); }} />
        )}
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-600">Fichier (.csv)</span>
          <input type="file" accept=".csv,text/csv,text/plain" className="block w-full text-sm text-slate-600"
            onChange={async (e) => {
              const f = e.target.files?.[0];
              setVerif(null);
              setFait("");
              setFichier(f ? { nom: f.name, contenu: await lireFichier(f) } : null);
            }} />
        </label>
      </div>
      <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
        <p className="mb-1">{format.aide}</p>
        <p>
          Première ligne : <code className="font-mono">{format.entete}</code>. Séparateur « ; » ou « , », montants
          « 1 234,50 », dates JJ/MM/AAAA, lot = son numéro.
        </p>
        <pre className="mt-1 font-mono text-slate-500">{format.entete + "\n" + format.exemple}</pre>
      </div>

      {verif && r && (
        <div className="mt-3 space-y-2 text-sm">
          {verif.erreurs.length === 0 ? (
            <p className="rounded-lg bg-emerald-50 px-3 py-2 text-emerald-800">
              {r.lignes} ligne(s) valide(s)
              {r.appels !== undefined && `, ${r.appels} appel(s)`}
              {r.paiements !== undefined && `, ${r.paiements} paiement(s)`}
              {` pour ${fmtEUR(r.total)}.`}
              {r.couverts_par_la_base ? ` ${r.couverts_par_la_base} opération(s) datée(s) avant la base : sans effet sur les soldes, elles servent à remonter d'une année.` : ""}
            </p>
          ) : (
            <div className="rounded-lg bg-red-50 px-3 py-2 text-red-800">
              <p className="mb-1 font-medium">
                {verif.erreurs.length} erreur(s) : rien ne sera importé tant qu'elles ne sont pas corrigées.
              </p>
              <ul className="list-disc pl-5">
                {verif.erreurs.slice(0, 50).map((e, i) => (
                  <li key={i}>Ligne {e.ligne} : {e.message}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
      {fait && <p className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{fait}</p>}

      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="secondary" disabled={!fichier || busy} onClick={() => envoyer(true)}>
          Vérifier{fichier ? ` « ${fichier.nom} »` : ""}
        </Button>
        <Button disabled={!verif || verif.erreurs.length > 0 || busy} onClick={() => envoyer(false)}>Importer</Button>
      </div>
    </Card>
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
    // Une ligne par ensemble : le lot principal porte le solde de ses annexes (cave, garage).
    const ajout = lots
      .filter((lot) => estPrincipal(lots, lot) && !presents.has(`${lot.id}-${annee}`))
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
        <Empty text="Aucune ligne. « Une ligne par lot » prépare une ligne par lot (une seule par ensemble de lots non séparables) pour l'exercice de l'état." />
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
                        <option key={lot.id} value={lot.id}>{nomLot(lots, lot.id)}</option>
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
            <th className="py-1">Lot ou ensemble</th>
            <th className="py-1 text-right">État saisi</th>
            <th className="py-1 text-right">Calculé</th>
            <th className="py-1 text-right">Écart</th>
          </tr>
        </thead>
        <tbody>
          {c.lignes.map((l) => (
            <tr key={l.lot_id} className={l.ecart !== 0 ? "bg-red-50" : ""}>
              <td className="py-1">{l.libelle || `Lot ${l.lot_numero}`}</td>
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
                <td className="py-2 text-slate-700">{nomLot(lots, l.lot_id)}</td>
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

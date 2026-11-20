import { useEffect, useState } from "react";
import { api, envoyerFormulaire } from "../api";
import type { Lot } from "../types";
import { fmtDate, fmtEUR } from "../types";
import { Badge, Button, Card, Empty, Input, Modal, Select } from "../components/ui";
import { CATEGORIES } from "../components/TableMouvements";
import { OptionsCles, useCles } from "../components/Cles";
import { PaiementModal } from "./Comptes";

/** Banque : import des relevés (CSV, OFX, QIF) et rapprochement avec les opérations saisies.
 * L'application propose, le syndic valide (services/releves.py). */

type Compte = "syndicat" | "fonds_travaux";

interface Op {
  id: number; date: string; date_banque: string; libelle: string; type: string; categorie: string; montant: number;
  lot_id: number | null; a_payer: boolean;
}
interface Ligne {
  id: number; date: string; libelle: string; montant: number; fichier: string;
  statut: "pointee" | "ecart" | "proposee" | "a_traiter" | "ignoree";
  mouvements: Op[]; ecart: number | null;
  candidats: { jours: number; sure: boolean; mouvements: Op[] }[];
}
interface Etat {
  compte: Compte; libelle_compte: string; du: string | null; au: string | null;
  resume: { lignes: number; pointees: number; proposees: number; a_traiter: number; ecarts: number; ignorees: number;
            surs: number; absentes: number };
  lignes: Ligne[]; absentes: Op[];
}
interface Resume {
  erreurs: string[]; simulation: boolean; operations: number; nouvelles: number; deja_importees: number;
  du: string | null; au: string | null; credits: number; debits: number;
}

const STATUTS: Record<Ligne["statut"], [string, "green" | "red" | "amber" | "slate" | "indigo"]> = {
  pointee: ["Pointée", "green"], ecart: ["Écart", "red"], proposee: ["Proposition", "indigo"],
  a_traiter: ["À traiter", "amber"], ignoree: ["Mise de côté", "slate"],
};

const signe = (o: Op) => (o.type === "encaissement" ? o.montant : -o.montant);
const resumeOps = (ops: Op[]) =>
  ops.length === 1
    ? `${fmtDate(ops[0].date)} « ${ops[0].libelle} »${ops[0].a_payer ? " (facture à payer)" : ""}`
    : `${ops.length} encaissements du ${fmtDate(ops[0].date)} (« ${ops[0].libelle.split(" — lot ")[0]} »)`;

export default function Banque() {
  const [compte, setCompte] = useState<Compte>("syndicat");
  const [etat, setEtat] = useState<Etat | null>(null);
  const [filtre, setFiltre] = useState<"a_voir" | "toutes">("a_voir");
  const [lots, setLots] = useState<Lot[]>([]);
  const [importer, setImporter] = useState(false);
  const [creation, setCreation] = useState<Ligne | null>(null);
  const [paiement, setPaiement] = useState<Ligne | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const charger = () => {
    api.get<Etat>(`/releves?compte=${compte}`).then(setEtat).catch((e) => setError(e instanceof Error ? e.message : "Erreur"));
  };
  useEffect(charger, [compte]);
  useEffect(() => { api.get<Lot[]>("/lots").then(setLots).catch(() => {}); }, []);

  async function action(f: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await f(); charger(); } catch (e) { setError(e instanceof Error ? e.message : "Erreur"); } finally { setBusy(false); }
  }
  const pointer = (l: Ligne, ops: Op[]) => action(() => api.post(`/releves/${l.id}/pointer`, { mouvement_ids: ops.map((o) => o.id) }));

  const lignes = (etat?.lignes ?? []).filter((l) => filtre === "toutes" || ["proposee", "a_traiter", "ecart"].includes(l.statut));
  const r = etat?.resume;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Banque</h1>
          <p className="text-sm text-slate-500">
            Relevés importés depuis votre banque en ligne et rapprochement avec les opérations saisies : l'application
            propose, vous validez.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={compte} onChange={(e) => setCompte(e.target.value as Compte)} className="w-64">
            <option value="syndicat">Compte du syndicat</option>
            <option value="fonds_travaux">Compte du fonds de travaux</option>
          </Select>
          <Button onClick={() => setImporter(true)}>Importer un relevé</Button>
        </div>
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {r && r.lignes > 0 && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Tuile label="Lignes importées" valeur={String(r.lignes)}
            sous={etat?.du && etat?.au ? `du ${fmtDate(etat.du)} au ${fmtDate(etat.au)}` : ""} />
          <Tuile label="Pointées" valeur={String(r.pointees)} sous={r.ignorees ? `${r.ignorees} mise(s) de côté` : ""} />
          <Tuile label="À voir" valeur={String(r.proposees + r.a_traiter + r.ecarts)}
            sous={`${r.proposees} proposition(s), ${r.a_traiter} sans équivalent${r.ecarts ? `, ${r.ecarts} écart(s)` : ""}`} />
          <Tuile label="Saisies absentes du relevé" valeur={String(r.absentes)} sous="dans la période importée" />
        </div>
      )}

      {!etat ? null : etat.lignes.length === 0 ? (
        <Empty text="Aucun relevé importé pour ce compte. Exportez-le depuis votre banque en ligne (CSV, OFX ou QIF), puis « Importer un relevé »." />
      ) : (
        <Card title={`Relevé — ${etat.libelle_compte}`}
          action={
            <div className="flex items-center gap-2">
              {r && r.surs > 0 && (
                <Button className="px-2.5 py-1.5 text-xs" disabled={busy}
                  onClick={() => action(() => api.post(`/releves/pointer-surs?compte=${compte}`))}>
                  Valider les {r.surs} proposition(s) sûre(s)
                </Button>
              )}
              <Select value={filtre} onChange={(e) => setFiltre(e.target.value as "a_voir" | "toutes")} className="w-40">
                <option value="a_voir">À voir</option>
                <option value="toutes">Toutes les lignes</option>
              </Select>
            </div>
          }>
          {lignes.length === 0 ? (
            <p className="text-sm text-slate-500">Tout est pointé.</p>
          ) : (
            <ul className="divide-y divide-slate-100 text-sm">
              {lignes.map((l) => (
                <li key={l.id} className="py-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="w-24 text-slate-500 tabular-nums">{fmtDate(l.date)}</span>
                    <span className="min-w-0 flex-1 font-medium text-slate-800">{l.libelle || "—"}</span>
                    <span className={`tabular-nums font-semibold ${l.montant > 0 ? "text-emerald-700" : "text-slate-800"}`}>
                      {l.montant > 0 ? "+" : ""}{fmtEUR(l.montant)}
                    </span>
                    <Badge color={STATUTS[l.statut][1]}>{STATUTS[l.statut][0]}</Badge>
                  </div>
                  <div className="mt-1.5 space-y-1 pl-0 text-xs text-slate-600 sm:pl-[6.5rem]">
                    {(l.statut === "pointee" || l.statut === "ecart") && (
                      <div className="flex flex-wrap items-center gap-2">
                        <span>Rapprochée de : {resumeOps(l.mouvements)}
                          {l.statut === "ecart" && l.ecart !== null &&
                            <b className="text-red-700"> — écart de {fmtEUR(l.ecart)} (une opération a été modifiée)</b>}
                        </span>
                        <Button variant="ghost" className="text-xs" disabled={busy}
                          onClick={() => action(() => api.post(`/releves/${l.id}/depointer`))}>Dépointer</Button>
                      </div>
                    )}
                    {l.statut === "proposee" && l.candidats.map((c, i) => (
                      <div key={i} className="flex flex-wrap items-center gap-2">
                        <span>
                          {c.sure ? "✓ " : ""}{resumeOps(c.mouvements)}
                          {c.mouvements.length > 1 && ` : ${c.mouvements.map((o) => fmtEUR(signe(o))).join(" + ")}`}
                          {c.jours > 0 && <span className="text-slate-400"> · {c.jours} j d'écart</span>}
                        </span>
                        <Button variant="secondary" className="px-2 py-1 text-xs" disabled={busy} onClick={() => pointer(l, c.mouvements)}>
                          Valider
                        </Button>
                      </div>
                    ))}
                    {(l.statut === "proposee" || l.statut === "a_traiter") && (
                      <div className="flex flex-wrap gap-1">
                        <Button variant="ghost" className="text-xs" onClick={() => setCreation(l)}>
                          {l.montant > 0 ? "Créer l'encaissement" : "Créer la dépense"}
                        </Button>
                        {l.montant > 0 && compte === "syndicat" && (
                          <Button variant="ghost" className="text-xs" onClick={() => setPaiement(l)}>Paiement d'un copropriétaire</Button>
                        )}
                        <Button variant="ghost" className="text-xs" disabled={busy}
                          onClick={() => action(() => api.post(`/releves/${l.id}/ignorer`, { ignoree: true }))}>Mettre de côté</Button>
                        <Button variant="ghost" className="text-xs" disabled={busy}
                          onClick={() => { if (confirm("Supprimer cette ligne du relevé ?")) action(() => api.del(`/releves/${l.id}`)); }}>
                          Supprimer
                        </Button>
                      </div>
                    )}
                    {l.statut === "ignoree" && (
                      <Button variant="ghost" className="text-xs" disabled={busy}
                        onClick={() => action(() => api.post(`/releves/${l.id}/ignorer`, { ignoree: false }))}>Reprendre</Button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {etat && etat.absentes.length > 0 && (
        <Card title="Opérations saisies absentes du relevé">
          <p className="mb-2 text-xs text-slate-500">
            Passées par la banque d'après Proprietas, datées dans la période importée, mais rattachées à aucune ligne :
            une erreur de saisie (date, montant), une opération pas encore passée, ou un relevé incomplet.
          </p>
          <ul className="divide-y divide-slate-100 text-sm">
            {etat.absentes.map((o) => (
              <li key={o.id} className="flex flex-wrap items-center gap-2 py-1.5">
                <span className="w-24 text-slate-500 tabular-nums">{fmtDate(o.date_banque)}</span>
                <span className="flex-1 text-slate-800">{o.libelle}</span>
                <span className="tabular-nums">{fmtEUR(signe(o))}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {importer && <ImportModal compte={compte} onClose={() => setImporter(false)} onDone={charger} />}
      {creation && (
        <CreationModal ligne={creation} compte={compte} lots={lots} onClose={() => setCreation(null)}
          onDone={() => { setCreation(null); charger(); }} />
      )}
      {paiement && (
        <PaiementModal lots={lots} initial={{ date: paiement.date, montant: paiement.montant, libelle: paiement.libelle }}
          onClose={() => setPaiement(null)} onError={setError}
          onSaved={(crees) => { const l = paiement; setPaiement(null); pointer(l, crees as unknown as Op[]); }} />
      )}
    </div>
  );
}

function Tuile({ label, valeur, sous }: { label: string; valeur: string; sous?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1.5 text-2xl font-bold tabular-nums text-slate-800">{valeur}</p>
      {sous && <p className="mt-0.5 text-xs text-slate-500">{sous}</p>}
    </div>
  );
}

function ImportModal({ compte, onClose, onDone }: { compte: Compte; onClose: () => void; onDone: () => void }) {
  const [fichier, setFichier] = useState<File | null>(null);
  const [resume, setResume] = useState<Resume | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function envoyer(simuler: boolean) {
    if (!fichier) return;
    setBusy(true); setError("");
    const form = new FormData();
    form.append("fichier", fichier);
    form.append("compte", compte);
    form.append("simuler", simuler ? "true" : "false");
    try {
      const r = await envoyerFormulaire<Resume>("/releves/import", form);
      if (simuler) setResume(r); else { onDone(); onClose(); }
    } catch (e) { setError(e instanceof Error ? e.message : "Erreur"); }
    finally { setBusy(false); }
  }

  return (
    <Modal open title={`Importer un relevé — ${compte === "syndicat" ? "compte du syndicat" : "compte du fonds de travaux"}`} onClose={onClose}>
      <div className="space-y-3 text-sm">
        <p className="text-xs leading-relaxed text-slate-600">
          Exportez les opérations depuis votre banque en ligne : <b>CSV</b> (tableur), <b>OFX</b> (Money) ou <b>QIF</b>{" "}
          (Quicken). En CSV, il faut une colonne de date, un libellé et un montant (ou deux colonnes débit et crédit) ; les
          lignes d'en-tête de la banque et les soldes sont passés. Les opérations déjà importées ne sont pas ajoutées deux
          fois : vous pouvez importer des relevés qui se chevauchent.
        </p>
        <input type="file" accept=".csv,.txt,.tsv,.ofx,.qfx,.qif" className="block w-full text-sm text-slate-600"
          onChange={(e) => { setFichier(e.target.files?.[0] ?? null); setResume(null); }} />
        {resume && (resume.erreurs.length > 0 ? (
          <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-800">
            <p className="mb-1 font-medium">{resume.erreurs.length} erreur(s) : rien ne sera importé tant qu'elles ne sont pas corrigées.</p>
            <ul className="list-disc pl-4">{resume.erreurs.slice(0, 20).map((e, i) => <li key={i}>{e}</li>)}</ul>
          </div>
        ) : (
          <div className="rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
            {resume.operations} opération(s) {resume.du && resume.au && `du ${fmtDate(resume.du)} au ${fmtDate(resume.au)}`} :{" "}
            {resume.nouvelles} nouvelle(s) (crédits {fmtEUR(resume.credits)}, débits {fmtEUR(resume.debits)})
            {resume.deja_importees > 0 && `, ${resume.deja_importees} déjà importée(s)`}.
          </div>
        ))}
        {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-800">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button variant="secondary" disabled={!fichier || busy} onClick={() => envoyer(true)}>Vérifier</Button>
          <Button disabled={!resume || resume.erreurs.length > 0 || resume.nouvelles === 0 || busy} onClick={() => envoyer(false)}>
            Importer
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function CreationModal({ ligne, compte, lots, onClose, onDone }: {
  ligne: Ligne; compte: Compte; lots: Lot[]; onClose: () => void; onDone: () => void;
}) {
  const [cles] = useCles();
  const depense = ligne.montant < 0;
  const [libelle, setLibelle] = useState(ligne.libelle);
  const [categorie, setCategorie] = useState(compte === "fonds_travaux" ? "fonds_travaux" : depense ? "charges" : "autre");
  const [lotId, setLotId] = useState("");
  const [cleId, setCleId] = useState("");
  const [error, setError] = useState("");
  const categories = CATEGORIES.filter(([v]) => (compte === "fonds_travaux" ? v === "fonds_travaux" : v !== "fonds_travaux"));

  async function save() {
    setError("");
    try {
      await api.post(`/releves/${ligne.id}/creer`, {
        libelle, categorie, lot_id: lotId === "" ? null : Number(lotId),
        cle_id: depense && lotId === "" && cleId !== "" ? Number(cleId) : null,
      });
      onDone();
    } catch (e) { setError(e instanceof Error ? e.message : "Erreur"); }
  }

  return (
    <Modal open title={depense ? "Créer la dépense" : "Créer l'encaissement"} onClose={onClose}>
      <div className="space-y-3 text-sm">
        <p className="text-xs text-slate-600">
          {fmtDate(ligne.date)} · {fmtEUR(Math.abs(ligne.montant))} — dans l'exercice {ligne.date.slice(0, 4)}, rapprochée
          aussitôt de cette ligne du relevé. Pour joindre la facture, modifiez ensuite l'opération dans Comptes.
        </p>
        <Input label="Libellé" value={libelle} onChange={(e) => setLibelle(e.target.value)} />
        <Select label="Catégorie" value={categorie} onChange={(e) => setCategorie(e.target.value)}>
          {categories.map(([v, lib]) => <option key={v} value={v}>{lib}</option>)}
        </Select>
        <Select label="Lot (facultatif)" value={lotId} onChange={(e) => setLotId(e.target.value)}>
          <option value="">Toute la copropriété</option>
          {lots.map((l) => <option key={l.id} value={l.id}>Lot {l.numero}{l.designation ? ` — ${l.designation}` : ""}</option>)}
        </Select>
        {depense && lotId === "" && cles.length > 0 && (
          <Select label="Répartition" value={cleId} onChange={(e) => setCleId(e.target.value)}>
            <OptionsCles cles={cles} />
          </Select>
        )}
        {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-800">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>Créer et rapprocher</Button>
        </div>
      </div>
    </Modal>
  );
}

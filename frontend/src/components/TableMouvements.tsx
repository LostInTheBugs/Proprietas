import { useMemo, useState } from "react";
import { api } from "../api";
import type { Contrat, Document as DocumentFichier, Exercice, Lot, Mouvement } from "../types";
import { fmtDate, fmtEUR } from "../types";
import { Badge, Button, Empty, Input, Modal, Select } from "./ui";

export const CATEGORIES: [string, string][] = [
  ["charges", "Charges"], ["fonds_travaux", "Fonds de travaux"], ["travaux", "Travaux"], ["assurance", "Assurance"],
  ["energie", "Énergie"], ["entretien", "Entretien"], ["autre", "Autre"],
];
const libCategorie = (c: string) => CATEGORIES.find(([v]) => v === c)?.[1] ?? c;
const libType = (t: string) => (t === "encaissement" ? "Encaissement" : "Dépense");

type Colonne = "date" | "libelle" | "type" | "lot" | "categorie" | "contrat" | "montant";
interface Filtres { libelle: string; type: string; lot: string; categorie: string; contrat: string; min: string; max: string }
const VIDES: Filtres = { libelle: "", type: "", lot: "", categorie: "", contrat: "", min: "", max: "" };

/** Mouvements d'un exercice : filtres, tri sur chaque colonne, sélection et modification groupée. */
export function TableMouvements({ mouvements, exercices, exId, lots, contrats, documents, isSyndic, onEdit, onDelete,
  onChanged, onError }: {
  mouvements: Mouvement[]; exercices: Exercice[]; exId: number | null; lots: Lot[]; contrats: Contrat[];
  documents: DocumentFichier[]; isSyndic: boolean; onEdit: (m: Mouvement) => void; onDelete: (m: Mouvement) => void;
  onChanged: () => void; onError: (e: string) => void;
}) {
  const [f, setF] = useState<Filtres>(VIDES);
  const [tri, setTri] = useState<{ col: Colonne; asc: boolean }>({ col: "date", asc: false });
  const [selection, setSelection] = useState<Set<number>>(new Set());
  const [groupe, setGroupe] = useState(false);
  const annee = exercices.find((e) => e.id === exId)?.annee;
  const lotNum = (id: number | null) => lots.find((l) => l.id === id)?.numero ?? "";
  const contratLib = (id?: number | null) => (id ? contrats.find((c) => c.id === id)?.libelle ?? `#${id}` : "");
  const set = (k: keyof Filtres, v: string) => setF((x) => ({ ...x, [k]: v }));

  const affiches = useMemo(() => {
    const txt = f.libelle.trim().toLowerCase();
    const min = f.min === "" ? null : Number(f.min.replace(",", "."));
    const max = f.max === "" ? null : Number(f.max.replace(",", "."));
    const liste = mouvements.filter((m) =>
      (!txt || m.libelle.toLowerCase().includes(txt))
      && (!f.type || m.type === f.type)
      && (!f.lot || (f.lot === "aucun" ? m.lot_id == null : String(m.lot_id) === f.lot))
      && (!f.categorie || m.categorie === f.categorie)
      && (!f.contrat || (f.contrat === "aucun" ? !m.contrat_id : String(m.contrat_id) === f.contrat))
      && (min === null || isNaN(min) || m.montant >= min)
      && (max === null || isNaN(max) || m.montant <= max));
    const cle = (m: Mouvement): string | number => {
      switch (tri.col) {
        case "date": return m.date + String(m.id).padStart(10, "0");
        case "libelle": return m.libelle.toLowerCase();
        case "type": return m.type;
        case "lot": return lotNum(m.lot_id).padStart(10, "0");
        case "categorie": return libCategorie(m.categorie);
        case "contrat": return contratLib(m.contrat_id).toLowerCase();
        case "montant": return m.type === "encaissement" ? m.montant : -m.montant;
      }
    };
    return [...liste].sort((a, b) => {
      const x = cle(a), y = cle(b);
      const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "fr");
      return tri.asc ? c : -c;
    });
  }, [mouvements, f, tri, lots, contrats]); // eslint-disable-line react-hooks/exhaustive-deps

  const choisis = affiches.filter((m) => selection.has(m.id));
  const tousCoches = affiches.length > 0 && choisis.length === affiches.length;
  const filtre = Object.values(f).some((v) => v !== "");
  const entrees = affiches.filter((m) => m.type === "encaissement").reduce((s, m) => s + m.montant, 0);
  const sorties = affiches.filter((m) => m.type !== "encaissement").reduce((s, m) => s + m.montant, 0);

  function basculer(id: number) {
    setSelection((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  }

  function entete(col: Colonne, children: React.ReactNode, droite = false) {
    const actif = tri.col === col;
    return (
      <th key={col} className={`pb-2 font-medium ${droite ? "text-right" : ""}`}
        aria-sort={actif ? (tri.asc ? "ascending" : "descending") : "none"}>
        <button type="button" className={`inline-flex items-center gap-1 uppercase hover:text-slate-800 ${actif ? "text-slate-800" : ""}`}
          onClick={() => setTri({ col, asc: actif ? !tri.asc : col !== "date" && col !== "montant" })}>
          {children}<span className="text-[10px]">{actif ? (tri.asc ? "▲" : "▼") : "↕"}</span>
        </button>
      </th>
    );
  }

  if (mouvements.length === 0) {
    return <Empty text="Aucun mouvement. Enregistrez les virements reçus des copropriétaires et les factures payées." />;
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
        <div className="col-span-2">
          <Input label="Libellé" value={f.libelle} onChange={(e) => set("libelle", e.target.value)} placeholder="Rechercher…" />
        </div>
        <Select label="Type" value={f.type} onChange={(e) => set("type", e.target.value)}>
          <option value="">Tous</option>
          <option value="depense">Dépense</option>
          <option value="encaissement">Encaissement</option>
        </Select>
        <Select label="Lot" value={f.lot} onChange={(e) => set("lot", e.target.value)}>
          <option value="">Tous</option>
          <option value="aucun">Sans lot</option>
          {lots.map((l) => <option key={l.id} value={l.id}>Lot {l.numero}</option>)}
        </Select>
        <Select label="Catégorie" value={f.categorie} onChange={(e) => set("categorie", e.target.value)}>
          <option value="">Toutes</option>
          {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </Select>
        <Select label="Contrat" value={f.contrat} onChange={(e) => set("contrat", e.target.value)}>
          <option value="">Tous</option>
          <option value="aucun">Sans contrat</option>
          {contrats.map((c) => <option key={c.id} value={c.id}>{c.libelle}</option>)}
        </Select>
        <Input label="Montant min" inputMode="decimal" value={f.min} onChange={(e) => set("min", e.target.value)} />
        <Input label="Montant max" inputMode="decimal" value={f.max} onChange={(e) => set("max", e.target.value)} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <span>
          {affiches.length} mouvement(s){filtre && ` sur ${mouvements.length}`} · entrées {fmtEUR(entrees)} · sorties {fmtEUR(sorties)}
          {filtre && <button type="button" className="ml-2 text-indigo-600 hover:underline" onClick={() => setF(VIDES)}>Effacer les filtres</button>}
        </span>
        {isSyndic && choisis.length > 0 && (
          <span className="flex items-center gap-2 rounded-lg bg-indigo-50 px-2 py-1 text-indigo-800">
            {choisis.length} sélectionné(s)
            <Button className="px-2 py-1 text-xs" onClick={() => setGroupe(true)}>Modifier la sélection…</Button>
            <button type="button" className="hover:underline" onClick={() => setSelection(new Set())}>Désélectionner</button>
          </span>
        )}
      </div>
      {affiches.length === 0 ? (
        <Empty text="Aucun mouvement ne correspond aux filtres." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-left text-xs tracking-wide text-slate-500">
                {isSyndic && (
                  <th className="w-6 pb-2">
                    <input type="checkbox" aria-label="Tout sélectionner" checked={tousCoches}
                      onChange={() => setSelection(tousCoches ? new Set() : new Set(affiches.map((m) => m.id)))} />
                  </th>
                )}
                {entete("date", "Date")}
                {entete("libelle", "Libellé")}
                {entete("type", "Type")}
                {entete("lot", "Lot")}
                {entete("categorie", "Catégorie")}
                {entete("contrat", "Contrat")}
                {entete("montant", "Montant", true)}
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody>
              {affiches.map((m) => (
                <tr key={m.id} className={`border-b border-slate-50 last:border-0 ${selection.has(m.id) ? "bg-indigo-50/50" : ""}`}>
                  {isSyndic && (
                    <td className="py-2">
                      <input type="checkbox" aria-label={`Sélectionner ${m.libelle}`} checked={selection.has(m.id)}
                        onChange={() => basculer(m.id)} />
                    </td>
                  )}
                  <td className="py-2 whitespace-nowrap text-slate-600">
                    {fmtDate(m.date)}{" "}
                    {annee !== undefined && Number(m.date.slice(0, 4)) !== annee && <Badge color="amber">autre année</Badge>}
                  </td>
                  <td className="py-2 text-slate-700">
                    {m.libelle}
                    {m.document_id && (
                      <a href={`/api/documents/${m.document_id}/download`} className="block text-xs text-indigo-600 hover:underline">
                        📎 {documents.find((d) => d.id === m.document_id)?.libelle ?? "facture"}
                      </a>
                    )}
                  </td>
                  <td className="py-2 text-slate-600">{libType(m.type)}</td>
                  <td className="py-2 text-slate-600">{m.lot_id ? `Lot ${lotNum(m.lot_id)}` : "—"}</td>
                  <td className="py-2"><Badge>{libCategorie(m.categorie)}</Badge></td>
                  <td className="py-2 text-slate-600">{contratLib(m.contrat_id) || "—"}</td>
                  <td className={`py-2 text-right font-semibold tabular-nums whitespace-nowrap ${m.type === "encaissement" ? "text-emerald-600" : "text-slate-700"}`}>
                    {m.type === "encaissement" ? "+" : "−"}{fmtEUR(m.montant)}
                  </td>
                  <td className="py-2.5 text-right">
                    {isSyndic && (
                      <span className="whitespace-nowrap">
                        <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => onEdit(m)}>Modifier</Button>
                        <Button variant="ghost" className="px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                          onClick={() => onDelete(m)}>Suppr.</Button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {groupe && (
        <ModificationGroupee ids={choisis.map((m) => m.id)} exercices={exercices} contrats={contrats}
          onClose={() => setGroupe(false)}
          onSaved={() => { setGroupe(false); setSelection(new Set()); onChanged(); }}
          onError={(e) => { setGroupe(false); onError(e); }} />
      )}
    </div>
  );
}

function ModificationGroupee({ ids, exercices, contrats, onClose, onSaved, onError }: {
  ids: number[]; exercices: Exercice[]; contrats: Contrat[];
  onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  // Chaque champ n'est envoyé (donc modifié) que si sa case est cochée.
  const [actifs, setActifs] = useState({ exercice: false, type: false, categorie: false, contrat: false });
  const [exerciceId, setExerciceId] = useState(String(exercices[0]?.id ?? ""));
  const [type, setType] = useState("depense");
  const [categorie, setCategorie] = useState("charges");
  const [contratId, setContratId] = useState("");
  const [busy, setBusy] = useState(false);
  const basculer = (k: keyof typeof actifs) => setActifs((a) => ({ ...a, [k]: !a[k] }));

  async function enregistrer() {
    const corps: Record<string, unknown> = { ids };
    if (actifs.exercice) corps.exercice_id = Number(exerciceId);
    if (actifs.type) corps.type = type;
    if (actifs.categorie) corps.categorie = categorie;
    if (actifs.contrat) corps.contrat_id = contratId === "" ? null : Number(contratId);
    setBusy(true);
    try {
      await api.post("/mouvements/groupe", corps);
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); } finally { setBusy(false); }
  }

  const champ = (k: keyof typeof actifs, label: string, children: React.ReactNode) => (
    <div className="grid grid-cols-[9rem_1fr] items-center gap-3">
      <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
        <input type="checkbox" checked={actifs[k]} onChange={() => basculer(k)} /> {label}
      </label>
      <div className={actifs[k] ? "" : "pointer-events-none opacity-40"}>{children}</div>
    </div>
  );

  return (
    <Modal open title={`Modifier ${ids.length} mouvement(s)`} onClose={onClose}>
      <div className="space-y-3">
        <p className="text-sm text-slate-500">Cochez les champs à changer : les autres restent tels quels.</p>
        {champ("exercice", "Exercice", (
          <Select value={exerciceId} onChange={(e) => setExerciceId(e.target.value)}>
            {exercices.map((ex) => <option key={ex.id} value={ex.id}>{ex.annee}</option>)}
          </Select>
        ))}
        {champ("type", "Type", (
          <Select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="depense">Dépense</option>
            <option value="encaissement">Encaissement</option>
          </Select>
        ))}
        {champ("categorie", "Catégorie", (
          <Select value={categorie} onChange={(e) => setCategorie(e.target.value)}>
            {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </Select>
        ))}
        {champ("contrat", "Contrat", (
          <Select value={contratId} onChange={(e) => setContratId(e.target.value)}>
            <option value="">Aucun contrat</option>
            {contrats.map((c) => <option key={c.id} value={c.id}>{c.libelle}</option>)}
          </Select>
        ))}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button disabled={busy || !Object.values(actifs).some(Boolean)} onClick={enregistrer}>
            {busy ? "Enregistrement…" : "Appliquer"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

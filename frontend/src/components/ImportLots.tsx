import { useState } from "react";
import { envoyerFormulaire } from "../api";
import { Button, Modal } from "./ui";

interface Resume {
  erreurs: string[]; crees: string[]; modifies: string[]; cles_creees: string[]; cles_modifiees: string[];
  simulation: boolean;
}

/** Page Lots : import depuis un tableur (CSV, Excel, LibreOffice), vérifié avant d'être écrit. */
export function ImportLotsModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [fichier, setFichier] = useState<File | null>(null);
  const [resume, setResume] = useState<Resume | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function envoyer(simuler: boolean) {
    if (!fichier) return;
    setBusy(true); setError("");
    const form = new FormData();
    form.append("fichier", fichier);
    form.append("simuler", simuler ? "true" : "false");
    try {
      const r = await envoyerFormulaire<Resume>("/lots/import", form);
      if (simuler) setResume(r); else { onDone(); onClose(); }
    } catch (e) { setError(e instanceof Error ? e.message : "Erreur"); }
    finally { setBusy(false); }
  }

  return (
    <Modal open title="Importer les lots depuis un tableur" onClose={onClose}>
      <div className="space-y-3 text-sm">
        <p className="text-xs leading-relaxed text-slate-600">
          Fichier CSV, Excel (.xlsx) ou LibreOffice (.ods), première feuille, une ligne d'en-tête. Colonnes :{" "}
          <b>numero</b> et <b>tantiemes</b> (obligatoires), designation, type (appartement, cave, parking…), surface,
          proprietaire (e-mail d'un compte de la copropriété) et, pour chaque clé de répartition, une colonne{" "}
          <b>« clé : Nom de la clé »</b> avec les millièmes du lot. Un lot existant (même numéro) est mis à jour ; les
          lots absents du fichier ne changent pas.{" "}
          <a className="text-indigo-600 hover:underline" href="/api/lots/import/modele.csv">Télécharger un modèle (CSV)</a>
        </p>
        <input type="file" accept=".csv,.txt,.xlsx,.ods" className="block w-full text-sm text-slate-600"
          onChange={(e) => { setFichier(e.target.files?.[0] ?? null); setResume(null); }} />
        {resume && (resume.erreurs.length > 0 ? (
          <div className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-800">
            <p className="mb-1 font-medium">{resume.erreurs.length} erreur(s) : rien ne sera importé tant qu'elles ne sont pas corrigées.</p>
            <ul className="list-disc pl-4">{resume.erreurs.map((e, i) => <li key={i}>{e}</li>)}</ul>
          </div>
        ) : (
          <div className="rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
            {resume.crees.length} lot(s) créé(s){resume.crees.length > 0 && ` (${resume.crees.join(", ")})`},{" "}
            {resume.modifies.length} mis à jour{resume.modifies.length > 0 && ` (${resume.modifies.join(", ")})`}
            {resume.cles_creees.length > 0 && <>, clé(s) créée(s) : {resume.cles_creees.join(", ")}</>}
            {resume.cles_modifiees.length > 0 && <>, clé(s) mise(s) à jour : {resume.cles_modifiees.join(", ")}</>}.
          </div>
        ))}
        {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-800">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button variant="secondary" disabled={!fichier || busy} onClick={() => envoyer(true)}>Vérifier</Button>
          <Button disabled={!resume || resume.erreurs.length > 0 || busy} onClick={() => envoyer(false)}>Importer</Button>
        </div>
      </div>
    </Modal>
  );
}

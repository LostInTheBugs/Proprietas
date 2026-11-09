import { useState } from "react";
import { api, getToken } from "../api";
import { Button, Card } from "./ui";

interface ResultatImport {
  copropriete_id: number;
  nom: string;
  comptes_crees: number;
  comptes_existants: number;
  documents: number;
  deuxfa_desactivee: number;
  avertissements: string[];
}

/** Sauvegarde de la copropriété active : export (archive ZIP) et import (nouvelle copropriété). */
export function SauvegardeCard() {
  const [fichier, setFichier] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [erreur, setErreur] = useState("");
  const [resultat, setResultat] = useState<ResultatImport | null>(null);

  async function importer() {
    if (!fichier) return;
    setBusy(true);
    setErreur("");
    setResultat(null);
    try {
      const form = new FormData();
      form.append("fichier", fichier);
      const jeton = getToken();   // session héritée (transition) ; sinon cookie de session
      const res = await fetch("/api/sauvegarde/import", {
        method: "POST", body: form, credentials: "include",
        headers: jeton ? { Authorization: `Bearer ${jeton}` } : {},
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Import impossible");
      setResultat(data as ResultatImport);
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Import impossible");
    } finally {
      setBusy(false);
    }
  }

  async function ouvrir(id: number) {
    await api.post(`/auth/switch-copro/${id}`);
    window.location.href = "/";
  }

  return (
    <Card title="Sauvegarde de la copropriété">
      <div className="space-y-4 text-sm">
        <div>
          <p className="mb-2 text-slate-600">
            Une archive (.zip) avec toutes les données de cette copropriété : lots, comptes, exercices, appels,
            mouvements, AG, recouvrement, historique, contrats, et les fichiers de la page Documents. Gardez-la
            en lieu sûr : elle contient des données personnelles. Le mot de passe SMTP n'y figure pas (à ressaisir).
          </p>
          <a href="/api/sauvegarde/export"
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700">
            ⬇ Télécharger la sauvegarde
          </a>
        </div>
        <div className="border-t border-slate-100 pt-4">
          <p className="mb-2 text-slate-600">
            Restaurer une sauvegarde (changement de serveur, panne) : elle est importée comme une
            <b> nouvelle copropriété</b> de cette instance, sans rien écraser. Les comptes existants (même
            e-mail) sont réutilisés, les autres sont recréés avec leur mot de passe.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <input type="file" accept=".zip,application/zip" className="text-sm text-slate-600"
              onChange={(e) => { setFichier(e.target.files?.[0] ?? null); setResultat(null); setErreur(""); }} />
            <Button variant="secondary" disabled={!fichier || busy} onClick={importer}>
              {busy ? "Import en cours…" : "Importer"}
            </Button>
          </div>
          {erreur && <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-red-700">{erreur}</p>}
          {resultat && (
            <div className="mt-2 space-y-1 rounded-lg bg-emerald-50 px-3 py-2 text-emerald-800">
              <p>
                « {resultat.nom} » importée : {resultat.comptes_crees} compte(s) créé(s),{" "}
                {resultat.comptes_existants} compte(s) existant(s) rattaché(s), {resultat.documents} document(s).
              </p>
              {resultat.deuxfa_desactivee > 0 && (
                <p>{resultat.deuxfa_desactivee} compte(s) devront réactiver leur double authentification.</p>
              )}
              {resultat.avertissements.map((a, i) => <p key={i} className="text-amber-700">{a}</p>)}
              <Button onClick={() => ouvrir(resultat.copropriete_id)}>Ouvrir la copropriété importée</Button>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

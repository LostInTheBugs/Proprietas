import { useEffect, useState } from "react";
import { api, uploadDocument } from "../api";
import { useUser } from "../auth";
import type { Document } from "../types";
import { fmtDate } from "../types";
import { Button, Card, Input, Select, Badge, Empty } from "../components/ui";

const CAT_LABELS: Record<string, string> = {
  contrat: "Contrat",
  assurance: "Assurance",
  facture: "Facture",
  devis: "Devis",
  diagnostic: "Diagnostic",
  pv: "PV d'AG",
  convocation: "Convocation",
  autre: "Autre",
};

export default function Documents() {
  const { user } = useUser();
  const isSyndic = user?.role === "syndic";
  const [docs, setDocs] = useState<Document[]>([]);
  const [categorie, setCategorie] = useState("autre");
  const [libelle, setLibelle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setDocs(await api.get<Document[]>("/documents"));
  }
  useEffect(() => { load().catch(() => {}); }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      await uploadDocument(categorie, libelle || file.name, file);
      setFile(null);
      setLibelle("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload échoué");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Documents</h1>
          <p className="text-sm text-slate-500">
            Contrats, assurances, factures, devis, diagnostics, PV d'AG…
          </p>
        </div>
        <a
          href={`/api/export/registre`}
          className="rounded-lg bg-white px-3 py-2 text-sm font-medium text-indigo-600 shadow-sm ring-1 ring-slate-200 hover:bg-indigo-50"
        >
          Export registre des copropriétés ↓
        </a>
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {isSyndic && (
        <Card title="Ajouter un document">
          <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
            <Select label="Catégorie" value={categorie} onChange={(e) => setCategorie(e.target.value)} className="w-44">
              {Object.entries(CAT_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
            <Input label="Libellé" value={libelle} onChange={(e) => setLibelle(e.target.value)} placeholder={file?.name ?? "Contrat assurance 2026"} className="min-w-56 flex-1" />
            <label className="block flex-1 text-sm">
              <span className="mb-1 block font-medium text-slate-600">Fichier</span>
              <input
                type="file"
                required
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full text-sm text-slate-500 file:mr-3 file:rounded-lg file:border-0 file:bg-indigo-50 file:px-3 file:py-2 file:text-sm file:font-medium file:text-indigo-700 hover:file:bg-indigo-100"
              />
            </label>
            <Button type="submit" disabled={busy || !file}>{busy ? "Envoi…" : "Uploader"}</Button>
          </form>
        </Card>
      )}

      {docs.length === 0 ? (
        <Empty text="Aucun document. Déposez les contrats, devis et factures importants ici." />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {docs.map((d) => (
            <div key={d.id} className="flex items-start justify-between rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="min-w-0">
                <p className="truncate font-medium text-slate-800">{d.libelle}</p>
                <div className="mt-1.5 flex items-center gap-2">
                  <Badge color="indigo">{CAT_LABELS[d.categorie] ?? d.categorie}</Badge>
                  <span className="text-xs text-slate-500">{fmtDate(d.date_ajout)}</span>
                </div>
              </div>
              <div className="flex shrink-0 gap-1">
                <a
                  href={`/api/documents/${d.id}/download`}
                  className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-indigo-600 hover:bg-indigo-50"
                >
                  ↓
                </a>
                {isSyndic && (
                  <button
                    onClick={async () => { await api.del(`/documents/${d.id}`); load(); }}
                    className="rounded-lg px-2.5 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"
                  >
                    ✕
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import { api } from "../api";
import { Card } from "./ui";

interface Espace {
  stockage: "local" | "s3";
  documents: { nombre: number; octets: number | null; introuvables: number };
  instance: null | {
    disque: { total: number; utilise: number; libre: number } | null;
    base_octets: number | null;
    documents_octets: number | null;
  };
  erreur: string;
}

/** 1536 → « 1,5 Ko » (unités binaires, notation française). */
export function taille(octets: number | null | undefined): string {
  if (octets === null || octets === undefined) return "—";
  const unites = ["octets", "Ko", "Mo", "Go", "To"];
  let v = octets;
  let i = 0;
  while (v >= 1024 && i < unites.length - 1) { v /= 1024; i++; }
  const n = i === 0 ? String(v) : v.toLocaleString("fr-FR", { maximumFractionDigits: v < 10 ? 1 : 0 });
  return `${n} ${unites[i]}`;
}

function Ligne({ libelle, valeur }: { libelle: string; valeur: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-slate-100 py-1.5 last:border-0">
      <span className="text-slate-500">{libelle}</span>
      <span className="font-medium text-slate-800">{valeur}</span>
    </div>
  );
}

/** Espace de stockage : documents de la copropriété ; disque et base pour l'administrateur de l'instance. */
export function EspaceStockageCard() {
  const [e, setE] = useState<Espace | null>(null);
  const [erreur, setErreur] = useState("");

  useEffect(() => {
    api.get<Espace>("/stockage").then(setE).catch((x) => setErreur(x instanceof Error ? x.message : "Erreur"));
  }, []);

  const d = e?.instance?.disque;
  const pct = d && d.total > 0 ? Math.round((d.utilise / d.total) * 100) : 0;
  const couleur = pct >= 90 ? "bg-red-500" : pct >= 75 ? "bg-amber-500" : "bg-emerald-500";

  return (
    <Card title="Espace de stockage">
      <div className="space-y-4 text-sm">
        {erreur && <p className="rounded-lg bg-red-50 px-3 py-2 text-red-700">{erreur}</p>}
        {!e && !erreur && <p className="text-slate-500">Calcul en cours…</p>}
        {e && (
          <>
            <div>
              <p className="mb-1 font-medium text-slate-700">Documents de la copropriété</p>
              <Ligne libelle="Nombre" valeur={e.documents.nombre} />
              <Ligne libelle="Place utilisée" valeur={taille(e.documents.octets)} />
              {e.documents.introuvables > 0 && (
                <Ligne libelle="Fichiers introuvables" valeur={<span className="text-amber-700">{e.documents.introuvables}</span>} />
              )}
              <Ligne libelle="Emplacement" valeur={e.stockage === "s3" ? "Stockage S3 (pas de limite fixe)" : "Disque du serveur"} />
            </div>
            {e.instance && (
              <div className="border-t border-slate-100 pt-4">
                <p className="mb-1 font-medium text-slate-700">Serveur (administrateur de l'instance)</p>
                {d ? (
                  <div className="mb-2">
                    <div className="mb-1 flex justify-between text-slate-500">
                      <span>Disque : {taille(d.utilise)} utilisés sur {taille(d.total)}</span>
                      <span className={pct >= 90 ? "font-medium text-red-700" : ""}>{taille(d.libre)} libres</span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-slate-100" role="progressbar"
                      aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Disque utilisé">
                      <div className={`h-full ${couleur}`} style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                ) : (
                  <Ligne libelle="Disque" valeur="non disponible" />
                )}
                <Ligne libelle="Base de données" valeur={taille(e.instance.base_octets)} />
                <Ligne libelle={e.stockage === "s3" ? "Documents (toutes copropriétés, S3)" : "Documents (toutes copropriétés)"}
                  valeur={taille(e.instance.documents_octets)} />
              </div>
            )}
            {e.erreur && <p className="rounded-lg bg-amber-50 px-3 py-2 text-amber-800">{e.erreur}</p>}
          </>
        )}
      </div>
    </Card>
  );
}

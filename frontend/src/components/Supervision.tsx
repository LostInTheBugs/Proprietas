import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Card } from "./ui";

/** Réglages → Serveur : état du serveur sur 24 h ou 7 jours (relevés toutes les 5 minutes). */

interface Mesure {
  instant: string; cpu_pct: number | null; memoire_pct: number | null; disque_pct: number | null;
  requetes: number; erreurs_5xx: number; latence_moy_ms: number | null; latence_p95_ms: number | null; source: string;
}
interface Historique { heures: number; intervalle_minutes: number; mesures: Mesure[] }

const L = 300, H = 60;

function Courbe({ titre, valeurs, instants, unite, max, alerte }: {
  titre: string; valeurs: (number | null)[]; instants: number[]; unite: string; max?: number; alerte?: number;
}) {
  const connues = valeurs.filter((v): v is number => v != null);
  const haut = Math.max(max ?? 0, ...connues, 1);
  const t0 = instants[0] ?? 0, t1 = instants[instants.length - 1] ?? 1;
  const x = (t: number) => (t1 > t0 ? ((t - t0) / (t1 - t0)) * L : L);
  const y = (v: number) => H - (v / haut) * H;
  // Segments interrompus quand une valeur manque (pas de relevé, ou mesure inconnue).
  const segments: string[] = [];
  let courant: string[] = [];
  valeurs.forEach((v, i) => {
    if (v == null) { if (courant.length) segments.push(courant.join(" ")); courant = []; return; }
    courant.push(`${x(instants[i]).toFixed(1)},${y(v).toFixed(1)}`);
  });
  if (courant.length) segments.push(courant.join(" "));
  const dernier = connues[connues.length - 1];
  const pic = connues.length ? Math.max(...connues) : null;
  const fmt = (v: number) => `${v.toLocaleString("fr-FR", { maximumFractionDigits: 1 })}${unite}`;
  return (
    <div>
      <div className="flex justify-between text-xs">
        <span className="font-medium text-slate-700">{titre}</span>
        <span className="text-slate-500">
          {dernier != null ? `actuel ${fmt(dernier)}` : "—"}{pic != null ? ` · max ${fmt(pic)}` : ""}
        </span>
      </div>
      <svg viewBox={`0 0 ${L} ${H}`} className="mt-1 h-16 w-full rounded bg-slate-50" preserveAspectRatio="none" role="img"
        aria-label={titre}>
        {alerte != null && alerte <= haut && (
          <line x1="0" x2={L} y1={y(alerte)} y2={y(alerte)} stroke="#f59e0b" strokeDasharray="4 3" strokeWidth="1" />
        )}
        {segments.map((pts, i) => (
          <polyline key={i} points={pts} fill="none" stroke="#4f46e5" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        ))}
      </svg>
    </div>
  );
}

export function SupervisionCard() {
  const [heures, setHeures] = useState(24);
  const [h, setH] = useState<Historique | null>(null);
  const [erreur, setErreur] = useState("");
  const charger = useCallback(() => {
    api.get<Historique>(`/instance/supervision?heures=${heures}`).then((x) => { setH(x); setErreur(""); })
      .catch((e) => setErreur(e instanceof Error ? e.message : "Erreur"));
  }, [heures]);
  useEffect(() => {
    charger();
    const t = window.setInterval(charger, 5 * 60 * 1000);
    return () => window.clearInterval(t);
  }, [charger]);

  const m = h?.mesures ?? [];
  const instants = m.map((x) => new Date(x.instant).getTime());
  const total = m.reduce((s, x) => s + x.requetes, 0);
  const erreurs = m.reduce((s, x) => s + x.erreurs_5xx, 0);

  return (
    <Card title="État du serveur" action={
      <div className="flex gap-1 text-xs">
        {[24, 168].map((v) => (
          <button key={v} type="button" onClick={() => setHeures(v)}
            className={`rounded px-2 py-1 ${heures === v ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"}`}>
            {v === 24 ? "24 h" : "7 jours"}
          </button>
        ))}
      </div>}>
      {erreur && <p className="text-sm text-red-700">{erreur}</p>}
      {h && m.length === 0 && (
        <p className="text-sm text-slate-500">Pas encore de relevé : le premier arrive dans les 5 minutes suivant le démarrage.</p>
      )}
      {m.length > 0 && (
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Courbe titre="Processeur" unite=" %" max={100} alerte={90} instants={instants} valeurs={m.map((x) => x.cpu_pct)} />
            <Courbe titre="Mémoire" unite=" %" max={100} alerte={90} instants={instants} valeurs={m.map((x) => x.memoire_pct)} />
            <Courbe titre="Disque" unite=" %" max={100} alerte={90} instants={instants} valeurs={m.map((x) => x.disque_pct)} />
            <Courbe titre="Temps de réponse (95 % des requêtes sous)" unite=" ms" instants={instants}
              valeurs={m.map((x) => x.latence_p95_ms)} />
            <Courbe titre={`Requêtes par ${h!.intervalle_minutes} min`} unite="" instants={instants} valeurs={m.map((x) => x.requetes)} />
            <Courbe titre="Erreurs serveur (5xx)" unite="" instants={instants} valeurs={m.map((x) => x.erreurs_5xx)} />
          </div>
          <p className="text-xs text-slate-500">
            {m.length} relevé(s) toutes les {h!.intervalle_minutes} minutes, de {new Date(instants[0]).toLocaleString("fr-FR")} à{" "}
            {new Date(instants[instants.length - 1]).toLocaleString("fr-FR")} : {total.toLocaleString("fr-FR")} requêtes,{" "}
            {erreurs} erreur(s) serveur.{" "}
            {m[m.length - 1].source === "hote" ? "Ressources de toute la machine." : "Ressources vues par l'application (applicateur absent)."}
            {" "}Ligne orange : seuil d'alerte (90 %). Historique gardé 7 jours.
          </p>
        </div>
      )}
    </Card>
  );
}

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Button, Card } from "./ui";
import { taille } from "./EspaceStockage";

/** Réglages → Serveur : processeur, mémoire, disque de la machine, et par service (application, base, Jitsi…). */

interface Conteneur { service: string; conteneur: string; cpu_pct: number; mem_octets: number | null; mem_limite: number | null }
interface Groupe { groupe: string; cpu_pct: number; mem_octets: number; conteneurs: Conteneur[] }
interface Ressources {
  source: "hote" | "application";
  applicateur: { present: boolean; a_jour: boolean; at: number | null };
  systeme: {
    cpus: number; charge: number[];
    memoire: { total?: number | null; disponible?: number | null; utilisee?: number; swap_total?: number | null; swap_libre?: number | null };
    disque: { total: number; utilise: number; libre: number };
    demarre_depuis_s: number | null;
  };
  services: Groupe[];
  services_anciens: boolean;
  application: { memoire_octets: number; base_octets: number | null };
}

function Jauge({ libelle, pct, detail }: { libelle: string; pct: number | null; detail: string }) {
  const p = pct == null ? 0 : Math.min(100, Math.max(0, pct));
  const couleur = p >= 85 ? "bg-red-500" : p >= 70 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div>
      <div className="flex justify-between text-xs text-slate-600">
        <span className="font-medium text-slate-700">{libelle}</span>
        <span>{pct == null ? "—" : `${Math.round(p)} %`} · {detail}</span>
      </div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full ${couleur}`} style={{ width: `${p}%` }} />
      </div>
    </div>
  );
}

function duree(s: number | null) {
  if (s == null) return "";
  const j = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600);
  return j > 0 ? `${j} j ${h} h` : `${h} h ${Math.floor((s % 3600) / 60)} min`;
}

export function RessourcesCard() {
  const [r, setR] = useState<Ressources | null>(null);
  const [erreur, setErreur] = useState("");
  const charger = useCallback(() => {
    api.get<Ressources>("/instance/ressources").then((x) => { setR(x); setErreur(""); })
      .catch((e) => setErreur(e instanceof Error ? e.message : "Erreur"));
  }, []);
  useEffect(() => {
    charger();
    const t = window.setInterval(charger, 30000);
    return () => window.clearInterval(t);
  }, [charger]);
  if (!r) return erreur ? <Card title="Ressources du serveur"><p className="text-sm text-red-700">{erreur}</p></Card> : null;

  const s = r.systeme;
  const m = s.memoire;
  const charge1 = s.charge[0];
  const ilYa = r.applicateur.at ? Math.max(0, Math.round(Date.now() / 1000 - r.applicateur.at)) : null;

  return (
    <Card title="Ressources du serveur" action={<Button variant="secondary" onClick={charger}>Actualiser</Button>}>
      <div className="space-y-4 text-sm">
        <p className="text-xs text-slate-500">
          {r.source === "hote"
            ? `Toute la machine, relevée par l'applicateur de mises à jour il y a ${ilYa} s.`
            : r.applicateur.present
              ? "L'applicateur de mises à jour ne répond plus (relevé de plus de 3 minutes) : chiffres vus par l'application."
              : "Chiffres vus par l'application. Le détail par service (application, base, Jitsi…) demande l'applicateur de mises à jour (deploy/apply-update.py)."}
          {s.demarre_depuis_s != null && ` Serveur démarré depuis ${duree(s.demarre_depuis_s)}.`}
        </p>
        <div className="space-y-3">
          <Jauge libelle="Processeur" pct={charge1 != null ? (charge1 / s.cpus) * 100 : null}
            detail={`charge ${s.charge.map((c) => c.toFixed(2)).join(" / ") || "—"} sur ${s.cpus} cœur(s)`} />
          <Jauge libelle="Mémoire" pct={m.total && m.utilisee != null ? (m.utilisee / m.total) * 100 : null}
            detail={m.total ? `${taille(m.utilisee)} sur ${taille(m.total)}, ${taille(m.disponible)} disponibles` : "inconnue"} />
          {!!m.swap_total && (
            <Jauge libelle="Mémoire d'échange (swap)" pct={((m.swap_total - (m.swap_libre ?? 0)) / m.swap_total) * 100}
              detail={`${taille(m.swap_total - (m.swap_libre ?? 0))} sur ${taille(m.swap_total)}`} />
          )}
          <Jauge libelle="Disque" pct={s.disque.total ? (s.disque.utilise / s.disque.total) * 100 : null}
            detail={`${taille(s.disque.utilise)} sur ${taille(s.disque.total)}, ${taille(s.disque.libre)} libres`} />
        </div>

        {r.services.length > 0 && (
          <div>
            <p className="mb-1 font-medium text-slate-700">Par service</p>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-slate-500"><th className="py-1">Service</th><th className="py-1">Processeur</th><th className="py-1">Mémoire</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {r.services.map((g) => (
                  <tr key={g.groupe} className="align-top">
                    <td className="py-1.5">
                      <span className="font-medium text-slate-800">{g.groupe}</span>
                      {g.conteneurs.length > 1 && (
                        <span className="block text-slate-500">{g.conteneurs.map((c) => `${c.service} (${taille(c.mem_octets)})`).join(", ")}</span>
                      )}
                    </td>
                    <td className="py-1.5 tabular-nums">{g.cpu_pct.toLocaleString("fr-FR")} %</td>
                    <td className="py-1.5 tabular-nums">{taille(g.mem_octets)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-1 text-xs text-slate-500">Processeur : 100 % = un cœur entier.</p>
          </div>
        )}
        {r.services_anciens && <p className="text-xs text-amber-700">Détail par service indisponible : relevé trop ancien.</p>}

        <div className="grid grid-cols-2 gap-2 text-xs text-slate-600">
          <span>Mémoire du processus de l'application : <b>{taille(r.application.memoire_octets)}</b></span>
          <span>Base de données : <b>{taille(r.application.base_octets)}</b></span>
        </div>
      </div>
    </Card>
  );
}

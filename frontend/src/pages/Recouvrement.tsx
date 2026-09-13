import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useUser } from "../auth";
import type {
  DecompteLigne,
  Mise19_2,
  RecouvrementActe,
  RecouvrementDossier,
  RecouvrementLot,
  Relance,
  RelanceLot,
} from "../types";
import { fmtDate, fmtDateTime, fmtEUR } from "../types";
import { Badge, Button, Card, Empty, Input, Modal, Select } from "../components/ui";

const COULEUR_STATUT: Record<string, "green" | "red" | "amber" | "slate" | "indigo"> = {
  a_jour: "green",
  en_retard: "red",
  mise_en_demeure: "amber",
  delai_19_2_depasse: "amber",
  apres_19_2: "indigo",
  amiable: "indigo",
  contentieux: "indigo",
};

const AIDE_STATUT: Record<string, string> = {
  en_retard:
    "Impayé constaté. Envoyez une relance (email) ; si elle reste sans effet, passez à la mise en demeure — c'est l'acte qui déclenche la suite (intérêts au taux légal, délai de 30 jours de l'article 19-2).",
  mise_en_demeure:
    "Mise en demeure envoyée : le délai de 30 jours court. Des intérêts de retard courent au taux légal à compter de sa date. Passé 30 jours, les provisions futures pourront être rendues exigibles (article 19-2).",
  delai_19_2_depasse:
    "Mise en demeure restée infructueuse pendant 30 jours : les provisions non encore échues de l'exercice en cours et les restes des exercices précédents peuvent être rendus immédiatement exigibles (article 19-2 de la loi du 10 juillet 1965).",
  apres_19_2:
    "Article 19-2 activé : les provisions futures sont exigibles immédiatement. Étapes suivantes : tentative de règlement amiable, puis saisine de la juridiction compétente si nécessaire.",
  amiable:
    "Procédure amiable en cours. Rappel : pour une créance ≤ 5 000 €, la tentative de règlement amiable (conciliateur — gratuit) est obligatoire avant de saisir le juge ; la procédure simplifiée par commissaire de justice est aussi possible.",
  contentieux:
    "Procédure judiciaire en cours. Le syndic n'a pas besoin d'autorisation de l'assemblée pour les actions en recouvrement ; l'hypothèque légale et l'opposition sur le prix de vente sont possibles sans autorisation préalable.",
};

const MODES_ENVOI = [
  { value: "lre", label: "Lettre recommandée électronique (LRE)" },
  { value: "lrar", label: "LRAR papier (si demandée par le copropriétaire)" },
  { value: "email", label: "Email (courtoisie)" },
  { value: "remise", label: "Remise en main propre" },
];

const LIBELLE_MODE: Record<string, string> = Object.fromEntries(MODES_ENVOI.map((m) => [m.value, m.label]));

const TYPES_PROCEDURE = [
  { value: "conciliation", label: "Conciliation / médiation (amiable)" },
  { value: "commissaire_justice", label: "Commissaire de justice" },
  { value: "tribunal", label: "Saisine du tribunal" },
  { value: "note", label: "Note" },
];

const EN_PROCEDURE = ["mise_en_demeure", "delai_19_2_depasse", "apres_19_2", "amiable", "contentieux"];

function Chiffre({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 px-3 py-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="font-semibold tabular-nums text-slate-800">{value}</p>
      {sub && <p className="text-xs text-slate-400">{sub}</p>}
    </div>
  );
}

export default function Recouvrement() {
  const { user } = useUser();
  const isSyndic = user?.role === "syndic";

  const [lots, setLots] = useState<RecouvrementLot[]>([]);
  const [membreEtat, setMembreEtat] = useState<RelanceLot[]>([]);
  const [historique, setHistorique] = useState<Relance[]>([]);
  const [selection, setSelection] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [resultat, setResultat] = useState<{ envoyes: number; sans_email: number; erreurs: string[] } | null>(null);
  const [error, setError] = useState("");
  const [dossierId, setDossierId] = useState<number | null>(null);
  const [taux, setTaux] = useState("");
  const [tauxBusy, setTauxBusy] = useState(false);

  const load = useCallback(async () => {
    if (isSyndic) {
      const [l, h, c] = await Promise.all([
        api.get<RecouvrementLot[]>("/recouvrement"),
        api.get<Relance[]>("/relances/historique"),
        api.get<{ taux_legal_retard?: number }>("/copro").catch(() => ({ taux_legal_retard: 0 })),
      ]);
      setLots(l);
      setHistorique(h);
      setTaux(String(c.taux_legal_retard ?? ""));
      setSelection(new Set(l.filter((x) => x.solde > 0.005).map((x) => x.lot_id)));
    } else {
      const [e, h] = await Promise.all([
        api.get<RelanceLot[]>("/relances"),
        api.get<Relance[]>("/relances/historique"),
      ]);
      setMembreEtat(e);
      setHistorique(h);
    }
  }, [isSyndic]);
  useEffect(() => { load().catch(() => {}); }, [load]);

  const enRetard = lots.filter((l) => l.solde > 0.005);
  const totalDu = enRetard.reduce((s, l) => s + l.solde, 0);
  const nbProcedure = lots.filter((l) => EN_PROCEDURE.includes(l.statut)).length;

  function toggle(lotId: number) {
    setSelection((prev) => {
      const next = new Set(prev);
      if (next.has(lotId)) next.delete(lotId);
      else next.add(lotId);
      return next;
    });
  }

  async function envoyer(lotIds?: number[]) {
    const ids = lotIds ?? [...selection];
    setBusy(true);
    setResultat(null);
    setError("");
    try {
      const res = await api.post<{ envoyes: number; sans_email: number; erreurs: string[] }>("/relances/envoyer", {
        lot_ids: ids,
      });
      setResultat(res);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setBusy(false);
    }
  }

  async function sauverTaux() {
    setTauxBusy(true);
    setError("");
    try {
      await api.put("/copro", { taux_legal_retard: parseFloat(taux.replace(",", ".")) || 0 });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur");
    } finally {
      setTauxBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-slate-800">Recouvrement des impayés</h1>
        <p className="text-sm text-slate-500">
          {isSyndic
            ? `${enRetard.length} lot(s) en retard · ${fmtEUR(totalDu)} dû · ${nbProcedure} dossier(s) en procédure`
            : `${membreEtat.filter((e) => e.solde > 0.005).length} lot(s) en retard`}
        </p>
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {resultat && (
        <p className="rounded-lg bg-indigo-50 px-3 py-2 text-sm text-indigo-800">
          {resultat.envoyes} relance(s) envoyée(s)
          {resultat.sans_email > 0 && ` · ${resultat.sans_email} propriétaire(s) sans adresse email`}
          {resultat.erreurs.length > 0 && <span className="block text-red-700">Échecs : {resultat.erreurs.join(" · ")}</span>}
        </p>
      )}

      {isSyndic && (
        <Card title="Taux de l'intérêt légal">
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-36">
              <Input label="Taux (%)" value={taux} onChange={(e) => setTaux(e.target.value)} placeholder="ex. 2,75" />
            </div>
            <Button variant="secondary" disabled={tauxBusy} onClick={sauverTaux}>
              {tauxBusy ? "…" : "Enregistrer"}
            </Button>
            <p className="max-w-xl text-xs leading-relaxed text-slate-500">
              Arrêté semestriel (au 2ᵉ semestre 2026 : 2,75 % pour un syndicat — « autres cas » ; 6,84 % pour un
              créancier particulier). Les intérêts de retard courent à compter de la mise en demeure ; ils sont
              affichés à titre indicatif.
            </p>
          </div>
        </Card>
      )}

      <Card
        title="Situation par lot"
        action={
          isSyndic ? (
            <Button disabled={busy || selection.size === 0} onClick={() => envoyer()}>
              {busy ? "Envoi…" : `Envoyer ${selection.size} relance(s)`}
            </Button>
          ) : undefined
        }
      >
        {isSyndic ? (
          lots.length === 0 ? (
            <Empty text="Aucun lot. Ajoutez d'abord les lots dans Lots & occupants." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="py-2 pr-2" />
                    <th className="px-3 py-2 font-medium">Lot</th>
                    <th className="px-3 py-2 font-medium">Propriétaire</th>
                    <th className="px-3 py-2 text-right font-medium">Solde</th>
                    <th className="px-3 py-2 font-medium">Retard depuis</th>
                    <th className="px-3 py-2 font-medium">Statut</th>
                    <th className="px-3 py-2 text-right font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {lots.map((l) => {
                    const retardLot = l.solde > 0.005;
                    return (
                      <tr key={l.lot_id} className="border-b border-slate-50 last:border-0">
                        <td className="py-2 pr-2">
                          <input
                            type="checkbox"
                            checked={selection.has(l.lot_id)}
                            disabled={!retardLot}
                            onChange={() => toggle(l.lot_id)}
                            className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                          />
                        </td>
                        <td className="px-3 py-2 font-medium text-slate-700">Lot {l.lot_numero}</td>
                        <td className="px-3 py-2 text-slate-600">
                          {l.personne_nom}
                          {l.personne_email && <span className="block text-xs text-slate-400">{l.personne_email}</span>}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {retardLot ? <span className="font-semibold text-red-600">{fmtEUR(l.solde)}</span> : <span className="text-slate-500">0,00 €</span>}
                        </td>
                        <td className="px-3 py-2 text-slate-600">{l.retard_depuis ? fmtDate(l.retard_depuis) : "—"}</td>
                        <td className="px-3 py-2">
                          <Badge color={COULEUR_STATUT[l.statut] ?? "slate"}>
                            {l.statut === "mise_en_demeure" && l.jours_restants !== null
                              ? `${l.statut_label} (reste ${l.jours_restants} j)`
                              : l.statut_label}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 text-right whitespace-nowrap">
                          {retardLot && (
                            <button
                              className="rounded-lg px-2 py-1 text-xs font-medium text-slate-500 hover:bg-slate-100 hover:text-indigo-600"
                              onClick={() => envoyer([l.lot_id])}
                              disabled={busy}
                            >
                              Relancer
                            </button>
                          )}
                          <button
                            className="rounded-lg px-2 py-1 text-xs font-medium text-indigo-600 hover:bg-indigo-50"
                            onClick={() => setDossierId(l.lot_id)}
                          >
                            Dossier
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2 font-medium">Lot</th>
                  <th className="px-3 py-2 font-medium">Propriétaire</th>
                  <th className="px-3 py-2 text-right font-medium">Charges appelées</th>
                  <th className="px-3 py-2 text-right font-medium">Fonds travaux</th>
                  <th className="px-3 py-2 text-right font-medium">Encaissé</th>
                  <th className="px-3 py-2 text-right font-medium">Solde</th>
                </tr>
              </thead>
              <tbody>
                {membreEtat.map((e) => (
                  <tr key={e.lot_id} className="border-b border-slate-50 last:border-0">
                    <td className="px-3 py-2 font-medium text-slate-700">Lot {e.lot_numero}</td>
                    <td className="px-3 py-2 text-slate-600">{e.personne_nom}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{fmtEUR(e.appels_charges)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{fmtEUR(e.appels_fonds)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{fmtEUR(e.encaisse)}</td>
                    <td className="px-3 py-2 text-right">
                      {e.solde > 0.005 ? <Badge color="red">{fmtEUR(e.solde)}</Badge> : <Badge color="green">{fmtEUR(e.solde)}</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-xs text-slate-500">
          Les relances sont envoyées par email avec le détail. La mise en demeure se gère dans le dossier du lot
          (bouton « Dossier ») : PDF, enregistrement de l'envoi, suivi des 30 jours et de l'article 19-2.
        </p>
      </Card>

      <Card title="Historique des relances">
        {historique.length === 0 ? (
          <Empty text="Aucune relance envoyée pour le moment." />
        ) : (
          <ul className="space-y-1.5 text-sm">
            {historique.map((h) => (
              <li key={h.id} className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-700">Lot {h.lot_numero}</span>
                <span className="text-slate-500">{h.personne_nom}</span>
                <span className="ml-auto text-xs text-slate-400">{fmtDateTime(h.date_envoi)}</span>
                <span className="font-semibold tabular-nums text-red-600">{fmtEUR(h.montant_du)}</span>
                {h.statut === "envoye" ? <Badge color="green">envoyé</Badge> : <Badge color="red">erreur</Badge>}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {dossierId !== null && (
        <DossierModal
          lotId={dossierId}
          onClose={() => setDossierId(null)}
          onChanged={() => load()}
        />
      )}
    </div>
  );
}

const AUJOURDHUI = () => new Date().toISOString().slice(0, 10);

function DossierModal({ lotId, onClose, onChanged }: { lotId: number; onClose: () => void; onChanged: () => void }) {
  const [d, setD] = useState<RecouvrementDossier | null>(null);
  const [err, setErr] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);
  const [mdOpen, setMdOpen] = useState(false);
  const [mdMode, setMdMode] = useState("lre");
  const [mdDate, setMdDate] = useState(AUJOURDHUI());
  const [mdRef, setMdRef] = useState("");
  const [prev19, setPrev19] = useState<Mise19_2 | null>(null);
  const [fraisLib, setFraisLib] = useState("");
  const [fraisMontant, setFraisMontant] = useState("");
  const [procType, setProcType] = useState("conciliation");
  const [procDate, setProcDate] = useState(AUJOURDHUI());
  const [procLib, setProcLib] = useState("");

  const load = useCallback(async () => {
    setD(await api.get<RecouvrementDossier>(`/recouvrement/lot/${lotId}`));
  }, [lotId]);
  useEffect(() => { load().catch((e) => setErr(e instanceof Error ? e.message : "Erreur")); }, [load]);

  async function action(fn: () => Promise<unknown>, message: string) {
    setBusy(true);
    setErr("");
    setInfo("");
    try {
      await fn();
      setInfo(message);
      await load();
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Erreur");
    } finally {
      setBusy(false);
    }
  }

  const md = d ? [...d.actes].filter((a) => a.type === "mise_en_demeure").pop() : undefined;
  const actesFrais = d ? d.actes.filter((a) => a.type === "frais") : [];
  const timeline = d
    ? [
        ...d.relances.map((r) => ({
          key: `r${r.id}`,
          date: r.date_envoi,
          node: (
            <span>
              📧 Relance {r.statut === "envoye" ? "envoyée" : "en erreur"} — {fmtEUR(r.montant_du)}
              <span className="text-slate-400"> · {fmtDateTime(r.date_envoi)}</span>
            </span>
          ),
        })),
        ...d.actes.map((a) => ({
          key: `a${a.id}`,
          date: a.date_envoi ? `${a.date_envoi}T12:00:00` : a.date_acte,
          node: (
            <span className="flex flex-wrap items-center gap-x-2">
              <span className="font-medium text-slate-700">{a.libelle}</span>
              {a.date_envoi && <span className="text-slate-400">{fmtDate(a.date_envoi)}</span>}
              {a.reference && <span className="text-slate-400">réf. {a.reference}</span>}
              {a.montant > 0 && <span className="tabular-nums text-slate-500">{fmtEUR(a.montant)}</span>}
              {a.auteur && <span className="text-xs text-slate-400">par {a.auteur}</span>}
            </span>
          ),
          del: a.type !== "activation_19_2" ? a.id : null,
        })),
      ].sort((x, y) => (x.date < y.date ? 1 : -1))
    : [];

  return (
    <Modal open wide title={`Dossier de recouvrement — lot ${d?.lot_numero ?? "…"}`} onClose={onClose}>
      {!d ? (
        <p className="text-sm text-slate-500">Chargement…</p>
      ) : (
        <div className="space-y-4 text-sm">
          {err && <p className="rounded-lg bg-red-50 px-3 py-2 text-red-700">{err}</p>}
          {info && <p className="rounded-lg bg-emerald-50 px-3 py-2 text-emerald-700">{info}</p>}

          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-slate-700">{d.personne_nom}</span>
            {d.personne_email && <span className="text-xs text-slate-400">{d.personne_email}</span>}
            <Badge color={COULEUR_STATUT[d.statut] ?? "slate"}>{d.statut_label}</Badge>
          </div>
          {d.solde > 0.005 && !d.personne_adresse && (
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-amber-800">
              Adresse postale du copropriétaire manquante — complétez sa fiche dans « Lots &amp; occupants » (mention
              obligatoire de la mise en demeure).
            </p>
          )}
          {AIDE_STATUT[d.statut] && (
            <p className="rounded-lg bg-slate-50 px-3 py-2 leading-relaxed text-slate-600">{AIDE_STATUT[d.statut]}</p>
          )}

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Chiffre label="Solde impayé" value={fmtEUR(d.solde)} sub={d.retard_depuis ? `depuis le ${fmtDate(d.retard_depuis)}` : undefined} />
            <Chiffre label="dont échu" value={fmtEUR(d.arriere_echu)} />
            <Chiffre label="Frais engagés" value={fmtEUR(d.frais_total)} />
            <Chiffre
              label="Intérêts estimés"
              value={d.taux_legal > 0 ? fmtEUR(d.interets) : "—"}
              sub={d.taux_legal > 0 ? `taux ${String(d.taux_legal).replace(".", ",")} %` : "taux non renseigné"}
            />
          </div>

          <section>
            <p className="mb-1.5 font-medium text-slate-700">Décompte</p>
            <div className="overflow-x-auto rounded-lg border border-slate-100">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-100 text-left uppercase tracking-wide text-slate-400">
                    <th className="px-2 py-1.5 font-medium">Exercice</th>
                    <th className="px-2 py-1.5 font-medium">Libellé</th>
                    <th className="px-2 py-1.5 font-medium">Échéance</th>
                    <th className="px-2 py-1.5 text-right font-medium">Montant</th>
                    <th className="px-2 py-1.5 text-right font-medium">Restant dû</th>
                  </tr>
                </thead>
                <tbody>
                  {d.decompte.map((l: DecompteLigne, i: number) => (
                    <tr key={i} className={`border-b border-slate-50 last:border-0 ${l.restant_du <= 0.005 ? "text-slate-400" : "text-slate-600"}`}>
                      <td className="px-2 py-1.5">{l.exercice ?? "—"}</td>
                      <td className="px-2 py-1.5">
                        {l.libelle} {l.echu && l.restant_du > 0.005 && <span className="text-amber-600">· échu</span>}
                      </td>
                      <td className="px-2 py-1.5">{l.echeance ? fmtDate(l.echeance) : "—"}</td>
                      <td className="px-2 py-1.5 text-right tabular-nums">{fmtEUR(l.montant)}</td>
                      <td className="px-2 py-1.5 text-right tabular-nums font-medium">{fmtEUR(l.restant_du)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="space-y-2 rounded-lg border border-slate-200 p-3">
            <p className="font-medium text-slate-700">Mise en demeure (délai de 30 jours — article 19-2)</p>
            {md && !mdOpen ? (
              <div className="space-y-2">
                <p className="text-slate-600">
                  Envoyée le {md.date_envoi ? fmtDate(md.date_envoi) : "—"}
                  {md.mode_envoi && ` — ${LIBELLE_MODE[md.mode_envoi] ?? md.mode_envoi}`}
                  {md.reference && ` — réf. ${md.reference}`} · montant réclamé :{" "}
                  <strong className="tabular-nums">{fmtEUR(md.montant)}</strong>
                </p>
                {d.statut === "mise_en_demeure" && d.jours_restants !== null && (
                  <p className="text-amber-700">
                    Délai en cours — reste {d.jours_restants} jour(s) avant l'exigibilité des provisions futures (19-2).
                  </p>
                )}
                <div className="flex flex-wrap gap-2">
                  <a
                    className="inline-flex items-center rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
                    href={`/api/recouvrement/lot/${d.lot_id}/mise-en-demeure.pdf`}
                    target="_blank"
                    rel="noopener"
                  >
                    Télécharger le PDF
                  </a>
                  <Button variant="ghost" onClick={() => setMdOpen(true)}>Nouvelle mise en demeure</Button>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                <p className="text-xs leading-relaxed text-slate-500">
                  1. Téléchargez le PDF (provisions échues impayées, décompte détaillé par provision).
                  Envoyez-le par voie électronique recommandée (LRE) — le LRAR papier n'est prévu que si le
                  copropriétaire l'a demandé. 2. Enregistrez l'envoi : le délai de 30 jours démarre.
                </p>
                <div className="grid grid-cols-2 gap-2">
                  <Select label="Mode d'envoi" value={mdMode} onChange={(e) => setMdMode(e.target.value)}>
                    {MODES_ENVOI.map((m) => (
                      <option key={m.value} value={m.value}>{m.label}</option>
                    ))}
                  </Select>
                  <Input label="Date d'envoi" type="date" value={mdDate} onChange={(e) => setMdDate(e.target.value)} />
                </div>
                <Input label="Référence (n° LRE / AR)" value={mdRef} onChange={(e) => setMdRef(e.target.value)} />
                <div className="flex flex-wrap items-center gap-2">
                  <a
                    className="inline-flex items-center rounded-lg border border-indigo-200 px-3 py-1.5 text-xs font-medium text-indigo-600 hover:bg-indigo-50"
                    href={`/api/recouvrement/lot/${d.lot_id}/mise-en-demeure.pdf`}
                    target="_blank"
                    rel="noopener"
                  >
                    Télécharger le PDF
                  </a>
                  <Button
                    disabled={busy}
                    onClick={() =>
                      action(
                        () =>
                          api.post(`/recouvrement/lot/${d.lot_id}/acte`, {
                            type: "mise_en_demeure",
                            date_envoi: mdDate,
                            mode_envoi: mdMode,
                            reference: mdRef,
                          }),
                        "Mise en demeure enregistrée."
                      ).then(() => setMdOpen(false))
                    }
                  >
                    Enregistrer l'envoi
                  </Button>
                  {md && <Button variant="ghost" onClick={() => setMdOpen(false)}>Annuler</Button>}
                </div>
              </div>
            )}
          </section>

          {(d.statut === "delai_19_2_depasse" || d.statut === "apres_19_2" || prev19) && (
            <section className="space-y-2 rounded-lg border border-indigo-200 bg-indigo-50/40 p-3">
              <p className="font-medium text-indigo-800">Article 19-2 — provisions devenues exigibles</p>
              {prev19 ? (
                <>
                  <table className="w-full text-xs">
                    <tbody>
                      {prev19.lignes.map((l, i) => (
                        <tr key={i} className="border-b border-indigo-100/60 last:border-0 text-slate-600">
                          <td className="py-1">{l.exercice ?? "—"}</td>
                          <td className="py-1">{l.libelle}</td>
                          <td className="py-1 text-right tabular-nums font-medium">{fmtEUR(l.restant_du)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="text-slate-700">
                    Total nouvellement exigible : <strong className="tabular-nums">{fmtEUR(prev19.total)}</strong>
                    {prev19.exercice !== null && (
                      <span className="text-slate-500"> (provisions non échues {prev19.exercice} + restes des exercices précédents)</span>
                    )}
                    {" — l'arriéré déjà échu reste dû en parallèle ("}{fmtEUR(prev19.arriere_echu)}{")."}
                  </p>
                  {d.statut !== "apres_19_2" && (
                    <Button
                      disabled={busy}
                      onClick={() => action(() => api.post(`/recouvrement/lot/${d.lot_id}/19-2`), "Article 19-2 activé.")}
                    >
                      Activer l'article 19-2
                    </Button>
                  )}
                  {d.statut === "apres_19_2" && <p className="text-xs text-indigo-700">Article 19-2 déjà activé pour ce dossier.</p>}
                </>
              ) : (
                <Button
                  variant="secondary"
                  disabled={busy}
                  onClick={async () => {
                    setErr("");
                    try {
                      setPrev19(await api.get<Mise19_2>(`/recouvrement/lot/${d.lot_id}/19-2`));
                    } catch (e) {
                      setErr(e instanceof Error ? e.message : "Erreur");
                    }
                  }}
                >
                  Voir les sommes devenues exigibles
                </Button>
              )}
            </section>
          )}

          <section className="space-y-2">
            <p className="font-medium text-slate-700">Frais de recouvrement (à la charge du débiteur)</p>
            {actesFrais.length > 0 && (
              <ul className="space-y-1">
                {actesFrais.map((f: RecouvrementActe) => (
                  <li key={f.id} className="flex items-center gap-2 text-slate-600">
                    <span className="flex-1">{f.libelle}</span>
                    <span className="tabular-nums">{fmtEUR(f.montant)}</span>
                    <button
                      className="rounded px-1 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                      title="Supprimer cet acte"
                      onClick={() => {
                        if (confirm("Supprimer ce frais ? (tracé dans le journal d'audit)")) {
                          action(() => api.del(`/recouvrement/acte/${f.id}`), "Frais supprimé.");
                        }
                      }}
                    >
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex flex-wrap items-end gap-2">
              <div className="w-56"><Input label="Libellé" value={fraisLib} onChange={(e) => setFraisLib(e.target.value)} placeholder="Frais de mise en demeure" /></div>
              <div className="w-32"><Input label="Montant (€)" value={fraisMontant} onChange={(e) => setFraisMontant(e.target.value)} /></div>
              <Button
                variant="secondary"
                disabled={busy || !fraisLib || !parseFloat(fraisMontant.replace(",", "."))}
                onClick={() =>
                  action(
                    () => api.post(`/recouvrement/lot/${d.lot_id}/acte`, { type: "frais", libelle: fraisLib, montant: parseFloat(fraisMontant.replace(",", ".")) }),
                    "Frais ajouté."
                  ).then(() => { setFraisLib(""); setFraisMontant(""); })
                }
              >
                Ajouter
              </Button>
            </div>
          </section>

          <section className="space-y-2">
            <p className="font-medium text-slate-700">Suite de la procédure</p>
            <Select label="Étape" value={procType} onChange={(e) => setProcType(e.target.value)}>
              {TYPES_PROCEDURE.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </Select>
            <div className="grid grid-cols-2 gap-2">
              <Input label="Date" type="date" value={procDate} onChange={(e) => setProcDate(e.target.value)} />
              <Input label="Note (optionnel)" value={procLib} onChange={(e) => setProcLib(e.target.value)} />
            </div>
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() =>
                action(
                  () => api.post(`/recouvrement/lot/${d.lot_id}/acte`, { type: procType, date_envoi: procDate, libelle: procLib }),
                  "Étape enregistrée."
                ).then(() => setProcLib(""))
              }
            >
              Enregistrer l'étape
            </Button>
            <p className="text-xs leading-relaxed text-slate-400">
              ≤ 5 000 € : la tentative de règlement amiable (conciliateur, gratuit) est obligatoire avant le juge ;
              une procédure simplifiée par commissaire de justice est possible. Au-delà : tribunal judiciaire. Le syndic
              n'a pas besoin d'autorisation de l'assemblée pour le recouvrement. Les sommes se prescrivent par 5 ans.
            </p>
          </section>

          <section>
            <p className="mb-1.5 font-medium text-slate-700">Historique du dossier</p>
            {timeline.length === 0 ? (
              <p className="text-slate-400">Aucun acte pour le moment.</p>
            ) : (
              <ul className="space-y-1.5">
                {timeline.map((t) => (
                  <li key={t.key} className="flex items-start gap-2 text-slate-600">
                    <span className="flex-1">{t.node}</span>
                    {"del" in t && t.del !== null && t.del !== undefined && (
                      <button
                        className="rounded px-1 text-slate-300 hover:bg-slate-100 hover:text-red-600"
                        title="Supprimer cet acte (saisie par erreur)"
                        onClick={() => {
                          if (confirm("Supprimer cet acte ? (tracé dans le journal d'audit)")) {
                            action(() => api.del(`/recouvrement/acte/${t.del}`), "Acte supprimé.");
                          }
                        }}
                      >
                        ✕
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-500">
            Les modèles de courriers (mise en demeure) sont générés automatiquement à partir de la procédure
            prévue par le Service-Public (fiche F2603) et de l'article 19-2 de la loi du 10 juillet 1965.
            Faites-les valider par un conseil juridique avant usage réel — l'application ne fournit pas de
            conseil juridique.
          </p>
        </div>
      )}
    </Modal>
  );
}

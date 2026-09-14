import { useEffect, useState } from "react";
import { api } from "../api";
import { useUser } from "../auth";
import type { Lot, User } from "../types";
import { Button, Card, Input, Modal, Select, Badge, Empty } from "../components/ui";

export default function Lots() {
  const { user } = useUser();
  const isSyndic = user?.role === "syndic";
  const [lots, setLots] = useState<Lot[]>([]);
  // Comptes copropriétaires : les propriétaires sont des COMPTES utilisateurs
  // (modèle « zéro fiche ») — réservés au syndic (l'API refuse aux membres).
  const [comptes, setComptes] = useState<User[]>([]);
  const [modal, setModal] = useState<null | { item?: Lot }>(null);
  const [error, setError] = useState("");

  async function load() {
    const l = await api.get<Lot[]>("/lots");
    setLots(l);
    if (isSyndic) {
      setComptes(await api.get<User[]>("/auth/users"));
    }
  }
  useEffect(() => { load(); }, [isSyndic]); // eslint-disable-line react-hooks/exhaustive-deps

  const totalTantiemes = lots.reduce((s, l) => s + l.tantiemes, 0);
  const ecart = Math.abs(totalTantiemes - 1000);

  function occupationBadge(lot: Lot) {
    if (lot.proprietaire_occupant) return <Badge color="green">propriétaire occupant</Badge>;
    if (lot.statut_occupation === "loue") return <Badge color="amber">loué</Badge>;
    if (lot.statut_occupation === "vacant") return <Badge color="slate">vacant</Badge>;
    return <span className="text-slate-400">—</span>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-800">Lots & occupants</h1>
          <p className="text-sm text-slate-500">
            {lots.length} lot(s) — {totalTantiemes} millièmes au total
            {totalTantiemes !== 1000 && ecart <= 100 && (
              <span className="ml-2 font-medium text-amber-600">
                (base de répartition : {totalTantiemes}‰ — les appels de fonds et les votes
                utilisent ce total réel, pas besoin d'ajuster à 1000)
              </span>
            )}
            {totalTantiemes !== 1000 && ecart > 100 && (
              <span className="ml-2 font-medium text-red-600">
                (⚠ total très éloigné de 1000 — vérifie la saisie des millièmes)
              </span>
            )}
          </p>
        </div>
        {isSyndic && <Button onClick={() => setModal({})}>+ Ajouter un lot</Button>}
      </div>

      <Card title="Lots">
        {lots.length === 0 ? (
          <Empty text="Aucun lot. Ajoutez les lots de la copropriété (appartements, caves, parkings) avec leurs millièmes." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="pb-2 font-medium">N°</th>
                  <th className="pb-2 font-medium">Désignation</th>
                  <th className="pb-2 text-right font-medium">Millièmes</th>
                  <th className="pb-2 font-medium">Propriétaire</th>
                  <th className="pb-2 font-medium">Occupation</th>
                  <th className="pb-2 font-medium">Type</th>
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody>
                {lots.map((lot) => (
                  <tr key={lot.id} className="border-b border-slate-50 last:border-0">
                    <td className="py-2.5 font-semibold text-slate-800">{lot.numero}</td>
                    <td className="py-2.5 text-slate-600">{lot.designation || "—"}</td>
                    <td className="py-2.5 text-right tabular-nums text-slate-700">{lot.tantiemes}</td>
                    <td className="py-2.5 text-slate-600">{lot.proprietaire_nom || "—"}</td>
                    <td className="py-2.5">{occupationBadge(lot)}</td>
                    <td className="py-2.5">
                      <Badge>{lot.type}</Badge>
                    </td>
                    <td className="py-2.5 text-right">
                      {isSyndic && (
                        <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setModal({ item: lot })}>
                          Modifier
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 text-xs text-slate-500">
          Les propriétaires sont des comptes utilisateurs (Réglages → Comptes utilisateurs).
          Chaque copropriétaire règle l'occupation de ses propres lots dans Réglages → Mes lots ;
          le syndic peut tout régler ici. Jamais de nom de locataire (RGPD).
        </p>
      </Card>

      {modal && (
        <LotModal
          item={modal.item}
          comptes={comptes}
          autresTotal={totalTantiemes - (modal.item ? modal.item.tantiemes : 0)}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); load(); }}
          onError={setError}
        />
      )}
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
    </div>
  );
}

function LotModal({ item, comptes, autresTotal, onClose, onSaved, onError }: {
  item?: Lot; comptes: User[]; autresTotal: number; onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const [f, setF] = useState({
    numero: item?.numero ?? "",
    designation: item?.designation ?? "",
    type: item?.type ?? "appartement",
    tantiemes: item?.tantiemes ?? 0,
    proprietaire_id: item?.proprietaire_id ?? "",
    statut_occupation: item?.statut_occupation ?? "",
  });
  const set = (k: string, v: unknown) => setF((p) => ({ ...p, [k]: v }));
  const totalProjete = autresTotal + Number(f.tantiemes || 0);

  async function save() {
    try {
      const body = {
        numero: f.numero, designation: f.designation, type: f.type,
        tantiemes: Number(f.tantiemes),
        proprietaire_id: f.proprietaire_id === "" ? null : Number(f.proprietaire_id),
        statut_occupation: f.statut_occupation,
        notes: "",
      };
      if (item) await api.put(`/lots/${item.id}`, body);
      else await api.post("/lots", body);
      onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Erreur");
    }
  }

  return (
    <Modal open title={item ? `Modifier le lot ${item.numero}` : "Nouveau lot"} onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          <Input label="N° de lot" value={f.numero} onChange={(e) => set("numero", e.target.value)} placeholder="1" />
          <Input
            label="Millièmes"
            type="number"
            value={f.tantiemes}
            onChange={(e) => set("tantiemes", e.target.value)}
            placeholder="250"
            className="col-span-2"
          />
        </div>
        <p className="text-xs text-slate-500">
          Total des millièmes après enregistrement :{" "}
          <b className="tabular-nums">{totalProjete}</b>
          {totalProjete !== 1000 && (
            <span className="ml-1 text-amber-600">
              (les répartitions utiliseront ce total comme base — pas besoin qu'il fasse 1000)
            </span>
          )}
        </p>
        <Input label="Désignation" value={f.designation} onChange={(e) => set("designation", e.target.value)} placeholder="Appartement T3" />
        <Select label="Type" value={f.type} onChange={(e) => set("type", e.target.value)}>
          <option value="appartement">Appartement</option>
          <option value="cave">Cave</option>
          <option value="parking">Parking</option>
          <option value="commerce">Commerce</option>
          <option value="autre">Autre</option>
        </Select>
        <Select label="Propriétaire" value={f.proprietaire_id} onChange={(e) => set("proprietaire_id", e.target.value)}>
          <option value="">— aucun —</option>
          {comptes.map((c) => (
            <option key={c.id} value={c.id}>{[c.prenom, c.nom].filter(Boolean).join(" ")}</option>
          ))}
        </Select>
        <Select
          label="Occupation du lot"
          value={f.statut_occupation}
          onChange={(e) => set("statut_occupation", e.target.value)}
        >
          <option value="">Non renseigné</option>
          <option value="occupant">Propriétaire occupant (le propriétaire y habite)</option>
          <option value="loue">Loué</option>
          <option value="vacant">Vacant</option>
        </Select>
        <p className="text-xs text-slate-500">
          « Propriétaire occupant » : le propriétaire habite son logement. Les noms des locataires
          ne sont jamais enregistrés (RGPD) — un logement non occupé par son propriétaire est
          indiqué « loué » ou « vacant ». Chaque copropriétaire peut régler ses propres lots
          (Réglages → Mes lots).
        </p>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>Enregistrer</Button>
        </div>
      </div>
    </Modal>
  );
}

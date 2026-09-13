import { useEffect, useState } from "react";
import { api } from "../api";
import { useUser } from "../auth";
import type { Lot, Personne } from "../types";
import { Button, Card, Input, Modal, Select, Badge, Empty } from "../components/ui";

export default function Lots() {
  const { user } = useUser();
  const isSyndic = user?.role === "syndic";
  const [lots, setLots] = useState<Lot[]>([]);
  const [personnes, setPersonnes] = useState<Personne[]>([]);
  const [modal, setModal] = useState<null | { type: "lot" | "personne"; item?: Lot | Personne }>(null);
  const [error, setError] = useState("");

  async function load() {
    const [l, p] = await Promise.all([api.get<Lot[]>("/lots"), api.get<Personne[]>("/personnes")]);
    setLots(l);
    setPersonnes(p);
  }
  useEffect(() => { load(); }, []);

  const totalTantiemes = lots.reduce((s, l) => s + l.tantiemes, 0);
  const ecart = Math.abs(totalTantiemes - 1000);
  const prop = (id: number | null) => personnes.find((p) => p.id === id);

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
        {isSyndic && <Button onClick={() => setModal({ type: "lot" })}>+ Ajouter un lot</Button>}
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
                  <th className="pb-2 font-medium">Occupant</th>
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
                    <td className="py-2.5 text-slate-600">{prop(lot.proprietaire_id)?.nom ?? "—"}</td>
                    <td className="py-2.5 text-slate-600">{prop(lot.occupant_id)?.nom ?? "—"}</td>
                    <td className="py-2.5">
                      <Badge>{lot.type}</Badge>
                    </td>
                    <td className="py-2.5 text-right">
                      {isSyndic && (
                        <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setModal({ type: "lot", item: lot })}>
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
      </Card>

      <Card
        title="Personnes (propriétaires & locataires)"
        action={isSyndic ? <Button onClick={() => setModal({ type: "personne" })}>+ Ajouter une personne</Button> : undefined}
      >
        {personnes.length === 0 ? (
          <Empty text="Aucune personne enregistrée." />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {personnes.map((p) => (
              <div key={p.id} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-start justify-between">
                  <div>
                    <p className="font-medium text-slate-800">
                      {p.prenom} {p.nom}
                    </p>
                    <p className="text-xs text-slate-500">{p.email || "—"}</p>
                  </div>
                  {isSyndic && (
                    <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setModal({ type: "personne", item: p })}>
                      Modifier
                    </Button>
                  )}
                </div>
                <div className="mt-2 flex gap-1.5">
                  {p.est_proprietaire && <Badge color="indigo">propriétaire</Badge>}
                  {p.est_occupant && <Badge color="green">occupant</Badge>}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {modal?.type === "lot" && (
        <LotModal
          item={modal.item as Lot | undefined}
          personnes={personnes}
          autresTotal={totalTantiemes - (modal.item ? (modal.item as Lot).tantiemes : 0)}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); load(); }}
          onError={setError}
        />
      )}
      {modal?.type === "personne" && (
        <PersonneModal
          item={modal.item as Personne | undefined}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); load(); }}
          onError={setError}
        />
      )}
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
    </div>
  );
}

function LotModal({ item, personnes, autresTotal, onClose, onSaved, onError }: {
  item?: Lot; personnes: Personne[]; autresTotal: number; onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const [f, setF] = useState({
    numero: item?.numero ?? "",
    designation: item?.designation ?? "",
    type: item?.type ?? "appartement",
    tantiemes: item?.tantiemes ?? 0,
    proprietaire_id: item?.proprietaire_id ?? "",
    occupant_id: item?.occupant_id ?? "",
  });
  const set = (k: string, v: unknown) => setF((p) => ({ ...p, [k]: v }));
  const totalProjete = autresTotal + Number(f.tantiemes || 0);

  async function save() {
    try {
      const body = {
        numero: f.numero, designation: f.designation, type: f.type,
        tantiemes: Number(f.tantiemes),
        proprietaire_id: f.proprietaire_id === "" ? null : Number(f.proprietaire_id),
        occupant_id: f.occupant_id === "" ? null : Number(f.occupant_id),
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
          {personnes.filter((p) => p.est_proprietaire).map((p) => (
            <option key={p.id} value={p.id}>{p.prenom} {p.nom}</option>
          ))}
        </Select>
        <Select label="Occupant (locataire éventuel)" value={f.occupant_id} onChange={(e) => set("occupant_id", e.target.value)}>
          <option value="">— aucun —</option>
          {personnes.filter((p) => p.est_occupant).map((p) => (
            <option key={p.id} value={p.id}>{p.prenom} {p.nom}</option>
          ))}
        </Select>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>Enregistrer</Button>
        </div>
      </div>
    </Modal>
  );
}

function PersonneModal({ item, onClose, onSaved, onError }: {
  item?: Personne; onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const [f, setF] = useState({
    nom: item?.nom ?? "",
    prenom: item?.prenom ?? "",
    email: item?.email ?? "",
    telephone: item?.telephone ?? "",
    adresse: item?.adresse ?? "",
    est_proprietaire: item?.est_proprietaire ?? true,
    est_occupant: item?.est_occupant ?? true,
    notes: "",
  });
  const set = (k: string, v: unknown) => setF((p) => ({ ...p, [k]: v }));

  async function save() {
    try {
      if (item) await api.put(`/personnes/${item.id}`, f);
      else await api.post("/personnes", f);
      onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Erreur");
    }
  }

  return (
    <Modal open title={item ? "Modifier la personne" : "Nouvelle personne"} onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Input label="Nom" value={f.nom} onChange={(e) => set("nom", e.target.value)} required />
          <Input label="Prénom" value={f.prenom} onChange={(e) => set("prenom", e.target.value)} />
        </div>
        <Input label="Email" type="email" value={f.email} onChange={(e) => set("email", e.target.value)} />
        <Input label="Téléphone" value={f.telephone} onChange={(e) => set("telephone", e.target.value)} />
        <Input label="Adresse postale (mises en demeure)" value={f.adresse} onChange={(e) => set("adresse", e.target.value)} />
        <div className="flex gap-4">
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={f.est_proprietaire} onChange={(e) => set("est_proprietaire", e.target.checked)} />
            Propriétaire
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={f.est_occupant} onChange={(e) => set("est_occupant", e.target.checked)} />
            Occupant
          </label>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={save}>Enregistrer</Button>
        </div>
      </div>
    </Modal>
  );
}

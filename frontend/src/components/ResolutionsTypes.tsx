import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Button, Modal } from "./ui";

/** Résolutions types d'une AG annuelle : cases à cocher (pré-cochées : celles de chaque année). */

export interface ModeleResolution {
  code: string; libelle: string; texte: string; majorite: string; nature: string; coche: boolean;
  exercice_id: number | null; remarque: string;
}

const MAJ: Record<string, string> = { art24: "art. 24", art25: "art. 25", art26: "art. 26", unanimite: "unanimité" };

export function useModele(jour: string): [ModeleResolution[], Set<string>, (s: Set<string>) => void] {
  const [modele, setModele] = useState<ModeleResolution[]>([]);
  const [choix, setChoix] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!jour) return;
    api.get<ModeleResolution[]>(`/ag/modele-annuelle?jour=${jour}`).then((m) => {
      setModele(m);
      setChoix(new Set(m.filter((x) => x.coche).map((x) => x.code)));
    }).catch(() => {});
  }, [jour]);
  return [modele, choix, setChoix];
}

export function ListeModele({ modele, choix, onChange }: {
  modele: ModeleResolution[]; choix: Set<string>; onChange: (s: Set<string>) => void;
}) {
  const basculer = (code: string) => {
    const s = new Set(choix);
    if (s.has(code)) s.delete(code); else s.add(code);
    onChange(s);
  };
  return (
    <ul className="max-h-80 space-y-1 overflow-y-auto rounded-lg border border-slate-200 p-2 text-sm">
      {modele.map((m) => {
        const impossible = m.nature === "approbation_comptes" && m.exercice_id === null;
        return (
          <li key={m.code}>
            <label className={`flex items-start gap-2 ${impossible ? "text-slate-400" : "text-slate-700"}`}>
              <input type="checkbox" className="mt-1" disabled={impossible} checked={choix.has(m.code)}
                onChange={() => basculer(m.code)} />
              <span>
                {m.libelle} <Badge color="slate">{MAJ[m.majorite] ?? m.majorite}</Badge>
                {m.remarque && <span className="block text-xs text-slate-500">{m.remarque}</span>}
              </span>
            </label>
          </li>
        );
      })}
    </ul>
  );
}

/** Bouton « Résolutions types » d'une AG existante. */
export function ResolutionsTypesModal({ agId, jour, onClose, onSaved, onError }: {
  agId: number; jour: string; onClose: () => void; onSaved: () => void; onError: (e: string) => void;
}) {
  const [modele, choix, setChoix] = useModele(jour);
  async function ajouter() {
    try {
      await api.post(`/ag/${agId}/resolutions-types`, { codes: [...choix] });
      onSaved();
    } catch (e) { onError(e instanceof Error ? e.message : "Erreur"); }
  }
  return (
    <Modal open title="Résolutions types de l'AG annuelle" onClose={onClose}>
      <div className="space-y-3">
        <p className="text-xs text-slate-500">
          Elles s'ajoutent à la suite de l'ordre du jour, avec leur majorité et un texte à compléter (« …… ») avant la
          convocation. Les montants connus (dépenses de l'exercice écoulé, budget de l'exercice suivant, fonds de
          travaux) sont repris.
        </p>
        <ListeModele modele={modele} choix={choix} onChange={setChoix} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>Annuler</Button>
          <Button onClick={ajouter} disabled={choix.size === 0}>Ajouter {choix.size} résolution(s)</Button>
        </div>
      </div>
    </Modal>
  );
}

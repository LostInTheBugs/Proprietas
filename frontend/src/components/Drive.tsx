import { useEffect, useState } from "react";
import { api } from "../api";
import { Button, Card, Input } from "./ui";

interface EtatDrive {
  autorise: boolean;
  type: "" | "webdav";
  url: string;
  utilisateur: string;
  dossier: string;
  mot_de_passe_defini: boolean;
  documents_sur_le_drive: number;
  dossier_propose: string;
}

/** Drive de la copropriété : ses fichiers rangés sur un serveur WebDAV (Nextcloud, ownCloud, Synology…). */
export function DriveCard() {
  const [etat, setEtat] = useState<EtatDrive | null>(null);
  const [url, setUrl] = useState("");
  const [utilisateur, setUtilisateur] = useState("");
  const [motDePasse, setMotDePasse] = useState("");
  const [dossier, setDossier] = useState("");
  const [occupe, setOccupe] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; texte: string } | null>(null);

  function afficher(e: EtatDrive) {
    setEtat(e);
    setUrl(e.url);
    setUtilisateur(e.utilisateur);
    setDossier(e.dossier || e.dossier_propose);
    setMotDePasse("");
  }
  useEffect(() => { api.get<EtatDrive>("/drive").then(afficher).catch(() => {}); }, []);

  if (!etat || !etat.autorise) return null;
  const branche = etat.type === "webdav";
  const corps = { type: "webdav", url, utilisateur, mot_de_passe: motDePasse, dossier };

  async function lancer(action: () => Promise<{ ok: boolean; texte: string }>) {
    setOccupe(true);
    setMessage(null);
    try {
      setMessage(await action());
    } catch (err) {
      setMessage({ ok: false, texte: err instanceof Error ? err.message : "Échec" });
    } finally {
      setOccupe(false);
    }
  }
  const tester = () => lancer(async () => {
    const r = await api.post<{ ok: boolean; detail: string }>("/drive/test", corps);
    return { ok: r.ok, texte: r.detail };
  });
  const enregistrer = () => lancer(async () => {
    afficher(await api.put<EtatDrive>("/drive", corps));
    return { ok: true, texte: "Drive branché : les nouveaux fichiers y seront rangés." };
  });
  const debrancher = () => lancer(async () => {
    afficher(await api.put<EtatDrive>("/drive", { type: "" }));
    return { ok: true, texte: "Drive débranché : les nouveaux fichiers iront sur le serveur." };
  });

  return (
    <Card title="Drive de la copropriété">
      <div className="space-y-3">
        <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
          Range les fichiers déposés (factures, contrats, devis…) sur votre drive, dans un dossier par catégorie et sous
          un nom lisible, par exemple <code className="text-slate-700">Factures/2026-11-16 Facture d'électricité.pdf</code>.
          Compatible WebDAV : Nextcloud, ownCloud (<code className="text-slate-700">https://cloud.exemple.fr/remote.php/dav/files/identifiant/</code>),
          Synology (paquet WebDAV Server, <code className="text-slate-700">https://nas.exemple.fr:5006/</code>).
        </p>
        {branche ? (
          <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            Drive branché : <strong>{etat.documents_sur_le_drive}</strong> fichier(s) y sont rangés, dans « {etat.dossier} ».
            Les fichiers déposés avant le branchement restent sur le serveur.
          </p>
        ) : (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800">
            Une fois le drive branché, les nouveaux fichiers n'existent <strong>que sur le drive</strong> : s'il est
            éteint, ils ne sont plus consultables ici, et un fichier renommé ou supprimé sur le drive devient introuvable
            dans Proprietas. Pensez à sauvegarder le drive lui-même.
          </p>
        )}
        <Input label="Adresse WebDAV" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://cloud.exemple.fr/remote.php/dav/files/identifiant/" />
        <div className="grid grid-cols-2 gap-3">
          <Input label="Identifiant" value={utilisateur} onChange={(e) => setUtilisateur(e.target.value)} autoComplete="off" />
          <Input label={etat.mot_de_passe_defini ? "Nouveau mot de passe" : "Mot de passe (d'application, de préférence)"} type="password" value={motDePasse}
            onChange={(e) => setMotDePasse(e.target.value)} placeholder={etat.mot_de_passe_defini ? "Laisser vide pour conserver" : ""} autoComplete="new-password" />
        </div>
        <Input label="Dossier sur le drive" value={dossier} onChange={(e) => setDossier(e.target.value)}
          disabled={etat.documents_sur_le_drive > 0} placeholder={etat.dossier_propose} />
        {etat.documents_sur_le_drive > 0 && (
          <p className="text-xs text-slate-500">Le dossier ne peut plus changer tant que des fichiers y sont rangés.</p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button onClick={enregistrer} disabled={occupe || !url || !dossier}>{branche ? "Enregistrer" : "Brancher le drive"}</Button>
          <Button variant="secondary" onClick={tester} disabled={occupe || !url || !dossier}>{occupe ? "Essai…" : "Tester la connexion"}</Button>
          {branche && etat.documents_sur_le_drive === 0 && (
            <Button variant="ghost" onClick={debrancher} disabled={occupe}>Débrancher</Button>
          )}
        </div>
        {message && (
          <p className={`rounded-lg px-3 py-2 text-sm ${message.ok ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
            {message.ok ? "✓ " : "✗ "}{message.texte}
          </p>
        )}
      </div>
    </Card>
  );
}

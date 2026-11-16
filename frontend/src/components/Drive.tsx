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
  documents_sur_le_serveur: number;
  dossier_propose: string;
}

interface Lot { deplaces: number; restants: number; introuvables: { id: number; libelle: string }[] }
interface Verification {
  verifies: number;
  introuvables: { id: number; libelle: string; categorie: string; fichier: string; retrouvable: boolean }[];
  non_rattaches: { chemin: string; taille: number }[];
  relies?: { id: number; libelle: string; ancien: string; nouveau: string }[];
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
  const [verif, setVerif] = useState<Verification | null>(null);
  const [choix, setChoix] = useState<Record<number, string>>({});

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

  // Déplacement par lots : le serveur traite quelques fichiers par appel, on rappelle tant qu'il en reste.
  const transferer = (chemin: "deplacer" | "rapatrier", fait: string) => lancer(async () => {
    let total = 0;
    const absents: string[] = [];
    for (;;) {
      const lot = await api.post<Lot>(`/drive/${chemin}`);
      total += lot.deplaces;
      absents.push(...lot.introuvables.map((i) => i.libelle));
      setMessage({ ok: true, texte: `${total} fichier(s) ${fait}, ${lot.restants} restant(s)…` });
      if (lot.restants === 0 || lot.deplaces === 0) break;
    }
    afficher(await api.get<EtatDrive>("/drive"));
    setVerif(null);
    return absents.length
      ? { ok: false, texte: `${total} fichier(s) ${fait}. Introuvables à l'origine, laissés tels quels : ${absents.join(", ")}.` }
      : { ok: true, texte: `${total} fichier(s) ${fait}.` };
  });
  const verifier = () => lancer(async () => {
    const v = await api.get<Verification>("/drive/verification");
    setVerif(v);
    return v.introuvables.length
      ? { ok: false, texte: `${v.introuvables.length} fichier(s) introuvable(s) sur ${v.verifies} : renommés, déplacés ou supprimés sur le drive.` }
      : { ok: true, texte: `Les ${v.verifies} fichier(s) attendus sont bien sur le drive.` };
  });
  const retrouver = () => lancer(async () => {
    const v = await api.post<Verification>("/drive/retrouver");
    setVerif(v);
    const n = v.relies?.length ?? 0;
    return { ok: v.introuvables.length === 0, texte: `${n} fichier(s) retrouvé(s) par leur contenu et reliés${v.introuvables.length ? `, ${v.introuvables.length} encore introuvable(s)` : ""}.` };
  });
  const relier = (id: number) => lancer(async () => {
    await api.post("/drive/relier", { document_id: id, chemin: choix[id] });
    setVerif(await api.get<Verification>("/drive/verification"));
    return { ok: true, texte: "Fichier relié." };
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
        {branche && (
          <div className="space-y-2 border-t border-slate-100 pt-3">
            <p className="text-sm font-medium text-slate-700">Fichiers</p>
            {etat.documents_sur_le_serveur > 0 && (
              <p className="text-sm text-slate-600">
                <strong>{etat.documents_sur_le_serveur}</strong> fichier(s) déposés avant le branchement sont encore sur le serveur.
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              {etat.documents_sur_le_serveur > 0 && (
                <Button variant="secondary" onClick={() => transferer("deplacer", "déplacé(s) vers le drive")} disabled={occupe}>Déplacer vers le drive</Button>
              )}
              <Button variant="secondary" onClick={verifier} disabled={occupe}>Vérifier le drive</Button>
              {etat.documents_sur_le_drive > 0 && (
                <Button variant="ghost" disabled={occupe}
                  onClick={() => { if (window.confirm("Ramener sur le serveur tous les fichiers du drive ? Ils seront retirés du drive, qui pourra ensuite être débranché.")) transferer("rapatrier", "rapatrié(s) sur le serveur"); }}>
                  Rapatrier sur le serveur
                </Button>
              )}
            </div>
            {verif && verif.introuvables.length > 0 && (
              <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-medium text-amber-900">Fichiers introuvables sur le drive</p>
                  <Button variant="secondary" onClick={retrouver} disabled={occupe}>Retrouver par le contenu</Button>
                </div>
                <p className="text-xs leading-relaxed text-amber-800">
                  « Retrouver » relie chaque document au fichier du drive qui a exactement le même contenu, même renommé ou
                  déplacé. Sinon, choisissez le fichier à la main, ou supprimez le document dans la page Documents.
                </p>
                {verif.introuvables.map((d) => (
                  <div key={d.id} className="flex flex-wrap items-end gap-2 border-t border-amber-200 pt-2 text-sm">
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium text-slate-800">{d.libelle}</p>
                      <p className="truncate text-xs text-slate-500">attendu : {d.fichier}{d.retrouvable ? "" : " (déposé avant le relevé des empreintes : à relier à la main)"}</p>
                    </div>
                    <select value={choix[d.id] ?? ""} onChange={(e) => setChoix({ ...choix, [d.id]: e.target.value })}
                      className="max-w-xs rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm" aria-label={`Fichier du drive pour ${d.libelle}`}>
                      <option value="">Choisir un fichier du drive…</option>
                      {verif.non_rattaches.map((f) => <option key={f.chemin} value={f.chemin}>{f.chemin}</option>)}
                    </select>
                    <Button variant="secondary" onClick={() => relier(d.id)} disabled={occupe || !choix[d.id]}>Relier</Button>
                  </div>
                ))}
              </div>
            )}
            {verif && verif.non_rattaches.length > 0 && (
              <p className="text-xs text-slate-500">
                {verif.non_rattaches.length} fichier(s) du dossier ne sont rattachés à aucun document (déposés directement sur le drive) : Proprietas n'y touche pas.
              </p>
            )}
          </div>
        )}
        {message && (
          <p className={`rounded-lg px-3 py-2 text-sm ${message.ok ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
            {message.ok ? "✓ " : "✗ "}{message.texte}
          </p>
        )}
      </div>
    </Card>
  );
}

import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Button, Card, Input, Select } from "./ui";

interface EtatDrive {
  autorise: boolean;
  // Application Google : de la copropriété (identifiant affiché, code secret jamais) ou de l'instance (.env).
  google: { source: "" | "copropriete" | "instance"; instance: boolean; client_id: string; secret_defini: boolean; retour: string };
  type: "" | "webdav" | "google";
  url: string;
  utilisateur: string;
  dossier: string;
  mot_de_passe_defini: boolean;
  documents_sur_le_drive: number;
  documents_sur_le_serveur: number;
  en_attente: { nombre: number; octets: number; plafond_mo: number };
  dossier_propose: string;
  sauvegarde: { auto: boolean; mot_de_passe_defini: boolean; derniere: string | null; prochaine: string | null; erreur: string; gardees: number };
}

const dateHeure = (iso: string | null) => iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" }) : "—";

interface Lot { deplaces: number; restants: number; introuvables: { id: number; libelle: string }[] }
interface Verification {
  verifies: number;
  introuvables: { id: number; libelle: string; categorie: string; fichier: string; retrouvable: boolean }[];
  non_rattaches: { chemin: string; taille: number }[];
  relies?: { id: number; libelle: string; ancien: string; nouveau: string }[];
}

const GUIDE_GOOGLE = "https://github.com/LostInTheBugs/Proprietas/blob/main/docs/google-drive.md";

/** Drive de la copropriété : ses fichiers rangés sur un serveur WebDAV (Nextcloud, ownCloud, Synology…) ou sur
 *  Google Drive. Le type de drive se choisit dans une liste ; les champs suivent. */
export function DriveCard() {
  const [etat, setEtat] = useState<EtatDrive | null>(null);
  const [url, setUrl] = useState("");
  const [utilisateur, setUtilisateur] = useState("");
  const [motDePasse, setMotDePasse] = useState("");
  const [dossier, setDossier] = useState("");
  const [occupe, setOccupe] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; texte: string } | null>(null);
  const zoneMessage = useRef<HTMLParagraphElement>(null);
  const [verif, setVerif] = useState<Verification | null>(null);
  const [choix, setChoix] = useState<Record<number, string>>({});
  const [mdpSauvegarde, setMdpSauvegarde] = useState("");
  const [archives, setArchives] = useState<{ fichier: string; taille: number }[] | null>(null);

  const [service, setService] = useState<"webdav" | "google">("webdav");
  const [googleId, setGoogleId] = useState("");
  const [googleSecret, setGoogleSecret] = useState("");
  const [copie, setCopie] = useState(false);

  function afficher(e: EtatDrive) {
    setEtat(e);
    if (e.type) setService(e.type);
    setUrl(e.url);
    setUtilisateur(e.utilisateur);
    setDossier(e.dossier || e.dossier_propose);
    setMotDePasse("");
    setGoogleId(e.google.client_id);
    setGoogleSecret("");
  }
  useEffect(() => {
    api.get<EtatDrive>("/drive").then(afficher).catch(() => {});
    // Retour de la page de Google : le serveur renvoie ici avec le résultat dans l'adresse.
    const params = new URLSearchParams(window.location.search);
    const ok = params.get("drive_ok"), erreur = params.get("drive_erreur");
    if (ok || erreur) {
      setMessage({ ok: !!ok, texte: ok || erreur || "" });
      params.delete("drive_ok");
      params.delete("drive_erreur");
      window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
    }
  }, []);

  // Le résultat s'affiche en bas de la carte : on l'amène à l'écran (sinon, après « Tester la connexion »
  // ou au retour de Google, rien ne semble se passer).
  useEffect(() => {
    if (message) zoneMessage.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [message, etat]);

  if (!etat || !etat.autorise) return null;
  const branche = etat.type !== "";
  const google = service === "google";
  const corps = google ? { type: "google" } : { type: "webdav", url, utilisateur, mot_de_passe: motDePasse, dossier };
  const connecterGoogle = () => lancer(async () => {
    const r = await api.post<{ adresse: string }>("/drive/google/connecter",
      { dossier, client_id: googleId.trim(), client_secret: googleSecret.trim() });
    window.location.href = r.adresse;           // page de Google, puis retour dans Réglages
    return { ok: true, texte: "Redirection vers Google…" };
  });

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
  const transferer = (chemin: "deplacer" | "rapatrier" | "ranger-attente", fait: string) => lancer(async () => {
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

  const reglerSauvegarde = (auto: boolean) => lancer(async () => {
    afficher(await api.put<EtatDrive>("/drive/sauvegarde", { auto, mot_de_passe: mdpSauvegarde }));
    setMdpSauvegarde("");
    return { ok: true, texte: auto ? "Sauvegarde automatique activée : une par semaine, sur le drive." : "Réglages de la sauvegarde enregistrés." };
  });
  const sauvegarderMaintenant = () => lancer(async () => {
    const r = await api.post<{ fichier: string; etat: EtatDrive }>("/drive/sauvegarde/maintenant");
    afficher(r.etat);
    setArchives(await api.get<{ fichier: string; taille: number }[]>("/drive/sauvegardes"));
    return { ok: true, texte: `Sauvegarde déposée sur le drive : ${r.fichier}` };
  });
  const voirSauvegardes = () => lancer(async () => {
    const liste = await api.get<{ fichier: string; taille: number }[]>("/drive/sauvegardes");
    setArchives(liste);
    return { ok: true, texte: `${liste.length} sauvegarde(s) sur le drive.` };
  });

  return (
    <Card title="Drive de la copropriété">
      <div className="space-y-3">
        <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
          Range les fichiers déposés (factures, contrats, devis…) sur votre drive, dans un dossier par catégorie et sous
          un nom lisible, par exemple <code className="text-slate-700">Factures/2026-11-16 Facture d'électricité.pdf</code>.
          Deux types de drive : WebDAV (Nextcloud, ownCloud, Synology) ou Google Drive.
        </p>
        {!branche && (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
            Utilisez un <strong>compte dédié à la copropriété</strong> (par exemple une adresse Gmail ou un compte Nextcloud
            créés pour l'immeuble), pas votre compte personnel : quand le syndic change, il transmet ce compte à son
            successeur, et les documents restent à la copropriété.
          </p>
        )}
        {branche ? (
          <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            Drive branché : <strong>{etat.documents_sur_le_drive}</strong> fichier(s) y sont rangés, dans « {etat.dossier} ».
          </p>
        ) : etat.documents_sur_le_drive > 0 ? (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
            <strong>{etat.documents_sur_le_drive}</strong> fichier(s) de cette copropriété sont sur un drive qui n'est pas
            branché ici (copropriété restaurée d'une sauvegarde). Rebranchez le drive ci-dessous (même service, même compte), sur le dossier
            « {etat.dossier} », pour les retrouver.
          </p>
        ) : (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800">
            Une fois le drive branché, les nouveaux fichiers n'existent <strong>que sur le drive</strong> : s'il est
            éteint, ils ne sont plus consultables ici, et un fichier renommé ou supprimé sur le drive devient introuvable
            dans Proprietas. Pensez à sauvegarder le drive lui-même.
          </p>
        )}
        <Select label="Type de drive" value={service} onChange={(e) => { setService(e.target.value as "webdav" | "google"); setMessage(null); }}
          disabled={branche && etat.documents_sur_le_drive > 0}>
          <option value="webdav">Nextcloud, ownCloud, Synology (WebDAV)</option>
          <option value="google">Google Drive</option>
        </Select>
        {branche && etat.documents_sur_le_drive > 0 && (
          <p className="text-xs text-slate-500">Le type de drive ne peut plus changer tant que des fichiers y sont rangés.</p>
        )}
        {google ? (<>
          <p className="text-sm text-slate-600">
            {etat.type === "google"
              ? <>Compte Google : <strong>{etat.utilisateur}</strong>. Proprietas ne voit que les dossiers et fichiers qu'il a créés lui-même.</>
              : <>Vous serez envoyé sur la page de Google pour autoriser Proprietas. Il n'aura accès qu'aux dossiers et fichiers qu'il crée lui-même.</>}
          </p>
          <div className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
            <p className="text-xs leading-relaxed text-slate-600">
              <strong>Application Google</strong> : créée une fois dans la console Google Cloud, de préférence avec le compte
              Google de la copropriété (<a className="text-indigo-700 underline" href={GUIDE_GOOGLE} target="_blank" rel="noreferrer">guide pas à pas</a>).
              {etat.google.instance && !etat.google.client_id && <> Laissez ces champs vides pour utiliser celle de cette instance.</>}
            </p>
            <Input label="ID client" value={googleId} onChange={(e) => setGoogleId(e.target.value)} autoComplete="off"
              placeholder="123456789012-abc….apps.googleusercontent.com" />
            <Input label={etat.google.secret_defini ? "Nouveau code secret du client" : "Code secret du client"} type="password"
              value={googleSecret} onChange={(e) => setGoogleSecret(e.target.value)} autoComplete="new-password"
              placeholder={etat.google.secret_defini ? "Laisser vide pour conserver" : "GOCSPX-…"} />
            {etat.google.retour && (
              <div className="text-xs text-slate-600">
                <p className="mb-1">URI de redirection à déclarer dans le client Google (« URI de redirection autorisés ») :</p>
                <div className="flex items-center gap-2 rounded-lg bg-white px-2 py-1.5 ring-1 ring-slate-200">
                  <code className="flex-1 select-all overflow-x-auto whitespace-nowrap text-slate-800">{etat.google.retour}</code>
                  <button type="button" className="shrink-0 font-medium text-indigo-700"
                    onClick={() => { navigator.clipboard?.writeText(etat.google.retour); setCopie(true); setTimeout(() => setCopie(false), 1500); }}>
                    {copie ? "✓ copié" : "copier"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </>) : (<>
        <Input label="Adresse WebDAV" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://cloud.exemple.fr/remote.php/dav/files/identifiant/" />
        <p className="-mt-2 text-xs text-slate-500">
          Nextcloud, ownCloud : <code>https://cloud.exemple.fr/remote.php/dav/files/identifiant/</code> ; Synology (paquet WebDAV
          Server) : <code>https://nas.exemple.fr:5006/</code>.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <Input label="Identifiant" value={utilisateur} onChange={(e) => setUtilisateur(e.target.value)} autoComplete="off" />
          <Input label={etat.mot_de_passe_defini ? "Nouveau mot de passe" : "Mot de passe (d'application, de préférence)"} type="password" value={motDePasse}
            onChange={(e) => setMotDePasse(e.target.value)} placeholder={etat.mot_de_passe_defini ? "Laisser vide pour conserver" : ""} autoComplete="new-password" />
        </div>
        </>)}
        <Input label="Dossier sur le drive" value={dossier} onChange={(e) => setDossier(e.target.value)}
          disabled={etat.documents_sur_le_drive > 0} placeholder={etat.dossier_propose} />
        {etat.documents_sur_le_drive > 0 && (
          <p className="text-xs text-slate-500">Le dossier ne peut plus changer tant que des fichiers y sont rangés.</p>
        )}
        <div className="flex flex-wrap gap-2">
          {google ? (
            <Button onClick={connecterGoogle} disabled={occupe || !dossier}>
              {etat.type === "google" ? "Reconnecter Google Drive" : "Se connecter à Google Drive"}
            </Button>
          ) : (
            <Button onClick={enregistrer} disabled={occupe || !url || !dossier}>{etat.type === "webdav" ? "Enregistrer" : "Brancher le drive"}</Button>
          )}
          {(!google || etat.type === "google") && (
            <Button variant="secondary" onClick={tester} disabled={occupe || (!google && !url) || !dossier}>{occupe ? "Essai…" : "Tester la connexion"}</Button>
          )}
          {branche && etat.documents_sur_le_drive === 0 && (
            <Button variant="ghost" onClick={debrancher} disabled={occupe}>Débrancher</Button>
          )}
        </div>
        {branche && (
          <div className="space-y-2 border-t border-slate-100 pt-3">
            <p className="text-sm font-medium text-slate-700">Fichiers</p>
            {etat.en_attente.nombre > 0 && (
              <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
                <strong>{etat.en_attente.nombre}</strong> document(s) déposés pendant une panne du drive sont gardés sur le serveur
                ({(etat.en_attente.octets / 1024 / 1024).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} Mo) : ils sont
                rangés sur le drive automatiquement dès son retour (essai toutes les 5 minutes).
              </p>
            )}
            {etat.documents_sur_le_serveur > 0 && (
              <p className="text-sm text-slate-600">
                <strong>{etat.documents_sur_le_serveur}</strong> fichier(s) déposés avant le branchement sont encore sur le serveur.
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              {etat.documents_sur_le_serveur > 0 && (
                <Button variant="secondary" onClick={() => transferer("deplacer", "déplacé(s) vers le drive")} disabled={occupe}>Déplacer vers le drive</Button>
              )}
              {etat.en_attente.nombre > 0 && (
                <Button variant="secondary" onClick={() => transferer("ranger-attente", "rangé(s) sur le drive")} disabled={occupe}>Ranger maintenant</Button>
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
        {branche && (
          <div className="space-y-2 border-t border-slate-100 pt-3">
            <p className="text-sm font-medium text-slate-700">Sauvegardes sur le drive</p>
            <p className="text-xs leading-relaxed text-slate-600">
              Une archive chiffrée de toute la copropriété (comptes et données personnelles compris), déposée dans
              « {etat.dossier}/Sauvegardes ». Avec les fichiers déjà rangés sur le drive, elle permet de repartir sur un
              autre serveur. Les {etat.sauvegarde.gardees} plus récentes sont gardées.
            </p>
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800">
              <strong>Notez ce mot de passe ailleurs</strong> (gestionnaire de mots de passe, papier) : il n'est pas dans la
              sauvegarde, et sans lui elle est illisible.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <Input label={etat.sauvegarde.mot_de_passe_defini ? "Nouveau mot de passe des sauvegardes" : "Mot de passe des sauvegardes (10 caractères min.)"}
                type="password" value={mdpSauvegarde} onChange={(e) => setMdpSauvegarde(e.target.value)}
                placeholder={etat.sauvegarde.mot_de_passe_defini ? "Laisser vide pour conserver" : ""} autoComplete="new-password" />
              <div className="text-sm text-slate-600">
                <p>Dernière : <strong>{dateHeure(etat.sauvegarde.derniere)}</strong></p>
                <p>Prochaine : <strong>{etat.sauvegarde.auto ? dateHeure(etat.sauvegarde.prochaine) : "à la demande"}</strong></p>
              </div>
            </div>
            {etat.sauvegarde.erreur && (
              <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">Dernière sauvegarde automatique en échec — {etat.sauvegarde.erreur}</p>
            )}
            <div className="flex flex-wrap gap-2">
              {etat.sauvegarde.auto ? (
                <Button variant="secondary" onClick={() => reglerSauvegarde(false)} disabled={occupe}>Arrêter la sauvegarde automatique</Button>
              ) : (
                <Button onClick={() => reglerSauvegarde(true)} disabled={occupe || (!etat.sauvegarde.mot_de_passe_defini && mdpSauvegarde.length < 10)}>
                  Sauvegarder chaque semaine
                </Button>
              )}
              {mdpSauvegarde && etat.sauvegarde.auto === true && (
                <Button variant="secondary" onClick={() => reglerSauvegarde(true)} disabled={occupe || mdpSauvegarde.length < 10}>Changer le mot de passe</Button>
              )}
              {mdpSauvegarde && !etat.sauvegarde.auto && (
                <Button variant="secondary" onClick={() => reglerSauvegarde(false)} disabled={occupe || mdpSauvegarde.length < 10}>Enregistrer le mot de passe</Button>
              )}
              <Button variant="secondary" onClick={sauvegarderMaintenant} disabled={occupe || !etat.sauvegarde.mot_de_passe_defini}>Sauvegarder maintenant</Button>
              <Button variant="ghost" onClick={voirSauvegardes} disabled={occupe}>Voir les sauvegardes</Button>
            </div>
            {archives && archives.length > 0 && (
              <ul className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-600">
                {archives.map((a) => (
                  <li key={a.fichier} className="flex justify-between gap-4 py-0.5">
                    <span className="truncate">{a.fichier}</span>
                    <span className="shrink-0">{(a.taille / 1024).toLocaleString("fr-FR", { maximumFractionDigits: 0 })} Ko</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {message && (
          <p ref={zoneMessage} className={`rounded-lg px-3 py-2 text-sm ${message.ok ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
            {message.ok ? "✓ " : "✗ "}{message.texte}
          </p>
        )}
      </div>
    </Card>
  );
}

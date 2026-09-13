import { useEffect, useState } from "react";
import { postAuthStep } from "../api";
import { Button, Input } from "./ui";

interface SetupData {
  secret: string;
  otpauth_uri: string;
  qr_svg: string;
}

/** Assistant d'enrôlement TOTP : QR → premier code → codes de secours.
 *
 * Utilisé pendant la connexion (enrôlement forcé par la politique, jeton
 * « setup ») et depuis la page Sécurité (activation volontaire, jeton complet).
 */
export default function TwoFactorWizard({
  token,
  intro,
  onDone,
  onCancel,
}: {
  token: string;
  intro?: string;
  onDone: (accessToken?: string) => void;
  onCancel?: () => void;
}) {
  const [setup, setSetup] = useState<SetupData | null>(null);
  const [etape, setEtape] = useState<"chargement" | "qr" | "codes" | "erreur">("chargement");
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[]>([]);
  const [accessToken, setAccessToken] = useState<string | undefined>(undefined);
  const [note, setNote] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    postAuthStep<SetupData>("/auth/2fa/setup", {}, token)
      .then((d) => {
        setSetup(d);
        setEtape("qr");
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Erreur");
        setEtape("erreur");
      });
  }, [token]);

  async function valider(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await postAuthStep<{ recovery_codes: string[]; access_token?: string }>(
        "/auth/2fa/verify",
        { code },
        token
      );
      setCodes(res.recovery_codes);
      setAccessToken(res.access_token);
      setEtape("codes");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur");
    } finally {
      setBusy(false);
    }
  }

  if (etape === "chargement") {
    return <p className="text-sm text-slate-500">Préparation de l'enrôlement…</p>;
  }

  if (etape === "erreur") {
    return (
      <div className="space-y-3">
        <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
        {onCancel && (
          <Button variant="secondary" onClick={onCancel}>
            Retour
          </Button>
        )}
      </div>
    );
  }

  if (etape === "qr" && setup) {
    const secretGroupe = setup.secret.match(/.{1,4}/g)?.join(" ") ?? setup.secret;
    return (
      <form onSubmit={valider} className="space-y-4">
        {intro && <p className="text-sm leading-relaxed text-slate-600">{intro}</p>}
        <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-600">
          <li>Installez une application d'authentification (FreeOTP, Aegis, Google Authenticator…).</li>
          <li>Scannez ce QR code :</li>
        </ol>
        <img
          src={setup.qr_svg}
          alt="QR code à scanner avec l'application d'authentification"
          className="mx-auto h-52 w-52 rounded-lg border border-slate-200 bg-white p-2"
        />
        <p className="text-center text-xs text-slate-500">
          Pas de scan possible ? Saisissez cette clé :{" "}
          <span className="select-all font-mono text-slate-700">{secretGroupe}</span>
        </p>
        <Input
          label="Code à 6 chiffres affiché par l'application"
          inputMode="numeric"
          autoComplete="one-time-code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          required
          autoFocus
          placeholder="123456"
        />
        {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        <div className="flex gap-2">
          <Button type="submit" disabled={busy || code.trim().length < 6}>
            {busy ? "…" : "Vérifier et activer"}
          </Button>
          {onCancel && (
            <Button type="button" variant="secondary" onClick={onCancel}>
              Annuler
            </Button>
          )}
        </div>
      </form>
    );
  }

  return (
    <div className="space-y-4">
      <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
        ⚠️ Notez ces codes de secours MAINTENANT : ils ne seront plus jamais affichés. Chaque code
        permet une connexion unique si vous perdez votre téléphone.
      </p>
      <div className="grid grid-cols-2 gap-1.5 rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-sm text-slate-800">
        {codes.map((c) => (
          <span key={c} className="select-all">
            {c}
          </span>
        ))}
      </div>
      <label className="flex items-center gap-2 text-sm text-slate-600">
        <input type="checkbox" checked={note} onChange={(e) => setNote(e.target.checked)} />
        J'ai noté mes codes de secours
      </label>
      <Button disabled={!note} onClick={() => onDone(accessToken)}>
        Continuer
      </Button>
    </div>
  );
}

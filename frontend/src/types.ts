// Types alignés sur l'API backend

export interface User {
  id: number;
  email: string;
  nom: string;
  prenom: string;
  role: string;
  personne_id: number | null;
  est_occupant: boolean; // « propriétaire occupant » : occupe son logement
  two_factor_enabled?: boolean;
  theme?: string;
}

export interface Copro {
  id: number;
  nom: string;
  adresse: string;
  ville: string;
  code_postal: string;
  annee_construction: number | null;
  regles_pays: string;
  devise: string;
  fonds_travaux_actif: boolean;
  fonds_travaux_taux_pct: number;
  fonds_travaux_compte: string;
  compte_bancaire_separe: string;
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  // smtp_password absent : le backend ne renvoie jamais le secret
  email_expediteur: string;
  frontend_url: string;
  relance_auto: boolean;
  relance_frequence: string;
  relance_jour: number;
  relance_heure: string;
  relance_minimum: number;
  totp_policy: string;
  notes: string;
}

export interface LoginResponse {
  access_token?: string | null;
  token_type?: string;
  two_factor_required?: boolean;
  must_enroll_2fa?: boolean;
  challenge_token?: string | null;
}

export interface TwoFactorStatus {
  enabled: boolean;
  recovery_codes_left: number;
  policy: string;
  required: boolean;
}

export interface AuditEntry {
  id: number;
  created_at: string;
  user_email: string;
  user_nom: string;
  action: string;
  detail: string;
  ip: string;
}

export interface DiagnosticItem {
  id: string;
  label: string;
  statut: string; // ok | attention | echec | ignore
  detail: string;
}

export interface InstanceOut {
  mode: string; // local | vps | maison
  public_url: string;
  first_external_at: string | null;
  last_check_at: string | null;
  last_check: DiagnosticItem[];
  exposed_unprotected: boolean;
  https_active: boolean;
  version: string;
}

export interface Personne {
  id: number;
  nom: string;
  prenom: string;
  email: string;
  telephone: string;
  adresse: string;
  notes: string;
  // Enrichissements GET /api/personnes (aucun n'est stocké sur la fiche) :
  est_proprietaire?: boolean; // dérivé : propriétaire d'au moins un lot
  a_un_compte?: boolean; // un compte utilisateur est lié à cette fiche
  compte_occupant?: boolean; // le compte lié déclare « occupe son logement »
}

export interface Lot {
  id: number;
  numero: string;
  designation: string;
  type: string;
  tantiemes: number;
  surface_m2: number | null;
  proprietaire_id: number | null;
  statut_occupation: string; // "" | "loue" | "vacant" (jamais de nom de locataire — RGPD)
  proprietaire_occupant?: boolean; // dérivé : le compte du propriétaire « occupe son logement »
  notes: string;
}

export interface LotSolde {
  lot: Lot;
  proprietaire: Personne | null;
  total_appels: number;
  total_appels_fonds: number;
  total_encaisse: number;
  solde: number;
}

export interface Exercice {
  id: number;
  annee: number;
  cloture: boolean;
  budget_total: number;
}

export interface BudgetLine {
  id: number;
  libelle: string;
  montant: number;
  type_repartition: string;
}

export interface AppelLot {
  id: number;
  lot_id: number;
  lot_numero: string;
  montant_charges: number;
  montant_fonds_travaux: number;
}

export interface Appel {
  id: number;
  exercice_id: number;
  libelle: string;
  date_emission: string;
  date_echeance: string | null;
  montant_total: number;
  inclut_fonds_travaux: boolean;
  fonds_travaux_montant: number;
  parts: AppelLot[];
}

export interface Mouvement {
  id: number;
  date: string;
  libelle: string;
  type: string;
  categorie: string;
  montant: number;
  lot_id: number | null;
  appel_id: number | null;
  piece_path: string;
}

export interface EtatDateLot {
  lot: Lot;
  appels_charges: number;
  appels_fonds: number;
  encaisse: number;
  solde: number;
}

export interface Recap {
  exercice_id: number;
  annee: number;
  budget_previsionnel: number;
  encaisse: number;
  depense: number;
  solde_caisse: number;
  fonds_travaux_encaisse: number;
  appels_en_cours: number;
  nb_lots: number;
  regime_petite_copro: boolean;
  lots: EtatDateLot[];
}

export interface Vote {
  id: number;
  lot_id: number;
  voix: string;
}

export interface ResolutionResult {
  statut: string;
  pour: number;
  contre: number;
  abstention: number;
  total: number;
  quorum: number;
  regime_deux: boolean;
  detail: string;
}

export interface Resolution {
  id: number;
  ag_id: number;
  numero: number;
  libelle: string;
  texte: string;
  majorite: string;
  statut: string;
  votes: Vote[];
  resultat: ResolutionResult | null;
}

export interface AG {
  id: number;
  date: string;
  heure: string;
  type_ag: string;
  statut: string;
  lieu: string;
  notes: string;
  rappel_jours: number;
  convocation_envoyee: boolean;
  resolutions: Resolution[];
}

export interface CreneauVote {
  id: number;
  lot_id: number;
  lot_numero: string;
  dispo: boolean;
}

export interface Creneau {
  id: number;
  debut: string;
  fin: string | null;
  votes: CreneauVote[];
}

export interface Invitation {
  id: number;
  personne_nom: string;
  personne_email: string;
  date_envoi: string;
  statut: string;
  message: string;
}

export interface InvitationsResult {
  envoyes: number;
  sans_email: number;
  erreurs: string[];
}

export interface RelanceLot {
  lot_id: number;
  lot_numero: string;
  personne_id: number | null;
  personne_nom: string;
  personne_email: string;
  appels_charges: number;
  appels_fonds: number;
  encaisse: number;
  solde: number;
}

export interface Relance {
  id: number;
  lot_id: number;
  lot_numero: string;
  personne_nom: string;
  personne_email: string;
  date_envoi: string;
  statut: string;
  montant_du: number;
  message: string;
}

export interface Travaux {
  id: number;
  libelle: string;
  categorie: string;
  annee: number;
  montant: number;
  statut: string;
  notes: string;
}

export interface Contact {
  id: number;
  nom: string;
  type: string;
  categorie: string;
  telephone: string;
  email: string;
  adresse: string;
  site_web: string;
  notes: string;
}

export interface Contrat {
  id: number;
  libelle: string;
  type: string;
  reference: string;
  contact_id: number | null;
  contact_nom: string;
  date_debut: string;
  date_fin: string;
  montant: number;
  periode: string;
  renouvellement_auto: boolean;
  notes: string;
  statut: string; // actif, expire_bientot, expire
  jours_restants: number | null;
}

export interface Document {
  id: number;
  categorie: string;
  libelle: string;
  fichier: string;
  date_ajout: string;
}

export interface Entretien {
  id: number;
  date: string;
  type_intervention: string;
  prestataire: string;
  cout: number;
  lot_id: number | null;
  description: string;
}

export interface Majorite {
  label: string;
  description: string;
}

export const fmtEUR = (n: number) =>
  new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" }).format(n || 0);

export const fmtDate = (d: string) =>
  new Date(d + (d.length === 10 ? "T00:00:00" : "")).toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });

export const fmtDateTime = (d: string) =>
  new Date(d).toLocaleDateString("fr-FR", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

export const toLocalInput = (d: Date) => {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

// ---------- Recouvrement ----------
export interface RecouvrementLot {
  lot_id: number;
  lot_numero: string;
  personne_id: number | null;
  personne_nom: string;
  personne_email: string;
  solde: number;
  retard_depuis: string | null;
  statut: string;
  statut_label: string;
  md_date: string | null;
  md_jours: number | null;
  jours_restants: number | null;
  frais_total: number;
  interets: number;
  total_reclame: number;
}

export interface DecompteLigne {
  exercice: number | null;
  libelle: string;
  echeance: string | null;
  charges: number;
  fonds: number;
  montant: number;
  restant_du: number;
  echu: boolean;
}

export interface RecouvrementActe {
  id: number;
  type: string;
  date_acte: string;
  date_envoi: string | null;
  mode_envoi: string;
  reference: string;
  montant: number;
  libelle: string;
  auteur: string;
}

export interface RecouvrementDossier {
  lot_id: number;
  lot_numero: string;
  personne_nom: string;
  personne_email: string;
  personne_adresse: string;
  solde: number;
  arriere_echu: number;
  retard_depuis: string | null;
  statut: string;
  statut_label: string;
  md_date: string | null;
  md_jours: number | null;
  jours_restants: number | null;
  frais_total: number;
  interets: number;
  taux_legal: number;
  total_reclame: number;
  decompte: DecompteLigne[];
  actes: RecouvrementActe[];
  relances: Relance[];
}

export interface Mise19_2 {
  lignes: DecompteLigne[];
  total: number;
  arriere_echu: number;
  exercice: number | null;
}


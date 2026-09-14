from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, field_validator


# ---------- Auth / Users ----------
class RegisterRequest(BaseModel):
    email: str
    password: str
    nom: str
    prenom: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _valider_email(v) -> str:
    v = (v or "").strip()
    if "@" not in v or v.startswith("@") or v.endswith("@") or " " in v:
        raise ValueError("email invalide")
    return v


def _valider_role(v) -> str:
    if v not in ("syndic", "membre"):
        raise ValueError("rôle invalide (syndic | membre)")
    return v


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    nom: str
    prenom: str = ""
    role: str
    adresse: str = ""  # coordonnées du copropriétaire (Réglages → Mes informations)
    telephone: str = ""
    two_factor_enabled: bool = False  # propriété du modèle User (totp_enabled)
    theme: str = "system"  # light | dark | system

    @field_validator("prenom", "adresse", "telephone", mode="before")
    @classmethod
    def _colonnes_none(cls, v):
        """Colonnes ajoutées par ALTER TABLE : NULL sur les lignes existantes."""
        return "" if v is None else v

    @field_validator("theme", mode="before")
    @classmethod
    def _theme_none(cls, v):
        """Colonne ajoutée par ALTER TABLE : NULL sur les lignes existantes."""
        return "system" if v is None else v


class ThemeIn(BaseModel):
    theme: str

    @field_validator("theme")
    @classmethod
    def _theme_valide(cls, v):
        if v not in ("light", "dark", "system"):
            raise ValueError("thème invalide (light | dark | system)")
        return v


class UserCreate(BaseModel):
    email: str
    password: str
    nom: str
    prenom: str = ""
    role: str = "membre"
    adresse: str = ""
    telephone: str = ""

    @field_validator("email")
    @classmethod
    def _email_ok(cls, v):
        return _valider_email(v)

    @field_validator("role")
    @classmethod
    def _role_ok(cls, v):
        return _valider_role(v)

    @field_validator("nom")
    @classmethod
    def _nom_ok(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("le nom est requis")
        return v

    @field_validator("password")
    @classmethod
    def _mdp_ok(cls, v):
        if len(v or "") < 6:
            raise ValueError("mot de passe trop court (6 caractères minimum)")
        return v


class UserUpdate(BaseModel):
    """Édition d'une fiche de compte (Réglages → Comptes utilisateurs)."""
    email: str
    nom: str
    prenom: str = ""
    role: str = "membre"
    adresse: str = ""
    telephone: str = ""
    # Nouveau mot de passe facultatif : absent/vide = mot de passe conservé.
    password: Optional[str] = None

    @field_validator("email")
    @classmethod
    def _email_ok(cls, v):
        return _valider_email(v)

    @field_validator("role")
    @classmethod
    def _role_ok(cls, v):
        return _valider_role(v)

    @field_validator("nom")
    @classmethod
    def _nom_ok(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("le nom est requis")
        return v

    @field_validator("password")
    @classmethod
    def _mdp_ok(cls, v):
        if v is None or not v.strip():
            return None  # laisser vide = conserver le mot de passe actuel
        if len(v) < 6:
            raise ValueError("mot de passe trop court (6 caractères minimum)")
        return v


# ---------- Copropriete ----------
class CoproOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nom: str
    adresse: str = ""
    ville: str = ""
    code_postal: str = ""
    annee_construction: Optional[int] = None
    regles_pays: str = "FR"
    devise: str = "EUR"
    fonds_travaux_actif: bool = True
    fonds_travaux_taux_pct: float = 5.0
    fonds_travaux_compte: str = ""
    compte_bancaire_separe: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    # smtp_password volontairement absent : le secret ne sort jamais du backend
    # (voir issue GitHub « chiffrement SMTP »)
    email_expediteur: str = ""
    frontend_url: str = ""
    relance_auto: bool = False
    relance_frequence: str = "hebdo"
    relance_jour: int = 1
    relance_heure: str = "09:00"
    relance_minimum: float = 0.0
    taux_legal_retard: float = 0.0  # intérêts de retard de recouvrement (%)

    @field_validator("taux_legal_retard", mode="before")
    @classmethod
    def _taux_none(cls, v):
        """Colonne ajoutée par ALTER TABLE : NULL sur les lignes existantes."""
        return 0.0 if v is None else v
    totp_policy: str = "off"  # double authentification : off | syndic | all

    @field_validator("totp_policy", mode="before")
    @classmethod
    def _totp_policy_jamais_none(cls, v):
        # Copropriétés créées avant la 2FA : NULL en base (NULL ≡ « off ») —
        # ne jamais renvoyer None (ResponseValidationError → 500 sur /api/copro).
        return v or "off"

    notes: str = ""


class CoproCreate(BaseModel):
    """Création d'une nouvelle copropriété (multi-copro)."""
    nom: str
    adresse: str = ""
    ville: str = ""
    code_postal: str = ""
    annee_construction: Optional[int] = None


class CoproUpdate(BaseModel):
    nom: Optional[str] = None
    adresse: Optional[str] = None
    ville: Optional[str] = None
    code_postal: Optional[str] = None
    annee_construction: Optional[int] = None
    fonds_travaux_actif: Optional[bool] = None
    fonds_travaux_taux_pct: Optional[float] = None
    fonds_travaux_compte: Optional[str] = None
    compte_bancaire_separe: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    email_expediteur: Optional[str] = None
    frontend_url: Optional[str] = None
    relance_auto: Optional[bool] = None
    relance_frequence: Optional[str] = None
    relance_jour: Optional[int] = None
    relance_heure: Optional[str] = None
    relance_minimum: Optional[float] = None
    taux_legal_retard: Optional[float] = None
    totp_policy: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("totp_policy")
    @classmethod
    def _valider_totp_policy(cls, v):
        if v is not None and v not in ("off", "syndic", "all"):
            raise ValueError("politique 2FA invalide (off | syndic | all)")
        return v


# ---------- Profil (auto-édition du copropriétaire) ----------
class ProfilIn(BaseModel):
    """Réglages → « Mes informations » : chacun modifie ses propres
    coordonnées (prénom, nom, email de connexion, adresse, téléphone)."""
    prenom: str = ""
    nom: str
    email: str
    adresse: str = ""
    telephone: str = ""

    @field_validator("email")
    @classmethod
    def _email_ok(cls, v):
        return _valider_email(v)

    @field_validator("nom")
    @classmethod
    def _nom_ok(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("le nom est requis")
        return v

    @field_validator("adresse", "telephone", mode="before")
    @classmethod
    def _none_vide(cls, v):
        return "" if v is None else v


# ---------- Lots ----------
class LotIn(BaseModel):
    numero: str
    designation: str = ""
    type: str = "appartement"
    tantiemes: int = 0
    surface_m2: Optional[float] = None
    # Propriétaire = un COMPTE UTILISATEUR de la copropriété (modèle « zéro fiche »).
    proprietaire_id: Optional[int] = None
    # "" = non renseigné | "occupant" (le propriétaire occupe son logement)
    # | "loue" | "vacant" — jamais de nom de locataire (RGPD).
    statut_occupation: str = ""
    notes: str = ""

    @field_validator("statut_occupation")
    @classmethod
    def _statut_ok(cls, v):
        if v not in ("", "occupant", "loue", "vacant"):
            raise ValueError("statut d'occupation invalide ('' | occupant | loue | vacant)")
        return v


class LotOut(LotIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    # Enrichissements (GET/POST/PUT renseignés par _lots_out) :
    proprietaire_nom: str = ""  # « Prénom Nom » du compte propriétaire
    proprietaire_occupant: bool = False  # DÉRIVÉ : statut_occupation == "occupant"


class ProprietaireOut(BaseModel):
    """Compte propriétaire (vue publique : nom pour les états de soldes)."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    prenom: str = ""
    nom: str = ""


class OccupationIn(BaseModel):
    """Occupation d'un lot déclarée par son propriétaire (ou le syndic)."""
    statut_occupation: str = ""

    @field_validator("statut_occupation")
    @classmethod
    def _statut_ok(cls, v):
        if v not in ("", "occupant", "loue", "vacant"):
            raise ValueError("statut d'occupation invalide ('' | occupant | loue | vacant)")
        return v


class LotSolde(BaseModel):
    lot: LotOut
    proprietaire: Optional[ProprietaireOut] = None
    total_appels: float = 0.0
    total_appels_fonds: float = 0.0
    total_encaisse: float = 0.0
    solde: float = 0.0


# ---------- Exercices / budget ----------
class ExerciceIn(BaseModel):
    annee: int
    cloture: bool = False


class BudgetLineIn(BaseModel):
    libelle: str
    montant: float = 0.0
    type_repartition: str = "generale"


class BudgetLineOut(BudgetLineIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ExerciceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    annee: int
    cloture: bool = False
    budget_total: float = 0.0


# ---------- Appels de fonds ----------
class AppelIn(BaseModel):
    libelle: str
    date_emission: date
    date_echeance: Optional[date] = None
    montant_total: float = 0.0
    inclut_fonds_travaux: bool = False


class AppelLotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lot_id: int
    lot_numero: str = ""
    montant_charges: float = 0.0
    montant_fonds_travaux: float = 0.0


class AppelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exercice_id: int
    libelle: str
    date_emission: date
    date_echeance: Optional[date] = None
    montant_total: float = 0.0
    inclut_fonds_travaux: bool = False
    fonds_travaux_montant: float = 0.0
    parts: List[AppelLotOut] = []


# ---------- Mouvements ----------
class MouvementIn(BaseModel):
    date: date
    libelle: str
    type: str  # encaissement | depense
    categorie: str = "autre"
    montant: float = 0.0
    lot_id: Optional[int] = None
    appel_id: Optional[int] = None


class MouvementOut(MouvementIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    piece_path: str = ""


# ---------- Etat daté / récap ----------
class EtatDateLot(BaseModel):
    lot: LotOut
    appels_charges: float = 0.0
    appels_fonds: float = 0.0
    encaisse: float = 0.0
    solde: float = 0.0


class RecapOut(BaseModel):
    exercice_id: int
    annee: int
    budget_previsionnel: float = 0.0
    encaisse: float = 0.0
    depense: float = 0.0
    solde_caisse: float = 0.0
    fonds_travaux_encaisse: float = 0.0
    appels_en_cours: int = 0
    lots: List[EtatDateLot] = []
    nb_lots: int = 0
    regime_petite_copro: bool = True  # art. 41-8 : ≤ 5 lots ou budget moyen < 15 000 €/an


# ---------- AG / résolutions ----------
class AGIn(BaseModel):
    date: date
    heure: str = ""
    type_ag: str = "annuelle"
    statut: str = "projet"
    lieu: str = ""
    notes: str = ""
    rappel_jours: int = 15  # envoi auto de la convocation N jours avant (0 = désactivé)


class VoteIn(BaseModel):
    lot_id: int
    voix: str  # pour | contre | abstention | null


class ResolutionIn(BaseModel):
    numero: int = 1
    libelle: str
    texte: str = ""
    majorite: str = "art24"


class ResolutionResult(BaseModel):
    statut: str
    pour: float = 0.0
    contre: float = 0.0
    abstention: float = 0.0
    total: float = 0.0
    quorum: float = 0.0
    regime_deux: bool = False
    detail: str = ""


class VoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lot_id: int
    voix: str


class ResolutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ag_id: int
    numero: int
    libelle: str
    texte: str = ""
    majorite: str = "art24"
    statut: str = "a_voter"
    votes: List[VoteOut] = []
    resultat: Optional[ResolutionResult] = None


class AGOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    date: date
    heure: Optional[str] = ""
    type_ag: str = "annuelle"
    statut: str = "projet"
    lieu: str = ""
    notes: str = ""
    rappel_jours: int = 15
    convocation_envoyee: bool = False
    resolutions: List[ResolutionOut] = []


# ---------- Sondage de dates (Doodle) ----------
class CreneauIn(BaseModel):
    debut: datetime
    fin: Optional[datetime] = None


class CreneauVoteIn(BaseModel):
    lot_id: int
    dispo: bool = True


class CreneauVoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lot_id: int
    lot_numero: str = ""
    dispo: bool = True


class CreneauOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    debut: datetime
    fin: Optional[datetime] = None
    votes: List[CreneauVoteOut] = []


# ---------- Invitations ----------
class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    personne_nom: str = ""
    personne_email: str = ""
    date_envoi: datetime
    statut: str = "envoye"
    message: str = ""


class InvitationsResult(BaseModel):
    envoyes: int
    sans_email: int
    erreurs: List[str] = []


# ---------- Relances d'impayés ----------
class RelanceLotOut(BaseModel):
    lot_id: int
    lot_numero: str = ""
    personne_id: Optional[int] = None
    personne_nom: str = ""
    personne_email: str = ""
    appels_charges: float = 0.0
    appels_fonds: float = 0.0
    encaisse: float = 0.0
    solde: float = 0.0


class RelanceEnvoiIn(BaseModel):
    lot_ids: List[int] = []


class RelanceOut(BaseModel):
    id: int
    lot_id: int
    lot_numero: str = ""
    personne_nom: str = ""
    personne_email: str = ""
    date_envoi: datetime
    statut: str = "envoye"
    montant_du: float = 0.0
    message: str = ""


# ---------- Contacts ----------
class ContactIn(BaseModel):
    nom: str
    type: str = "entreprise"
    categorie: str = "autres"
    telephone: str = ""
    email: str = ""
    adresse: str = ""
    site_web: str = ""
    notes: str = ""


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nom: str
    type: str = "entreprise"
    categorie: str = "autres"
    telephone: str = ""
    email: str = ""
    adresse: str = ""
    site_web: str = ""
    notes: str = ""


# ---------- Contrats ----------
class ContratIn(BaseModel):
    libelle: str
    type: str = "autres"
    reference: str = ""
    contact_id: Optional[int] = None
    date_debut: str = ""
    date_fin: str = ""
    montant: float = 0.0
    periode: str = "annuel"
    renouvellement_auto: bool = False
    notes: str = ""


class ContratOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    libelle: str
    type: str = "autres"
    reference: str = ""
    contact_id: Optional[int] = None
    contact_nom: str = ""
    date_debut: str = ""
    date_fin: str = ""
    montant: float = 0.0
    periode: str = "annuel"
    renouvellement_auto: bool = False
    notes: str = ""
    statut: str = "actif"  # actif, expire_bientot, expire
    jours_restants: Optional[int] = None


# ---------- Plan pluriannuel de travaux ----------
class TravauxIn(BaseModel):
    libelle: str
    categorie: str = "autres"
    annee: int
    montant: float = 0.0
    statut: str = "planifie"
    notes: str = ""


class TravauxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    libelle: str
    categorie: str = "autres"
    annee: int
    montant: float = 0.0
    statut: str = "planifie"
    notes: str = ""


# ---------- SMTP ----------
class SmtpConfigIn(BaseModel):
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    email_expediteur: Optional[str] = None
    frontend_url: Optional[str] = None


class SmtpTestResult(BaseModel):
    ok: bool
    detail: str = ""


# ---------- Documents ----------
class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    categorie: str = "autre"
    libelle: str
    fichier: str = ""
    date_ajout: date


# ---------- Carnet d'entretien ----------
class EntretienIn(BaseModel):
    date: date
    type_intervention: str = ""
    prestataire: str = ""
    cout: float = 0.0
    lot_id: Optional[int] = None
    description: str = ""


class EntretienOut(EntretienIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- Sécurité : 2FA + journal d'audit ----------
class LoginResponse(BaseModel):
    """Réponse du login : soit un jeton complet, soit une étape 2FA à poursuivre."""
    access_token: Optional[str] = None
    token_type: str = "bearer"
    two_factor_required: bool = False  # saisir un code (TOTP ou code de secours)
    must_enroll_2fa: bool = False      # la politique exige l'activation de la 2FA
    challenge_token: Optional[str] = None


class TwoFactorSetupOut(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str  # data:image/svg+xml;base64,...


class TwoFactorVerifyIn(BaseModel):
    code: str


class TwoFactorVerifyOut(BaseModel):
    ok: bool = True
    recovery_codes: List[str] = []
    access_token: Optional[str] = None
    token_type: str = "bearer"


class TwoFactorRecoveryOut(BaseModel):
    recovery_codes: List[str] = []


class TwoFactorVerifyLoginIn(BaseModel):
    challenge_token: str
    code: str


class TwoFactorDisableIn(BaseModel):
    password: str
    code: str


class TwoFactorRecoveryIn(BaseModel):
    password: str
    code: str


class TwoFactorStatusOut(BaseModel):
    enabled: bool
    recovery_codes_left: int = 0
    policy: str = "off"
    required: bool = False


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    user_email: str = ""
    user_nom: str = ""
    action: str = ""
    detail: str = ""
    ip: str = ""


# ---------- Instance (profil d'exposition) ----------
class DiagnosticItem(BaseModel):
    id: str
    label: str
    statut: str = "ignore"  # ok | attention | echec | ignore
    detail: str = ""


class DiagnosticOut(BaseModel):
    checked_at: datetime
    results: List[DiagnosticItem] = []


class InstanceOut(BaseModel):
    mode: str = "local"  # local | vps | maison
    public_url: str = ""
    first_external_at: Optional[datetime] = None
    last_check_at: Optional[datetime] = None
    last_check: List[DiagnosticItem] = []
    exposed_unprotected: bool = False
    https_active: bool = False
    version: str = ""


class InstanceUpdate(BaseModel):
    mode: str = "local"
    public_url: str = ""

    @field_validator("mode")
    @classmethod
    def _valider_mode(cls, v):
        if v not in ("local", "vps", "maison"):
            raise ValueError("mode invalide (local | vps | maison)")
        return v

    @field_validator("public_url")
    @classmethod
    def _valider_url(cls, v):
        v = (v or "").strip()
        if v and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("l'URL publique doit commencer par http:// ou https://")
        return v


# ---------- Recouvrement ----------
class RecouvrementLotOut(BaseModel):
    lot_id: int
    lot_numero: str
    personne_id: Optional[int] = None
    personne_nom: str = ""
    personne_email: str = ""
    solde: float = 0.0
    retard_depuis: Optional[date] = None
    statut: str = "a_jour"
    statut_label: str = ""
    md_date: Optional[date] = None
    md_jours: Optional[int] = None
    jours_restants: Optional[int] = None
    frais_total: float = 0.0
    interets: float = 0.0
    total_reclame: float = 0.0


class DecompteLigne(BaseModel):
    exercice: Optional[int] = None
    libelle: str = ""
    echeance: Optional[date] = None
    charges: float = 0.0
    fonds: float = 0.0
    montant: float = 0.0
    restant_du: float = 0.0
    echu: bool = False


class RecouvrementActeOut(BaseModel):
    id: int
    type: str
    date_acte: datetime
    date_envoi: Optional[date] = None
    mode_envoi: str = ""
    reference: str = ""
    montant: float = 0.0
    libelle: str = ""
    auteur: str = ""


class RecouvrementActeIn(BaseModel):
    type: str
    date_envoi: Optional[date] = None
    mode_envoi: str = ""
    reference: str = ""
    montant: float = 0.0
    libelle: str = ""


class RecouvrementDossierOut(BaseModel):
    lot_id: int
    lot_numero: str
    personne_nom: str = ""
    personne_email: str = ""
    personne_adresse: str = ""
    solde: float = 0.0
    arriere_echu: float = 0.0
    retard_depuis: Optional[date] = None
    statut: str = "a_jour"
    statut_label: str = ""
    md_date: Optional[date] = None
    md_jours: Optional[int] = None
    jours_restants: Optional[int] = None
    frais_total: float = 0.0
    interets: float = 0.0
    taux_legal: float = 0.0
    total_reclame: float = 0.0
    decompte: List[DecompteLigne] = []
    actes: List[RecouvrementActeOut] = []
    relances: List[RelanceOut] = []


class Mise19_2Out(BaseModel):
    lignes: List[DecompteLigne] = []
    total: float = 0.0
    arriere_echu: float = 0.0
    exercice: Optional[int] = None

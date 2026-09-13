/**
 * Thème d'affichage (clair / sombre / système).
 *
 * - La préférence est stockée par compte (colonne `users.theme`) et mise en
 *   cache dans `localStorage` (`copro_theme`) pour un rendu immédiat, y compris
 *   sur la page de connexion (voir aussi le script inline dans index.html qui
 *   applique la classe avant le premier rendu, sans flash).
 * - En mode « système », on suit `prefers-color-scheme` en direct.
 * - Le rendu sombre lui-même vit dans index.css : surcharges des utilitaires
 *   Tailwind sous `html.dark`.
 */
export type Theme = "light" | "dark" | "system";

const KEY = "copro_theme";

export function normalizeTheme(value: unknown): Theme {
  return value === "light" || value === "dark" || value === "system" ? value : "system";
}

export function getStoredTheme(): Theme {
  try {
    return normalizeTheme(localStorage.getItem(KEY));
  } catch {
    return "system";
  }
}

function systemPrefersDark(): boolean {
  try {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  } catch {
    return false;
  }
}

export function isDark(theme: Theme): boolean {
  return theme === "dark" || (theme === "system" && systemPrefersDark());
}

/** Applique le thème (et le met en cache localement si `persist`). */
export function applyTheme(theme: Theme, persist = true): void {
  if (persist) {
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* stockage indisponible : thème appliqué pour la session seulement */
    }
  }
  document.documentElement.classList.toggle("dark", isDark(theme));
}

let wired = false;

/** À appeler une fois au démarrage : applique le thème + écoute le système. */
export function initTheme(): void {
  applyTheme(getStoredTheme(), false);
  if (!wired) {
    wired = true;
    try {
      window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
        if (getStoredTheme() === "system") applyTheme("system", false);
      });
    } catch {
      /* vieux moteurs : pas d'écoute — le thème sera réévalué au chargement */
    }
  }
}

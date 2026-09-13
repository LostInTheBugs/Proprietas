import { createContext, useContext, useEffect, useState } from "react";
import { api, getToken } from "./api";
import { applyTheme, normalizeTheme } from "./theme";
import type { User } from "./types";

const UserContext = createContext<{ user: User | null; refresh: () => void }>({
  user: null,
  refresh: () => {},
});

export function UserProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);

  function charger() {
    if (!getToken()) return;
    api
      .get<User>("/auth/me")
      .then((u) => {
        setUser(u);
        // La préférence de thème du compte remplace celle mise en cache local.
        applyTheme(normalizeTheme(u.theme));
      })
      .catch(() => {});
  }

  useEffect(() => {
    // Sans token (page de login), ne PAS appeler /auth/me : le 401 déclencherait
    // une redirection → rechargement → boucle infinie.
    charger();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <UserContext.Provider value={{ user, refresh: charger }}>{children}</UserContext.Provider>;
}

export function useUser() {
  return useContext(UserContext);
}

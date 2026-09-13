import { createContext, useContext, useEffect, useState } from "react";
import { api } from "./api";
import { applyTheme, normalizeTheme } from "./theme";
import type { User } from "./types";

const UserContext = createContext<{ user: User | null; pret: boolean; refresh: () => void }>({
  user: null,
  pret: false,
  refresh: () => {},
});

export function UserProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [pret, setPret] = useState(false);

  function charger() {
    // Sur la page de connexion, inutile d'appeler /auth/me (401 systématique) :
    // le login recharge la page en entier après avoir posé le cookie de session.
    if (window.location.pathname.startsWith("/login")) {
      setPret(true);
      return;
    }
    api
      .get<User>("/auth/me")
      .then((u) => {
        setUser(u);
        // La préférence de thème du compte remplace celle mise en cache local.
        applyTheme(normalizeTheme(u.theme));
      })
      .catch(() => setUser(null))
      .finally(() => setPret(true));
  }

  useEffect(() => {
    charger();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <UserContext.Provider value={{ user, pret, refresh: charger }}>{children}</UserContext.Provider>
  );
}

export function useUser() {
  return useContext(UserContext);
}

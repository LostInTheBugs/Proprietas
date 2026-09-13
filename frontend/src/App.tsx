import { Navigate, Route, Routes } from "react-router-dom";
import { useUser } from "./auth";
import { UserProvider } from "./auth";
import Login from "./pages/Login";
import Layout from "./pages/Layout";
import Dashboard from "./pages/Dashboard";
import Lots from "./pages/Lots";
import Comptes from "./pages/Comptes";
import Ag from "./pages/Ag";
import Documents from "./pages/Documents";
import Contacts from "./pages/Contacts";
import Contrats from "./pages/Contrats";
import Carnet from "./pages/Carnet";
import Settings from "./pages/Settings";
import Recouvrement from "./pages/Recouvrement";
import TravauxPage from "./pages/Travaux";
import Consolide from "./pages/Consolide";
import Securite from "./pages/Securite";

function RequireAuth({ children }: { children: React.ReactNode }) {
  // Session en cookie httpOnly : on ne peut pas la tester en JS — on rend la
  // main à /auth/me (UserProvider). Sans profil après vérification → /login
  // (et l'intercepteur 401 d'api.ts gère l'expiration en cours de session).
  const { user, pret } = useUser();
  if (!pret) return null;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <UserProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="lots" element={<Lots />} />
          <Route path="comptes" element={<Comptes />} />
          <Route path="ag" element={<Ag />} />
          <Route path="documents" element={<Documents />} />
          <Route path="contacts" element={<Contacts />} />
          <Route path="contrats" element={<Contrats />} />
          <Route path="carnet" element={<Carnet />} />
          <Route path="recouvrement" element={<Recouvrement />} />
          <Route path="relances" element={<Navigate to="/recouvrement" replace />} />
          <Route path="travaux" element={<TravauxPage />} />
          <Route path="consolide" element={<Consolide />} />
          <Route path="securite" element={<Securite />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </UserProvider>
  );
}

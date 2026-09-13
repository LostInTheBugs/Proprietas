import { useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { getToken } from "./api";
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
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  if (!ready) return null;
  if (!getToken()) return <Navigate to="/login" replace />;
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

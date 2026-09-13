import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { installDesktopDownloadBridge } from "./desktop";
import { initTheme } from "./theme";
import "./index.css";

// Thème (clair / sombre / système) appliqué avant le premier rendu React.
initTheme();

// Version de bureau (Windows) : exports PDF/CSV via « Enregistrer sous » natif.
installDesktopDownloadBridge();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);

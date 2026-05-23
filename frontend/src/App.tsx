/**
 * Application shell.
 *
 * Mounts the navy top bar (with theme toggle), the accent gradient strip,
 * the active page, and the dark footer. All page content lives below the
 * sticky nav.
 */

import { useState } from "react";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { ModelsPage } from "./pages/ModelsPage";
import { SessionPage } from "./pages/SessionPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TopBar, type TopBarPage } from "./components/TopBar";
import { useThemeStore } from "./stores/themeStore";

export default function App() {
  const [page, setPage] = useState<TopBarPage>("session");
  const { theme, toggle } = useThemeStore();

  return (
    <div className="shell">
      <TopBar
        page={page}
        onPage={setPage}
        theme={theme}
        onToggleTheme={toggle}
        user={{ initials: "OP", name: "Octavio Perez", role: "Data & AI Strategy" }}
      />
      <div className="accent-bar" />

      {page === "session"   && <SessionPage />}
      {page === "analytics" && <AnalyticsPage />}

      {page === "models" && <ModelsPage />}
      {page === "settings" && <SettingsPage />}

      <footer className="foot">
        <div>
          OPB · Octavio Pérez Bravo · <em>TrustSignal AI</em>
        </div>
        <div>
          {new Date()
            .toLocaleDateString("en-US", { year: "numeric", month: "long" })
            .toUpperCase()}{" "}
          · Confidential
        </div>
      </footer>
    </div>
  );
}

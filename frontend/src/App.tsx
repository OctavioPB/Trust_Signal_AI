import { useState } from "react";
import { useThemeStore } from "./stores/themeStore";

type Page = "session" | "settings";

export default function App() {
  const [page, setPage] = useState<Page>("session");
  const theme = useThemeStore((s) => s.theme);

  const containerStyle: React.CSSProperties = {
    minHeight: "100vh",
    backgroundColor: "var(--light)",
    fontFamily: "var(--fb)",
    color: "var(--dark)",
  };

  const navStyle: React.CSSProperties = {
    background: "rgba(0,51,102,0.97)",
    backdropFilter: "blur(12px)",
    height: 52,
    position: "sticky",
    top: 0,
    zIndex: 100,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "0 40px",
    borderBottom: "1px solid rgba(255,255,255,0.08)",
  };

  const navCenterStyle: React.CSSProperties = {
    fontFamily: "var(--fb)",
    fontSize: 9,
    letterSpacing: "3px",
    textTransform: "uppercase",
    color: "rgba(255,255,255,0.4)",
  };

  const navRightStyle: React.CSSProperties = { display: "flex", gap: 8, alignItems: "center" };

  const navLinkBase: React.CSSProperties = {
    background: "none",
    border: "none",
    color: "rgba(255,255,255,0.45)",
    cursor: "pointer",
    fontFamily: "var(--fb)",
    fontSize: 9,
    letterSpacing: "2px",
    textTransform: "uppercase",
    padding: "5px 8px",
    borderRadius: 6,
    transition: "color 0.15s",
  };

  const navLinkActive: React.CSSProperties = {
    color: "var(--gold-light)",
    backgroundColor: "rgba(201,168,76,0.12)",
  };

  // theme variable referenced to avoid unused-variable TS error; applied via data-theme attr on <html>
  void theme;

  return (
    <div style={containerStyle}>
      <nav style={navStyle}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <span style={{ fontFamily: "'Fraunces', Georgia, serif", fontSize: 20, fontWeight: 300, color: "#ffffff" }}>
            O
          </span>
          <em style={{ fontFamily: "'Fraunces', Georgia, serif", fontSize: 20, fontWeight: 300, fontStyle: "italic", color: "var(--gold-light)" }}>
            PB
          </em>
        </div>

        <span style={navCenterStyle}>TrustSignal AI</span>

        <div style={navRightStyle}>
          <button
            style={page === "session" ? { ...navLinkBase, ...navLinkActive } : navLinkBase}
            onClick={() => setPage("session")}
          >
            Session
          </button>
          <button
            style={page === "settings" ? { ...navLinkBase, ...navLinkActive } : navLinkBase}
            onClick={() => setPage("settings")}
          >
            Settings
          </button>
        </div>
      </nav>

      <main>
        {(() => {
          switch (page) {
            case "session":
              return (
                <div style={{ padding: "40px 48px" }}>
                  <p style={{ fontFamily: "var(--fb)", color: "var(--mid)", fontSize: 14 }}>
                    Session view — coming in Sprint 12.
                  </p>
                </div>
              );
            case "settings":
              return (
                <div style={{ padding: "40px 48px" }}>
                  <p style={{ fontFamily: "var(--fb)", color: "var(--mid)", fontSize: 14 }}>
                    Settings — coming in Sprint 12.
                  </p>
                </div>
              );
          }
        })()}
      </main>

      <footer
        style={{
          backgroundColor: "var(--primary)",
          padding: "20px 48px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontFamily: "var(--fb)",
          fontSize: 9,
          letterSpacing: "3px",
          textTransform: "uppercase",
          color: "rgba(255,255,255,0.4)",
        }}
      >
        <span>OPB · Octavio Pérez Bravo · TrustSignal AI</span>
        <span>
          {new Date()
            .toLocaleDateString("en-US", { year: "numeric", month: "long" })
            .toUpperCase()}
        </span>
      </footer>
    </div>
  );
}

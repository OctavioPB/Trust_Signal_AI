import { useState } from "react";
import { SessionPage } from "./pages/SessionPage";
import { useThemeStore } from "./stores/themeStore";

type Page = "session" | "settings";

export default function App() {
  const [page, setPage] = useState<Page>("session");
  const { theme, toggle } = useThemeStore();

  const nav: React.CSSProperties = {
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
    flexShrink: 0,
  };

  const linkBase: React.CSSProperties = {
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

  const linkActive: React.CSSProperties = {
    color: "var(--gold-light)",
    backgroundColor: "rgba(201,168,76,0.12)",
  };

  const footer: React.CSSProperties = {
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
    flexShrink: 0,
  };

  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      flexDirection: "column",
      backgroundColor: "var(--light)",
      fontFamily: "var(--fb)",
      color: "var(--dark)",
    }}>
      {/* ── Nav ────────────────────────────────────────────────────── */}
      <nav style={nav}>
        <span>
          <span style={{ fontFamily: "'Fraunces', Georgia, serif", fontSize: 20, fontWeight: 300, color: "#ffffff" }}>O</span>
          <em style={{ fontFamily: "'Fraunces', Georgia, serif", fontSize: 20, fontWeight: 300, fontStyle: "italic", color: "var(--gold-light)" }}>PB</em>
        </span>

        <span style={{ fontFamily: "var(--fb)", fontSize: 9, letterSpacing: "3px", textTransform: "uppercase", color: "rgba(255,255,255,0.4)" }}>
          TrustSignal AI &mdash; Recruiter Dashboard
        </span>

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            style={page === "session" ? { ...linkBase, ...linkActive } : linkBase}
            onClick={() => setPage("session")}
          >
            Session
          </button>
          <button
            style={page === "settings" ? { ...linkBase, ...linkActive } : linkBase}
            onClick={() => setPage("settings")}
          >
            Settings
          </button>
          <div style={{ width: 1, height: 16, backgroundColor: "rgba(255,255,255,0.15)", margin: "0 4px" }} />
          <button style={linkBase} onClick={toggle} title="Toggle theme">
            {theme === "light" ? "◑" : "○"}
          </button>
        </div>
      </nav>

      {/* ── Page content (grows to push footer down) ─────────────── */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        {page === "session" && <SessionPage />}
        {page === "settings" && (
          <div style={{ maxWidth: 1300, margin: "0 auto", padding: "64px 48px", width: "100%", boxSizing: "border-box" }}>
            <p style={{ fontFamily: "var(--fb)", color: "var(--mid)", fontSize: 14 }}>
              Settings — coming soon.
            </p>
          </div>
        )}
      </div>

      {/* ── Footer ─────────────────────────────────────────────────── */}
      <footer style={footer}>
        <span>OPB · Octavio Pérez Bravo · TrustSignal AI</span>
        <span>{new Date().toLocaleDateString("en-US", { year: "numeric", month: "long" }).toUpperCase()}</span>
      </footer>
    </div>
  );
}

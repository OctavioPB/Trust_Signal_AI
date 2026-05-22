/**
 * Left sidebar: API inputs, Load Session / Load Demo buttons,
 * live-polling toggle, and dark/light theme toggle.
 *
 * BRAND.md: navy background (var(--primary)), white/gold text.
 */

import { useThemeStore } from "../stores/themeStore";

interface Props {
  apiUrl: string;
  recruiterId: string;
  sessionId: string;
  polling: boolean;
  loading: boolean;
  onApiUrlChange: (v: string) => void;
  onRecruiterIdChange: (v: string) => void;
  onSessionIdChange: (v: string) => void;
  onLoadSession: () => void;
  onLoadDemo: () => void;
  onPollingToggle: () => void;
}

const sidebar: React.CSSProperties = {
  width: 260,
  flexShrink: 0,
  backgroundColor: "var(--primary)",
  backgroundImage: `
    linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px)
  `,
  backgroundSize: "48px 48px",
  padding: "28px 20px",
  display: "flex",
  flexDirection: "column",
  gap: 20,
  minHeight: "calc(100vh - 52px)",
};

const sectionLabel: React.CSSProperties = {
  fontFamily: "var(--fb)",
  fontSize: 8,
  fontWeight: 700,
  letterSpacing: "3px",
  textTransform: "uppercase",
  color: "rgba(255,255,255,0.35)",
  marginBottom: 8,
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  backgroundColor: "rgba(255,255,255,0.07)",
  border: "1px solid rgba(255,255,255,0.14)",
  borderRadius: 6,
  color: "rgba(255,255,255,0.85)",
  fontFamily: "var(--fb)",
  fontSize: 12,
  padding: "8px 10px",
  outline: "none",
};

const primaryBtn: React.CSSProperties = {
  width: "100%",
  padding: "9px 0",
  backgroundColor: "var(--gold)",
  border: "none",
  borderRadius: 8,
  color: "var(--primary)",
  fontFamily: "var(--fb)",
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: "1.5px",
  textTransform: "uppercase",
  cursor: "pointer",
};

const ghostBtn: React.CSSProperties = {
  width: "100%",
  padding: "8px 0",
  backgroundColor: "transparent",
  border: "1px solid rgba(255,255,255,0.2)",
  borderRadius: 8,
  color: "rgba(255,255,255,0.65)",
  fontFamily: "var(--fb)",
  fontSize: 11,
  fontWeight: 600,
  letterSpacing: "1.5px",
  textTransform: "uppercase",
  cursor: "pointer",
};

const divider: React.CSSProperties = {
  height: 1,
  backgroundColor: "rgba(255,255,255,0.08)",
};

export function Sidebar({
  apiUrl, recruiterId, sessionId, polling, loading,
  onApiUrlChange, onRecruiterIdChange, onSessionIdChange,
  onLoadSession, onLoadDemo, onPollingToggle,
}: Props) {
  const { theme, toggle } = useThemeStore();

  const pillStyle: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    backgroundColor: polling ? "rgba(39,185,124,0.15)" : "rgba(255,255,255,0.07)",
    border: `1px solid ${polling ? "var(--green)" : "rgba(255,255,255,0.14)"}`,
    borderRadius: 20,
    padding: "6px 14px",
    cursor: "pointer",
    fontFamily: "var(--fb)",
    fontSize: 10,
    fontWeight: 600,
    letterSpacing: "1.5px",
    textTransform: "uppercase",
    color: polling ? "var(--green)" : "rgba(255,255,255,0.5)",
    userSelect: "none",
  };

  const dotStyle: React.CSSProperties = {
    width: 7,
    height: 7,
    borderRadius: "50%",
    backgroundColor: polling ? "var(--green)" : "rgba(255,255,255,0.35)",
    animation: polling ? "pulse 1.4s ease-in-out infinite" : "none",
  };

  return (
    <aside style={sidebar}>
      {/* API connection */}
      <div>
        <div style={sectionLabel}>Connection</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <input
            style={inputStyle}
            placeholder="API base URL"
            value={apiUrl}
            onChange={e => onApiUrlChange(e.target.value)}
          />
          <input
            style={inputStyle}
            placeholder="Recruiter ID (UUID)"
            value={recruiterId}
            onChange={e => onRecruiterIdChange(e.target.value)}
          />
          <input
            style={inputStyle}
            placeholder="Session ID (UUID)"
            value={sessionId}
            onChange={e => onSessionIdChange(e.target.value)}
          />
        </div>
      </div>

      {/* Action buttons */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <button
          style={{ ...primaryBtn, opacity: loading ? 0.6 : 1 }}
          onClick={onLoadSession}
          disabled={loading}
        >
          {loading ? "Loading…" : "Load Session"}
        </button>
        <button style={ghostBtn} onClick={onLoadDemo}>
          Load Demo
        </button>
      </div>

      <div style={divider} />

      {/* Live polling toggle */}
      <div>
        <div style={sectionLabel}>Live Polling</div>
        <div style={pillStyle} onClick={onPollingToggle} role="button" aria-pressed={polling}>
          <span style={dotStyle} />
          {polling ? "Live" : "Paused"}
        </div>
        <p style={{ fontFamily: "var(--fb)", fontSize: 10, color: "rgba(255,255,255,0.3)", marginTop: 6, lineHeight: 1.5 }}>
          Refreshes score every 10 s while session is live.
        </p>
      </div>

      <div style={divider} />

      {/* Theme toggle */}
      <div>
        <div style={sectionLabel}>Appearance</div>
        <button
          style={ghostBtn}
          onClick={toggle}
        >
          {theme === "light" ? "◑ Dark Mode" : "○ Light Mode"}
        </button>
      </div>

      {/* Pulse animation */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.3; }
        }
      `}</style>
    </aside>
  );
}

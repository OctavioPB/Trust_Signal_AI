/**
 * Application top bar.
 *
 * - OPB monogram on the left ("O*PB*" — italic gold for the PB).
 * - Product wordmark ("TrustSignal AI") sits next to it.
 * - Page tabs in the centre/right; theme toggle; recruiter chip on far right.
 * - Recruiter chip is interactive: click opens a dropdown with profile info,
 *   quick nav to Settings, theme toggle, and sign-out.
 *
 * Always navy; not affected by the dark-theme toggle (per BRAND.md §Nav).
 */

import { useState, useEffect, useRef } from "react";

export type TopBarPage = "session" | "analytics" | "models" | "settings" | "info";

interface Props {
  page: TopBarPage;
  onPage: (p: TopBarPage) => void;
  onToggleTheme: () => void;
  theme: "light" | "dark";
  user?: { initials: string; name: string; role: string };
}

const LINKS: { key: TopBarPage; label: string }[] = [
  { key: "session",   label: "Sessions"  },
  { key: "analytics", label: "Analytics" },
  { key: "models",    label: "Models"    },
  { key: "settings",  label: "Settings"  },
  { key: "info",      label: "Info"      },
];

// ── User chip + dropdown ──────────────────────────────────────────────────────

function UserChip({
  user, onPage, onToggleTheme, theme,
}: {
  user: { initials: string; name: string; role: string };
  onPage: (p: TopBarPage) => void;
  onToggleTheme: () => void;
  theme: "light" | "dark";
}) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const menuItem = (label: string, icon: string, onClick: () => void, danger = false) => (
    <button
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        width: "100%",
        padding: "9px 18px",
        background: "none",
        border: "none",
        cursor: "pointer",
        textAlign: "left",
        fontFamily: "var(--fb)",
        fontSize: 13,
        color: danger ? "var(--rojo)" : "var(--dark)",
        transition: "background 0.12s ease",
      }}
      onMouseEnter={e => (e.currentTarget.style.background = danger ? "var(--rojo-ice)" : "var(--primary-10)")}
      onMouseLeave={e => (e.currentTarget.style.background = "none")}
    >
      <span style={{ fontSize: 14, width: 18, textAlign: "center", flexShrink: 0 }}>{icon}</span>
      {label}
    </button>
  );

  return (
    <div ref={wrapperRef} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        aria-haspopup="true"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "6px 10px 6px 6px",
          borderRadius: 999,
          background: open ? "rgba(255,255,255,0.1)" : "rgba(255,255,255,0.05)",
          border: "1px solid rgba(255,255,255,0.12)",
          cursor: "pointer",
          transition: "background 0.15s ease",
        }}
      >
        <div style={{
          width: 28, height: 28, borderRadius: "50%",
          background: "linear-gradient(135deg, var(--gold), var(--gold-light))",
          color: "var(--primary)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontFamily: "var(--fd)", fontWeight: 600, fontSize: 13,
          flexShrink: 0,
        }}>
          {user.initials}
        </div>
        <div style={{ textAlign: "left" }}>
          <div style={{ fontSize: 12, fontWeight: 500, color: "rgba(255,255,255,0.85)", lineHeight: 1.2 }}>
            {user.name}
          </div>
          <div style={{ fontSize: 9, letterSpacing: "2px", textTransform: "uppercase", color: "rgba(255,255,255,0.4)", marginTop: 1 }}>
            {user.role}
          </div>
        </div>
        <span style={{
          fontSize: 10, color: "rgba(255,255,255,0.4)",
          marginLeft: 2,
          transform: open ? "rotate(180deg)" : "none",
          transition: "transform 0.2s ease",
          display: "inline-block",
        }}>
          ▾
        </span>
      </button>

      {open && (
        <div style={{
          position: "absolute",
          top: "calc(100% + 8px)",
          right: 0,
          minWidth: 232,
          backgroundColor: "var(--white)",
          borderRadius: 12,
          border: "1px solid var(--primary-10)",
          boxShadow: "0 8px 32px rgba(0,51,102,0.18)",
          overflow: "hidden",
          zIndex: 100,
        }}>
          {/* Profile header */}
          <div style={{
            padding: "16px 18px 14px",
            borderBottom: "1px solid var(--primary-10)",
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}>
            <div style={{
              width: 40, height: 40, borderRadius: "50%",
              background: "linear-gradient(135deg, var(--gold), var(--gold-light))",
              color: "var(--primary)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontFamily: "var(--fd)", fontWeight: 600, fontSize: 16,
              flexShrink: 0,
            }}>
              {user.initials}
            </div>
            <div>
              <div style={{ fontFamily: "var(--fb)", fontSize: 14, fontWeight: 600, color: "var(--dark)", lineHeight: 1.2 }}>
                {user.name}
              </div>
              <div style={{ fontFamily: "var(--fb)", fontSize: 10, letterSpacing: "1.5px", textTransform: "uppercase", color: "var(--mid)", marginTop: 2 }}>
                {user.role}
              </div>
            </div>
          </div>

          {/* Actions */}
          <div style={{ padding: "6px 0" }}>
            {menuItem("Settings", "⚙", () => { onPage("settings"); setOpen(false); })}
            {menuItem(
              theme === "light" ? "Dark mode" : "Light mode",
              theme === "light" ? "◑" : "○",
              () => { onToggleTheme(); },
            )}
          </div>

          {/* Sign out */}
          <div style={{ borderTop: "1px solid var(--primary-10)", padding: "6px 0" }}>
            {menuItem("Sign out", "→", () => setOpen(false), true)}
          </div>
        </div>
      )}
    </div>
  );
}

// ── TopBar ────────────────────────────────────────────────────────────────────

export function TopBar({ page, onPage, onToggleTheme, theme, user }: Props) {
  return (
    <div className="topbar">
      <span className="brand">O<em>PB</em></span>
      <span className="divider-v" />
      <span className="product">
        TrustSignal <em>AI</em>
      </span>

      <div className="spacer" />

      <div className="nav-links">
        {LINKS.map(({ key, label }) => (
          <button
            key={key}
            className={"nav-link" + (page === key ? " active" : "")}
            onClick={() => onPage(key)}
          >
            {label}
          </button>
        ))}
        <button
          className="nav-link"
          onClick={onToggleTheme}
          title="Toggle theme"
          aria-label="Toggle theme"
        >
          {theme === "light" ? "◑" : "○"}
        </button>
      </div>

      <span className="divider-v" />

      {user && (
        <UserChip
          user={user}
          onPage={onPage}
          onToggleTheme={onToggleTheme}
          theme={theme}
        />
      )}
    </div>
  );
}

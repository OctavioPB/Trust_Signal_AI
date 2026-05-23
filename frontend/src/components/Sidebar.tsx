/**
 * Recruiter rail (left sidebar).
 *
 * Restyled per OPB system: a white surface (not the old navy block), with
 * eyebrows, OPB inputs and buttons. Wraps the existing session-control props
 * 1:1 so this is a drop-in replacement for the old Sidebar.
 *
 * Once you have a real session-list endpoint, render it under the
 * "Recent Sessions" header below — see the placeholder.
 */

import { Eyebrow } from "./Eyebrow";

interface Props {
  recruiterId: string;
  sessionId: string;
  polling: boolean;
  loading: boolean;
  onRecruiterIdChange: (v: string) => void;
  onSessionIdChange: (v: string) => void;
  onLoadSession: () => void;
  onLoadDemo: () => void;
  onPollingToggle: () => void;
}

export function Sidebar({
  recruiterId,
  sessionId,
  polling,
  loading,
  onRecruiterIdChange,
  onSessionIdChange,
  onLoadSession,
  onLoadDemo,
  onPollingToggle,
}: Props) {
  return (
    <aside className="rail">
      {/* ── Identity ─────────────────────────────────────────────────── */}
      <div>
        <Eyebrow>Recruiter Console</Eyebrow>
        <h3 className="rail-product">
          Trust<em>Signal</em>
        </h3>
        <p className="rail-product-sub">
          Five-signal interview authenticity scoring.
        </p>
      </div>

      {/* ── Session credentials ─────────────────────────────────────── */}
      <div>
        <h4 className="rail-title">Session</h4>
        <div className="rail-fields">
          <label className="rail-field">
            <span className="rail-field-lbl">Recruiter ID</span>
            <input
              className="rail-input"
              placeholder="00000000-0000-0000-0000-…"
              value={recruiterId}
              onChange={(e) => onRecruiterIdChange(e.target.value)}
            />
          </label>
          <label className="rail-field">
            <span className="rail-field-lbl">Session ID</span>
            <input
              className="rail-input"
              placeholder="00000000-0000-0000-0000-…"
              value={sessionId}
              onChange={(e) => onSessionIdChange(e.target.value)}
            />
          </label>
        </div>
      </div>

      {/* ── Actions ──────────────────────────────────────────────────── */}
      <div className="rail-actions">
        <button
          className="btn btn-primary"
          onClick={onLoadSession}
          disabled={loading}
        >
          {loading ? "Loading…" : "Load Session"}
        </button>
        <button className="btn btn-ghost" onClick={onLoadDemo}>
          Load Demo
        </button>
      </div>

      {/* ── Live polling toggle ─────────────────────────────────────── */}
      <div>
        <h4 className="rail-title">Live Polling</h4>
        <button
          type="button"
          className={"rail-poll " + (polling ? "on" : "off")}
          onClick={onPollingToggle}
          aria-pressed={polling}
        >
          <span className="poll-dot" />
          {polling ? "Live · refreshing every 10 s" : "Paused"}
        </button>
        <p className="rail-hint">
          Refreshes the TrustScore and signal modules while the session is
          still live on the back-end.
        </p>
      </div>

      {/* ── TODO: real session list goes here ───────────────────────── */}
      {/*
       * <div>
       *   <h4 className="rail-title">Recent Sessions</h4>
       *   <ul className="session-list">
       *     {sessions.map(s => (
       *       <li key={s.id}>…</li>
       *     ))}
       *   </ul>
       * </div>
       */}
    </aside>
  );
}

/**
 * Candidates — pre-screening management page.
 *
 * Two-column layout: 260px candidate list + 1fr detail panel.
 * Status: pending (navy), screened (verde), flagged (rojo).
 * Score gauges use SVG arcs; signal bars use percentage widths.
 * All styling is inline CSS using design-token CSS variables.
 */

import { useState, useRef } from "react";
import type { CSSProperties, DragEvent } from "react";
import type { Candidate, CandidateSignal } from "../types";
import { useCandidatesStore } from "../stores/candidatesStore";
import { Eyebrow } from "../components/Eyebrow";

// ── Design helpers ─────────────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  pending:  "var(--primary)",
  screened: "var(--verde)",
  flagged:  "var(--rojo)",
};

const STATUS_BG: Record<string, string> = {
  pending:  "var(--primary-10)",
  screened: "#e6f9f1",
  flagged:  "#fdeced",
};

function scoreColor(score: number): string {
  if (score <= 33) return "var(--verde)";
  if (score <= 66) return "var(--gold)";
  return "var(--rojo)";
}

function shortUuid(uuid: string): string {
  return uuid.slice(0, 8).toUpperCase();
}

function formatTs(ts: number | null): string {
  if (ts === null) return "—";
  return new Date(ts * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

// ── Gauge ──────────────────────────────────────────────────────────────────────

function Gauge({ label, value }: { label: string; value: number | null }) {
  const size = 88;
  const stroke = 7;
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const pct = value === null ? 0 : Math.min(100, Math.max(0, value));
  const dash = (pct / 100) * circ;
  const color = value === null ? "var(--primary-10)" : scoreColor(pct);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ transform: "rotate(-90deg)" }}>
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke="var(--primary-10)" strokeWidth={stroke}
        />
        <circle
          cx={size / 2} cy={size / 2} r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circ}`}
          style={{ transition: "stroke-dasharray 0.6s ease" }}
        />
        <text
          x={size / 2} y={size / 2 + 5}
          textAnchor="middle"
          style={{ transform: `rotate(90deg)`, transformOrigin: `${size / 2}px ${size / 2}px` }}
          fill={value === null ? "var(--primary-30)" : "var(--dark)"}
          fontFamily="var(--fd)"
          fontSize={value === null ? 11 : 16}
          fontWeight={600}
        >
          {value === null ? "—" : Math.round(pct)}
        </text>
      </svg>
      <span style={{ fontFamily: "var(--fb)", fontSize: 10, letterSpacing: "1.2px", textTransform: "uppercase", color: "var(--mid)", textAlign: "center" }}>
        {label}
      </span>
    </div>
  );
}

// ── Signal bar ────────────────────────────────────────────────────────────────

function SignalBar({ signal }: { signal: CandidateSignal }) {
  const pct = Math.round(signal.raw_suspicion * 100);
  const color = scoreColor(pct);
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
        <span style={{ fontFamily: "var(--fb)", fontSize: 11, color: "var(--dark)", fontWeight: 500 }}>{signal.signal_name}</span>
        <span style={{ fontFamily: "var(--fb)", fontSize: 11, color, fontWeight: 600 }}>{pct}</span>
      </div>
      <div style={{ height: 5, background: "var(--primary-10)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 3, transition: "width 0.5s ease" }} />
      </div>
      <p style={{ fontFamily: "var(--fb)", fontSize: 10, color: "var(--mid)", marginTop: 3, lineHeight: 1.5 }}>
        {signal.explanation}
      </p>
    </div>
  );
}

// ── Candidate card ────────────────────────────────────────────────────────────

function CandidateCard({ candidate, selected, onClick }: {
  candidate: Candidate;
  selected: boolean;
  onClick: () => void;
}) {
  const bg    = selected ? "var(--primary)" : "var(--white)";
  const col   = selected ? "#ffffff" : "var(--dark)";
  const subCol = selected ? "rgba(255,255,255,0.6)" : "var(--mid)";

  return (
    <button
      onClick={onClick}
      style={{
        display: "block",
        width: "100%",
        textAlign: "left",
        padding: "12px 14px",
        background: bg,
        border: selected ? "1.5px solid var(--primary)" : "1.5px solid var(--primary-10)",
        borderRadius: 10,
        cursor: "pointer",
        transition: "all 0.15s ease",
        marginBottom: 6,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6 }}>
        <code style={{ fontFamily: "var(--fm)", fontSize: 11, fontWeight: 600, color: col }}>
          #{shortUuid(candidate.candidate_uuid)}
        </code>
        <span style={{
          fontSize: 9, fontFamily: "var(--fb)", fontWeight: 600, letterSpacing: "1.5px",
          textTransform: "uppercase",
          color: selected ? "#fff" : STATUS_COLOR[candidate.status],
          background: selected ? "rgba(255,255,255,0.15)" : STATUS_BG[candidate.status],
          padding: "2px 7px", borderRadius: 20,
        }}>
          {candidate.status}
        </span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontFamily: "var(--fb)", fontSize: 10, color: subCol }}>
          {formatTs(candidate.created_at)}
        </span>
        {candidate.prescreening_score !== null && (
          <span style={{
            fontFamily: "var(--fd)", fontSize: 13, fontWeight: 600,
            color: selected ? "#fff" : scoreColor(candidate.prescreening_score),
          }}>
            {Math.round(candidate.prescreening_score)}
          </span>
        )}
      </div>
    </button>
  );
}

// ── Upload zone ───────────────────────────────────────────────────────────────

function UploadZone({ onFile }: { onFile: (f: File) => void }) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) onFile(file);
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      style={{
        border: `1.5px dashed ${dragging ? "var(--gold)" : "var(--primary-30)"}`,
        borderRadius: 10,
        padding: "18px 16px",
        textAlign: "center",
        cursor: "pointer",
        background: dragging ? "var(--primary-10)" : "transparent",
        transition: "all 0.15s ease",
        marginBottom: 12,
      }}
    >
      <input ref={inputRef} type="file" accept=".pdf,.doc,.docx" style={{ display: "none" }}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); }} />
      <div style={{ fontFamily: "var(--fb)", fontSize: 12, color: "var(--mid)" }}>
        Drop PDF / DOCX here, or <span style={{ color: "var(--primary)", fontWeight: 600 }}>browse</span>
      </div>
      <div style={{ fontFamily: "var(--fb)", fontSize: 10, color: "var(--primary-30)", marginTop: 4 }}>
        PDF, DOC, DOCX · max 10 MB
      </div>
    </div>
  );
}

// ── Add Candidate Modal ───────────────────────────────────────────────────────

function AddCandidateModal({ onClose, onAdd }: { onClose: () => void; onAdd: (uuid: string) => void }) {
  const [value, setValue] = useState("");

  function handleSubmit() {
    const trimmed = value.trim();
    if (!trimmed) return;
    onAdd(trimmed);
    onClose();
  }

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200,
    }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--white)", borderRadius: 16, padding: 32,
          width: 440, boxShadow: "0 12px 48px rgba(0,51,102,0.22)",
          border: "1px solid var(--primary-10)",
        }}
      >
        <div style={{ fontFamily: "var(--fd)", fontSize: 20, fontWeight: 300, color: "var(--primary)", marginBottom: 6 }}>
          Add <em style={{ fontStyle: "italic", color: "var(--gold)" }}>Candidate</em>
        </div>
        <p style={{ fontFamily: "var(--fb)", fontSize: 12, color: "var(--mid)", marginBottom: 20, lineHeight: 1.6 }}>
          Enter an anonymous candidate UUID. No personal identifiers are stored.
        </p>
        <label style={{ fontFamily: "var(--fb)", fontSize: 10, letterSpacing: "1.5px", textTransform: "uppercase", fontWeight: 600, color: "var(--primary-60)", display: "block", marginBottom: 6 }}>
          Candidate UUID
        </label>
        <input
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") handleSubmit(); if (e.key === "Escape") onClose(); }}
          placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
          style={{
            width: "100%", boxSizing: "border-box",
            fontFamily: "var(--fm)", fontSize: 12,
            border: "1.5px solid var(--primary-10)", borderRadius: 8,
            padding: "10px 12px", outline: "none", color: "var(--dark)",
            background: "var(--bg)",
          }}
        />
        <div style={{ display: "flex", gap: 10, marginTop: 20, justifyContent: "flex-end" }}>
          <button onClick={onClose} style={{
            fontFamily: "var(--fb)", fontSize: 12, fontWeight: 500,
            padding: "8px 20px", border: "1.5px solid var(--primary-10)",
            borderRadius: 8, background: "none", cursor: "pointer", color: "var(--mid)",
          }}>
            Cancel
          </button>
          <button onClick={handleSubmit} style={{
            fontFamily: "var(--fb)", fontSize: 12, fontWeight: 600,
            padding: "8px 20px", border: "none",
            borderRadius: 8, background: "var(--primary)", cursor: "pointer", color: "#fff",
          }}>
            Add Candidate
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Detail panel ──────────────────────────────────────────────────────────────

function DetailPanel({ candidate }: { candidate: Candidate | null }) {
  const [repoInput, setRepoInput] = useState("");
  const { loadingUpload, loadingScreen, uploadResume, linkRepo, runPreScreen } = useCandidatesStore();

  if (!candidate) {
    return (
      <div style={{
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        height: "100%", gap: 12,
      }}>
        <svg width={48} height={48} viewBox="0 0 48 48" fill="none">
          <circle cx={24} cy={24} r={22} stroke="var(--primary-10)" strokeWidth={2} />
          <path d="M16 24h16M24 16v16" stroke="var(--primary-30)" strokeWidth={2} strokeLinecap="round" />
        </svg>
        <p style={{ fontFamily: "var(--fb)", fontSize: 13, color: "var(--mid)" }}>
          Select a candidate to view details
        </p>
      </div>
    );
  }

  const PANEL: CSSProperties = {
    background: "var(--white)",
    border: "1px solid var(--primary-10)",
    borderRadius: 12,
    padding: 20,
    marginBottom: 14,
  };

  const SECTION_LABEL: CSSProperties = {
    fontFamily: "var(--fb)", fontSize: 9, letterSpacing: "2px", textTransform: "uppercase",
    fontWeight: 700, color: "var(--primary-60)", marginBottom: 12, display: "block",
  };

  const BTN: CSSProperties = {
    fontFamily: "var(--fb)", fontSize: 12, fontWeight: 600,
    padding: "9px 18px", border: "none", borderRadius: 8,
    cursor: "pointer", transition: "opacity 0.15s ease",
  };

  return (
    <div style={{ overflowY: "auto", height: "100%", paddingRight: 2 }}>

      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <code style={{ fontFamily: "var(--fm)", fontSize: 13, fontWeight: 700, color: "var(--dark)" }}>
            #{shortUuid(candidate.candidate_uuid)}
          </code>
          <span style={{
            fontSize: 9, fontFamily: "var(--fb)", fontWeight: 600, letterSpacing: "1.5px",
            textTransform: "uppercase", padding: "2px 8px", borderRadius: 20,
            color: STATUS_COLOR[candidate.status],
            background: STATUS_BG[candidate.status],
          }}>
            {candidate.status}
          </span>
          {candidate.flagged && (
            <span style={{
              fontSize: 9, fontFamily: "var(--fb)", fontWeight: 600, letterSpacing: "1.5px",
              textTransform: "uppercase", padding: "2px 8px", borderRadius: 20,
              color: "#fff", background: "var(--rojo)",
            }}>
              {candidate.severity}
            </span>
          )}
        </div>
        <div style={{ fontFamily: "var(--fb)", fontSize: 10, color: "var(--mid)" }}>
          UUID: {candidate.candidate_uuid} · Added {formatTs(candidate.created_at)}
        </div>
      </div>

      {/* Alert callout */}
      {candidate.flagged && (
        <div style={{
          background: "#fdeced", border: "1.5px solid var(--rojo)",
          borderRadius: 10, padding: "12px 16px", marginBottom: 14,
        }}>
          <div style={{ fontFamily: "var(--fb)", fontSize: 11, fontWeight: 700, color: "var(--rojo)", marginBottom: 4 }}>
            AI-Assist Flag — {candidate.severity.toUpperCase()} severity
          </div>
          <p style={{ fontFamily: "var(--fb)", fontSize: 11, color: "#9b1c2b", margin: 0, lineHeight: 1.6 }}>
            {candidate.flag_reason}
          </p>
        </div>
      )}

      {/* Score gauges */}
      <div style={PANEL}>
        <span style={SECTION_LABEL}>Score Overview</span>
        <div style={{ display: "flex", gap: 20, justifyContent: "space-around" }}>
          <Gauge label="Resume AI" value={candidate.resume_ai_score} />
          <Gauge label="Repo AI" value={candidate.repo_ai_score} />
          <Gauge label="Pre-Screening" value={candidate.prescreening_score} />
        </div>
        {candidate.scored_at && (
          <div style={{ textAlign: "center", marginTop: 10, fontFamily: "var(--fb)", fontSize: 10, color: "var(--mid)" }}>
            Scored {formatTs(candidate.scored_at)}
          </div>
        )}
      </div>

      {/* Signal breakdown */}
      {candidate.signals.length > 0 && (
        <div style={PANEL}>
          <span style={SECTION_LABEL}>Signal Breakdown</span>
          {candidate.signals.map((sig) => (
            <SignalBar key={sig.signal_name} signal={sig} />
          ))}
        </div>
      )}

      {/* Resume upload */}
      <div style={PANEL}>
        <span style={SECTION_LABEL}>Resume</span>
        <UploadZone onFile={(f) => uploadResume("", candidate.candidate_uuid, f)} />
        {loadingUpload && (
          <div style={{ fontFamily: "var(--fb)", fontSize: 11, color: "var(--mid)", textAlign: "center" }}>
            Uploading…
          </div>
        )}
      </div>

      {/* Repo linker */}
      <div style={PANEL}>
        <span style={SECTION_LABEL}>GitHub Repository</span>
        {candidate.repo_url ? (
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            background: "var(--primary-10)", borderRadius: 8, padding: "9px 12px",
          }}>
            <span style={{ fontFamily: "var(--fm)", fontSize: 11, color: "var(--primary)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {candidate.repo_url}
            </span>
            <button
              onClick={() => linkRepo("", candidate.candidate_uuid, "")}
              style={{ fontFamily: "var(--fb)", fontSize: 10, color: "var(--rojo)", background: "none", border: "none", cursor: "pointer" }}
            >
              Remove
            </button>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 8 }}>
            <input
              value={repoInput}
              onChange={(e) => setRepoInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && repoInput.trim()) {
                  linkRepo("", candidate.candidate_uuid, repoInput.trim());
                  setRepoInput("");
                }
              }}
              placeholder="https://github.com/user/repo"
              style={{
                flex: 1, fontFamily: "var(--fm)", fontSize: 12,
                border: "1.5px solid var(--primary-10)", borderRadius: 8,
                padding: "8px 12px", outline: "none", color: "var(--dark)", background: "var(--bg)",
              }}
            />
            <button
              onClick={() => { if (repoInput.trim()) { linkRepo("", candidate.candidate_uuid, repoInput.trim()); setRepoInput(""); } }}
              style={{ ...BTN, background: "var(--primary)", color: "#fff", padding: "8px 14px" }}
            >
              Link
            </button>
          </div>
        )}
      </div>

      {/* Run Pre-Screen CTA */}
      {candidate.status === "pending" && (
        <button
          onClick={() => runPreScreen("", candidate.candidate_uuid)}
          disabled={loadingScreen}
          style={{
            ...BTN,
            width: "100%",
            background: loadingScreen ? "var(--primary-30)" : "var(--gold)",
            color: loadingScreen ? "#fff" : "var(--primary)",
            fontSize: 13, padding: "12px 24px",
            opacity: loadingScreen ? 0.7 : 1,
          }}
        >
          {loadingScreen ? "Running pre-screen…" : "Run Pre-Screen"}
        </button>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function CandidatesPage() {
  const {
    candidates, selectedId, activeTab,
    setTab, selectCandidate, addCandidate,
  } = useCandidatesStore();

  const [showModal, setShowModal] = useState(false);

  const filtered = candidates.filter((c) => {
    if (activeTab === "pending") return c.status === "pending";
    if (activeTab === "flagged") return c.status === "flagged";
    return true;
  });

  const selectedCandidate = candidates.find((c) => c.candidate_uuid === selectedId) ?? null;

  const total    = candidates.length;
  const screened = candidates.filter((c) => c.status === "screened" || c.status === "flagged").length;
  const flagged  = candidates.filter((c) => c.flagged).length;
  const scores   = candidates.map((c) => c.prescreening_score).filter((s): s is number => s !== null);
  const avgScore = scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : null;

  const TABS: { key: "all" | "pending" | "flagged"; label: string }[] = [
    { key: "all",     label: `All (${total})` },
    { key: "pending", label: `Pending (${candidates.filter((c) => c.status === "pending").length})` },
    { key: "flagged", label: `Flagged (${flagged})` },
  ];

  const KPI_CARD: CSSProperties = {
    background: "var(--white)",
    border: "1px solid var(--primary-10)",
    borderRadius: 10, padding: "14px 18px",
    flex: 1,
  };

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflowY: "hidden" }}>

      {/* ── Hero ─────────────────────────────────────────────────── */}
      <div style={{ padding: "32px 56px 0", background: "var(--bg)" }}>
        <Eyebrow>Pre-Screening</Eyebrow>
        <h1 style={{
          fontFamily: "var(--fd)", fontWeight: 300, fontSize: 36,
          color: "var(--primary)", margin: "10px 0 6px", lineHeight: 1.1,
        }}>
          Candidate{" "}
          <em style={{ fontStyle: "italic", color: "var(--gold)" }}>Pre-Screening</em>
        </h1>
        <p style={{
          fontFamily: "var(--fb)", fontSize: 13, color: "var(--mid)",
          maxWidth: 560, lineHeight: 1.65, marginBottom: 20,
        }}>
          Detect AI-assisted resume and repository submissions before the interview. Each
          candidate is scored across three orthogonal signal dimensions.
        </p>

        {/* KPI row */}
        <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
          {[
            { label: "Total",   value: String(total) },
            { label: "Screened", value: String(screened) },
            { label: "Flagged",  value: String(flagged),  accent: "var(--rojo)" },
            { label: "Avg Score", value: avgScore !== null ? Math.round(avgScore).toString() : "—", accent: avgScore !== null ? scoreColor(avgScore) : undefined },
          ].map(({ label, value, accent }) => (
            <div key={label} style={KPI_CARD}>
              <div style={{ fontFamily: "var(--fd)", fontSize: 28, fontWeight: 600, color: accent ?? "var(--primary)", lineHeight: 1 }}>
                {value}
              </div>
              <div style={{ fontFamily: "var(--fb)", fontSize: 10, letterSpacing: "1.5px", textTransform: "uppercase", color: "var(--mid)", marginTop: 4 }}>
                {label}
              </div>
            </div>
          ))}
        </div>

        {/* Tab bar + Add button */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "2px solid var(--primary-10)" }}>
          <div style={{ display: "flex", gap: 4 }}>
            {TABS.map(({ key, label }) => (
              <button key={key} onClick={() => setTab(key)} style={{
                fontFamily: "var(--fb)", fontSize: 12, fontWeight: activeTab === key ? 600 : 400,
                color: activeTab === key ? "var(--primary)" : "var(--mid)",
                background: "none", border: "none", cursor: "pointer",
                padding: "8px 14px",
                borderBottom: activeTab === key ? "2px solid var(--primary)" : "2px solid transparent",
                marginBottom: -2, transition: "all 0.15s ease",
              }}>
                {label}
              </button>
            ))}
          </div>
          <button
            onClick={() => setShowModal(true)}
            style={{
              fontFamily: "var(--fb)", fontSize: 12, fontWeight: 600,
              background: "var(--primary)", color: "#fff",
              border: "none", borderRadius: 8, padding: "7px 16px",
              cursor: "pointer", display: "flex", alignItems: "center", gap: 6,
              marginBottom: 8,
            }}
          >
            <span style={{ fontSize: 16, lineHeight: 1 }}>+</span> Add Candidate
          </button>
        </div>
      </div>

      {/* ── Two-column body ──────────────────────────────────────── */}
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "260px 1fr", overflow: "hidden", padding: "20px 56px 40px", gap: 20 }}>

        {/* Left — candidate list */}
        <div style={{ overflowY: "auto" }}>
          {filtered.length === 0 ? (
            <div style={{
              display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
              height: 200, gap: 8,
            }}>
              <p style={{ fontFamily: "var(--fb)", fontSize: 12, color: "var(--mid)", textAlign: "center" }}>
                No candidates in this view.
              </p>
            </div>
          ) : (
            filtered.map((c) => (
              <CandidateCard
                key={c.candidate_uuid}
                candidate={c}
                selected={c.candidate_uuid === selectedId}
                onClick={() => selectCandidate(c.candidate_uuid === selectedId ? null : c.candidate_uuid)}
              />
            ))
          )}
        </div>

        {/* Right — detail panel */}
        <div style={{
          background: "var(--bg-alt, var(--bg))",
          borderRadius: 14,
          border: "1px solid var(--primary-10)",
          padding: 22,
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}>
          <DetailPanel candidate={selectedCandidate} />
        </div>
      </div>

      {/* Add Candidate modal */}
      {showModal && (
        <AddCandidateModal
          onClose={() => setShowModal(false)}
          onAdd={(uuid) => {
            addCandidate({
              candidate_uuid: uuid,
              status: "pending",
              resume_ai_score: null,
              repo_ai_score: null,
              prescreening_score: null,
              interview_trust_score: null,
              flagged: false,
              severity: "low",
              flag_reason: "",
              signals: [],
              repo_url: null,
              scored_at: null,
              created_at: Date.now() / 1000,
            });
          }}
        />
      )}
    </div>
  );
}

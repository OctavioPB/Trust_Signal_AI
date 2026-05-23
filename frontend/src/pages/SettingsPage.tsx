/**
 * Settings — account, detection thresholds, alerts, data retention, and integrations.
 *
 * UI_Decisions compliance:
 *  - KPI accent bars: never overridden (always gold via CSS)
 *  - Structural card accents: always gold, never status colours
 *  - No SVG; all layout is HTML/CSS
 *  - Status colours appear only on value text and semantic badges
 *
 * CLAUDE.md security rules enforced in UI:
 *  - Audio retention hard-capped at 90 days — slider max locked by policy
 *  - Candidate anonymization always ON — toggle disabled, policy note shown
 *  - "Regenerate API key" requires explicit confirm dialog before execution
 *  - False Positive alert suppression prohibited — note shown in Alerts section
 */

import { useState, type ReactNode } from "react";
import type { CSSProperties } from "react";
import { Eyebrow } from "../components/Eyebrow";

// ── Types ─────────────────────────────────────────────────────────────────────

type SectionId = "detection" | "alerts" | "retention" | "integrations" | "account";
type ATSStatus  = "connected" | "disconnected" | "pending";

// ── Static data ───────────────────────────────────────────────────────────────

const NAV_SECTIONS: { id: SectionId; label: string; sub: string }[] = [
  { id: "detection",    label: "Detection",    sub: "Thresholds & sensitivity"   },
  { id: "alerts",       label: "Alerts",        sub: "Notifications & recipients" },
  { id: "retention",    label: "Retention",     sub: "Data lifecycle & privacy"   },
  { id: "integrations", label: "Integrations",  sub: "API keys & webhooks"        },
  { id: "account",      label: "Account",       sub: "Organisation & plan"        },
];

const ATS_INTEGRATIONS: { name: string; status: ATSStatus }[] = [
  { name: "Greenhouse", status: "connected"    },
  { name: "Lever",      status: "disconnected" },
  { name: "Workday",    status: "pending"      },
];

const TEAM_MEMBERS = [
  { name: "Ana Moreno",  role: "Talent · LATAM", initials: "AM", admin: true  },
  { name: "Raj Sharma",  role: "Talent · APAC",  initials: "RS", admin: false },
  { name: "Lena Kohl",   role: "Talent · EMEA",  initials: "LK", admin: false },
];

// ── Style constants ───────────────────────────────────────────────────────────

const CARD: CSSProperties = {
  backgroundColor: "var(--white)",
  border: "1px solid var(--primary-10)",
  borderRadius: 14,
  boxShadow: "var(--shadow-card)",
};

const FIELD_LBL: CSSProperties = {
  fontSize: 10,
  letterSpacing: "2px",
  textTransform: "uppercase",
  fontWeight: 600,
  color: "var(--primary-60)",
  fontFamily: "var(--fb)",
  marginBottom: 6,
  display: "block",
};

const INPUT_S: CSSProperties = {
  width: "100%",
  background: "var(--light)",
  border: "1px solid var(--primary-10)",
  borderRadius: 8,
  padding: "10px 14px",
  fontFamily: "var(--fm)",
  fontSize: 13,
  color: "var(--dark)",
  outline: "none",
  boxSizing: "border-box",
};

const DIVIDER: CSSProperties = {
  border: "none",
  borderTop: "1px solid var(--primary-10)",
  margin: "0 0 24px",
};

// ── Sub-components ────────────────────────────────────────────────────────────

function Toggle({
  on, onChange, disabled,
}: { on: boolean; onChange?: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      role="switch"
      aria-checked={on}
      onClick={() => !disabled && onChange?.(!on)}
      style={{
        width: 44, height: 24, borderRadius: 12,
        background: on ? "var(--verde)" : "var(--primary-10)",
        border: "none",
        cursor: disabled ? "not-allowed" : "pointer",
        position: "relative",
        transition: "background 0.2s ease",
        opacity: disabled ? 0.55 : 1,
        flexShrink: 0,
      }}
    >
      <span style={{
        position: "absolute",
        top: 3, left: on ? 23 : 3,
        width: 18, height: 18, borderRadius: 9,
        background: "var(--white)",
        boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
        transition: "left 0.2s ease",
        display: "block",
      }} />
    </button>
  );
}

function SettingRow({
  label, description, children, last = false,
}: { label: string; description?: string; children: ReactNode; last?: boolean }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "flex-start",
      gap: 32, padding: "18px 0",
      borderBottom: last ? "none" : "1px solid var(--primary-10)",
    }}>
      <div>
        <div style={{ fontFamily: "var(--fb)", fontSize: 14, fontWeight: 600, color: "var(--dark)", marginBottom: 3 }}>
          {label}
        </div>
        {description && (
          <div style={{ fontFamily: "var(--fb)", fontSize: 12, color: "var(--mid)", lineHeight: 1.65, maxWidth: 420 }}>
            {description}
          </div>
        )}
      </div>
      <div style={{ flexShrink: 0, display: "flex", alignItems: "center", gap: 10, paddingTop: 2 }}>
        {children}
      </div>
    </div>
  );
}

function SaveBar({ onSave, saved }: { onSave: () => void; saved: boolean }) {
  return (
    <div style={{
      display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 16,
      marginTop: 24, paddingTop: 20, borderTop: "1px solid var(--primary-10)",
    }}>
      {saved && (
        <span style={{ fontFamily: "var(--fb)", fontSize: 12, color: "var(--verde-dark)" }}>
          ✓ Changes saved
        </span>
      )}
      <button className="btn btn-primary" onClick={onSave}>Save changes</button>
    </div>
  );
}

function PolicyLock({ text }: { text: string }) {
  return (
    <div style={{
      background: "var(--primary-10)",
      borderLeft: "3px solid var(--gold)",
      borderRadius: "0 8px 8px 0",
      padding: "10px 14px",
      fontFamily: "var(--fb)",
      fontSize: 12,
      color: "var(--mid)",
      lineHeight: 1.65,
      marginTop: 14,
    }}>
      <span style={{ marginRight: 6 }}>🔒</span>{text}
    </div>
  );
}

// ── Section panels ────────────────────────────────────────────────────────────

function DetectionSection() {
  const [threshold,   setThreshold]   = useState(0.65);
  const [sensitivity, setSensitivity] = useState<"lenient" | "standard" | "strict">("standard");
  const [autoFlag,    setAutoFlag]    = useState(true);
  const [saved,       setSaved]       = useState(false);

  const SENS_OPTS: { value: "lenient" | "standard" | "strict"; label: string; sub: string }[] = [
    { value: "lenient",  label: "Lenient",  sub: "Flag threshold raised to 0.70. Reduces false positives at cost of sensitivity." },
    { value: "standard", label: "Standard", sub: "Flag at 0.65. Default calibration, validated against internal test set."         },
    { value: "strict",   label: "Strict",   sub: "Flag at 0.55. Higher recall; expect more items in the manual review queue."      },
  ];

  const threshColor =
    threshold >= 0.65 ? "var(--rojo)" :
    threshold >= 0.50 ? "var(--naranja)" : "var(--verde)";

  return (
    <div style={{ ...CARD, padding: 28 }}>
      <div style={{ marginBottom: 20 }}>
        <Eyebrow>Detection Thresholds</Eyebrow>
        <p style={{ fontFamily: "var(--fb)", fontSize: 13, color: "var(--mid)", lineHeight: 1.65, marginTop: 10, marginBottom: 0 }}>
          Controls when a candidate is flagged for review. Threshold changes take effect on the next scored session; signal weights require a nightly model run.
        </p>
      </div>

      {/* Threshold slider */}
      <div style={{ marginBottom: 24 }}>
        <span style={FIELD_LBL}>Suspicion index cutoff</span>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <input
            type="range"
            min={0.35} max={0.90} step={0.01}
            value={threshold}
            onChange={e => setThreshold(Number(e.target.value))}
            style={{ flex: 1, accentColor: "var(--primary)" }}
          />
          <code style={{
            fontFamily: "var(--fm)", fontSize: 14, fontWeight: 600,
            color: threshColor,
            background: "var(--primary-10)",
            padding: "4px 12px", borderRadius: 6,
            minWidth: 52, textAlign: "center", display: "block",
          }}>
            {threshold.toFixed(2)}
          </code>
        </div>
        {threshold < 0.50 && (
          <div style={{ fontFamily: "var(--fb)", fontSize: 11, color: "var(--naranja-dark)", marginTop: 8 }}>
            ⚠ Threshold below 0.50 significantly increases the false positive rate.
          </div>
        )}
      </div>

      <hr style={DIVIDER} />

      {/* Sensitivity mode */}
      <div style={{ marginBottom: 24 }}>
        <span style={FIELD_LBL}>Signal sensitivity mode</span>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {SENS_OPTS.map(opt => (
            <label key={opt.value} style={{ display: "flex", gap: 14, cursor: "pointer", alignItems: "flex-start" }}>
              <input
                type="radio"
                name="sensitivity"
                checked={sensitivity === opt.value}
                onChange={() => setSensitivity(opt.value)}
                style={{ marginTop: 4, accentColor: "var(--primary)", flexShrink: 0 }}
              />
              <div>
                <div style={{ fontFamily: "var(--fb)", fontSize: 14, fontWeight: 600, color: "var(--dark)" }}>{opt.label}</div>
                <div style={{ fontFamily: "var(--fb)", fontSize: 12, color: "var(--mid)", marginTop: 2 }}>{opt.sub}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      <hr style={DIVIDER} />

      {/* Auto-flag toggle */}
      <SettingRow
        label="Auto-flag mode"
        description="When ON, sessions crossing the threshold are flagged immediately and the alert dispatched. When OFF, they enter the manual review queue first."
        last
      >
        <Toggle on={autoFlag} onChange={setAutoFlag} />
        <span style={{ fontFamily: "var(--fb)", fontSize: 12, color: "var(--mid)", minWidth: 52 }}>
          {autoFlag ? "Auto" : "Manual"}
        </span>
      </SettingRow>

      <SaveBar onSave={() => { setSaved(true); setTimeout(() => setSaved(false), 3000); }} saved={saved} />
    </div>
  );
}

function AlertsSection() {
  const [email,             setEmail]             = useState("ana.moreno@company.com");
  const [onFlag,            setOnFlag]            = useState(true);
  const [onComplete,        setOnComplete]        = useState(false);
  const [includeTranscript, setIncludeTranscript] = useState(true);
  const [saved,             setSaved]             = useState(false);

  return (
    <div style={{ ...CARD, padding: 28 }}>
      <div style={{ marginBottom: 20 }}>
        <Eyebrow>Alerts & Notifications</Eyebrow>
        <p style={{ fontFamily: "var(--fb)", fontSize: 13, color: "var(--mid)", lineHeight: 1.65, marginTop: 10, marginBottom: 0 }}>
          All alerts include a human-readable explanation attached to the flag payload. Alert suppression is prohibited by platform policy.
        </p>
      </div>

      <div style={{ marginBottom: 20 }}>
        <span style={FIELD_LBL}>Alert recipient</span>
        <input
          style={INPUT_S}
          type="email"
          value={email}
          onChange={e => setEmail(e.target.value)}
          placeholder="recruiter@company.com"
        />
      </div>

      <hr style={DIVIDER} />

      <SettingRow
        label="Notify on flag"
        description="Dispatch an alert email immediately when a session's suspicion index crosses the configured threshold."
      >
        <Toggle on={onFlag} onChange={setOnFlag} />
      </SettingRow>

      <SettingRow
        label="Notify on session complete"
        description="Send a summary email when any scored session finishes, regardless of flag status."
      >
        <Toggle on={onComplete} onChange={setOnComplete} />
      </SettingRow>

      <SettingRow
        label="Include transcript excerpt"
        description="Attach the highest-suspicion candidate turn to the alert email. Candidate UUID is used — no name or email address is included."
        last
      >
        <Toggle on={includeTranscript} onChange={setIncludeTranscript} />
      </SettingRow>

      <PolicyLock text="Silent suppression of False Positive alerts is prohibited. Every flagged candidate receives a human-readable explanation in the alert payload, and the flag reason must be included in any downstream ATS update." />

      <SaveBar onSave={() => { setSaved(true); setTimeout(() => setSaved(false), 3000); }} saved={saved} />
    </div>
  );
}

function RetentionSection() {
  const [audioDays,      setAudioDays]      = useState(30);
  const [transcriptDays, setTranscriptDays] = useState(180);
  const [region, setRegion] = useState<"us-east-1" | "eu-west-1" | "ap-southeast-1">("us-east-1");
  const [saved,  setSaved]  = useState(false);

  const REGIONS: { value: "us-east-1" | "eu-west-1" | "ap-southeast-1"; label: string }[] = [
    { value: "us-east-1",        label: "US East — N. Virginia"       },
    { value: "eu-west-1",        label: "EU West — Ireland (GDPR)"    },
    { value: "ap-southeast-1",   label: "AP Southeast — Singapore"    },
  ];

  return (
    <div style={{ ...CARD, padding: 28 }}>
      <div style={{ marginBottom: 20 }}>
        <Eyebrow>Data Retention & Privacy</Eyebrow>
        <p style={{ fontFamily: "var(--fb)", fontSize: 13, color: "var(--mid)", lineHeight: 1.65, marginTop: 10, marginBottom: 0 }}>
          Audio data is stored in MinIO; transcripts in PostgreSQL. Configure retention windows and data residency below.
        </p>
      </div>

      {/* Audio retention */}
      <div style={{ marginBottom: 24 }}>
        <span style={FIELD_LBL}>Audio retention — {audioDays} days</span>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 8 }}>
          <input
            type="range"
            min={7} max={90} step={1}
            value={audioDays}
            onChange={e => setAudioDays(Number(e.target.value))}
            style={{ flex: 1, accentColor: "var(--primary)" }}
          />
          <code style={{
            fontFamily: "var(--fm)", fontSize: 14, color: "var(--primary)",
            background: "var(--primary-10)",
            padding: "4px 12px", borderRadius: 6,
            minWidth: 52, textAlign: "center", display: "block",
          }}>
            {audioDays}d
          </code>
        </div>
        <PolicyLock text="Audio data is deleted from MinIO within 90 days unless extended retention is explicitly opted into. This slider is capped at 90 days by platform policy." />
      </div>

      <hr style={DIVIDER} />

      {/* Transcript retention */}
      <div style={{ marginBottom: 24 }}>
        <span style={FIELD_LBL}>Transcript retention — {transcriptDays} days</span>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <input
            type="range"
            min={30} max={365} step={30}
            value={transcriptDays}
            onChange={e => setTranscriptDays(Number(e.target.value))}
            style={{ flex: 1, accentColor: "var(--primary)" }}
          />
          <code style={{
            fontFamily: "var(--fm)", fontSize: 14, color: "var(--primary)",
            background: "var(--primary-10)",
            padding: "4px 12px", borderRadius: 6,
            minWidth: 52, textAlign: "center", display: "block",
          }}>
            {transcriptDays}d
          </code>
        </div>
      </div>

      <hr style={DIVIDER} />

      {/* Data region */}
      <div style={{ marginBottom: 24 }}>
        <span style={FIELD_LBL}>Data residency region</span>
        <select
          value={region}
          onChange={e => setRegion(e.target.value as typeof region)}
          style={{ ...INPUT_S, cursor: "pointer" }}
        >
          {REGIONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
        </select>
      </div>

      <hr style={DIVIDER} />

      {/* Anonymization — locked per CLAUDE.md §1 */}
      <SettingRow
        label="Candidate anonymization"
        description="Candidate names, email addresses, and recruiter identifiers are anonymized (UUID only) in all log lines, Kafka payloads, and exports."
        last
      >
        <Toggle on={true} disabled />
        <span className="badge success"><span className="dot" />Always active</span>
      </SettingRow>

      <PolicyLock text="Anonymization cannot be disabled. All PII is stripped at ingestion and only UUIDs appear in logs, Kafka topics, and data exports. This is a non-negotiable platform security requirement." />

      <SaveBar onSave={() => { setSaved(true); setTimeout(() => setSaved(false), 3000); }} saved={saved} />
    </div>
  );
}

function IntegrationsSection() {
  const [webhookUrl,    setWebhookUrl]    = useState("https://hooks.company.com/trustsignal");
  const [exportFormat,  setExportFormat]  = useState<"json" | "csv">("json");
  const [keyVisible,    setKeyVisible]    = useState(false);
  const [confirmRegen,  setConfirmRegen]  = useState(false);
  const [saved,         setSaved]         = useState(false);

  const MASKED_KEY = "ts_live_3f8a2d1e9c7b4f0a6e2c8d5f1a3b7e9d";

  const atsBadge = (s: ATSStatus) => {
    const map: Record<ATSStatus, { cls: string; label: string }> = {
      connected:    { cls: "success", label: "Connected"  },
      disconnected: { cls: "danger",  label: "Not linked" },
      pending:      { cls: "warning", label: "Pending"    },
    };
    const { cls, label } = map[s];
    return <span className={`badge ${cls}`}><span className="dot" />{label}</span>;
  };

  return (
    <div style={{ ...CARD, padding: 28 }}>
      {/* Confirm-regenerate modal */}
      {confirmRegen && (
        <div style={{
          position: "fixed", inset: 0,
          backgroundColor: "rgba(0,0,0,0.45)",
          display: "flex", alignItems: "center", justifyContent: "center",
          zIndex: 200,
        }}>
          <div style={{
            backgroundColor: "var(--white)",
            borderRadius: 14, padding: "32px 36px",
            maxWidth: 400, width: "90%",
            boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
          }}>
            <div style={{ fontFamily: "var(--fd)", fontSize: 22, fontWeight: 300, color: "var(--primary)", marginBottom: 12 }}>
              Regenerate API <em style={{ fontStyle: "italic", color: "var(--rojo)" }}>key?</em>
            </div>
            <p style={{ fontFamily: "var(--fb)", fontSize: 13, color: "var(--mid)", lineHeight: 1.7, marginBottom: 24 }}>
              The current key will be permanently revoked. Any integration using it will stop working until the key is updated on the receiving end.
            </p>
            <div style={{ display: "flex", gap: 12, justifyContent: "flex-end" }}>
              <button className="btn btn-ghost" onClick={() => setConfirmRegen(false)}>Cancel</button>
              <button
                className="btn"
                style={{ background: "var(--rojo)", color: "#fff" }}
                onClick={() => setConfirmRegen(false)}
              >
                Regenerate
              </button>
            </div>
          </div>
        </div>
      )}

      <div style={{ marginBottom: 20 }}>
        <Eyebrow>API & Integrations</Eyebrow>
      </div>

      {/* API key */}
      <div style={{ marginBottom: 24 }}>
        <span style={FIELD_LBL}>API key</span>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <code style={{
            ...INPUT_S,
            flex: 1,
            letterSpacing: keyVisible ? 0 : 3,
            color: "var(--primary-60)",
            fontSize: 12,
          }}>
            {keyVisible ? MASKED_KEY : "•".repeat(32)}
          </code>
          <button
            className="btn btn-ghost"
            onClick={() => setKeyVisible(v => !v)}
            style={{ whiteSpace: "nowrap", padding: "10px 14px" }}
          >
            {keyVisible ? "Hide" : "Reveal"}
          </button>
          <button
            className="btn btn-ghost"
            onClick={() => setConfirmRegen(true)}
            style={{ whiteSpace: "nowrap", padding: "10px 14px" }}
          >
            Regenerate
          </button>
        </div>
      </div>

      <hr style={DIVIDER} />

      {/* Webhook */}
      <div style={{ marginBottom: 24 }}>
        <span style={FIELD_LBL}>Webhook endpoint</span>
        <input
          style={INPUT_S}
          type="url"
          value={webhookUrl}
          onChange={e => setWebhookUrl(e.target.value)}
          placeholder="https://your-service.com/webhook"
        />
        <div style={{ fontFamily: "var(--fb)", fontSize: 11, color: "var(--mid)", marginTop: 6 }}>
          POST payload includes{" "}
          {["session_id", "trust_score", "flagged", "candidate_id"].map(k => (
            <code key={k} style={{ fontFamily: "var(--fm)", background: "var(--primary-10)", padding: "1px 5px", borderRadius: 3, margin: "0 2px" }}>{k}</code>
          ))}.
          {" "}Candidate ID is UUID — no PII.
        </div>
      </div>

      <hr style={DIVIDER} />

      {/* ATS connections */}
      <div style={{ marginBottom: 24 }}>
        <span style={FIELD_LBL}>ATS connections</span>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {ATS_INTEGRATIONS.map(a => (
            <div key={a.name} style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              padding: "12px 16px",
              background: "var(--light)",
              borderRadius: 8, border: "1px solid var(--primary-10)",
            }}>
              <span style={{ fontFamily: "var(--fb)", fontSize: 14, fontWeight: 600, color: "var(--dark)" }}>
                {a.name}
              </span>
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                {atsBadge(a.status)}
                <button
                  className="btn btn-ghost"
                  style={{ padding: "6px 12px", fontSize: 10, letterSpacing: "1.5px" }}
                >
                  {a.status === "connected" ? "Disconnect" : "Connect"}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <hr style={DIVIDER} />

      {/* Export format */}
      <div>
        <span style={FIELD_LBL}>Export format</span>
        <div style={{ display: "flex", gap: 24 }}>
          {(["json", "csv"] as const).map(fmt => (
            <label key={fmt} style={{ display: "flex", gap: 10, alignItems: "center", cursor: "pointer" }}>
              <input
                type="radio"
                name="exportFormat"
                checked={exportFormat === fmt}
                onChange={() => setExportFormat(fmt)}
                style={{ accentColor: "var(--primary)" }}
              />
              <span style={{ fontFamily: "var(--fb)", fontSize: 13, fontWeight: 600, color: "var(--dark)", textTransform: "uppercase", letterSpacing: "1.5px" }}>
                {fmt}
              </span>
            </label>
          ))}
        </div>
      </div>

      <SaveBar onSave={() => { setSaved(true); setTimeout(() => setSaved(false), 3000); }} saved={saved} />
    </div>
  );
}

function AccountSection() {
  const [orgName,       setOrgName]       = useState("Apex Global Talent");
  const [contactEmail,  setContactEmail]  = useState("admin@apexglobal.com");
  const [saved,         setSaved]         = useState(false);

  return (
    <div style={{ ...CARD, padding: 28 }}>
      <div style={{ marginBottom: 20 }}>
        <Eyebrow>Account & Organisation</Eyebrow>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 24 }}>
        <div>
          <span style={FIELD_LBL}>Organisation name</span>
          <input style={INPUT_S} value={orgName} onChange={e => setOrgName(e.target.value)} />
        </div>
        <div>
          <span style={FIELD_LBL}>Billing contact</span>
          <input style={INPUT_S} type="email" value={contactEmail} onChange={e => setContactEmail(e.target.value)} />
        </div>
      </div>

      {/* Plan card */}
      <div style={{
        background: "var(--primary)",
        backgroundImage: "linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)",
        backgroundSize: "48px 48px",
        borderRadius: 10,
        padding: "20px 24px",
        display: "grid", gridTemplateColumns: "1fr auto",
        alignItems: "center", gap: 24,
        marginBottom: 24,
      }}>
        <div>
          <div style={{ fontFamily: "var(--fd)", fontSize: 22, fontWeight: 300, color: "#fff", marginBottom: 4 }}>
            Enterprise <em style={{ fontStyle: "italic", color: "var(--gold-light)" }}>plan</em>
          </div>
          <div style={{ fontFamily: "var(--fb)", fontSize: 12, color: "rgba(255,255,255,0.55)" }}>
            Unlimited sessions · 8 / 20 seats · Priority support · 90-day audio retention
          </div>
        </div>
        <button className="btn btn-ghost-dark" style={{ whiteSpace: "nowrap" }}>
          Manage plan
        </button>
      </div>

      {/* Team members */}
      <div>
        <span style={FIELD_LBL}>Team members</span>
        {TEAM_MEMBERS.map((u, i) => (
          <div key={u.name} style={{
            display: "flex", alignItems: "center", gap: 14,
            padding: "12px 0",
            borderBottom: i < TEAM_MEMBERS.length - 1 ? "1px solid var(--primary-10)" : "none",
          }}>
            <div style={{
              width: 36, height: 36, borderRadius: "50%",
              background: "linear-gradient(135deg, var(--gold), var(--gold-light))",
              color: "var(--primary)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontFamily: "var(--fd)", fontWeight: 600, fontSize: 13,
              flexShrink: 0,
            }}>
              {u.initials}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontFamily: "var(--fb)", fontSize: 14, fontWeight: 600, color: "var(--dark)" }}>
                {u.name}
              </div>
              <div style={{ fontFamily: "var(--fb)", fontSize: 11, color: "var(--mid)", letterSpacing: "1px", marginTop: 1 }}>
                {u.role}
              </div>
            </div>
            {u.admin && <span className="badge info"><span className="dot" />Admin</span>}
          </div>
        ))}
        <button
          className="btn btn-ghost"
          style={{ marginTop: 16, width: "100%" }}
        >
          + Invite team member
        </button>
      </div>

      <SaveBar onSave={() => { setSaved(true); setTimeout(() => setSaved(false), 3000); }} saved={saved} />
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

function renderSection(id: SectionId) {
  switch (id) {
    case "detection":    return <DetectionSection />;
    case "alerts":       return <AlertsSection />;
    case "retention":    return <RetentionSection />;
    case "integrations": return <IntegrationsSection />;
    case "account":      return <AccountSection />;
  }
}

export function SettingsPage() {
  const [active, setActive] = useState<SectionId>("detection");

  return (
    <div style={{ flex: 1, padding: "40px 56px 80px", boxSizing: "border-box", width: "100%", maxWidth: 1440, margin: "0 auto" }}>

      {/* ── Hero ─────────────────────────────────────────────────────────────── */}
      <div className="hero">
        <div className="hero-top">
          <div className="hero-id">
            <Eyebrow variant="dark">Settings</Eyebrow>
          </div>
        </div>
        <div className="hero-body" style={{ gap: 0 }}>
          <div>
            <h1>Platform <em>configuration</em></h1>
            <p className="lede">
              Adjust detection thresholds, notification rules, data retention periods, and integration endpoints.
              Policy-locked fields reflect non-negotiable security requirements.
            </p>
            <div className="meta-strip">
              <div className="meta-cell">
                <div className="lbl">Plan</div>
                <div className="val">Enterprise</div>
              </div>
              <div className="meta-cell">
                <div className="lbl">Seats</div>
                <div className="val">8<span className="unit">/ 20</span></div>
              </div>
              <div className="meta-cell">
                <div className="lbl">Sessions this month</div>
                <div className="val">247</div>
              </div>
              <div className="meta-cell">
                <div className="lbl">Storage</div>
                <div className="val">2.4<span className="unit">GB</span></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── KPI row ─────────────────────────────────────────────────────────── */}
      <div className="kpi-grid" style={{ marginBottom: 32 }}>
        <div className="kpi">
          <span className="kpi-accent" />
          <div className="kpi-top">
            <div className="kpi-lbl">Sessions today</div>
            <span className="badge info"><span className="dot" />Active</span>
          </div>
          <div className="kpi-val" style={{ color: "var(--primary)" }}>12</div>
          <div className="kpi-sub">of 247 this month</div>
        </div>

        <div className="kpi">
          <span className="kpi-accent" />
          <div className="kpi-top">
            <div className="kpi-lbl">Flagged this week</div>
            <span className="badge warning"><span className="dot" />Review</span>
          </div>
          <div className="kpi-val" style={{ color: "var(--naranja)" }}>3</div>
          <div className="kpi-sub">of 21 sessions (14%)</div>
        </div>

        <div className="kpi">
          <span className="kpi-accent" />
          <div className="kpi-top">
            <div className="kpi-lbl">API calls today</div>
            <span className="badge success"><span className="dot" />Within limit</span>
          </div>
          <div className="kpi-val" style={{ color: "var(--primary)" }}>1,203</div>
          <div className="kpi-sub">10k / day rate limit</div>
        </div>

        <div className="kpi">
          <span className="kpi-accent" />
          <div className="kpi-top">
            <div className="kpi-lbl">Storage used</div>
          </div>
          <div className="kpi-val" style={{ color: "var(--primary-60)" }}>
            2.4<span className="unit">GB</span>
          </div>
          <div className="kpi-sub">of 10 GB (24%)</div>
        </div>
      </div>

      {/* ── 2-column: nav + content ─────────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 20, alignItems: "flex-start" }}>

        {/* Left nav */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12, position: "sticky", top: "calc(var(--nav-h) + 24px)" }}>
          <div style={{ ...CARD, padding: 8 }}>
            {NAV_SECTIONS.map(s => (
              <button
                key={s.id}
                onClick={() => setActive(s.id)}
                style={{
                  width: "100%", background: "transparent",
                  border: "none",
                  borderLeft: active === s.id ? "3px solid var(--gold)" : "3px solid transparent",
                  borderRadius: 8,
                  padding: "12px 14px",
                  cursor: "pointer",
                  textAlign: "left",
                  transition: "background 0.15s ease",
                  backgroundColor: active === s.id ? "var(--primary-10)" : "transparent",
                }}
              >
                <div style={{
                  fontFamily: "var(--fb)", fontSize: 13, fontWeight: 600,
                  color: active === s.id ? "var(--primary)" : "var(--dark)",
                  marginBottom: 2,
                }}>
                  {s.label}
                </div>
                <div style={{ fontFamily: "var(--fb)", fontSize: 11, color: "var(--mid)" }}>
                  {s.sub}
                </div>
              </button>
            ))}
          </div>

          {/* Policy callout */}
          <div style={{ ...CARD, padding: 16, borderLeft: "3px solid var(--gold)" }}>
            <div style={{
              fontFamily: "var(--fb)", fontSize: 10, letterSpacing: "2px",
              textTransform: "uppercase", fontWeight: 600, color: "var(--gold)",
              marginBottom: 8,
            }}>
              Policy
            </div>
            <p style={{ fontFamily: "var(--fb)", fontSize: 11, color: "var(--mid)", lineHeight: 1.65, margin: 0 }}>
              Settings marked 🔒 are governed by platform security policy and cannot be disabled by organisation admins.
            </p>
          </div>
        </div>

        {/* Right content */}
        <div>
          {renderSection(active)}
        </div>

      </div>
    </div>
  );
}

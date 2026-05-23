/**
 * Models — signal module registry and health dashboard.
 *
 * Shows each of the five ML signal modules: version, accuracy, false-positive
 * rate, feature list, and contribution weight. Also surfaces the nightly
 * Airflow retraining log.
 *
 * UI_Decisions compliance:
 *  - KPI accent bars: never overridden (always gold via CSS)
 *  - Accent bars on model cards: 3px solid var(--gold) — structural, not semantic
 *  - Weight bars: CSS background (not SVG) → may use var() tokens
 *  - No SVG in this file; all visuals are CSS-based
 *  - Status colours appear only on value text and badges
 */

import { Eyebrow } from "../components/Eyebrow";

// ── Types ─────────────────────────────────────────────────────────────────────

type ModelStatus = "healthy" | "degraded" | "retraining";
type RunStatus   = "success" | "partial"  | "failed";

interface SignalModel {
  id:               string;
  name:             string;
  description:      string;
  version:          string;
  lastTrained:      string;
  accuracy:         number;   // 0–1
  falsePositiveRate:number;   // 0–1
  threshold:        number;   // suspicion flag threshold
  weight:           number;   // contribution weight (all five sum to 1.0)
  status:           ModelStatus;
  features:         string[];
}

interface RetrainRun {
  date:          string;
  duration:      string;
  status:        RunStatus;
  modelsUpdated: number;
  samples:       number;
}

// ── Data ──────────────────────────────────────────────────────────────────────

const MODELS: SignalModel[] = [
  {
    id: "01", name: "Response Latency",
    description: "Measures pre-answer pause variance. Suspiciously constant latency (~3.2 s) suggests an LLM inference + read-aloud buffer pattern.",
    version: "v2.4.1", lastTrained: "2026-05-21",
    accuracy: 0.887, falsePositiveRate: 0.018, threshold: 0.65, weight: 0.22,
    status: "healthy",
    features: ["pause_duration_ms", "variance_coefficient", "silence_ratio"],
  },
  {
    id: "02", name: "Background Audio",
    description: "Classifies ambient audio during candidate silences. Detects mechanical keyboard typing indicating AI-assisted lookup.",
    version: "v1.9.3", lastTrained: "2026-05-21",
    accuracy: 0.923, falsePositiveRate: 0.012, threshold: 0.65, weight: 0.18,
    status: "healthy",
    features: ["keystroke_energy", "ambient_freq_peak", "silence_snr"],
  },
  {
    id: "03", name: "Perplexity",
    description: "Scores transcript predictability against GPT-2. AI-generated text exhibits characteristically low perplexity across turns.",
    version: "v3.1.0", lastTrained: "2026-05-20",
    accuracy: 0.901, falsePositiveRate: 0.021, threshold: 0.65, weight: 0.26,
    status: "healthy",
    features: ["token_perplexity", "sentence_entropy", "ngram_ratio"],
  },
  {
    id: "04", name: "Burstiness",
    description: "Measures sentence-length variance. Humans are naturally bursty; AI-generated text has homogeneous, low-variance sentence lengths.",
    version: "v2.0.7", lastTrained: "2026-05-21",
    accuracy: 0.856, falsePositiveRate: 0.024, threshold: 0.65, weight: 0.17,
    status: "healthy",
    features: ["sentence_len_cv", "burst_ratio", "long_run_ratio"],
  },
  {
    id: "05", name: "Semantic Similarity",
    description: "Cosine similarity between transcript embeddings and a curated bank of canonical LLM interview answers. Updated nightly.",
    version: "v4.2.0", lastTrained: "2026-05-21",
    accuracy: 0.934, falsePositiveRate: 0.015, threshold: 0.65, weight: 0.17,
    status: "healthy",
    features: ["cosine_sim", "top_k_coverage", "answer_overlap"],
  },
];

const RETRAIN_LOG: RetrainRun[] = [
  { date: "2026-05-21  02:14", duration: "8m 43s",  status: "success", modelsUpdated: 5, samples: 1_847 },
  { date: "2026-05-20  02:11", duration: "7m 51s",  status: "success", modelsUpdated: 5, samples: 1_820 },
  { date: "2026-05-19  02:09", duration: "9m 12s",  status: "success", modelsUpdated: 5, samples: 1_798 },
  { date: "2026-05-18  02:15", duration: "8m 05s",  status: "success", modelsUpdated: 5, samples: 1_775 },
  { date: "2026-05-17  02:22", duration: "14m 38s", status: "partial", modelsUpdated: 3, samples: 1_701 },
];

// Ordered navy gradient for categorical weight bars — UI_Decisions §5
const WEIGHT_COLORS = [
  "var(--primary)",
  "var(--primary-80)",
  "var(--primary-60)",
  "#4d7099",
  "var(--primary-30)",
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function statusBadge(s: ModelStatus): JSX.Element {
  const map: Record<ModelStatus, { cls: string; label: string }> = {
    healthy:    { cls: "success", label: "Healthy"    },
    degraded:   { cls: "warning", label: "Degraded"   },
    retraining: { cls: "info",    label: "Retraining" },
  };
  const { cls, label } = map[s];
  return <span className={`badge ${cls}`}><span className="dot" />{label}</span>;
}

function runBadge(s: RunStatus): JSX.Element {
  const map: Record<RunStatus, { cls: string; label: string }> = {
    success: { cls: "success", label: "Success" },
    partial: { cls: "warning", label: "Partial" },
    failed:  { cls: "danger",  label: "Failed"  },
  };
  const { cls, label } = map[s];
  return <span className={`badge ${cls}`}><span className="dot" />{label}</span>;
}

function pct(v: number, decimals = 1): string {
  return (v * 100).toFixed(decimals) + "%";
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ModelCard({ model, idx }: { model: SignalModel; idx: number }) {
  return (
    <div style={{
      backgroundColor: "var(--white)",
      border: "1px solid var(--primary-10)",
      borderRadius: 14,
      padding: 28,
      boxShadow: "var(--shadow-card)",
      display: "flex",
      flexDirection: "column",
      gap: 0,
    }}>
      {/* Decorative number + gold accent bar — UI_Decisions §9 */}
      <div style={{
        fontFamily: "var(--fd)", fontSize: 44, fontWeight: 300,
        color: "var(--primary-30)", lineHeight: 1, userSelect: "none",
      }}>
        {model.id}
      </div>
      <div style={{ width: 36, height: 3, backgroundColor: "var(--gold)", borderRadius: 2, margin: "8px 0 14px" }} />

      {/* Name + version + status */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 10 }}>
        <div style={{ fontFamily: "var(--fd)", fontSize: 18, fontWeight: 300, color: "var(--dark)", lineHeight: 1.25 }}>
          {model.name}
        </div>
        {statusBadge(model.status)}
      </div>

      {/* Version tag */}
      <div style={{ marginBottom: 12 }}>
        <code style={{ fontFamily: "var(--fm)", fontSize: 11, color: "var(--primary-60)", background: "var(--primary-10)", padding: "2px 8px", borderRadius: 4 }}>
          {model.version}
        </code>
        <span style={{ marginLeft: 10, fontFamily: "var(--fb)", fontSize: 10, color: "var(--mid)", letterSpacing: "1px" }}>
          trained {model.lastTrained}
        </span>
      </div>

      {/* Description */}
      <p style={{ fontFamily: "var(--fb)", fontSize: 12, color: "var(--mid)", lineHeight: 1.7, margin: "0 0 20px" }}>
        {model.description}
      </p>

      {/* Accuracy bar */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
          <span style={{ fontFamily: "var(--fb)", fontSize: 10, fontWeight: 600, letterSpacing: "2px", textTransform: "uppercase", color: "var(--mid)" }}>
            Accuracy
          </span>
          <span style={{ fontFamily: "var(--fd)", fontSize: 18, fontWeight: 300, color: "var(--primary)" }}>
            {pct(model.accuracy)}
          </span>
        </div>
        <div style={{ height: 6, background: "var(--primary-10)", borderRadius: 3, overflow: "hidden" }}>
          <div style={{ height: "100%", width: pct(model.accuracy, 2), background: WEIGHT_COLORS[idx], borderRadius: 3, transition: "width 0.5s ease" }} />
        </div>
      </div>

      {/* Stats row */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, paddingTop: 16, borderTop: "1px solid var(--primary-10)" }}>
        {[
          { label: "FP Rate",    value: pct(model.falsePositiveRate) },
          { label: "Threshold",  value: model.threshold.toFixed(2)   },
          { label: "Weight",     value: pct(model.weight)             },
        ].map(({ label, value }) => (
          <div key={label}>
            <div style={{ fontFamily: "var(--fb)", fontSize: 9, fontWeight: 600, letterSpacing: "2px", textTransform: "uppercase", color: "var(--mid)", marginBottom: 4 }}>
              {label}
            </div>
            <div style={{ fontFamily: "var(--fd)", fontSize: 16, fontWeight: 300, color: "var(--dark)" }}>
              {value}
            </div>
          </div>
        ))}
      </div>

      {/* Feature tags */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 16 }}>
        {model.features.map(f => (
          <code key={f} style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--primary-60)", background: "var(--primary-10)", padding: "2px 7px", borderRadius: 4 }}>
            {f}
          </code>
        ))}
      </div>
    </div>
  );
}

function WeightChart() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {MODELS.map((m, i) => (
        <div key={m.id}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
            <span style={{ fontFamily: "var(--fb)", fontSize: 13, fontWeight: 600, color: "var(--dark)" }}>
              {m.name}
            </span>
            <span style={{ fontFamily: "var(--fm)", fontSize: 11, color: "var(--mid)" }}>
              {pct(m.weight)} weight · {pct(m.accuracy)} acc
            </span>
          </div>
          <div style={{ height: 10, background: "var(--primary-10)", borderRadius: 5, overflow: "hidden" }}>
            <div style={{
              height: "100%",
              width: pct(m.weight, 2),
              background: WEIGHT_COLORS[i],
              borderRadius: 5,
              transition: "width 0.5s ease",
            }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function RetrainLog() {
  const TH: React.CSSProperties = {
    textAlign: "left",
    padding: "10px 16px",
    fontSize: 9,
    letterSpacing: "2px",
    textTransform: "uppercase",
    fontWeight: 600,
    color: "#fff",
    whiteSpace: "nowrap",
    background: "transparent",
  };
  const TD: React.CSSProperties = { padding: "11px 16px", fontSize: 12, fontFamily: "var(--fb)" };

  return (
    <div style={{ overflowX: "auto", borderRadius: 10, overflow: "hidden", border: "1px solid var(--primary-10)" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ backgroundColor: "var(--primary)" }}>
            <th style={TH}>Run date</th>
            <th style={TH}>Duration</th>
            <th style={TH}>Status</th>
            <th style={TH}>Models updated</th>
            <th style={TH}>Training samples</th>
          </tr>
        </thead>
        <tbody>
          {RETRAIN_LOG.map((r, i) => (
            <tr key={r.date} style={{ background: i % 2 === 0 ? "var(--white)" : "var(--light)", borderBottom: "1px solid var(--primary-10)" }}>
              <td style={{ ...TD, fontFamily: "var(--fm)", color: "var(--dark)" }}>{r.date}</td>
              <td style={{ ...TD, color: "var(--mid)" }}>{r.duration}</td>
              <td style={TD}>{runBadge(r.status)}</td>
              <td style={{ ...TD, fontFamily: "var(--fd)", fontSize: 18, fontWeight: 300, color: "var(--primary)" }}>
                {r.modelsUpdated} <span style={{ fontFamily: "var(--fb)", fontSize: 10, color: "var(--mid)", fontWeight: 400 }}>/ 5</span>
              </td>
              <td style={{ ...TD, fontFamily: "var(--fm)", color: "var(--dark)" }}>
                {r.samples.toLocaleString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Shared style objects (defined outside component — not recreated on render) ─

const SECTION_LABEL: React.CSSProperties = {
  fontSize: 11,
  letterSpacing: "2.5px",
  textTransform: "uppercase",
  fontWeight: 600,
  color: "var(--mid)",
  fontFamily: "var(--fb)",
  marginBottom: 20,
};

const CARD: React.CSSProperties = {
  backgroundColor: "var(--white)",
  border: "1px solid var(--primary-10)",
  borderRadius: 14,
  padding: 28,
  boxShadow: "var(--shadow-card)",
};

// ── Page ─────────────────────────────────────────────────────────────────────

export function ModelsPage() {
  const avgAccuracy = MODELS.reduce((a, m) => a + m.accuracy, 0) / MODELS.length;
  const avgFP       = MODELS.reduce((a, m) => a + m.falsePositiveRate, 0) / MODELS.length;
  const healthy     = MODELS.filter(m => m.status === "healthy").length;

  return (
    <div style={{ flex: 1, padding: "40px 56px 80px", boxSizing: "border-box", width: "100%", maxWidth: 1440, margin: "0 auto" }}>

      {/* ── Hero card ────────────────────────────────────────────────────── */}
      <div className="hero">
        <div className="hero-top">
          <div className="hero-id">
            <Eyebrow variant="dark">Signal Models</Eyebrow>
          </div>
          <div className="hero-actions">
            <button
              className="btn btn-ghost-dark"
              disabled
              title="Ad-hoc retraining is prohibited — models update via the nightly Airflow DAG only."
              style={{ cursor: "not-allowed", opacity: 0.45 }}
            >
              ↻ Trigger Retrain
            </button>
          </div>
        </div>

        <div className="hero-body" style={{ gap: 0 }}>
          <div>
            <h1>Five-signal <em>detection</em> stack</h1>
            <p className="lede">
              Each module scores one behavioural dimension. The five weighted
              scores collapse into a single suspicion index, delivered within
              60 s of call end. All models retrain nightly via Airflow.
            </p>

            <div className="meta-strip" style={{ gridTemplateColumns: "repeat(4, auto)" }}>
              <div className="meta-cell">
                <div className="lbl">Active Models</div>
                <div className="val">{healthy}<span className="unit">/ 5</span></div>
              </div>
              <div className="meta-cell">
                <div className="lbl">Last Retrain</div>
                <div className="val">8h<span className="unit">ago</span></div>
              </div>
              <div className="meta-cell">
                <div className="lbl">Fleet FP Rate</div>
                <div className="val">{pct(avgFP)}</div>
              </div>
              <div className="meta-cell">
                <div className="lbl">Avg Accuracy</div>
                <div className="val">{pct(avgAccuracy)}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── KPI row — accent bars always gold via CSS ─────────────────────── */}
      <div className="kpi-grid" style={{ marginBottom: 32 }}>
        <div className="kpi">
          <span className="kpi-accent" />
          <div className="kpi-top"><div className="kpi-lbl">Models Online</div></div>
          <div className="kpi-val" style={{ color: "var(--primary)" }}>
            {healthy}<span className="unit">/ 5</span>
          </div>
          <div className="kpi-sub">
            <span className="badge success"><span className="dot" />All healthy</span>
          </div>
        </div>

        <div className="kpi">
          <span className="kpi-accent" />
          <div className="kpi-top">
            <div className="kpi-lbl">Avg Accuracy</div>
            <span className="badge success"><span className="dot" />Above target</span>
          </div>
          <div className="kpi-val" style={{ color: "var(--verde)" }}>
            {pct(avgAccuracy)}<span className="unit"> acc</span>
          </div>
          <div className="kpi-sub">Target ≥ 85%</div>
        </div>

        <div className="kpi">
          <span className="kpi-accent" />
          <div className="kpi-top">
            <div className="kpi-lbl">Fleet FP Rate</div>
            <span className="badge success"><span className="dot" />Below target</span>
          </div>
          <div className="kpi-val" style={{ color: "var(--primary-60)" }}>
            {pct(avgFP)}<span className="unit"> fp</span>
          </div>
          <div className="kpi-sub">Target &lt; 2%</div>
        </div>

        <div className="kpi">
          <span className="kpi-accent" />
          <div className="kpi-top"><div className="kpi-lbl">Flag Threshold</div></div>
          <div className="kpi-val" style={{ color: "var(--primary)" }}>
            0.65<span className="unit"> idx</span>
          </div>
          <div className="kpi-sub">Suspicion index cutoff</div>
        </div>
      </div>

      {/* ── Model cards ──────────────────────────────────────────────────── */}
      <div style={{ marginBottom: 12 }}>
        <Eyebrow>Signal Modules</Eyebrow>
      </div>
      <p style={{ fontFamily: "var(--fb)", fontSize: 13, color: "var(--mid)", lineHeight: 1.7, marginBottom: 24 }}>
        One card per signal module — version, accuracy, false-positive rate, feature list, and aggregate weight.
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 20, marginBottom: 32 }}>
        {MODELS.map((m, i) => <ModelCard key={m.id} model={m} idx={i} />)}
      </div>

      {/* ── Weight contribution + Retraining log ─────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>

        <div style={CARD}>
          <div style={SECTION_LABEL}>Aggregate Weight Distribution</div>
          <WeightChart />
          <p style={{ fontFamily: "var(--fb)", fontSize: 11, color: "var(--mid)", lineHeight: 1.65, marginTop: 20, paddingTop: 16, borderTop: "1px solid var(--primary-10)" }}>
            Weights are fixed at deployment and reviewed quarterly. The perplexity module carries the highest weight (26%) due to its lowest false-positive rate in the validation set.
          </p>
        </div>

        <div style={CARD}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
            <div style={SECTION_LABEL}>Nightly Retraining Log</div>
            <span className="badge info"><span className="dot" />Airflow DAG</span>
          </div>
          <RetrainLog />
          <p style={{ fontFamily: "var(--fb)", fontSize: 11, color: "var(--mid)", lineHeight: 1.65, marginTop: 16 }}>
            Models retrain nightly at 02:00 UTC on suspicious transcripts from the preceding 24 h. Ad-hoc retraining in production requires a DAG task entry — the button above is disabled by policy.
          </p>
        </div>

      </div>
    </div>
  );
}

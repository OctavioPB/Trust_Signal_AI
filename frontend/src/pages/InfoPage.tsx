/**
 * Info — three-tab documentation page.
 *
 * Instructions:   recruiter workflow, signal reference, score interpretation.
 * Business View:  problem framing, detection approach, scope and limitations.
 * Engineering:    tech stack, system architecture (SVG), data pipeline (SVG),
 *                 Kafka topics, ML model table, security invariants.
 *
 * Tab bar bridges the hero to the content body per UI_Decisions §8.
 * All SVG fill/stroke attributes use raw hex values — CSS custom properties
 * do not apply to SVG presentation attributes (UI_Decisions §5).
 */

import { useState } from "react";
import type { CSSProperties } from "react";
import { Eyebrow } from "../components/Eyebrow";

// ── Types ─────────────────────────────────────────────────────────────────────

type Tab = "instructions" | "business" | "engineering";

// ── Static content ─────────────────────────────────────────────────────────────

const SETUP_STEPS = [
  {
    title: "Enter the candidate identifier",
    body: "Type the candidate's anonymous session ID (UUID) into the Session Control panel. The platform never stores or processes personal identifiers — the UUID is the only link between the recorded session and the downstream hiring workflow.",
  },
  {
    title: "Confirm monitoring disclosure",
    body: "Verify that the candidate has acknowledged the monitoring disclosure notice before the session begins. This requirement is outside the platform's scope — it should be handled through your ATS or pre-screening workflow, and its completion should be logged.",
  },
  {
    title: "Select interview type",
    body: "Choose Technical, Behavioural, or Case Study. This adjusts the perplexity baseline — scripted technical answer sets have lower natural perplexity than open-ended behavioural questions. Using the wrong type inflates or suppresses the perplexity signal.",
  },
  {
    title: "Start the session",
    body: "Click 'Start session'. The browser initialises the MediaRecorder pipeline and begins streaming 250ms audio chunks via WebSocket. The signal bars and transcript panel become active within 10–15 seconds of the first candidate turn.",
  },
];

const SIGNAL_REF = [
  {
    name: "Response Latency",
    weight: "22%",
    body: "Measures pre-answer pause variance across turns. Natural thinkers pause inconsistently: briefly for easy questions, longer for complex ones. A consistent 3.0–3.5s gap before every answer — regardless of question complexity — matches the LLM inference + earpiece playback pattern. The model tracks both mean pause duration and the coefficient of variation across turns.",
    threshold: "Mean pause > 2.8s and CV < 0.25 across ≥ 5 candidate turns",
  },
  {
    name: "Background Audio",
    weight: "18%",
    body: "A CNN audio classifier runs on candidate-silence windows between turns. It distinguishes four classes: silence, voice overlap, mechanical keyboard activity, and ambient environmental noise. Keystroke bursts during thinking pauses are consistent with real-time AI querying and clipboard operations. The model was trained on a dataset of 40,000 labeled audio segments.",
    threshold: "Keystroke classification > 0.60 in more than 30% of silence windows",
  },
  {
    name: "Perplexity",
    weight: "26%",
    body: "GPT-2 assigns a perplexity score to each candidate turn. Human speech has natural variation: filler words, reformulations, domain jargon, incomplete sentences. AI-generated text is predictably low-perplexity — lexically consistent, syntactically regular, and free of the false starts that characterise genuine spoken explanation. Very low perplexity sustained across multiple turns is the single strongest individual signal.",
    threshold: "Mean turn perplexity below 15 over four or more candidate turns",
  },
  {
    name: "Burstiness",
    weight: "17%",
    body: "Computes the coefficient of variation in sentence length across a candidate's turns. Human speech is naturally bursty: a long technical explanation, then a short clarifying sentence, then an anecdote. AI-generated text produces sentence-length distributions that are statistically more uniform — a CV consistently below the human baseline across a session.",
    threshold: "Sentence-length CV below 0.30 over six or more sentences",
  },
  {
    name: "Semantic Similarity",
    weight: "17%",
    body: "SBERT embeddings of candidate turns are compared against a curated bank of 300+ canonical AI-generated responses to standard technical interview questions. The bank is updated nightly by the Airflow retraining DAG as new AI answer patterns emerge. High cosine similarity to a known AI-generated answer pattern is treated as corroborating evidence when at least one other signal is also elevated.",
    threshold: "Top-1 cosine similarity > 0.82, or mean top-5 > 0.74",
  },
];

const SCORE_TIERS = [
  {
    range: "70 – 100", label: "Low Risk", hex: "#27b97c",
    action: "Proceed with the standard hiring process. No additional verification is recommended based on this dimension alone. The session showed no pattern consistent with AI-assisted response.",
  },
  {
    range: "40 – 69", label: "Moderate Risk", hex: "#f07020",
    action: "Consider a follow-up technical screen, a live coding challenge, or an asynchronous take-home exercise before advancing the candidate. One or more signals were elevated but did not cross the flag threshold.",
  },
  {
    range: "0 – 39", label: "High Risk", hex: "#e03448",
    action: "Escalate for human review. Consider an in-person or proctored assessment. Do not use this score as the sole basis for rejection — review the signal breakdown and the written flag explanation before deciding.",
  },
];

const PAIN_POINTS = [
  {
    heading: "AI assistants answer in ~3 seconds",
    body: "A candidate with an earpiece or screen reader can receive ChatGPT, Claude, or Gemini output and read it aloud with a consistent 3.0–3.5s lead time. Repeated across 10 technical turns, this produces a flat pause-variance signature that is statistically distinct from genuine live thinking.",
  },
  {
    heading: "Human interviewers cannot detect it reliably",
    body: "Research on human detection of AI-generated text shows accuracy only marginally above chance (~54%) for untrained evaluators. Interviewers focusing on content quality cannot simultaneously monitor response timing patterns, sentence-length distributions, and ambient audio — and should not be expected to.",
  },
  {
    heading: "Existing tools cover a different threat surface",
    body: "Plagiarism detection tools (Turnitin, Moss) compare submitted text documents. Resume verification services validate credentials. Neither category addresses real-time verbal interview assistance, which leaves a gap in the integrity coverage of remote technical hiring.",
  },
  {
    heading: "AI-generated resumes and repositories pass automated screening",
    body: "Candidates now submit resumes and GitHub repositories produced almost entirely by AI — uniform vocabulary, suspiciously clean commit histories, boilerplate-heavy code. Standard ATS keyword matching and manual review cannot distinguish these at scale. By the time the live interview reveals the gap, significant recruiter time has already been invested.",
  },
];

const VALUE_PROPS = [
  {
    title: "Consistent evaluation criteria",
    body: "The same five signals, the same thresholds, applied identically to every session. Human raters vary in attention, fatigue, and familiarity with AI patterns — the model does not.",
  },
  {
    title: "Auditable flags with written explanations",
    body: "Every flagged session includes a human-readable explanation attached to the alert payload. The specific signals that contributed, their individual scores, and the weighted sum are all surfaced — no black-box outcome.",
  },
  {
    title: "Asynchronous scoring within 60 seconds",
    body: "The scoring pipeline runs after the session ends. The recruiter receives a result within 60 seconds of call completion without interrupting the interview itself or requiring any synchronous judgment during the conversation.",
  },
  {
    title: "Pre-screening before the interview even begins",
    body: "Resume, repository, and cross-correlation signals are scored asynchronously after upload — before a recruiter invests time in a live session. A combined pre-screening score surfaces high-risk candidates early, allowing the live interview to be replaced with a proctored challenge or skipped entirely.",
  },
];

const LIMITATIONS = [
  { label: "Language calibration", body: "The perplexity and semantic similarity models are calibrated on English-language interview transcripts. Applying them to other languages without local recalibration will produce unreliable scores." },
  { label: "Audio-only surface", body: "The background audio classifier detects keyboard activity and ambient noise. It does not detect candidates using silent input methods, on-screen text, or voice-to-text tools without keyboard interaction." },
  { label: "False positive rate", body: "At default thresholds, approximately 1.5–2.5% of genuine human sessions will cross the suspicion threshold. With 50 sessions per month, this implies roughly one false positive per month at scale." },
  { label: "Model drift", body: "AI assistant providers change their output latency, vocabulary, and phrasing across model versions. The nightly retraining DAG mitigates this, but there will be a degradation window of up to 24 hours after a major LLM update." },
];

const STACK_ROWS = [
  { layer: "Frontend",    tech: "React 19, TypeScript strict, Vite 5",              role: "Browser UI, WebSocket audio streaming, real-time score display"          },
  { layer: "State",       tech: "Zustand 4",                                         role: "Minimal global state (session, theme). No Redux, no server-state library" },
  { layer: "API gateway", tech: "FastAPI (Python 3.12)",                             role: "WebSocket handler, REST endpoints, audio routing to MinIO and Kafka"      },
  { layer: "Event bus",   tech: "Apache Kafka 3.x",                                  role: "Three append-only topics: audio-stream, text-stream, scoring-events"      },
  { layer: "Audio store", tech: "MinIO (S3-compatible)",                             role: "Raw audio chunk storage. Retention: 7–90 days. Deletion enforced at 90"   },
  { layer: "Database",    tech: "PostgreSQL 16",                                     role: "Session metadata, scored transcripts, signal breakdowns"                  },
  { layer: "ASR",         tech: "OpenAI Whisper (large-v3)",                        role: "Audio-to-text transcription. Runs as a Kafka consumer on audio-stream"    },
  { layer: "ML models",   tech: "scikit-learn, HuggingFace Transformers, SBERT",    role: "Five independent signal scorers. Retrained nightly via Airflow"           },
  { layer: "Orchestration", tech: "Apache Airflow 2.x",                             role: "Nightly retraining DAG at 02:00 UTC. No ad-hoc production retraining"     },
  { layer: "Container",   tech: "Docker Compose (dev), Kubernetes (prod)",          role: "Service isolation, health checks, rolling deployments"                    },
];

const KAFKA_TOPICS = [
  { topic: "interview-audio-stream",    retention: "24h",     key: "session_uuid",    value: "Audio chunk (binary, webm/opus, 250ms)",                         consumer: "Whisper ASR service"                     },
  { topic: "interview-text-stream",     retention: "7 days",  key: "session_uuid",    value: "Transcript turn JSON (speaker, text, ts)",                       consumer: "Five signal processors"                  },
  { topic: "scoring-events",            retention: "30 days", key: "session_uuid",    value: "Final score JSON (trust_score, signals, flagged)",                consumer: "API gateway, webhook dispatcher"          },
  { topic: "candidate-resume-stream",   retention: "90 days", key: "candidate_uuid",  value: "Resume upload event JSON (uuid, s3_key, parsed_sections_count)", consumer: "Resume Detector DAG (03:00 UTC)"         },
  { topic: "candidate-repo-stream",     retention: "90 days", key: "candidate_uuid",  value: "Repo scan event JSON (uuid, repo_url, file_count)",              consumer: "Repo Detector DAG (04:00 UTC)"           },
  { topic: "candidate-profile-stream",  retention: "90 days", key: "candidate_uuid",  value: "Pre-screening result JSON (uuid, score, flagged, severity)",     consumer: "Pre-screening API, Delta Lake writer"    },
];

const ML_MODELS = [
  { signal: "Response Latency",         type: "Statistical",           features: "pause_duration_ms, variance_coefficient, silence_ratio",                                    accuracy: "88.7%", fp: "1.8%" },
  { signal: "Background Audio",         type: "CNN classifier",        features: "MFCC spectrum, silence_snr, ambient_freq_peak",                                             accuracy: "92.3%", fp: "1.2%" },
  { signal: "Perplexity",               type: "GPT-2 scorer",          features: "token_perplexity, sentence_entropy, ngram_ratio",                                           accuracy: "90.1%", fp: "2.1%" },
  { signal: "Burstiness",               type: "Statistical",           features: "sentence_len_cv, burst_ratio, long_run_ratio",                                              accuracy: "85.6%", fp: "2.4%" },
  { signal: "Semantic Similarity",      type: "SBERT cosine",          features: "cosine_sim, top_k_coverage, answer_overlap",                                                accuracy: "93.4%", fp: "1.5%" },
  { signal: "Resume Detector",          type: "GPT-2 + Statistical",   features: "perplexity, burstiness_cv, vocab_richness, section_uniformity",                             accuracy: "87.2%", fp: "2.0%" },
  { signal: "Repo Detector",            type: "CodeBERT + Statistical", features: "code_perplexity, commit_velocity_burst, line_entropy, boilerplate_ratio, edit_distance",   accuracy: "84.9%", fp: "2.3%" },
  { signal: "Pre-Screening Aggregator", type: "Weighted combiner",     features: "resume_ai_score × 0.35, repo_ai_score × 0.35, interview_trust_inv × 0.30",                  accuracy: "91.1%", fp: "1.7%" },
  { signal: "Cross-Correlator",         type: "SBERT cosine + Δvar",   features: "skill_coherence (resume ↔ readme), style_bridge_delta (resume ↔ transcript)",               accuracy: "82.4%", fp: "2.8%" },
];

const SECURITY_RULES = [
  { rule: "No PII in logs",             detail: "Candidate names, email addresses, and recruiter identifiers appear as UUIDs in all log lines, Kafka message payloads, and database records." },
  { rule: "90-day audio deletion",      detail: "Raw audio files are deleted from MinIO within 90 days of recording. Extended retention requires explicit customer opt-in; the platform enforces the hard cap." },
  { rule: "Append-only event streams",  detail: "Kafka topics interview-audio-stream and interview-text-stream are append-only. Delete and update operations on these topics are not implemented and are blocked at the broker ACL level." },
  { rule: "No ad-hoc model retraining", detail: "ML model updates require a nightly Airflow DAG run. Triggering a retrain in production without a corresponding DAG task entry is not supported through the API." },
  { rule: "Mandatory flag explanation",  detail: "Every flagged session carries a human-readable explanation in the alert payload. Silent suppression of False Positive alerts is prohibited by the platform's alert dispatch logic." },
  { rule: "No secrets in code",          detail: "API keys, database credentials, and Kafka broker passwords are loaded via python-dotenv from .env files. No credential appears in source code or version control." },
];

// ── Style constants ───────────────────────────────────────────────────────────

const CARD: CSSProperties = {
  backgroundColor: "var(--white)",
  border: "1px solid var(--primary-10)",
  borderRadius: 14,
  padding: 28,
  boxShadow: "var(--shadow-card)",
};

const BODY_WRAP: CSSProperties = {
  maxWidth: 1240,
  margin: "0 auto",
  padding: "40px 56px 80px",
};

const H2_STYLE: CSSProperties = {
  fontFamily: "var(--fd)",
  fontSize: 24,
  fontWeight: 300,
  color: "var(--primary)",
  marginBottom: 6,
  marginTop: 0,
  lineHeight: 1.2,
};

const BODY_TEXT: CSSProperties = {
  fontFamily: "var(--fb)",
  fontSize: 13,
  color: "var(--mid)",
  lineHeight: 1.75,
  margin: 0,
};

const TH: CSSProperties = {
  textAlign: "left",
  padding: "10px 16px",
  fontSize: 9,
  letterSpacing: "2px",
  textTransform: "uppercase",
  fontWeight: 600,
  color: "#ffffff",
  whiteSpace: "nowrap",
};

const TD: CSSProperties = {
  padding: "11px 16px",
  fontSize: 12,
  fontFamily: "var(--fb)",
  color: "var(--dark)",
  borderBottom: "1px solid var(--primary-10)",
  verticalAlign: "top",
};

// ── SVG Diagrams ──────────────────────────────────────────────────────────────

function ArchDiagram() {
  const SIGNALS_LIST = [
    "Response Latency",
    "Background Audio",
    "Perplexity · GPT-2",
    "Burstiness",
    "Semantic Similarity",
  ];

  return (
    <svg
      viewBox="0 0 820 310"
      width="100%"
      aria-label="System architecture: Browser connects to FastAPI which publishes to Kafka. Signal processors consume from Kafka and store results in PostgreSQL. MinIO stores audio. Whisper transcribes audio. Airflow runs nightly retraining."
      style={{ display: "block" }}
    >
      <defs>
        <marker id="ag" markerWidth="7" markerHeight="7" refX="5.5" refY="3.5" orient="auto">
          <path d="M0,0 L7,3.5 L0,7 Z" fill="#c8982a" />
        </marker>
        <marker id="an" markerWidth="7" markerHeight="7" refX="5.5" refY="3.5" orient="auto">
          <path d="M0,0 L7,3.5 L0,7 Z" fill="#99bbdd" />
        </marker>
      </defs>

      {/* Layer labels */}
      {[
        { x: 10,  t: "CLIENT"     },
        { x: 162, t: "GATEWAY"    },
        { x: 332, t: "EVENT BUS"  },
        { x: 500, t: "PROCESSING" },
        { x: 708, t: "STORAGE"    },
      ].map(({ x, t }) => (
        <text key={t} x={x} y={20} fill="#6b7280"
          fontFamily="'Plus Jakarta Sans', sans-serif"
          fontSize={8} fontWeight={700} letterSpacing={2}>
          {t}
        </text>
      ))}

      {/* ── Row 1: main pipeline ─────────────────────────────────── */}

      {/* Browser */}
      <rect x={10}  y={34} width={112} height={66} rx={8} fill="#003366" />
      <text x={66}  y={63}  textAnchor="middle" fill="#ffffff" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={12} fontWeight={600}>Browser</text>
      <text x={66}  y={82}  textAnchor="middle" fill="#e8c46a" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={9}>React 19 · Vite 5</text>

      {/* FastAPI */}
      <rect x={162} y={34} width={120} height={66} rx={8} fill="#003366" />
      <text x={222} y={63}  textAnchor="middle" fill="#ffffff" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={12} fontWeight={600}>FastAPI</text>
      <text x={222} y={82}  textAnchor="middle" fill="#e8c46a" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={9}>Python 3.12</text>

      {/* Kafka */}
      <rect x={332} y={34} width={118} height={66} rx={8} fill="#003366" />
      <text x={391} y={58}  textAnchor="middle" fill="#ffffff" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={12} fontWeight={600}>Kafka</text>
      <text x={391} y={75}  textAnchor="middle" fill="#e8c46a" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={9}>audio-stream</text>
      <text x={391} y={90}  textAnchor="middle" fill="#e8c46a" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={9}>text-stream</text>

      {/* Signal processors (tall) */}
      <rect x={500} y={18}  width={166} height={110} rx={8} fill="#1a4d80" />
      <text x={583} y={40}  textAnchor="middle" fill="#ffffff" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={11} fontWeight={600}>Signal Processors</text>
      <line x1={514} y1={48} x2={652} y2={48} stroke="rgba(255,255,255,0.15)" strokeWidth={1} />
      {SIGNALS_LIST.map((s, i) => (
        <text key={s} x={583} y={64 + i * 14} textAnchor="middle"
          fill="rgba(255,255,255,0.65)" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={8.5}>
          {s}
        </text>
      ))}

      {/* PostgreSQL */}
      <rect x={714} y={34} width={100} height={66} rx={8} fill="#003366" />
      <text x={764} y={63}  textAnchor="middle" fill="#ffffff" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={11} fontWeight={600}>PostgreSQL</text>
      <text x={764} y={81}  textAnchor="middle" fill="#e8c46a" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={9}>scores · sessions</text>

      {/* ── Row 1 arrows ─────────────────────────────────────────── */}
      <line x1={122} y1={67} x2={162} y2={67} stroke="#c8982a" strokeWidth={1.5} markerEnd="url(#ag)" />
      <text x={142} y={60} textAnchor="middle" fill="#6b7280" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={8}>WS / HTTP</text>

      <line x1={282} y1={67} x2={332} y2={67} stroke="#c8982a" strokeWidth={1.5} markerEnd="url(#ag)" />
      <text x={307} y={60} textAnchor="middle" fill="#6b7280" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={8}>publish</text>

      <line x1={450} y1={67} x2={500} y2={67} stroke="#c8982a" strokeWidth={1.5} markerEnd="url(#ag)" />
      <text x={475} y={60} textAnchor="middle" fill="#6b7280" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={8}>consume</text>

      <line x1={666} y1={67} x2={714} y2={67} stroke="#c8982a" strokeWidth={1.5} markerEnd="url(#ag)" />
      <text x={690} y={60} textAnchor="middle" fill="#6b7280" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={8}>store</text>

      {/* ── Vertical connectors ──────────────────────────────────── */}

      {/* FastAPI → MinIO */}
      <line x1={222} y1={100} x2={222} y2={218} stroke="#99bbdd" strokeWidth={1.5} strokeDasharray="4 3" markerEnd="url(#an)" />
      <text x={232} y={164} fill="#6b7280" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={8}>audio write</text>

      {/* Kafka → Whisper (audio-stream down) */}
      <line x1={375} y1={100} x2={375} y2={218} stroke="#99bbdd" strokeWidth={1.5} strokeDasharray="4 3" markerEnd="url(#an)" />
      {/* Whisper → Kafka (text-stream up) */}
      <line x1={407} y1={218} x2={407} y2={100} stroke="#c8982a" strokeWidth={1.5} strokeDasharray="4 3" markerEnd="url(#ag)" />
      <text x={416} y={164} fill="#6b7280" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={8}>text</text>

      {/* Airflow → PostgreSQL (retrain, upward) */}
      <line x1={764} y1={218} x2={764} y2={100} stroke="#99bbdd" strokeWidth={1.5} strokeDasharray="4 3" markerEnd="url(#an)" />
      <text x={772} y={164} fill="#6b7280" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={8}>retrain</text>

      {/* ── Row 2: support services ──────────────────────────────── */}

      {/* MinIO */}
      <rect x={162} y={218} width={120} height={56} rx={8} fill="#e0eaf4" />
      <text x={222} y={244} textAnchor="middle" fill="#003366" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={12} fontWeight={600}>MinIO</text>
      <text x={222} y={262} textAnchor="middle" fill="#336699" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={9}>Audio · ≤ 90 days</text>

      {/* Whisper */}
      <rect x={332} y={218} width={118} height={56} rx={8} fill="#e0eaf4" />
      <text x={391} y={244} textAnchor="middle" fill="#003366" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={12} fontWeight={600}>Whisper ASR</text>
      <text x={391} y={262} textAnchor="middle" fill="#336699" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={9}>audio → transcript</text>

      {/* Airflow */}
      <rect x={714} y={218} width={100} height={56} rx={8} fill="#e0eaf4" />
      <text x={764} y={244} textAnchor="middle" fill="#003366" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={11} fontWeight={600}>Airflow DAG</text>
      <text x={764} y={262} textAnchor="middle" fill="#336699" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={9}>02:00 UTC nightly</text>

      {/* ── Legend ──────────────────────────────────────────────── */}
      <line x1={10} y1={296} x2={38} y2={296} stroke="#c8982a" strokeWidth={1.5} markerEnd="url(#ag)" />
      <text x={44}  y={300} fill="#6b7280" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={9}>primary data flow</text>
      <line x1={168} y1={296} x2={196} y2={296} stroke="#99bbdd" strokeWidth={1.5} strokeDasharray="4 3" markerEnd="url(#an)" />
      <text x={202} y={300} fill="#6b7280" fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={9}>support / async</text>
    </svg>
  );
}

function PipelineDiagram() {
  const STEPS = [
    { label: "Audio Capture",   sub1: "MediaRecorder API",  sub2: "250ms webm/opus chunks" },
    { label: "API Gateway",     sub1: "FastAPI WebSocket",   sub2: "MinIO write + Kafka pub"  },
    { label: "Transcription",   sub1: "Whisper ASR",        sub2: "audio → text turns"       },
    { label: "Signal Scoring",  sub1: "5 independent models", sub2: "parallel execution"     },
    { label: "Aggregation",     sub1: "Weighted sum",        sub2: "suspicion_index"          },
    { label: "Delivery",        sub1: "PostgreSQL write",    sub2: "WS push · webhook"        },
  ];

  const BW = 112;
  const BH = 76;
  const GAP = 28;
  const X0  = 10;
  const Y0  = 28;
  const W   = X0 * 2 + STEPS.length * BW + (STEPS.length - 1) * GAP;

  return (
    <svg
      viewBox={`0 0 ${W} ${Y0 + BH + 28}`}
      width="100%"
      aria-label="Data pipeline from audio capture through transcription, scoring, and delivery"
      style={{ display: "block" }}
    >
      <defs>
        <marker id="ap" markerWidth="7" markerHeight="7" refX="5.5" refY="3.5" orient="auto">
          <path d="M0,0 L7,3.5 L0,7 Z" fill="#c8982a" />
        </marker>
      </defs>

      {STEPS.map((s, i) => {
        const x  = X0 + i * (BW + GAP);
        const cx = x + BW / 2;
        const cy = Y0 + BH / 2;
        const dark = i % 2 === 0;
        return (
          <g key={s.label}>
            {/* step number */}
            <text x={cx} y={Y0 - 8} textAnchor="middle" fill="#c8982a"
              fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={8} fontWeight={700} letterSpacing={1.5}>
              {String(i + 1).padStart(2, "0")}
            </text>
            {/* box */}
            <rect x={x} y={Y0} width={BW} height={BH} rx={8}
              fill={dark ? "#003366" : "#1a4d80"} />
            {/* label */}
            <text x={cx} y={Y0 + 22} textAnchor="middle" fill="#ffffff"
              fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={11} fontWeight={600}>
              {s.label}
            </text>
            {/* sub lines */}
            <text x={cx} y={Y0 + 40} textAnchor="middle" fill="#e8c46a"
              fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={8.5}>
              {s.sub1}
            </text>
            <text x={cx} y={Y0 + 56} textAnchor="middle" fill="rgba(232,196,106,0.65)"
              fontFamily="'Plus Jakarta Sans', sans-serif" fontSize={8}>
              {s.sub2}
            </text>
            {/* arrow to next */}
            {i < STEPS.length - 1 && (
              <line
                x1={x + BW + 2} y1={cy}
                x2={x + BW + GAP - 2} y2={cy}
                stroke="#c8982a" strokeWidth={1.5} markerEnd="url(#ap)"
              />
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ── Section content views ─────────────────────────────────────────────────────

const PRESCREEN_STEPS = [
  {
    title: "Upload the candidate's resume",
    body: "Navigate to the Candidates page and add a candidate using their anonymous UUID. Upload a PDF or DOCX resume. The platform parses the document and scores four dimensions: perplexity (GPT-2), burstiness, vocabulary richness, and section uniformity. The result is a Resume AI Score in [0, 100].",
  },
  {
    title: "Link a GitHub repository (optional)",
    body: "If the candidate has submitted a GitHub repository URL, paste it into the repo linker field. The platform crawls file content and commit history, scoring code perplexity (CodeBERT), commit velocity bursts, and code style signals. The result is a Repo AI Score. If no repository is provided, this signal is omitted and weights are re-scaled.",
  },
  {
    title: "Run pre-screen",
    body: "Click 'Run Pre-Screen'. The Pre-Screening Aggregator combines the available signals into a weighted suspicion index. A score above 65 triggers a flag with a human-readable explanation. The Cross-Correlator also checks whether the skills claimed in the resume are coherent with the repository README.",
  },
];

function InstructionsView() {
  return (
    <div style={BODY_WRAP}>

      {/* ── 0. Pre-screening workflow ────────────────────────────── */}
      <section style={{ marginBottom: 48 }}>
        <div style={{ marginBottom: 24 }}>
          <Eyebrow>Pre-screening workflow</Eyebrow>
          <h2 style={{ ...H2_STYLE, marginTop: 12 }}>
            Before the <em style={{ fontStyle: "italic", color: "var(--gold)" }}>interview</em> is even scheduled
          </h2>
          <p style={{ ...BODY_TEXT, marginTop: 8, maxWidth: 640 }}>
            The pre-screening pipeline scores resume and repository submissions before a live session is arranged.
            Run it as the first step in the hiring workflow — it takes under 90 seconds and surfaces high-risk candidates early.
          </p>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
          {PRESCREEN_STEPS.map((step, i) => (
            <div key={i} style={CARD}>
              <div style={{ fontFamily: "var(--fd)", fontSize: 40, fontWeight: 300, color: "var(--primary-30)", lineHeight: 1, userSelect: "none" }}>
                {String(i).padStart(2, "0")}
              </div>
              <div style={{ width: 28, height: 3, backgroundColor: "var(--gold)", borderRadius: 2, margin: "10px 0 14px" }} />
              <div style={{ fontFamily: "var(--fb)", fontSize: 14, fontWeight: 700, color: "var(--dark)", marginBottom: 8 }}>
                {step.title}
              </div>
              <p style={BODY_TEXT}>{step.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── 1. Pre-session setup ─────────────────────────────────── */}
      <section style={{ marginBottom: 48 }}>
        <div style={{ marginBottom: 24 }}>
          <Eyebrow>Pre-session setup</Eyebrow>
          <h2 style={{ ...H2_STYLE, marginTop: 12 }}>
            Before the <em style={{ fontStyle: "italic", color: "var(--gold)" }}>interview</em> starts
          </h2>
          <p style={{ ...BODY_TEXT, marginTop: 8, maxWidth: 640 }}>
            Four steps are required before a session can be scored. All four contribute to signal quality — skipping any of them degrades the result.
          </p>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 16 }}>
          {SETUP_STEPS.map((step, i) => (
            <div key={i} style={CARD}>
              <div style={{ fontFamily: "var(--fd)", fontSize: 40, fontWeight: 300, color: "var(--primary-30)", lineHeight: 1, userSelect: "none" }}>
                {String(i + 1).padStart(2, "0")}
              </div>
              <div style={{ width: 28, height: 3, backgroundColor: "var(--gold)", borderRadius: 2, margin: "10px 0 14px" }} />
              <div style={{ fontFamily: "var(--fb)", fontSize: 14, fontWeight: 700, color: "var(--dark)", marginBottom: 8 }}>
                {step.title}
              </div>
              <p style={BODY_TEXT}>{step.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── 2. Signal reference ──────────────────────────────────── */}
      <section style={{ marginBottom: 48 }}>
        <div style={{ marginBottom: 24 }}>
          <Eyebrow>Signal reference</Eyebrow>
          <h2 style={{ ...H2_STYLE, marginTop: 12 }}>
            What each <em style={{ fontStyle: "italic", color: "var(--gold)" }}>signal</em> measures
          </h2>
          <p style={{ ...BODY_TEXT, marginTop: 8, maxWidth: 640 }}>
            Five independent models score different behavioural and linguistic dimensions. No single signal is determinative — they are combined into a weighted suspicion index. The percentage shown is each signal's contribution weight.
          </p>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {SIGNAL_REF.map((sig, i) => (
            <div key={sig.name} style={{ ...CARD, display: "grid", gridTemplateColumns: "200px 1fr", gap: 24, alignItems: "start" }}>
              <div>
                <div style={{ fontFamily: "var(--fd)", fontSize: 32, fontWeight: 300, color: "var(--primary-30)", lineHeight: 1, userSelect: "none", marginBottom: 6 }}>
                  {String(i + 1).padStart(2, "0")}
                </div>
                <div style={{ fontFamily: "var(--fb)", fontSize: 14, fontWeight: 700, color: "var(--dark)", marginBottom: 4 }}>
                  {sig.name}
                </div>
                <div style={{ height: 4, background: "var(--primary-10)", borderRadius: 2, overflow: "hidden", marginBottom: 8 }}>
                  <div style={{ height: "100%", width: sig.weight, background: "var(--primary)", borderRadius: 2, transition: "width 0.5s" }} />
                </div>
                <div style={{ fontFamily: "var(--fb)", fontSize: 10, letterSpacing: "1.5px", textTransform: "uppercase", color: "var(--primary-60)", fontWeight: 600 }}>
                  Weight: {sig.weight}
                </div>
              </div>
              <div>
                <p style={{ ...BODY_TEXT, marginBottom: 12 }}>{sig.body}</p>
                <div style={{ background: "var(--primary-10)", borderRadius: 6, padding: "8px 12px" }}>
                  <span style={{ fontFamily: "var(--fb)", fontSize: 9, letterSpacing: "2px", textTransform: "uppercase", fontWeight: 700, color: "var(--primary-60)", marginRight: 8 }}>
                    Threshold
                  </span>
                  <code style={{ fontFamily: "var(--fm)", fontSize: 11, color: "var(--dark)" }}>
                    {sig.threshold}
                  </code>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── 3. Score interpretation ──────────────────────────────── */}
      <section style={{ marginBottom: 48 }}>
        <div style={{ marginBottom: 24 }}>
          <Eyebrow>Score interpretation</Eyebrow>
          <h2 style={{ ...H2_STYLE, marginTop: 12 }}>
            Reading the <em style={{ fontStyle: "italic", color: "var(--gold)" }}>TrustScore</em>
          </h2>
          <p style={{ ...BODY_TEXT, marginTop: 8, maxWidth: 640 }}>
            The TrustScore is <code style={{ fontFamily: "var(--fm)", fontSize: 12 }}>100 − (suspicion_index × 100)</code>. A higher score indicates lower measured suspicion. Three tiers drive recommended actions.
          </p>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 2, borderRadius: 14, overflow: "hidden", border: "1px solid var(--primary-10)", boxShadow: "var(--shadow-card)" }}>
          {SCORE_TIERS.map(tier => (
            <div key={tier.label} style={{
              display: "grid", gridTemplateColumns: "10px 160px 1fr",
              background: "var(--white)", padding: "20px 24px", gap: 20,
              alignItems: "center", borderBottom: "1px solid var(--primary-10)",
            }}>
              <div style={{ width: 10, height: "100%", minHeight: 40, borderRadius: 4, background: tier.hex, alignSelf: "stretch" }} />
              <div>
                <div style={{ fontFamily: "var(--fd)", fontSize: 22, fontWeight: 300, color: tier.hex, lineHeight: 1 }}>
                  {tier.range}
                </div>
                <div style={{ fontFamily: "var(--fb)", fontSize: 11, fontWeight: 700, color: tier.hex, letterSpacing: "1.5px", textTransform: "uppercase", marginTop: 4 }}>
                  {tier.label}
                </div>
              </div>
              <p style={BODY_TEXT}>{tier.action}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── 4. Caveats ───────────────────────────────────────────── */}
      <section>
        <div style={{ marginBottom: 20 }}>
          <Eyebrow>Important caveats</Eyebrow>
          <h2 style={{ ...H2_STYLE, marginTop: 12 }}>What this system does and does <em style={{ fontStyle: "italic", color: "var(--gold)" }}>not</em> determine</h2>
        </div>
        <div style={{ ...CARD, borderLeft: "3px solid var(--gold)", display: "flex", flexDirection: "column", gap: 14 }}>
          {[
            "The system identifies behavioral patterns consistent with AI-assisted response. It does not determine intent, and a flag is not evidence of deliberate cheating.",
            "At default thresholds, a false positive rate of ~1.5–2.5% applies. With 40 sessions per month, expect statistically approximately one incorrectly flagged session each month.",
            "Always read the full signal breakdown before acting on a TrustScore or flag. The overall score may mask a single high-confidence signal that tells a different story from the aggregate.",
            "A flagged session requires human review. It does not constitute grounds for rejection on its own. Every flag carries a written explanation — use it.",
          ].map((text, i) => (
            <div key={i} style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
              <div style={{ width: 6, height: 6, borderRadius: 3, background: "var(--gold)", flexShrink: 0, marginTop: 6 }} />
              <p style={BODY_TEXT}>{text}</p>
            </div>
          ))}
        </div>
      </section>

    </div>
  );
}

function BusinessView() {
  return (
    <div style={BODY_WRAP}>

      {/* ── The problem ──────────────────────────────────────────── */}
      <section style={{ marginBottom: 48 }}>
        <div style={{ marginBottom: 24 }}>
          <Eyebrow>The problem</Eyebrow>
          <h2 style={{ ...H2_STYLE, marginTop: 12 }}>
            What the <em style={{ fontStyle: "italic", color: "var(--gold)" }}>platform</em> addresses
          </h2>
          <p style={{ ...BODY_TEXT, marginTop: 8, maxWidth: 640 }}>
            Remote technical interviews became standard after 2020. So did the availability of AI assistants capable of answering interview questions in real time. These two developments interact in a way that existing integrity tools were not designed to handle.
          </p>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {PAIN_POINTS.map((p, i) => (
            <div key={i} style={{ ...CARD, display: "grid", gridTemplateColumns: "24px 1fr", gap: 20, alignItems: "start" }}>
              <div style={{ fontFamily: "var(--fd)", fontSize: 28, fontWeight: 300, color: "var(--primary-30)", lineHeight: 1, userSelect: "none" }}>
                {i + 1}
              </div>
              <div>
                <div style={{ fontFamily: "var(--fb)", fontSize: 15, fontWeight: 700, color: "var(--dark)", marginBottom: 8 }}>
                  {p.heading}
                </div>
                <p style={BODY_TEXT}>{p.body}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Detection approach ───────────────────────────────────── */}
      <section style={{ marginBottom: 48 }}>
        <div style={{ marginBottom: 24 }}>
          <Eyebrow>Detection approach</Eyebrow>
          <h2 style={{ ...H2_STYLE, marginTop: 12 }}>
            Five <em style={{ fontStyle: "italic", color: "var(--gold)" }}>independent</em> signals
          </h2>
          <p style={{ ...BODY_TEXT, marginTop: 8, maxWidth: 680 }}>
            The platform does not attempt to "catch" cheating through a single heuristic. Five independent behavioral and linguistic signals each score one dimension of the candidate's response pattern. The signals are weighted and combined into a single suspicion index. No one signal is determinative — a candidate who pauses consistently but shows natural perplexity and burstiness is not flagged.
          </p>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12 }}>
          {[
            { n: "01", name: "Latency", detail: "Response timing variance across turns" },
            { n: "02", name: "Audio",   detail: "Keyboard and ambient noise classification" },
            { n: "03", name: "Perplexity", detail: "Linguistic predictability via GPT-2" },
            { n: "04", name: "Burstiness", detail: "Sentence-length coefficient of variation" },
            { n: "05", name: "Semantic",   detail: "Cosine match to AI answer bank" },
          ].map(({ n, name, detail }) => (
            <div key={n} style={{
              ...CARD, padding: 20,
              display: "flex", flexDirection: "column", gap: 0, textAlign: "center",
            }}>
              <div style={{ fontFamily: "var(--fd)", fontSize: 28, fontWeight: 300, color: "var(--primary-30)", lineHeight: 1, userSelect: "none" }}>{n}</div>
              <div style={{ width: 20, height: 3, backgroundColor: "var(--gold)", borderRadius: 2, margin: "8px auto 10px" }} />
              <div style={{ fontFamily: "var(--fb)", fontSize: 13, fontWeight: 700, color: "var(--dark)", marginBottom: 6 }}>{name}</div>
              <p style={{ ...BODY_TEXT, fontSize: 11, textAlign: "center" }}>{detail}</p>
            </div>
          ))}
        </div>

        {/* Aggregation note */}
        <div style={{ ...CARD, marginTop: 16, borderLeft: "3px solid var(--gold)", padding: "18px 24px" }}>
          <p style={BODY_TEXT}>
            The suspicion index is computed as a weighted sum:{" "}
            <code style={{ fontFamily: "var(--fm)", fontSize: 12 }}>
              Σ (signal_raw_score × weight)
            </code>
            . A session is flagged when this sum exceeds 0.65. The weights (22%, 18%, 26%, 17%, 17%) are fixed at deployment and reviewed quarterly against a holdout validation set. Adjustments require a DAG task entry and a full retraining run.
          </p>
        </div>
      </section>

      {/* ── Value proposition ────────────────────────────────────── */}
      <section style={{ marginBottom: 48 }}>
        <div style={{ marginBottom: 24 }}>
          <Eyebrow>Value proposition</Eyebrow>
          <h2 style={{ ...H2_STYLE, marginTop: 12 }}>
            What the system <em style={{ fontStyle: "italic", color: "var(--gold)" }}>provides</em>
          </h2>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
          {VALUE_PROPS.map(v => (
            <div key={v.title} style={CARD}>
              <div style={{ width: 32, height: 3, backgroundColor: "var(--gold)", borderRadius: 2, marginBottom: 16 }} />
              <div style={{ fontFamily: "var(--fb)", fontSize: 14, fontWeight: 700, color: "var(--dark)", marginBottom: 10 }}>
                {v.title}
              </div>
              <p style={BODY_TEXT}>{v.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Limitations ──────────────────────────────────────────── */}
      <section>
        <div style={{ marginBottom: 24 }}>
          <Eyebrow>Scope and limitations</Eyebrow>
          <h2 style={{ ...H2_STYLE, marginTop: 12 }}>
            What the system does <em style={{ fontStyle: "italic", color: "var(--gold)" }}>not</em> cover
          </h2>
          <p style={{ ...BODY_TEXT, marginTop: 8, maxWidth: 640 }}>
            These constraints are not gaps to be fixed — they are the boundaries within which the model was designed and validated. Operating outside them produces unreliable results.
          </p>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 16 }}>
          {LIMITATIONS.map(l => (
            <div key={l.label} style={{ ...CARD, display: "grid", gridTemplateColumns: "3px 1fr", gap: 20, paddingLeft: 18 }}>
              <div style={{ background: "var(--primary-30)", borderRadius: 2 }} />
              <div>
                <div style={{ fontFamily: "var(--fb)", fontSize: 13, fontWeight: 700, color: "var(--dark)", marginBottom: 6 }}>
                  {l.label}
                </div>
                <p style={BODY_TEXT}>{l.body}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

    </div>
  );
}

function EngineeringView() {
  return (
    <div style={BODY_WRAP}>

      {/* ── Stack overview ───────────────────────────────────────── */}
      <section style={{ marginBottom: 48 }}>
        <div style={{ marginBottom: 24 }}>
          <Eyebrow>Technology stack</Eyebrow>
          <h2 style={{ ...H2_STYLE, marginTop: 12 }}>
            Components and their <em style={{ fontStyle: "italic", color: "var(--gold)" }}>roles</em>
          </h2>
        </div>

        <div style={{ ...CARD, padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--primary)" }}>
                {["Layer", "Technology", "Role"].map(h => (
                  <th key={h} style={TH}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {STACK_ROWS.map((r, i) => (
                <tr key={r.layer} style={{ background: i % 2 === 0 ? "var(--white)" : "var(--light)" }}>
                  <td style={{ ...TD, fontFamily: "var(--fb)", fontWeight: 700, color: "var(--primary)", whiteSpace: "nowrap" }}>
                    {r.layer}
                  </td>
                  <td style={{ ...TD, fontFamily: "var(--fm)", fontSize: 11, color: "var(--primary-60)" }}>
                    {r.tech}
                  </td>
                  <td style={{ ...TD, color: "var(--mid)" }}>
                    {r.role}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── Architecture diagram ─────────────────────────────────── */}
      <section style={{ marginBottom: 48 }}>
        <div style={{ marginBottom: 24 }}>
          <Eyebrow>System architecture</Eyebrow>
          <h2 style={{ ...H2_STYLE, marginTop: 12 }}>
            Services and <em style={{ fontStyle: "italic", color: "var(--gold)" }}>connections</em>
          </h2>
          <p style={{ ...BODY_TEXT, marginTop: 8, maxWidth: 680 }}>
            The primary data flow runs left-to-right through the main pipeline row. Support services (MinIO, Whisper, Airflow) connect vertically to their primary counterparts. All inter-service communication except the WebSocket channel is mediated by Kafka.
          </p>
        </div>

        <div style={CARD}>
          <ArchDiagram />
        </div>
      </section>

      {/* ── Data pipeline ────────────────────────────────────────── */}
      <section style={{ marginBottom: 48 }}>
        <div style={{ marginBottom: 24 }}>
          <Eyebrow>Data pipeline</Eyebrow>
          <h2 style={{ ...H2_STYLE, marginTop: 12 }}>
            From microphone to <em style={{ fontStyle: "italic", color: "var(--gold)" }}>score</em>
          </h2>
          <p style={{ ...BODY_TEXT, marginTop: 8, maxWidth: 680 }}>
            Audio captured in the browser travels through six processing stages before a TrustScore is available. The total latency from session end to score delivery is under 60 seconds under normal load conditions.
          </p>
        </div>

        <div style={CARD}>
          <PipelineDiagram />
          <div style={{ marginTop: 20, paddingTop: 16, borderTop: "1px solid var(--primary-10)", display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
            {[
              { label: "Audio chunk size", value: "250ms", note: "webm/opus, ≈8 KB per chunk" },
              { label: "Transcription lag", value: "~4s",  note: "Whisper large-v3, 8× real-time" },
              { label: "End-to-end latency", value: "<60s", note: "from session end to score available" },
            ].map(({ label, value, note }) => (
              <div key={label}>
                <div style={{ fontFamily: "var(--fb)", fontSize: 9, letterSpacing: "2px", textTransform: "uppercase", fontWeight: 600, color: "var(--mid)", marginBottom: 4 }}>
                  {label}
                </div>
                <div style={{ fontFamily: "var(--fd)", fontSize: 22, fontWeight: 300, color: "var(--primary)", lineHeight: 1, marginBottom: 4 }}>
                  {value}
                </div>
                <div style={{ fontFamily: "var(--fb)", fontSize: 11, color: "var(--mid)" }}>
                  {note}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Kafka topics ─────────────────────────────────────────── */}
      <section style={{ marginBottom: 48 }}>
        <div style={{ marginBottom: 24 }}>
          <Eyebrow>Kafka topics</Eyebrow>
          <h2 style={{ ...H2_STYLE, marginTop: 12 }}>
            Event stream <em style={{ fontStyle: "italic", color: "var(--gold)" }}>reference</em>
          </h2>
          <p style={{ ...BODY_TEXT, marginTop: 8, maxWidth: 640 }}>
            All topics are append-only. Delete and update operations are blocked at the broker ACL level. The first three topics use the session UUID as partition key; the pre-screening topics use the candidate UUID.
          </p>
        </div>

        <div style={{ ...CARD, padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--primary)" }}>
                {["Topic", "Retention", "Key", "Value schema", "Consumer"].map(h => (
                  <th key={h} style={TH}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {KAFKA_TOPICS.map((r, i) => (
                <tr key={r.topic} style={{ background: i % 2 === 0 ? "var(--white)" : "var(--light)" }}>
                  <td style={{ ...TD, fontFamily: "var(--fm)", fontSize: 11, color: "var(--primary-60)", whiteSpace: "nowrap" }}>
                    {r.topic}
                  </td>
                  <td style={{ ...TD, whiteSpace: "nowrap", color: "var(--mid)" }}>{r.retention}</td>
                  <td style={{ ...TD, fontFamily: "var(--fm)", fontSize: 11, color: "var(--dark)" }}>{r.key}</td>
                  <td style={{ ...TD, color: "var(--mid)" }}>{r.value}</td>
                  <td style={{ ...TD, color: "var(--mid)" }}>{r.consumer}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── ML models ────────────────────────────────────────────── */}
      <section style={{ marginBottom: 48 }}>
        <div style={{ marginBottom: 24 }}>
          <Eyebrow>ML model registry</Eyebrow>
          <h2 style={{ ...H2_STYLE, marginTop: 12 }}>
            Signal model <em style={{ fontStyle: "italic", color: "var(--gold)" }}>specifications</em>
          </h2>
          <p style={{ ...BODY_TEXT, marginTop: 8, maxWidth: 640 }}>
            Each model is trained and validated independently. Accuracy and false positive rates are measured on a 20% holdout set from the most recent 30-day window. A model is deployed only when both thresholds pass: accuracy ≥ 85%, FP rate ≤ 3%.
          </p>
        </div>

        <div style={{ ...CARD, padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--primary)" }}>
                {["Signal", "Model type", "Feature set", "Accuracy", "FP rate"].map(h => (
                  <th key={h} style={TH}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ML_MODELS.map((m, i) => (
                <tr key={m.signal} style={{ background: i % 2 === 0 ? "var(--white)" : "var(--light)" }}>
                  <td style={{ ...TD, fontWeight: 600 }}>{m.signal}</td>
                  <td style={{ ...TD, fontFamily: "var(--fm)", fontSize: 11, color: "var(--primary-60)" }}>{m.type}</td>
                  <td style={{ ...TD, fontFamily: "var(--fm)", fontSize: 10, color: "var(--mid)" }}>{m.features}</td>
                  <td style={{ ...TD, fontFamily: "var(--fd)", fontSize: 18, fontWeight: 300, color: "var(--verde-dark)", verticalAlign: "middle" }}>
                    {m.accuracy}
                  </td>
                  <td style={{ ...TD, fontFamily: "var(--fd)", fontSize: 18, fontWeight: 300, color: "var(--mid)", verticalAlign: "middle" }}>
                    {m.fp}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── Security invariants ───────────────────────────────────── */}
      <section>
        <div style={{ marginBottom: 24 }}>
          <Eyebrow>Security invariants</Eyebrow>
          <h2 style={{ ...H2_STYLE, marginTop: 12 }}>
            Non-negotiable <em style={{ fontStyle: "italic", color: "var(--gold)" }}>constraints</em>
          </h2>
          <p style={{ ...BODY_TEXT, marginTop: 8, maxWidth: 640 }}>
            These rules are enforced at the platform level — they are not configuration options. Any component that violates them fails its CI health check and is blocked from deployment.
          </p>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {SECURITY_RULES.map((r, i) => (
            <div key={i} style={{
              ...CARD,
              display: "grid", gridTemplateColumns: "220px 1fr",
              gap: 24, alignItems: "start",
            }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                <span style={{
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  width: 28, height: 28, borderRadius: "50%",
                  background: "var(--primary)", flexShrink: 0,
                  fontFamily: "var(--fd)", fontSize: 13, fontWeight: 300, color: "var(--gold-light)",
                }}>
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div style={{ fontFamily: "var(--fb)", fontSize: 13, fontWeight: 700, color: "var(--dark)", lineHeight: 1.4, paddingTop: 4 }}>
                  {r.rule}
                </div>
              </div>
              <p style={BODY_TEXT}>{r.detail}</p>
            </div>
          ))}
        </div>
      </section>

    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

const TABS: { id: Tab; label: string }[] = [
  { id: "instructions", label: "Instructions"     },
  { id: "business",     label: "Business View"    },
  { id: "engineering",  label: "Engineering View" },
];

export function InfoPage() {
  const [tab, setTab] = useState<Tab>("instructions");

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>

      {/* ── Hero + tab bar ───────────────────────────────────────── */}
      <div style={{ padding: "0 56px", maxWidth: 1440, margin: "0 auto", width: "100%", boxSizing: "border-box" }}>
        <div className="hero" style={{ marginBottom: 0, borderBottomLeftRadius: 0, borderBottomRightRadius: 0 }}>
          <div className="hero-top">
            <div className="hero-id">
              <Eyebrow variant="dark">Documentation</Eyebrow>
            </div>
          </div>

          <div className="hero-body" style={{ gap: 0 }}>
            <div>
              <h1>Platform <em>overview</em></h1>
              <p className="lede">
                Three views of the same system — a recruiter workflow guide, a business framing of the problem and approach, and a technical architecture reference for engineers.
              </p>
            </div>
          </div>

          {/* Tab bar */}
          <div style={{ display: "flex", gap: 0, marginTop: 24, borderTop: "1px solid rgba(255,255,255,0.1)", marginLeft: -40, marginRight: -40, paddingLeft: 40 }}>
            {TABS.map(t => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                style={{
                  padding: "14px 28px",
                  background: "none",
                  border: "none",
                  borderBottom: tab === t.id ? "2px solid var(--gold-light)" : "2px solid transparent",
                  color: tab === t.id ? "var(--gold-light)" : "rgba(255,255,255,0.4)",
                  cursor: "pointer",
                  fontFamily: "var(--fb)",
                  fontSize: 11,
                  fontWeight: 600,
                  letterSpacing: "2.5px",
                  textTransform: "uppercase",
                  transition: "color 0.15s ease, border-color 0.15s ease",
                }}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Tab content ─────────────────────────────────────────── */}
      <div style={{ flex: 1, backgroundColor: "var(--light)" }}>
        {tab === "instructions" && <InstructionsView />}
        {tab === "business"     && <BusinessView />}
        {tab === "engineering"  && <EngineeringView />}
      </div>

    </div>
  );
}

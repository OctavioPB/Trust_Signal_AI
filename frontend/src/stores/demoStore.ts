import { create } from "zustand";
import type { ReportResponse } from "../types";

const DEMO_SCENARIO: ReportResponse = {
  session_id: "demo-session-0001-0000-0000-000000000000",
  recruiter_id: "demo-recruiter-0000-0000-0000-000000000000",
  status: "flagged",
  start_ts: Date.now() / 1000 - 900,
  end_ts: Date.now() / 1000,
  trust_score: 31.5,
  suspicion_index: 0.685,
  flagged: true,
  flag_reason:
    "Suspicion index 0.685 exceeds threshold 0.65.\n" +
    "• Response latency is unusually constant (σ = 0.08 s) across 12 turns — consistent with LLM inference delay.\n" +
    "• Burstiness score 0.78 indicates homogeneous sentence-length distribution typical of AI-generated text.\n" +
    "• Semantic similarity 0.82 to canonical LLM answer bank exceeds the 0.75 high-risk threshold.",
  signals: [
    {
      signal_name: "Response Latency",
      raw_score: 0.82,
      weight: 0.30,
      weighted_contribution: 0.246,
      explanation:
        "Candidate response onset was consistently 3.1–3.4 s after question end across all turns. " +
        "Natural speakers show variance of 0.5–2.5 s depending on question complexity.",
    },
    {
      signal_name: "Background Audio",
      raw_score: 0.45,
      weight: 0.15,
      weighted_contribution: 0.0675,
      explanation:
        "Intermittent mechanical keyboard activity detected in 4 of 12 silence windows. " +
        "Below the high-risk threshold but contributes to overall suspicion.",
    },
    {
      signal_name: "Perplexity",
      raw_score: 0.71,
      weight: 0.20,
      weighted_contribution: 0.142,
      explanation:
        "Transcript perplexity (GPT-2) is low, indicating predictable, fluent text unlikely to arise in spontaneous speech.",
    },
    {
      signal_name: "Burstiness",
      raw_score: 0.78,
      weight: 0.20,
      weighted_contribution: 0.156,
      explanation:
        "Sentence-length variance is in the bottom 8th percentile of authentic candidate transcripts. " +
        "Human speech is naturally bursty; this transcript is unusually uniform.",
    },
    {
      signal_name: "Semantic Similarity",
      raw_score: 0.82,
      weight: 0.15,
      weighted_contribution: 0.123,
      explanation:
        "Answer embeddings match canonical LLM-generated responses with cosine similarity 0.82. " +
        "Threshold for elevated concern is 0.75.",
    },
  ],
  turns: [
    { speaker: "RECRUITER", text: "Tell me about a challenging project you led.", suspicion_score: 0.1 },
    { speaker: "CANDIDATE", text: "Certainly. In my previous role I spearheaded a data migration initiative that involved coordinating cross-functional stakeholders across three time zones.", suspicion_score: 0.71 },
    { speaker: "RECRUITER", text: "How did you handle disagreements in the team?", suspicion_score: 0.05 },
    { speaker: "CANDIDATE", text: "I employed a structured conflict-resolution framework, prioritising active listening and data-driven decision-making to reach consensus efficiently.", suspicion_score: 0.79 },
  ],
};

interface DemoState {
  isDemo: boolean;
  scenario: ReportResponse;
  setDemo: (on: boolean) => void;
  clearDemo: () => void;
}

export const useDemoStore = create<DemoState>((set) => ({
  isDemo: false,
  scenario: DEMO_SCENARIO,
  setDemo: (on) => set({ isDemo: on }),
  clearDemo: () => set({ isDemo: false }),
}));

import { create } from "zustand";
import type { Candidate, CandidateStatus } from "../types";

// ── Demo data (shown before any real API is wired) ────────────────────────────

const _DEMO: Candidate[] = [
  {
    candidate_uuid: "a1b2c3d4-0000-0000-0000-000000000001",
    status: "flagged",
    resume_ai_score: 82.4,
    repo_ai_score: 74.1,
    prescreening_score: 79.3,
    interview_trust_score: 22.0,
    flagged: true,
    severity: "high",
    flag_reason: "Resume AI score 82.4 (high suspicion). Interview trust 22.0 (very low — strong AI-assist signal).",
    signals: [
      { signal_name: "Resume AI Score",           raw_suspicion: 0.824, weight: 0.35, weighted_contribution: 0.2884, explanation: "Perplexity and burstiness patterns consistent with AI-generated text." },
      { signal_name: "Repo AI Score",             raw_suspicion: 0.741, weight: 0.35, weighted_contribution: 0.2594, explanation: "Commit velocity burst and uniform line-length entropy detected." },
      { signal_name: "Interview Trust (inverted)", raw_suspicion: 0.780, weight: 0.30, weighted_contribution: 0.2340, explanation: "Trust score 22.0 — consistent pause timing and low-perplexity turns." },
    ],
    repo_url: "https://github.com/testuser/sample-repo",
    scored_at: Date.now() / 1000 - 3600,
    created_at: Date.now() / 1000 - 86400,
  },
  {
    candidate_uuid: "b2c3d4e5-0000-0000-0000-000000000002",
    status: "screened",
    resume_ai_score: 18.7,
    repo_ai_score: 22.3,
    prescreening_score: 20.5,
    interview_trust_score: 81.0,
    flagged: false,
    severity: "low",
    flag_reason: "",
    signals: [
      { signal_name: "Resume AI Score",           raw_suspicion: 0.187, weight: 0.35, weighted_contribution: 0.0655, explanation: "Natural variance and burstiness typical of human writing." },
      { signal_name: "Repo AI Score",             raw_suspicion: 0.223, weight: 0.35, weighted_contribution: 0.0781, explanation: "Commit history shows organic development cadence." },
      { signal_name: "Interview Trust (inverted)", raw_suspicion: 0.190, weight: 0.30, weighted_contribution: 0.0570, explanation: "Trust score 81.0 — natural pause variance and high-perplexity turns." },
    ],
    repo_url: "https://github.com/alice/portfolio",
    scored_at: Date.now() / 1000 - 7200,
    created_at: Date.now() / 1000 - 172800,
  },
  {
    candidate_uuid: "c3d4e5f6-0000-0000-0000-000000000003",
    status: "screened",
    resume_ai_score: 45.2,
    repo_ai_score: null,
    prescreening_score: 45.2,
    interview_trust_score: null,
    flagged: false,
    severity: "low",
    flag_reason: "",
    signals: [
      { signal_name: "Resume AI Score", raw_suspicion: 0.452, weight: 1.0, weighted_contribution: 0.4520, explanation: "Moderate suspicion — some uniform phrasing but natural vocabulary richness." },
    ],
    repo_url: null,
    scored_at: Date.now() / 1000 - 14400,
    created_at: Date.now() / 1000 - 259200,
  },
  {
    candidate_uuid: "d4e5f6a7-0000-0000-0000-000000000004",
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
    created_at: Date.now() / 1000 - 1800,
  },
];

// ── Store ─────────────────────────────────────────────────────────────────────

type Tab = "all" | "pending" | "flagged";

interface CandidatesState {
  candidates: Candidate[];
  selectedId: string | null;
  loadingList: boolean;
  loadingUpload: boolean;
  loadingScreen: boolean;
  error: string | null;
  activeTab: Tab;

  setTab: (tab: Tab) => void;
  selectCandidate: (id: string | null) => void;
  addCandidate: (candidate: Candidate) => void;
  fetchCandidates: (token: string) => Promise<void>;
  uploadResume: (token: string, candidateUuid: string, file: File) => Promise<void>;
  linkRepo: (token: string, candidateUuid: string, repoUrl: string) => Promise<void>;
  runPreScreen: (token: string, candidateUuid: string) => Promise<void>;
}

export const useCandidatesStore = create<CandidatesState>((set, get) => ({
  candidates: _DEMO,
  selectedId: null,
  loadingList: false,
  loadingUpload: false,
  loadingScreen: false,
  error: null,
  activeTab: "all",

  setTab: (tab) => set({ activeTab: tab }),
  selectCandidate: (id) => set({ selectedId: id }),

  addCandidate: (candidate) =>
    set((s) => ({ candidates: [candidate, ...s.candidates] })),

  fetchCandidates: async (token) => {
    set({ loadingList: true, error: null });
    try {
      const { getCandidates } = await import("../services/api");
      const res = await getCandidates(token);
      set({ candidates: res.candidates });
    } catch {
      // Keep demo data on error; don't surface API errors in the UI yet
    } finally {
      set({ loadingList: false });
    }
  },

  uploadResume: async (token, candidateUuid, file) => {
    set({ loadingUpload: true, error: null });
    try {
      const { uploadResume: apiUpload } = await import("../services/api");
      await apiUpload(token, candidateUuid, file);
      set((s) => ({
        candidates: s.candidates.map((c) =>
          c.candidate_uuid === candidateUuid ? { ...c, status: "pending" as CandidateStatus } : c,
        ),
      }));
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Upload failed" });
    } finally {
      set({ loadingUpload: false });
    }
  },

  linkRepo: async (token, candidateUuid, repoUrl) => {
    try {
      const { linkRepo: apiLink } = await import("../services/api");
      await apiLink(token, candidateUuid, repoUrl);
      set((s) => ({
        candidates: s.candidates.map((c) =>
          c.candidate_uuid === candidateUuid ? { ...c, repo_url: repoUrl } : c,
        ),
      }));
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Failed to link repo" });
    }
  },

  runPreScreen: async (token, candidateUuid) => {
    set({ loadingScreen: true, error: null });
    try {
      const { triggerPreScreen } = await import("../services/api");
      const res = await triggerPreScreen(token, candidateUuid);
      set((s) => ({
        candidates: s.candidates.map((c) =>
          c.candidate_uuid === candidateUuid
            ? {
                ...c,
                status: res.flagged ? ("flagged" as CandidateStatus) : ("screened" as CandidateStatus),
                prescreening_score: res.prescreening_score,
                flagged: res.flagged,
                scored_at: Date.now() / 1000,
              }
            : c,
        ),
      }));
    } catch (err) {
      set({ error: err instanceof Error ? err.message : "Pre-screening failed" });
    } finally {
      set({ loadingScreen: false });
    }
  },
}));

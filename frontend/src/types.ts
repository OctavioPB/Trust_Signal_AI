/** TypeScript interfaces mirroring api/main.py Pydantic models exactly. */

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in_hours: number;
}

export interface SessionStartResponse {
  session_id: string;
  status: string;
  start_ts: number;
}

export interface SignalDetail {
  signal_name: string;
  raw_score: number;
  weight: number;
  weighted_contribution: number;
  explanation: string;
}

export interface ScoreResponse {
  session_id: string;
  status: string;
  trust_score: number;
  suspicion_index: number;
  flagged: boolean;
  flag_reason: string;
  signals: SignalDetail[];
}

export interface ReportResponse {
  session_id: string;
  recruiter_id: string;
  status: string;
  start_ts: number;
  end_ts: number | null;
  trust_score: number;
  suspicion_index: number;
  flagged: boolean;
  flag_reason: string;
  signals: SignalDetail[];
  turns: Record<string, unknown>[];
}

export interface SessionEndResponse {
  session_id: string;
  status: string;
  trust_score: number;
  flagged: boolean;
  flag_reason: string;
}

export interface SignalScoresRequest {
  latency_score?: number;
  bg_audio_score?: number;
  perplexity_score?: number;
  burstiness_score?: number;
  similarity_score?: number;
}

// ── Candidate pre-screening types ─────────────────────────────────────────────

export type CandidateStatus = "pending" | "screened" | "flagged";

export interface CandidateSignal {
  signal_name: string;
  raw_suspicion: number;
  weight: number;
  weighted_contribution: number;
  explanation: string;
}

export interface Candidate {
  candidate_uuid: string;
  status: CandidateStatus;
  resume_ai_score: number | null;
  repo_ai_score: number | null;
  prescreening_score: number | null;
  interview_trust_score: number | null;
  flagged: boolean;
  severity: "low" | "medium" | "high";
  flag_reason: string;
  signals: CandidateSignal[];
  repo_url: string | null;
  scored_at: number | null;
  created_at: number;
}

export interface CandidatesListResponse {
  candidates: Candidate[];
  total: number;
}

export interface PreScreeningTriggerResponse {
  candidate_uuid: string;
  status: string;
  prescreening_score: number | null;
  flagged: boolean;
}

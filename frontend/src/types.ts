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

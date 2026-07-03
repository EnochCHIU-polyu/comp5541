import { API_BASE } from "../../../lib/apiConfig";

export type BenchmarkDataset = "smartbugs" | "solidifi";
export type BenchmarkMode = "binary" | "non_binary" | "cot";
export type BenchmarkPipeline = "standard" | "cascade" | "multi_llm";
export type TrackBProfile =
  | "baseline"
  | "h1"
  | "h2"
  | "h3"
  | "h4"
  | "all"
  | "all_minus_h1"
  | "all_minus_h2"
  | "all_minus_h3"
  | "all_minus_h4";

export interface BenchmarkContractPreview {
  name: string;
  labels: string[];
  source_preview: string;
}

export interface BenchmarkLoadResponse {
  dataset: BenchmarkDataset;
  loaded: number;
  contracts: BenchmarkContractPreview[];
  vuln_types_under_test: string[];
}

export interface BenchmarkRunRequest {
  dataset: BenchmarkDataset;
  limit: number;
  prefer_shared_db: boolean;
  model: string;
  mode: BenchmarkMode;
  pipeline: BenchmarkPipeline;
  cascade_small: string;
  cascade_large: string;
  multi_models: string[];
  multi_parallel: boolean;
  multi_aggregation: "majority" | "consensus";
}

export interface BenchmarkRunResponse {
  dataset: BenchmarkDataset;
  loaded: number;
  vuln_types_under_test: string[];
  swe_mapping?: Array<{
    label: string;
    covered: boolean;
    swe_field_id: number | null;
    swe_field: string;
    swe_weakness: string;
  }>;
  scores: {
    aggregate?: {
      counts?: Record<string, number>;
      metrics?: Record<string, number>;
      skipped_unparseable?: number;
    };
    per_contract?: Array<{
      contract_name: string;
      counts?: Record<string, number>;
      metrics?: Record<string, number>;
      skipped_unparseable?: number;
    }>;
  };
  audit_results: Array<{
    contract_name: string;
    error?: string;
    vuln_results?: Array<{ vuln_name: string; response: string }>;
  }>;
}

export interface BenchmarkLlmCheckResponse {
  ok: boolean;
  model: string;
  latency_ms: number | null;
  preview: string;
  error: string | null;
}

export interface TrackBRunCreateRequest {
  report_path: string;
  cases_path: string;
  model: string;
  temperature: number;
  max_cases: number;
  profiles: TrackBProfile[];
}

export interface TrackBRunCreateResponse {
  run_id: string;
  status: string;
  created_at: string;
  profiles: TrackBProfile[];
  links: Record<string, string>;
}

export interface TrackBProfileProgress {
  profile: TrackBProfile;
  status: "queued" | "running" | "scoring" | "completed" | "failed";
  cases_total: number;
  cases_completed: number;
}

export interface TrackBRunStatusResponse {
  run_id: string;
  status: "queued" | "running" | "scoring" | "completed" | "failed";
  stage: "queued" | "running" | "scoring" | "completed" | "failed";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  report_path: string;
  cases_path: string;
  model: string;
  temperature: number;
  max_cases: number;
  profiles: TrackBProfile[];
  progress: TrackBProfileProgress[];
  error: string | null;
}

export interface TrackBMetricsResponse {
  run_id: string;
  metrics_by_profile: Record<string, Record<string, unknown>>;
}

export interface TrackBArtifactsResponse {
  run_id: string;
  output_dir: string;
  artifacts: Array<{
    profile: string;
    name: string;
    path: string;
    bytes: number;
  }>;
  profiles: Array<{
    profile: string;
    metrics: Record<string, unknown>;
    wrong_cases: Array<{
      case_id: string;
      question: string;
      answer: string;
      expected_answer: string;
      correct: boolean;
      numeric_correct: boolean | null;
      citation_present: boolean;
      error_codes: string[];
    }>;
    wrong_case_count: number;
    overall_accuracy: number;
    numeric_accuracy: number;
    citation_rate: number;
  }>;
}

export interface TrackBHistoryResponse {
  runs: Array<{
    run_id: string;
    created_at: string;
    finished_at: string;
    status: string;
    report_path: string;
    cases_path: string;
    model: string;
    temperature: number;
    profiles: Array<{
      profile: string;
      metrics: Record<string, unknown>;
      wrong_cases: Array<{
        case_id: string;
        question: string;
        answer: string;
        expected_answer: string;
        correct: boolean;
        numeric_correct: boolean | null;
        citation_present: boolean;
        error_codes: string[];
      }>;
      wrong_case_count: number;
      overall_accuracy: number;
      numeric_accuracy: number;
      citation_rate: number;
    }>;
    output_dir: string;
  }>;
}

export interface TrackBComparisonResponse {
  run_id: string;
  baseline_profile: TrackBProfile;
  rows: Array<Record<string, unknown>>;
  loo_impact: Array<Record<string, unknown>>;
}

export interface TrackBReproduceResponse {
  run_id: string;
  commands: Record<string, string>;
  config: Record<string, unknown>;
}

export interface TrackBEvent {
  run_id: string;
  event: string;
  stage: string;
  seq: number;
  ts: string;
  payload: Record<string, unknown>;
}

export async function checkBackendHealth(): Promise<{ status: string }> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/healthz`);
  } catch (err) {
    throw new Error(
      `Cannot reach backend (${API_BASE}). Original error: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
  if (!res.ok) {
    throw new Error(`Backend health check failed: ${res.status}`);
  }
  return res.json() as Promise<{ status: string }>;
}

export async function checkBenchmarkLlm(
  model: string,
): Promise<BenchmarkLlmCheckResponse> {
  const params = new URLSearchParams({ model });

  let res: Response;
  try {
    res = await fetch(
      `${API_BASE}/api/v1/benchmark/llm-check?${params.toString()}`,
    );
  } catch (err) {
    throw new Error(
      `Cannot reach backend (${API_BASE}) during LLM check. Original error: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`LLM check failed: ${res.status} ${detail}`);
  }
  return res.json() as Promise<BenchmarkLlmCheckResponse>;
}

export async function loadBenchmarkContracts(
  dataset: BenchmarkDataset,
  limit: number,
  preferSharedDb: boolean,
): Promise<BenchmarkLoadResponse> {
  const params = new URLSearchParams({
    dataset,
    limit: String(limit),
    prefer_shared_db: String(preferSharedDb),
  });

  let res: Response;
  try {
    res = await fetch(
      `${API_BASE}/api/v1/benchmark/contracts?${params.toString()}`,
    );
  } catch (err) {
    throw new Error(
      `Cannot reach backend (${API_BASE}). Check backend server and VITE_API_URL. Original error: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
  if (!res.ok) {
    throw new Error(`Load benchmark failed: ${res.status}`);
  }
  return res.json() as Promise<BenchmarkLoadResponse>;
}

export async function runBenchmark(
  payload: BenchmarkRunRequest,
): Promise<BenchmarkRunResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1/benchmark/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    throw new Error(
      `Cannot reach backend (${API_BASE}) while running benchmark. Check backend server and VITE_API_URL. Original error: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Run benchmark failed: ${res.status} ${detail}`);
  }
  return res.json() as Promise<BenchmarkRunResponse>;
}

export async function createTrackBRun(
  payload: TrackBRunCreateRequest,
): Promise<TrackBRunCreateResponse> {
  const res = await fetch(`${API_BASE}/api/v1/trackb/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Create Track B run failed: ${res.status} ${detail}`);
  }
  return res.json() as Promise<TrackBRunCreateResponse>;
}

export async function createTrackBUploadRun(params: {
  reportFile: File;
  casesFile: File;
  model: string;
  temperature: number;
  maxCases: number;
  profiles: TrackBProfile[];
}): Promise<TrackBRunCreateResponse> {
  const formData = new FormData();
  formData.append("report_file", params.reportFile);
  formData.append("cases_file", params.casesFile);
  formData.append("model", params.model);
  formData.append("temperature", String(params.temperature));
  formData.append("max_cases", String(params.maxCases));
  formData.append("profiles", JSON.stringify(params.profiles));

  const res = await fetch(`${API_BASE}/api/v1/trackb/runs/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Create Track B upload run failed: ${res.status} ${detail}`);
  }
  return res.json() as Promise<TrackBRunCreateResponse>;
}

export async function getTrackBRunStatus(
  runId: string,
): Promise<TrackBRunStatusResponse> {
  const res = await fetch(`${API_BASE}/api/v1/trackb/runs/${runId}`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Get Track B run status failed: ${res.status} ${detail}`);
  }
  return res.json() as Promise<TrackBRunStatusResponse>;
}

export async function getTrackBMetrics(
  runId: string,
): Promise<TrackBMetricsResponse> {
  const res = await fetch(`${API_BASE}/api/v1/trackb/runs/${runId}/metrics`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Get Track B metrics failed: ${res.status} ${detail}`);
  }
  return res.json() as Promise<TrackBMetricsResponse>;
}

export async function getTrackBArtifacts(
  runId: string,
): Promise<TrackBArtifactsResponse> {
  const res = await fetch(`${API_BASE}/api/v1/trackb/runs/${runId}/artifacts`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Get Track B artifacts failed: ${res.status} ${detail}`);
  }
  return res.json() as Promise<TrackBArtifactsResponse>;
}

export async function getTrackBHistory(
  limit = 20,
): Promise<TrackBHistoryResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(`${API_BASE}/api/v1/trackb/history?${params.toString()}`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Get Track B history failed: ${res.status} ${detail}`);
  }
  return res.json() as Promise<TrackBHistoryResponse>;
}

export async function getTrackBComparison(
  runId: string,
  baselineProfile: TrackBProfile,
): Promise<TrackBComparisonResponse> {
  const res = await fetch(`${API_BASE}/api/v1/trackb/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId, baseline_profile: baselineProfile }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Get Track B comparison failed: ${res.status} ${detail}`);
  }
  return res.json() as Promise<TrackBComparisonResponse>;
}

export async function getTrackBReproduce(
  runId: string,
): Promise<TrackBReproduceResponse> {
  const res = await fetch(`${API_BASE}/api/v1/trackb/runs/${runId}/reproduce`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Get Track B reproduce failed: ${res.status} ${detail}`);
  }
  return res.json() as Promise<TrackBReproduceResponse>;
}

export function streamTrackBRunEvents(
  runId: string,
  onEvent: (evt: TrackBEvent) => void,
): EventSource {
  const source = new EventSource(`${API_BASE}/api/v1/trackb/runs/${runId}/stream`);
  const handler = (event: MessageEvent<string>) => {
    try {
      const payload = JSON.parse(event.data) as TrackBEvent;
      onEvent(payload);
    } catch {
      // Ignore malformed heartbeat payloads.
    }
  };

  source.addEventListener("trackb_started", handler);
  source.addEventListener("trackb_profile_started", handler);
  source.addEventListener("trackb_case_progress", handler);
  source.addEventListener("trackb_profile_completed", handler);
  source.addEventListener("trackb_scoring_done", handler);
  source.addEventListener("trackb_completed", handler);
  source.addEventListener("trackb_failed", handler);
  source.addEventListener("ping", handler);

  return source;
}

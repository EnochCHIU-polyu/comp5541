import type { KGGraph, KGSnapshot, NodeDetailResponse } from "../types";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export async function extractKG(params: {
  title: string;
  text?: string;
  file?: File;
  model?: string;
}): Promise<{ graph_id: string; status: string }> {
  const form = new FormData();
  form.append("title", params.title);
  form.append("model", params.model ?? "deepseek-v3.2");
  if (params.file) {
    form.append("file", params.file);
  } else {
    form.append("text", params.text ?? "");
  }

  const res = await fetch(`${BASE}/api/v1/kg/extract`, { method: "POST", body: form });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Extract failed (${res.status}): ${body}`);
  }
  return res.json();
}

export async function fetchKGGraph(graphId: string): Promise<KGGraph> {
  const res = await fetch(`${BASE}/api/v1/kg/${graphId}/graph`);
  if (!res.ok) throw new Error(`Graph fetch failed (${res.status})`);
  return res.json();
}

export async function fetchKGSnapshot(graphId: string): Promise<KGSnapshot> {
  const res = await fetch(`${BASE}/api/v1/kg/${graphId}/snapshot`);
  if (!res.ok) throw new Error(`Snapshot fetch failed (${res.status})`);
  return res.json();
}

export async function fetchNodeDetail(
  graphId: string,
  nodeId: string,
  query?: string,
): Promise<NodeDetailResponse> {
  const params = new URLSearchParams({ top_k: "5" });
  if (query) params.set("query", query);
  const res = await fetch(`${BASE}/api/v1/kg/${graphId}/nodes/${nodeId}?${params}`);
  if (!res.ok) throw new Error(`Node detail fetch failed (${res.status})`);
  return res.json();
}

export function openKGEventStream(
  graphId: string,
  onEvent: (evt: MessageEvent) => void,
  onError?: (err: Event) => void,
): EventSource {
  const es = new EventSource(`${BASE}/api/v1/kg/${graphId}/stream`);
  es.addEventListener("kg_started", onEvent);
  es.addEventListener("kg_progress", onEvent);
  es.addEventListener("kg_completed", onEvent);
  es.addEventListener("kg_failed", onEvent);
  es.addEventListener("ping", onEvent);
  if (onError) es.onerror = onError;
  return es;
}

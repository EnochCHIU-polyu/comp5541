export interface SourceRef {
  chunk_id: string;
  page: number;
  span: string;
  text: string;
}

export interface KGNode {
  id: string;
  label: string;
  node_type: string;
  background_intro: string;
  source_refs: SourceRef[];
}

export interface KGEdge {
  source_id: string;
  target_id: string;
  relation: string;
  weight: number;
}

export interface KGGraph {
  graph_id: string;
  title: string;
  nodes: KGNode[];
  edges: KGEdge[];
  created_at: string;
}

export interface KGEvent {
  graph_id: string;
  event: string;
  stage: string;
  seq: number;
  ts: string;
  payload: Record<string, unknown>;
}

export interface KGSnapshot {
  graph_id: string;
  stage: string;
  status: string;
  events: KGEvent[];
}

export interface NodeDetailEvidence {
  chunk_id: string;
  page: number;
  score: number;
  text: string;
}

export interface NodeDetailResponse {
  node_id: string;
  label: string;
  background_intro: string;
  explanation: string;
  evidence: NodeDetailEvidence[];
}

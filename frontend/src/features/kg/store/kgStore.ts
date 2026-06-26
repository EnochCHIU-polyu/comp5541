import { create } from "zustand";
import type { KGGraph, KGEvent, NodeDetailResponse } from "../types";

interface KGStore {
  // Current job state
  graphId: string | null;
  stage: string;
  status: string;
  events: KGEvent[];
  graph: KGGraph | null;

  // Node detail panel
  selectedNodeId: string | null;
  nodeDetail: NodeDetailResponse | null;
  nodeDetailLoading: boolean;

  // Actions
  setJobStarted: (graphId: string) => void;
  pushEvent: (evt: KGEvent) => void;
  setGraph: (graph: KGGraph) => void;
  selectNode: (nodeId: string | null) => void;
  setNodeDetail: (detail: NodeDetailResponse | null) => void;
  setNodeDetailLoading: (loading: boolean) => void;
  reset: () => void;
}

const initialState = {
  graphId: null,
  stage: "idle",
  status: "idle",
  events: [],
  graph: null,
  selectedNodeId: null,
  nodeDetail: null,
  nodeDetailLoading: false,
};

export const useKGStore = create<KGStore>((set) => ({
  ...initialState,

  setJobStarted: (graphId) =>
    set({ graphId, stage: "queued", status: "queued", events: [], graph: null }),

  pushEvent: (evt) =>
    set((s) => ({
      events: [...s.events, evt],
      stage: evt.stage,
      status: evt.event === "kg_completed"
        ? "completed"
        : evt.event === "kg_failed"
        ? "failed"
        : "running",
    })),

  setGraph: (graph) => set({ graph }),

  selectNode: (nodeId) =>
    set({ selectedNodeId: nodeId, nodeDetail: null, nodeDetailLoading: false }),

  setNodeDetail: (detail) => set({ nodeDetail: detail, nodeDetailLoading: false }),

  setNodeDetailLoading: (loading) => set({ nodeDetailLoading: loading }),

  reset: () => set(initialState),
}));

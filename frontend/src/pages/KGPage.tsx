import { AppFrame } from "../components/AppFrame";
import { KGUploadPanel } from "../features/kg/components/KGUploadPanel";
import { KGGraphView } from "../features/kg/components/KGGraphView";
import { KGNodeDetailPanel } from "../features/kg/components/KGNodeDetailPanel";
import { useKGStore } from "../features/kg/store/kgStore";

export function KGPage() {
  const { graph, graphId, selectedNodeId, selectNode } = useKGStore();

  const selectedNode = graph?.nodes.find((n) => n.id === selectedNodeId) ?? null;

  return (
    <AppFrame>
      <section className="mx-auto w-full max-w-6xl space-y-6">
        <div className="aw-card">
          <p className="aw-subtle text-xs uppercase tracking-[0.2em]">
            COMP5541 · Knowledge Graph
          </p>
          <h1 className="aw-title mt-2 text-2xl font-bold md:text-3xl">
            AI-Driven Interactive Knowledge Graph
          </h1>
          <p className="aw-subtle mt-2 text-sm max-w-2xl">
            Upload lecture notes or a PDF. The system will extract key concepts, build a
            knowledge graph, and let you explore each node with AI-generated explanations
            grounded in source evidence.
          </p>
        </div>

        {/* Upload panel – always visible until a graph loads */}
        {!graph && <KGUploadPanel />}

        {/* Graph view */}
        {graph && graphId && (
          <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
            <div className="space-y-4">
              <KGGraphView
                graph={graph}
                selectedNodeId={selectedNodeId}
                onNodeClick={selectNode}
              />

              {/* Re-upload button */}
              <button
                type="button"
                onClick={() => useKGStore.getState().reset()}
                className="text-xs text-slate-500 underline hover:text-slate-700"
              >
                ← Upload a different document
              </button>
            </div>

            <div>
              {selectedNode ? (
                <KGNodeDetailPanel node={selectedNode} graphId={graphId} />
              ) : (
                <div className="aw-card text-center text-sm aw-subtle py-10">
                  Click a node in the graph to see its AI-generated explanation and
                  source evidence.
                </div>
              )}
            </div>
          </div>
        )}
      </section>
    </AppFrame>
  );
}

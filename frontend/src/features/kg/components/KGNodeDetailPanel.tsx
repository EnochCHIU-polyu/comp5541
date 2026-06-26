import { useEffect } from "react";
import { useKGStore } from "../store/kgStore";
import { fetchNodeDetail } from "../services/kgApi";
import type { KGNode } from "../types";

interface Props {
  node: KGNode;
  graphId: string;
}

export function KGNodeDetailPanel({ node, graphId }: Props) {
  const { nodeDetail, nodeDetailLoading, setNodeDetail, setNodeDetailLoading } = useKGStore();

  useEffect(() => {
    setNodeDetailLoading(true);
    setNodeDetail(null);
    fetchNodeDetail(graphId, node.id)
      .then(setNodeDetail)
      .catch((err) => {
        setNodeDetail({
          node_id: node.id,
          label: node.label,
          background_intro: node.background_intro,
          explanation: `Error fetching detail: ${err instanceof Error ? err.message : String(err)}`,
          evidence: [],
        });
      });
  }, [graphId, node.id]);

  const isInsufficient =
    nodeDetail?.explanation?.trim() === "EVIDENCE_INSUFFICIENT";

  return (
    <aside className="aw-card space-y-4">
      <div className="flex items-start justify-between gap-2">
        <h2 className="aw-title text-lg font-semibold">{node.label}</h2>
        <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
          {node.node_type}
        </span>
      </div>

      <p className="aw-subtle text-sm">{node.background_intro}</p>

      <hr className="border-slate-200" />

      <div>
        <h3 className="text-sm font-semibold text-[#1E293B] mb-1">AI Explanation</h3>
        {nodeDetailLoading ? (
          <p className="aw-subtle text-sm">Generating explanation…</p>
        ) : isInsufficient ? (
          <p className="rounded bg-amber-50 border border-amber-200 px-3 py-2 text-sm text-amber-700">
            ⚠️ Evidence insufficient — not enough source material to generate a reliable explanation.
          </p>
        ) : (
          <p className="text-sm leading-relaxed">{nodeDetail?.explanation}</p>
        )}
      </div>

      {nodeDetail && nodeDetail.evidence.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-[#1E293B] mb-2">Source Evidence</h3>
          <ol className="space-y-2">
            {nodeDetail.evidence.map((ev, i) => (
              <li
                key={i}
                className="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs"
              >
                <div className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
                  <span>Page {ev.page} · Chunk {ev.chunk_id}</span>
                  <span>score {ev.score.toFixed(3)}</span>
                </div>
                <p className="text-slate-600 line-clamp-4">{ev.text}</p>
              </li>
            ))}
          </ol>
        </div>
      )}

      {node.source_refs.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-[#1E293B] mb-2">Graph Citations</h3>
          <ul className="space-y-1 text-xs text-slate-500">
            {node.source_refs.map((ref, i) => (
              <li key={i}>
                <span className="font-medium">p.{ref.page}</span>
                {ref.span && <> – <em>{ref.span}</em></>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  );
}

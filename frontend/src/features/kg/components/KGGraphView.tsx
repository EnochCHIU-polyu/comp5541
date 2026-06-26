import { useEffect, useRef, useState } from "react";
import type { KGGraph, KGNode, KGEdge } from "../types";

interface NodePos {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
}

const WIDTH = 700;
const HEIGHT = 500;
const REPULSION = 3000;
const ATTRACTION = 0.04;
const DAMPING = 0.85;
const STEPS = 200;

function initPositions(nodes: KGNode[]): NodePos[] {
  return nodes.map((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length;
    return {
      id: n.id,
      x: WIDTH / 2 + 180 * Math.cos(angle),
      y: HEIGHT / 2 + 180 * Math.sin(angle),
      vx: 0,
      vy: 0,
    };
  });
}

function simulate(positions: NodePos[], edges: KGEdge[]): NodePos[] {
  const pos = positions.map((p) => ({ ...p }));

  for (let step = 0; step < STEPS; step++) {
    // Repulsion between all node pairs
    for (let i = 0; i < pos.length; i++) {
      for (let j = i + 1; j < pos.length; j++) {
        const dx = pos[j].x - pos[i].x;
        const dy = pos[j].y - pos[i].y;
        const dist2 = dx * dx + dy * dy + 1;
        const force = REPULSION / dist2;
        const fx = (force * dx) / Math.sqrt(dist2);
        const fy = (force * dy) / Math.sqrt(dist2);
        pos[i].vx -= fx;
        pos[i].vy -= fy;
        pos[j].vx += fx;
        pos[j].vy += fy;
      }
    }

    // Attraction along edges
    const posMap = new Map(pos.map((p) => [p.id, p]));
    for (const edge of edges) {
      const src = posMap.get(edge.source_id);
      const tgt = posMap.get(edge.target_id);
      if (!src || !tgt) continue;
      const dx = tgt.x - src.x;
      const dy = tgt.y - src.y;
      src.vx += dx * ATTRACTION;
      src.vy += dy * ATTRACTION;
      tgt.vx -= dx * ATTRACTION;
      tgt.vy -= dy * ATTRACTION;
    }

    // Center gravity
    for (const p of pos) {
      p.vx += (WIDTH / 2 - p.x) * 0.005;
      p.vy += (HEIGHT / 2 - p.y) * 0.005;
    }

    // Apply + dampen + clamp
    for (const p of pos) {
      p.vx *= DAMPING;
      p.vy *= DAMPING;
      p.x = Math.max(40, Math.min(WIDTH - 40, p.x + p.vx));
      p.y = Math.max(30, Math.min(HEIGHT - 30, p.y + p.vy));
    }
  }

  return pos;
}

interface Props {
  graph: KGGraph;
  selectedNodeId: string | null;
  onNodeClick: (nodeId: string) => void;
}

export function KGGraphView({ graph, selectedNodeId, onNodeClick }: Props) {
  const [positions, setPositions] = useState<NodePos[]>([]);
  const computed = useRef(false);

  useEffect(() => {
    if (computed.current) return;
    computed.current = true;
    const init = initPositions(graph.nodes);
    const final = simulate(init, graph.edges);
    setPositions(final);
  }, [graph]);

  const posMap = new Map(positions.map((p) => [p.id, p]));

  return (
    <div className="aw-card overflow-hidden">
      <h2 className="aw-title mb-3 text-lg font-semibold">{graph.title}</h2>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full rounded border border-slate-200 bg-white"
        style={{ maxHeight: 480 }}
      >
        {/* Edges */}
        {graph.edges.map((edge, i) => {
          const src = posMap.get(edge.source_id);
          const tgt = posMap.get(edge.target_id);
          if (!src || !tgt) return null;
          return (
            <line
              key={i}
              x1={src.x}
              y1={src.y}
              x2={tgt.x}
              y2={tgt.y}
              stroke="#CBD5E1"
              strokeWidth={1.5}
              markerEnd="url(#arrow)"
            />
          );
        })}

        {/* Arrow marker */}
        <defs>
          <marker
            id="arrow"
            markerWidth="6"
            markerHeight="6"
            refX="5"
            refY="3"
            orient="auto"
          >
            <path d="M0,0 L0,6 L6,3 z" fill="#94A3B8" />
          </marker>
        </defs>

        {/* Edge labels */}
        {graph.edges.map((edge, i) => {
          const src = posMap.get(edge.source_id);
          const tgt = posMap.get(edge.target_id);
          if (!src || !tgt) return null;
          const mx = (src.x + tgt.x) / 2;
          const my = (src.y + tgt.y) / 2;
          return (
            <text
              key={`label-${i}`}
              x={mx}
              y={my - 4}
              textAnchor="middle"
              className="text-[9px]"
              fill="#94A3B8"
              fontSize={9}
            >
              {edge.relation}
            </text>
          );
        })}

        {/* Nodes */}
        {graph.nodes.map((node) => {
          const p = posMap.get(node.id);
          if (!p) return null;
          const isSelected = node.id === selectedNodeId;
          return (
            <g
              key={node.id}
              transform={`translate(${p.x},${p.y})`}
              style={{ cursor: "pointer" }}
              onClick={() => onNodeClick(node.id)}
            >
              <circle
                r={isSelected ? 18 : 14}
                fill={isSelected ? "#1E293B" : "#3B82F6"}
                stroke={isSelected ? "#F8FAFC" : "#fff"}
                strokeWidth={2}
                opacity={0.9}
              />
              <text
                textAnchor="middle"
                dy={26}
                fontSize={10}
                fill="#334155"
                fontWeight={isSelected ? "bold" : "normal"}
              >
                {node.label.length > 18 ? node.label.slice(0, 16) + "…" : node.label}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="aw-subtle mt-2 text-xs">
        {graph.nodes.length} nodes · {graph.edges.length} edges · Click a node for details
      </p>
    </div>
  );
}

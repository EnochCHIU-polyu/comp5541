import { useMemo, useState } from "react";

import { AppFrame } from "../components/AppFrame";
import type { TrackBH3LayerConfig } from "../features/benchmark/services/benchmarkApi";

const H3_LAYERS_STORAGE_KEY = "trackb.h3.layers.v1";
const MAX_LAYERS = 4;

const DEFAULT_LAYERS: TrackBH3LayerConfig[] = [
  { model: "DeepSeek-V3.2", batch_size: 8 },
  { model: "gpt-4.1", batch_size: 4 },
];

function loadH3Layers(): TrackBH3LayerConfig[] {
  if (typeof window === "undefined") return DEFAULT_LAYERS;
  try {
    const raw = window.localStorage.getItem(H3_LAYERS_STORAGE_KEY);
    if (!raw) return DEFAULT_LAYERS;
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return DEFAULT_LAYERS;
    const layers = parsed
      .map((item) => {
        if (!item || typeof item !== "object") return null;
        const row = item as Record<string, unknown>;
        const model = String(row.model ?? "").trim();
        if (!model) return null;
        return {
          model,
          batch_size: Math.max(
            1,
            Math.min(Number(row.batch_size ?? 8) || 8, 64),
          ),
        } satisfies TrackBH3LayerConfig;
      })
      .filter((row): row is TrackBH3LayerConfig => row !== null)
      .slice(0, MAX_LAYERS);
    return layers.length ? layers : DEFAULT_LAYERS;
  } catch {
    return DEFAULT_LAYERS;
  }
}

function saveH3Layers(layers: TrackBH3LayerConfig[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(H3_LAYERS_STORAGE_KEY, JSON.stringify(layers));
}

export function TrackBH3Page() {
  const [layers, setLayers] = useState<TrackBH3LayerConfig[]>(() =>
    loadH3Layers(),
  );
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  const applyLayers = (next: TrackBH3LayerConfig[]) => {
    const sanitized = next
      .map((layer) => ({
        model: layer.model.trim(),
        batch_size: Math.max(1, Math.min(Number(layer.batch_size) || 1, 64)),
      }))
      .filter((layer) => layer.model.length > 0)
      .slice(0, MAX_LAYERS);
    setLayers(sanitized);
    saveH3Layers(sanitized);
    setSaveMessage(
      `Saved ${sanitized.length} H3 layer(s). New runs will use this workflow.`,
    );
  };

  const totalBatchPerPass = useMemo(
    () => layers.reduce((sum, layer) => sum + layer.batch_size, 0),
    [layers],
  );

  const updateLayer = (index: number, patch: Partial<TrackBH3LayerConfig>) => {
    const next = [...layers];
    next[index] = {
      ...next[index],
      ...patch,
    };
    applyLayers(next);
  };

  const moveLayer = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= layers.length) return;
    const next = [...layers];
    const [item] = next.splice(index, 1);
    next.splice(target, 0, item);
    applyLayers(next);
  };

  const addLayer = () => {
    if (layers.length >= MAX_LAYERS) return;
    applyLayers([...layers, { model: "DeepSeek-V3.2", batch_size: 4 }]);
  };

  const removeLayer = (index: number) => {
    applyLayers(layers.filter((_, idx) => idx !== index));
  };

  const resetDefaults = () => {
    applyLayers(DEFAULT_LAYERS);
  };

  return (
    <AppFrame>
      <div className="space-y-4">
        <header className="aw-card">
          <p className="aw-subtle text-xs uppercase tracking-[0.2em]">
            Track B Harness H3
          </p>
          <h1 className="aw-title mt-2 text-3xl font-bold">
            H3 Layered Reviewer Flow
          </h1>
          <p className="aw-subtle mt-2 text-sm">
            Configure multi-layer reviewer models and per-layer batch sizes.
            This setting is applied to all new Track B runs with H3 enabled.
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <span className="aw-chip">storage: {H3_LAYERS_STORAGE_KEY}</span>
            <span className="aw-chip">max layers: {MAX_LAYERS}</span>
            <span className="aw-chip">
              total per-pass batch: {totalBatchPerPass}
            </span>
          </div>
        </header>

        {saveMessage && (
          <section className="aw-card border-emerald-300 bg-emerald-50">
            <p className="text-sm text-emerald-700">{saveMessage}</p>
          </section>
        )}

        <section className="aw-card space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="aw-title text-lg font-semibold">Reviewer Layers</h2>
            <div className="flex gap-2">
              <button type="button" className="aw-chip" onClick={resetDefaults}>
                Reset Defaults
              </button>
              <button
                type="button"
                className="aw-button w-auto px-4 py-2"
                onClick={addLayer}
                disabled={layers.length >= MAX_LAYERS}
              >
                + Add Layer
              </button>
            </div>
          </div>

          <div className="space-y-2">
            {layers.map((layer, index) => (
              <div
                key={`${index}-${layer.model}`}
                className="rounded-xl border border-slate-300 p-3"
              >
                <div className="mb-2 flex items-center justify-between">
                  <span className="aw-title text-sm font-semibold">
                    Layer {index + 1}
                  </span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="aw-chip"
                      onClick={() => moveLayer(index, -1)}
                      disabled={index === 0}
                    >
                      Up
                    </button>
                    <button
                      type="button"
                      className="aw-chip"
                      onClick={() => moveLayer(index, 1)}
                      disabled={index === layers.length - 1}
                    >
                      Down
                    </button>
                    <button
                      type="button"
                      className="aw-chip"
                      onClick={() => removeLayer(index)}
                      disabled={layers.length <= 1}
                    >
                      Remove
                    </button>
                  </div>
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  <label className="text-sm aw-subtle">
                    Model
                    <input
                      className="aw-input mt-1"
                      value={layer.model}
                      onChange={(e) =>
                        updateLayer(index, { model: e.target.value })
                      }
                      placeholder="DeepSeek-V3.2"
                    />
                  </label>

                  <label className="text-sm aw-subtle">
                    Batch Size
                    <input
                      className="aw-input mt-1"
                      type="number"
                      min={1}
                      max={64}
                      value={layer.batch_size}
                      onChange={(e) =>
                        updateLayer(index, {
                          batch_size: Number(e.target.value) || 1,
                        })
                      }
                    />
                  </label>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </AppFrame>
  );
}

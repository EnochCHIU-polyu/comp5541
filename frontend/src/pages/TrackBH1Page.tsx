import { useEffect, useState } from "react";

import { AppFrame } from "../components/AppFrame";
import {
  getTrackBH1Components,
  saveTrackBH1Source,
} from "../features/benchmark/services/benchmarkApi";

export function TrackBH1Page() {
  const [sourcePath, setSourcePath] = useState(
    "phase2_llm_engine/trackb_harnesses/h1_code_base.py",
  );
  const [fullSource, setFullSource] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const boot = async () => {
      setIsLoading(true);
      setError(null);
      setSaveMessage(null);
      try {
        const payload = await getTrackBH1Components();
        if (!active) return;
        setSourcePath(payload.source_path);
        setFullSource(payload.full_source);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (active) setIsLoading(false);
      }
    };

    void boot();
    return () => {
      active = false;
    };
  }, []);

  const onSave = async () => {
    setIsSaving(true);
    setError(null);
    setSaveMessage(null);
    try {
      const saved = await saveTrackBH1Source(fullSource);
      setSaveMessage(
        `Saved ${saved.bytes_written} bytes to ${saved.source_path}.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <AppFrame>
      <div className="space-y-4">
        <header className="aw-card">
          <p className="aw-subtle text-xs uppercase tracking-[0.2em]">
            Track B Harness H1
          </p>
          <h1 className="aw-title mt-2 text-3xl font-bold">H1 Code Editor</h1>
          <p className="aw-subtle mt-2 text-sm">
            Edit full source code directly and save changes.
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <span className="aw-chip">source: {sourcePath}</span>
          </div>
        </header>

        {error && (
          <section className="aw-card border-red-300 bg-red-50">
            <p className="text-sm text-red-700">{error}</p>
          </section>
        )}

        {saveMessage && (
          <section className="aw-card border-emerald-300 bg-emerald-50">
            <p className="text-sm text-emerald-700">{saveMessage}</p>
          </section>
        )}

        <section className="aw-card space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="aw-title text-lg font-semibold">Full Source Code</h2>
            <button
              type="button"
              className="aw-button w-auto px-4 py-2"
              disabled={isLoading || isSaving}
              onClick={onSave}
            >
              {isSaving ? "Saving..." : "Save"}
            </button>
          </div>
          {isLoading ? (
            <p className="aw-subtle text-sm">Loading source code...</p>
          ) : (
            <textarea
              className="aw-input resize-y font-mono text-xs"
              rows={30}
              style={{ minHeight: "72vh", height: "72vh" }}
              value={fullSource}
              onChange={(e) => setFullSource(e.target.value)}
            />
          )}
        </section>
      </div>
    </AppFrame>
  );
}

import { useEffect, useMemo, useState } from "react";

import { AppFrame } from "../components/AppFrame";
import {
  getTrackBH4Source,
  saveTrackBH4Source,
} from "../features/benchmark/services/benchmarkApi";

export function TrackBH4Page() {
  const [sourcePath, setSourcePath] = useState(
    "phase2_llm_engine/trackb_harnesses/h4_evidence_verifier.py",
  );
  const [originalSource, setOriginalSource] = useState("");
  const [fullSource, setFullSource] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  const isDirty = useMemo(
    () => fullSource !== originalSource,
    [fullSource, originalSource],
  );

  const loadSource = async () => {
    setIsLoading(true);
    setError(null);
    setSaveMessage(null);
    try {
      const payload = await getTrackBH4Source();
      setSourcePath(payload.source_path);
      setOriginalSource(payload.full_source);
      setFullSource(payload.full_source);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadSource();
  }, []);

  const onSave = async () => {
    setIsSaving(true);
    setError(null);
    setSaveMessage(null);
    try {
      const saved = await saveTrackBH4Source(fullSource);
      setOriginalSource(fullSource);
      setSaveMessage(
        `Saved ${saved.bytes_written} bytes to ${saved.source_path}. Runtime refreshed: ${saved.runtime_refreshed ? "yes" : "no"}.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSaving(false);
    }
  };

  const onRevert = () => {
    setFullSource(originalSource);
    setSaveMessage(null);
    setError(null);
  };

  return (
    <AppFrame>
      <div className="space-y-4">
        <header className="aw-card">
          <p className="aw-subtle text-xs uppercase tracking-[0.2em]">
            Track B Harness H4
          </p>
          <h1 className="aw-title mt-2 text-3xl font-bold">
            H4 Verifier Editor
          </h1>
          <p className="aw-subtle mt-2 text-sm">
            Edit full verifier source and save. Changes apply to new Track B
            runs across the system.
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <span className="aw-chip">source: {sourcePath}</span>
            <span className={`aw-chip ${isDirty ? "aw-chip-accent" : ""}`}>
              {isDirty ? "Unsaved changes" : "Saved"}
            </span>
          </div>
          <p className="aw-subtle mt-3 text-xs">
            Required definitions: verify_support, repair_answer_deterministic,
            h2_numeric_guard.
          </p>
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
            <div className="flex gap-2">
              <button
                type="button"
                className="aw-chip"
                disabled={isLoading || isSaving || !isDirty}
                onClick={onRevert}
              >
                Revert
              </button>
              <button
                type="button"
                className="aw-chip"
                disabled={isLoading || isSaving}
                onClick={() => {
                  void loadSource();
                }}
              >
                Reload
              </button>
              <button
                type="button"
                className="aw-button w-auto px-4 py-2"
                disabled={isLoading || isSaving || !isDirty}
                onClick={onSave}
              >
                {isSaving ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
          {isLoading ? (
            <p className="aw-subtle text-sm">Loading H4 source code...</p>
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

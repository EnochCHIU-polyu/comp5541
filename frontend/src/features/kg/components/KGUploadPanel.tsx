import { useRef, useState } from "react";
import { extractKG, openKGEventStream, fetchKGGraph } from "../services/kgApi";
import { useKGStore } from "../store/kgStore";
import type { KGEvent } from "../types";

export function KGUploadPanel() {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const { setJobStarted, pushEvent, setGraph, stage, status } = useKGStore();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setError("Please enter a document title.");
      return;
    }
    if (!text.trim() && !file) {
      setError("Please paste text or upload a PDF.");
      return;
    }
    setError(null);
    setLoading(true);

    try {
      const { graph_id } = await extractKG({
        title: title.trim(),
        text: text.trim() || undefined,
        file: file ?? undefined,
      });

      setJobStarted(graph_id);

      const es = openKGEventStream(
        graph_id,
        (msg) => {
          const data = JSON.parse(msg.data) as KGEvent;
          pushEvent(data);

          if (data.event === "kg_completed") {
            es.close();
            fetchKGGraph(graph_id).then(setGraph).catch(console.error);
          }
          if (data.event === "kg_failed") {
            es.close();
          }
        },
        () => {
          setError("Connection error. Check that the backend is running.");
        },
      );
      esRef.current = es;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="aw-card space-y-4">
      <h2 className="aw-title text-lg font-semibold">Upload Document</h2>

      <div>
        <label className="aw-subtle block text-sm mb-1" htmlFor="kg-title">
          Document Title
        </label>
        <input
          id="kg-title"
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Week 3 – Smart Contract Security"
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
        />
      </div>

      <div>
        <label className="aw-subtle block text-sm mb-1" htmlFor="kg-text">
          Paste Text <span className="text-xs">(or upload PDF below)</span>
        </label>
        <textarea
          id="kg-text"
          rows={6}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste lecture notes or textbook content here…"
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400 font-mono"
        />
      </div>

      <div>
        <label className="aw-subtle block text-sm mb-1" htmlFor="kg-file">
          Upload PDF <span className="text-xs">(optional, overrides text)</span>
        </label>
        <input
          id="kg-file"
          type="file"
          accept="application/pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-sm text-slate-600"
        />
        {file && <p className="aw-subtle text-xs mt-1">Selected: {file.name}</p>}
      </div>

      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}

      {stage !== "idle" && (
        <div className="rounded-md bg-slate-50 border border-slate-200 px-3 py-2 text-sm">
          <span className="font-medium">Status:</span>{" "}
          <span
            className={
              status === "completed"
                ? "text-green-600"
                : status === "failed"
                ? "text-red-600"
                : "text-amber-600"
            }
          >
            {stage} ({status})
          </span>
        </div>
      )}

      <button
        type="submit"
        disabled={loading || (status === "running")}
        className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
      >
        {loading ? "Submitting…" : "Extract Knowledge Graph"}
      </button>
    </form>
  );
}

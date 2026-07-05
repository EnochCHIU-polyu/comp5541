import { useMemo, useState } from "react";

import { AppFrame } from "../components/AppFrame";
import {
  askTrackBChatSession,
  createTrackBChatSessionUpload,
  type TrackBChatHarness,
  type TrackBChatSessionCreateResponse,
  type TrackBChatTurn,
  type TrackBH1ComponentConfig,
  type TrackBH3LayerConfig,
} from "../features/benchmark/services/benchmarkApi";

const H1_COMPONENTS_STORAGE_KEY = "trackb.h1.components.v1";
const H3_LAYERS_STORAGE_KEY = "trackb.h3.layers.v1";

const HARNESS_OPTIONS: TrackBChatHarness[] = [
  "baseline",
  "h1",
  "h2",
  "h3",
  "h4",
  "all",
];

function loadH1ComponentsFromStorage(): TrackBH1ComponentConfig[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(H1_COMPONENTS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((item) => {
        if (!item || typeof item !== "object") return null;
        const row = item as Record<string, unknown>;
        const name = String(row.name ?? "").trim();
        if (!name) return null;
        return {
          name,
          enabled: Boolean(row.enabled ?? true),
          top_k: Math.max(1, Math.min(Number(row.top_k ?? 6) || 6, 20)),
          evidence_keywords: Array.isArray(row.evidence_keywords)
            ? row.evidence_keywords
                .map((v) => String(v ?? "").trim())
                .filter((v) => v.length > 0)
            : [],
          note: String(row.note ?? ""),
        } satisfies TrackBH1ComponentConfig;
      })
      .filter((row): row is TrackBH1ComponentConfig => row !== null);
  } catch {
    return [];
  }
}

function loadH3LayersFromStorage(): TrackBH3LayerConfig[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(H3_LAYERS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
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
      .slice(0, 4);
  } catch {
    return [];
  }
}

function isReportFile(name: string): boolean {
  const lower = name.toLowerCase();
  return (
    lower.endsWith(".pdf") ||
    lower.endsWith(".md") ||
    lower.endsWith(".markdown")
  );
}

export function TrackBChatPage() {
  const [reportFile, setReportFile] = useState<File | null>(null);
  const [model, setModel] = useState("DeepSeek-V3.2");
  const [temperature, setTemperature] = useState(0);
  const [harnesses, setHarnesses] = useState<TrackBChatHarness[]>(["all"]);
  const [session, setSession] =
    useState<TrackBChatSessionCreateResponse | null>(null);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<TrackBChatTurn[]>([]);
  const [isCreatingSession, setIsCreatingSession] = useState(false);
  const [isAsking, setIsAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canAsk = useMemo(
    () =>
      Boolean(session && question.trim() && harnesses.length > 0 && !isAsking),
    [session, question, harnesses, isAsking],
  );

  const toggleHarness = (harness: TrackBChatHarness) => {
    setHarnesses((prev) => {
      if (harness === "baseline") {
        return ["baseline"];
      }
      if (harness === "all") {
        return ["all"];
      }

      const next = prev.filter((item) => item !== "baseline" && item !== "all");
      if (next.includes(harness)) {
        const reduced = next.filter((item) => item !== harness);
        return reduced.length ? reduced : ["baseline"];
      }
      return [...next, harness];
    });
  };

  const createSession = async () => {
    if (!reportFile) {
      setError("Please choose a report file first.");
      return;
    }
    if (!isReportFile(reportFile.name)) {
      setError("Report must be PDF or markdown (.md). ");
      return;
    }

    setIsCreatingSession(true);
    setError(null);
    try {
      const created = await createTrackBChatSessionUpload({
        reportFile,
        model,
        temperature,
        h1Components: loadH1ComponentsFromStorage(),
        h3Layers: loadH3LayersFromStorage(),
      });
      setSession(created);
      setTurns([]);
      setQuestion("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsCreatingSession(false);
    }
  };

  const askQuestion = async () => {
    if (!session) {
      setError("Create a chat session first.");
      return;
    }
    const prompt = question.trim();
    if (!prompt) return;

    setIsAsking(true);
    setError(null);
    try {
      const res = await askTrackBChatSession(session.session_id, {
        question: prompt,
        harnesses,
        model,
        temperature,
        h1_components: loadH1ComponentsFromStorage(),
        h3_layers: loadH3LayersFromStorage(),
      });
      setTurns((prev) => [...prev, res.turn]);
      setQuestion("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsAsking(false);
    }
  };

  return (
    <AppFrame>
      <div className="space-y-4">
        <header className="aw-card">
          <p className="aw-subtle text-xs uppercase tracking-[0.2em]">
            Track B Chat Use Case
          </p>
          <h1 className="aw-title mt-2 text-3xl font-bold">
            Financial Report Harness Chat
          </h1>
          <p className="aw-subtle mt-2 text-sm">
            Upload a financial report (PDF/MD), pick harness profiles, and chat
            with AI answers improved by H1-H4 workflow logic.
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <span className="aw-chip">model: {model}</span>
            <span className="aw-chip">temperature: {temperature}</span>
            <span className="aw-chip">harnesses: {harnesses.join(" + ")}</span>
          </div>
        </header>

        {error && (
          <section className="aw-card border-red-300 bg-red-50">
            <p className="text-sm text-red-700">{error}</p>
          </section>
        )}

        <section className="grid gap-4 lg:grid-cols-[360px,1fr]">
          <aside className="aw-card space-y-3">
            <h2 className="aw-title text-lg font-semibold">Session Setup</h2>

            <label className="text-sm aw-subtle">
              Report file (.pdf / .md)
              <input
                className="aw-input mt-1"
                type="file"
                accept=".pdf,.md,.markdown"
                onChange={(e) => {
                  const file = e.target.files?.[0] ?? null;
                  setReportFile(file);
                }}
              />
            </label>

            <label className="text-sm aw-subtle">
              Model
              <input
                className="aw-input mt-1"
                value={model}
                onChange={(e) => setModel(e.target.value)}
              />
            </label>

            <label className="text-sm aw-subtle">
              Temperature
              <input
                className="aw-input mt-1"
                type="number"
                step={0.1}
                min={0}
                max={2}
                value={temperature}
                onChange={(e) => setTemperature(Number(e.target.value) || 0)}
              />
            </label>

            <div className="space-y-2">
              <p className="text-sm aw-subtle">Harness combination</p>
              <div className="flex flex-wrap gap-2">
                {HARNESS_OPTIONS.map((harness) => {
                  const active = harnesses.includes(harness);
                  return (
                    <button
                      key={harness}
                      type="button"
                      className={`aw-chip ${active ? "aw-chip-accent" : ""}`}
                      onClick={() => toggleHarness(harness)}
                    >
                      {harness}
                    </button>
                  );
                })}
              </div>
              <p className="text-xs aw-subtle">
                `baseline` is exclusive. `all` means H1 + H2 + H3 + H4 together.
                Selecting H1/H2/H3/H4 combines them into one workflow.
              </p>
            </div>

            <button
              type="button"
              className="aw-button"
              disabled={isCreatingSession || !reportFile}
              onClick={createSession}
            >
              {isCreatingSession
                ? "Creating session..."
                : "Create Chat Session"}
            </button>

            {session && (
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
                <p>Session: {session.session_id}</p>
                <p>Report: {session.report_name}</p>
              </div>
            )}
          </aside>

          <section className="aw-card space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="aw-title text-lg font-semibold">Chat</h2>
              <span className="aw-chip">turns: {turns.length}</span>
            </div>

            <div className="space-y-3">
              {turns.length === 0 ? (
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
                  No chat turns yet. Create a session and ask a question.
                </div>
              ) : (
                turns.map((turn) => (
                  <article
                    key={turn.turn_id}
                    className="rounded-xl border border-slate-200 p-4 space-y-3"
                  >
                    <div>
                      <p className="text-xs aw-subtle">User question</p>
                      <p className="text-sm text-slate-800">{turn.question}</p>
                    </div>
                    <div className="space-y-2">
                      {turn.answers.map((ans) => (
                        <div
                          key={`${turn.turn_id}-${ans.profile}`}
                          className="rounded-lg border border-slate-200 bg-slate-50 p-3"
                        >
                          <div className="mb-1 flex flex-wrap items-center gap-2">
                            <span className="aw-chip aw-chip-accent">
                              {ans.profile}
                            </span>
                            <span className="aw-chip">{ans.elapsed_ms} ms</span>
                          </div>
                          <p className="text-sm text-slate-800 whitespace-pre-wrap">
                            {ans.answer || "(empty answer)"}
                          </p>
                          <div className="mt-2">
                            <p className="text-xs aw-subtle">Citations</p>
                            {ans.citations.length > 0 ? (
                              <ul className="mt-1 space-y-1 text-xs text-slate-700">
                                {ans.citations.map((citation, idx) => (
                                  <li
                                    key={`${ans.profile}-${idx}`}
                                    className="rounded border border-slate-200 bg-white px-2 py-1"
                                  >
                                    {citation}
                                  </li>
                                ))}
                              </ul>
                            ) : (
                              <p className="text-xs text-slate-500">
                                No citations
                              </p>
                            )}
                          </div>
                          <details className="mt-2">
                            <summary className="cursor-pointer text-xs text-slate-600">
                              Diagnostics
                            </summary>
                            <pre className="mt-2 overflow-auto rounded border border-slate-200 bg-white p-2 text-[11px] text-slate-700">
                              {JSON.stringify(ans.diagnostics, null, 2)}
                            </pre>
                          </details>
                        </div>
                      ))}
                    </div>
                  </article>
                ))
              )}
            </div>

            <div className="border-t border-slate-200 pt-3">
              <label className="text-sm aw-subtle">
                Ask a question
                <textarea
                  className="aw-input mt-1 resize-y"
                  rows={4}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="Example: What is the YoY revenue growth in Q1 and what evidence supports it?"
                />
              </label>

              <div className="mt-2 flex justify-end">
                <button
                  type="button"
                  className="aw-button w-auto px-4 py-2"
                  disabled={!canAsk}
                  onClick={askQuestion}
                >
                  {isAsking ? "Asking..." : "Send"}
                </button>
              </div>
            </div>
          </section>
        </section>
      </div>
    </AppFrame>
  );
}

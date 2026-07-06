import { useEffect, useMemo, useRef, useState } from "react";

import { AppFrame } from "../components/AppFrame";
import {
  askTrackBChatSession,
  createTrackBChatSessionUpload,
  getTrackBChatSessionReport,
  type TrackBChatHarness,
  type TrackBChatReportResponse,
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

function extractLineNumbers(texts: string[]): number[] {
  const lines = new Set<number>();

  for (const text of texts) {
    for (const match of text.matchAll(/\bL(\d+)(?:\s*[-–]\s*L?(\d+))?/g)) {
      const start = Number(match[1]);
      const end = match[2] ? Number(match[2]) : start;
      for (let line = start; line <= end; line += 1) {
        if (line > 0) lines.add(line);
      }
    }

    for (const match of text.matchAll(/\blines?\s+(\d+)(?:\s*[-–]\s*(\d+))?/gi)) {
      const start = Number(match[1]);
      const end = match[2] ? Number(match[2]) : start;
      for (let line = start; line <= end; line += 1) {
        if (line > 0) lines.add(line);
      }
    }
  }

  return [...lines].sort((left, right) => left - right);
}

function formatLineLabel(line: number): string {
  return `L${line}`;
}

export function TrackBChatPage() {
  const [reportFile, setReportFile] = useState<File | null>(null);
  const [model, setModel] = useState("DeepSeek-V3.2");
  const [temperature, setTemperature] = useState(0);
  const [harnesses, setHarnesses] = useState<TrackBChatHarness[]>(["all"]);
  const [session, setSession] =
    useState<TrackBChatSessionCreateResponse | null>(null);
  const [report, setReport] = useState<TrackBChatReportResponse | null>(null);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<TrackBChatTurn[]>([]);
  const [isCreatingSession, setIsCreatingSession] = useState(false);
  const [isLoadingReport, setIsLoadingReport] = useState(false);
  const [isAsking, setIsAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedLine, setSelectedLine] = useState<number | null>(null);
  const [focusNonce, setFocusNonce] = useState(0);
  const lineRefs = useRef<Record<number, HTMLButtonElement | null>>({});

  const canAsk = useMemo(
    () =>
      Boolean(session && question.trim() && harnesses.length > 0 && !isAsking),
    [session, question, harnesses, isAsking],
  );

  const reportLines = useMemo(
    () => report?.content.split("\n") ?? [],
    [report],
  );

  const selectedLineText =
    selectedLine && reportLines[selectedLine - 1] !== undefined
      ? reportLines[selectedLine - 1]
      : null;

  useEffect(() => {
    if (!session) {
      setReport(null);
      setSelectedLine(null);
      return;
    }

    let active = true;
    setIsLoadingReport(true);
    setReport(null);

    void getTrackBChatSessionReport(session.session_id)
      .then((nextReport) => {
        if (!active) return;
        setReport(nextReport);
        setSelectedLine(null);
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!active) return;
        setIsLoadingReport(false);
      });

    return () => {
      active = false;
    };
  }, [session]);

  useEffect(() => {
    if (!selectedLine) return;
    const target = lineRefs.current[selectedLine];
    target?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selectedLine, report, focusNonce]);

  const jumpToLine = (line: number | null | undefined) => {
    if (!line || line < 1) return;
    setSelectedLine(line);
    setFocusNonce((current) => current + 1);
  };

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
      setSelectedLine(null);
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
      const turnEvidenceLines = res.turn.answers.flatMap((answer) =>
        answer.primary_evidence_line ? [answer.primary_evidence_line] : answer.evidence_lines,
      );
      jumpToLine(turnEvidenceLines[0] ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsAsking(false);
    }
  };

  return (
    <AppFrame>
      <div className="space-y-4">
        <header className="aw-card overflow-hidden">
          <div className="grid gap-4 lg:grid-cols-[1.4fr,0.9fr] lg:items-end">
            <div>
              <p className="aw-subtle text-xs uppercase tracking-[0.22em]">
                Track B Chat Workspace
              </p>
              <h1 className="aw-title mt-2 text-3xl font-bold sm:text-4xl">
                Setup, markdown reader, and guided chat
              </h1>
              <p className="aw-subtle mt-3 max-w-2xl text-sm leading-6">
                Upload a report, inspect the rendered markdown in the center
                panel, and use chat responses to jump directly to the line that
                supports the key detail.
              </p>
            </div>
            <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
              <span className="aw-chip aw-chip-accent text-center">model {model}</span>
              <span className="aw-chip aw-chip-accent text-center">temp {temperature}</span>
              <span className="aw-chip aw-chip-accent text-center">{harnesses.join(" + ")}</span>
            </div>
          </div>
        </header>

        {error && (
          <section className="aw-card border-red-300 bg-red-50">
            <p className="text-sm text-red-700">{error}</p>
          </section>
        )}

        <section className="grid gap-4 xl:grid-cols-[320px,minmax(0,1.15fr),minmax(360px,0.95fr)]">
          <aside className="aw-card space-y-4 xl:sticky xl:top-6 xl:self-start">
            <div>
              <h2 className="aw-title text-lg font-semibold">Session Setup</h2>
              <p className="aw-subtle mt-1 text-sm">
                Configure the report, model, and harnesses before creating the
                chat session.
              </p>
            </div>

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
              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
                <p className="break-all">Session: {session.session_id}</p>
                <p className="break-all">Report: {session.report_name}</p>
                <p className="break-all">Markdown: {session.report_path}</p>
              </div>
            )}
          </aside>

          <section className="aw-card flex min-h-[72vh] flex-col gap-3 xl:sticky xl:top-6 xl:self-start">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="aw-title text-lg font-semibold">MD reader</h2>
                <p className="aw-subtle mt-1 text-sm">
                  Click a line or a chat citation to focus the supporting detail.
                </p>
              </div>
              <span className="aw-chip">
                {report ? `${report.line_count} lines` : "no report"}
              </span>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-gradient-to-br from-white to-slate-50 p-2">
              <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2 text-xs text-slate-600">
                <span>
                  {report
                    ? `${report.report_name} · ${report.line_count} markdown lines`
                    : isLoadingReport
                      ? "Loading markdown report..."
                      : "Create a session to load the report"}
                </span>
                <span>{selectedLine ? `Focused ${formatLineLabel(selectedLine)}` : "No line focused"}</span>
              </div>
              <div className="max-h-[52vh] overflow-auto px-1 py-2 font-mono text-[11px] leading-5">
                {report && reportLines.length > 0 ? (
                  reportLines.map((lineText, index) => {
                    const line = index + 1;
                    const active = selectedLine === line;
                    return (
                      <button
                        key={`${report.session_id}-${line}`}
                        ref={(element) => {
                          lineRefs.current[line] = element;
                        }}
                        id={`md-line-${line}`}
                        type="button"
                        className={`flex w-full items-start gap-3 rounded-md px-3 py-1.5 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900/40 ${
                          active
                            ? "bg-slate-900 text-white shadow ring-2 ring-slate-900/30"
                            : "hover:bg-slate-100"
                        }`}
                        onClick={() => setSelectedLine(line)}
                      >
                        <span className={`w-12 shrink-0 text-right ${active ? "text-slate-200" : "text-slate-400"}`}>
                          {String(line).padStart(4, "0")}
                        </span>
                        <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">
                          {lineText || " "}
                        </span>
                      </button>
                    );
                  })
                ) : (
                  <div className="px-4 py-6 text-sm text-slate-500">
                    {isLoadingReport
                      ? "Loading report content..."
                      : "The markdown report will appear here after session creation."}
                  </div>
                )}
              </div>
              {selectedLine && selectedLineText && (
                <div className="border-t border-slate-200 px-3 py-2 text-xs text-slate-600">
                  <span className="font-semibold text-slate-800">
                    {formatLineLabel(selectedLine)}
                  </span>
                  <span className="ml-2 break-words">{selectedLineText}</span>
                </div>
              )}
            </div>
          </section>

          <section className="aw-card flex min-h-[72vh] flex-col gap-3 xl:sticky xl:top-6 xl:self-start">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="aw-title text-lg font-semibold">Chat bot</h2>
                <p className="aw-subtle mt-1 text-sm">
                  Ask a question and jump from the answer to the exact markdown
                  line that supports it.
                </p>
              </div>
              <span className="aw-chip">turns: {turns.length}</span>
            </div>

            <div className="flex-1 space-y-3 overflow-auto pr-1">
              {turns.length === 0 ? (
                <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
                  No chat turns yet. Create a session and ask a question.
                </div>
              ) : (
                turns.map((turn) => (
                  <article
                    key={turn.turn_id}
                    className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4"
                  >
                    <div className="rounded-xl bg-slate-50 p-3">
                      <p className="text-xs aw-subtle">User question</p>
                      <p className="text-sm text-slate-800">{turn.question}</p>
                    </div>
                    <div className="space-y-3">
                      {turn.answers.map((ans) => {
                        const lineTargets =
                          ans.evidence_lines.length > 0
                            ? ans.evidence_lines
                            : extractLineNumbers([ans.answer, ...ans.citations]);
                        const primaryLine = ans.primary_evidence_line ?? lineTargets[0] ?? null;

                        return (
                          <div
                            key={`${turn.turn_id}-${ans.profile}`}
                            className="rounded-2xl border border-slate-200 bg-slate-50 p-3"
                          >
                            <div className="mb-2 flex flex-wrap items-center gap-2">
                              <span className="aw-chip aw-chip-accent">
                                {ans.profile}
                              </span>
                              <span className="aw-chip">{ans.elapsed_ms} ms</span>
                              {primaryLine ? (
                                <button
                                  type="button"
                                  className="aw-chip aw-chip-accent cursor-pointer"
                                  onClick={() => jumpToLine(primaryLine)}
                                >
                                  Open {formatLineLabel(primaryLine)}
                                </button>
                              ) : null}
                            </div>
                            <p className="whitespace-pre-wrap text-sm text-slate-800">
                              {ans.answer || "(empty answer)"}
                            </p>
                            <div className="mt-3 space-y-2">
                              <div className="flex items-center justify-between gap-2">
                                <p className="text-xs aw-subtle">Citations</p>
                                <span className="text-[11px] text-slate-500">
                                  {lineTargets.length > 0
                                    ? `${lineTargets.length} linked line${lineTargets.length === 1 ? "" : "s"}`
                                    : "No line links"}
                                </span>
                              </div>
                              {ans.citations.length > 0 ? (
                                <ul className="space-y-2 text-xs text-slate-700">
                                  {ans.citations.map((citation, idx) => {
                                    const citationLines = extractLineNumbers([citation]);
                                    return (
                                      <li
                                        key={`${ans.profile}-${idx}`}
                                        className="rounded-xl border border-slate-200 bg-white px-3 py-2"
                                      >
                                        <div className="flex flex-wrap items-start justify-between gap-2">
                                          <span className="min-w-0 flex-1 break-words">
                                            {citation}
                                          </span>
                                          {citationLines.length > 0 ? (
                                            <div className="flex flex-wrap gap-2">
                                              {citationLines.map((line) => (
                                                <button
                                                  key={`${ans.profile}-${idx}-${line}`}
                                                  type="button"
                                                  className="aw-chip aw-chip-accent cursor-pointer"
                                                  onClick={() => jumpToLine(line)}
                                                >
                                                  Open {formatLineLabel(line)}
                                                </button>
                                              ))}
                                            </div>
                                          ) : (
                                            <button
                                              type="button"
                                              className="aw-chip cursor-pointer"
                                              onClick={() => jumpToLine(primaryLine)}
                                              disabled={!primaryLine}
                                            >
                                              {primaryLine ? `Open ${formatLineLabel(primaryLine)}` : "No line found"}
                                            </button>
                                          )}
                                        </div>
                                      </li>
                                    );
                                  })}
                                </ul>
                              ) : (
                                <p className="text-xs text-slate-500">
                                  No citations
                                </p>
                              )}
                            </div>
                            <details className="mt-3 rounded-xl border border-slate-200 bg-white px-3 py-2">
                              <summary className="cursor-pointer text-xs text-slate-600">
                                Diagnostics
                              </summary>
                              <pre className="mt-2 overflow-auto rounded border border-slate-200 bg-slate-50 p-2 text-[11px] text-slate-700">
                                {JSON.stringify(ans.diagnostics, null, 2)}
                              </pre>
                            </details>
                          </div>
                        );
                      })}
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

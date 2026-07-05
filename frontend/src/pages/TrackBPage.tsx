import { useEffect, useMemo, useState } from "react";

import { AppFrame } from "../components/AppFrame";
import {
  createTrackBUploadRun,
  getTrackBArtifacts,
  getTrackBMetrics,
  getTrackBReproduce,
  getTrackBRunStatus,
  streamTrackBRunEvents,
  type TrackBArtifactsResponse,
  type TrackBEvent,
  type TrackBMetricsResponse,
  type TrackBProfile,
  type TrackBReproduceResponse,
  type TrackBRunStatusResponse,
} from "../features/benchmark/services/benchmarkApi";

const PROFILE_BUTTONS: TrackBProfile[] = [
  "baseline",
  "h1",
  "h2",
  "h3",
  "h4",
  "all",
];

const PROFILE_LABELS: Record<TrackBProfile, string> = {
  baseline: "baseline",
  h1: "h1_1",
  h2: "h1_2",
  h3: "h1_3",
  h4: "h1_4",
  all: "h1_all",
  all_minus_h1: "all_minus_h1",
  all_minus_h2: "all_minus_h2",
  all_minus_h3: "all_minus_h3",
  all_minus_h4: "all_minus_h4",
};

const DEFAULT_PROFILES: TrackBProfile[] = ["baseline"];

const ERROR_TAXONOMY = [
  {
    code: "E1",
    title: "Context miss",
    description: "The answer was produced without enough relevant report context.",
  },
  {
    code: "E2",
    title: "Unit mismatch",
    description: "The answer used the wrong scale or missed the report's unit convention.",
  },
  {
    code: "E3",
    title: "Arithmetic error",
    description: "The answer failed a deterministic numeric or tolerance check.",
  },
  {
    code: "E4",
    title: "Chronology mix-up",
    description: "The answer confused event ordering or time-specific disclosures.",
  },
  {
    code: "E5",
    title: "Unsupported claim",
    description: "The claim was not backed by the cited evidence snippets.",
  },
];

export function TrackBPage() {
  const [model, setModel] = useState("deepseek-v4-flash");
  const [temperature, setTemperature] = useState(0);
  const [batchSize, setBatchSize] = useState(10);
  const [casesCount, setCasesCount] = useState<number | null>(null);
  const batchMin = 1;
  const batchMax = Math.max(casesCount ?? 50, batchMin);
  const batchMarks = useMemo(() => {
    const mid = Math.max(batchMin, Math.round((batchMin + batchMax) / 2));
    return [batchMin, mid, batchMax];
  }, [batchMax]);
  const [profiles, setProfiles] = useState<TrackBProfile[]>(DEFAULT_PROFILES);
  const [reportFile, setReportFile] = useState<File | null>(null);
  const [casesFile, setCasesFile] = useState<File | null>(null);
  const [isDraggingReport, setIsDraggingReport] = useState(false);
  const [isDraggingCases, setIsDraggingCases] = useState(false);

  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<TrackBRunStatusResponse | null>(null);
  const [metrics, setMetrics] = useState<TrackBMetricsResponse | null>(null);
  const [artifacts, setArtifacts] = useState<TrackBArtifactsResponse | null>(
    null,
  );
  const [reproduce, setReproduce] = useState<TrackBReproduceResponse | null>(
    null,
  );
  const [events, setEvents] = useState<TrackBEvent[]>([]);

  const [isLaunching, setIsLaunching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    const source = streamTrackBRunEvents(runId, (evt) => {
      setEvents((prev) => [evt, ...prev].slice(0, 120));
    });
    source.onerror = () => {
      source.close();
    };
    return () => {
      source.close();
    };
  }, [runId]);

  useEffect(() => {
    let active = true;

    const detectCasesCount = async () => {
      if (!casesFile) {
        if (!active) return;
        setCasesCount(null);
        return;
      }

      try {
        const text = await casesFile.text();
        let count = 0;
        if (/\.json$/i.test(casesFile.name)) {
          const parsed = JSON.parse(text);
          count = Array.isArray(parsed) ? parsed.length : 0;
        } else {
          count = text
            .split(/\r?\n/)
            .map((line) => line.trim())
            .filter((line) => line.length > 0).length;
        }
        if (!active) return;
        setCasesCount(count > 0 ? count : null);
      } catch {
        if (!active) return;
        setCasesCount(null);
      }
    };

    void detectCasesCount();
    return () => {
      active = false;
    };
  }, [casesFile]);

  useEffect(() => {
    setBatchSize((prev) => {
      if (prev < batchMin) return batchMin;
      if (prev > batchMax) return batchMax;
      return prev;
    });
  }, [batchMax]);

  useEffect(() => {
    if (!runId) return;
    let active = true;
    let timer: number | null = null;

    const tick = async () => {
      try {
        const next = await getTrackBRunStatus(runId);
        if (!active) return;
        setStatus(next);
        if (next.status === "completed" || next.status === "failed") {
          const [m, a, r] = await Promise.all([
            getTrackBMetrics(runId),
            getTrackBArtifacts(runId),
            getTrackBReproduce(runId),
          ]);
          if (!active) return;
          setMetrics(m);
          setArtifacts(a);
          setReproduce(r);
          return;
        }
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : String(err));
      }
      timer = window.setTimeout(tick, 1500);
    };

    void tick();
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [runId]);

  const selectedProfilesLabel = useMemo(() => profiles.join(", "), [profiles]);
  const selectedProfilesDisplay = useMemo(
    () => profiles.map((p) => PROFILE_LABELS[p]).join(", "),
    [profiles],
  );
  const artifactProfiles = artifacts?.profiles ?? [];

  const reportLabel = reportFile ? `${reportFile.name} (${Math.round(reportFile.size / 1024)} KB)` : "Choose a PDF or markdown report";
  const casesLabel = casesFile ? `${casesFile.name} (${Math.round(casesFile.size / 1024)} KB)` : "Choose the Track B cases file";

  const setSingleFile = (
    file: File | null,
    setFile: (next: File | null) => void,
    allowed: (name: string) => boolean,
  ) => {
    if (!file) {
      setFile(null);
      return;
    }
    if (!allowed(file.name)) {
      setError("Unsupported file type. Use a .pdf, .md, or .jsonl file.");
      return;
    }
    setError(null);
    setFile(file);
  };

  const onToggleProfile = (profile: TrackBProfile) => {
    setProfiles((prev) => {
      const has = prev.includes(profile);

      if (profile === "all") {
        return has ? ["baseline"] : ["all"];
      }

      if (profile === "baseline") {
        return ["baseline"];
      }

      let next = prev.filter((p) => p !== "baseline" && p !== "all");
      if (has) {
        next = next.filter((p) => p !== profile);
      } else {
        next = [...next, profile];
      }

      return next.length > 0 ? next : ["baseline"];
    });
  };

  const onLaunch = async () => {
    setError(null);
    setIsLaunching(true);
    setRunId(null);
    setStatus(null);
    setMetrics(null);
    setArtifacts(null);
    setReproduce(null);
    setEvents([]);

    try {
      if (!reportFile || !casesFile) {
        throw new Error("Select both the report file and the Track B cases file before launching.");
      }
      const run = await createTrackBUploadRun({
        reportFile,
        casesFile,
        model,
        temperature,
        maxCases: 0,
        batchSize,
        profiles,
      });
      setRunId(run.run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsLaunching(false);
    }
  };

  return (
    <AppFrame>
      <div className="space-y-4">
        <header className="aw-card">
          <p className="aw-subtle text-xs uppercase tracking-[0.2em]">
            Track B Workflow
          </p>
          <h1 className="aw-title mt-2 text-3xl font-bold">
            Harness 1: Retrieval + Guardrails
          </h1>
          <p className="aw-subtle mt-2 text-sm">
            Combined Track B harness for retrieval, numeric checks, chronology checks,
            and evidence verification in a single workflow profile.
          </p>
        </header>

        <section className="aw-card space-y-4">
          <h2 className="aw-title text-lg font-semibold">Run Configuration</h2>

          <div className="grid gap-3 md:grid-cols-2">
            <div
              className={`rounded-xl border border-dashed p-4 text-sm transition ${isDraggingReport ? "border-slate-900 bg-slate-50" : "border-slate-300 bg-white"}`}
              onDragOver={(e) => {
                e.preventDefault();
                setIsDraggingReport(true);
              }}
              onDragLeave={() => setIsDraggingReport(false)}
              onDrop={(e) => {
                e.preventDefault();
                setIsDraggingReport(false);
                setSingleFile(e.dataTransfer.files?.[0] ?? null, setReportFile, (name) => /\.(pdf|md)$/i.test(name));
              }}
            >
              <p className="aw-subtle text-xs uppercase tracking-[0.2em]">Report</p>
              <p className="mt-2 font-medium">{reportLabel}</p>
              <p className="aw-subtle mt-1 text-xs">Drop a .pdf or .md file, or use the file picker.</p>
              <input
                className="mt-3 block w-full text-sm"
                type="file"
                accept=".pdf,.md"
                onChange={(e) => setSingleFile(e.target.files?.[0] ?? null, setReportFile, (name) => /\.(pdf|md)$/i.test(name))}
              />
            </div>

            <div
              className={`rounded-xl border border-dashed p-4 text-sm transition ${isDraggingCases ? "border-slate-900 bg-slate-50" : "border-slate-300 bg-white"}`}
              onDragOver={(e) => {
                e.preventDefault();
                setIsDraggingCases(true);
              }}
              onDragLeave={() => setIsDraggingCases(false)}
              onDrop={(e) => {
                e.preventDefault();
                setIsDraggingCases(false);
                setSingleFile(e.dataTransfer.files?.[0] ?? null, setCasesFile, (name) => /\.(jsonl|json)$/i.test(name));
              }}
            >
              <p className="aw-subtle text-xs uppercase tracking-[0.2em]">Cases</p>
              <p className="mt-2 font-medium">{casesLabel}</p>
              <p className="aw-subtle mt-1 text-xs">Drop the Track B cases file or choose it manually.</p>
              <input
                className="mt-3 block w-full text-sm"
                type="file"
                accept=".jsonl,.json"
                onChange={(e) => setSingleFile(e.target.files?.[0] ?? null, setCasesFile, (name) => /\.(jsonl|json)$/i.test(name))}
              />
            </div>

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
                min={0}
                max={2}
                step={0.1}
                value={temperature}
                onChange={(e) => setTemperature(Number(e.target.value || 0))}
              />
            </label>

            <div className="text-sm aw-subtle md:col-span-2">
              <div className="flex items-center justify-between gap-3">
                <span>Batch size (questions per run)</span>
                <span className="aw-chip aw-chip-accent">{batchSize}</span>
              </div>
              <input
                className="mt-2 w-full"
                type="range"
                min={batchMin}
                max={batchMax}
                step={1}
                list="trackb-batch-size-marks"
                value={batchSize}
                onChange={(e) => setBatchSize(Number(e.target.value || batchMin))}
              />
              <datalist id="trackb-batch-size-marks">
                {batchMarks.map((mark) => (
                  <option key={mark} value={mark} label={String(mark)} />
                ))}
              </datalist>
              <div className="mt-1 flex justify-between text-xs">
                {batchMarks.map((mark) => (
                  <span key={mark}>{mark}</span>
                ))}
              </div>
              <p className="aw-subtle mt-1 text-xs">
                Range: {batchMin} to {batchMax}
                {casesCount ? ` (detected from cases file: ${casesCount})` : ""}
              </p>
            </div>
          </div>

          <div className="space-y-2">
            <div className="grid gap-2 md:grid-cols-3">
              {PROFILE_BUTTONS.map((profile) => {
                const selected = profiles.includes(profile);
                return (
                  <button
                    key={profile}
                    type="button"
                    className={`aw-chip text-left ${selected ? "aw-chip-accent" : ""}`}
                    onClick={() => onToggleProfile(profile)}
                  >
                    {PROFILE_LABELS[profile]}
                  </button>
                );
              })}
            </div>
            <p className="aw-subtle text-xs">
              Selected profiles: {selectedProfilesDisplay || "baseline"}
            </p>
          </div>

          <button
            type="button"
            className="aw-button w-auto px-5"
            disabled={isLaunching || !reportFile || !casesFile}
            onClick={onLaunch}
          >
            {isLaunching ? "Launching run..." : "Launch Track B Run"}
          </button>
        </section>

        {error && (
          <section className="aw-card border-red-300 bg-red-50">
            <p className="text-sm text-red-700">{error}</p>
          </section>
        )}

        <section className="aw-card space-y-3">
          <h2 className="aw-title text-lg font-semibold">Run Status</h2>
          <p className="aw-subtle text-sm">Run ID: {runId ?? "not started"}</p>

          {status && (
            <>
              <div className="flex flex-wrap gap-2 text-sm">
                <span className="aw-chip aw-chip-accent">status: {status.status}</span>
                <span className="aw-chip">stage: {status.stage}</span>
                <span className="aw-chip">model: {status.model}</span>
                <span className="aw-chip">temp: {status.temperature}</span>
                <span className="aw-chip">batch: {status.batch_size}/request</span>
              </div>

              <div className="grid gap-2 md:grid-cols-2">
                {status.progress.map((p) => (
                  <div key={p.profile} className="rounded-md border border-slate-200 p-3">
                    <p className="text-sm font-semibold">{p.profile === "baseline" ? "baseline (V0)" : p.profile}</p>
                    <p className="aw-subtle text-xs">{p.status}</p>
                    <p className="aw-subtle text-xs">
                      {p.cases_completed} / {p.cases_total}
                    </p>
                  </div>
                ))}
              </div>
            </>
          )}

          <div className="max-h-56 overflow-auto rounded-md border border-slate-200 p-3">
            {events.length === 0 ? (
              <p className="aw-subtle text-xs">No events yet.</p>
            ) : (
              <ul className="space-y-2 text-xs">
                {events.map((evt) => (
                  <li key={`${evt.seq}-${evt.event}`} className="border-b border-slate-100 pb-1">
                    <span className="font-semibold">{evt.event}</span>
                    <span className="aw-subtle"> [{evt.stage}]</span>
                    <span className="aw-subtle"> seq={evt.seq}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-2">
          <div className="aw-card space-y-3">
            <h2 className="aw-title text-lg font-semibold">Error Taxonomy</h2>
            {!metrics ? (
              <p className="aw-subtle text-sm">Metrics appear after completion.</p>
            ) : (
              <div className="grid gap-3">
                {ERROR_TAXONOMY.map((item) => (
                  <div key={item.code} className="rounded-md border border-slate-200 p-3">
                    <p className="text-sm font-semibold">
                      {item.code}: {item.title}
                    </p>
                    <p className="aw-subtle mt-1 text-xs">{item.description}</p>
                    <p className="aw-subtle mt-2 text-xs">
                      {(() => {
                        const ec = Object.entries(metrics.metrics_by_profile)
                          .flatMap(([, m]) => [((m.error_counts ?? {}) as Record<string, number>)[item.code] ?? 0])
                          .reduce((sum, value) => sum + value, 0);
                        return `Count across profiles: ${ec}`;
                      })()}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="aw-card space-y-3">
            <h2 className="aw-title text-lg font-semibold">Reproducibility</h2>
            {!reproduce ? (
              <p className="aw-subtle text-sm">Run commands appear after completion.</p>
            ) : (
              <>
                <p className="aw-subtle text-xs">Profiles: {String(reproduce.commands.profiles ?? "-")}</p>
                <textarea
                  className="aw-input h-28 font-mono text-xs"
                  readOnly
                  value={String(reproduce.commands.single_variant_template ?? "")}
                />
                <textarea
                  className="aw-input h-28 font-mono text-xs"
                  readOnly
                  value={String(reproduce.commands.api_submit ?? "")}
                />
              </>
            )}
          </div>
        </section>

        <section className="aw-card space-y-3">
          <h2 className="aw-title text-lg font-semibold">Artifacts</h2>
          {!artifacts || artifacts.artifacts.length === 0 ? (
            <p className="aw-subtle text-sm">No artifacts yet.</p>
          ) : (
            <>
              <p className="aw-subtle text-xs">Output dir: {artifacts.output_dir}</p>
              <div className="grid gap-3 md:grid-cols-2">
                {artifactProfiles.map((profileSummary) => (
                  <div key={profileSummary.profile} className="rounded-xl border border-slate-200 p-4">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-semibold">
                        {profileSummary.profile === "baseline" ? "baseline (V0)" : profileSummary.profile}
                      </p>
                      <span className="aw-chip aw-chip-accent">
                        wrong cases: {profileSummary.wrong_case_count}
                      </span>
                    </div>
                    <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                      <div className="rounded-md bg-slate-50 p-2">overall {(Number(profileSummary.overall_accuracy) * 100).toFixed(1)}%</div>
                      <div className="rounded-md bg-slate-50 p-2">numeric {(Number(profileSummary.numeric_accuracy) * 100).toFixed(1)}%</div>
                      <div className="rounded-md bg-slate-50 p-2">citations {(Number(profileSummary.citation_rate) * 100).toFixed(1)}%</div>
                    </div>
                    <div className="mt-3 space-y-2">
                      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Wrong cases</p>
                      {profileSummary.wrong_cases.length === 0 ? (
                        <p className="aw-subtle text-xs">No wrong cases in the preview.</p>
                      ) : (
                        profileSummary.wrong_cases.map((caseItem) => (
                          <div key={caseItem.case_id} className="rounded-md border border-slate-200 p-2 text-xs">
                            <p className="font-semibold">{caseItem.case_id}</p>
                            <p className="aw-subtle mt-1">{caseItem.question}</p>
                            <p className="mt-1">Answer: {caseItem.answer || "(empty)"}</p>
                            <p className="aw-subtle mt-1">Expected: {caseItem.expected_answer}</p>
                            <p className="aw-subtle mt-1">Errors: {caseItem.error_codes.join(", ") || "none"}</p>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                ))}
              </div>

              <div className="max-h-56 overflow-auto rounded-md border border-slate-200 p-3">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left">
                      <th className="px-2 py-2">Profile</th>
                      <th className="px-2 py-2">File</th>
                      <th className="px-2 py-2">Path</th>
                      <th className="px-2 py-2 text-right">Bytes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {artifacts.artifacts.map((a, idx) => (
                      <tr key={`${a.path}-${idx}`} className="border-b border-slate-100">
                        <td className="px-2 py-2">{a.profile}</td>
                        <td className="px-2 py-2">{a.name}</td>
                        <td className="px-2 py-2 font-mono text-xs">{a.path}</td>
                        <td className="px-2 py-2 text-right">{a.bytes}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </section>
      </div>
    </AppFrame>
  );
}

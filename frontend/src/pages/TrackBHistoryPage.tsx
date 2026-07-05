import { useEffect, useState } from "react";

import { AppFrame } from "../components/AppFrame";
import {
  getTrackBHistory,
  type TrackBHistoryResponse,
} from "../features/benchmark/services/benchmarkApi";

export function TrackBHistoryPage() {
  const [history, setHistory] = useState<TrackBHistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadHistory = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getTrackBHistory(24);
      setHistory(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadHistory();
  }, []);

  return (
    <AppFrame>
      <div className="space-y-4">
        <header className="aw-card flex items-start justify-between gap-4">
          <div>
            <p className="aw-subtle text-xs uppercase tracking-[0.2em]">
              Track B History
            </p>
            <h1 className="aw-title mt-2 text-3xl font-bold">
              Run Performance Overview
            </h1>
            <p className="aw-subtle mt-2 text-sm">
              A compact history view over{" "}
              <span className="font-medium">
                phase4_evaluation/results/trackb_runs
              </span>{" "}
              with a focus on metrics.json summaries.
            </p>
          </div>
          <button
            type="button"
            className="aw-button w-auto px-4"
            onClick={() => void loadHistory()}
          >
            Refresh
          </button>
        </header>

        {error && (
          <section className="aw-card border-red-300 bg-red-50">
            <p className="text-sm text-red-700">{error}</p>
          </section>
        )}

        {loading && !history ? (
          <section className="aw-card">
            <p className="aw-subtle text-sm">Loading history...</p>
          </section>
        ) : null}

        <section className="space-y-4">
          {history?.runs?.length ? (
            history.runs.map((run) => (
              <article key={run.run_id} className="aw-card space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="aw-title text-xl font-semibold">
                      {run.run_id}
                    </h2>
                    <p className="aw-subtle text-xs">
                      {run.created_at} | {run.status} | {run.model} | temp{" "}
                      {run.temperature}
                    </p>
                    <p className="aw-subtle mt-1 text-xs">{run.output_dir}</p>
                  </div>
                  <span className="aw-chip aw-chip-accent">
                    profiles: {run.profiles.length}
                  </span>
                </div>

                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {run.profiles.map((profile) => (
                    <div
                      key={profile.profile}
                      className="rounded-xl border border-slate-200 p-4"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-semibold">
                          {profile.profile}
                        </p>
                        <span className="aw-chip aw-chip-accent">
                          wrong {profile.wrong_case_count}
                        </span>
                      </div>
                      <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                        <div className="rounded-md bg-slate-50 p-2">
                          overall{" "}
                          {(Number(profile.overall_accuracy) * 100).toFixed(1)}%
                        </div>
                        <div className="rounded-md bg-slate-50 p-2">
                          numeric{" "}
                          {(Number(profile.numeric_accuracy) * 100).toFixed(1)}%
                        </div>
                        <div className="rounded-md bg-slate-50 p-2">
                          citations{" "}
                          {(Number(profile.citation_rate) * 100).toFixed(1)}%
                        </div>
                      </div>
                      {profile.llm_telemetry_summary ? (
                        <div className="mt-2 rounded-md bg-slate-50 p-2 text-xs">
                          <div>
                            llm req{" "}
                            {profile.llm_telemetry_summary.total_requests} | ok{" "}
                            {profile.llm_telemetry_summary.success_count} | fail{" "}
                            {profile.llm_telemetry_summary.failure_count}
                          </div>
                          <div className="aw-subtle mt-1">
                            avg{" "}
                            {profile.llm_telemetry_summary.avg_elapsed_ms.toFixed(
                              1,
                            )}{" "}
                            ms | tokens{" "}
                            {profile.llm_telemetry_summary.total_tokens}
                          </div>
                          {profile.llm_telemetry_preview &&
                          profile.llm_telemetry_preview.length > 0 ? (
                            <div className="aw-subtle mt-1">
                              last:{" "}
                              {
                                profile.llm_telemetry_preview[
                                  profile.llm_telemetry_preview.length - 1
                                ].process
                              }
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                      <div className="mt-3 text-xs text-slate-600">
                        error counts:{" "}
                        {Object.entries(
                          (profile.metrics.error_counts ?? {}) as Record<
                            string,
                            number
                          >,
                        )
                          .map(([k, v]) => `${k}:${v}`)
                          .join(" · ") || "n/a"}
                      </div>
                    </div>
                  ))}
                </div>
              </article>
            ))
          ) : (
            <section className="aw-card">
              <p className="aw-subtle text-sm">
                No completed Track B history runs found yet.
              </p>
            </section>
          )}
        </section>
      </div>
    </AppFrame>
  );
}

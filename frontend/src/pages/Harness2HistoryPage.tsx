import { useEffect, useMemo, useState } from "react";

import { AppFrame } from "../components/AppFrame";
import {
  getHarness2History,
  type Harness2BuildResponse,
  type Harness2HistoryResponse,
} from "../features/benchmark/services/benchmarkApi";

function TrendGraph({ points }: { points: Array<{ date: string; close: number }> }) {
  const graph = useMemo(() => {
    if (!points.length) {
      return { path: "", min: 0, max: 0 };
    }
    const values = points.map((p) => p.close);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const width = 720;
    const height = 180;
    const denom = Math.max(max - min, 1e-9);

    const path = points
      .map((p, idx) => {
        const x = (idx / Math.max(points.length - 1, 1)) * width;
        const y = height - ((p.close - min) / denom) * height;
        return `${idx === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(" ");

    return { path, min, max };
  }, [points]);

  if (!points.length) {
    return <p className="aw-subtle text-xs">No trend points captured for this run.</p>;
  }

  return (
    <div className="space-y-2">
      <svg viewBox="0 0 720 180" className="w-full rounded-lg border border-slate-200 bg-white p-2">
        <path d={graph.path} fill="none" stroke="#0f766e" strokeWidth="2.5" />
      </svg>
      <div className="flex items-center justify-between text-[11px] aw-subtle">
        <span>{points[0].date}</span>
        <span>
          min {graph.min.toFixed(2)} | max {graph.max.toFixed(2)}
        </span>
        <span>{points[points.length - 1].date}</span>
      </div>
    </div>
  );
}

function RunCard({ run }: { run: Harness2BuildResponse }) {
  const downloadCode = run.download_script_code.trim();

  return (
    <article className="aw-card space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="aw-subtle text-xs uppercase tracking-[0.18em]">{run.symbol || "unlabeled run"}</p>
          <h2 className="aw-title mt-1 text-xl font-semibold break-all">{run.run_id}</h2>
          <p className="aw-subtle mt-1 text-xs">{run.created_at}</p>
          <p className="aw-subtle mt-1 text-xs break-all">{run.resolved_root_link || run.seed_url || "No root link resolved"}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="aw-chip aw-chip-accent">reports {run.reports.length}</span>
          <span className="aw-chip aw-chip-accent">root {run.evaluation.root_link_ok ? "ok" : "miss"}</span>
        </div>
      </div>

      <div className="grid gap-2 md:grid-cols-4 text-sm">
        <div className="rounded-lg bg-slate-50 p-3">PDF {(run.evaluation.pdf_download_rate * 100).toFixed(1)}%</div>
        <div className="rounded-lg bg-slate-50 p-3">MD {(run.evaluation.markdown_conversion_rate * 100).toFixed(1)}%</div>
        <div className="rounded-lg bg-slate-50 p-3">Internal {(run.evaluation.internal_report_rate * 100).toFixed(1)}%</div>
        <div className="rounded-lg bg-slate-50 p-3">Trend {(run.evaluation.trend_direction_accuracy * 100).toFixed(1)}%</div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-slate-200 p-4 text-sm">
          <p className="font-semibold text-[#1E293B]">Configuration</p>
          <div className="mt-2 space-y-1 aw-subtle text-xs">
            <p>Output: {run.output_dir}</p>
            <p>Seed: {run.seed_url || "n/a"}</p>
            <p>Model: {String(run.metadata.model ?? "n/a")}</p>
            <p>Analysis profile: {String(run.metadata.analysis_profile ?? "n/a")}</p>
            <p>Horizon: {String(run.metadata.horizon_days ?? "n/a")} days</p>
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 p-4 text-sm">
          <p className="font-semibold text-[#1E293B]">Notes</p>
          {run.notes.length ? (
            <ul className="mt-2 list-disc space-y-1 pl-5 aw-subtle text-xs">
              {run.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 aw-subtle text-xs">No notes recorded.</p>
          )}
        </div>
      </div>

      <details className="rounded-xl border border-slate-200 p-4">
        <summary className="cursor-pointer text-sm font-semibold text-[#1E293B]">Trend series</summary>
        <div className="mt-3">
          <TrendGraph points={run.trend_points} />
        </div>
      </details>

      <details className="rounded-xl border border-slate-200 p-4">
        <summary className="cursor-pointer text-sm font-semibold text-[#1E293B]">Reports ({run.reports.length})</summary>
        <div className="mt-3 space-y-3">
          {run.reports.length ? (
            run.reports.map((report) => (
              <div key={`${run.run_id}-${report.source_url}-${report.title}`} className="rounded-lg bg-slate-50 p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-semibold text-[#1E293B]">{report.title}</p>
                  <span className="aw-chip aw-chip-accent">{report.predicted_trend} → {report.actual_trend}</span>
                </div>
                <p className="mt-1 aw-subtle text-xs break-all">{report.source_url || "n/a"}</p>
                <p className="mt-2 text-xs">Date: {report.report_date ?? "n/a"} | Rating: {report.rating.toFixed(1)}/10</p>
                <p className="mt-2 text-xs"><span className="font-semibold">Summary:</span> {report.summary || "n/a"}</p>
                <p className="mt-1 text-xs"><span className="font-semibold">Overview:</span> {report.overview || "n/a"}</p>
                <p className="mt-1 text-xs"><span className="font-semibold">Further direction:</span> {report.further_direction || "n/a"}</p>
                <p className="mt-1 text-xs">
                  <span className="font-semibold">Correct:</span> {report.trend_correct === null ? "n/a" : report.trend_correct ? "yes" : "no"}
                </p>
                <p className="mt-1 break-all text-[11px] aw-subtle">PDF: {report.pdf_path}</p>
                <p className="mt-1 break-all text-[11px] aw-subtle">MD: {report.markdown_path}</p>
                <p className="mt-1 break-all text-[11px] aw-subtle">Internal: {report.internal_report_path}</p>
              </div>
            ))
          ) : (
            <p className="aw-subtle text-xs">No reports were reconstructed for this run.</p>
          )}
        </div>
      </details>

      <details className="rounded-xl border border-slate-200 p-4">
        <summary className="cursor-pointer text-sm font-semibold text-[#1E293B]">Download script</summary>
        <div className="mt-3 space-y-2">
          <p className="aw-subtle text-xs break-all">{run.download_script_path || "n/a"}</p>
          <pre className="max-h-[220px] overflow-auto rounded-lg border border-slate-200 bg-slate-950 p-3 text-[11px] text-slate-100">
            {downloadCode || "No script content saved for this run."}
          </pre>
        </div>
      </details>
    </article>
  );
}

export function Harness2HistoryPage() {
  const [history, setHistory] = useState<Harness2HistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [symbol, setSymbol] = useState("");
  const [limit, setLimit] = useState(24);
  const [sort, setSort] = useState<"created_at" | "run_id" | "symbol">("created_at");
  const [order, setOrder] = useState<"asc" | "desc">("desc");

  const loadHistory = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getHarness2History({
        q: query,
        symbol,
        limit,
        sort,
        order,
      });
      setHistory(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AppFrame>
      <div className="space-y-4">
        <header className="aw-card flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="aw-subtle text-xs uppercase tracking-[0.2em]">Harness 2 History</p>
            <h1 className="aw-title mt-2 text-3xl font-bold">Search Prior Runs</h1>
            <p className="aw-subtle mt-2 text-sm">
              Browse saved Harness 2 runs from <span className="font-medium">phase4_evaluation/results/harness2_history</span>, filter by symbol or text, and inspect trend-validation output.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="aw-button w-auto px-4" onClick={() => void loadHistory()}>
              Refresh
            </button>
          </div>
        </header>

        <section className="aw-card space-y-4">
          <h2 className="aw-title text-lg font-semibold">Search</h2>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <label className="text-sm aw-subtle xl:col-span-2">
              Query
              <input className="aw-input mt-1" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="run id, root link, note, report text" />
            </label>
            <label className="text-sm aw-subtle">
              Symbol
              <input className="aw-input mt-1" value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="GOOGL" />
            </label>
            <label className="text-sm aw-subtle">
              Limit
              <input className="aw-input mt-1" type="number" min={1} max={100} value={limit} onChange={(e) => setLimit(Number(e.target.value || 24))} />
            </label>
            <label className="text-sm aw-subtle">
              Sort
              <select className="aw-input mt-1" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
                <option value="created_at">created_at</option>
                <option value="run_id">run_id</option>
                <option value="symbol">symbol</option>
              </select>
            </label>
            <label className="text-sm aw-subtle">
              Order
              <select className="aw-input mt-1" value={order} onChange={(e) => setOrder(e.target.value as typeof order)}>
                <option value="desc">desc</option>
                <option value="asc">asc</option>
              </select>
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="aw-button w-auto px-4" onClick={() => void loadHistory()}>
              Search History
            </button>
            <button
              type="button"
              className="aw-button aw-button-secondary w-auto px-4"
              onClick={() => {
                setQuery("");
                setSymbol("");
                setLimit(24);
                setSort("created_at");
                setOrder("desc");
              }}
            >
              Reset
            </button>
          </div>
        </section>

        {error ? (
          <section className="aw-card border-red-300 bg-red-50">
            <p className="text-sm text-red-700">{error}</p>
          </section>
        ) : null}

        {loading && !history ? (
          <section className="aw-card">
            <p className="aw-subtle text-sm">Loading Harness 2 history...</p>
          </section>
        ) : null}

        <section className="space-y-4">
          <div className="aw-card flex flex-wrap items-center justify-between gap-2 text-sm aw-subtle">
            <p>
              Showing {history?.runs.length ?? 0} of {history?.total ?? 0} runs
            </p>
            <p>
              sort {history?.sort ?? sort} | order {history?.order ?? order}
            </p>
          </div>

          {history?.runs.length ? (
            history.runs.map((run) => <RunCard key={run.run_id} run={run} />)
          ) : (
            <section className="aw-card">
              <p className="aw-subtle text-sm">No Harness 2 history runs matched the current filters.</p>
            </section>
          )}
        </section>
      </div>
    </AppFrame>
  );
}
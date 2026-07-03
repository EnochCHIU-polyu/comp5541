import { useMemo, useState } from "react";

import { AppFrame } from "../components/AppFrame";
import {
  buildHarness2HistoryUpload,
  type Harness2BuildResponse,
} from "../features/benchmark/services/benchmarkApi";

function TrendGraph({ points }: { points: Array<{ date: string; close: number }> }) {
  const graph = useMemo(() => {
    if (!points.length) {
      return { path: "", min: 0, max: 0 };
    }
    const values = points.map((p) => p.close);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const width = 760;
    const height = 260;
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
    return <p className="aw-subtle text-sm">No trend points available.</p>;
  }

  return (
    <div className="space-y-2">
      <svg viewBox="0 0 760 260" className="w-full rounded-lg border border-slate-200 bg-white p-2">
        <path d={graph.path} fill="none" stroke="#0f766e" strokeWidth="2.5" />
      </svg>
      <div className="flex items-center justify-between text-xs aw-subtle">
        <span>{points[0].date}</span>
        <span>
          min {graph.min.toFixed(2)} | max {graph.max.toFixed(2)}
        </span>
        <span>{points[points.length - 1].date}</span>
      </div>
    </div>
  );
}

export function Harness2Page() {
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [symbol, setSymbol] = useState("GOOGL");
  const [maxReports, setMaxReports] = useState(5);
  const [horizonDays, setHorizonDays] = useState(30);
  const [analysisProfile, setAnalysisProfile] = useState<"baseline" | "h1_all">("h1_all");
  const [model, setModel] = useState("deepseek-v4-flash");
  const [temperature, setTemperature] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Harness2BuildResponse | null>(null);

  const onRun = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      if (!sourceFile) {
        throw new Error("Choose a source file (.md or .pdf) first.");
      }
      const fileName = sourceFile.name.toLowerCase();
      if (!fileName.endsWith(".md") && !fileName.endsWith(".pdf")) {
        throw new Error("Harness 2 input must be .md or .pdf");
      }

      const data = await buildHarness2HistoryUpload({
        source_file: sourceFile,
        symbol: symbol.trim(),
        max_reports: maxReports,
        horizon_days: horizonDays,
        analysis_profile: analysisProfile,
        model,
        temperature,
      });
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AppFrame>
      <div className="space-y-4">
        <header className="aw-card">
          <p className="aw-subtle text-xs uppercase tracking-[0.2em]">Harness 2</p>
          <h1 className="aw-title mt-2 text-3xl font-bold">History Search + LLM Trend Reports</h1>
          <p className="aw-subtle mt-2 text-sm">
            Upload a source markdown/PDF, let LLM find the root report link, generate secure download code,
            analyze each report with baseline or harness1-style context, and validate trends against stock prices.
          </p>
        </header>

        <section className="aw-card space-y-4">
          <h2 className="aw-title text-lg font-semibold">Run Configuration</h2>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-sm aw-subtle md:col-span-2">
              Source file (.md or .pdf)
              <input
                className="aw-input mt-1"
                type="file"
                accept=".md,.pdf"
                onChange={(e) => setSourceFile(e.target.files?.[0] ?? null)}
              />
              <p className="aw-subtle mt-1 text-xs">{sourceFile ? sourceFile.name : "No file selected"}</p>
            </label>

            <label className="text-sm aw-subtle">
              Stock Symbol
              <input className="aw-input mt-1" value={symbol} onChange={(e) => setSymbol(e.target.value)} />
            </label>

            <label className="text-sm aw-subtle">
              Max Reports
              <input
                className="aw-input mt-1"
                type="number"
                min={1}
                max={20}
                value={maxReports}
                onChange={(e) => setMaxReports(Number(e.target.value || 5))}
              />
            </label>

            <label className="text-sm aw-subtle">
              Trend Horizon (days)
              <input
                className="aw-input mt-1"
                type="number"
                min={1}
                max={365}
                value={horizonDays}
                onChange={(e) => setHorizonDays(Number(e.target.value || 30))}
              />
            </label>

            <label className="text-sm aw-subtle">
              Analysis Profile
              <select
                className="aw-input mt-1"
                value={analysisProfile}
                onChange={(e) => setAnalysisProfile((e.target.value as "baseline" | "h1_all") || "baseline")}
              >
                <option value="baseline">baseline</option>
                <option value="h1_all">h1_all (harness1 retrieval context)</option>
              </select>
            </label>

            <label className="text-sm aw-subtle">
              Model
              <input className="aw-input mt-1" value={model} onChange={(e) => setModel(e.target.value)} />
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
          </div>

          <button type="button" className="aw-button" onClick={() => void onRun()} disabled={loading}>
            {loading ? "Running Harness 2..." : "Build Harness 2 From Uploaded Source"}
          </button>
        </section>

        {error ? (
          <section className="aw-card border-red-300 bg-red-50">
            <p className="text-sm text-red-700">{error}</p>
          </section>
        ) : null}

        {result ? (
          <>
            <section className="aw-card space-y-2">
              <h2 className="aw-title text-lg font-semibold">Summary</h2>
              <p className="aw-subtle text-sm">Run ID: {result.run_id}</p>
              <p className="aw-subtle text-sm break-all">Resolved root: {result.resolved_root_link}</p>
              <p className="aw-subtle text-sm">Output: {result.output_dir}</p>
              <p className="aw-subtle text-sm">Download script: {result.download_script_path}</p>
              <div className="grid gap-2 md:grid-cols-3 text-sm">
                <div className="rounded-lg bg-slate-50 p-2">PDF download rate: {(result.evaluation.pdf_download_rate * 100).toFixed(1)}%</div>
                <div className="rounded-lg bg-slate-50 p-2">MD conversion rate: {(result.evaluation.markdown_conversion_rate * 100).toFixed(1)}%</div>
                <div className="rounded-lg bg-slate-50 p-2">Trend direction accuracy: {(result.evaluation.trend_direction_accuracy * 100).toFixed(1)}%</div>
              </div>
            </section>

            <section className="aw-card space-y-3">
              <h2 className="aw-title text-lg font-semibold">Trend Graph (Company Situation)</h2>
              <TrendGraph points={result.trend_points} />
            </section>

            <section className="aw-card space-y-3">
              <h2 className="aw-title text-lg font-semibold">Evaluation Checklist</h2>
              <div className="grid gap-2 md:grid-cols-2 text-sm">
                {Object.entries(result.evaluation.checklist).map(([k, v]) => (
                  <div key={k} className="rounded-lg border border-slate-200 p-2">
                    <span className="font-medium">{k}</span>: {v ? "yes" : "no"}
                  </div>
                ))}
              </div>
            </section>

            <section className="aw-card space-y-3">
              <h2 className="aw-title text-lg font-semibold">Report Results</h2>
              <div className="space-y-2">
                {result.reports.map((report) => (
                  <article key={report.source_url} className="rounded-lg border border-slate-200 p-3 text-sm">
                    <p className="font-semibold">{report.title}</p>
                    <p className="aw-subtle mt-1 break-all">{report.source_url}</p>
                    <p className="aw-subtle mt-1">Date: {report.report_date ?? "n/a"}</p>
                    <p className="mt-1">
                      Predicted: <span className="font-medium">{report.predicted_trend}</span> | Actual: <span className="font-medium">{report.actual_trend}</span> | Correct: <span className="font-medium">{report.trend_correct === null ? "n/a" : report.trend_correct ? "yes" : "no"}</span> | Rating: <span className="font-medium">{report.rating.toFixed(1)}/10</span>
                    </p>
                    <p className="mt-2"><span className="font-medium">Summary:</span> {report.summary || "n/a"}</p>
                    <p className="mt-1"><span className="font-medium">Overview:</span> {report.overview || "n/a"}</p>
                    <p className="mt-1"><span className="font-medium">Further direction:</span> {report.further_direction || "n/a"}</p>
                    <p className="aw-subtle mt-1 break-all">Internal report: {report.internal_report_path}</p>
                  </article>
                ))}
              </div>
            </section>

            <section className="aw-card space-y-2">
              <h2 className="aw-title text-lg font-semibold">Secure Download Code</h2>
              <pre className="max-h-[360px] overflow-auto rounded-lg border border-slate-200 bg-slate-950 p-3 text-xs text-slate-100">
                {result.download_script_code}
              </pre>
            </section>

            {result.notes.length > 0 ? (
              <section className="aw-card space-y-2">
                <h2 className="aw-title text-lg font-semibold">Notes</h2>
                <ul className="list-disc space-y-1 pl-5 text-sm aw-subtle">
                  {result.notes.map((note, idx) => (
                    <li key={`${idx}-${note}`}>{note}</li>
                  ))}
                </ul>
              </section>
            ) : null}
          </>
        ) : null}
      </div>
    </AppFrame>
  );
}

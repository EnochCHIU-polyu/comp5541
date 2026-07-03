import { TrackBHarnessPageShell } from "./TrackBHarnessPageShell";

export function TrackBH3Page() {
  return (
    <TrackBHarnessPageShell
      harnessId="H3"
      title="Chronology Guard"
      subtitle="Verifies that event order and funding chronology match the source report."
      sourcePath="phase2_llm_engine/trackb_harnesses/h3_chronology_guard.py"
      focus={[
        "Event ordering",
        "Disclosure dates",
        "Funding sequence checks",
      ]}
      notes={[
        "Extend the expected-event parsing if the report format changes.",
        "Use this harness to catch timeline conflation across reporting periods.",
      ]}
    />
  );
}

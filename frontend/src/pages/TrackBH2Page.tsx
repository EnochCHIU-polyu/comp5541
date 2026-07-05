import { TrackBHarnessPageShell } from "./TrackBHarnessPageShell";

export function TrackBH2Page() {
  return (
    <TrackBHarnessPageShell
      harnessId="H2"
      title="Numeric Guard"
      subtitle="Checks unit consistency and numeric tolerance before a result is accepted."
      sourcePath="phase2_llm_engine/trackb_harnesses/h2_numeric_guard.py"
      focus={[
        "Unit normalization",
        "Arithmetic sanity checks",
        "Tolerance handling",
      ]}
      notes={[
        "Update the unit list when new report conventions appear.",
        "Adjust tolerance rules per question type if needed.",
      ]}
    />
  );
}

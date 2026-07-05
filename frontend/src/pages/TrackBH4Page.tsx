import { TrackBHarnessPageShell } from "./TrackBHarnessPageShell";

export function TrackBH4Page() {
  return (
    <TrackBHarnessPageShell
      harnessId="H4"
      title="Skeptical Verifier"
      subtitle="Flags answers whose citations do not appear to support the claim."
      sourcePath="phase2_llm_engine/trackb_harnesses/h4_verifier.py"
      focus={[
        "Citation support",
        "False-positive suppression",
        "Answer verification",
      ]}
      notes={[
        "Strengthen verification rules if citation style becomes more structured.",
        "Use this page to tune what counts as evidence-backed support.",
      ]}
    />
  );
}

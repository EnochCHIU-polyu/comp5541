import { TrackBHarnessPageShell } from "./TrackBHarnessPageShell";

export function TrackBH1Page() {
  return (
    <TrackBHarnessPageShell
      harnessId="H1"
      title="Retrieval Harness"
      subtitle="Ranks report chunks and feeds the most relevant context into answer generation."
      sourcePath="phase2_llm_engine/trackb_harnesses/h1_retrieval.py"
      focus={[
        "Chunk selection",
        "Long-context reduction",
        "Evidence-first answering",
      ]}
      notes={[
        "Edit retrieval chunking if the report is still too large or table-heavy.",
        "Tune top-k to balance coverage and prompt length.",
      ]}
    />
  );
}

import { AppFrame } from "../components/AppFrame";

export interface TrackBHarnessPageShellProps {
  harnessId: "H1" | "H2" | "H3" | "H4";
  title: string;
  subtitle: string;
  sourcePath: string;
  focus: string[];
  notes: string[];
}

export function TrackBHarnessPageShell({
  harnessId,
  title,
  subtitle,
  sourcePath,
  focus,
  notes,
}: TrackBHarnessPageShellProps) {
  return (
    <AppFrame>
      <div className="space-y-4">
        <header className="aw-card">
          <p className="aw-subtle text-xs uppercase tracking-[0.2em]">Track B Harness {harnessId}</p>
          <h1 className="aw-title mt-2 text-3xl font-bold">{title}</h1>
          <p className="aw-subtle mt-2 text-sm">{subtitle}</p>
        </header>

        <section className="grid gap-4 md:grid-cols-2">
          <div className="aw-card space-y-3">
            <h2 className="aw-title text-lg font-semibold">Source</h2>
            <p className="aw-subtle text-sm">{sourcePath}</p>
            <p className="text-sm text-slate-700">
              This page is a design surface for the harness module. Use it to review the current role of the harness before changing code.
            </p>
          </div>

          <div className="aw-card space-y-3">
            <h2 className="aw-title text-lg font-semibold">Primary Focus</h2>
            <div className="flex flex-wrap gap-2">
              {focus.map((item) => (
                <span key={item} className="aw-chip aw-chip-accent">{item}</span>
              ))}
            </div>
          </div>
        </section>

        <section className="aw-card space-y-3">
          <h2 className="aw-title text-lg font-semibold">Editing Notes</h2>
          <div className="grid gap-3 md:grid-cols-2">
            {notes.map((note) => (
              <div key={note} className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
                {note}
              </div>
            ))}
          </div>
        </section>
      </div>
    </AppFrame>
  );
}

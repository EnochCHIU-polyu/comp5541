import { AppFrame } from "../components/AppFrame";

export function LandingPage() {
  return (
    <AppFrame>
      <section className="mx-auto w-full max-w-5xl">
        <div className="aw-card">
          <p className="aw-subtle text-xs uppercase tracking-[0.2em]">
            AI Powered Financial Analysis
          </p>
          <h1 className="aw-title mt-3 text-3xl font-bold md:text-4xl">
            AI Notes and Learning Platform
          </h1>
          <p className="aw-subtle mx-auto mt-3 max-w-xl text-sm md:text-base">
            This blank startup is ready for drafting your new system. Replace
            the sections below with your feature implementation.
          </p>

          <div className="mt-6 grid gap-4 md:grid-cols-3">
            <article id="draft-notes" className="aw-card bg-white/80">
              <h2 className="aw-title text-lg font-semibold">Notes Draft</h2>
              <p className="aw-subtle mt-2 text-sm">
                Start with note blocks, tags, and AI summarization workflows.
              </p>
            </article>

            <article id="learning-plan" className="aw-card bg-white/80">
              <h2 className="aw-title text-lg font-semibold">Learning Plan</h2>
              <p className="aw-subtle mt-2 text-sm">
                Define weekly goals, topics, and adaptive learning checkpoints.
              </p>
            </article>

            <article id="reminders" className="aw-card bg-white/80">
              <h2 className="aw-title text-lg font-semibold">Reminders</h2>
              <p className="aw-subtle mt-2 text-sm">
                Keep a placeholder for notification rules and study reminders.
              </p>
            </article>
          </div>
        </div>
      </section>
    </AppFrame>
  );
}

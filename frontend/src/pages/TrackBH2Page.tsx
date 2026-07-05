import { useEffect, useState } from "react";

import { AppFrame } from "../components/AppFrame";
import {
  getTrackBH2Source,
  saveTrackBH2Source,
} from "../features/benchmark/services/benchmarkApi";

interface PromptTemplateParts {
  prefix: string;
  middle: string;
  suffix: string;
}

function locatePromptBlock(source: string): { start: number; end: number } {
  const start = source.indexOf("def build_h2_prompt(");
  if (start < 0) {
    throw new Error("Cannot find build_h2_prompt() in H2 source.");
  }

  const afterStart = source.slice(start + 1);
  const relNext = afterStart.search(/\n\ndef\s+[A-Za-z_][A-Za-z0-9_]*\s*\(/);
  const end = relNext >= 0 ? start + 1 + relNext : source.length;
  return { start, end };
}

function extractPromptBlock(source: string): string {
  const { start, end } = locatePromptBlock(source);
  return source.slice(start, end).trimEnd();
}

function replacePromptBlock(source: string, promptBlock: string): string {
  const { start, end } = locatePromptBlock(source);
  return `${source.slice(0, start)}${promptBlock.trimEnd()}${source.slice(end)}`;
}

function splitPromptBlock(promptBlock: string): {
  parts: PromptTemplateParts;
  systemExpr: string;
  userExpr: string;
} | null {
  const pattern =
    /([\s\S]*?"role":\s*"system",\s*"content":\s*\()([\s\S]*?)(\)\s*},[\s\S]*?"role":\s*"user",\s*"content":\s*\()([\s\S]*?)(\)\s*},[\s\S]*)/;
  const match = promptBlock.match(pattern);
  if (!match) return null;

  return {
    parts: {
      prefix: match[1],
      middle: match[3],
      suffix: match[5],
    },
    systemExpr: match[2].trim(),
    userExpr: match[4].trim(),
  };
}

function buildPromptBlockFromSections(
  parts: PromptTemplateParts,
  systemExpr: string,
  userExpr: string,
): string {
  return `${parts.prefix}${systemExpr.trim()}${parts.middle}${userExpr.trim()}${parts.suffix}`;
}

export function TrackBH2Page() {
  const [sourcePath, setSourcePath] = useState(
    "phase2_llm_engine/trackb_harnesses/h2_prompt_base.py",
  );
  const [fullSource, setFullSource] = useState("");
  const [promptBlock, setPromptBlock] = useState("");
  const [templateParts, setTemplateParts] =
    useState<PromptTemplateParts | null>(null);
  const [systemExpr, setSystemExpr] = useState("");
  const [userExpr, setUserExpr] = useState("");
  const [guidedMode, setGuidedMode] = useState(true);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const boot = async () => {
      setIsLoading(true);
      setError(null);
      setSaveMessage(null);
      try {
        const payload = await getTrackBH2Source();
        if (!active) return;
        setSourcePath(payload.source_path);
        setFullSource(payload.full_source);
        const extracted = extractPromptBlock(payload.full_source);
        setPromptBlock(extracted);

        const split = splitPromptBlock(extracted);
        if (split) {
          setTemplateParts(split.parts);
          setSystemExpr(split.systemExpr);
          setUserExpr(split.userExpr);
          setGuidedMode(true);
        } else {
          setTemplateParts(null);
          setGuidedMode(false);
        }
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (active) setIsLoading(false);
      }
    };

    void boot();
    return () => {
      active = false;
    };
  }, []);

  const onSave = async () => {
    setIsSaving(true);
    setError(null);
    setSaveMessage(null);
    try {
      const nextPromptBlock =
        guidedMode && templateParts
          ? buildPromptBlockFromSections(templateParts, systemExpr, userExpr)
          : promptBlock;

      const nextSource = replacePromptBlock(fullSource, nextPromptBlock);
      const saved = await saveTrackBH2Source(nextSource);
      setFullSource(nextSource);
      setPromptBlock(nextPromptBlock);
      setSaveMessage(
        `Saved ${saved.bytes_written} bytes to ${saved.source_path}. Runtime refreshed: ${saved.runtime_refreshed ? "yes" : "no"}.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <AppFrame>
      <div className="space-y-4">
        <header className="aw-card">
          <p className="aw-subtle text-xs uppercase tracking-[0.2em]">
            Track B Harness H2
          </p>
          <h1 className="aw-title mt-2 text-3xl font-bold">H2 Prompt Editor</h1>
          <p className="aw-subtle mt-2 text-sm">
            Edit H2 prompt-building logic and save. Changes apply to new Track B
            runs across the system.
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <span className="aw-chip">source: {sourcePath}</span>
          </div>
        </header>

        {error && (
          <section className="aw-card border-red-300 bg-red-50">
            <p className="text-sm text-red-700">{error}</p>
          </section>
        )}

        {saveMessage && (
          <section className="aw-card border-emerald-300 bg-emerald-50">
            <p className="text-sm text-emerald-700">{saveMessage}</p>
          </section>
        )}

        <section className="aw-card space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="aw-title text-lg font-semibold">H2 Prompt Editor</h2>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="aw-chip"
                disabled={isLoading || !templateParts}
                onClick={() => setGuidedMode((prev) => !prev)}
              >
                {guidedMode ? "Switch to raw mode" : "Switch to guided mode"}
              </button>
              <button
                type="button"
                className="aw-button w-auto px-4 py-2"
                disabled={isLoading || isSaving}
                onClick={onSave}
              >
                {isSaving ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
          {isLoading ? (
            <p className="aw-subtle text-sm">Loading H2 prompt section...</p>
          ) : guidedMode && templateParts ? (
            <div className="space-y-3">
              <p className="aw-subtle text-sm">
                Guided mode lets you edit only the prompt content. Keep valid
                Python string expressions in both fields.
              </p>

              <label className="text-sm aw-subtle">
                System Prompt Content
                <textarea
                  className="aw-input mt-1 resize-y font-mono text-xs"
                  rows={10}
                  value={systemExpr}
                  onChange={(e) => setSystemExpr(e.target.value)}
                />
              </label>

              <label className="text-sm aw-subtle">
                User Prompt Content
                <textarea
                  className="aw-input mt-1 resize-y font-mono text-xs"
                  rows={16}
                  value={userExpr}
                  onChange={(e) => setUserExpr(e.target.value)}
                />
              </label>
            </div>
          ) : (
            <div className="space-y-2">
              <p className="aw-subtle text-sm">
                Raw mode fallback for advanced edits to the full
                build_h2_prompt() function block.
              </p>
              <textarea
                className="aw-input resize-y font-mono text-xs"
                rows={30}
                style={{ minHeight: "72vh", height: "72vh" }}
                value={promptBlock}
                onChange={(e) => setPromptBlock(e.target.value)}
              />
            </div>
          )}
        </section>
      </div>
    </AppFrame>
  );
}

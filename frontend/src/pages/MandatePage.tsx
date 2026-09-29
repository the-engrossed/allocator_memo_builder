import { useEffect, useState } from "react";
import { getMandate, putMandate } from "../api/client";
import { MandateForm, Timestamp, type SaveState } from "../components/MandateForm";
import {
  MANDATE_DEFAULTS,
  draftFromMandate,
  draftToPayload,
  draftsEqual,
  strategyOptions,
  toggleStrategyRole,
  type MandateDraft,
  type MandateFieldErrors,
  type TextDraftField,
} from "../lib/mandateForm";
import type { AnalysisResponse, MandateResponse } from "../types/api";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; saved: MandateResponse | null };

interface MandatePageProps {
  analysis: AnalysisResponse;
  onMandatePersisted: (mandate: MandateResponse) => void;
}

export function MandatePage({ analysis, onMandatePersisted }: MandatePageProps) {
  const analysisId = analysis.analysis_id;
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoad({ status: "loading" });
    getMandate(analysisId)
      .then((saved) => {
        if (!cancelled) {
          setLoad({ status: "ready", saved });
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setLoad({ status: "error", message: errorMessage(cause, "Could not load the mandate.") });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [analysisId, attempt]);

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-slate-800 bg-slate-900 p-4">
        <h2 className="text-sm font-semibold text-slate-100">Mandate</h2>
        <p className="mt-1 text-sm text-slate-400">
          Constraints for this analysis. Rates are saved as integer basis points; every save
          replaces the complete mandate.
        </p>
        <p className="mt-2 font-mono text-xs text-slate-500">
          {analysis.filename} · {analysisId}
        </p>
      </section>

      {load.status === "loading" && <p className="text-sm text-slate-400">Loading mandate…</p>}

      {load.status === "error" && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-red-500/40 bg-red-950/40 px-3 py-2 text-sm text-red-100">
          <span>{load.message}</span>
          <button
            type="button"
            onClick={() => setAttempt((value) => value + 1)}
            className="rounded-lg border border-red-400/60 px-3 py-1 text-sm font-medium hover:bg-red-950/60"
          >
            Retry
          </button>
        </div>
      )}

      {load.status === "ready" && (
        <MandateEditor
          analysisId={analysisId}
          initial={load.saved}
          universeStrategies={analysis.strategies}
          onMandatePersisted={onMandatePersisted}
        />
      )}
    </div>
  );
}

interface MandateEditorProps {
  analysisId: string;
  initial: MandateResponse | null;
  universeStrategies: string[];
  onMandatePersisted: (mandate: MandateResponse) => void;
}

function MandateEditor({
  analysisId,
  initial,
  universeStrategies,
  onMandatePersisted,
}: MandateEditorProps) {
  const [persisted, setPersisted] = useState<MandateResponse | null>(initial);
  const [draft, setDraft] = useState<MandateDraft>(() =>
    draftFromMandate(initial ?? MANDATE_DEFAULTS),
  );
  const [errors, setErrors] = useState<MandateFieldErrors>({});
  const [showErrors, setShowErrors] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>({ status: "idle" });

  useEffect(() => {
    if (initial) {
      onMandatePersisted(initial);
    }
  }, [initial, onMandatePersisted]);

  function updateDraft(next: MandateDraft) {
    setDraft(next);
    if (showErrors) {
      const result = draftToPayload(next);
      setErrors(result.ok ? {} : result.errors);
    }
    if (saveState.status !== "saving") {
      setSaveState({ status: "idle" });
    }
  }

  async function save() {
    const result = draftToPayload(draft);
    if (!result.ok) {
      setShowErrors(true);
      setErrors(result.errors);
      return;
    }
    setErrors({});
    setSaveState({ status: "saving" });
    try {
      const saved = await putMandate(analysisId, result.payload);
      setPersisted(saved);
      setDraft(draftFromMandate(saved));
      setSaveState({ status: "saved", updatedAt: saved.updated_at });
      onMandatePersisted(saved);
    } catch (cause) {
      setSaveState({ status: "error", message: errorMessage(cause, "Save failed.") });
    }
  }

  const baseline = draftFromMandate(persisted ?? MANDATE_DEFAULTS);
  const dirty = !draftsEqual(draft, baseline);
  const statusNote = persisted ? (
    dirty ? (
      <span className="text-amber-200">Unsaved changes.</span>
    ) : (
      <span>
        Last saved <Timestamp iso={persisted.updated_at} />.
      </span>
    )
  ) : (
    <span>No saved mandate yet. Showing default constraints; save to confirm them.</span>
  );

  return (
    <MandateForm
      draft={draft}
      errors={errors}
      strategyOptions={strategyOptions(
        [...(persisted?.preferred_strategies ?? []), ...(persisted?.excluded_strategies ?? [])],
        universeStrategies,
        [...draft.preferred_strategies, ...draft.excluded_strategies],
      )}
      universeStrategies={universeStrategies}
      saveState={saveState}
      statusNote={statusNote}
      onChange={(field: TextDraftField, value: string) => updateDraft({ ...draft, [field]: value })}
      onLiquidityChange={(value) => updateDraft({ ...draft, min_liquidity_frequency: value })}
      onToggleStrategy={(strategy, role) => updateDraft(toggleStrategyRole(draft, strategy, role))}
      onSubmit={() => void save()}
    />
  );
}

function errorMessage(cause: unknown, fallback: string): string {
  return cause instanceof Error && cause.message ? cause.message : fallback;
}

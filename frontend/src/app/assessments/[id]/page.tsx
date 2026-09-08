"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ErrorNote, Loading } from "@/components/AuthShell";
import { useLocale } from "@/i18n/LocaleProvider";
import type { MessageKey } from "@/i18n/messages";
import {
  ApiError,
  api,
  type Assessment,
  type Axis,
  type FrameworkVersion,
  type MaturityLevel,
  type Progress,
  type Question,
  type ResponseRow,
} from "@/lib/api";
import { useRequireSession } from "@/lib/session";

type Draft = {
  score: number | null;
  is_not_applicable: boolean;
  na_rationale: string;
  comment: string;
};

type SaveState = "idle" | "saving" | "saved" | "error";

const emptyDraft = (): Draft => ({
  score: null,
  is_not_applicable: false,
  na_rationale: "",
  comment: "",
});

export default function QuestionnairePage() {
  const { t, pick, locale } = useLocale();
  const { me, loading } = useRequireSession();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const assessmentId = params.id;

  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [framework, setFramework] = useState<FrameworkVersion | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [activeAxis, setActiveAxis] = useState<string | null>(null);
  const [unansweredOnly, setUnansweredOnly] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [error, setError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const pending = useRef<Map<string, Draft>>(new Map());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  /* ---------- load ---------- */

  useEffect(() => {
    if (!me) return;
    let cancelled = false;

    (async () => {
      try {
        const detail = await api<Assessment>(`/assessments/${assessmentId}`);
        if (cancelled) return;
        setAssessment(detail);

        if (["submitted", "under_review", "completed"].includes(detail.status)) {
          router.replace(`/assessments/${assessmentId}/results`);
          return;
        }

        const [version, responses, prog] = await Promise.all([
          api<FrameworkVersion>(`/frameworks/versions/${detail.framework_version_id}`),
          api<ResponseRow[]>(`/assessments/${assessmentId}/responses`),
          api<Progress>(`/assessments/${assessmentId}/progress`),
        ]);
        if (cancelled) return;

        const chosen = new Set(detail.selected_axis_ids ?? []);
        const axes = chosen.size ? version.axes.filter((a) => chosen.has(a.id)) : version.axes;
        setFramework({ ...version, axes });
        setActiveAxis(axes[0]?.id ?? null);
        setProgress(prog);

        const map: Record<string, Draft> = {};
        for (const row of responses) {
          map[row.question_id] = {
            score: row.score,
            is_not_applicable: row.is_not_applicable,
            na_rationale: row.na_rationale ?? "",
            comment: row.comment ?? "",
          };
        }
        setDrafts(map);
      } catch (err) {
        if (err instanceof ApiError) setError(err);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [me, assessmentId, router]);

  /* ---------- auto-save (BRD FR-10) ---------- */

  const flush = useCallback(async () => {
    if (pending.current.size === 0) return;
    const batch = Array.from(pending.current.entries())
      .map(([question_id, draft]) => ({
        question_id,
        score: draft.is_not_applicable ? null : draft.score,
        is_not_applicable: draft.is_not_applicable,
        na_rationale: draft.is_not_applicable ? draft.na_rationale : null,
        comment: draft.comment || null,
      }))
      // A "not applicable" answer without its rationale is not a valid answer
      // yet — hold it back rather than bounce off the API on every keystroke.
      .filter((item) => (item.is_not_applicable ? !!item.na_rationale?.trim() : item.score !== null));

    if (batch.length === 0) return;
    pending.current.clear();
    setSaveState("saving");
    try {
      await api(`/assessments/${assessmentId}/responses`, { method: "PUT", body: batch });
      setSaveState("saved");
      setError(null);
      setProgress(await api<Progress>(`/assessments/${assessmentId}/progress`));
    } catch (err) {
      setSaveState("error");
      if (err instanceof ApiError) setError(err);
    }
  }, [assessmentId]);

  const queue = useCallback(
    (questionId: string, draft: Draft) => {
      pending.current.set(questionId, draft);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => void flush(), 700);
    },
    [flush],
  );

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
      void flush();
    };
  }, [flush]);

  const update = useCallback(
    (questionId: string, patch: Partial<Draft>) => {
      setDrafts((prev) => {
        const next = { ...(prev[questionId] ?? emptyDraft()), ...patch };
        queue(questionId, next);
        return { ...prev, [questionId]: next };
      });
    },
    [queue],
  );

  /* ---------- submit ---------- */

  async function submit() {
    setSubmitting(true);
    setError(null);
    if (timer.current) clearTimeout(timer.current);
    await flush();
    try {
      await api(`/assessments/${assessmentId}/submit`, { method: "POST" });
      router.push(`/assessments/${assessmentId}/results`);
    } catch (err) {
      if (err instanceof ApiError) setError(err);
      setSubmitting(false);
    }
  }

  /* ---------- render ---------- */

  const levels = useMemo<MaturityLevel[]>(() => framework?.maturity_levels ?? [], [framework]);
  const axis: Axis | undefined = framework?.axes.find((a) => a.id === activeAxis);
  const axisProgress = progress?.axes.find((a) => a.axis_id === activeAxis);

  const visibleQuestions = useMemo(() => {
    if (!axis) return [];
    if (!unansweredOnly) return axis.questions;
    return axis.questions.filter((q) => {
      const draft = drafts[q.id];
      return !draft || (!draft.is_not_applicable && draft.score === null);
    });
  }, [axis, unansweredOnly, drafts]);

  if (loading || !me || !framework || !assessment) {
    return error ? (
      <div className="shell shell-narrow" style={{ paddingBlock: "var(--space-8)" }}>
        <ErrorNote text={error.localised(locale)} />
      </div>
    ) : (
      <Loading label={t("common.loading")} />
    );
  }

  const percent = Math.round((progress?.completion ?? 0) * 100);

  return (
    <div className="shell" style={{ paddingBottom: "var(--space-8)" }}>
      <div className="page-head">
        <div>
          <span className="eyebrow">
            {t(`assessment.status.${assessment.status}` as MessageKey)}
          </span>
          <h1>{assessment.name}</h1>
        </div>
        <div className="row row-tight" style={{ minWidth: 260 }}>
          <SaveBadge state={saveState} />
          <div className="meter">
            <span style={{ width: `${percent}%` }} />
          </div>
          <span className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
            {progress?.answered_questions ?? 0} {t("questionnaire.of")}{" "}
            {progress?.total_questions ?? 0}
          </span>
        </div>
      </div>

      <div className="split-rail" style={{ marginBlockStart: "var(--space-5)" }}>
        {/* axis rail */}
        <nav className="card rail">
          {framework.axes.map((item) => {
            const stat = progress?.axes.find((a) => a.axis_id === item.id);
            const pct = stat ? Math.round(stat.completion * 100) : 0;
            return (
              <button
                key={item.id}
                type="button"
                className="rail-item"
                data-on={item.id === activeAxis}
                onClick={() => setActiveAxis(item.id)}
              >
                <span className="rail-top">
                  {item.code}
                  <span className="push">{stat ? `${stat.answered_questions}/${stat.total_questions}` : ""}</span>
                </span>
                <span className="rail-name">{pick(item, "name")}</span>
                <span className="meter meter-thin" style={{ marginBlockStart: 6 }}>
                  <span style={{ width: `${pct}%` }} />
                </span>
              </button>
            );
          })}
        </nav>

        {/* questions */}
        <section className="stack stack-4">
          {axis && (
            <div className="card card-tight stack stack-3">
              <div className="row row-tight">
                <span className="mono" style={{ fontSize: "var(--text-xs)", color: "var(--brand-500)" }}>
                  {axis.code}
                </span>
                <h2 style={{ fontSize: "var(--text-lg)" }}>{pick(axis, "name")}</h2>
                <label className="check push">
                  <input
                    type="checkbox"
                    checked={unansweredOnly}
                    onChange={(e) => setUnansweredOnly(e.target.checked)}
                  />
                  {t("questionnaire.filterUnanswered")}
                </label>
              </div>
              {pick(axis, "description") && (
                <p className="muted" style={{ fontSize: "var(--text-sm)" }}>
                  {pick(axis, "description")}
                </p>
              )}
              {axisProgress && axisProgress.unanswered_mandatory > 0 && (
                <div>
                  <span className="chip chip-warn">
                    {axisProgress.unanswered_mandatory} {t("questionnaire.mandatoryRemaining")}
                  </span>
                </div>
              )}
            </div>
          )}

          {visibleQuestions.map((question, index) => (
            <QuestionCard
              key={question.id}
              index={index + 1}
              question={question}
              levels={levels}
              draft={drafts[question.id] ?? emptyDraft()}
              onChange={(patch) => update(question.id, patch)}
            />
          ))}

          {error && <ErrorNote text={error.localised(locale)} />}

          <div className="card card-pad row">
            <div>
              <div style={{ fontWeight: 500 }}>{t("questionnaire.submit")}</div>
              <div className="dim" style={{ fontSize: "var(--text-sm)" }}>
                {t("questionnaire.submitHint")}
              </div>
            </div>
            {progress && progress.unanswered_mandatory > 0 && (
              <span className="chip chip-warn">
                {progress.unanswered_mandatory} {t("questionnaire.mandatoryRemaining")}
              </span>
            )}
            <button
              type="button"
              className="btn btn-primary push"
              disabled={!progress?.can_submit || submitting}
              onClick={submit}
            >
              {submitting ? t("common.loading") : t("questionnaire.submit")}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}

/* ---------- pieces ---------- */

function SaveBadge({ state }: { state: SaveState }) {
  const { t } = useLocale();
  if (state === "idle") return null;
  const map = {
    saving: { cls: "chip", label: t("questionnaire.saving") },
    saved: { cls: "chip chip-ok", label: t("questionnaire.saved") },
    error: { cls: "chip chip-danger", label: t("questionnaire.saveFailed") },
  } as const;
  const item = map[state];
  return <span className={item.cls}>{item.label}</span>;
}

function QuestionCard({
  index,
  question,
  levels,
  draft,
  onChange,
}: {
  index: number;
  question: Question;
  levels: MaturityLevel[];
  draft: Draft;
  onChange: (patch: Partial<Draft>) => void;
}) {
  const { t, pick } = useLocale();
  const disabled = draft.is_not_applicable;
  const answered = draft.is_not_applicable || draft.score !== null;

  return (
    <article className="q-card" data-answered={answered}>
      <div className="row" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
        <span className="q-num">{String(index).padStart(2, "0")}</span>
        <div className="stack stack-3" style={{ flex: 1, minWidth: 0 }}>
          <p className="q-text">{pick(question, "text")}</p>
          <div className="row row-tight">
            <span className={question.is_mandatory ? "chip chip-brand" : "chip"}>
              {question.is_mandatory ? t("questionnaire.mandatory") : t("questionnaire.optional")}
            </span>
            <span className="chip mono">
              {t("questionnaire.weight")} {question.weight}
            </span>
            {question.evidence_required && pick(question, "evidence_hint") && (
              <span className="chip">
                <DocIcon />
                {pick(question, "evidence_hint")}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* the 1-5 scale, labelled from the framework's own level names and
          coloured with the same ramp used everywhere else in the product */}
      <div className="scale">
        {levels.map((level) => (
          <button
            key={level.score}
            type="button"
            className="scale-btn"
            data-level={level.score}
            disabled={disabled}
            aria-pressed={draft.score === level.score}
            onClick={() =>
              onChange({
                score: draft.score === level.score ? null : level.score,
                is_not_applicable: false,
              })
            }
            title={pick(level, "description")}
          >
            <span className="n">{level.score}</span>
            <span className="lbl">{pick(level, "label")}</span>
          </button>
        ))}
      </div>

      <div className="stack stack-3">
        {question.allow_not_applicable && (
          <label className="check">
            <input
              type="checkbox"
              checked={draft.is_not_applicable}
              onChange={(e) =>
                onChange({
                  is_not_applicable: e.target.checked,
                  score: e.target.checked ? null : draft.score,
                })
              }
            />
            {t("questionnaire.notApplicable")}
          </label>
        )}

        {draft.is_not_applicable && (
          <div className="field">
            <label htmlFor={`na-${question.id}`}>{t("questionnaire.naRationale")}</label>
            <textarea
              id={`na-${question.id}`}
              rows={2}
              required
              value={draft.na_rationale}
              onChange={(e) => onChange({ na_rationale: e.target.value })}
            />
          </div>
        )}

        <div className="field">
          <label htmlFor={`comment-${question.id}`}>{t("questionnaire.comment")}</label>
          <textarea
            id={`comment-${question.id}`}
            rows={2}
            value={draft.comment}
            onChange={(e) => onChange({ comment: e.target.value })}
          />
        </div>
      </div>
    </article>
  );
}

function DocIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 3.5h8L18.5 8v12.5H6z" />
      <path d="M13.5 3.5V8h5" />
    </svg>
  );
}

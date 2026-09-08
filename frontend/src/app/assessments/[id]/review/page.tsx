"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ErrorNote, Loading } from "@/components/AuthShell";
import { useLocale } from "@/i18n/LocaleProvider";
import type { MessageKey } from "@/i18n/messages";
import {
  ApiError,
  api,
  type Comparison,
  type OverdueRow,
  type ReviewView,
  type UserProgress,
} from "@/lib/api";
import { useRequireSession } from "@/lib/session";

export default function ReviewPage() {
  const { t, locale, num } = useLocale();
  const { me, loading } = useRequireSession();
  const params = useParams<{ id: string }>();

  const [view, setView] = useState<ReviewView | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    if (!me) return;
    api<ReviewView>(`/assessments/${params.id}/review`)
      .then(setView)
      .catch((err) => err instanceof ApiError && setError(err));
  }, [me, params.id]);

  if (loading || !me) return <Loading label={t("common.loading")} />;

  if (error) {
    return (
      <div className="shell shell-narrow stack stack-4" style={{ paddingBlock: "var(--space-8)" }}>
        <ErrorNote text={error.localised(locale)} />
        <Link href="/dashboard" className="btn btn-secondary" style={{ alignSelf: "flex-start" }}>
          {t("nav.dashboard")}
        </Link>
      </div>
    );
  }

  if (!view) return <Loading label={t("common.loading")} />;

  const { progress, score_deltas: deltas, clarifications } = view;
  const byUser = (view as ReviewView & { by_user?: UserProgress[] }).by_user ?? [];
  const overdue = (view as ReviewView & { overdue?: OverdueRow[] }).overdue ?? [];
  const comparison = (view as ReviewView & { comparison?: Comparison | null }).comparison;

  return (
    <div className="shell" style={{ paddingBottom: "var(--space-8)" }}>
      <div className="page-head">
        <div>
          <span className="eyebrow">{view.assessment.name}</span>
          <h1>{t("review.title")}</h1>
        </div>
        <div className="row row-tight">
          <span className="chip">
            {t(`assessment.status.${view.assessment.status}` as MessageKey)}
          </span>
          <Link href={`/assessments/${params.id}/insights`} className="btn btn-secondary btn-sm">
            {t("ai.title")}
          </Link>
          <Link href={`/assessments/${params.id}/results`} className="btn btn-secondary btn-sm">
            {t("results.title")}
          </Link>
        </div>
      </div>

      <section className="grid grid-auto-sm" style={{ marginBlockStart: "var(--space-5)" }}>
        <Stat
          label={t("assessment.completion")}
          value={`${Math.round(progress.completion * 100)}%`}
        />
        <Stat
          label={t("questionnaire.answered")}
          value={`${progress.answered_questions} / ${progress.total_questions}`}
        />
        <Stat label={t("review.deltas")} value={num(deltas.length, 0)} />
        <Stat label={t("assign.overdue")} value={num(overdue.length, 0)} />
      </section>

      {/* per-axis progress — FR-12 */}
      <section style={{ marginBlockStart: "var(--space-6)" }}>
        <div className="section-head">
          <h2>{t("results.byAxis")}</h2>
        </div>
        <div className="card">
          {progress.axes.map((axis) => (
            <div className="axis-row" key={axis.axis_id}>
              <span className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                {axis.code}
              </span>
              <span className="axis-name">{locale === "ar" ? axis.name_ar : axis.name_en}</span>
              <span className="axis-track">
                <span
                  style={{
                    width: `${Math.round(axis.completion * 100)}%`,
                    background: "var(--brand-500)",
                  }}
                />
              </span>
              <span className="axis-score">
                {axis.answered_questions}/{axis.total_questions}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* FR-12 — completion by user */}
      {byUser.length > 0 && (
        <section style={{ marginBlockStart: "var(--space-6)" }}>
          <div className="section-head">
            <h2>{t("assign.byUser")}</h2>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("assign.to")}</th>
                  <th className="num" style={{ width: 110 }}>{t("assign.assigned")}</th>
                  <th className="num" style={{ width: 110 }}>{t("questionnaire.answered")}</th>
                  <th className="num" style={{ width: 110 }}>{t("assign.overdue")}</th>
                  <th style={{ width: 160 }}>{t("assessment.completion")}</th>
                </tr>
              </thead>
              <tbody>
                {byUser.map((row) => (
                  <tr key={row.user_id ?? "unassigned"}>
                    <td>
                      {row.full_name ?? (
                        <span className="dim">{t("assign.unassigned")}</span>
                      )}
                      {row.email && (
                        <span
                          className="mono dim"
                          dir="ltr"
                          style={{ display: "block", fontSize: "var(--text-xs)" }}
                        >
                          {row.email}
                        </span>
                      )}
                    </td>
                    <td className="mono" style={{ textAlign: "end" }}>{row.assigned}</td>
                    <td className="mono" style={{ textAlign: "end" }}>{row.answered}</td>
                    <td style={{ textAlign: "end" }}>
                      {row.overdue > 0 ? (
                        <span className="chip chip-danger mono">{row.overdue}</span>
                      ) : (
                        <span className="mono dim">0</span>
                      )}
                    </td>
                    <td>
                      <div className="row row-tight">
                        <div className="meter">
                          <span style={{ width: `${Math.round(row.completion * 100)}%` }} />
                        </div>
                        <span className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                          {Math.round(row.completion * 100)}%
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* FR-12 — overdue items */}
      <section style={{ marginBlockStart: "var(--space-6)" }}>
        <div className="section-head">
          <h2>{t("assign.overdue")}</h2>
        </div>
        {overdue.length === 0 ? (
          <div className="card card-pad dim">{t("assign.noOverdue")}</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("results.axis")}</th>
                  <th>{t("assign.to")}</th>
                  <th style={{ width: 130 }}>{t("assign.due")}</th>
                  <th className="num" style={{ width: 120 }}>{t("assign.daysLate")}</th>
                </tr>
              </thead>
              <tbody>
                {overdue.slice(0, 30).map((row) => (
                  <tr key={row.question_id}>
                    <td>
                      <span className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                        {row.axis_code} · {row.question_code}
                      </span>
                      {row.is_mandatory && (
                        <span className="chip chip-brand push">
                          {t("questionnaire.mandatory")}
                        </span>
                      )}
                    </td>
                    <td>{row.assigned_to ?? <span className="dim">{t("assign.unassigned")}</span>}</td>
                    <td className="mono" style={{ fontSize: "var(--text-xs)" }}>
                      {row.due_at?.slice(0, 10) ?? "—"}
                    </td>
                    <td style={{ textAlign: "end" }}>
                      <span className="chip chip-danger mono">{row.days_overdue ?? 0}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* comparison to the prior assessment */}
      {comparison && (
        <section style={{ marginBlockStart: "var(--space-6)" }}>
          <div className="section-head">
            <h2>{t("compare.title")}</h2>
            <span className="chip mono">
              {num(comparison.previous_overall)} → {num(comparison.current_overall)}
            </span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("results.axis")}</th>
                  <th className="num" style={{ width: 110 }}>{t("compare.previous")}</th>
                  <th className="num" style={{ width: 110 }}>{t("compare.current")}</th>
                  <th className="num" style={{ width: 110 }}>{t("compare.change")}</th>
                </tr>
              </thead>
              <tbody>
                {comparison.axes.map((row) => (
                  <tr key={row.axis_id}>
                    <td className="mono">{row.code}</td>
                    <td className="mono" style={{ textAlign: "end" }}>{num(row.previous)}</td>
                    <td className="mono" style={{ textAlign: "end" }}>{num(row.current)}</td>
                    <td style={{ textAlign: "end" }}>
                      <span
                        className={`chip mono ${row.delta > 0 ? "chip-ok" : row.delta < 0 ? "chip-danger" : ""}`}
                      >
                        {row.delta > 0 ? "+" : ""}
                        {num(row.delta)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* FR-24 — material differences */}
      <section style={{ marginBlockStart: "var(--space-6)" }}>
        <div className="section-head">
          <h2>{t("review.deltas")}</h2>
        </div>
        {deltas.length === 0 ? (
          <div className="card card-pad dim">{t("review.noDeltas")}</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("results.axis")}</th>
                  <th style={{ width: 110 }}>{t("review.customerScore")}</th>
                  <th style={{ width: 110 }}>{t("review.reviewerScore")}</th>
                  <th style={{ width: 90 }}>{t("review.delta")}</th>
                  <th>{t("review.reason")}</th>
                </tr>
              </thead>
              <tbody>
                {deltas.map((row) => (
                  <tr key={row.question_id}>
                    <td>
                      <span className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                        {row.axis_code} · {row.question_code}
                      </span>
                    </td>
                    <td className="mono">{row.customer_score}</td>
                    <td className="mono">{row.reviewer_score}</td>
                    <td>
                      <span className={`chip mono ${row.is_material ? "chip-danger" : "chip-warn"}`}>
                        {row.delta > 0 ? `+${row.delta}` : row.delta}
                      </span>
                    </td>
                    <td>{row.reason ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* items needing clarification */}
      <section style={{ marginBlockStart: "var(--space-6)" }}>
        <div className="section-head">
          <h2>{t("review.clarifications")}</h2>
        </div>
        {clarifications.length === 0 ? (
          <div className="card card-pad dim">{t("review.noClarifications")}</div>
        ) : (
          <div className="stack stack-2">
            {clarifications.map((item) => (
              <div key={`${item.question_id}-${item.document_id}`} className="card card-tight row row-tight">
                <span className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                  {item.question_code}
                </span>
                <span style={{ fontSize: "var(--text-sm)" }}>{item.filename}</span>
                <span
                  className={`chip ${item.status === "rejected" ? "chip-danger" : "chip-warn"} push`}
                >
                  {t(`evidence.status.${item.status}` as MessageKey)}
                </span>
                {item.reviewer_note && (
                  <span className="muted" style={{ fontSize: "var(--text-xs)", flexBasis: "100%" }}>
                    {item.reviewer_note}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ErrorNote, Loading } from "@/components/AuthShell";
import { DocumentPreview } from "@/components/DocumentPreview";
import { useLocale } from "@/i18n/LocaleProvider";
import type { MessageKey } from "@/i18n/messages";
import {
  ApiError,
  api,
  downloadFile,
  uploadFile,
  type Assessment,
  type Axis,
  type DocumentRow,
  type EvidenceLink,
  type FrameworkVersion,
} from "@/lib/api";
import { useRequireSession } from "@/lib/session";

export default function EvidencePage() {
  const { t, pick, locale } = useLocale();
  const { me, loading } = useRequireSession();
  const params = useParams<{ id: string }>();
  const assessmentId = params.id;

  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [axes, setAxes] = useState<Axis[]>([]);
  const [documents, setDocuments] = useState<DocumentRow[]>([]);
  const [links, setLinks] = useState<EvidenceLink[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [linkFor, setLinkFor] = useState<DocumentRow | null>(null);
  const [previewing, setPreviewing] = useState<DocumentRow | null>(null);
  const [replacing, setReplacing] = useState<string | null>(null);
  const [category, setCategory] = useState<string>("");
  const [categories, setCategories] = useState<string[]>([]);
  const [filter, setFilter] = useState<string>("");
  const fileInput = useRef<HTMLInputElement>(null);
  const replaceInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    const [docs, evidence, cats] = await Promise.all([
      api<DocumentRow[]>(`/documents${filter ? `?category=${encodeURIComponent(filter)}` : ""}`),
      api<EvidenceLink[]>(`/assessments/${assessmentId}/evidence`),
      api<string[]>("/documents/categories").catch(() => [] as string[]),
    ]);
    setDocuments(docs);
    setLinks(evidence);
    setCategories(cats);
  }, [assessmentId, filter]);

  useEffect(() => {
    if (!me) return;
    (async () => {
      try {
        const detail = await api<Assessment>(`/assessments/${assessmentId}`);
        setAssessment(detail);
        const version = await api<FrameworkVersion>(
          `/frameworks/versions/${detail.framework_version_id}`,
        );
        const chosen = new Set(detail.selected_axis_ids ?? []);
        setAxes(chosen.size ? version.axes.filter((a) => chosen.has(a.id)) : version.axes);
        await refresh();
      } catch (err) {
        if (err instanceof ApiError) setError(err);
      }
    })();
  }, [me, assessmentId, refresh]);

  const linksByDocument = useMemo(() => {
    const map = new Map<string, EvidenceLink[]>();
    for (const link of links) {
      const list = map.get(link.document_id) ?? [];
      list.push(link);
      map.set(link.document_id, list);
    }
    return map;
  }, [links]);

  const questionsById = useMemo(() => {
    const map = new Map<string, { code: string; axisCode: string }>();
    for (const axis of axes) {
      for (const question of axis.questions) {
        map.set(question.id, { code: question.code, axisCode: axis.code });
      }
    }
    return map;
  }, [axes]);

  async function handleFiles(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of Array.from(files)) {
        await uploadFile<DocumentRow>("/documents", file, category ? { category } : {});
      }
      await refresh();
    } catch (err) {
      if (err instanceof ApiError) setError(err);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  /** FR-19 — an explicit replacement carries the old document's links across. */
  async function handleReplace(files: FileList | null) {
    if (!files?.length || !replacing) return;
    setUploading(true);
    setError(null);
    try {
      await uploadFile<DocumentRow>("/documents", files[0], { supersedes_id: replacing });
      await refresh();
    } catch (err) {
      if (err instanceof ApiError) setError(err);
    } finally {
      setUploading(false);
      setReplacing(null);
      if (replaceInput.current) replaceInput.current.value = "";
    }
  }

  async function unlink(linkId: string) {
    try {
      await api(`/evidence/${linkId}`, { method: "DELETE" });
      await refresh();
    } catch (err) {
      if (err instanceof ApiError) setError(err);
    }
  }

  async function removeDocument(documentId: string) {
    try {
      await api(`/documents/${documentId}`, { method: "DELETE" });
      await refresh();
    } catch (err) {
      if (err instanceof ApiError) setError(err);
    }
  }

  if (loading || !me || !assessment) return <Loading label={t("common.loading")} />;

  return (
    <div className="shell" style={{ paddingBottom: "var(--space-8)" }}>
      <div className="page-head">
        <div>
          <span className="eyebrow">{assessment.name}</span>
          <h1>{t("evidence.title")}</h1>
        </div>
        <Link href={`/assessments/${assessmentId}`} className="btn btn-secondary btn-sm">
          {t("common.back")}
        </Link>
      </div>

      <p className="muted" style={{ marginBlock: "var(--space-4)", fontSize: "var(--text-sm)" }}>
        {t("evidence.body")}
      </p>

      <div className="row row-tight" style={{ marginBlockEnd: "var(--space-4)" }}>
        <div className="field" style={{ width: 220 }}>
          <label htmlFor="upload-category">{t("preview.category")}</label>
          <input
            id="upload-category"
            list="doc-categories"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          />
          <datalist id="doc-categories">
            {categories.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </div>
        <div className="field" style={{ width: 220 }}>
          <label htmlFor="filter-category">{t("preview.allCategories")}</label>
          <select
            id="filter-category"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="">{t("preview.allCategories")}</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* drop zone */}
      <div
        className="dropzone"
        data-dragging={dragging}
        onClick={() => fileInput.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void handleFiles(e.dataTransfer.files);
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") fileInput.current?.click();
        }}
      >
        <UploadIcon />
        <span style={{ fontWeight: 500 }}>
          {uploading ? t("evidence.uploading") : t("evidence.drop")}
        </span>
        <span className="dim" style={{ fontSize: "var(--text-xs)" }}>
          {t("evidence.formats")}
        </span>
        <input
          ref={fileInput}
          type="file"
          multiple
          hidden
          accept=".pdf,.docx,.xlsx,.pptx,.png,.jpg,.jpeg"
          onChange={(e) => void handleFiles(e.target.files)}
        />
      </div>

      {error && (
        <div style={{ marginBlockStart: "var(--space-4)" }}>
          <ErrorNote text={error.localised(locale)} />
        </div>
      )}

      <div className="section-head" style={{ marginBlockStart: "var(--space-6)" }}>
        <h2>{t("evidence.myDocuments")}</h2>
        <span className="chip mono">{documents.length}</span>
      </div>

      {documents.length === 0 ? (
        <div className="card card-pad dim">{t("evidence.noDocuments")}</div>
      ) : (
        <div className="stack stack-3">
          {documents.map((document) => {
            const documentLinks = linksByDocument.get(document.id) ?? [];
            return (
              <article key={document.id} className="card card-tight stack stack-3">
                <div className="row row-tight">
                  <FileIcon />
                  <span style={{ fontWeight: 500 }}>{document.filename}</span>
                  {document.version > 1 && (
                    <span className="chip mono">
                      {t("evidence.version")} {document.version}
                    </span>
                  )}
                  <span className="chip mono dim">{formatSize(document.size_bytes)}</span>
                  {document.category && <span className="chip">{document.category}</span>}
                  <div className="row row-tight push">
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => setLinkFor(document)}
                    >
                      {t("evidence.linkTo")}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => setPreviewing(document)}
                    >
                      {t("preview.open")}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => {
                        setReplacing(document.id);
                        replaceInput.current?.click();
                      }}
                    >
                      {t("preview.replace")}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() =>
                        void downloadFile(
                          `/documents/${document.id}/download`,
                          document.filename,
                        )
                      }
                    >
                      {t("evidence.download")}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => void removeDocument(document.id)}
                    >
                      {t("evidence.delete")}
                    </button>
                  </div>
                </div>

                {documentLinks.length > 0 && (
                  <div className="row row-tight">
                    <span className="dim" style={{ fontSize: "var(--text-xs)" }}>
                      {t("evidence.linked")} {documentLinks.length} {t("evidence.questions")}
                    </span>
                    {documentLinks.map((link) => {
                      const question = questionsById.get(link.question_id);
                      return (
                        <span key={link.id} className={`chip ${statusTone(link.status)}`}>
                          <span className="mono">{question?.code ?? "—"}</span>
                          <span>·</span>
                          {t(`evidence.status.${link.status}` as MessageKey)}
                          <button
                            type="button"
                            className="chip-x"
                            aria-label={t("evidence.unlink")}
                            onClick={() => void unlink(link.id)}
                          >
                            ×
                          </button>
                        </span>
                      );
                    })}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}

      <input
        ref={replaceInput}
        type="file"
        hidden
        accept=".pdf,.docx,.xlsx,.pptx,.png,.jpg,.jpeg"
        onChange={(e) => void handleReplace(e.target.files)}
      />

      {previewing && (
        <DocumentPreview document={previewing} onClose={() => setPreviewing(null)} />
      )}

      {linkFor && (
        <LinkDialog
          document={linkFor}
          axes={axes}
          existing={new Set((linksByDocument.get(linkFor.id) ?? []).map((l) => l.question_id))}
          onClose={() => setLinkFor(null)}
          onDone={async () => {
            setLinkFor(null);
            await refresh();
          }}
          assessmentId={assessmentId}
          onError={setError}
        />
      )}

      <style>{`
        .dropzone {
          display:flex; flex-direction:column; align-items:center; justify-content:center;
          gap:var(--space-2); padding:var(--space-7) var(--space-4);
          border:2px dashed var(--line-2); border-radius:var(--radius-lg);
          background:var(--surface); cursor:pointer;
          transition:border-color .15s var(--ease), background-color .15s var(--ease);
        }
        .dropzone:hover, .dropzone[data-dragging="true"] {
          border-color:var(--brand-400); background:var(--brand-50);
        }
        .chip-x {
          border:0; background:transparent; color:inherit; cursor:pointer;
          font-size:1rem; line-height:1; padding:0 0 0 2px; opacity:.6;
        }
        .chip-x:hover { opacity:1; }
        .modal-backdrop {
          position:fixed; inset:0; background:var(--overlay); z-index:60;
          display:grid; place-items:center; padding:var(--space-4);
        }
        .modal {
          background:var(--surface); border:1px solid var(--line);
          border-radius:var(--radius-lg); box-shadow:var(--shadow-lg);
          width:min(680px,100%); max-height:82vh; display:flex; flex-direction:column;
        }
        .modal-body { overflow-y:auto; padding:var(--space-4); }
        .modal-head, .modal-foot {
          padding:var(--space-4); display:flex; align-items:center; gap:var(--space-3);
        }
        .modal-head { border-block-end:1px solid var(--line); }
        .modal-foot { border-block-start:1px solid var(--line); }
      `}</style>
    </div>
  );
}

function LinkDialog({
  document: doc,
  axes,
  existing,
  assessmentId,
  onClose,
  onDone,
  onError,
}: {
  document: DocumentRow;
  axes: Axis[];
  existing: Set<string>;
  assessmentId: string;
  onClose: () => void;
  onDone: () => Promise<void>;
  onError: (error: ApiError) => void;
}) {
  const { t, pick } = useLocale();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  async function confirm() {
    if (selected.size === 0) return onClose();
    setBusy(true);
    try {
      await api(`/assessments/${assessmentId}/evidence`, {
        method: "POST",
        body: { document_id: doc.id, question_ids: Array.from(selected) },
      });
      await onDone();
    } catch (err) {
      if (err instanceof ApiError) onError(err);
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={t("evidence.selectQuestions")}
      >
        <div className="modal-head">
          <h3 style={{ fontSize: "var(--text-lg)" }}>{t("evidence.selectQuestions")}</h3>
          <span className="chip mono push">{selected.size}</span>
        </div>

        <div className="modal-body stack stack-4">
          {axes.map((axis) => (
            <div key={axis.id} className="stack stack-2">
              <div className="row row-tight">
                <span className="mono" style={{ fontSize: "var(--text-xs)", color: "var(--brand-500)" }}>
                  {axis.code}
                </span>
                <strong style={{ fontSize: "var(--text-sm)" }}>{pick(axis, "name")}</strong>
              </div>
              {axis.questions.map((question) => {
                const already = existing.has(question.id);
                const on = selected.has(question.id);
                return (
                  <label
                    key={question.id}
                    className="option-tile"
                    data-on={on || already}
                    style={{ opacity: already ? 0.55 : 1, alignItems: "flex-start" }}
                  >
                    <input
                      type="checkbox"
                      checked={on || already}
                      disabled={already}
                      onChange={() =>
                        setSelected((prev) => {
                          const next = new Set(prev);
                          if (next.has(question.id)) next.delete(question.id);
                          else next.add(question.id);
                          return next;
                        })
                      }
                    />
                    <span className="mono dim" style={{ fontSize: "var(--text-xs)", flex: "none" }}>
                      {question.code}
                    </span>
                    <span style={{ fontSize: "var(--text-sm)" }}>
                      {pick(question, "text")}
                      {pick(question, "evidence_hint") && (
                        <span className="dim" style={{ display: "block", fontSize: "var(--text-xs)" }}>
                          {t("evidence.expected")}: {pick(question, "evidence_hint")}
                        </span>
                      )}
                    </span>
                  </label>
                );
              })}
            </div>
          ))}
        </div>

        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary push"
            onClick={confirm}
            disabled={busy || selected.size === 0}
          >
            {busy ? t("common.loading") : t("evidence.confirmLink")}
          </button>
        </div>
      </div>
    </div>
  );
}

function statusTone(status: string): string {
  if (status === "validated" || status === "ai_reviewed") return "chip-ok";
  if (status === "requires_clarification") return "chip-warn";
  if (status === "rejected") return "chip-danger";
  return "";
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function UploadIcon() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="var(--brand-500)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 16V4M12 4l-4 4M12 4l4 4" />
      <path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--ink-3)" strokeWidth="1.6" strokeLinejoin="round" style={{ flex: "none" }} aria-hidden="true">
      <path d="M6 3.5h8L18.5 8v12.5H6z" />
      <path d="M13.5 3.5V8h5" />
    </svg>
  );
}

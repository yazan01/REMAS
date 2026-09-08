"use client";

import { useEffect, useState } from "react";

import { useLocale } from "@/i18n/LocaleProvider";
import { ApiError, previewUrl, type DocumentHistoryRow, type DocumentRow } from "@/lib/api";
import { api } from "@/lib/api";

const PREVIEWABLE = new Set(["application/pdf", "image/png", "image/jpeg"]);

/**
 * In-browser preview (FR-16) plus the version history behind the document
 * (FR-19). The bytes are fetched with the bearer token and handed to the
 * viewer as an object URL — a plain <img src> or <iframe src> cannot carry the
 * Authorization header, and evidence must not be readable without one.
 */
export function DocumentPreview({
  document: doc,
  onClose,
}: {
  document: DocumentRow;
  onClose: () => void;
}) {
  const { t, locale } = useLocale();
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<DocumentHistoryRow[]>([]);

  const canPreview = PREVIEWABLE.has(doc.content_type);

  useEffect(() => {
    let objectUrl: string | null = null;
    if (canPreview) {
      previewUrl(`/documents/${doc.id}/preview`)
        .then(({ url: created }) => {
          objectUrl = created;
          setUrl(created);
        })
        .catch((err) => setError(err instanceof ApiError ? err.localised(locale) : String(err)));
    }
    api<DocumentHistoryRow[]>(`/documents/${doc.id}/history`)
      .then(setHistory)
      .catch(() => setHistory([]));

    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [doc.id, canPreview, locale]);

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={t("preview.title")}
        style={{ width: "min(900px, 100%)" }}
      >
        <div className="modal-head">
          <h3 style={{ fontSize: "var(--text-lg)" }}>{doc.filename}</h3>
          <span className="chip mono">
            {t("evidence.version")} {doc.version}
          </span>
          <button type="button" className="btn btn-ghost btn-sm push" onClick={onClose}>
            {t("common.close")}
          </button>
        </div>

        <div className="modal-body stack stack-4">
          {!canPreview && <div className="note note-warn">{t("preview.unavailable")}</div>}
          {error && <div className="note note-error">{error}</div>}

          {canPreview && url && doc.content_type === "application/pdf" && (
            <iframe className="preview-frame" src={url} title={doc.filename} />
          )}
          {canPreview && url && doc.content_type !== "application/pdf" && (
            <img className="preview-image" src={url} alt={doc.filename} />
          )}

          {history.length > 1 && (
            <div className="stack stack-2">
              <h4 style={{ fontSize: "var(--text-base)" }}>{t("preview.history")}</h4>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: 90 }}>{t("evidence.version")}</th>
                      <th>{t("auth.email").replace(/.*/, doc.filename ? "" : "")}</th>
                      <th style={{ width: 150 }}>{t("admin.when")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((row) => (
                      <tr key={row.id}>
                        <td className="mono">{row.version}</td>
                        <td>
                          {row.filename}
                          {row.superseded && (
                            <span className="chip push">{t("preview.replace")}</span>
                          )}
                        </td>
                        <td className="mono" style={{ fontSize: "var(--text-xs)" }}>
                          {row.created_at.slice(0, 10)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

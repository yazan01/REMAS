"use client";

import { useCallback, useEffect, useState } from "react";

import { useLocale } from "@/i18n/LocaleProvider";
import type { MessageKey } from "@/i18n/messages";
import { ApiError, api, type AISettings as AISettingsState, type AITestResult } from "@/lib/api";

/**
 * FR-31 — the AI provider is configuration, not a code change.
 *
 * One screen decides what runs for every AI stage in the BRD: AI-01 document
 * extraction, AI-02 evidence relevance, AI-03 traceable explanations, AI-04
 * narratives, AI-05 initiatives and AI-06 the roadmap. The API key is sealed
 * before it reaches the database and only ever comes back as a four-character
 * hint, so this form can never redisplay it.
 */
export function AISettings({
  onError,
  canWrite,
}: {
  onError: (e: ApiError) => void;
  canWrite: boolean;
}) {
  const { t } = useLocale();
  const [state, setState] = useState<AISettingsState | null>(null);
  const [form, setForm] = useState({
    provider: "rules",
    model: "",
    base_url: "",
    ocr_provider: "auto",
    ocr_model: "",
    enabled: true,
    api_key: "",
  });
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [test, setTest] = useState<AITestResult | null>(null);
  const [saved, setSaved] = useState(false);

  const apply = useCallback((next: AISettingsState) => {
    setState(next);
    setForm({
      provider: next.provider,
      model: next.model ?? "",
      base_url: next.base_url ?? "",
      ocr_provider: next.ocr_provider,
      ocr_model: next.ocr_model ?? "",
      enabled: next.enabled,
      api_key: "",
    });
  }, []);

  const load = useCallback(async () => {
    apply(await api<AISettingsState>("/admin/settings/ai"));
  }, [apply]);

  useEffect(() => {
    load().catch((e) => e instanceof ApiError && onError(e));
  }, [load, onError]);

  async function save(overrides: Record<string, unknown> = {}) {
    setBusy(true);
    setTest(null);
    try {
      const body: Record<string, unknown> = {
        provider: form.provider,
        model: form.model,
        base_url: form.base_url,
        ocr_provider: form.ocr_provider,
        ocr_model: form.ocr_model,
        enabled: form.enabled,
        ...overrides,
      };
      // An untouched key field means "keep what is stored", not "clear it".
      if (!("api_key" in overrides) && form.api_key.trim()) body.api_key = form.api_key.trim();
      apply(await api<AISettingsState>("/admin/settings/ai", { method: "PUT", body }));
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      if (e instanceof ApiError) onError(e);
    } finally {
      setBusy(false);
    }
  }

  async function runTest() {
    setTesting(true);
    setTest(null);
    try {
      setTest(await api<AITestResult>("/admin/settings/ai/test", { method: "POST" }));
    } catch (e) {
      if (e instanceof ApiError) onError(e);
    } finally {
      setTesting(false);
    }
  }

  if (!state) return <div className="card card-pad dim">{t("common.loading")}</div>;

  const external = form.provider !== "rules";
  const keyHint =
    form.provider === "anthropic" ? state.anthropic_key_hint : state.openai_key_hint;
  const keyFromEnv =
    form.provider === "anthropic" ? state.anthropic_key_from_env : state.openai_key_from_env;
  const degraded = state.provider !== "rules" && state.effective_provider === "rules";

  return (
    <div className="stack stack-4">
      <p className="muted" style={{ fontSize: "var(--text-sm)", maxWidth: "72ch" }}>
        {t("aiset.intro")}
      </p>

      {!state.secrets_encrypted && <div className="note note-warn">{t("aiset.notEncrypted")}</div>}
      {degraded && <div className="note note-warn">{t("aiset.degraded")}</div>}
      {!canWrite && <div className="note note-warn">{t("users.adminOnly")}</div>}

      {/* ── analysis provider ───────────────────────────────────────────── */}
      <section className="card card-pad stack stack-4">
        <div className="row row-tight">
          <span className="eyebrow">{t("aiset.provider")}</span>
          <span className={`chip push ${degraded ? "chip-warn" : "chip-ok"}`}>
            {t("aiset.effective")}: {state.effective_provider}
          </span>
          {saved && <span className="chip chip-ok">{t("common.save")}</span>}
        </div>

        <div className="grid grid-auto-md">
          <div className="field">
            <label htmlFor="ai-provider">{t("aiset.provider")}</label>
            <select
              id="ai-provider"
              value={form.provider}
              disabled={!canWrite}
              onChange={(e) => {
                const provider = e.target.value;
                setForm({
                  ...form,
                  provider,
                  // Carrying the previous provider's model id across would send
                  // OpenAI a Claude model name.
                  model: state.default_models[provider] ?? "",
                });
              }}
            >
              {state.providers.map((p) => (
                <option key={p} value={p}>
                  {t(`aiset.provider${p.charAt(0).toUpperCase()}${p.slice(1)}` as MessageKey)}
                </option>
              ))}
            </select>
          </div>

          {external && (
            <div className="field">
              <label htmlFor="ai-model">{t("aiset.model")}</label>
              <input
                id="ai-model"
                dir="ltr"
                value={form.model}
                disabled={!canWrite}
                placeholder={state.default_models[form.provider] ?? ""}
                onChange={(e) => setForm({ ...form, model: e.target.value })}
              />
            </div>
          )}
        </div>

        {external && (
          <>
            <div className="field">
              <label htmlFor="ai-key">{t("aiset.apiKey")}</label>
              <input
                id="ai-key"
                type="password"
                dir="ltr"
                autoComplete="off"
                placeholder={t("aiset.apiKeyPlaceholder")}
                value={form.api_key}
                disabled={!canWrite || !state.secrets_encrypted}
                onChange={(e) => setForm({ ...form, api_key: e.target.value })}
              />
              <span className="hint">{t("aiset.apiKeyKeep")}</span>
              <div className="row row-tight" style={{ marginBlockStart: "var(--space-2)" }}>
                {keyHint ? (
                  <span className="chip chip-ok mono">
                    {t("aiset.apiKeyStored")} {keyHint}
                  </span>
                ) : keyFromEnv ? (
                  <span className="chip chip-brand">{t("aiset.apiKeyFromEnv")}</span>
                ) : (
                  <span className="chip chip-warn">{t("aiset.apiKeyNone")}</span>
                )}
                {keyHint && canWrite && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    disabled={busy}
                    onClick={() => void save({ api_key: "" })}
                  >
                    {t("aiset.apiKeyClear")}
                  </button>
                )}
              </div>
            </div>

            <div className="field">
              <label htmlFor="ai-base">{t("aiset.baseUrl")}</label>
              <input
                id="ai-base"
                dir="ltr"
                value={form.base_url}
                disabled={!canWrite}
                placeholder="https://api.openai.com/v1"
                onChange={(e) => setForm({ ...form, base_url: e.target.value })}
              />
              <span className="hint">{t("aiset.baseUrlHint")}</span>
            </div>

            <div className="note">{t("aiset.privacyNote")}</div>
          </>
        )}

        <label className="check">
          <input
            type="checkbox"
            checked={form.enabled}
            disabled={!canWrite}
            onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
          />
          {t("aiset.enabled")}
        </label>

        <p className="dim" style={{ fontSize: "var(--text-xs)" }}>
          {t("aiset.scoringNote")}
        </p>
      </section>

      {/* ── OCR (AI-01 / AI-07) ─────────────────────────────────────────── */}
      <section className="card card-pad stack stack-4">
        <div className="row row-tight">
          <span className="eyebrow">{t("aiset.ocrTitle")}</span>
          <span className="chip mono push">
            {t("aiset.ocrEffective")}: {state.ocr_effective}
          </span>
        </div>

        <div className="grid grid-auto-md">
          <div className="field">
            <label htmlFor="ocr-provider">{t("aiset.ocrProvider")}</label>
            <select
              id="ocr-provider"
              value={form.ocr_provider}
              disabled={!canWrite}
              onChange={(e) => setForm({ ...form, ocr_provider: e.target.value })}
            >
              {state.ocr_providers.map((p) => (
                <option key={p} value={p}>
                  {t(`aiset.ocr${p.charAt(0).toUpperCase()}${p.slice(1)}` as MessageKey)}
                </option>
              ))}
            </select>
          </div>

          {form.ocr_provider === "openai" && (
            <div className="field">
              <label htmlFor="ocr-model">{t("aiset.ocrModel")}</label>
              <input
                id="ocr-model"
                dir="ltr"
                value={form.ocr_model}
                disabled={!canWrite}
                onChange={(e) => setForm({ ...form, ocr_model: e.target.value })}
              />
            </div>
          )}
        </div>

        {form.ocr_provider === "openai" && (
          <p className="dim" style={{ fontSize: "var(--text-xs)" }}>
            {t("aiset.ocrConfidenceNote")}
          </p>
        )}
      </section>

      {/* ── actions ─────────────────────────────────────────────────────── */}
      {canWrite && (
        <div className="row row-tight">
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void save()}>
            {t("common.save")}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={testing || busy}
            onClick={() => void runTest()}
          >
            {testing ? t("aiset.testing") : t("aiset.test")}
          </button>
          {test && (
            <span className={`chip ${test.ok ? "chip-ok" : "chip-warn"}`}>
              {test.ok ? t("aiset.testOk") : t("aiset.testFailed")} · {test.detail}
              {test.latency_ms != null && ` · ${test.latency_ms}ms`}
            </span>
          )}
        </div>
      )}

      <p className="dim" style={{ fontSize: "var(--text-xs)" }}>
        {t("aiset.encryptedAtRest")}
      </p>
    </div>
  );
}

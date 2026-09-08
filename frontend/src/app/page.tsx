"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useLocale } from "@/i18n/LocaleProvider";
import { api, type Layer, type MaturityLevel } from "@/lib/api";
import { useSession } from "@/lib/session";

type Pillar = { code: string; name_ar: string; name_en: string; question_count: number };
type Preview = {
  pillars: Pillar[];
  levels: MaturityLevel[];
  question_count: number;
};

export default function LandingPage() {
  const { t, pick, pickList, num } = useLocale();
  const { me } = useSession();
  const [layers, setLayers] = useState<Layer[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);

  useEffect(() => {
    api<Layer[]>("/catalogue/layers", { auth: false })
      .then(setLayers)
      .catch(() => setLayers([]));
    api<Preview>("/catalogue/preview", { auth: false })
      .then(setPreview)
      .catch(() => setPreview(null));
  }, []);

  const pillars = preview?.pillars ?? [];
  const levels = preview?.levels ?? [];

  return (
    <div className="shell" style={{ paddingBottom: "var(--space-8)" }}>
      {/* ── hero ─────────────────────────────────────────────────────────── */}
      <section className="hero-split" style={{ paddingBlock: "var(--space-8) var(--space-7)" }}>
        <div className="stack stack-4">
          <span className="eyebrow">REMAS · iValue Consult</span>
          <h1 className="display" style={{ fontSize: "var(--text-4xl)", fontWeight: 600 }}>
            {t("landing.heroTitle")}
          </h1>
          <p className="muted" style={{ fontSize: "var(--text-lg)", maxWidth: "56ch" }}>
            {t("landing.heroBody")}
          </p>
          <div className="row" style={{ marginBlockStart: "var(--space-2)" }}>
            <Link href={me ? "/assessments/new" : "/register"} className="btn btn-primary">
              {t("landing.cta")}
            </Link>
            {!me && (
              <Link href="/login" className="btn btn-secondary">
                {t("landing.ctaSecondary")}
              </Link>
            )}
          </div>
        </div>

        {/* The maturity ladder — the scale the whole product resolves to */}
        <div className="card card-pad card-raised">
          <div className="row" style={{ marginBlockEnd: "var(--space-4)" }}>
            <span className="eyebrow">{t("landing.scaleTitle")}</span>
          </div>
          <div className="ladder">
            {(levels.length ? levels : FALLBACK_LEVELS).map((level) => (
              <div className="ladder-row" key={level.score}>
                <span className="ladder-num">{level.score}</span>
                <span className="ladder-bar">{pick(level, "label")}</span>
                <span className="mono dim" style={{ fontSize: "var(--text-xs)" }}>
                  {level.score}.0
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── numbers ──────────────────────────────────────────────────────── */}
      <section className="grid grid-auto-sm">
        <Stat value={num(pillars.length || 16, 0)} label={t("landing.statPillars")} />
        <Stat value={num(preview?.question_count || 0, 0)} label={t("landing.statQuestions")} />
        <Stat value={num(5, 0)} label={t("landing.statLevels")} />
        <Stat value={num(3, 0)} label={t("landing.statLayers")} />
      </section>

      {/* ── layers ───────────────────────────────────────────────────────── */}
      <section className="section">
        <div className="section-head">
          <div>
            <h2>{t("landing.layersTitle")}</h2>
            <p>{t("landing.layersBody")}</p>
          </div>
        </div>

        <div className="grid grid-auto-lg">
          {layers.map((layer, index) => {
            const featured = index === 1;
            return (
              <article
                key={layer.key}
                className={`card card-pad card-interactive stack stack-3 ${featured ? "card-feature" : ""}`}
              >
                <div className="row row-tight">
                  <span className="mono" style={{ fontSize: "var(--text-xs)", color: "var(--brand-500)" }}>
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  {featured && <span className="chip chip-accent push">{t("landing.popular")}</span>}
                </div>
                <h3 style={{ fontSize: "var(--text-lg)" }}>{pick(layer, "name")}</h3>
                <p className="muted" style={{ fontSize: "var(--text-sm)" }}>
                  {pick(layer, "summary")}
                </p>
                <hr className="divider" style={{ marginBlock: "var(--space-1)" }} />
                <ul className="stack stack-2 list-clean">
                  {pickList(layer, "includes").map((item) => (
                    <li key={item}>
                      <CheckMark />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
                {/* The output is a sentence, not a tag, so it gets its own row
                    and is free to wrap instead of overflowing the card. */}
                <div className="layer-output">
                  <span className="eyebrow">{t("landing.output")}</span>
                  <span className={`chip chip-wrap ${featured ? "chip-solid" : "chip-brand"}`}>
                    {pick(layer, "output")}
                  </span>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      {/* ── pillars ──────────────────────────────────────────────────────── */}
      {pillars.length > 0 && (
        <section className="section">
          <div className="section-head">
            <div>
              <h2>{t("landing.axes")}</h2>
              <p>{t("landing.axesBody")}</p>
            </div>
            <span className="chip mono">{pillars.length}</span>
          </div>
          <div className="grid grid-auto-md" style={{ gap: "var(--space-2)" }}>
            {pillars.map((pillar) => (
              <div key={pillar.code} className="card card-interactive pillar-row">
                <span className="mono" style={{ fontSize: "var(--text-xs)", color: "var(--brand-500)" }}>
                  {pillar.code}
                </span>
                <span className="pillar-name">{pick(pillar, "name")}</span>
                <span className="chip mono">{pillar.question_count}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <footer
        className="dim"
        style={{
          marginBlockStart: "var(--space-8)",
          paddingBlockStart: "var(--space-5)",
          borderBlockStart: "1px solid var(--line-2)",
          fontSize: "var(--text-sm)",
        }}
      >
        {t("app.by")}
      </footer>

      <style>{`
        .list-clean { margin:0; padding:0; list-style:none; }
        .layer-output {
          margin-block-start:auto; padding-block-start:var(--space-4);
          display:flex; flex-direction:column; gap:var(--space-2);
          align-items:flex-start; min-width:0;
        }
        /* Three fixed columns rather than a flex row: a long pillar name wraps
           inside its own column instead of shoving the count onto a second
           line, so every card keeps the same shape. */
        .pillar-row {
          display:grid; grid-template-columns:auto minmax(0,1fr) auto;
          align-items:center; gap:var(--space-3); padding:12px 14px;
        }
        .pillar-name { font-size:var(--text-sm); line-height:1.45; min-width:0; }
        .list-clean li {
          display:flex; align-items:flex-start; gap:var(--space-2);
          font-size:var(--text-sm); color:var(--ink-2); line-height:1.55;
        }
      `}</style>
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function CheckMark() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--brand-500)"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flex: "none", marginBlockStart: 4 }}
      aria-hidden="true"
    >
      <path d="M4.5 12.5l5 5 10-11" />
    </svg>
  );
}

/** Shown only if the API is unreachable, so the page never renders empty. */
const FALLBACK_LEVELS: MaturityLevel[] = [
  { score: 1, label_ar: "تأسيسي", label_en: "Initial", description_ar: null, description_en: null },
  { score: 2, label_ar: "ناشئ", label_en: "Developing", description_ar: null, description_en: null },
  { score: 3, label_ar: "مُعرَّف", label_en: "Defined", description_ar: null, description_en: null },
  { score: 4, label_ar: "مُدار", label_en: "Managed", description_ar: null, description_en: null },
  { score: 5, label_ar: "متميّز", label_en: "Distinguished", description_ar: null, description_en: null },
];

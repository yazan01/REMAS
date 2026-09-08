"use client";

/**
 * Maturity radar (BRD final report: "score by the 16 axes, radar chart").
 *
 * Hand-drawn SVG rather than a charting library: one scale places the rings,
 * the spokes, the polygon and the labels, and every colour comes from the
 * palette so it reads in both themes.
 */
export function RadarChart({
  data,
  max = 5,
  size = 320,
}: {
  data: Array<{ label: string; value: number }>;
  max?: number;
  size?: number;
}) {
  if (data.length < 3) {
    return (
      <div
        className="dim"
        style={{
          height: 180,
          display: "grid",
          placeItems: "center",
          fontSize: "var(--text-sm)",
        }}
      >
        —
      </div>
    );
  }

  const padding = 36; // room for the outermost labels inside the viewBox
  const radius = size / 2 - padding;
  const cx = size / 2;
  const cy = size / 2;
  const rings = [0.25, 0.5, 0.75, 1];

  const point = (index: number, ratio: number) => {
    const angle = (Math.PI * 2 * index) / data.length - Math.PI / 2;
    return [cx + Math.cos(angle) * radius * ratio, cy + Math.sin(angle) * radius * ratio] as const;
  };

  // The scale floor is 1, not 0 — a score of 1 is the lowest level, not "nothing".
  const ratioFor = (value: number) => Math.max(0, Math.min(1, (value - 1) / (max - 1)));

  const polygon = data
    .map((item, index) => {
      const [x, y] = point(index, ratioFor(item.value));
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      width="100%"
      height="auto"
      role="img"
      aria-label="Maturity radar"
      style={{ display: "block" }}
    >
      <defs>
        <radialGradient id="radar-fill" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="var(--brand-400)" stopOpacity="0.42" />
          <stop offset="100%" stopColor="var(--brand-500)" stopOpacity="0.16" />
        </radialGradient>
      </defs>

      {rings.map((ring, i) => (
        <polygon
          key={ring}
          points={data
            .map((_, index) => {
              const [x, y] = point(index, ring);
              return `${x.toFixed(1)},${y.toFixed(1)}`;
            })
            .join(" ")}
          fill={i === rings.length - 1 ? "var(--surface-2)" : "none"}
          stroke="var(--line-2)"
          strokeWidth="1"
        />
      ))}

      {data.map((_, index) => {
        const [x, y] = point(index, 1);
        return (
          <line key={index} x1={cx} y1={cy} x2={x} y2={y} stroke="var(--line-2)" strokeWidth="1" />
        );
      })}

      <polygon
        points={polygon}
        fill="url(#radar-fill)"
        stroke="var(--brand-600)"
        strokeWidth="2"
        strokeLinejoin="round"
      />

      {data.map((item, index) => {
        const [x, y] = point(index, ratioFor(item.value));
        return (
          <circle
            key={item.label}
            cx={x}
            cy={y}
            r="3"
            fill="var(--surface)"
            stroke="var(--brand-600)"
            strokeWidth="2"
          />
        );
      })}

      {data.map((item, index) => {
        const [x, y] = point(index, 1.15);
        return (
          <text
            key={item.label}
            x={x}
            y={y}
            fontSize="9"
            fontFamily="var(--font-mono)"
            fill="var(--ink-3)"
            textAnchor="middle"
            dominantBaseline="middle"
          >
            {item.label}
          </text>
        );
      })}
    </svg>
  );
}

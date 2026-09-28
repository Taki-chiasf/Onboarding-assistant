"use client";

export type ChartPoint = {
  label: string;
  value?: number;
  passed?: boolean;
};

const WIDTH = 640;
const HEIGHT = 170;
const INSET = { top: 14, right: 16, bottom: 26, left: 52 };

function fixed(value: number): string {
  return Number(value.toFixed(4)).toString();
}

export function MetricsChart({
  points,
  target,
  format = fixed,
}: {
  points: ChartPoint[];
  target?: number;
  format?: (value: number) => string;
}) {
  const defined = points.flatMap((point) => (point.value === undefined ? [] : [point.value]));
  if (defined.length === 0) {
    return (
      <p className="border-y py-6 text-sm text-muted-foreground">
        No values recorded for this metric yet.
      </p>
    );
  }

  const values = target === undefined ? defined : [...defined, target];
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    min -= 0.05;
    max += 0.05;
  }
  const pad = (max - min) * 0.12;
  min -= pad;
  max += pad;

  const innerW = WIDTH - INSET.left - INSET.right;
  const innerH = HEIGHT - INSET.top - INSET.bottom;
  const x = (index: number) =>
    INSET.left + (points.length <= 1 ? innerW / 2 : (index / (points.length - 1)) * innerW);
  const y = (value: number) => INSET.top + innerH - ((value - min) / (max - min)) * innerH;

  const segments: { x: number; y: number }[][] = [];
  let current: { x: number; y: number }[] = [];
  points.forEach((point, index) => {
    if (point.value === undefined) {
      if (current.length > 0) segments.push(current);
      current = [];
      return;
    }
    current.push({ x: x(index), y: y(point.value) });
  });
  if (current.length > 0) segments.push(current);

  const first = points[0]?.label ?? "";
  const last = points[points.length - 1]?.label ?? "";

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label="Metric over time"
      className="h-auto w-full"
    >
      <g className="text-muted-foreground">
        <line
          x1={INSET.left}
          x2={WIDTH - INSET.right}
          y1={INSET.top}
          y2={INSET.top}
          stroke="currentColor"
          strokeOpacity={0.15}
        />
        <text x={4} y={INSET.top + 4} className="font-mono text-[9px]">
          {format(max)}
        </text>
        <line
          x1={INSET.left}
          x2={WIDTH - INSET.right}
          y1={HEIGHT - INSET.bottom}
          y2={HEIGHT - INSET.bottom}
          stroke="currentColor"
          strokeOpacity={0.15}
        />
        <text x={4} y={HEIGHT - INSET.bottom + 4} className="font-mono text-[9px]">
          {format(min)}
        </text>
      </g>

      {target !== undefined && (
        <g className="text-muted-foreground">
          <line
            x1={INSET.left}
            x2={WIDTH - INSET.right}
            y1={y(target)}
            y2={y(target)}
            stroke="currentColor"
            strokeDasharray="4 4"
            strokeOpacity={0.6}
          />
          <text
            x={WIDTH - INSET.right}
            y={y(target) - 4}
            textAnchor="end"
            className="font-mono text-[9px]"
          >
            target {format(target)}
          </text>
        </g>
      )}

      <g className="text-foreground/40">
        {segments.map((segment, index) => (
          <polyline
            key={index}
            points={segment.map((point) => `${point.x},${point.y}`).join(" ")}
            fill="none"
            stroke="currentColor"
            strokeWidth={1.5}
          />
        ))}
      </g>

      <g>
        {points.map((point, index) =>
          point.value === undefined ? null : (
            <circle
              key={index}
              cx={x(index)}
              cy={y(point.value)}
              r={3}
              fill={point.passed === false ? "var(--destructive)" : "var(--brand-vermilion)"}
            >
              <title>
                {point.label}: {format(point.value)}
              </title>
            </circle>
          )
        )}
      </g>

      <g className="text-muted-foreground">
        <text x={INSET.left} y={HEIGHT - 8} className="font-mono text-[9px]">
          {first}
        </text>
        {last !== first && (
          <text
            x={WIDTH - INSET.right}
            y={HEIGHT - 8}
            textAnchor="end"
            className="font-mono text-[9px]"
          >
            {last}
          </text>
        )}
      </g>
    </svg>
  );
}

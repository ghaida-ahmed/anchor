import { useId } from 'react';

export interface SparkPoint {
  label: string;
  value: number;
}

interface SparklineProps {
  points: SparkPoint[];
  /** Accessible summary of what the line shows. */
  caption: string;
  max?: number;
  min?: number;
}

/**
 * A small line chart, drawn as inline SVG.
 *
 * No charting dependency: the shapes needed here are a polyline and some dots, and
 * a library would add far more weight than it saves.
 *
 * Sparse data is handled honestly. Points are plotted at equal spacing by their
 * order, NOT by calendar position, and no value is interpolated across days with no
 * activity — a gap in practice is not drawn as a smooth line through it. A single
 * point renders as a dot rather than a misleading flat line.
 */
export function Sparkline({ points, caption, max = 100, min = 0 }: SparklineProps) {
  const titleId = useId();

  if (points.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-ink-400">Not enough data yet.</p>
    );
  }

  const width = 100;
  const height = 32;
  const span = Math.max(max - min, 1);

  const x = (index: number) =>
    points.length === 1 ? width / 2 : (index / (points.length - 1)) * width;
  const y = (value: number) =>
    height - ((Math.min(Math.max(value, min), max) - min) / span) * height;

  const path = points.map((point, index) => `${x(index)},${y(point.value)}`).join(' ');
  const last = points[points.length - 1];

  return (
    <figure className="w-full">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-labelledby={titleId}
        className="h-16 w-full overflow-visible"
      >
        <title id={titleId}>{caption}</title>

        {points.length > 1 ? (
          <polyline
            points={path}
            fill="none"
            className="stroke-ink-700"
            strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ) : null}

        {points.map((point, index) => (
          <circle
            key={`${point.label}-${index}`}
            cx={x(index)}
            cy={y(point.value)}
            r={points.length === 1 ? 3 : 2}
            className={
              index === points.length - 1 ? 'fill-brass-500' : 'fill-ink-400'
            }
            vectorEffect="non-scaling-stroke"
          >
            <title>{`${point.label}: ${point.value.toFixed(0)}`}</title>
          </circle>
        ))}
      </svg>

      <figcaption className="mt-1 flex justify-between text-xs text-ink-400">
        <span>{points[0]?.label}</span>
        {points.length > 1 ? <span>{last?.label}</span> : null}
      </figcaption>
    </figure>
  );
}

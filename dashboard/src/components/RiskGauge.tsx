/**
 * RiskGauge.tsx — Pure SVG semicircular gauge for p_fraud (0→1).
 *
 * Color zones: green (0–0.3), amber (0.3–0.6), red (0.6–1.0).
 * No external dependencies.
 */

interface Props {
  value: number;       // 0..1
  size?: number;       // px, default 120
  label?: string;      // optional label below the value
}

export function RiskGauge({ value, size = 120, label }: Props) {
  const clamped = Math.max(0, Math.min(1, value));

  // SVG arc geometry
  const cx = size / 2;
  const cy = size / 2 + 4;         // push center down slightly
  const radius = size / 2 - 12;
  const strokeWidth = 10;

  // Arc from 180° to 0° (left semicircle to right)
  const startAngle = Math.PI;       // 180°
  const endAngle = 0;               // 0°
  const totalAngle = Math.PI;       // 180° sweep

  // Background arc (full semicircle)
  const bgArc = describeArc(cx, cy, radius, startAngle, endAngle);

  // Value arc (partial fill)
  const valueAngle = startAngle - clamped * totalAngle;
  const valArc = describeArc(cx, cy, radius, startAngle, valueAngle);

  // Color based on value
  const color = clamped <= 0.3
    ? 'var(--status-success)'
    : clamped <= 0.6
      ? 'var(--status-warning)'
      : 'var(--status-danger)';

  const glowColor = clamped <= 0.3
    ? 'rgba(16, 185, 129, 0.4)'
    : clamped <= 0.6
      ? 'rgba(245, 158, 11, 0.4)'
      : 'rgba(239, 68, 68, 0.4)';

  return (
    <div style={{ width: size, height: size * 0.65, position: 'relative' }}>
      <svg
        width={size}
        height={size * 0.65}
        viewBox={`0 0 ${size} ${size * 0.65}`}
        style={{ overflow: 'visible' }}
      >
        {/* Glow filter */}
        <defs>
          <filter id={`glow-${size}`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Background arc */}
        <path
          d={bgArc}
          fill="none"
          stroke="rgba(255,255,255,0.08)"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
        />

        {/* Value arc */}
        {clamped > 0.001 && (
          <path
            d={valArc}
            fill="none"
            stroke={color}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            filter={`url(#glow-${size})`}
            style={{
              transition: 'stroke 0.4s ease',
              filter: `drop-shadow(0 0 6px ${glowColor})`,
            }}
          />
        )}

        {/* Center text */}
        <text
          x={cx}
          y={cy - 6}
          textAnchor="middle"
          fill="var(--text-primary)"
          fontSize={size * 0.22}
          fontWeight="700"
          fontFamily="'Inter', monospace"
        >
          {(clamped * 100).toFixed(1)}%
        </text>

        {label && (
          <text
            x={cx}
            y={cy + size * 0.1}
            textAnchor="middle"
            fill="var(--text-muted)"
            fontSize={size * 0.1}
            fontWeight="500"
          >
            {label}
          </text>
        )}
      </svg>
    </div>
  );
}

/**
 * Describe an SVG arc path from startAngle to endAngle (radians).
 * Angles: 0 = right, PI/2 = bottom, PI = left (standard math).
 */
function describeArc(
  cx: number, cy: number, r: number,
  startAngle: number, endAngle: number
): string {
  const x1 = cx + r * Math.cos(startAngle);
  const y1 = cy - r * Math.sin(startAngle);
  const x2 = cx + r * Math.cos(endAngle);
  const y2 = cy - r * Math.sin(endAngle);

  const sweep = startAngle - endAngle;
  const largeArc = sweep > Math.PI ? 1 : 0;

  return `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 0 ${x2} ${y2}`;
}

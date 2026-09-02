/**
 * LayerVerdicts.tsx — Compact pipeline visualizer for the 6 decision layers.
 *
 * Shows each layer in order with its verdict badge (PASS, HOLD, SKIP, etc.).
 * Matches the spec §9.2 layer order:
 *   1. Compliance → 2. Blocklist → 3. Allowlist → 4. Breaker → 5. ML → 6. Shadow
 */
import { Shield, Ban, CheckCircle, Zap, Brain, Eye } from 'lucide-react';
import type { ReactNode } from 'react';

interface Props {
  verdicts: Record<string, string>;
  shadowMode?: boolean;
}

interface LayerConfig {
  key: string;
  label: string;
  icon: ReactNode;
}

const LAYERS: LayerConfig[] = [
  { key: 'compliance', label: 'Compliance',     icon: <Shield size={14} /> },
  { key: 'blocklist',  label: 'Blocklist',      icon: <Ban size={14} /> },
  { key: 'allowlist',  label: 'Allowlist',       icon: <CheckCircle size={14} /> },
  { key: 'breaker',    label: 'Breaker',         icon: <Zap size={14} /> },
  { key: 'ml',         label: 'ML Scoring',      icon: <Brain size={14} /> },
];

function getVerdictStyle(verdict: string): { bg: string; color: string; border: string } {
  const v = verdict.toUpperCase();
  if (v.includes('HOLD') || v.includes('BLOCK'))
    return { bg: 'var(--status-danger-bg)', color: 'var(--status-danger)', border: 'rgba(239,68,68,0.3)' };
  if (v === 'PASS' || v === 'NO_MATCH' || v === 'CLOSED')
    return { bg: 'var(--status-success-bg)', color: 'var(--status-success)', border: 'rgba(16,185,129,0.3)' };
  if (v === 'CAPTURE')
    return { bg: 'var(--status-success-bg)', color: 'var(--status-success)', border: 'rgba(16,185,129,0.3)' };
  if (v === 'VERIFY')
    return { bg: 'var(--status-info-bg)', color: 'var(--status-info)', border: 'rgba(59,130,246,0.3)' };
  if (v === 'SKIP' || v === 'BYPASSED')
    return { bg: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)', border: 'rgba(255,255,255,0.1)' };
  if (v === 'OPEN')
    return { bg: 'var(--status-warning-bg)', color: 'var(--status-warning)', border: 'rgba(245,158,11,0.3)' };
  return { bg: 'rgba(255,255,255,0.05)', color: 'var(--text-secondary)', border: 'rgba(255,255,255,0.1)' };
}

export function LayerVerdicts({ verdicts, shadowMode }: Props) {
  if (!verdicts || Object.keys(verdicts).length === 0) {
    return (
      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
        No layer data available
      </div>
    );
  }

  return (
    <div className="layer-verdicts-container">
      <div className="layer-verdicts-pipeline">
        {LAYERS.map((layer, idx) => {
          const verdict = verdicts[layer.key] || '—';
          const style = getVerdictStyle(verdict);
          const isResolvingLayer = verdict !== 'PASS' && verdict !== 'NO_MATCH'
            && verdict !== 'SKIP' && verdict !== 'CLOSED' && verdict !== '—';

          return (
            <div key={layer.key} className="layer-verdicts-step">
              {/* Connector line */}
              {idx > 0 && (
                <div className="layer-verdicts-connector" />
              )}

              {/* Layer node */}
              <div
                className="layer-verdicts-node"
                style={{
                  borderColor: isResolvingLayer ? style.color : 'var(--panel-border)',
                  background: isResolvingLayer ? style.bg : 'rgba(0,0,0,0.2)',
                  boxShadow: isResolvingLayer ? `0 0 12px ${style.border}` : 'none',
                }}
              >
                <div className="layer-verdicts-icon" style={{ color: style.color }}>
                  {layer.icon}
                </div>
                <div className="layer-verdicts-info">
                  <span className="layer-verdicts-label">{layer.label}</span>
                  <span
                    className="layer-verdicts-verdict"
                    style={{ color: style.color }}
                  >
                    {verdict}
                  </span>
                </div>
              </div>
            </div>
          );
        })}

        {/* Shadow mode indicator (layer 6) */}
        {shadowMode !== undefined && (
          <div className="layer-verdicts-step">
            <div className="layer-verdicts-connector" />
            <div
              className="layer-verdicts-node"
              style={{
                borderColor: shadowMode ? 'var(--status-warning)' : 'var(--panel-border)',
                background: shadowMode ? 'var(--status-warning-bg)' : 'rgba(0,0,0,0.2)',
              }}
            >
              <div className="layer-verdicts-icon" style={{ color: shadowMode ? 'var(--status-warning)' : 'var(--text-muted)' }}>
                <Eye size={14} />
              </div>
              <div className="layer-verdicts-info">
                <span className="layer-verdicts-label">Shadow</span>
                <span
                  className="layer-verdicts-verdict"
                  style={{ color: shadowMode ? 'var(--status-warning)' : 'var(--status-success)' }}
                >
                  {shadowMode ? 'ACTIVE' : 'OFF'}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

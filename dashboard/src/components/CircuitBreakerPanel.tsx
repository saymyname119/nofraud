/**
 * CircuitBreakerPanel.tsx — Dashboard status card for the circuit breaker.
 *
 * Shows OPEN/CLOSED state, current hold rate, and a visual indicator.
 */
import { useEffect, useState } from 'react';
import { Zap, ZapOff } from 'lucide-react';
import { fetchBreakerStatus } from '../api';
import type { BreakerStatus } from '../api';

interface Props {
  refreshKey?: string | null;  // trigger refetch when this changes (from SSE)
}

export function CircuitBreakerPanel({ refreshKey }: Props) {
  const [status, setStatus] = useState<BreakerStatus | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchBreakerStatus()
      .then((data) => { if (!cancelled) { setStatus(data); setError(false); } })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; };
  }, [refreshKey]);

  if (error) {
    return (
      <div className="glass-panel breaker-panel" style={{ padding: '1.25rem' }}>
        <div className="flex items-center gap-2">
          <ZapOff size={18} style={{ color: 'var(--text-muted)' }} />
          <span className="text-sm text-muted">Breaker status unavailable</span>
        </div>
      </div>
    );
  }

  if (!status) {
    return (
      <div className="glass-panel breaker-panel" style={{ padding: '1.25rem' }}>
        <span className="text-sm text-muted animate-pulse">Loading breaker…</span>
      </div>
    );
  }

  const isOpen = status.state === 'OPEN';

  return (
    <div
      className="glass-panel breaker-panel"
      style={{
        padding: '1.25rem',
        borderColor: isOpen ? 'rgba(245, 158, 11, 0.4)' : 'var(--panel-border)',
      }}
    >
      <div className="flex items-center justify-between" style={{ marginBottom: '0.75rem' }}>
        <div className="flex items-center gap-2">
          {isOpen ? (
            <div
              className="animate-pulse"
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                width: 32, height: 32, borderRadius: 'var(--radius-sm)',
                background: 'var(--status-warning-bg)', border: '1px solid rgba(245,158,11,0.3)',
              }}
            >
              <ZapOff size={18} style={{ color: 'var(--status-warning)' }} />
            </div>
          ) : (
            <div
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                width: 32, height: 32, borderRadius: 'var(--radius-sm)',
                background: 'var(--status-success-bg)', border: '1px solid rgba(16,185,129,0.3)',
              }}
            >
              <Zap size={18} style={{ color: 'var(--status-success)' }} />
            </div>
          )}
          <div>
            <div className="text-sm font-semibold" style={{ letterSpacing: '0.02em' }}>
              Circuit Breaker
            </div>
            <div className="text-xs text-muted">ML scoring gate</div>
          </div>
        </div>

        <span className={`badge ${isOpen ? 'warning' : 'success'}`}>
          {status.state}
        </span>
      </div>

      {/* Hold rate bar */}
      <div>
        <div className="flex justify-between text-xs" style={{ marginBottom: '0.35rem' }}>
          <span className="text-muted">Hold Rate</span>
          <span className="font-semibold" style={{ fontFamily: "'Inter', monospace" }}>
            {(status.hold_rate * 100).toFixed(1)}%
          </span>
        </div>
        <div
          style={{
            width: '100%', height: 6, borderRadius: 3,
            background: 'rgba(26,25,24,0.08)', overflow: 'hidden',
          }}
        >
          <div
            style={{
              height: '100%', borderRadius: 3,
              width: `${Math.min(status.hold_rate * 100, 100)}%`,
              background: isOpen
                ? 'var(--status-warning)'
                : status.hold_rate > 0.03
                  ? 'var(--status-warning)'
                  : 'var(--status-success)',
              transition: 'width 0.6s ease, background 0.4s ease',
            }}
          />
        </div>
      </div>
    </div>
  );
}

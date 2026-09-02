import { useEffect, useState } from 'react';
import type { CostStats } from '../api';
import { IndianRupee, ShieldCheck, AlertCircle } from 'lucide-react';

interface Props {
  stats: CostStats | null;
}

export function CostCounter({ stats }: Props) {
  const [animatedFraud, setAnimatedFraud] = useState(0);

  // Simple animation for the big number
  useEffect(() => {
    if (!stats) return;
    let start = animatedFraud;
    const end = stats.fraud_prevented;
    const duration = 1000;
    const startTime = performance.now();

    const animate = (time: number) => {
      const elapsed = time - startTime;
      const progress = Math.min(elapsed / duration, 1);
      
      // Easing out function
      const easeProgress = 1 - Math.pow(1 - progress, 3);
      setAnimatedFraud(Math.floor(start + (end - start) * easeProgress));

      if (progress < 1) {
        requestAnimationFrame(animate);
      }
    };
    
    requestAnimationFrame(animate);
  }, [stats?.fraud_prevented]);

  if (!stats) {
    return (
      <div className="glass-panel" style={{ padding: '2rem', textAlign: 'center' }}>
        <p className="text-muted animate-pulse">Loading stats...</p>
      </div>
    );
  }

  const breakdown = stats.action_breakdown || { CAPTURE: 0, VERIFY: 0, HOLD: 0 };
  const total = breakdown.CAPTURE + breakdown.VERIFY + breakdown.HOLD;
  const capturePct = total > 0 ? (breakdown.CAPTURE / total) * 100 : 100;
  const verifyPct = total > 0 ? (breakdown.VERIFY / total) * 100 : 0;
  const holdPct = total > 0 ? (breakdown.HOLD / total) * 100 : 0;

  return (
    <div className="glass-panel" style={{ padding: '2rem' }}>
      <div className="flex justify-between items-center header" style={{ borderBottom: '1px solid var(--ant-border-mid)', paddingBottom: '1rem', marginBottom: '1.5rem' }}>
        <h2 className="text-xl font-semibold flex items-center gap-2" style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontWeight: 400 }}>
          <ShieldCheck size={24} style={{ color: 'var(--status-info)' }} />
          Live Value Created
        </h2>
        <span className="badge neutral">Last 24h</span>
      </div>

      <div className="cost-stats-grid">
        <div className="flex-col gap-2">
          <span className="text-muted text-sm uppercase font-semibold tracking-wider">
            Fraud Prevented
          </span>
          <div className="flex items-center gap-2 text-4xl font-bold text-gradient">
            <IndianRupee size={36} />
            {animatedFraud.toLocaleString('en-IN')}
          </div>
          <span className="text-xs text-secondary">
            Estimated vs Allow-All baseline
          </span>
        </div>

        <div className="flex-col gap-2">
          <span className="text-muted text-sm uppercase font-semibold tracking-wider flex items-center gap-2">
            False Positives <AlertCircle size={14} />
          </span>
          <div className="text-4xl font-bold" style={{ color: 'var(--status-warning)' }}>
            {stats.false_positives_count.toLocaleString('en-IN')}
          </div>
          <span className="text-xs text-secondary">
            Genuine txns challenged
          </span>
        </div>

        <div className="flex-col gap-2">
          <span className="text-muted text-sm uppercase font-semibold tracking-wider">
            Total Scored Volume
          </span>
          <div className="flex items-center gap-2 text-2xl font-semibold">
            <IndianRupee size={24} />
            {Math.floor(stats.total_volume).toLocaleString('en-IN')}
          </div>
          <span className="text-xs text-secondary">
            Across {stats.total_decisions} decisions
          </span>
        </div>
      </div>

      {/* Action breakdown stacked bar */}
      {total > 0 && (
        <div style={{ marginTop: '1.5rem' }}>
          <div className="flex justify-between text-xs" style={{ marginBottom: '0.5rem' }}>
            <span className="text-muted uppercase font-semibold" style={{ letterSpacing: '0.05em' }}>
              Decision Breakdown
            </span>
            <span className="text-secondary">{total} decisions</span>
          </div>

          {/* Stacked bar */}
          <div className="action-bar-container">
            {capturePct > 0 && (
              <div
                className="action-bar-segment"
                style={{
                  width: `${capturePct}%`,
                  background: 'var(--status-success)',
                }}
                title={`CAPTURE: ${breakdown.CAPTURE}`}
              />
            )}
            {verifyPct > 0 && (
              <div
                className="action-bar-segment"
                style={{
                  width: `${verifyPct}%`,
                  background: 'var(--status-info)',
                }}
                title={`VERIFY: ${breakdown.VERIFY}`}
              />
            )}
            {holdPct > 0 && (
              <div
                className="action-bar-segment"
                style={{
                  width: `${holdPct}%`,
                  background: 'var(--status-warning)',
                }}
                title={`HOLD: ${breakdown.HOLD}`}
              />
            )}
          </div>

          {/* Legend */}
          <div className="flex gap-4" style={{ marginTop: '0.5rem' }}>
            <div className="flex items-center gap-2 text-xs">
              <div style={{ width: 8, height: 8, borderRadius: 2, background: 'var(--status-success)' }} />
              <span className="text-secondary">Capture ({breakdown.CAPTURE})</span>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <div style={{ width: 8, height: 8, borderRadius: 2, background: 'var(--status-info)' }} />
              <span className="text-secondary">Verify ({breakdown.VERIFY})</span>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <div style={{ width: 8, height: 8, borderRadius: 2, background: 'var(--status-warning)' }} />
              <span className="text-secondary">Hold ({breakdown.HOLD})</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

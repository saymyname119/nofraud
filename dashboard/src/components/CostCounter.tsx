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

  return (
    <div className="glass-panel" style={{ padding: '2rem' }}>
      <div className="flex justify-between items-center header">
        <h2 className="text-xl font-semibold flex items-center gap-2">
          <ShieldCheck size={24} style={{ color: 'var(--accent-blue)' }} />
          Live Value Created
        </h2>
        <span className="badge neutral">Last 24h</span>
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '2rem' }}>
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
    </div>
  );
}

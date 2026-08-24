import type { PaymentDecision } from '../api';
import { Clock, ShieldAlert, IndianRupee } from 'lucide-react';

interface Props {
  payments: PaymentDecision[];
}

export function PaymentTable({ payments }: Props) {
  if (payments.length === 0) {
    return (
      <div className="glass-panel" style={{ padding: '3rem', textAlign: 'center' }}>
        <p className="text-muted">No transactions yet. Send a webhook to see live activity.</p>
      </div>
    );
  }

  const getActionBadgeClass = (action: string) => {
    switch (action) {
      case 'CAPTURE': return 'success';
      case 'HOLD': return 'warning';
      case 'VERIFY': return 'info';
      default: return 'neutral';
    }
  };

  return (
    <div className="glass-panel" style={{ overflow: 'hidden' }}>
      <div className="header flex items-center justify-between" style={{ padding: '1.5rem', marginBottom: 0, borderBottom: '1px solid var(--panel-border)' }}>
        <h3 className="text-lg font-semibold flex items-center gap-2">
          <Clock size={20} className="text-secondary" />
          Recent Transactions
        </h3>
        <span className="badge neutral animate-pulse" style={{ fontSize: '0.65rem' }}>
          Live
        </span>
      </div>
      
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead>
            <tr style={{ backgroundColor: 'rgba(0,0,0,0.2)', color: 'var(--text-muted)', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              <th style={{ padding: '1rem 1.5rem' }}>Time</th>
              <th style={{ padding: '1rem 1.5rem' }}>Amount</th>
              <th style={{ padding: '1rem 1.5rem' }}>Action</th>
              <th style={{ padding: '1rem 1.5rem' }}>Risk (p_fraud)</th>
              <th style={{ padding: '1rem 1.5rem' }}>Reasons</th>
            </tr>
          </thead>
          <tbody>
            {payments.map((p, idx) => (
              <tr 
                key={p.tx_id} 
                className="animate-slide-up"
                style={{ 
                  borderTop: '1px solid var(--panel-border)',
                  animationDelay: `${idx * 50}ms`
                }}
              >
                <td style={{ padding: '1rem 1.5rem', fontSize: '0.875rem' }}>
                  {new Date(p.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                </td>
                <td style={{ padding: '1rem 1.5rem', fontSize: '0.875rem', fontWeight: 600 }}>
                  <div className="flex items-center">
                    <IndianRupee size={14} />
                    {p.amount?.toLocaleString('en-IN') ?? '-'}
                  </div>
                </td>
                <td style={{ padding: '1rem 1.5rem' }}>
                  <span className={`badge ${getActionBadgeClass(p.action)}`}>
                    {p.action}
                  </span>
                </td>
                <td style={{ padding: '1rem 1.5rem' }}>
                  {p.p_fraud !== null ? (
                    <div className="flex items-center gap-2">
                      <div 
                        style={{
                          width: '40px', 
                          height: '6px', 
                          background: 'rgba(255,255,255,0.1)',
                          borderRadius: '3px',
                          overflow: 'hidden'
                        }}
                      >
                        <div 
                          style={{
                            height: '100%',
                            width: `${p.p_fraud * 100}%`,
                            background: p.p_fraud > 0.5 ? 'var(--status-danger)' : 'var(--status-success)'
                          }}
                        />
                      </div>
                      <span className="text-xs font-mono">{p.p_fraud.toFixed(3)}</span>
                    </div>
                  ) : (
                    <span className="text-xs text-muted">N/A</span>
                  )}
                </td>
                <td style={{ padding: '1rem 1.5rem' }}>
                  <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
                    {p.reasons.map((r) => (
                      <span key={r} className="badge neutral flex items-center gap-1" style={{ fontSize: '0.65rem' }}>
                        {r.includes('RISK') && <ShieldAlert size={10} style={{ color: 'var(--status-danger)' }} />}
                        {r}
                      </span>
                    ))}
                    {p.reasons.length === 0 && <span className="text-xs text-muted">-</span>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

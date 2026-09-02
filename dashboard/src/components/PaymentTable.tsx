import { useState } from 'react';
import type { PaymentDecision } from '../api';
import { Clock, ShieldAlert, IndianRupee, ChevronDown, ChevronUp } from 'lucide-react';
import { RiskGauge } from './RiskGauge';
import { LayerVerdicts } from './LayerVerdicts';

interface Props {
  payments: PaymentDecision[];
}

export function PaymentTable({ payments }: Props) {
  const [expandedTxId, setExpandedTxId] = useState<string | null>(null);

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
      case 'PASS (shadow)': return 'neutral';
      default: return 'neutral';
    }
  };

  const toggleRow = (txId: string) => {
    setExpandedTxId((prev) => (prev === txId ? null : txId));
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
        <table className="payment-table">
          <thead>
            <tr style={{ backgroundColor: 'transparent', borderBottom: '1px solid var(--ant-border-mid)', color: 'var(--text-muted)', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              <th style={{ padding: '1rem 1.5rem', width: '2rem' }}></th>
              <th style={{ padding: '1rem 1.5rem' }}>Time</th>
              <th style={{ padding: '1rem 1.5rem' }}>Amount</th>
              <th style={{ padding: '1rem 1.5rem' }}>Action</th>
              <th className="hide-mobile" style={{ padding: '1rem 1.5rem' }}>Risk (p_fraud)</th>
              <th className="hide-mobile" style={{ padding: '1rem 1.5rem' }}>Reasons</th>
            </tr>
          </thead>
          <tbody>
            {payments.map((p, idx) => {
              const isExpanded = expandedTxId === p.tx_id;
              return (
                <>
                  <tr 
                    key={p.tx_id} 
                    className="animate-slide-up payment-row"
                    style={{ 
                      borderTop: '1px solid var(--panel-border)',
                      animationDelay: `${idx * 50}ms`,
                      cursor: 'pointer',
                    }}
                    onClick={() => toggleRow(p.tx_id)}
                  >
                    <td style={{ padding: '1rem 0.75rem 1rem 1.5rem', width: '1.5rem' }}>
                      {isExpanded
                        ? <ChevronUp size={16} style={{ color: 'var(--text-muted)', transition: 'transform 0.2s' }} />
                        : <ChevronDown size={16} style={{ color: 'var(--text-muted)', transition: 'transform 0.2s' }} />
                      }
                    </td>
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
                    <td className="hide-mobile" style={{ padding: '1rem 1.5rem' }}>
                      {p.p_fraud !== null ? (
                        <div className="flex items-center gap-2">
                          <div 
                            style={{
                              width: '40px', 
                              height: '6px', 
                              background: 'rgba(26,25,24,0.1)',
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
                    <td className="hide-mobile" style={{ padding: '1rem 1.5rem' }}>
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

                  {/* Expanded detail row */}
                  {isExpanded && (
                    <tr key={`${p.tx_id}-detail`}>
                      <td colSpan={6} style={{ padding: 0 }}>
                        <div className="expanded-detail animate-scale-in">
                          <div className="expanded-detail-grid">
                            {/* Risk Gauge */}
                            <div className="expanded-detail-section">
                              <div className="text-xs text-muted uppercase font-semibold" style={{ marginBottom: '0.75rem', letterSpacing: '0.05em' }}>
                                Risk Score
                              </div>
                              <div className="flex justify-center">
                                <RiskGauge
                                  value={p.p_fraud ?? 0}
                                  size={140}
                                  label="p(fraud)"
                                />
                              </div>
                            </div>

                            {/* Layer Verdicts */}
                            <div className="expanded-detail-section">
                              <div className="text-xs text-muted uppercase font-semibold" style={{ marginBottom: '0.75rem', letterSpacing: '0.05em' }}>
                                Decision Pipeline
                              </div>
                              <LayerVerdicts
                                verdicts={p.layer_verdicts}
                                shadowMode={p.shadow_mode}
                              />
                            </div>

                            {/* Transaction Details */}
                            <div className="expanded-detail-section">
                              <div className="text-xs text-muted uppercase font-semibold" style={{ marginBottom: '0.75rem', letterSpacing: '0.05em' }}>
                                Details
                              </div>
                              <div className="flex-col gap-2 text-xs">
                                <div className="flex justify-between">
                                  <span className="text-muted">TX ID</span>
                                  <span className="font-mono text-secondary" title={p.tx_id}>
                                    {p.tx_id}
                                  </span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted">Payment ID</span>
                                  <span className="font-mono text-secondary">
                                    {p.payment_id ?? '—'}
                                  </span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted">Amount</span>
                                  <span className="font-semibold flex items-center">
                                    <IndianRupee size={12} />
                                    {p.amount?.toLocaleString('en-IN') ?? '-'}
                                  </span>
                                </div>
                                <div className="flex justify-between">
                                  <span className="text-muted">Shadow Mode</span>
                                  <span className={`badge ${p.shadow_mode ? 'warning' : 'neutral'}`} style={{ fontSize: '0.6rem' }}>
                                    {p.shadow_mode ? 'ON' : 'OFF'}
                                  </span>
                                </div>
                                {/* Reasons shown here for mobile (hidden in table on small screens) */}
                                <div className="show-mobile-only" style={{ marginTop: '0.5rem' }}>
                                  <span className="text-muted" style={{ display: 'block', marginBottom: '0.35rem' }}>Reasons</span>
                                  <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
                                    {p.reasons.map((r) => (
                                      <span key={r} className="badge neutral" style={{ fontSize: '0.6rem' }}>{r}</span>
                                    ))}
                                    {p.reasons.length === 0 && <span className="text-muted">—</span>}
                                  </div>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

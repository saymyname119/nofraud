import { useEffect, useState, useCallback } from 'react';
import './App.css';
import { fetchPayments, fetchAuditLog, fetchStats, useSSE } from './api';
import type { PaymentDecision, AuditRecord, CostStats } from './api';
import { CostCounter } from './components/CostCounter';
import { PaymentTable } from './components/PaymentTable';
import { AuditLog } from './components/AuditLog';
import { CircuitBreakerPanel } from './components/CircuitBreakerPanel';
import { Shield, Activity } from 'lucide-react';

function App() {
  const [payments, setPayments] = useState<PaymentDecision[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditRecord[]>([]);
  const [stats, setStats] = useState<CostStats | null>(null);
  const [isLive, setIsLive] = useState(true);

  const lastEventId = useSSE();

  const loadData = useCallback(async () => {
    try {
      const [pData, aData, sData] = await Promise.all([
        fetchPayments(),
        fetchAuditLog(),
        fetchStats()
      ]);
      setPayments(pData);
      setAuditLogs(aData);
      setStats(sData);
      setIsLive(true);
    } catch (err) {
      console.error("Failed to fetch dashboard data:", err);
      setIsLive(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  useEffect(() => {
    if (lastEventId) loadData();
  }, [lastEventId, loadData]);

  return (
    <>
      {/* ── Sticky top nav bar ── */}
      <header className="app-header" style={{
        boxShadow: 'none',
        borderBottom: '1px solid var(--ant-border-subtle)',
        paddingTop: '32px',
        paddingBottom: '32px',
        backgroundColor: 'transparent'
      }}>
        <div className="flex items-center gap-4">
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'transparent',
            border: '1px solid var(--ant-border-strong)',
            borderRadius: '4px',
            padding: '8px'
          }}>
            <Shield size={24} style={{ color: 'var(--ant-primary)' }} />
          </div>
          <div>
            <h1
              style={{
                fontFamily: 'var(--font-serif)',
                fontSize: '1.5rem',
                fontWeight: 400,
                letterSpacing: '0',
                lineHeight: 1,
                color: 'var(--ant-text)',
                fontStyle: 'italic'
              }}
            >
              AegisPay
            </h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '13px', marginTop: '4px', letterSpacing: '0.02em', fontWeight: 500 }}>
              Autonomous Risk Intelligence & Payment Defense
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {isLive ? (
            <span className="badge success flex items-center gap-1 animate-pulse" style={{ background: 'transparent', border: '1px solid var(--status-success)', color: 'var(--status-success)' }}>
              <Activity size={12} /> LIVE
            </span>
          ) : (
            <span className="badge danger" style={{ background: 'transparent', border: '1px solid var(--status-danger)', color: 'var(--status-danger)' }}>DISCONNECTED</span>
          )}
        </div>
      </header>

      {/* ── Page content ── */}
      <div className="container">
        {/* Stats + Circuit Breaker row */}
        <section className="stats-row animate-slide-up" style={{ animationDelay: '60ms' }}>
          <div style={{ flex: '1 1 0' }}>
            <CostCounter stats={stats} />
          </div>
          <div className="breaker-column">
            <CircuitBreakerPanel refreshKey={lastEventId} />
          </div>
        </section>

        {/* Main Grid: Table + Audit Log */}
        <section className="main-grid animate-slide-up" style={{ animationDelay: '120ms' }}>
          <PaymentTable payments={payments} />
          <AuditLog logs={auditLogs} />
        </section>
      </div>
    </>
  );
}

export default App;

import { useEffect, useState, useCallback } from 'react';
import { fetchPayments, fetchAuditLog, fetchStats, useSSE } from './api';
import type { PaymentDecision, AuditRecord, CostStats } from './api';
import { CostCounter } from './components/CostCounter';
import { PaymentTable } from './components/PaymentTable';
import { AuditLog } from './components/AuditLog';
import { Shield, Activity } from 'lucide-react';

function App() {
  const [payments, setPayments] = useState<PaymentDecision[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditRecord[]>([]);
  const [stats, setStats] = useState<CostStats | null>(null);
  const [isLive, setIsLive] = useState(true);

  // Hook into the SSE stream
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
    } catch (err) {
      console.error("Failed to fetch dashboard data:", err);
      setIsLive(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadData();
  }, [loadData]);

  // Reload data whenever a new SSE event is received
  useEffect(() => {
    if (lastEventId) {
      loadData();
    }
  }, [lastEventId, loadData]);

  return (
    <div className="container flex-col gap-8">
      {/* Header section */}
      <header className="flex justify-between items-center" style={{ marginBottom: '1rem' }}>
        <div className="flex items-center gap-4">
          <div 
            className="flex items-center justify-center animate-pulse" 
            style={{ 
              width: '48px', height: '48px', 
              borderRadius: 'var(--radius-lg)', 
              background: 'var(--status-info-bg)',
              border: '1px solid var(--status-info)'
            }}
          >
            <Shield size={28} className="text-info" style={{ color: 'var(--status-info)' }} />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-gradient">FraudSpike</h1>
            <p className="text-secondary text-sm">Real-time Risk Intelligence & Decision Engine</p>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          {isLive ? (
            <span className="badge success flex items-center gap-1 animate-pulse">
              <Activity size={14} /> LIVE
            </span>
          ) : (
            <span className="badge danger">DISCONNECTED</span>
          )}
        </div>
      </header>

      {/* Stats Section */}
      <section className="animate-slide-up" style={{ animationDelay: '100ms' }}>
        <CostCounter stats={stats} />
      </section>

      {/* Main Grid: Table (Left, wider) and Audit Log (Right, narrower) */}
      <section 
        className="grid animate-slide-up" 
        style={{ 
          gridTemplateColumns: '2fr 1fr', 
          gap: '2rem',
          alignItems: 'start',
          animationDelay: '200ms'
        }}
      >
        <PaymentTable payments={payments} />
        <AuditLog logs={auditLogs} />
      </section>
    </div>
  );
}

export default App;

import type { AuditRecord } from '../api';
import { Link, Hash, Database } from 'lucide-react';

interface Props {
  logs: AuditRecord[];
}

export function AuditLog({ logs }: Props) {
  if (logs.length === 0) {
    return (
      <div className="glass-panel flex-col items-center justify-center gap-2" style={{ padding: '2rem', height: '100%' }}>
        <Database size={32} className="text-secondary" />
        <p className="text-muted text-sm">Log chain is empty</p>
      </div>
    );
  }

  return (
    <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', height: '100%', maxHeight: '600px' }}>
      <div className="header flex items-center justify-between" style={{ padding: '1.5rem', marginBottom: 0, borderBottom: '1px solid var(--panel-border)' }}>
        <h3 className="text-lg font-semibold flex items-center gap-2">
          <Link size={20} className="text-secondary" />
          Audit Hash Chain
        </h3>
        <span className="badge neutral text-xs font-mono">{logs.length} blocks</span>
      </div>
      
      <div style={{ padding: '1.5rem', overflowY: 'auto', flex: 1 }} className="flex-col gap-4">
        {logs.map((log, idx) => {
          // If this is the genesis block (no previous hash or 64 zeroes), or we don't have the previous log in our slice
          const prevLog = idx > 0 ? logs[idx - 1] : null;
          
          // Basic integrity check for the UI (just checks if the chain links correctly)
          const isBroken = prevLog && log.previous_log_hash !== prevLog.record_hash;

          return (
            <div key={log.id} className="flex-col animate-slide-up" style={{ animationDelay: `${idx * 30}ms` }}>
              {/* The "Chain" link between blocks */}
              {idx > 0 && (
                <div style={{ display: 'flex', justifyContent: 'center', height: '24px' }}>
                  <div style={{ width: '2px', height: '100%', background: isBroken ? 'var(--status-danger)' : 'var(--panel-border)' }} />
                </div>
              )}
              
              {/* The Block */}
              <div 
                style={{ 
                  background: 'rgba(0,0,0,0.2)', 
                  border: `1px solid ${isBroken ? 'rgba(239, 68, 68, 0.5)' : 'var(--panel-border)'}`,
                  borderRadius: 'var(--radius-sm)',
                  padding: '1rem',
                  position: 'relative'
                }}
              >
                {isBroken && (
                  <div style={{ position: 'absolute', top: '-10px', right: '-10px', background: 'var(--status-danger)', borderRadius: '50%', padding: '4px' }}>
                    <Hash size={12} color="white" />
                  </div>
                )}
                
                <div className="flex justify-between items-center" style={{ marginBottom: '0.5rem' }}>
                  <span className="badge" style={{ background: 'transparent', padding: 0, color: 'var(--text-primary)' }}>
                    {log.record_type}
                  </span>
                  <span className="text-xs text-muted font-mono">{log.tx_id.slice(0, 8)}...</span>
                </div>
                
                <div className="flex-col gap-1 text-xs font-mono">
                  <div className="flex justify-between text-secondary">
                    <span>Prev:</span>
                    <span style={{ color: isBroken ? 'var(--status-danger)' : 'inherit' }} title={log.previous_log_hash}>
                      {log.previous_log_hash === '0'.repeat(64) ? 'GENESIS_BLOCK' : log.previous_log_hash.slice(0, 16) + '...'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Hash:</span>
                    <span className="text-gradient" title={log.record_hash}>
                      {log.record_hash.slice(0, 16)}...
                    </span>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

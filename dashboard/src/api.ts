import { useEffect, useState } from 'react';

export interface PaymentDecision {
  id: number;
  tx_id: string;
  payment_id: string | null;
  timestamp: string;
  amount: number | null;
  action: 'CAPTURE' | 'VERIFY' | 'HOLD';
  p_fraud: number | null;
  reasons: string[];
  shadow_mode: boolean;
}

export interface AuditRecord {
  id: number;
  record_type: string;
  tx_id: string;
  timestamp: string;
  previous_log_hash: string;
  record_hash: string;
}

export interface CostStats {
  period: string;
  total_volume: number;
  fraud_prevented: number;
  false_positives_count: number;
  total_decisions: number;
}

const API_BASE = '/api/v1/dashboard';

export async function fetchPayments(): Promise<PaymentDecision[]> {
  const res = await fetch(`${API_BASE}/payments`);
  if (!res.ok) throw new Error('Failed to fetch payments');
  const data = await res.json();
  return data.payments;
}

export async function fetchAuditLog(): Promise<AuditRecord[]> {
  const res = await fetch(`${API_BASE}/audit`);
  if (!res.ok) throw new Error('Failed to fetch audit log');
  const data = await res.json();
  return data.logs;
}

export async function fetchStats(): Promise<CostStats> {
  const res = await fetch(`${API_BASE}/stats`);
  if (!res.ok) throw new Error('Failed to fetch stats');
  return await res.json();
}

/**
 * Custom hook to listen to the SSE stream.
 * Automatically reconnects on drop.
 * Returns a toggle to manually refetch data when an event occurs.
 */
export function useSSE(endpoint: string = `${API_BASE}/events`) {
  const [lastEventId, setLastEventId] = useState<string | null>(null);

  useEffect(() => {
    let eventSource: EventSource;
    let retryTimeout: ReturnType<typeof setTimeout>;

    const connect = () => {
      eventSource = new EventSource(endpoint);
      
      eventSource.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.tx_id) {
            setLastEventId(data.tx_id + '-' + Date.now()); // Force refresh trigger
          }
        } catch (err) {
          console.error("Failed to parse SSE message", err);
        }
      };

      eventSource.onerror = () => {
        eventSource.close();
        // Reconnect after 3s
        retryTimeout = setTimeout(connect, 3000);
      };
    };

    connect();

    return () => {
      clearTimeout(retryTimeout);
      if (eventSource) eventSource.close();
    };
  }, [endpoint]);

  return lastEventId;
}

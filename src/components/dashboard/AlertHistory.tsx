'use client';

import React, { useEffect, useRef, useState } from 'react';
import { AlertCircle, AlertTriangle, ExternalLink } from 'lucide-react';
import { useROS } from '@/hooks/useROS';
import { TOPICS } from '@/lib/rosTopics';
import type { AlertMessage, AlertSeverity, AlertType } from '@/types/ros';

const MAX_ALERTS = 50;
const GRAFANA_URL = 'http://localhost:3001';

interface StringMessage {
  data: string;
}

function severityClasses(severity: AlertSeverity): string {
  return severity === 'critical'
    ? 'bg-red-600 text-white'
    : 'bg-yellow-500 text-black';
}

function AlertIcon({ type }: { type: AlertType }) {
  const cls = 'w-3 h-3 flex-shrink-0';
  return type === 'COLLISION' || type === 'CONNECTION_LOSS' || type === 'TILT_WARNING' || type === 'GEOFENCE_BREACH'
    ? <AlertCircle className={cls} />
    : <AlertTriangle className={cls} />;
}

function formatTime(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export default function AlertHistory() {
  const [alerts, setAlerts] = useState<AlertMessage[]>([]);
  const listRef = useRef<HTMLDivElement>(null);
  const { subscribe, isConnected } = useROS({ url: 'ws://localhost:9090' });

  useEffect(() => {
    const unsubAlert = subscribe<StringMessage>(
      TOPICS.robotAlerts.path,
      TOPICS.robotAlerts.type,
      (msg) => {
        try {
          const alert: AlertMessage = JSON.parse(msg.data);
          setAlerts(prev => [alert, ...prev].slice(0, MAX_ALERTS));
        } catch (e) {
          console.warn("[AlertHistory] parse failed:", e, "raw:", msg.data);
        }
      }
    );

    const unsubHistory = subscribe<StringMessage>(
      TOPICS.robotAlertsHistory.path,
      TOPICS.robotAlertsHistory.type,
      (msg) => {
        try {
          const history: AlertMessage[] = JSON.parse(msg.data);
          setAlerts(prev => {
            const existingIds = new Set(prev.map(a => a.id));
            const newItems = history.filter(a => !existingIds.has(a.id));
            return [...prev, ...newItems]
              .sort((a, b) => b.timestamp - a.timestamp)
              .slice(0, MAX_ALERTS);
          });
        } catch {
          // ignore malformed messages
        }
      }
    );

    return () => {
      unsubAlert();
      unsubHistory();
    };
  }, [subscribe]);

  return (
    <div className="h-full bg-[#1a1a1a] rounded-sm p-2 border border-[#2a2a2a] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-2 flex-shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-[#00a5ff] text-sm font-semibold">Alert History</span>
          <div
            className={`w-2 h-2 rounded-full ${
              isConnected ? 'bg-green-500 animate-pulse' : 'bg-red-500'
            }`}
          />
          <span className="text-xs text-gray-500">({alerts.length})</span>
        </div>
        <a
          href={GRAFANA_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 text-xs text-gray-400 hover:text-[#00a5ff] transition-colors"
        >
          <ExternalLink className="w-3 h-3" />
          Grafana
        </a>
      </div>

      {/* Alert list */}
      <div ref={listRef} className="flex-1 overflow-y-auto space-y-1 pr-0.5 min-h-0">
        {alerts.length === 0 ? (
          <div className="text-xs text-gray-500 text-center mt-6">No alerts</div>
        ) : (
          alerts.map(alert => (
            <div
              key={alert.id}
              className="bg-[#222222] rounded px-2 py-1.5 border border-[#333333] flex items-start gap-2"
            >
              <span
                className={`text-xs px-1.5 py-0.5 rounded font-semibold flex items-center gap-1 flex-shrink-0 mt-0.5 ${severityClasses(alert.severity)}`}
              >
                <AlertIcon type={alert.alert_type} />
                {alert.severity === 'critical' ? 'CRIT' : 'WARN'}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-xs text-white leading-tight truncate">
                  {alert.message}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">
                  Robot {alert.robot_id} · {formatTime(alert.timestamp)}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

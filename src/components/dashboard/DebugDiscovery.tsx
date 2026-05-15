'use client';

import { useDiscoveredRobots } from '@/hooks/useDiscoveredRobots';

export default function DebugDiscovery() {
  const robotIds = useDiscoveredRobots();

  // Log on every change so you can watch the rediscovery polling
  console.log('[DebugDiscovery] robotIds =', robotIds);

  return (
    <div style={{
      position: 'fixed',
      bottom: 8,
      right: 8,
      padding: '8px 12px',
      background: 'rgba(0, 0, 0, 0.8)',
      color: '#00a5ff',
      fontFamily: 'monospace',
      fontSize: 12,
      borderRadius: 4,
      zIndex: 9999,
      pointerEvents: 'none',
    }}>
      Discovered robots: [{robotIds.join(', ')}]
    </div>
  );
}
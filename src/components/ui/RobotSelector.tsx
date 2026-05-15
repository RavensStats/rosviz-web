'use client';

import React, { useEffect, useRef, useState } from 'react';
import { Cpu, ChevronDown, Check } from 'lucide-react';
import { cn } from '@/lib/utils';

interface RobotSelectorProps {
  robots: number[];
  selectedRobotId: number | null;
  onSelect: (id: number) => void;
  isConnected: boolean;
}

export default function RobotSelector({
  robots,
  selectedRobotId,
  onSelect,
  isConnected,
}: RobotSelectorProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close the dropdown when clicking anywhere outside of it.
  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [open]);

  const hasRobots = robots.length > 0;

  let label: string;
  if (selectedRobotId !== null) {
    label = `Robot ${selectedRobotId}`;
  } else if (!isConnected) {
    label = 'Connecting…';
  } else if (!hasRobots) {
    label = 'No robots';
  } else {
    label = 'Select robot';
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        disabled={!hasRobots}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'h-8 px-3 flex items-center gap-2 rounded-md text-sm font-medium transition-colors',
          'text-gray-400 hover:text-white hover:bg-[#2a2a2a]',
          'disabled:opacity-50 disabled:pointer-events-none',
          open && 'bg-[#2a2a2a] text-white'
        )}
      >
        <Cpu className="w-4 h-4" />
        <span>{label}</span>
        <ChevronDown
          className={cn('w-3 h-3 transition-transform', open && 'rotate-180')}
        />
      </button>

      {open && hasRobots && (
        <div className="absolute left-0 top-full mt-1 z-50 min-w-[10rem] py-1 bg-[#232323] border border-[#333333] rounded-md shadow-lg">
          {robots.map((id) => {
            const isSelected = id === selectedRobotId;
            return (
              <button
                key={id}
                type="button"
                onClick={() => {
                  onSelect(id);
                  setOpen(false);
                }}
                className={cn(
                  'w-full px-3 py-1.5 flex items-center justify-between gap-2 text-sm text-left transition-colors',
                  'text-gray-400 hover:text-white hover:bg-[#2a2a2a]',
                  isSelected && 'text-white'
                )}
              >
                <span className="flex items-center gap-2">
                  <Cpu className="w-4 h-4" />
                  Robot {id}
                </span>
                {isSelected && <Check className="w-4 h-4 text-[#00a5ff]" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
'use client';

import React, { useEffect, useState } from 'react';
import rosbridge from '@/lib/rosbridge';

const WORLD_SIZE = 4;
const PADDING = 20;

{/* Important: These arent the actual robots, but since the namespace matter is still WIP/TODO these are just placeholders for now. This will DEFINITELY need to get replaced later though! */}
const ROBOTS = [
  { id: 'tb3_0', name: 'TurtleBot 0', color: '#ff0000', label: 'TB3 0', online: true, battery_percentage: 87 },
  { id: 'tb3_1', name: 'TurtleBot 1', color: '#0000FF', label: 'TB3 1', online: true,  battery_percentage: 62 },
  { id: 'tb3_2', name: 'TurtleBot 2', color: '#10df10', label: 'TB3 2', online: false, battery_percentage: 12 },
];

{/* Hardcoded to match our map at the moment. TODO, might be better to have a 3D view with a seperate camera/render */}
const OBSTACLES = [
  { type: 'box', x: 1, y: 1, w: 0.5, h: 0.5, color: '#3b82f6' },
  { type: 'cylinder', x: -1, y: 0.5, r: 0.3, color: '#ef4444' },
];

const SPAWN_POSITIONS: Record<string, { x: number; y: number }> = {
  tb3_0: { x:  0, y:  0 },
  tb3_1: { x: -1, y: -1 },
  tb3_2: { x:  1, y: -1 },
};

const WALLS = [
  { x1: -2, y1: -2, x2:  2, y2: -2 },
  { x1:  2, y1: -2, x2:  2, y2:  2 },
  { x1:  2, y1:  2, x2: -2, y2:  2 },
  { x1: -2, y1:  2, x2: -2, y2: -2 },
];

interface RobotPosition {
  x: number;
  y: number;
  yaw: number;
}

interface OdometryMessage {
  pose: {
    pose: {
      position: { x: number; y: number; z: number };
      orientation: { x: number; y: number; z: number; w: number };
    };
  };
}

function worldToSVG(wx: number, wy: number, svgSize: number): [number, number] {
  const scale = (svgSize - PADDING * 2) / WORLD_SIZE;
  const sx = PADDING + (wx + WORLD_SIZE / 2) * scale;
  const sy = PADDING + (WORLD_SIZE / 2 - wy) * scale;
  return [sx, sy];
}

function yawFromQuaternion(q: { x: number; y: number; z: number; w: number }): number {
  return Math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z));
}

export default function FleetMap() {
  const SVG_SIZE = 300;
  const scale = (SVG_SIZE - PADDING * 2) / WORLD_SIZE;

  const [positions, setPositions] = useState<Record<string, RobotPosition>>({
    tb3_0: { x: 0,  y:  0,  yaw: 0 },
    tb3_1: { x: -1, y: -1,  yaw: Math.PI / 2 },
    tb3_2: { x: 1,  y: -1,  yaw: -Math.PI / 2 },
  });

  useEffect(() => {
    const unsubs: (() => void)[] = [];

    const connect = async () => {
      if (!rosbridge.isConnected()) {
        await rosbridge.connect('ws://localhost:9090');
      }

      for (const robot of ROBOTS) {
        const topic = `/${robot.id}/odom`;
        const unsub = rosbridge.subscribe<OdometryMessage>(
          topic,
          'nav_msgs/Odometry',
          (msg) => {
            const pos = msg.pose.pose.position;
            const ori = msg.pose.pose.orientation;
            const spawn = SPAWN_POSITIONS[robot.id];
            console.log(`[${robot.id}] odom:`, pos.x, pos.y, '-> world:', spawn.x + pos.x, spawn.y + pos.y);
            setPositions(prev => ({
              ...prev,
              [robot.id]: {
                x: pos.x,
                y: pos.y,
                yaw: yawFromQuaternion(ori),
              }
            }));
          }
        );
        unsubs.push(unsub);
      }
    };

    connect();
    return () => unsubs.forEach(u => u());
  }, []);

  return (
    <div className="h-full bg-[#1e1e1e] rounded-sm border border-[#333333] flex flex-col p-2">
      <span className="text-[#00a5ff] text-sm font-semibold mb-2 shrink-0">2D Fleet Map</span>
      <div className="flex-1 flex items-center justify-center min-h-0">
            <svg
                viewBox={`0 0 ${SVG_SIZE} ${SVG_SIZE}`}
                className="w-full h-full"
            >
            {/* Background */}
          <rect x={0} y={0} width={SVG_SIZE} height={SVG_SIZE} fill="#111111" />

          {/* Grid lines */}
          {[-2, -1, 0, 1, 2].map(v => {
            const [x1, y1] = worldToSVG(v, -2, SVG_SIZE);
            const [x2, y2] = worldToSVG(v,  2, SVG_SIZE);
            const [x3, y3] = worldToSVG(-2, v, SVG_SIZE);
            const [x4, y4] = worldToSVG( 2, v, SVG_SIZE);
            return (
              <g key={v}>
                <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#222" strokeWidth={0.5} />
                <line x1={x3} y1={y3} x2={x4} y2={y4} stroke="#222" strokeWidth={0.5} />
              </g>
            );
          })}

          {/* Walls */}
          {WALLS.map((w, i) => {
            const [x1, y1] = worldToSVG(w.x1, w.y1, SVG_SIZE);
            const [x2, y2] = worldToSVG(w.x2, w.y2, SVG_SIZE);
            return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#8b6343" strokeWidth={3} />;
          })}

          {/* Obstacles */}
          {OBSTACLES.map((obs, i) => {
            if (obs.type === 'box') {
              const [cx, cy] = worldToSVG(obs.x, obs.y, SVG_SIZE);
              const sw = (obs.w!) * scale;
              const sh = (obs.h!) * scale;
              return (
                <rect
                  key={i}
                  x={cx - sw / 2}
                  y={cy - sh / 2}
                  width={sw}
                  height={sh}
                  fill={obs.color}
                  opacity={0.7}
                />
              );
            } else {
              const [cx, cy] = worldToSVG(obs.x, obs.y, SVG_SIZE);
              const sr = (obs.r!) * scale;
              return <circle key={i} cx={cx} cy={cy} r={sr} fill={obs.color} opacity={0.7} />;
            }
          })}

          {/* Robots */}
          {ROBOTS.map(robot => {
            const pos = positions[robot.id];
            const [cx, cy] = worldToSVG(pos.x, pos.y, SVG_SIZE);

            return (
              <g key={robot.id}>
                <circle cx={cx} cy={cy} r={6} fill={robot.color} opacity={0.9} />
                <circle cx={cx} cy={cy} r={6} fill="none" stroke="#ffffff" strokeWidth={1} opacity={0.3} />
                <text
                  x={cx}
                  y={cy - 10}
                  textAnchor="middle"
                  fill={robot.color}
                  fontSize={8}
                  fontFamily="monospace"
                >
                  {robot.label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
import Link from 'next/link';
import VideoStream from '@/components/dashboard/VideoStream';
import { Grid, Eye } from 'lucide-react';

{/* Important: These arent the actual robots, but since the namespace matter is still WIP/TODO these are just placeholders for now. This will DEFINITELY need to get replaced later though! */}
const ROBOTS = [
  { id: 'tb3_0', online: true,  battery_percentage: 87 },
  { id: 'tb3_1', online: true,  battery_percentage: 62 },
  { id: 'tb3_2', online: false, battery_percentage: 12 },
];

{/* These values will also be computed dynamically later! */}
const onlineCount  = ROBOTS.filter(r => r.online).length;
const offlineCount = ROBOTS.filter(r => !r.online).length;

export default function FleetOverview() {
  return (
    <div className="h-screen w-screen overflow-hidden bg-[#1a1a1a]">
      {/* Top bar with fleet overview/common buttons */}
      <div className="w-full h-12 bg-[#232323] flex items-center px-2 gap-1 border-b border-[#333333]">
        <div className="flex items-center gap-1">
          <Link href="/">
            <button className="h-8 px-3 text-sm flex items-center gap-2 rounded text-white bg-[#2a2a2a]">
              <Grid className="w-4 h-4" />
              Fleet Overview
            </button>
          </Link>
          <Link href="/common">
            <button className="h-8 px-3 text-sm flex items-center gap-2 rounded text-gray-400 hover:text-white hover:bg-[#2a2a2a] transition-colors">
              <Eye className="w-4 h-4" />
              Common
            </button>
          </Link>
        </div>
        <div className="flex-1" />
        <span className="text-gray-400 text-sm">TurtleBot3 Control System</span>
      </div>

      {/* Main Page */}
      <div className="h-[calc(100vh-3rem)] flex">
        {/* Sidebar with fleet info */}
        <div className="w-64 h-full bg-[#1e1e1e] border-r border-[#2a2a2a] p-4 flex flex-col gap-3">
          <span className="text-[#00a5ff] text-base font-semibold">Overview</span>
          <div className="border-t border-[#2a2a2a] pt-3 flex flex-col gap-2">
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">Total Robots</span>
              <span className="text-white font-bold">{ROBOTS.length}</span>
            </div>
            <div className="border-t border-[#2a2a2a]" />
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">Online</span>
              <span className="text-green-500 font-bold">{onlineCount}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-gray-400">Offline</span>
              <span className="text-red-500 font-bold">{offlineCount}</span>
            </div>
          </div>
        </div>

        {/* Robot Grid */}
        <div className="flex-1 p-6 grid grid-cols-3 gap-4 content-start">
          {ROBOTS.map((robot) => (
            <Link
              key={robot.id}
              href={`/robot/${robot.id}`}
              className="bg-[#2a2a2a] border border-[#333333] rounded-lg overflow-hidden hover:border-[#00a5ff] transition-colors duration-150 flex flex-col p-3 gap-2"
            >
              {/* Top section: camera + info side by side */}
              <div className="flex gap-3">
                {/* Camera Feed */}
                <div className="flex-1 aspect-video rounded overflow-hidden">
                  {robot.online
                    ? <VideoStream topic="/camera/image_raw" />
                    : <div className="w-full h-full bg-[#222222] flex items-center justify-center">
                        <span className="text-gray-700 text-xs">Offline</span>
                      </div>
                  }
                </div>

                {/* Info */}
                <div className="flex flex-col justify-start gap-1 w-28">
                  <div className="flex items-baseline gap-1">
                    <div className={`w-2 h-2 rounded-full flex-shrink-0 ${robot.online ? 'bg-green-500' : 'bg-red-500'}`} />
                    <span className={`text-m font-medium ${robot.online ? 'text-green-500' : 'text-red-500'}`}>
                      {robot.online ? 'Online' : 'Offline'}
                    </span>
                  </div>
                  <span className="text-white text-sm font-semibold">{robot.id}</span>
                </div>
              </div>

              {/* Battery Bar */}
              <div className="flex items-center gap-2">
                <div className="flex-1 h-1.5 bg-[#1a1a1a] rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{
                      width: `${robot.battery_percentage}%`,
                      backgroundColor: robot.battery_percentage > 20 ? '#facc15' : '#ef4444'
                    }}
                  />
                </div>
                <span className={`text-xs font-bold flex-shrink-0 ${robot.battery_percentage > 20 ? 'text-yellow-400' : 'text-red-500'}`}>
                  {robot.battery_percentage}%
                </span>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
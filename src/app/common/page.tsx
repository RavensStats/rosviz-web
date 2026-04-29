import Link from 'next/link';
import { Grid, Eye } from 'lucide-react';

const ROBOTS = ['tb3_0', 'tb3_1', 'tb3_2'];

export default function FleetOverview() {
  return (
    <div className="h-screen w-screen overflow-hidden bg-[#1a1a1a]">
      
      {/* top bar with links to fleet overview and common tab */}
      <div className="w-full h-12 bg-[#232323] flex items-center px-2 gap-1 border-b border-[#333333]">
        <div className="flex items-center gap-1">
          <Link href="/">
            <button className="h-8 px-3 text-sm flex items-center gap-2 rounded text-gray-400 hover:text-white hover:bg-[#2a2a2a] transition-colors">
              <Grid className="w-4 h-4" />
              Fleet Overview
            </button>
          </Link>
          <Link href="/common">
            <button className="h-8 px-3 text-sm flex items-center gap-2 rounded text-white bg-[#2a2a2a]">
              <Eye className="w-4 h-4" />
              Common
            </button>
          </Link>
        </div>
        <div className="flex-1" />
        <span className="text-gray-400 text-sm">TurtleBot3 Control System</span>
      </div>

      {/* grid with fleet overview */}
      <span className="text-gray-400 text-sm">TODO: Common Tab</span>
    </div>
  );
}
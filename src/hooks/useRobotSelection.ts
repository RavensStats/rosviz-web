'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import rosbridge from '@/lib/rosbridge';

const STORAGE_KEY = 'rosviz.selectedRobotId';

const MUX_SELECT_SERVICE_TYPE = 'topic_tools_interfaces/srv/MuxSelect';
// const MUX_SELECT_SERVICE_TYPE = 'topic_tools/MuxSelect';  // older fallback

interface MuxConfig {
  /** Mux service path, e.g. '/mux_scan_points/select' */
  service: string;
  /** Function returning the input topic for a given robot id */
  inputForRobot: (id: number) => string;
}

const MUXES: MuxConfig[] = [
  {
    service: '/mux_scan_points/select',
    inputForRobot: (id) => `/tb3_${id}/scan/points`,
  },
  {
    service: '/mux_camera_image/select',
    inputForRobot: (id) => `/tb3_${id}/camera/image_raw/compressed`,
  },
  {
    service: '/mux_camera_depth/select',
    inputForRobot: (id) => `/tb3_${id}/camera/depth/image_rect_raw/compressed`,
  },
];

function readPersistedSelection(): number | null {
  if (typeof window === 'undefined') return null;
  const raw = window.sessionStorage.getItem(STORAGE_KEY);
  if (raw === null) return null;
  const parsed = Number(raw);
  return Number.isInteger(parsed) ? parsed : null;
}

function persistSelection(id: number | null) {
  if (typeof window === 'undefined') return;
  if (id === null) {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } else {
    window.sessionStorage.setItem(STORAGE_KEY, String(id));
  }
}

/**
 * Single source of truth for which robot the individual view is focused on.
 *
 * `selectRobot(id)` does two things atomically:
 *   1. Updates local state (so UI follows).
 *   2. Calls every mux's /select service to route /selected/* to that robot.
 *
 * Selection is persisted to sessionStorage so a page refresh doesn't reset it.
 */
export function useRobotSelection() {
  // Keep SSR and first client render deterministic (null), then hydrate from storage.
  const [selectedRobotId, setSelectedRobotId] = useState<number | null>(null);  

  // Prevent concurrent/racy robot switches.
  const requestIdRef = useRef(0);

  // Expose loading state to the UI.
  const [isSwitchingRobot, setIsSwitchingRobot] = useState(false);

  useEffect(() => {
    setSelectedRobotId(readPersistedSelection());
  }, []);

  useEffect(() => {    
    persistSelection(selectedRobotId);
  }, [selectedRobotId]);

/**
   * Atomically switch all muxes to a robot.
   *
   * Guarantees:
   *   - Prevents stale async requests from overwriting newer selections.
   *   - Updates UI state only if ALL muxes succeeded.
   *   - Exposes loading state for UI disabling/spinners.
   *
   * Returns:
   *   true  -> all muxes switched successfully
   *   false -> at least one mux failed OR request became stale
   */
  const selectRobot = useCallback(async (id: number): Promise<boolean> => {
    // Generate monotonically increasing request id.
    // Newer requests invalidate older ones.
    const requestId = ++requestIdRef.current;

    setIsSwitchingRobot(true);

    try {
      const results = await Promise.allSettled(
        MUXES.map((mux) =>
          rosbridge.callService(
            mux.service,
            MUX_SELECT_SERVICE_TYPE,
            { topic: mux.inputForRobot(id) },
            3000
          )
        )
      );

      // Ignore stale/outdated async completions.
      if (requestId !== requestIdRef.current) {
        console.warn(
          `[useRobotSelection] Ignoring stale robot switch request for robot ${id}`
        );
        return false;
      }

      const failures = results
        .map((result, index) =>
          result.status === 'rejected'
            ? {
                mux: MUXES[index].service,
                reason: result.reason,
              }
            : null
        )
        .filter(
          (failure): failure is { mux: string; reason: unknown } =>
            failure !== null
        );

      // Do NOT update frontend selection state if mux state is inconsistent.
      if (failures.length > 0) {
        console.warn(
          `[useRobotSelection] ${failures.length}/${MUXES.length} mux switches failed`,
          failures
        );

        return false;
      }

      // Only commit state once all muxes succeeded.
      setSelectedRobotId(id);

      console.log(
        `[useRobotSelection] Successfully switched to robot ${id}`
      );

      return true;
    } catch (error) {
      console.error(
        `[useRobotSelection] Unexpected robot switch error`,
        error
      );

      return false;
    } finally {
      // Only clear loading state if this request is still the newest active request.
      if (requestId === requestIdRef.current) {
        setIsSwitchingRobot(false);
      }
    }
  }, []);

  return {
    selectedRobotId,
    isSwitchingRobot,
    selectRobot,
  };
}

export default useRobotSelection;

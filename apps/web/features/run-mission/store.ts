import { create } from "zustand";

interface MissionStore {
  openMissionId: string | null;
  openMission: (id: string) => void;
  closeMission: () => void;
}

/**
 * Holds the single-slide-over selection. Lifted out of React state so the
 * top-bar (which fires submissions) and the sidebar rows (which open
 * existing missions) can share one truth without prop-drilling.
 *
 * Spec 11 expands this to a stack-of-lanes selection model; for now one id
 * is enough.
 */
export const useMissionStore = create<MissionStore>((set) => ({
  openMissionId: null,
  openMission: (id) => set({ openMissionId: id }),
  closeMission: () => set({ openMissionId: null }),
}));

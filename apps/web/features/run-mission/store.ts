import { create } from "zustand";

interface MissionStore {
  openMissionId: string | null;
  openMission: (id: string) => void;
  closeMission: () => void;
  multiUrlOpen: boolean;
  openMultiUrl: () => void;
  closeMultiUrl: () => void;
}

/**
 * Holds the single-slide-over selection plus the multi-URL slide-over's
 * open state. Lifted out of React state so the top-bar (which fires
 * single-URL submissions), the sidebar rows (which open existing
 * missions), and the command palette (which opens the multi-URL
 * composer) can share one truth without prop-drilling.
 *
 * Spec 11 expands `openMissionId` to a stack-of-lanes selection model;
 * for now one id is enough.
 */
export const useMissionStore = create<MissionStore>((set) => ({
  openMissionId: null,
  openMission: (id) => set({ openMissionId: id }),
  closeMission: () => set({ openMissionId: null }),
  multiUrlOpen: false,
  openMultiUrl: () => set({ multiUrlOpen: true }),
  closeMultiUrl: () => set({ multiUrlOpen: false }),
}));

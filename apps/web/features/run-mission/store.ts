import { create } from "zustand";

interface MissionStore {
  multiUrlOpen: boolean;
  openMultiUrl: () => void;
  closeMultiUrl: () => void;
  descriptionOpen: boolean;
  openDescription: () => void;
  closeDescription: () => void;
}

/**
 * Holds the composer slide-overs' open state. Mission selection lives in
 * the URL (`/missions/[id]`) since the route is the source of truth and
 * survives navigation; the previous `openMissionId`/`openMission` keys
 * lost every piece of mission state on close (elapsed counter, lane
 * focus, reasoning toggle) and are gone.
 */
export const useMissionStore = create<MissionStore>((set) => ({
  multiUrlOpen: false,
  openMultiUrl: () => set({ multiUrlOpen: true }),
  closeMultiUrl: () => set({ multiUrlOpen: false }),
  descriptionOpen: false,
  openDescription: () => set({ descriptionOpen: true }),
  closeDescription: () => set({ descriptionOpen: false }),
}));

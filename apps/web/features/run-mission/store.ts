import { create } from "zustand";

interface MissionStore {
  openMissionId: string | null;
  openMission: (id: string) => void;
  closeMission: () => void;
  multiUrlOpen: boolean;
  openMultiUrl: () => void;
  closeMultiUrl: () => void;
  descriptionOpen: boolean;
  openDescription: () => void;
  closeDescription: () => void;
}

/**
 * Holds the single-slide-over selection plus the composer slide-overs'
 * open state. Lifted out of React state so the top-bar (which fires
 * single-URL submissions), the sidebar rows (which open existing
 * missions), and the command palette (which opens the multi-URL or
 * description-mode composer) can share one truth without prop-drilling.
 *
 * Spec 11 expanded `openMissionId` to support the multi-lane selection
 * model; Spec 12 adds the description-mode composer slide-over.
 */
export const useMissionStore = create<MissionStore>((set) => ({
  openMissionId: null,
  openMission: (id) => set({ openMissionId: id }),
  closeMission: () => set({ openMissionId: null }),
  multiUrlOpen: false,
  openMultiUrl: () => set({ multiUrlOpen: true }),
  closeMultiUrl: () => set({ multiUrlOpen: false }),
  descriptionOpen: false,
  openDescription: () => set({ descriptionOpen: true }),
  closeDescription: () => set({ descriptionOpen: false }),
}));

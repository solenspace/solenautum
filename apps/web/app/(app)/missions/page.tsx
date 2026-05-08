import { EmptyState } from "./empty-state";
import { WelcomeState } from "./welcome-state";

/**
 * `/missions` — landing page when no specific mission is selected. The
 * route-based detail (`/missions/[id]`) renders in this same outlet
 * once a mission is opened, so this page is the empty/welcome surface
 * the user sees on first visit and after closing a mission.
 */
export default function MissionsPage() {
  return (
    <div className="flex h-full flex-col">
      <EmptyState />
      <WelcomeState />
    </div>
  );
}

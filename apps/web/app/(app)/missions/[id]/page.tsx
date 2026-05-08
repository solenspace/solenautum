import { MissionView } from "@/widgets/mission-view";

/**
 * Per-mission detail route. URL is the source of truth: `/missions/{id}`
 * survives navigation, refresh, and direct link sharing — replaces the
 * prior slide-over pattern, which lost every piece of mission state on
 * close (elapsed counter, lane focus, reasoning toggle).
 *
 * `params` is a Promise in Next.js 16; this is a server component so it
 * awaits the param and hands the id to the client `<MissionView>`.
 */
export default async function MissionDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <MissionView missionId={id} />;
}

import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { KeyboardShortcuts } from "@/shared/keyboard";
import { CommandPalette } from "@/widgets/command-palette";
import { DescriptionModeSlideover } from "@/widgets/description-mode-slideover";
import { MissionSidebar } from "@/widgets/mission-sidebar";
import { MultiUrlSlideover } from "@/widgets/multi-url-slideover";
import { TopBar } from "@/widgets/top-bar";

/**
 * Authenticated app shell. The route group `(app)` doesn't affect the URL —
 * it groups every signed-in surface (today: `/missions`) under one layout
 * that owns the top bar, sidebar, command palette, and global shortcuts.
 *
 * `auth()` is awaited at the server-component layer; unauthenticated users
 * never reach the client bundle. The placeholder page from Spec 04 is
 * deleted in this commit; the `(app)/missions/page.tsx` resolves to the
 * same `/missions` URL.
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const { userId } = await auth();
  if (!userId) redirect("/sign-in");

  // shadcn's `<Sidebar>` is `fixed inset-y-0 z-10` from the viewport top;
  // the documented pattern is `<MissionSidebar /><SidebarInset>` so the
  // inset gets the sidebar-aware width offset and the topbar lives next
  // to (not under) the sidebar. Wrapping `<TopBar />` in a manual flex
  // column put it at viewport top, where the sidebar's z-10 sat on top
  // of the brand wordmark and the URL input's left edge.
  return (
    <SidebarProvider>
      <MissionSidebar />
      <SidebarInset className="flex min-h-dvh flex-col overflow-hidden bg-background text-foreground">
        <TopBar />
        <div className="flex-1 overflow-auto">{children}</div>
      </SidebarInset>
      <CommandPalette />
      <MultiUrlSlideover />
      <DescriptionModeSlideover />
      <KeyboardShortcuts />
    </SidebarProvider>
  );
}

import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

import { SidebarProvider } from "@/components/ui/sidebar";
import { KeyboardShortcuts } from "@/shared/keyboard";
import { CommandPalette } from "@/widgets/command-palette";
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

  return (
    <SidebarProvider>
      <div className="flex min-h-dvh w-full flex-col bg-background text-foreground">
        <TopBar />
        <div className="flex flex-1 overflow-hidden">
          <MissionSidebar />
          <main className="flex-1 overflow-auto">{children}</main>
        </div>
        <CommandPalette />
        <MultiUrlSlideover />
        <KeyboardShortcuts />
      </div>
    </SidebarProvider>
  );
}

import { redirect } from "next/navigation";

// Root has no content of its own; the app entry is `/missions`. The
// Clerk middleware bounces unauthenticated users to `/sign-in` from there.
export default function Home() {
  redirect("/missions");
}
